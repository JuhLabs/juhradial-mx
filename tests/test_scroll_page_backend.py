#!/usr/bin/env python3
"""Point & Scroll tab: the #108 trio (the wheel selector follows the mouse,
the SmartShift threshold never flips the wheel, the DPI readout keeps
following the mouse), the sensor's DPI range and step, refused hardware
writes, the thumb-wheel Invert that always applies, and the desktop pointer
settings (KWin per device, GNOME, Hyprland, sway, X11).

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_scroll_page_backend.py -q
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
    b.calls = []
    b.reply = []  # what every daemon call answers ([] = ok, None = refused)
    b.daemon._available = True
    b.daemon.call_async = lambda *a, **k: None
    b.daemon.call = lambda *a, **k: None

    def call_then(method, cb, *args):
        b.calls.append((method, args))
        cb(b.reply)
    b.daemon.call_then = call_then
    return b


# ---- #108 ----
def test_wheel_selector_follows_the_mouse(backend):
    backend.setLocal("scroll.mode", "smartshift")
    backend._apply_smartshift([False, 0])  # the mouse is permanently ratcheted
    assert backend.scrollMode == "ratchet"
    backend._apply_smartshift([True, 0])
    assert backend.scrollMode == "freespin"


def test_threshold_never_flips_the_wheel(backend):
    backend.setScrollMode("ratchet")
    backend.calls.clear()
    backend.setSmartShiftThreshold(70)
    assert backend.get("scroll.smartshift_threshold") == 70
    assert backend.calls == []  # saved for later, the wheel stays ratcheted
    backend.setScrollMode("smartshift")
    backend.calls.clear()
    backend.setSmartShiftThreshold(80)
    assert backend.calls and backend.calls[0][0] == "SetSmartShift"
    assert backend.calls[0][1][0] is True


def test_dpi_readout_follows_the_mouse_after_a_drag(tmp_path):
    """The shared Slider keeps its `value` binding through drags and keys."""
    pytest.importorskip("PyQt6.QtQml")  # the Qt settings app is not installed on every CI image
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlComponent, QQmlEngine
    from bridge.theme import Theme
    engine = QQmlEngine()
    theme = Theme()
    engine.rootContext().setContextProperty("Theme", theme)
    comps = (REPO / "settings-qt" / "qml" / "components").as_uri()
    qml = tmp_path / "S.qml"
    qml.write_text('import QtQuick\nimport "%s"\nItem {\n property int live: 1000\n'
                   ' Slider { id: s; objectName: "s"; from: 200; to: 8000; stepSize: 50; value: parent.live }\n'
                   ' property real shown: s.shown\n}\n' % comps)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(qml)))
    root = comp.create()
    assert root is not None, comp.errorString()
    from PyQt6.QtCore import QMetaObject, QObject, Q_ARG, QVariant
    s = root.findChild(QObject, "s")
    # a keyboard step lands where a drag would: _setKey is the Slider's own
    QMetaObject.invokeMethod(s, "_setKey", Q_ARG(QVariant, 1600))
    assert root.property("shown") == 1600      # the dragged value shows
    root.setProperty("live", 2400)             # a DPI button, a profile...
    assert root.property("shown") == 2400      # the binding survived


# ---- DPI range ----
def test_dpi_range_and_snap(backend):
    assert backend.dpiRange["min"] == 200  # fallback until the daemon answers
    backend._apply_dpi_range([400, 1300, 100, 0])
    assert backend.dpiRange == {"min": 400, "max": 1300, "step": 100, "default": 1000}
    backend._apply_dpi_range([200, 8000, 50, 1000])
    assert backend.snapDpi(1234) == 1250
    assert backend.snapDpi(1225) == 1250  # half up, like the daemon
    assert backend.snapDpi(100) == 200
    assert backend.snapDpi(9000) == 8000
    backend._apply_dpi_range([0, 0, 0, 0])  # unknown: keep what we had
    assert backend.dpiRange["max"] == 8000


def test_set_dpi_snaps_and_sends(backend):
    backend.setDpi(1234)
    assert backend.dpi == 1250 and backend.get("pointer.dpi") == 1250
    assert backend.calls[-1][0] == "SetDpi"
    assert backend.hwErrors == {}


def test_refused_dpi_is_undone_and_reported(backend):
    backend._link_daemon = ("connected", "bolt")
    backend.setDpi(1600)
    backend.reply = None
    backend.setDpi(3200)
    assert backend.dpi == 1600 and backend.get("pointer.dpi") == 1600
    assert backend.hwErrors["dpi"]["error"] is True


def test_dpi_while_asleep_is_kept_for_the_wake(backend):
    backend._link_daemon = ("asleep", "bolt")
    backend.reply = None
    backend.setDpi(3200)
    assert backend.dpi == 3200 and backend.get("pointer.dpi") == 3200
    assert backend.hwErrors["dpi"]["error"] is False
    backend.reply = []
    backend._link_daemon = ("connected", "bolt")
    backend.setDpi(3200)
    assert "dpi" not in backend.hwErrors


def test_refused_mode_restores_an_absent_key(backend):
    backend._link_daemon = ("connected", "bolt")
    assert backend.get("scroll.mode") is None
    backend.reply = None
    backend.setScrollMode("freespin")
    assert backend.get("scroll.mode") is None  # never forced onto the mouse by replay


def test_dpi_presets_and_precision(backend):
    assert backend.dpiPresets() == [800, 1600, 3200]  # the daemon's cycle default
    backend.setDpiPresets([3210, 800, 800, 100])
    assert backend.get("pointer.dpi_presets") == [200, 800, 3200]
    assert backend.dpiShift == 400
    backend.setDpiShift(433)
    assert backend.get("pointer.dpi_shift") == 450


# ---- thumb wheel ----
def test_thumbwheel_invert_always_applies(backend):
    assert [m["id"] for m in backend.thumbwheelModes()] == ["off", "volume", "zoom"]
    backend.setThumbwheelInvert(True)
    assert backend.get("thumbwheel.mode") == "scroll"  # the mode the daemon inverts (#127)
    assert backend.thumbwheelMode == "off"             # one "Horizontal scroll"
    backend.setThumbwheelMode("volume")
    assert backend.get("thumbwheel.mode") == "volume"
    backend.setThumbwheelMode("off")
    assert backend.get("thumbwheel.mode") == "scroll"
    backend.setThumbwheelInvert(False)
    assert backend.get("thumbwheel.mode") == "off"


def test_app_profile_thumbwheel_follows_invert(backend):
    backend.setThumbwheelInvert(True)
    backend.saveAppProfile("gimp", {"dpi": 1234, "thumbwheel": "off",
                                    "overrides": {"dpi": True, "thumbwheel": True}})
    prof = backend._load_profiles()["hardware"]["gimp"]
    assert prof["thumbwheel"] == "scroll" and prof["dpi"] == 1250
    assert backend.appProfiles()[0]["thumbwheel"] == "off"


# ---- desktop pointer settings ----
@pytest.mark.parametrize("env,desk,speed,accel", [
    ({"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}, "kde", "kde", "kde"),
    ({"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "x11"}, "x11", "imwheel", "xinput"),
    ({"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"}, "gnome", "", "gsettings"),
    ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "x11"}, "gnome", "imwheel", "gsettings"),
    ({"XDG_CURRENT_DESKTOP": "Hyprland", "HYPRLAND_INSTANCE_SIGNATURE": "x"}, "hyprland", "hyprland", "hyprland"),
    ({"XDG_CURRENT_DESKTOP": "sway", "XDG_SESSION_TYPE": "wayland"}, "sway", "sway", "sway"),
    ({"XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11"}, "x11", "imwheel", "xinput"),
    ({"XDG_CURRENT_DESKTOP": "COSMIC", "XDG_SESSION_TYPE": "wayland"}, "", "", ""),
])
def test_each_desktop_gets_its_own_knob(env, desk, speed, accel):
    have = lambda _tool: "/usr/bin/x"  # noqa: E731
    assert bk.pointer_desktop(env) == desk
    assert bk.scroll_speed_method(env, have)[0] == speed
    assert bk.accel_method(env, have)[0] == accel
    if speed == "":
        assert bk.scroll_speed_method(env, have)[1]  # says why
    none = lambda _tool: None  # noqa: E731
    if speed == "imwheel":
        m, why = bk.scroll_speed_method(env, none)
        assert m == "" and "imwheel" in why


def test_scroll_speed_readout_matches_the_desktop():
    assert bk.speed_for_factor(1.0) == 4
    assert bk.speed_for_factor(0.834) == 3
    assert bk.speed_for_factor(9) == 10
    assert bk.scroll_lines("kde", 4) == 3.0
    assert bk.scroll_lines("imwheel", 2) == 6


def test_xinput_parsing():
    names = "Virtual core pointer\nLogitech USB Receiver Mouse\nAT Keyboard\nMX Master 4\n"
    ids = "2\n11\n14\n17\n"
    assert bk.xinput_ids(names, ids) == ["11", "17"]
    props = ('Device \'x\':\n\tlibinput Accel Profile Enabled (301):\t1, 0, 0\n'
             '\tlibinput Natural Scrolling Enabled (290):\t0\n')
    assert bk.xinput_prop(props, "libinput Accel Profile Enabled") == ["1", "0", "0"]
    assert bk.xinput_prop(props, "libinput Natural Scrolling Enabled") == ["0"]
    assert bk.xinput_prop(props, "nope") is None


def test_kwin_writes_only_logitech_pointers(backend):
    """KDE Wayland: scroll factor and acceleration go to each Logitech
    pointer in KWin (the [Mouse] group of 0.4.4 never reached KWin)."""
    vendors = {"event4": 1133, "event9": 1133, "event20": 1267, "event24": 4660}
    sets = []

    def kwin_then(path, iface, method, args, cb):
        if method == "ListPointers":
            cb([list(vendors)])
        elif method == "Get":
            cb([vendors[path.rsplit("/", 1)[1]]])
        elif method == "Set":
            sets.append((path, args[1], args[2].variant()))
            cb([])
    backend._kwin_then = kwin_then
    backend._kwin_set("scrollFactor", 1.5)
    assert sets == [(f"{bk.KWIN_INPUT}/event4", "scrollFactor", 1.5),
                    (f"{bk.KWIN_INPUT}/event9", "scrollFactor", 1.5)]
