#!/usr/bin/env python3
"""Haptics tab: every event and pattern the Settings app lists matches the
daemon, styles and Restore apply in one save with Undo, the strength and
Sense Panel steps follow the mouse until you pick one, and a Test that stays
silent says why.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_haptics_backend.py -q
"""
import os
import re
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

CONFIG_RS = (REPO / "daemon" / "src" / "config.rs").read_text()
PATTERNS_RS = (REPO / "daemon" / "src" / "hidpp" / "patterns.rs").read_text()


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    b.replies = {}
    b.daemon._available = True
    b.daemon.call_async = lambda *a, **k: None
    b.daemon.call_then = lambda m, cb, *a: cb(b.replies.get(m, []))
    return b


def test_event_defaults_match_the_daemon():
    for (key, _n, _d, _g, default) in bk.HAPTIC_EVENTS:
        m = re.search(r'fn default_%s\(\) -> String \{ "([a-z_]+)"' % key, CONFIG_RS)
        assert m, key
        assert m.group(1) == default, key
    off = re.search(r'unwrap_or\(!matches!\(key, ([^)]*)\)\)', CONFIG_RS).group(1)
    assert set(re.findall(r'"([a-z_]+)"', off)) == bk.HAPTIC_EVENTS_OFF
    keys = re.findall(r'HapticEvent::\w+ => "([a-z_]+)",', PATTERNS_RS)
    assert set(keys) >= {e[0] for e in bk.HAPTIC_EVENTS}


def test_patterns_are_the_daemons_waveforms():
    names = re.findall(r'^\s+"([a-z_]+)" => Self::\w+,', PATTERNS_RS, re.M)
    assert [p[0] for p in bk.HAPTIC_PATTERNS] == names
    for style in bk.HAPTIC_STYLES.values():
        assert set(style) == {e[0] for e in bk.HAPTIC_EVENTS}
        assert set(style.values()) <= set(names)


def test_events_list_switches_and_availability(backend):
    ev = {e["key"]: e for e in backend.hapticEvents()}
    assert ev["macro_start"]["enabled"] is False and ev["dpi_change"]["enabled"] is True
    backend.setHapticEventEnabled("window_switch", False)
    backend.setHapticEventEnabled("slice_change", False)
    assert backend.get("haptics.window_switch_enabled") is False
    assert backend.get("haptics.per_event_enabled.slice_change") is False
    backend._hap_dev["tracking"] = False
    ev = {e["key"]: e for e in backend.hapticEvents()}
    assert ev["window_switch"]["available"] is False and ev["window_switch"]["reason"]
    assert ev["slice_change"]["enabled"] is False


def test_style_apply_detect_and_undo(backend):
    assert backend.hapticStyle == "balanced"
    before = backend.hapticPatternSnapshot()
    backend.applyHapticStyle("expressive")
    assert backend.hapticStyle == "expressive"
    assert backend.get("haptics.per_event.dpi_change") == "knock"
    backend.setHapticEventPattern("menu_appear", "jingle")
    assert backend.hapticStyle == "custom"
    backend.setHapticPatterns(before)
    assert backend.hapticStyle == "balanced"


def test_strength_follows_the_mouse_until_picked(backend):
    assert backend.hapticLevel == ""
    backend.replies["GetHapticLevel"] = [True, True, 100]
    backend.readHapticDevice()
    assert backend.hapticDevice["levelSupported"] and backend.hapticLevel == "high"
    backend.setHapticLevel("low")
    assert backend.get("haptics.level") == 50 and backend.hapticLevel == "low"


def test_panel_force_steps_from_the_owner_mouse(backend):
    backend.replies["GetForceSense"] = [True, 4625, 7689, 5781, 4625]
    backend.readHapticDevice()
    assert backend.panelForce == "light"
    assert backend.panelForceDefaultPct == 38
    backend.setPanelForce("hard")
    assert backend.get("haptics.panel_force") == 66 and backend.panelForce == "hard"


def test_a_silent_test_says_why(backend):
    seen, toasts = [], []
    backend.hapticTested.connect(lambda p, ok, why: seen.append((p, ok, why)))
    backend.toastRequested.connect(lambda t, k: toasts.append(t))
    backend.replies["TriggerHapticPattern"] = [False, "no_motor"]
    backend.testHaptic("knock")
    assert seen[-1] == ("knock", False, "no_motor") and "motor" in toasts[-1]
    backend.replies["TriggerHapticPattern"] = [True, ""]
    backend.testHaptic("knock")
    assert seen[-1] == ("knock", True, "") and len(toasts) == 1
    backend.daemon.call_then = lambda m, cb, *a: cb(None)
    backend.testHaptic("knock")
    assert seen[-1] == ("knock", False, "service")


def test_muted_apps_and_tick_rate(backend):
    backend.addHapticMutedApp(" Steam ")
    backend.addHapticMutedApp("steam")
    assert backend.hapticMutedApps() == ["steam"]
    backend.removeHapticMutedApp("steam")
    assert backend.hapticMutedApps() == []
    assert backend.sliceTickRate == "balanced"
    backend.setSliceTickRate("calm")
    assert backend.get("haptics.slice_debounce_ms") == 80
    assert backend.appClassFor("org.example.NoSuchApp.desktop") == "nosuchapp"


def test_monitor_switch_has_its_own_switch_the_daemon_reads(backend):
    # #122: haptics.monitor_switch_enabled, separate from the ring's events.
    backend.setHapticEventEnabled("monitor_switch", False)
    assert backend.get("haptics.monitor_switch_enabled") is False
    assert backend.get("haptics.per_event_enabled.monitor_switch") is None
    ev = {e["key"]: e for e in backend.hapticEvents()}
    assert ev["monitor_switch"]["enabled"] is False and ev["monitor_switch"]["available"]
    backend.setHapticEventPattern("monitor_switch", "subtle_collision")
    assert backend.get("haptics.per_event.monitor_switch") == "subtle_collision"
    config_rs = (Path(__file__).resolve().parents[1] / "daemon/src/config.rs").read_text()
    assert "pub monitor_switch_enabled: bool" in config_rs
