#!/usr/bin/env python3
"""Backend._prime never blocks the UI thread on D-Bus (PR #66 goal).

Every getter goes through call_then/prop_then, one call in flight at a time,
readouts update as answers land (#13/#108), `primed` turns true once and a
round superseded by a daemon restart is dropped. Also covers the new caps and
linkState properties and their fallbacks for the older installed daemon.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_settings_prime.py -q
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


class FakeDaemon:
    """Records async calls; answers are fed by the test. Any blocking call
    during a prime is a failure."""

    def __init__(self, available=True):
        self.available = available
        self.pending = []   # (method, callback)
        self.blocking = []

    def call(self, method, *args):
        self.blocking.append(method)
        return None

    def call1(self, method, *args, default=None):
        self.blocking.append(method)
        return default

    def prop(self, name, default=None):
        self.blocking.append(name)
        return default

    def call_async(self, *a, **k):
        pass

    def call_then(self, method, callback, *args):
        self.pending.append((method, callback))

    def prop_then(self, name, callback):
        self.pending.append((name, callback))

    def answer(self, value):
        method, cb = self.pending.pop(0)
        cb(value)
        return method


ANSWERS = {
    "GetDeviceName": ["MX Master 4"],
    "GetUnitId": ["0x1234ABCD"],
    "GetDeviceMode": ["logitech"],
    "DaemonVersion": "0.4.5",
    "GetDeviceConnection": ["asleep", "bolt"],
    "GetCapabilities": [{"dpi": True, "haptics": True, "force_sense": True}],
    "GetBatteryStatus": [80, False],
    "GetDpi": [1500],
    "GetDpiRange": [200, 8000, 50, 1000],
    "GetScrollForce": [True, 100, 75],
    "GetSmartShift": [True, 12],
    "SmartShiftSupported": [True],
    "ThumbwheelSupported": [True],
    "DpiSupported": [True],
    "GetGamingStatus": [False, False, 2, 0, True, False],
    "GetEasySwitchInfo": [3, 1],
    "GetHostNames": [["LINUX", "MAC", ""]],
    "GetFirmware": [["RBM 27.00.B0015"]],
}


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    monkeypatch.setattr(bk.Backend, "_detect_connection", staticmethod(lambda generic=False: "Bolt receiver"))
    b = bk.Backend()
    b.daemon = FakeDaemon()
    return b


def _drain(b, answers=ANSWERS):
    seen = []
    while b.daemon.pending:
        method = b.daemon.pending[0][0]
        seen.append(method)
        b.daemon.answer(answers.get(method))
    return seen


def test_prime_is_fully_async_and_one_call_at_a_time(backend):
    backend._prime()
    assert len(backend.daemon.pending) == 1          # one in flight
    seen = _drain(backend)
    assert backend.daemon.blocking == []             # nothing synchronous
    assert set(seen) == set(ANSWERS)
    assert backend.primed
    assert backend.deviceName == "MX Master 4"
    assert backend.dpi == 1500 and backend.battery == 80
    assert backend.wheelMode == "smartshift"
    assert backend.currentHost == 1 and backend.hostNames == ["LINUX", "MAC", ""]
    assert backend.linkState == "asleep" and backend.transport == "bolt"
    assert backend.caps["force_sense"] is True and backend.hapticsSupported
    assert backend.firmware == ["RBM 27.00.B0015"]


def test_readouts_update_as_answers_land(backend):
    updates = []
    backend.liveChanged.connect(lambda: updates.append(backend.deviceName))
    backend._prime()
    backend.daemon.answer(ANSWERS["GetDeviceName"])
    assert updates and updates[-1] == "MX Master 4"
    assert not backend.primed


def test_primed_turns_true_once_and_stays(backend):
    fired = []
    backend.primedChanged.connect(lambda: fired.append(True))
    backend._prime()
    _drain(backend)
    backend._prime()
    _drain(backend)
    assert fired == [True] and backend.primed


def test_superseded_round_is_dropped(backend):
    backend._prime()
    stale = backend.daemon.pending.pop(0)            # GetDeviceName of round 1
    backend._prime()                                  # daemon restarted
    _drain(backend)
    stale[1](["Stale Mouse"])
    assert backend.deviceName == "MX Master 4"


def test_a_late_prime_answer_keeps_the_users_dpi(backend):
    backend._prime()
    backend.setDpi(2400)
    _drain(backend, dict(ANSWERS, SetDpi=[]))  # the mouse took it
    assert backend.dpi == 2400
    assert backend.dpiRange == {"min": 200, "max": 8000, "step": 50, "default": 1000}


def test_old_daemon_fallbacks(backend):
    old = dict(ANSWERS, GetDeviceConnection=None, GetCapabilities=None)
    backend._prime()
    _drain(backend, old)
    assert backend.linkState == "connected"
    assert backend.transport == "bolt"                # from the sysfs guess
    assert backend.caps == {"dpi": True, "smartshift": True, "thumbwheel": True,
                            "haptics": True}


def test_unavailable_daemon_is_offline_and_primed(backend):
    backend.daemon = FakeDaemon(available=False)
    backend._prime()
    assert backend.linkState == "offline" and backend.primed and backend.caps == {}


def test_link_signal_updates_state_and_refreshes_caps(backend):
    backend._prime()
    _drain(backend)
    backend._set_link_live("connected", "bolt")
    assert backend.linkState == "connected"
    assert backend.daemon.pending[0][0] == "GetCapabilities"


def test_no_qdbusinterface_and_link_signal_uses_empty_service_name():
    src = (REPO_ROOT / "settings-qt" / "bridge" / "backend.py").read_text(encoding="utf-8")
    assert "QDBusInterface(" not in src
    assert 'self._bus.connect("", OBJ_PATH, IFACE, "DeviceConnectionChanged", self._on_link)' in src


def test_scroll_force_primes_saves_and_reverts_a_refusal(backend, monkeypatch):
    backend._prime()
    _drain(backend)
    assert backend.scrollForce == {"supported": True, "value": 100, "default": 75}
    monkeypatch.setattr(bk.Backend, "linkState", property(lambda self: "connected"))
    backend.setScrollForce(60)
    assert backend.daemon.pending[0][0] == "SetScrollForce"
    backend.daemon.answer([True])
    assert backend.get("scroll.force") == 60 and backend.scrollForce["value"] == 60
    backend.setScrollForce(250)  # clamped
    backend.daemon.answer([False])  # a connected mouse refused: back to 60
    assert backend.get("scroll.force") == 60 and backend.scrollForce["value"] == 60
    assert "force" in backend.hwErrors


def test_try_now_holds_the_app_for_a_minute_and_stops(backend):
    backend.tryAppProfile("firefox")
    assert backend.daemon.pending[0][0] == "TryAppProfile"
    backend.daemon.answer([True])
    assert backend.trialApp == "firefox" and backend._trial_timer.isActive()
    backend.stopAppProfileTrial()
    assert backend.daemon.pending[0][0] == "StopAppProfileTrial"
    assert backend.trialApp == "" and not backend._trial_timer.isActive()
    backend.tryAppProfile("code")
    backend.daemon.answer(None)  # service down: nothing is being tried
    assert backend.trialApp == ""
