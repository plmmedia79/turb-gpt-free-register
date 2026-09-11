# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from config import email
from config.env_loader import SECRET_ENV_KEYS
from webui.config_editor import EDITABLE_FIELDS


class SMSBowerConfigTests(unittest.TestCase):
    def test_email_config_declares_smsbower_api_key_with_empty_default(self):
        source = Path(email.__file__).read_text(encoding="utf-8")
        self.assertIn('SMSBOWER_API_KEY = env_str("SMSBOWER_API_KEY", "")', source)

    def test_secret_registry_includes_smsbower_api_key(self):
        self.assertEqual(SECRET_ENV_KEYS["SMSBOWER_API_KEY"], "SMSBower API Key")

    def test_webui_exposes_smsbower_key_as_secret_env_field(self):
        field = next(item for item in EDITABLE_FIELDS if item["key"] == "SMSBOWER_API_KEY")
        self.assertEqual(field["group"], "邮箱 / OTP")
        self.assertTrue(field["secret"])
        self.assertEqual(field["storage"], "env")

    def test_domain_is_a_gmail_icloud_selector(self):
        field = next(item for item in EDITABLE_FIELDS if item['key'] == 'SMSBOWER_DOMAIN')
        self.assertEqual(field['options'], [
            {'value': 'gmail.com', 'label': 'Gmail'},
            {'value': 'icloud.com', 'label': 'iCloud'},
        ])

    def test_invalid_selection_does_not_write_settings(self):
        from unittest.mock import patch
        from webui.config_editor import update_config
        with patch('config.env_loader.write_env_values') as write:
            with self.assertRaises(ValueError):
                update_config({'SMSBOWER_DOMAIN': 'invalid.com'})
        write.assert_not_called()

    def test_icloud_selection_saves_to_env(self):
        from unittest.mock import patch
        from webui.config_editor import update_config
        with patch('config.env_loader.write_env_values', return_value=[]) as write:
            update_config({'SMSBOWER_DOMAIN': 'icloud.com'})
        write.assert_called_once_with({'SMSBOWER_DOMAIN': 'icloud.com'})

    def test_saved_domain_reaches_actual_purchase_after_reload(self):
        import importlib
        import os
        import tempfile
        from unittest.mock import patch
        from config import env_loader
        from core import smsbower_client
        from webui.config_editor import update_config
        try:
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(env_loader, '_ENV_PATH', Path(directory) / '.env'), patch.dict(os.environ):
                    update_config({'SMSBOWER_DOMAIN': 'icloud.com', 'SMSBOWER_API_KEY': 'test-only-key'})
                    importlib.reload(email)
                    self.assertEqual(email.SMSBOWER_DOMAIN, 'icloud.com')
                    with patch.object(smsbower_client, '_get', return_value={
                        'status': 1, 'mail': 'reload-test@icloud.com', 'mailId': 77,
                    }) as get:
                        smsbower_client.pick_account()
                    get.assert_called_once_with('getActivation', 'test-only-key', service='dr', domain='icloud.com')
        finally:
            smsbower_client._CONTEXT_CACHE.pop('reload-test@icloud.com', None)
            importlib.reload(email)
