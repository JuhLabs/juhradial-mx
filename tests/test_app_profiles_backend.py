#!/usr/bin/env python3
"""App profiles tab: a profile overrides only what is switched on, carries
its own radial menu the overlay shows, can be removed with Undo and copied,
and the class field says why it cannot add.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_app_profiles_backend.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))
sys.path.insert(0, os.fspath(REPO / "overlay"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None

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


def _hw(tmp_path):
    return json.loads((tmp_path / "profiles.json").read_text())["hardware"]


def test_only_switched_on_settings_are_written(backend, tmp_path):
    backend.addAppProfile("gimp")
    assert _hw(tmp_path)["gimp"] == {}
    backend.saveAppProfile("gimp", {"dpi": 800, "hires": False, "overrides": {"dpi": True}})
    assert _hw(tmp_path)["gimp"] == {"dpi": 800}
    p = backend.appProfiles()[0]
    assert p["overrides"]["dpi"] and not p["overrides"]["hires"]
    assert p["hires"] is True                     # follows the global setting


def test_own_ring_reaches_the_overlay(backend, tmp_path):
    import overlay_actions
    backend.addAppProfile("gimp")
    backend.setAppOwnRing("gimp", True)
    backend.appSlices.setLabel(0, "Brush")
    slices = overlay_actions.app_slices("gimp", tmp_path / "profiles.json")
    assert slices and slices[0]["label"] == "Brush" and len(slices) == 8
    assert backend.appProfiles()[0]["ownRing"]
    backend.saveAppProfile("gimp", {"overrides": {"dpi": True}, "dpi": 900})
    assert _hw(tmp_path)["gimp"]["slices"][0]["label"] == "Brush"   # kept
    backend.setAppOwnRing("gimp", False)
    assert overlay_actions.app_slices("gimp", tmp_path / "profiles.json") is None


def test_remove_undo_copy_and_validation(backend, tmp_path):
    backend.addAppProfile("gimp")
    backend.saveAppProfile("gimp", {"dpi": 800, "overrides": {"dpi": True}})
    assert "already" in backend.appProfileError("gimp")
    assert backend.appProfileError("bad class!") != ""
    assert backend.appProfileError("steam_app_730") == ""
    backend.copyAppProfile("gimp", "krita")
    assert _hw(tmp_path)["krita"] == {"dpi": 800}
    old = backend.removeAppProfile("gimp")
    assert "gimp" not in _hw(tmp_path)
    backend.restoreAppProfile("gimp", old)
    assert _hw(tmp_path)["gimp"] == {"dpi": 800}


def test_recent_apps_offer_one_click_profiles(backend):
    backend._on_new_app("Firefox")
    backend._on_new_app("code")
    backend.addAppProfile("code")
    assert [a["app"] for a in backend.recentApps()] == ["firefox"]
