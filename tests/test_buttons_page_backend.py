#!/usr/bin/env python3
"""Buttons tab P0 fixes (audit P0 #3, #8): picked apps show their own name on
the wheel, quick links edit every submenu slice and never save a bare
https://, the MX3 pins are stored where they are read, the thumb-wheel
callout drives thumbwheel.mode, and pickers only offer actions that work.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_buttons_page_backend.py -q
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])

import bridge.backend as bk  # noqa: E402


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    b.daemon.call_async = lambda *a, **k: None
    return b


def test_picked_app_gets_its_own_action_id_and_label(backend):
    row = next(i for i, s in enumerate(backend.slices.slices()) if s.get("action_id") == "files")
    backend.slices.setApp(row, "gimp", "GIMP", "/tmp/gimp.png")
    s = backend.slices.slices()[row]
    assert s["action_id"] == "custom_app" and s["label"] == "GIMP" and s["command"] == "gimp"
    # the overlay's label lookup no longer resolves it to the preset name
    sys.path.insert(0, os.fspath(REPO / "overlay"))
    import settings_constants
    assert settings_constants.translate_radial_label("GIMP", "custom_app") != "Files"


def test_quick_links_on_every_submenu_slice(backend):
    slices = backend.slices.slices()
    slices[0]["type"] = "submenu"
    backend.slices.load(slices)
    rows = [r["row"] for r in backend.submenuRows()]
    assert 0 in rows and len(rows) >= 2
    backend.setLinksFor(0, [{"name": "Docs", "url": "example.org"},
                            {"name": "Empty", "url": "https://"},
                            {"name": "", "url": "https://x.org"}])
    assert backend.linksFor(0) == [{"name": "Docs", "url": "https://example.org",
                                    "icon": "browser", "command": ""}]
    other = [r for r in rows if r != 0][0]
    assert backend.linksFor(other)[0]["name"] != "Docs"     # independent lists


def test_clean_url():
    assert bk.Backend._clean_url("https://") == ""
    assert bk.Backend._clean_url("  ") == ""
    assert bk.Backend._clean_url("claude.ai") == "https://claude.ai"
    assert bk.Backend._clean_url("http://x.org/a") == "http://x.org/a"


def test_mx3_pins_are_nested_where_the_page_reads_them(backend):
    backend.setPinPos("mx3.back", 0.5, 0.25)
    assert backend.get("button_pins.mx3.back") == {"nx": 0.5, "ny": 0.25}
    backend.setPinPos("back", 0.1, 0.2)
    assert backend.get("button_pins.back") == {"nx": 0.1, "ny": 0.2}


def test_pickers_offer_only_working_actions(backend):
    ids = [a["id"] for a in backend.buttonActions()]
    assert "custom" not in ids and "smartshift" in ids and "middle_click" in ids
    assert "radial_menu" not in [a["id"] for a in backend.gestureActions()]


def test_thumb_wheel_default_is_named_for_what_it_does():
    assert dict(bk.THUMBWHEEL_MODES)["off"] == "Horizontal scroll (default)"
