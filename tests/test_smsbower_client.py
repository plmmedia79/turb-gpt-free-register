import unittest
from unittest.mock import Mock, patch

import requests

from config import email as cfg
from core import smsbower_client as client


class SMSBowerClientTests(unittest.TestCase):
    def setUp(self):
        client._CONTEXT_CACHE.clear()
        self.key = patch.object(cfg, 'SMSBOWER_API_KEY', 'secret-key')
        self.key.start()
        self.addCleanup(self.key.stop)
        self.addCleanup(client._CONTEXT_CACHE.clear)

    def response(self, data):
        return Mock(status_code=200, json=Mock(return_value=data))

    @patch.object(client.requests, 'get')
    def test_allocation_and_next_code_use_correct_contract(self, get):
        get.side_effect = [
            self.response({'status': '1', 'mail': 'test@gmail.com', 'mailId': 42}),
            self.response({'status': 1, 'code': '012345'}),
            self.response({'status': 1}),
            self.response({'status': 1, 'code': '654321'}),
            self.response({'status': 1}),
        ]
        account = client.pick_account()
        self.assertEqual(account.mail_id, '42')
        self.assertNotIn('secret-key', repr(account))
        self.assertEqual(get.call_args.kwargs['params'], {'api_key': 'secret-key', 'service': 'dr', 'domain': 'gmail.com'})
        self.assertEqual(client.fetch_latest_otp(account.email, max_wait=1), '012345')
        self.assertEqual(client.fetch_latest_otp(account.email, max_wait=1), '654321')
        self.assertEqual(get.call_args_list[2].kwargs['params'], {'api_key': 'secret-key', 'id': '42', 'status': 5})
        client.release_account(account.email, status='failed')
        self.assertEqual(get.call_args.kwargs['params']['status'], 3)
        self.assertIsNone(client.get_account_context(account.email))

    @patch.object(client, '_get')
    def test_unused_activation_is_cancelled(self, get):
        get.side_effect = [{'status': 1, 'mail': 'test@gmail.com', 'mailId': '7'}, {'status': 1}]
        account = client.pick_account()
        client.release_account(account.email)
        get.assert_called_with('setStatus', 'secret-key', id='7', status=2)

    @patch.object(client.requests, 'get')
    def test_missing_key_never_calls_api(self, get):
        with patch.object(cfg, 'SMSBOWER_API_KEY', ''):
            with self.assertRaisesRegex(client.SMSBowerError, 'API Key'):
                client.pick_account()
        get.assert_not_called()

    @patch.object(client.requests, 'get')
    def test_transport_error_never_exposes_key(self, get):
        get.side_effect = requests.ConnectionError('https://example/?api_key=secret-key')
        with self.assertRaises(client.SMSBowerError) as caught:
            client.pick_account()
        self.assertNotIn('secret-key', str(caught.exception))

    @patch.object(client, '_get')
    def test_waiting_and_duplicate_codes_are_not_returned(self, get):
        account = client.SMSBowerAccount('test@gmail.com', '7', 'secret-key')
        client._CONTEXT_CACHE[account.email] = account
        account.used_codes.add('123456')
        get.side_effect = [
            {'status': 0, 'error': 'Code has not been received yet, please try again later'},
            {'status': 1, 'code': '123456'},
            {'status': 1, 'code': '654321'},
        ]
        with patch.object(client.time, 'sleep'):
            self.assertEqual(client.fetch_latest_otp(account.email, max_wait=1), '654321')

    @patch.object(client, '_get')
    def test_expired_activation_never_polls(self, get):
        account = client.SMSBowerAccount('test@gmail.com', '7', 'secret-key', created_at=client.time.monotonic()-1200)
        client._CONTEXT_CACHE[account.email] = account
        with self.assertRaisesRegex(client.SMSBowerError, 'hết thời gian'):
            client.fetch_latest_otp(account.email)
        get.assert_not_called()

    @patch.object(client.requests, 'get')
    def test_errors_are_sanitized_and_bad_key_stops_poll(self, get):
        account = client.SMSBowerAccount('test@gmail.com', '7', 'secret-key')
        client._CONTEXT_CACHE[account.email] = account
        get.return_value = self.response({'status': 0, 'error': 'BAD_KEY secret-key'})
        with self.assertRaises(client.SMSBowerError) as caught:
            client.fetch_latest_otp(account.email)
        self.assertNotIn('secret-key', str(caught.exception))
        get.assert_called_once()

    @patch.object(client, '_get')
    def test_invalid_delivered_code_is_finished_not_refunded(self, get):
        account = client.SMSBowerAccount('test@gmail.com', '7', 'secret-key')
        client._CONTEXT_CACHE[account.email] = account
        get.side_effect = [{'status': 1, 'code': 'invalid'}, {'status': 1}]
        with self.assertRaises(client.SMSBowerError):
            client.fetch_latest_otp(account.email)
        client.release_account(account.email, status='failed')
        get.assert_called_with('setStatus', 'secret-key', id='7', status=3)

    @patch.object(client, '_get', return_value={'status': 1, 'mail': 'test@icloud.com', 'mailId': 9})
    def test_icloud_selection_is_used_for_purchase(self, get):
        with patch.object(cfg, 'SMSBOWER_DOMAIN', 'icloud.com'):
            account = client.pick_account()
        self.assertEqual(account.email, 'test@icloud.com')
        get.assert_called_once_with('getActivation', 'secret-key', service='dr', domain='icloud.com')

    @patch.object(client, '_get')
    def test_invalid_domain_never_purchases(self, get):
        with patch.object(cfg, 'SMSBOWER_DOMAIN', 'invalid.com'):
            with self.assertRaises(client.SMSBowerError):
                client.pick_account()
        get.assert_not_called()
