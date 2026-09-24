#!/usr/bin/env python3
"""The overlay tray shows device, battery, host and profile, badges the icon
and raises one low-battery notification.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_tray_status.py -q
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "overlay"))

from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QPixmap  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])

import overlay_tray as ot  # noqa: E402


class FakeTray:
    def __init__(self):
        self.tooltip = ""
        self.icon = None

    def setToolTip(self, text):
        self.tooltip = text

    def setIcon(self, icon):
        self.icon = icon


def _base_icon():
    pm = QPixmap(64, 64)
    pm.fill(QColor("#7C5CFF"))
    return QIcon(pm)


def _badge_pixel(icon, size=64):
    """Colour at the badge's centre (bottom-right corner)."""
    img = icon.pixmap(size, size).toImage()
    return img.pixelColor(size - 12, size - 12)


@pytest.fixture
def status():
    tray = FakeTray()
    notes = []
    st = ot.TrayStatus(tray, _base_icon(), bus=False, notify=lambda d, p: notes.append((d, p)))
    return st, tray, notes


def test_tooltip_lines():
    assert ot.tooltip("", None, False, 0, 0, [], "") == "JuhRadial MX"
    assert ot.tooltip("MX Master 4", 87, False, 0, 3, ["JULIANWINDOWS", "MacBook Pro", ""], "") == (
        "JuhRadial MX\nMX Master 4: 87%\nHost 1 of 3: JULIANWINDOWS")
    assert ot.tooltip("MX Master 4", 42, True, 2, 3, ["a", "b", ""], "firefox") == (
        "JuhRadial MX\nMX Master 4: 42%, charging\nHost 3 of 3\nProfile: firefox")
    assert ot.tooltip("MX Master 3S", None, False, 0, 0, [], "") == (
        "JuhRadial MX\nMX Master 3S: battery unknown")


def test_badge_letter():
    assert ot.badge_letter("") == ""
    assert ot.badge_letter("firefox") == "F"
    assert ot.badge_letter("org.kde.dolphin") == "O"


def test_render_icon_badges_only_when_needed():
    base = _base_icon()
    assert ot.render_icon(base, "", False) is base
    low = ot.render_icon(base, "", True)
    assert not low.isNull()
    assert _badge_pixel(low).red() > 180 and _badge_pixel(low).blue() < 120
    profile = ot.render_icon(base, "F", False)
    assert _badge_pixel(profile).blue() > 180
    both = ot.render_icon(base, "F", True)
    assert _badge_pixel(both).red() > 180
    # the top-left stays the base colour under every badge
    assert low.pixmap(64, 64).toImage().pixelColor(6, 6).name() == "#7c5cff"


def test_state_updates_reach_the_tray(status):
    st, tray, _notes = status
    assert tray.tooltip == "JuhRadial MX"
    st.set_device("MX Master 4")
    st.set_battery(63, "discharging")
    assert tray.tooltip == "JuhRadial MX\nMX Master 4: 63%"
    st._set_easy_switch([3, 1])
    st._set_host_names([["JULIANWINDOWS", "MacBook Pro", "macbook-air"]])
    assert tray.tooltip.endswith("Host 2 of 3: MacBook Pro")
    st.set_host(0)
    assert tray.tooltip.endswith("Host 1 of 3: JULIANWINDOWS")
    st.set_profile("firefox")
    assert tray.tooltip.endswith("Profile: firefox")
    assert _badge_pixel(tray.icon).blue() > 180
    st.set_profile("")
    assert "Profile" not in tray.tooltip
    assert tray.icon is st.base_icon


def test_low_battery_notifies_once_with_hysteresis(status):
    st, tray, notes = status
    st.set_device("MX Master 4")
    st.set_battery(14, "discharging")
    assert notes == [("MX Master 4", 14)]
    assert _badge_pixel(tray.icon).red() > 180
    st.set_battery(12, "discharging")
    assert len(notes) == 1, "no repeat while still low"
    st.set_battery(18, "discharging")
    st.set_battery(11, "discharging")
    assert len(notes) == 1, "18% is inside the hysteresis band"
    st.set_battery(25, "discharging")
    st.set_battery(10, "discharging")
    assert len(notes) == 2, "re-arms above 20%"
    st.set_battery(9, "charging")
    assert tray.icon is st.base_icon, "charging clears the low badge"
    assert len(notes) == 2


def test_byte_arguments_arrive_as_bytes_or_int(status):
    st, tray, _ = status
    st._set_easy_switch([b"\x03", b"\x02"])
    assert (st.num_hosts, st.host) == (3, 2)
    assert ot._int(b"\x40") == 64 and ot._int(7) == 7


def test_empty_device_name_is_ignored(status):
    st, tray, _ = status
    st.set_device("MX Master 4")
    st.set_device("")
    assert st.device == "MX Master 4"


def test_settings_app_defers_the_low_battery_notice_to_a_running_overlay(monkeypatch, tmp_path):
    sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))
    import bridge.backend as bk
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    sent = []
    monkeypatch.setattr(bk.subprocess, "Popen", lambda args, **kw: sent.append(args))
    monkeypatch.setattr(bk.Backend, "_overlay_running", staticmethod(lambda: True))
    b._maybe_low_battery_notify(10)
    assert sent == []
    b._low_batt_notified = False
    monkeypatch.setattr(bk.Backend, "_overlay_running", staticmethod(lambda: False))
    b._maybe_low_battery_notify(10)
    assert len(sent) == 1 and sent[0][0] == "notify-send"


def test_overlay_running_reads_the_reply_value():
    sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))
    import bridge.backend as bk
    # Must be a real bool answer, never the always-truthy QDBusReply object.
    assert isinstance(bk.Backend._overlay_running(), bool)


def test_tray_gaming_entry_follows_and_switches(status):
    from PyQt6.QtGui import QAction
    st, _tray, _notes = status
    sent = []

    class FakeIface:
        def asyncCall(self, method, *args):
            sent.append((method, args))
    action = QAction("Gaming mode")
    st.bind_gaming_action(action)
    assert action.isCheckable() and not action.isChecked()
    st.set_gaming(True)          # GamingModeChanged from anywhere
    assert action.isChecked() and sent == []   # following never sends
    st._iface = FakeIface()
    action.trigger()             # a click in the tray menu
    assert sent == [("SetGamingMode", (False,))]
