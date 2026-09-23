#!/usr/bin/env python3
"""Plugin actions reach the slice picker, bind to a slice and run from the ring.

The manifest rules live in the daemon (daemon/src/plugins.rs, cargo test).
These tests pin the app side: ListPlugins JSON -> picker entries, a picked
plugin action stored as {type: plugin, command: <folder>/<id>} on the slice
(colour kept), the Plugins card rows, and the overlay's plugin branch.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_plugins_ui.py -q
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

import bridge.backend as bk  # noqa: E402

LISTING = json.dumps([
    {"folder": "quick-note", "name": "Quick note", "version": "1.0.0", "description": "d",
     "author": "a", "actions": [
         {"ref": "quick-note/save-clipboard", "id": "save-clipboard", "label": "Clipboard to note",
          "icon": "document-save-symbolic", "description": "", "kind": "script"},
         {"ref": "quick-note/haptic-tap", "id": "haptic-tap", "label": "Haptic tap",
          "icon": "/home/u/.config/juhradial/plugins/quick-note/tap.svg", "description": "", "kind": "dbus"}]},
    {"folder": "broken", "name": "broken", "version": "", "description": "", "author": "",
     "actions": [], "error": "invalid plugin.json: expected value at line 1"},
])


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    b.daemon.call1 = lambda method, *a, default=None: LISTING if method == "ListPlugins" else default
    b.daemon.call_async = lambda *a, **k: None
    return b


def test_plugin_actions_become_picker_entries(backend):
    entries = backend.pluginActions()
    assert [e["id"] for e in entries] == ["plugin:quick-note/save-clipboard", "plugin:quick-note/haptic-tap"]
    first = entries[0]
    assert first["name"] == "Quick note: Clipboard to note"
    assert first["label"] == "Clipboard to note"
    assert first["type"] == "plugin" and first["command"] == "quick-note/save-clipboard"
    assert entries[1]["icon"].endswith("tap.svg")
    ids = [e["id"] for e in backend.sliceActions()]
    assert ids[: len(backend.radialActions())] == [a["id"] for a in backend.radialActions()]
    assert ids[-2:] == ["plugin:quick-note/save-clipboard", "plugin:quick-note/haptic-tap"]


def test_picking_a_plugin_action_binds_the_slice_and_keeps_its_colour(backend, tmp_path):
    slices = backend._slices
    colour = slices.slices()[2]["color"]
    slices.setAction(2, "plugin:quick-note/save-clipboard")
    s = slices.slices()[2]
    assert s == {"label": "Clipboard to note", "action_id": "plugin", "type": "plugin",
                 "command": "quick-note/save-clipboard", "color": colour,
                 "icon": "document-save-symbolic"}
    disk = json.loads((tmp_path / "config.json").read_text())
    assert disk["radial_menu"]["slices"][2]["type"] == "plugin"


def test_unknown_plugin_action_leaves_the_slice_alone(backend):
    before = dict(backend._slices.slices()[1])
    backend._slices.setAction(1, "plugin:gone/away")
    assert backend._slices.slices()[1] == before


def test_plugins_card_rows_carry_errors():
    rows = bk.Backend._plugin_rows(LISTING)
    assert rows[0] == {"folder": "quick-note", "name": "Quick note", "version": "1.0.0",
                       "description": "d", "actions": 2, "error": ""}
    assert rows[1]["actions"] == 0 and rows[1]["error"].startswith("invalid plugin.json")
    assert bk.Backend._plugin_rows("not json") == []
    assert bk.Backend._plugin_rows(None) == []


def test_daemon_down_means_no_plugin_entries(backend):
    backend.daemon.call1 = lambda method, *a, default=None: default
    assert backend.pluginActions() == []


def test_overlay_runs_plugin_slices_through_the_daemon():
    src = (REPO_ROOT / "overlay" / "juhradial-overlay.py").read_text(encoding="utf-8")
    assert 'elif cmd_type == "plugin":' in src
    assert 'self.daemon_iface.asyncCall("RunPluginAction", cmd)' in src
