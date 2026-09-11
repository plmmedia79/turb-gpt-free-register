"""Language selection must not change API data or authentication contracts."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from webui.app import create_app
from webui.config_editor import EDITABLE_FIELDS
from webui.i18n import vietnamese_catalog


class WebUiLanguageTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(auth_code="language-test-code")
        self.client = self.app.test_client()

    def test_default_login_is_vietnamese(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn('<html lang="vi">', response.text)
        self.assertIn("Tiếng Việt", response.text)
        self.assertTrue("Đăng nhập" in response.text, "Vietnamese login copy is missing")

    def test_language_survives_login_and_query_preserves_ui_mode(self):
        response = self.client.get("/login?lang=zh-CN")
        self.assertIn("webui_language=zh-CN", response.headers.get("Set-Cookie", ""))
        self.assertIn('<html lang="zh-CN">', response.text)
        response = self.client.post("/login", data={"auth_code": "language-test-code"})
        self.assertEqual(response.status_code, 302)
        for path in ("/", "/?ui=legacy"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('<html lang="zh-CN">', response.text)
        response = self.client.get("/?ui=legacy&lang=vi")
        self.assertIn('<html lang="vi">', response.text)
        self.assertIn('<html lang="vi">', self.client.get("/").text)

    def test_invalid_language_falls_back_without_echoing_input(self):
        response = self.client.get("/login?lang=unsupported-language")
        self.assertIn('<html lang="vi">', response.text)
        self.assertNotIn("webui_language=unsupported", response.headers.get("Set-Cookie", ""))

    def test_language_does_not_bypass_auth_or_translate_api_contract(self):
        response = self.client.get("/api/summary?lang=vi")
        self.assertEqual(response.status_code, 401)
        self.assertIn("未授权", response.json["error"])
        response = self.client.get("/api/config?lang=vi", headers={"X-Auth-Code": "language-test-code", "Accept-Encoding": "identity"})
        self.assertEqual(response.status_code, 200)
        # Translation occurs only at the point of display, not in API metadata.
        self.assertIn("WEBUI_AUTH_CODE", response.text)
        self.assertIn("WebUI", response.text)

    def test_all_config_copy_has_translation(self):
        catalog = vietnamese_catalog()
        missing = []

        def inspect(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    inspect(item, path + "." + key)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    inspect(item, f"{path}[{index}]")
            elif isinstance(value, str) and re.search(r"[\u3400-\u9fff]", value) and value not in catalog:
                missing.append((path, value))

        for field in EDITABLE_FIELDS:
            inspect(field, field["key"])
        self.assertFalse(missing, f"Missing configuration translations: {missing[:10]}")

    def test_template_catalog_coverage_and_placeholders(self):
        catalog = vietnamese_catalog()
        root = Path(__file__).resolve().parents[1] / "webui"
        missing = []
        for path in (root / "templates").glob("*.html"):
            for match in re.finditer(r'\b(?:t|tr)\(("(?:\\.|[^"\\])*")', path.read_text()):
                source = json.loads(match[1])
                if re.search(r"[\u3400-\u9fff]", source) and source not in catalog:
                    missing.append((path.name, source))
        self.assertFalse(missing, f"Missing {len(missing)} template translations; first ten: {missing[:10]}")
        for source, translation in catalog.items():
            with self.subTest(source=source):
                self.assertEqual(
                    set(re.findall(r"\{(\w+)\}", source)),
                    set(re.findall(r"\{(\w+)\}", translation)),
                )

    @unittest.skipUnless(shutil.which("node"), "Node required to validate browser scripts")
    def test_rendered_javascript_is_valid_in_both_languages(self):
        self.client.post("/login", data={"auth_code": "language-test-code"})
        for language in ("vi", "zh-CN"):
            for path in ("/login?", "/?", "/?ui=legacy&"):
                with self.subTest(language=language, path=path):
                    html = self.client.get(path + "lang=" + language).text
                    for attributes, script in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S):
                        if "application/json" in attributes:
                            json.loads(script)
                        elif script.strip():
                            result = subprocess.run(["node", "--check"], input=script, text=True, capture_output=True)
                            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node required for runtime interpolation tests")
    def test_runtime_preserves_variables_and_fallback(self):
        runtime = Path(__file__).resolve().parents[1] / "webui/static/i18n.js"
        script = """
const assert = require('node:assert/strict');
global.window = {};
global.document = {getElementById: () => ({textContent: JSON.stringify({
  '共 {count} 条': 'Tổng cộng {count} mục',
  '失败：{error}': 'Thất bại: {error}',
  '已入队 {value0} 个{value1}': 'Đã thêm {value0} vào hàng chờ{value1}',
  '已入队 {count} 个 2FA 设置任务': 'Đã thêm {count} tác vụ thiết lập 2FA vào hàng chờ'
})})};
require(process.argv[1]);
assert.equal(window.t('共 {count} 条', {count: 7}), 'Tổng cộng 7 mục');
assert.equal(window.t('共 12 条'), 'Tổng cộng 12 mục');
assert.equal(window.t('失败：user@example.com'), 'Thất bại: user@example.com');
assert.equal(window.t('token-{unchanged}'), 'token-{unchanged}');
assert.equal(window.t('未知内容'), '未知内容');
assert.equal(window.t('原文 {count}', {count: 4}), '原文 4');
assert.equal(window.t('已入队 3 个 2FA 设置任务'), 'Đã thêm 3 tác vụ thiết lập 2FA vào hàng chờ');
"""
        result = subprocess.run(["node", "-e", script, str(runtime)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
