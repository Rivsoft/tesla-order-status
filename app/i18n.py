import gettext
from pathlib import Path
from typing import Optional

from babel.support import Translations
from fastapi import Request

LANG_COOKIE_NAME = "tesla_lang"

class I18n:
    def __init__(self, translations_dir: Path, default_locale: str = "en"):
        self.translations_dir = translations_dir
        self.default_locale = default_locale
        self.translations: dict[str, Translations] = {}
        self.supported_locales = ["en", "nl"]

    def load_translations(self):
        for locale in self.supported_locales:
            try:
                translation = Translations.load(
                    dirname=str(self.translations_dir),
                    locales=[locale]
                )
                self.translations[locale] = translation
            except Exception:
                # Fallback to null translations if loading fails
                self.translations[locale] = Translations()

    def get_locale(self, request: Request) -> str:
        # 1. Check query param
        query_lang = request.query_params.get("lang")
        if query_lang in self.supported_locales:
            return query_lang

        # 2. Check cookie
        cookie_lang = request.cookies.get(LANG_COOKIE_NAME)
        if cookie_lang in self.supported_locales:
            return cookie_lang

        # 3. Check Accept-Language header
        accept_lang = request.headers.get("accept-language")
        if accept_lang:
            # Simple parsing, can be improved with babel.negotiate_locale
            # but for now let's just take the first two chars
            # or use a library function if available.
            # Let's use a simple match for now.
            if "nl" in accept_lang:
                return "nl"

        return self.default_locale

    def get_translation(self, locale: str) -> Translations:
        return self.translations.get(locale, self.translations.get(self.default_locale, Translations()))

BASE_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = BASE_DIR / "translations"

i18n = I18n(TRANSLATIONS_DIR)
i18n.load_translations()
