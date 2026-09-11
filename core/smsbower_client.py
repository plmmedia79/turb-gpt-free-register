"""SMSBower temporary mail API (https://smsbower.app/api/?page=mails)."""
from __future__ import annotations

import re
import time
import threading
from dataclasses import dataclass, field

import requests

from config import email as _email_cfg

BASE_URL = "https://smsbower.page/api/mail"
REQUEST_TIMEOUT = 20


class SMSBowerError(RuntimeError):
    pass


@dataclass
class SMSBowerAccount:
    email: str
    mail_id: str
    api_key: str = field(repr=False)
    created_at: float = field(default_factory=time.monotonic)
    used_codes: set[str] = field(default_factory=set, repr=False)
    needs_next_code: bool = False
    received_code: bool = False


_CONTEXT_CACHE: dict[str, SMSBowerAccount] = {}
_CONTEXT_LOCK = threading.RLock()


def _get(action: str, api_key: str, **params) -> dict:
    # Never expose exception URLs or response bodies: api_key is a query parameter.
    try:
        response = requests.get(
            f"{BASE_URL}/{action}",
            params={"api_key": api_key, **params},
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise SMSBowerError(f"SMSBower {action}: HTTP {response.status_code}")
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise SMSBowerError(f"SMSBower {action}: không kết nối được hoặc phản hồi không hợp lệ") from None
    if not isinstance(payload, dict):
        raise SMSBowerError(f"SMSBower {action}: phản hồi không hợp lệ")
    return payload


def _success(payload: dict) -> bool:
    return str(payload.get("status")) == "1"


def _fail(payload: dict, action: str) -> None:
    message = str(payload.get("error") or payload.get("message") or "").lower()
    for match, detail in (
        ("no mails", "hết email khả dụng"),
        ("insufficient balance", "số dư không đủ"),
        ("key", "API key không hợp lệ"),
        ("cancel", "email đã bị hủy"),
        ("maximum", "đã hết lượt nhận mã"),
        ("no activation", "email đã hết hạn"),
    ):
        if match in message:
            raise SMSBowerError(f"SMSBower {action}: {detail}")
    raise SMSBowerError(f"SMSBower {action}: yêu cầu bị từ chối")


def pick_account(*, api_key=None, domain=None) -> SMSBowerAccount:
    key = str((getattr(_email_cfg, "SMSBOWER_API_KEY", "") if api_key is None else api_key) or "").strip()
    if not key:
        raise SMSBowerError("Hãy nhập SMSBower API Key tại Cấu hình → Email / Mã xác minh.")
    domain = str((getattr(_email_cfg, "SMSBOWER_DOMAIN", "gmail.com") if domain is None else domain) or "").strip().lower()
    if domain not in ("gmail.com", "icloud.com"):
        raise SMSBowerError("SMSBower: hãy chọn Gmail hoặc iCloud")
    payload = _get("getActivation", key, service="dr", domain=domain)
    if not _success(payload):
        _fail(payload, "getActivation")
    email = str(payload.get("mail") or "").strip()
    mail_id = payload.get("mailId")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+", email) or isinstance(mail_id, bool) or not isinstance(mail_id, (str, int)) or not str(mail_id).strip():
        raise SMSBowerError("SMSBower: phản hồi thiếu email hoặc mailId")
    account = SMSBowerAccount(email, str(mail_id), key)
    with _CONTEXT_LOCK:
        _CONTEXT_CACHE[email.lower()] = account
    return account


def get_account_context(email: str) -> SMSBowerAccount | None:
    with _CONTEXT_LOCK:
        return _CONTEXT_CACHE.get(str(email).strip().lower())


def _set_status(account: SMSBowerAccount, status: int) -> None:
    payload = _get("setStatus", account.api_key, id=account.mail_id, status=status)
    if not _success(payload):
        _fail(payload, "setStatus")


def fetch_latest_otp(email: str, after_ts=None, max_wait=None, poll_interval=None, settle_seconds=None) -> str:
    # This API has no timestamps. Activation identity and served-code tracking
    # isolate this task; old/expired activations cannot be restored by address.
    account = get_account_context(email)
    if account is None:
        raise SMSBowerError("SMSBower: không còn phiên email; cần lấy email mới")
    return _fetch_account_otp(account, after_ts=after_ts, max_wait=max_wait, poll_interval=poll_interval, settle_seconds=settle_seconds)


def _fetch_account_otp(account, after_ts=None, max_wait=None, poll_interval=None, settle_seconds=None):
    wait = max(0, float(_email_cfg.OTP_MAX_WAIT if max_wait is None else max_wait))
    interval = max(1, float(_email_cfg.OTP_POLL_INTERVAL if poll_interval is None else poll_interval))
    deadline = min(time.monotonic() + wait, account.created_at + 18 * 60)
    if account.needs_next_code and time.monotonic() <= deadline:
        _set_status(account, 5)
        account.needs_next_code = False
    while time.monotonic() <= deadline:
        payload = _get("getCode", account.api_key, mailId=account.mail_id)
        if _success(payload):
            account.received_code = True
            code = str(payload.get("code") or "").strip()
            if not re.fullmatch(r"[0-9]{6}", code):
                raise SMSBowerError("SMSBower: mã xác minh không hợp lệ")
            if code not in account.used_codes:
                account.used_codes.add(code)
                account.needs_next_code = True
                return code
        else:
            message = str(payload.get("error") or payload.get("message") or "").lower()
            if str(payload.get("status")) != "0" or (message and "not been received" not in message and "try again later" not in message):
                _fail(payload, "getCode")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    raise SMSBowerError("SMSBower: hết thời gian chờ mã xác minh")


def release_account(email: str, status="available", note=None) -> None:
    account = get_account_context(email)
    if account is None:
        return
    _release_activation(account, status=status)


def _release_activation(account, status="available"):
    # Operate on the activation identity, even if the address has been reissued.
    try:
        _set_status(account, 3 if account.received_code or account.used_codes or status == "success" else 2)
    finally:
        key = account.email.strip().lower()
        with _CONTEXT_LOCK:
            if _CONTEXT_CACHE.get(key) is account:
                _CONTEXT_CACHE.pop(key, None)
