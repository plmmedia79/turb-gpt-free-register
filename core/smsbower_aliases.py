"""Two sequential signup aliases share one SMSBower activation, including TOTP."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from config import email as cfg
from core import smsbower_client as client

logger = logging.getLogger(__name__)
MAX_ALIASES = 2
MAX_CODES = 5
MIN_REUSE_SECONDS = 225
ACTIVATION_SECONDS = 18 * 60


@dataclass
class Group:
    account: client.SMSBowerAccount
    key: tuple[str, str, object] = field(repr=False)
    aliases: list[str] = field(default_factory=list)
    active: str | None = None
    closed: bool = False
    successful: bool = False
    retire: bool = False
    lock: object = field(default_factory=threading.RLock, repr=False)


@dataclass
class Alias:
    email: str
    group: Group
    done: bool = False
    pending: int = 0
    failed: bool = False


_CV = threading.Condition(threading.RLock())
_GROUPS: list[Group] = []
_CONTEXT: dict[str, Alias] = {}
_BUYING: set[tuple[str, str, object]] = set()
_LOCAL = threading.local()


def _remaining(group):
    return group.account.created_at + ACTIVATION_SECONDS - time.monotonic()


def _check_stop():
    from core.registration_service import check_stop_requested
    check_stop_requested()


def _notify():
    with _CV:
        _CV.notify_all()


def _close(group):
    # Callers hold group.lock, never _CV, across provider I/O.
    if group.closed:
        return
    group.closed = True
    with _CV:
        if group in _GROUPS:
            _GROUPS.remove(group)
        for email in group.aliases:
            _CONTEXT.pop(email.lower(), None)
        _CV.notify_all()
    try:
        client._release_activation(group.account, status='success' if group.successful else 'failed')
    except client.SMSBowerError:
        logger.warning('[SMSBower] Không xác nhận được đóng activation; bỏ khỏi nhóm tái sử dụng')


def _settle(lease):
    group = lease.group
    if group.closed or group.active != lease.email or not lease.done or lease.pending:
        return
    if group.retire or lease.failed or len(group.aliases) >= MAX_ALIASES or len(group.account.used_codes) > MAX_CODES - 2 or _remaining(group) < MIN_REUSE_SECONDS:
        _close(group)
    else:
        group.active = None
        _notify()


@contextmanager
def group_scope():
    """One executor task owns up to two jobs; other tasks own separate rentals."""
    previous = getattr(_LOCAL, 'owner', None)
    owner = object()
    _LOCAL.owner = owner
    try:
        yield
    finally:
        _LOCAL.owner = previous
        with _CV:
            groups = [g for g in _GROUPS if g.key[2] is owner]
        for group in groups:
            with group.lock:
                group.retire = True
                if group.active is None:
                    _close(group)
                elif group.active in _CONTEXT:
                    _settle(_CONTEXT[group.active])


@contextmanager
def registration_scope():
    previous = getattr(_LOCAL, 'leases', None)
    leases = []
    _LOCAL.leases = leases
    outcome = {'success': False}
    try:
        yield outcome
    finally:
        _LOCAL.leases = previous
        for lease in leases:
            with lease.group.lock:
                lease.done = True
                lease.failed = lease.failed or not outcome['success']
                lease.group.successful |= bool(outcome['success'])
                _settle(lease)


def pick_account():
    # Other workflows (e.g. changing an existing account's email) keep their
    # independent activation; they do not own a registration completion scope.
    leases = getattr(_LOCAL, 'leases', None)
    if leases is None:
        return client.pick_account()
    key = (str(cfg.SMSBOWER_API_KEY or '').strip(), str(cfg.SMSBOWER_DOMAIN).strip().lower(), getattr(_LOCAL, 'owner', None) or threading.current_thread())
    last_wait_log = 0.0
    while True:
        _check_stop()
        group = None
        expired = None
        buy = False
        with _CV:
            candidates = [g for g in _GROUPS if g.key == key and not g.closed]
            for candidate in candidates:
                if _remaining(candidate) <= 0:
                    expired = candidate
                    break
                if candidate.active is None:
                    group = candidate
                    # Reserve before releasing the condition lock.
                    group.active = '__reserving__'
                    break
            if group is None and expired is None:
                if candidates or key in _BUYING:
                    if time.monotonic() - last_wait_log >= 15:
                        logger.info('[SMSBower] Nhóm này đang chờ tag trước/TOTP; các nhóm khác vẫn chạy song song')
                        last_wait_log = time.monotonic()
                    _CV.wait(timeout=.5)
                    continue
                _BUYING.add(key)
                buy = True
        if expired is not None:
            with expired.lock:
                _close(expired)
            continue
        if buy:
            try:
                account = client.pick_account(api_key=key[0], domain=key[1])
                group = Group(account, key, active='__reserving__')
                with _CV:
                    _GROUPS.append(group)
            finally:
                with _CV:
                    _BUYING.discard(key)
                    _CV.notify_all()
        with group.lock:
            if group.closed:
                continue
            if _remaining(group) < MIN_REUSE_SECONDS or len(group.account.used_codes) > MAX_CODES - 2:
                _close(group)
                continue
            try:
                # Retire the previous code before handing the next alias to a
                # browser, so a new OTP can arrive immediately after submission.
                if group.account.needs_next_code:
                    client._set_status(group.account, 5)
                    group.account.needs_next_code = False
                local, domain = group.account.email.rsplit('@', 1)
                email = f'{local}+{secrets.token_hex(5)}@{domain}'
                lease = Alias(email, group)
                group.aliases.append(email)
                group.active = email
                with _CV:
                    _CONTEXT[email.lower()] = lease
                leases.append(lease)
                logger.info('[SMSBower] Alias %s/%s, đã nhận %s/%s OTP', len(group.aliases), MAX_ALIASES, len(group.account.used_codes), MAX_CODES)
                return lease
            except Exception:
                _close(group)
                raise


def get_account_context(email):
    with _CV:
        return _CONTEXT.get(str(email).strip().lower()) or client.get_account_context(email)


def fetch_latest_otp(email, **kwargs):
    lease = get_account_context(email)
    if not isinstance(lease, Alias):
        return client.fetch_latest_otp(email, **kwargs)
    group = lease.group
    with group.lock:
        if group.closed or group.active != lease.email or (lease.done and not lease.pending):
            raise client.SMSBowerError('SMSBower: lượt alias này đã kết thúc')
        if len(group.account.used_codes) >= MAX_CODES:
            raise client.SMSBowerError('SMSBower: đã dùng hết 5 lượt OTP của activation')
        try:
            return client._fetch_account_otp(group.account, **kwargs)
        except client.SMSBowerError:
            # Unknown/late replies cannot safely be assigned to another alias.
            lease.failed = True
            raise


def release_account(email, status='available', note=None):
    lease = get_account_context(email)
    if not isinstance(lease, Alias):
        return client.release_account(email, status=status, note=note)
    with lease.group.lock:
        if lease.group.closed or lease.group.active != lease.email or lease.done:
            return
        # Driver failure cleanup may be followed by registration-scope cleanup.
        # Keep the activation fenced until the whole scope and TOTP finish.
        lease.failed = True


def track_future(email, future):
    lease = get_account_context(email)
    if not isinstance(lease, Alias):
        return
    with lease.group.lock:
        if lease.group.closed or lease.group.active != lease.email or lease.done:
            return
        lease.pending += 1
    def completed(_future):
        with lease.group.lock:
            lease.pending -= 1
            try:
                result = _future.result()
                if not isinstance(result, dict) or not result.get('ok'):
                    lease.failed = True
            except Exception:
                lease.failed = True
            _settle(lease)
    future.add_done_callback(completed)
