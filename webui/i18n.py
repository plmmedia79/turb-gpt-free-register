"""Presentation-only Vietnamese/Chinese localization for the WebUI."""
import json
from functools import lru_cache
from pathlib import Path

from flask import request

SUPPORTED_LANGUAGES = ("vi", "zh-CN")
DEFAULT_LANGUAGE = "vi"


@lru_cache(maxsize=1)
def vietnamese_catalog():
    catalog = {}
    for path in sorted((Path(__file__).parent / "locales").glob("*-vi.json")):
        catalog.update(json.loads(path.read_text(encoding="utf-8")))
    return catalog


def current_language():
    requested = request.args.get("lang")
    if requested in SUPPORTED_LANGUAGES:
        return requested
    saved = request.cookies.get("webui_language")
    return saved if saved in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def init_i18n(app):
    @app.context_processor
    def language_context():
        language = current_language()
        catalog = vietnamese_catalog() if language == "vi" else {}

        def translate(source):
            return catalog.get(source, source)

        return {"ui_lang": language, "tr": translate, "ui_catalog": catalog}

    @app.after_request
    def remember_language(response):
        language = request.args.get("lang")
        if language in SUPPORTED_LANGUAGES:
            response.set_cookie(
                "webui_language", language, max_age=365 * 24 * 60 * 60,
                httponly=True, samesite="Lax", secure=request.is_secure,
            )
        return response
