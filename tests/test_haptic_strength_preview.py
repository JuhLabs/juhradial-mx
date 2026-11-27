#!/usr/bin/env python3
"""Picking a haptic strength plays one pulse at the new strength, once the
daemon has reloaded, and only when the mouse can play it. Several quick picks
give one pulse after the last.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_haptic_strength_preview.py -q
"""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

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
    b.calls, b.replies = [], {}
    b.daemon._available = True
    b.daemon.call_async = lambda m, *a: b.calls.append((m, *a))

    def call_then(m, cb, *a):
        b.calls.append((m, *a))
        cb(b.replies.get(m, []))
    b.daemon.call_then = call_then
    b._hap_dev["levelSupported"] = True
    return b


def _pulses(backend, wait=0.45):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        _qt_app.processEvents()
        time.sleep(0.01)
    return [c for c in backend.calls if c[0] == "TriggerHapticPattern"]


def test_quick_picks_give_one_pulse_after_the_reload(backend):
    backend.setHapticLevel("low")
    backend.setHapticLevel("medium")
    backend.setHapticLevel("high")
    assert _pulses(backend, wait=0) == []
    reloads = [i for i, c in enumerate(backend.calls) if c[0] == "ReloadConfig"]
    assert len(reloads) == 3
    assert len(_pulses(backend)) == 1
    pulse = next(i for i, c in enumerate(backend.calls) if c[0] == "TriggerHapticPattern")
    assert pulse > reloads[-1]
    assert backend.get("haptics.level") == 100


def test_no_pulse_with_haptics_off(backend):
    backend.set("haptics.enabled", False)
    backend.setHapticLevel("low")
    assert _pulses(backend) == []


def test_no_pulse_without_a_motor(backend):
    backend._hap_dev["levelSupported"] = False
    backend.setHapticLevel("low")
    assert _pulses(backend) == []


def test_no_pulse_when_the_reload_fails(backend):
    backend.replies["ReloadConfig"] = None
    backend.setHapticLevel("low")
    assert backend.get("haptics.level") == 50
    assert _pulses(backend) == []
