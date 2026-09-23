"""gettext catalogs behind a QTranslator; qsTr() and Python _() read the same catalogs.

The Qt settings app has its own gettext domain (DOMAIN) with a fallback to the
overlay/GTK domain (FALLBACK_DOMAIN), so strings the older UIs already
translate are translated here at once. Catalogs live next to the code:
<repo>/overlay/locales for a checkout and /opt/juhradial-mx, and
/usr/share/juhradial/locales when settings-qt is installed under
/usr/share/juhradial.

Language: config.json `language` when it holds a locale code; absent, empty
or "system" means the desktop locale (LANGUAGE/LC_ALL/LC_MESSAGES/LANG).
Changes take effect on the next start.
"""
import gettext
import json
import os
from pathlib import Path

from PyQt6.QtCore import QTranslator

DOMAIN = "juhradial-settings"
FALLBACK_DOMAIN = "juhradial"
_SETTINGS_QT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
               / "juhradial" / "config.json")


def locale_dirs() -> list[Path]:
    """Catalog directories in lookup order (checkout/opt first, then /usr/share)."""
    return [_SETTINGS_QT.parent / "overlay" / "locales",
            _SETTINGS_QT.parent / "locales"]


def configured_language(config_path=CONFIG_PATH) -> str | None:
    """The forced locale code from config.json, or None for the desktop locale."""
    try:
        with open(config_path, encoding="utf-8") as f:
            lang = json.load(f).get("language")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(lang, str):
        return None
    lang = lang.strip()
    if not lang or lang == "system":
        return None
    return lang


def load_translation(language=None, dirs=None) -> gettext.NullTranslations:
    """Own domain with the overlay domain as fallback; identity when nothing matches."""
    localedir = next((d for d in (dirs if dirs is not None else locale_dirs())
                      if Path(d).is_dir()), None)
    if localedir is None:
        return gettext.NullTranslations()
    languages = [language] if language else None
    try:
        t = gettext.translation(DOMAIN, str(localedir), languages=languages,
                                fallback=True)
        fb = gettext.translation(FALLBACK_DOMAIN, str(localedir),
                                 languages=languages, fallback=True)
    except (OSError, UnicodeDecodeError):
        return gettext.NullTranslations()
    t.add_fallback(fb)
    return t


class GettextTranslator(QTranslator):
    """Answers Qt's translation lookups (qsTr in QML) from a gettext translation.

    translate() returns None on a miss, never "": Qt treats a null QString as
    "not translated" and shows the source text, but an empty string is taken
    as a real translation and would blank every untranslated label. It never
    raises either, because an exception in this C++ virtual override aborts
    the whole app.
    """

    def __init__(self, translation, parent=None):
        super().__init__(parent)
        self._translation = translation

    def translate(self, context, source_text, disambiguation=None, n=-1):
        try:
            if not source_text:
                return None
            # qsTr("%n step(s)", "", n): gettext plural forms, so English
            # reads "1 step" / "3 steps" and catalogs can add their own.
            if n >= 0 and "(s)" in source_text:
                return self._translation.ngettext(source_text.replace("(s)", ""),
                                                  source_text.replace("(s)", "s"), n)
            if disambiguation:
                result = self._translation.pgettext(disambiguation, source_text)
            else:
                result = self._translation.gettext(source_text)
            if result and result != source_text:
                return result
        except Exception:
            pass
        return None

    def isEmpty(self):
        return False


_translation = load_translation(configured_language())


def _(message: str) -> str:
    """Translate a Python-side UI string (unchanged text when untranslated)."""
    return _translation.gettext(message)


def install_translator(app) -> GettextTranslator:
    """Install the translator on app; the caller keeps the returned reference."""
    t = GettextTranslator(_translation, app)
    app.installTranslator(t)
    return t
