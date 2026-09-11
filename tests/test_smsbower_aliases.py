import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import patch

from config import email as cfg
from core import smsbower_aliases as aliases
from core import smsbower_client as client


class SMSBowerAliasTests(unittest.TestCase):
    def setUp(self):
        aliases._GROUPS.clear()
        aliases._CONTEXT.clear()
        aliases._BUYING.clear()
        client._CONTEXT_CACHE.clear()
        self.calls = []
        self.rents = 0
        self.codes = 0
        def wire(action, key, **params):
            self.calls.append((action, params))
            if action == 'getActivation':
                self.rents += 1
                return {'status': 1, 'mail': f'mail{self.rents}@{params["domain"]}', 'mailId': self.rents}
            if action == 'getCode':
                self.codes += 1
                return {'status': 1, 'code': str(100000+self.codes)}
            return {'status': 1}
        for p in [patch.object(cfg, 'SMSBOWER_API_KEY', 'test-key'), patch.object(cfg, 'SMSBOWER_DOMAIN', 'icloud.com'), patch.object(client, '_get', side_effect=wire), patch.object(aliases, '_check_stop')]:
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(client._CONTEXT_CACHE.clear)
        self.addCleanup(aliases._GROUPS.clear)
        self.addCleanup(aliases._CONTEXT.clear)

    def signup(self, count=2):
        with aliases.registration_scope() as result:
            account = aliases.pick_account()
            for _ in range(count):
                aliases.fetch_latest_otp(account.email, max_wait=1)
            result['success'] = True
            return account.email

    def test_two_tags_share_one_rent_and_third_buys_again(self):
        first = self.signup()
        second = self.signup()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r'^mail1\+[a-f0-9]{10}@icloud.com$')
        self.assertRegex(second, r'^mail1\+[a-f0-9]{10}@icloud.com$')
        self.assertEqual(self.rents, 1)
        statuses = [p['status'] for action,p in self.calls if action == 'setStatus']
        self.assertEqual(statuses, [5, 5, 5, 3])
        self.signup(1)
        self.assertEqual(self.rents, 2)

    def test_rearm_happens_before_second_alias_is_given_to_browser(self):
        self.signup(1)
        with aliases.registration_scope() as result:
            account = aliases.pick_account()
            self.assertEqual(self.calls[-1], ('setStatus', {'id': '1', 'status': 5}))
            aliases.fetch_latest_otp(account.email, max_wait=1)
            result['success'] = True

    def test_old_alias_cannot_read_or_release_second_alias(self):
        first = self.signup(1)
        with aliases.registration_scope() as result:
            second = aliases.pick_account()
            with self.assertRaises(client.SMSBowerError):
                aliases.fetch_latest_otp(first, max_wait=1)
            before = len(self.calls)
            aliases.release_account(first)
            self.assertEqual(len(self.calls), before)
            self.assertEqual(aliases.fetch_latest_otp(second.email, max_wait=1), '100002')
            result['success'] = True

    def test_parallel_job_waits_for_scope_and_totp_before_reusing(self):
        twofa = Future()
        with aliases.registration_scope() as result:
            first = aliases.pick_account()
            aliases.fetch_latest_otp(first.email, max_wait=1)
            aliases.track_future(first.email, twofa)
            result['success'] = True
        started = threading.Event()
        owner = first.group.key[2]
        def second_job():
            aliases._LOCAL.owner = owner
            started.set()
            return self.signup(1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(second_job)
            self.assertTrue(started.wait(1))
            time.sleep(.05)
            self.assertFalse(second.done())
            self.assertEqual(self.rents, 1)
            # Background TOTP is still allowed to use the first alias.
            aliases.fetch_latest_otp(first.email, max_wait=1)
            twofa.set_result({'ok': True})
            self.assertTrue(second.result(timeout=2).startswith('mail1+'))
        self.assertEqual(self.rents, 1)

    def test_completed_future_callback_does_not_deadlock(self):
        future = Future();future.set_result({'ok': True})
        with aliases.registration_scope() as result:
            account = aliases.pick_account()
            aliases.track_future(account.email, future)
            result['success'] = True
        self.assertIsNone(account.group.active)

    def test_failed_totp_finishes_paid_activation_instead_of_refund(self):
        future = Future()
        with aliases.registration_scope() as result:
            account = aliases.pick_account()
            aliases.fetch_latest_otp(account.email, max_wait=1)
            aliases.track_future(account.email, future)
            result['success'] = True
        future.set_result({'ok': False})
        self.assertEqual(self.calls[-1], ('setStatus', {'id': '1', 'status': 3}))
        self.signup(1)
        self.assertEqual(self.rents, 2)

    def test_five_code_budget_stops_before_sixth_request(self):
        self.signup(2)
        with aliases.registration_scope() as result:
            account = aliases.pick_account()
            for _ in range(3):
                aliases.fetch_latest_otp(account.email, max_wait=1)
            before = len(self.calls)
            with self.assertRaisesRegex(client.SMSBowerError, '5 lượt'):
                aliases.fetch_latest_otp(account.email, max_wait=1)
            self.assertEqual(len(self.calls), before)
            result['success'] = True
        self.assertEqual(self.codes, 5)

    def test_low_budget_or_expiry_rents_new_activation(self):
        self.signup(4)
        self.signup(1)
        self.assertEqual(self.rents, 2)
        aliases._GROUPS[0].account.created_at -= 1000
        self.signup(1)
        self.assertEqual(self.rents, 3)

    def test_cleanup_error_does_not_mask_success_or_block_next_rent(self):
        self.signup(1)
        with patch.object(client, '_release_activation', side_effect=client.SMSBowerError('offline')):
            self.signup(1)
        self.assertEqual(aliases._GROUPS, [])
        self.signup(1)
        self.assertEqual(self.rents, 2)

    def test_unconsumed_failure_cancels_once_despite_duplicate_cleanup(self):
        with aliases.registration_scope():
            account = aliases.pick_account()
            aliases.release_account(account.email)
            aliases.release_account(account.email)
        self.assertEqual([p['status'] for a,p in self.calls if a=='setStatus'], [2])

    def test_outside_registration_uses_independent_activation(self):
        account = aliases.pick_account()
        self.assertEqual(account.email, 'mail1@icloud.com')
        self.assertEqual(aliases._GROUPS, [])
        aliases.release_account(account.email)

    def test_domain_switch_does_not_reuse_existing_group(self):
        self.signup(1)
        with patch.object(cfg, 'SMSBOWER_DOMAIN', 'gmail.com'):
            email = self.signup(1)
        self.assertTrue(email.endswith('@gmail.com'))
        self.assertEqual(self.rents, 2)

    def test_common_registration_wrapper_finalizes_browser_and_cli_returns(self):
        import main
        def register(**kwargs):
            account = aliases.pick_account()
            return {'success': True, 'email': account.email}
        with patch.object(main, '_run_registration', side_effect=register):
            first = main.run_registration(email=None, name='Example')
            second = main.run_registration(email=None, name='Example')
        self.assertNotEqual(first['email'], second['email'])
        self.assertEqual(self.rents, 1)
        self.assertEqual(self.calls[-1], ('setStatus', {'id': '1', 'status': 3}))

    def test_purchase_uses_captured_config_snapshot(self):
        original = client.pick_account
        def changed_config(**kwargs):
            with patch.object(cfg, 'SMSBOWER_DOMAIN', 'gmail.com'):
                return original(**kwargs)
        with patch.object(client, 'pick_account', side_effect=changed_config):
            email = self.signup(1)
        self.assertTrue(email.endswith('@icloud.com'))
        self.assertEqual(self.calls[0][1]['domain'], 'icloud.com')

    def test_reissued_base_does_not_redirect_otp_or_cleanup(self):
        with aliases.registration_scope() as result:
            alias = aliases.pick_account()
            old = alias.group.account
            newer = client.SMSBowerAccount(old.email, '999', 'new-key')
            client._CONTEXT_CACHE[old.email.lower()] = newer
            aliases.fetch_latest_otp(alias.email, max_wait=1)
            self.assertEqual(self.calls[-1][1]['mailId'], old.mail_id)
            aliases.release_account(alias.email, status='failed')
            result['success'] = True
        self.assertEqual(self.calls[-1][1]['id'], old.mail_id)
        self.assertIs(client._CONTEXT_CACHE[old.email.lower()], newer)

    def test_cancelled_waiter_does_not_buy(self):
        from core.registration_service import StopRequested
        with patch.object(aliases, '_check_stop', side_effect=StopRequested('stopped')):
            with aliases.registration_scope():
                with self.assertRaises(StopRequested):
                    aliases.pick_account()
        self.assertEqual(self.rents, 0)

    def test_production_twofa_enqueue_attaches_future_to_alias(self):
        from core import twofa_service
        future = Future()
        with aliases.registration_scope() as result:
            account = aliases.pick_account()
            with patch.object(cfg, 'USE_EMAIL_SERVICE', True), patch.object(twofa_service.db, 'claim_account_totp_setup', return_value=True), patch.object(twofa_service, '_append_log'), patch.object(twofa_service._EXECUTOR, 'submit', return_value=future), patch.object(twofa_service, '_QUEUE_SLOTS'):
                queued = twofa_service.enqueue_account_totp_setup(account_id=1, email=account.email, access_token='test-token')
            self.assertTrue(queued['accepted'])
            self.assertEqual(account.pending, 1)
            result['success'] = True
        self.assertEqual(account.group.active, account.email)
        future.set_result({'ok': True})
        self.assertEqual(account.pending, 0)
        self.assertIsNone(account.group.active)

    def test_independent_pairs_buy_concurrently_but_each_reuses_own_mail(self):
        barrier = threading.Barrier(2)
        def pair():
            with aliases.group_scope():
                with aliases.registration_scope() as result:
                    first = aliases.pick_account()
                    barrier.wait(timeout=2)
                    result['success'] = True
                with aliases.registration_scope() as result:
                    second = aliases.pick_account()
                    self.assertIs(first.group, second.group)
                    result['success'] = True
                return first.email, second.email
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(pair), pool.submit(pair)
            first, second = a.result(timeout=3), b.result(timeout=3)
        self.assertEqual(self.rents, 2)
        self.assertNotEqual(first[0].split('+')[0], second[0].split('+')[0])
        self.assertEqual(aliases._GROUPS, [])

    def test_odd_tail_closes_its_activation(self):
        with aliases.group_scope():
            self.signup(1)
        self.assertEqual(aliases._GROUPS, [])
        self.assertEqual(self.calls[-1][1]['status'], 3)

    def test_submit_splits_five_jobs_into_three_executor_tasks(self):
        from core import registration_service as service
        from unittest.mock import Mock
        executor = Mock()
        jobs = [{'id': i, 'log_file': f'/tmp/test-job-{i}.log'} for i in range(5)]
        with patch.object(service, 'get_executor', return_value=executor), patch.object(service, 'get_executor_workers', return_value=3), patch.object(service.db, 'create_job', side_effect=jobs), patch.object(service.db, 'get_job', side_effect=lambda i: jobs[i]):
            result = service.submit_registration(count=5, email_source='smsbower', workers=3)
        self.assertEqual(len(result), 5)
        self.assertEqual([len(call.args[1]) for call in executor.submit.call_args_list], [2, 2, 1])
        self.assertTrue(all(call.args[0] is service._run_smsbower_pair for call in executor.submit.call_args_list))

    def test_pair_continues_when_first_job_raises_outside_handler(self):
        from core import registration_service as service
        jobs = [{'id': 1, 'log_file': 'one'}, {'id': 2, 'log_file': 'two'}]
        with patch.object(service, '_run_one_job', side_effect=[RuntimeError('database'), None]) as run, patch.object(service.db, 'update_job') as update, patch.object(service, '_deactivate_job'):
            service._run_smsbower_pair(jobs)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(update.call_args.kwargs['status'], 'failed')
