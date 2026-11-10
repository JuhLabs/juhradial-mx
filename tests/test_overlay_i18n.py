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


import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

import pytest


@pytest.fixture(autouse=True)
def _restore_gtk_direction():
    original = Gtk.Widget.get_default_direction()
    yield
    Gtk.Widget.set_default_direction(original)


def test_gtk_direction_for_explicit_languages():
    from i18n import gtk_direction_for

    assert gtk_direction_for("he") == Gtk.TextDirection.RTL
    assert gtk_direction_for("ar") == Gtk.TextDirection.RTL
    assert gtk_direction_for("en") == Gtk.TextDirection.LTR


def test_gtk_direction_for_system_follows_locale_direction():
    from i18n import gtk_direction_for

    assert gtk_direction_for("system") == Gtk.get_locale_direction()


def test_qt_direction_for_explicit_languages():
    from PyQt6.QtCore import Qt
    from i18n import qt_direction_for

    assert qt_direction_for("he") == Qt.LayoutDirection.RightToLeft
    assert qt_direction_for("ar") == Qt.LayoutDirection.RightToLeft
    assert qt_direction_for("en") == Qt.LayoutDirection.LeftToRight


def test_qt_direction_for_system_follows_locale_direction():
    from PyQt6.QtCore import QLocale
    from i18n import qt_direction_for

    assert qt_direction_for("system") == QLocale.system().textDirection()


def test_setup_i18n_sets_and_resets_gtk_direction_on_language_switch(monkeypatch, tmp_path):
    import i18n as i18n_module

    cfg = tmp_path / "config.json"
    monkeypatch.setattr(i18n_module, "CONFIG_FILE", cfg)

    cfg.write_text('{"language": "he"}')
    i18n_module.setup_i18n()
    assert Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL

    cfg.write_text('{"language": "en"}')
    i18n_module.setup_i18n()
    assert Gtk.Widget.get_default_direction() == Gtk.TextDirection.LTR


_QT_APP = None


@pytest.fixture
def qt_app():
    """The tray app's QApplication. Importing PyQt6.QtWidgets is what turns
    on apply_platform_direction's Qt branch; restore the direction after."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    global _QT_APP  # keep it alive past this test, as the app is per process
    app = _QT_APP = QApplication.instance() or QApplication([])
    original = app.layoutDirection()
    yield app
    app.setLayoutDirection(original)


def test_setup_i18n_sets_and_resets_qt_direction_on_language_switch(monkeypatch, tmp_path, qt_app):
    from PyQt6.QtCore import Qt
    import i18n as i18n_module

    assert "PyQt6.QtWidgets" in sys.modules  # else the Qt branch silently no-ops
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(i18n_module, "CONFIG_FILE", cfg)

    cfg.write_text('{"language": "he"}')
    i18n_module.setup_i18n()
    assert qt_app.layoutDirection() == Qt.LayoutDirection.RightToLeft

    cfg.write_text('{"language": "en"}')
    i18n_module.setup_i18n()
    assert qt_app.layoutDirection() == Qt.LayoutDirection.LeftToRight
