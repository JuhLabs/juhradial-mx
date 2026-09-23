#!/usr/bin/env python3
"""Dashboard (audit 4.1): health issues with their fix, the first-run
checklist, the active app profile and whether Easy-Switch slots are known.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_dashboard_backend.py -q
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


def test_health_names_the_fix(backend, monkeypatch):
    monkeypatch.setattr(type(backend.daemon), "available", property(lambda self: False))
    assert [i["id"] for i in backend.healthIssues()] == ["daemon"]
    monkeypatch.setattr(type(backend.daemon), "available", property(lambda self: True))
    monkeypatch.setattr(bk.Backend, "_overlay_running", staticmethod(lambda: False))
    monkeypatch.setattr(bk.Backend, "daemonVersion", property(lambda self: "0.4.4"))
    monkeypatch.setattr(bk.Backend, "appVersion", property(lambda self: "0.4.5"))
    backend.setLocal("app.start_at_login", False)
    ids = [i["id"] for i in backend.healthIssues()]
    assert ids == ["overlay", "version"]


def test_onboarding_ticks_itself_off(backend):
    steps = {s["id"]: s["done"] for s in backend.onboarding()}
    assert steps == {"ring": False, "button": False, "skin": False}
    backend.daemon.menuRequested.emit()
    backend.setButtonIn("", "back", "copy")
    backend.set("radial.wheel", "azure")
    assert all(s["done"] for s in backend.onboarding())
    backend.finishOnboarding()
    assert backend.onboarding() == []


def test_active_profile_and_hosts(backend):
    backend.daemon.activeProfileChanged.emit("firefox")
    assert backend.activeProfile == "firefox"
    backend.daemon.activeProfileChanged.emit("")
    assert backend.activeProfile == ""
    assert backend.hostsKnown is False
