#!/usr/bin/env python3
"""The Devices card follows the keyboard live: KeyboardBatteryChanged from
the daemon (sent when a key press re-links the MX Keys S) marks it awake with
the fresh battery, and the last reading stays on screen while it is parked.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_keyboard_live.py -q
"""

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


def _kb_updates(backend):
    seen = []
    backend.keyboardInfoReady.connect(lambda info: seen.append(dict(info)))
    return seen


def test_keyboard_battery_push_marks_the_keyboard_awake(backend):
    backend.setLocal("keyboard.mx_keys.enabled", True)
    seen = _kb_updates(backend)
    # the page opened while the radio was parked
    asleep = backend._keyboard_info([0, False], [True], [["30", "31"]])
    backend._kb_info = asleep
    assert asleep["sleeping"] and asleep["present"]
    backend.daemon.keyboardBatteryChanged.emit(88, False)
    assert seen[-1]["sleeping"] is False and seen[-1]["battery"] == 88
    assert seen[-1]["present"] and seen[-1]["keyCount"] == 2 and seen[-1]["enabled"]
    # parked again on the next page open: the last reading is kept for display
    again = backend._keyboard_info([0, False], [True], [[]])
    assert again["sleeping"] and again["lastBattery"] == 88


def test_keyboard_battery_push_ignores_empty_readings(backend):
    seen = _kb_updates(backend)
    backend.daemon.keyboardBatteryChanged.emit(0, False)
    assert seen == []


def test_keyboard_battery_signal_is_subscribed_with_an_empty_service_name():
    src = (REPO_ROOT / "settings-qt" / "bridge" / "backend.py").read_text(encoding="utf-8")
    assert 'self._bus.connect("", OBJ_PATH, IFACE, "KeyboardBatteryChanged", self._on_kb_battery)' in src


def test_backlight_keys_move_the_card_without_a_read(backend):
    seen = _kb_updates(backend)
    backend.daemon.keyboardBacklightChanged.emit(3, 8, 4)
    assert seen == []  # nothing shown yet: the next full read brings it
    backend._kb_info = {"present": True, "backlight": {"ok": True, "level": 7, "levels": 8, "percent": 100}}
    backend.daemon.keyboardBacklightChanged.emit(3, 8, 4)
    light = seen[-1]["backlight"]
    assert (light["level"], light["levels"], light["percent"], light["status"]) == (3, 8, 43, 4)
    src = (REPO_ROOT / "settings-qt" / "bridge" / "backend.py").read_text(encoding="utf-8")
    assert 'self._bus.connect("", OBJ_PATH, IFACE, "KeyboardBacklightChanged", self._on_kb_backlight)' in src
