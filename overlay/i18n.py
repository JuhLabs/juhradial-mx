"""
JuhRadial MX - Internationalization (i18n) Module

Thin wrapper around Python's built-in gettext module.
Provides _() translation function used across all UI files.

Usage:
    from i18n import _
    label = _('Settings')

SPDX-License-Identifier: GPL-3.0
"""

import gettext
import locale
import os
import json
from pathlib import Path

# Locale directory: development = overlay/locales/, installed = /usr/share/juhradial/locales/
_DEV_LOCALE_DIR = Path(__file__).parent / "locales"
_INSTALLED_LOCALE_DIR = Path("/usr/share/juhradial/locales")
LOCALE_DIR = _DEV_LOCALE_DIR if _DEV_LOCALE_DIR.exists() else _INSTALLED_LOCALE_DIR

CONFIG_FILE = Path.home() / ".config" / "juhradial" / "config.json"
DOMAIN = "juhradial"

SUPPORTED_LANGUAGES = {
    "system": "System Default",
    "en": "English",
    "nb": "Norsk Bokmål",
    "es": "Español",
    "pt_BR": "Português (Brasil)",
    "de": "Deutsch",
    "fr": "Français",
    "it": "Italiano",
    "ru": "Русский",
    "ja": "日本語",
    "th": "ไทย",
    "zh_CN": "中文 (简体)",
    "ko": "한국어",
    "hi": "हिन्दी",
}


def get_configured_language() -> str:
    """Read language from config.json, fallback to 'system'."""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("language", "system")
    except (json.JSONDecodeError, OSError):
        pass
    return "system"


def setup_i18n():
    """Initialize gettext with configured or system language. Returns _() function."""
    lang = get_configured_language()

    if lang == "system":
        # Use system locale
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        languages = None  # Let gettext detect from environment
    else:
        languages = [lang]

    try:
        translation = gettext.translation(
            DOMAIN,
            localedir=str(LOCALE_DIR),
            languages=languages,
            fallback=True,
        )
    except Exception:
        translation = gettext.NullTranslations()

    return translation.gettext


# Module-level _() — imported by all UI files
_ = setup_i18n()


def reload_language():
    """Reload translations and patch _ in all imported settings modules."""
    global _
    _ = setup_i18n()
    import sys

    for name, mod in sys.modules.items():
        if (
            mod
            and hasattr(mod, "_")
            and (
                name.startswith("settings_")
                or name in ("i18n", "settings_dashboard", "__main__")
            )
        ):
            try:
                mod.__dict__["_"] = _
            except Exception:
                pass

    try:
        from settings_constants import refresh_translations

        refresh_translations()
    except Exception:
        pass
