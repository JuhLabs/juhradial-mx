#!/usr/bin/env python3
"""Devices tab backend: battery status words, keyboard backlight read-back and
writes, battery alerts for the mouse and the keyboard, firmware and refresh
time from the prime round, this mouse's own settings, and Copy diagnostics.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_devices_backend.py -q
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))

from PyQt6.QtDBus import QDBusArgument  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])

import bridge.backend as bk  # noqa: E402


class FakeDaemon:
    available = True

    def __init__(self):
        self.calls = []
        self.answers = {}

    def call(self, method, *args):
        self.calls.append((method, args))
        return self.answers.get(method)

    def call_then(self, method, callback, *args):
        self.calls.append((method, args))
        callback(self.answers.get(method))

    def prop_then(self, name, callback):
        callback(self.answers.get(name))

    def call_async(self, *a, **k):
        pass


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    monkeypatch.setattr(bk.Backend, "_detect_connection", staticmethod(lambda generic=False: "Bolt receiver"))
    monkeypatch.setattr(bk.Backend, "_overlay_running", staticmethod(lambda: False))
    b = bk.Backend()
    b.daemon = FakeDaemon()
    b.reloadConfig = lambda: None
    return b


def test_only_charging_counts_as_charging(backend):
    for status, charging in (("charging", True), ("full", False), ("not_charging", False),
                             ("discharging", False), ("unknown", False)):
        backend._set_battery(80, status)
        assert backend.charging is charging, status


BACKLIGHT = [True, True, 3, 5, 8, 5, True, 55, 55, 300]


def test_backlight_read_back_lands_in_the_keyboard_info(backend):
    info = backend._keyboard_info([90, False], [True], [[]], BACKLIGHT)
    bl = info["backlight"]
    assert bl["ok"] and bl["mode"] == 3 and bl["level"] == 5 and bl["levels"] == 8
    assert bl["percent"] == 71 and bl["autoSupported"] and (bl["away"], bl["powered"]) == (55, 300)
    # support off, asleep, or an older daemon without the method
    for r in (None, [], [False, False, 0, 0, 0, 255, False, 0, 0, 0]):
        assert backend._keyboard_info([0, False], [True], [[]], r)["backlight"] == {"ok": False}


def test_request_keyboard_info_reads_the_backlight_last(backend):
    backend.daemon.answers = {"GetKeyboardBattery": [70, False], "GetKeyboardPaired": [True],
                              "ListKeyboardKeys": [[]], "GetKeyboardBacklight": BACKLIGHT}
    seen = []
    backend.keyboardInfoReady.connect(lambda info: seen.append(dict(info)))
    backend.requestKeyboardInfo()
    assert [m for m, _a in backend.daemon.calls] == [
        "GetKeyboardBattery", "GetKeyboardPaired", "ListKeyboardKeys", "GetKeyboardBacklight"]
    assert seen[-1]["backlight"]["ok"] and seen[-1]["battery"] == 70


def test_backlight_writes_are_typed_and_read_back(backend):
    backend.daemon.answers = {"SetKeyboardBacklightMode": [True],
                              "SetKeyboardBacklightDurations": [True],
                              "SetKeyboardBacklight": [False]}
    toasts = []
    backend.toastRequested.connect(lambda text, kind: toasts.append(kind))
    backend.setKeyboardBacklightAuto(True)
    backend.setKeyboardBacklightDuration(30, 0)
    backend.setKeyboardBacklight(50)
    calls = backend.daemon.calls
    mode = next(a for m, a in calls if m == "SetKeyboardBacklightMode")
    assert mode == (True,)
    durations = next(a for m, a in calls if m == "SetKeyboardBacklightDurations")
    assert len(durations) == 3 and all(isinstance(a, QDBusArgument) for a in durations)
    # every write is followed by a fresh read of the keyboard
    assert sum(1 for m, _a in calls if m == "GetKeyboardBacklight") == 3
    assert toasts == ["warning"], "a refused write says so once"


def test_backlight_durations_offer_the_hardware_range(backend):
    ids = [int(d["id"]) for d in backend.backlightDurations(0)]
    assert ids == sorted(ids) and ids[0] >= 5 and ids[-1] == 7200 and 1800 in ids
    # a value set elsewhere (Options+ on another computer) stays selectable
    odd = [int(d["id"]) for d in backend.backlightDurations(45)]
    assert 45 in odd and odd == sorted(odd)


def test_battery_alerts_follow_the_config(backend, monkeypatch):
    sent = []
    monkeypatch.setattr(bk.subprocess, "Popen", lambda args, **kw: sent.append(args))
    assert backend._battery_alerts() == (15, True, True)
    backend.set("battery.alert_percent", 20)
    backend._charging = False
    backend._maybe_low_battery_notify(19)
    assert len(sent) == 1 and "Mouse" in sent[0][7]
    backend._maybe_low_battery_notify(18)
    assert len(sent) == 1, "once per discharge"
    backend._maybe_kb_low_notify(20, False)
    assert len(sent) == 2 and "Keyboard" in sent[1][7]
    backend._maybe_kb_low_notify(26, False)          # above level + 5: re-arms
    backend.set("battery.alert_keyboard", False)
    backend._maybe_kb_low_notify(10, False)
    assert len(sent) == 2
    backend._maybe_low_battery_notify(0)
    assert len(sent) == 2, "0 % is no reading"


def test_keyboard_push_raises_the_fallback_alert(backend, monkeypatch):
    sent = []
    monkeypatch.setattr(bk.subprocess, "Popen", lambda args, **kw: sent.append(args))
    backend.daemon.keyboardBatteryChanged = None
    backend._on_keyboard_battery(9, False)
    assert len(sent) == 1


def test_prime_reads_firmware_and_stamps_the_refresh(backend):
    backend.daemon.answers = {"GetFirmware": [["RBM 27.00.B0015", "RBM 27.03.B0019"]],
                              "GetDeviceName": ["MX Master 4"]}
    assert backend.refreshedAt == 0
    backend._prime()
    assert backend.firmware == ["RBM 27.00.B0015", "RBM 27.03.B0019"]
    assert backend.refreshedAt > 0


def test_this_mouses_own_settings_review_and_reset(backend):
    backend._unit_id = "0x37FC2B99"
    assert backend.deviceOverrides() == []
    backend.set("devices", {"0x37FC2B99": {"buttons": {"back": "copy", "controls": {"0x00D7": "paste"}}},
                            "0x11111111": {"buttons": {"back": "undo"}}})
    assert backend.deviceOverrides() == ["buttons.back", "buttons.controls.0x00D7"]
    backend.resetDeviceOverrides()
    assert backend.deviceOverrides() == []
    assert backend.get("devices") == {"0x11111111": {"buttons": {"back": "undo"}}}, "other mice keep theirs"


def test_diagnostics_carry_firmware_keyboard_and_journal(backend, monkeypatch):
    class R:
        stdout = "Sep 24 juhradiald[1]: Mouse link changed"
        stderr = ""
    monkeypatch.setattr(bk.subprocess, "run", lambda *a, **k: R())
    backend._firmware = ["RBM 27.00.B0015"]
    backend._kb_info = {"enabled": True, "present": True, "sleeping": True}
    text = backend._diagnostics()
    assert "Firmware: RBM 27.00.B0015" in text
    assert "Keyboard: on, present, asleep" in text
    assert "Mouse link changed" in text


def test_generic_trigger_names_are_plain_words(backend):
    names = [o["name"] for o in backend.genericTriggerOptions()]
    assert names and not any("BTN_" in n for n in names)
