# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from config import email as email_config
from core import email_provider


class SMSBowerProviderTests(unittest.TestCase):
    def test_parse_sources_keeps_smsbower_in_order(self):
        self.assertEqual(
            email_provider.parse_email_sources("outlook,smsbower,generic_api,mailnest,cloudmail"),
            ["outlook", "smsbower", "generic_api", "mailnest", "cloudmail"],
        )

    @patch("core.smsbower_aliases.pick_account")
    def test_acquire_email_uses_smsbower_client(self, pick_account):
        pick_account.return_value.email = "fresh@smsbower.test"

        with patch("core.email_provider.parse_email_sources", return_value=["smsbower"]):
            self.assertEqual(email_provider.acquire_email(), "fresh@smsbower.test")

    @patch("core.smsbower_aliases.get_account_context", return_value=object())
    def test_resolve_email_source_recognizes_cached_smsbower_address(self, get_context):
        self.assertEqual(email_provider.resolve_email_source("fresh@smsbower.test"), "smsbower")
        get_context.assert_called_once_with("fresh@smsbower.test")

    @patch("core.smsbower_aliases.release_account")
    @patch("core.email_provider.resolve_email_source", return_value="smsbower")
    def test_release_email_clears_smsbower_context(self, resolve, release):
        self.assertEqual(email_provider.release_email("fresh@smsbower.test", status="failed"), "smsbower")
        release.assert_called_once_with("fresh@smsbower.test", status="failed", note=None)

    @patch("core.smsbower_aliases.fetch_latest_otp", return_value="654321")
    @patch("core.email_provider.resolve_email_source", return_value="smsbower")
    def test_wait_for_otp_uses_smsbower_client(self, resolve, fetch_latest_otp):
        with patch.object(email_config, "USE_EMAIL_SERVICE", True):
            self.assertEqual(email_provider.wait_for_otp("fresh@smsbower.test", after_ts=123.0), "654321")
        fetch_latest_otp.assert_called_once_with("fresh@smsbower.test", after_ts=123.0)
