#!/usr/bin/env python3
"""Buttons tab P0 fixes (audit P0 #3, #8): picked apps show their own name on
the wheel, quick links edit every submenu slice and never save a bare
https://, the MX3 pins are stored where they are read, the thumb-wheel
callout drives thumbwheel.mode, and pickers only offer actions that work.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_buttons_page_backend.py -q
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


def test_picked_app_gets_its_own_action_id_and_label(backend):
    row = next(i for i, s in enumerate(backend.slices.slices()) if s.get("action_id") == "files")
    backend.slices.setApp(row, "gimp", "GIMP", "/tmp/gimp.png")
    s = backend.slices.slices()[row]
    assert s["action_id"] == "custom_app" and s["label"] == "GIMP" and s["command"] == "gimp"
    # the overlay's label lookup no longer resolves it to the preset name
    sys.path.insert(0, os.fspath(REPO / "overlay"))
    import settings_constants
    assert settings_constants.translate_radial_label("GIMP", "custom_app") != "Files"


def test_quick_links_on_every_submenu_slice(backend):
    slices = backend.slices.slices()
    slices[0]["type"] = "submenu"
    backend.slices.load(slices)
    rows = [r["row"] for r in backend.submenuRows()]
    assert 0 in rows and len(rows) >= 2
    backend.setLinksFor(0, [{"name": "Docs", "url": "example.org"},
                            {"name": "Empty", "url": "https://"},
                            {"name": "", "url": "https://x.org"}])
    assert backend.linksFor(0) == [{"name": "Docs", "url": "https://example.org",
                                    "icon": "browser", "command": ""}]
    other = [r for r in rows if r != 0][0]
    assert backend.linksFor(other)[0]["name"] != "Docs"     # independent lists


def test_clean_url():
    assert bk.Backend._clean_url("https://") == ""
    assert bk.Backend._clean_url("  ") == ""
    assert bk.Backend._clean_url("claude.ai") == "https://claude.ai"
    assert bk.Backend._clean_url("http://x.org/a") == "http://x.org/a"


def test_mx3_pins_are_nested_where_the_page_reads_them(backend):
    backend.setPinPos("mx3.back", 0.5, 0.25)
    assert backend.get("button_pins.mx3.back") == {"nx": 0.5, "ny": 0.25}
    backend.setPinPos("back", 0.1, 0.2)
    assert backend.get("button_pins.back") == {"nx": 0.1, "ny": 0.2}


def _daemon_action_ids():
    """Every ButtonAction id the daemon parses (its Display strings, which a
    config.rs test pins to the serde names)."""
    import re
    src = (REPO / "daemon" / "src" / "config.rs").read_text(encoding="utf-8")
    return set(re.findall(r'ButtonAction::\w+ => write!\(f, "([a-z0-9_]+)"\)', src))


def test_pickers_offer_only_working_actions(backend):
    offered = [a for a in backend.buttonActions() if not a["hidden"]]
    ids = [a["id"] for a in offered]
    # "custom" is back now that it has an editor; the native thumb-wheel
    # mode is a no-op on a button and only names old configs.
    assert {"custom", "smartshift", "middle_click", "dpi_shift", "host_next", "tab_reopen"} <= set(ids)
    assert "scroll_left_right" not in ids
    assert set(a["id"] for a in backend.buttonActions()) <= _daemon_action_ids()
    assert all(a["groupName"] for a in offered)
    gesture = {a["id"] for a in backend.gestureActions()}
    assert not gesture & {"radial_menu", "dpi_shift", "custom", "scroll_left_right"}
    assert "tab_close" in gesture


def test_scoped_buttons_follow_all_apps_until_set(backend):
    assert backend.buttonAction("firefox", "back", "back") == "back"
    backend.setButtonIn("firefox", "back", "tab_close")
    assert backend.buttonAction("firefox", "back", "back") == "tab_close"
    assert backend.hasOverride("firefox", "back") and not backend.hasOverride("firefox", "forward")
    assert backend.buttonAction("", "back", "back") == "back", "all apps untouched"
    assert "firefox" in [s["id"] for s in backend.buttonScopes()]
    backend.restoreButton("firefox", "back")
    assert not backend.hasOverride("firefox", "back")
    # an extra control keyed by CID
    backend.setButtonIn("", "0x00D7", "copy")
    assert backend.get("buttons.controls.0x00D7") == "copy"


def test_this_mouse_scope_writes_device_overrides(backend):
    assert "@mouse" not in [s["id"] for s in backend.buttonScopes()], "no unit id yet"
    backend._unit_id = "0x1234ABCD"
    assert "@mouse" in [s["id"] for s in backend.buttonScopes()]
    backend.setButtonIn("@mouse", "middle", "copy")
    assert backend.get("devices.0x1234ABCD.buttons.middle") == "copy"
    assert backend.buttonAction("@mouse", "middle", "middle_click") == "copy"
    assert backend.buttonAction("", "middle", "middle_click") == "middle_click"
    assert backend.setCustomAction("@mouse", "back", {"kind": "shortcut", "value": "F13"})
    assert backend.get("devices.0x1234ABCD.buttons.back") == "custom"
    assert backend.customAction("@mouse", "back")["value"] == "F13"
    backend.restoreButton("@mouse", "back")
    assert not backend.hasOverride("@mouse", "back")
    assert "back" not in (backend.get("devices.0x1234ABCD.buttons.custom") or {})


def test_global_restore_goes_back_to_the_default(backend):
    assert backend.setCustomAction("", "back", {"kind": "url", "value": "https://example.org"})
    assert backend.get("buttons.back") == "custom"
    backend.restoreButton("", "back")
    assert backend.get("buttons.back") == "back"
    assert "back" not in (backend.get("buttons.custom") or {})


def test_custom_actions_are_checked_before_saving(backend):
    bad = [{"kind": "shortcut", "value": "ctrl+c; rm -rf ~"}, {"kind": "url", "value": "https://"},
           {"kind": "url", "value": "file:///etc/passwd"}, {"kind": "exec", "value": "x"},
           {"kind": "command", "value": "  "}, "not a dict"]
    for obj in bad:
        assert bk.Backend._clean_custom(obj) is None, obj
    ok = bk.Backend._clean_custom({"kind": "command", "value": " firefox ", "label": "Firefox",
                                   "icon": "/x.png", "junk": 1})
    assert ok == {"kind": "command", "value": "firefox", "label": "Firefox", "icon": "/x.png"}
    assert backend.setCustomAction("", "middle", {"kind": "bogus", "value": "x"}) is False
    assert backend.get("buttons.middle", "middle_click") == "middle_click"


def test_app_custom_actions_live_in_the_profile(backend):
    assert backend.setCustomAction("gimp", "back", {"kind": "shortcut", "value": "ctrl+z"})
    hw = backend._load_profiles()["hardware"]["gimp"]
    assert hw["buttons"]["back"] == "custom" and hw["custom"]["back"]["value"] == "ctrl+z"
    # saving the app's pointer settings on the App profiles tab keeps them
    backend.saveAppProfile("gimp", {"dpi": 800})
    hw = backend._load_profiles()["hardware"]["gimp"]
    assert hw["dpi"] == 800 and hw["buttons"]["back"] == "custom" and hw["custom"]["back"]["kind"] == "shortcut"


def test_reset_button_map_and_undo(backend):
    backend.setButtonIn("", "back", "copy")
    backend.setCustomAction("", "0x00D7", {"kind": "shortcut", "value": "F14"})
    backend.setThumbwheelMode("volume")
    snap = backend.resetButtonMap("")
    assert backend.get("buttons.back") == "back" and backend.get("thumbwheel.mode") == "off"
    assert "0x00D7" in backend.get("buttons.custom"), "extra controls keep their custom action"
    backend.undoResetButtonMap("", snap)
    assert backend.get("buttons.back") == "copy" and backend.get("thumbwheel.mode") == "volume"

    backend.setButtonIn("gimp", "forward", "redo")
    snap = backend.resetButtonMap("gimp")
    assert not backend.hasOverride("gimp", "forward")
    backend.undoResetButtonMap("gimp", snap)
    assert backend.buttonAction("gimp", "forward", "forward") == "redo"


def test_button_pressed_names_the_slot(backend):
    seen = []
    backend.buttonPressed.connect(seen.append)
    backend.daemon.buttonPressed.emit(0x0053)
    backend.daemon.buttonPressed.emit(0x00D7)
    assert seen == ["back", "0x00D7"]


def test_macro_bindings_map_to_button_slots(backend):
    import json
    macros = [{"id": "m1", "name": "Build", "assigned_trigger": "mouse:8"},
              {"id": "m2", "name": "Other", "assigned_trigger": "mouse:10"},
              {"id": "m3", "assigned_trigger": None}]
    backend.daemon.call_then = lambda method, cb, *a: cb([json.dumps(macros)])
    got = []
    backend.macroBindingsReady.connect(got.append)
    backend.requestMacroBindings()
    assert got == [{"back": {"id": "m1", "name": "Build"}}]


def test_recorded_shortcuts_match_what_the_daemon_accepts():
    for chord in ("ctrl+shift+Page_Up", "F13", "super+comma", "XF86AudioPlay"):
        assert bk.SHORTCUT_RE.match(chord), chord
    for chord in ("ctrl++", "", "ctrl+c;x", "a b"):
        assert not bk.SHORTCUT_RE.match(chord), chord


def test_thumb_wheel_default_is_named_for_what_it_does():
    assert dict(bk.THUMBWHEEL_MODES)["off"] == "Horizontal scroll (default)"


def test_ring_shortcut_slices_run_through_the_daemon():
    """Copy / Paste / Undo slices are type "shortcut": the overlay had no
    branch for them, so they did nothing. The daemon presses the chord."""
    src = (REPO / "overlay" / "juhradial-overlay.py").read_text(encoding="utf-8")
    assert 'elif cmd_type == "shortcut":' in src
    assert 'self.daemon_iface.asyncCall("RunShortcut", cmd)' in src
    iface = (REPO / "daemon" / "src" / "dbus" / "interface.rs").read_text(encoding="utf-8")
    assert "async fn run_shortcut(&self, keys: String)" in iface


def test_key_recorder_names_keys_like_the_daemon(tmp_path):
    """keys.js turns Qt key events into the daemon's chord spelling and back
    into readable text."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlComponent, QQmlEngine
    keys = (REPO / "settings-qt" / "qml" / "components" / "keys.js").as_uri()
    qml = tmp_path / "K.qml"
    qml.write_text(
        'import QtQuick\nimport "%s" as K\nQtObject {\n'
        ' property string f13: K.keyName(Qt.Key_F13, 0)\n'
        ' property string pgup: K.keyName(Qt.Key_PageUp, 0)\n'
        ' property string letter: K.keyName(Qt.Key_T, 0)\n'
        ' property string shifted: K.keyName(Qt.Key_Exclam, 10)\n'
        ' property string chord: K.join(["shift", "ctrl"], "Page_Up")\n'
        ' property string pretty: K.pretty("ctrl+shift+Page_Up")\n'
        ' property string mods: K.split("Control+Meta+x").mods.join(",")\n'
        ' property string none: K.keyName(Qt.Key_Control, 37)\n'
        '}\n' % keys)
    engine = QQmlEngine()
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(qml)))
    obj = comp.create()
    assert obj is not None, comp.errorString()
    got = {k: obj.property(k) for k in ("f13", "pgup", "letter", "shifted", "chord", "pretty", "mods", "none")}
    assert got == {"f13": "F13", "pgup": "Page_Up", "letter": "t", "shifted": "1",
                   "chord": "ctrl+shift+Page_Up", "pretty": "Ctrl + Shift + PgUp",
                   "mods": "ctrl,super", "none": ""}
