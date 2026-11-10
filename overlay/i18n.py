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
    "he": "עברית",
    "pl": "Polski",
    "tr": "Turkce",
    "nl": "Nederlands",
    "sv": "Svenska",
    "ar": "العربية",
    "uk": "Українська",
}

RTL_LANGUAGES = frozenset({"ar", "he"})


def gtk_direction_for(lang: str):
    """Gtk.TextDirection for the configured language: RTL_LANGUAGES decides
    an explicit override outright; "system" defers to the process locale
    GTK itself would read (setup_i18n already ran locale.setlocale for that
    branch). Imports gi lazily so a process that never touches GTK (the
    PyQt6 tray app) never gains it as a hard dependency."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    if lang == "system":
        return Gtk.get_locale_direction()
    return Gtk.TextDirection.RTL if lang in RTL_LANGUAGES else Gtk.TextDirection.LTR


def qt_direction_for(lang: str):
    """PyQt6 Qt.LayoutDirection for the configured language, mirroring
    gtk_direction_for's rule for the overlay's own QApplication (tray menu).
    Imports PyQt6.QtCore lazily, same reasoning as gtk_direction_for."""
    from PyQt6.QtCore import QLocale, Qt

    if lang == "system":
        return QLocale.system().textDirection()
    return (Qt.LayoutDirection.RightToLeft if lang in RTL_LANGUAGES
            else Qt.LayoutDirection.LeftToRight)


def apply_platform_direction(lang: str) -> None:
    """Set the default direction of every GUI toolkit this process has
    already loaded. Checked via sys.modules, not import, so a process using
    only one toolkit never gains the other as a dependency: the GTK settings
    dashboard never imports PyQt6, the PyQt6 tray app never imports GTK."""
    import sys

    if "gi.repository.Gtk" in sys.modules:
        from gi.repository import Gtk
        Gtk.Widget.set_default_direction(gtk_direction_for(lang))
    if "PyQt6.QtWidgets" in sys.modules:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(qt_direction_for(lang))


def get_configured_language() -> str:
    """Read language from config.json, fallback to 'system'."""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("language", "system")
    except (json.JSONDecodeError, OSError):
        pass  # Config file doesn't exist or is corrupted, use system default
    return "system"


def setup_i18n():
    """Initialize gettext with configured or system language. Returns _() function."""
    lang = get_configured_language()
    apply_platform_direction(lang)

    if lang == "system":
        # Use system locale
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass  # Locale not supported, will use default
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
    except (OSError, UnicodeDecodeError):
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
            except (TypeError, AttributeError):
                pass  # Module dict not accessible, skip

    # Use sys.modules to break circular import with settings_constants
    sc = sys.modules.get('settings_constants')
    if sc and hasattr(sc, 'refresh_translations'):
        sc.refresh_translations(_)
