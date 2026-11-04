"""Overlay package language entries: the Hebrew picker entry and
RTL_LANGUAGES shared by the GTK settings dashboard and the PyQt6 tray app.

Run: python3 -m pytest tests/test_overlay_i18n.py -q
"""
import sys

sys.path.insert(0, "overlay")

from i18n import SUPPORTED_LANGUAGES, RTL_LANGUAGES


def test_hebrew_is_a_supported_language():
    assert SUPPORTED_LANGUAGES.get("he") == "עברית"


def test_rtl_languages_set():
    assert RTL_LANGUAGES == {"ar", "he"}
    for lang in SUPPORTED_LANGUAGES:
        if lang == "system":
            continue
        assert (lang in RTL_LANGUAGES) == (lang in ("he", "ar"))
