#!/usr/bin/env python3
"""Settings offers a profile once for an app the daemon announces (NewAppSeen).

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_new_app_prompt.py -q
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))

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
    monkeypatch.setattr(bk.Backend, "_app_display_name", staticmethod(lambda app: app.title()))
    b = bk.Backend()
    b.daemon.call_async = lambda *a, **k: None
    return b


def _signals(backend):
    seen = []
    backend.profileSuggested.connect(lambda: seen.append(True))
    return seen


def test_new_app_is_offered_once(backend, tmp_path):
    seen = _signals(backend)
    backend.daemon.newAppSeen.emit("GIMP")
    assert seen == [True]
    assert backend.takeProfileSuggestion() == {"app": "gimp", "name": "Gimp"}
    assert backend.takeProfileSuggestion() is None, "a suggestion is taken once"
    assert json.loads((tmp_path / "config.json").read_text())["app"]["profile_prompted"] == ["gimp"]
    backend.daemon.newAppSeen.emit("gimp")
    assert seen == [True], "an app that was offered is never offered again"


def test_own_windows_shell_and_existing_profiles_are_skipped(backend):
    seen = _signals(backend)
    backend.addAppProfile("firefox")
    for app in ("org.kde.juhradialmx.settings", "plasmashell", "firefox", "Firefox", "", "  "):
        backend.daemon.newAppSeen.emit(app)
    assert seen == []


def test_switch_off_stops_suggestions(backend):
    seen = _signals(backend)
    backend.setLocal("app.suggest_profiles", False)
    backend.daemon.newAppSeen.emit("inkscape")
    assert seen == []
    assert backend.takeProfileSuggestion() is None


def test_profile_created_meanwhile_cancels_the_pending_offer(backend):
    backend.daemon.newAppSeen.emit("krita")
    backend.addAppProfile("krita")
    assert backend.takeProfileSuggestion() is None


def test_prompted_list_is_capped(backend):
    backend.setLocal("app.profile_prompted", [f"app{i}" for i in range(bk.Backend.PROMPTED_MAX)])
    backend.daemon.newAppSeen.emit("newest")
    assert backend.takeProfileSuggestion()["app"] == "newest"
    prompted = backend.get("app.profile_prompted")
    assert len(prompted) == bk.Backend.PROMPTED_MAX and prompted[-1] == "newest"


def test_daemon_signal_is_subscribed_with_an_empty_service_name():
    src = (REPO_ROOT / "settings-qt" / "bridge" / "backend.py").read_text(encoding="utf-8")
    assert 'self._bus.connect("", OBJ_PATH, IFACE, "NewAppSeen", self._on_new_app)' in src
