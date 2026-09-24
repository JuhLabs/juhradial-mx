#!/usr/bin/env python3
"""QML hands every JS array and object to a "QVariant" slot as a QJSValue
(Qt 6, PyQt 6.11): a slot that iterates it raised (DPI presets crashed the
app) or dropped it silently (quick links, app profiles, custom actions).
These calls go through real QML, the way the pages make them.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_qml_slot_arguments.py -q
"""
import ast
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtQml")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))
sys.path.insert(0, os.fspath(REPO / "overlay"))

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication([])

import bridge.backend as bk  # noqa: E402


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    monkeypatch.setattr(bk.Daemon, "call", lambda *a, **k: None)
    monkeypatch.setattr(bk.Daemon, "call_async", lambda *a, **k: None)
    return bk.Backend()


def _run_qml(backend, body, props=""):
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("Backend", backend)
    component = QQmlComponent(engine)
    qml = "import QtQuick\nItem {\n" + props + "\nComponent.onCompleted: {\n" + body + "\n} }"
    component.setData(qml.encode(), QUrl())
    item = component.create()
    assert item is not None, [e.toString() for e in component.errors()]
    return engine, item


def test_arrays_and_objects_from_qml_reach_the_config(backend, tmp_path):
    engine, item = _run_qml(backend, """
        Backend.setDpiPresets([800, 1600, 3200])
        Backend.setLinksFor(Backend.submenuRows()[0].row, [{ name: "Docs", url: "https://docs.example.org", icon: "browser", command: "" }])
        Backend.saveAppProfile("kate", { overrides: { dpi: true }, dpi: 1200 })
        Backend.setCustomAction("", "back", { kind: "shortcut", value: "ctrl+c" })
        Backend.setHapticPatterns({ slice_change: "happy_alert" })
        Backend.setLocal("ui.test_list", [1, 2])
        Backend.set("ui.test_map", { a: 1 })
    """)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["pointer"]["dpi_presets"] == [800, 1600, 3200]
    sub = next(s["submenu"] for s in cfg["radial_menu"]["slices"] if s.get("type") == "submenu")
    assert sub == [{"label": "Docs", "url": "https://docs.example.org"}]
    assert cfg["buttons"]["custom"]["back"]["value"] == "ctrl+c"
    assert backend.get(backend._button_key("back")) == "custom"
    assert cfg["haptics"]["per_event"]["slice_change"] == "happy_alert"
    assert cfg["ui"] == {"test_list": [1, 2], "test_map": {"a": 1}}
    profiles = json.loads((tmp_path / "profiles.json").read_text())
    assert profiles["hardware"]["kate"]["dpi"] == 1200


def test_macro_rows_and_summaries_from_qml(backend, monkeypatch):
    macro = bk.new_macro("m1", "M", [])
    stored = []
    monkeypatch.setattr(backend, "_find_macro", lambda mid: macro if mid == "m1" else None)
    monkeypatch.setattr(backend, "_store_macro", lambda m: stored.append(m) or True)
    engine, item = _run_qml(backend, """
        Backend.saveMacroRows("m1", [{ kind: "keys", chord: "ctrl+c", hold: 0 }])
        ms = Backend.macroSummary({ actions: [{ type: "delay", ms: 120 }], use_standard_delay: false }).ms
    """, props="property int ms: 0")
    assert stored and stored[0]["actions"], "the rows saved from QML became the macro's steps"
    assert item.property("ms") == 120


def test_every_qvariant_argument_is_converted():
    # A new slot taking a "QVariant" argument must convert it (_js or
    # toVariant), or QML's arrays and objects break it again.
    tree = ast.parse((REPO / "settings-qt/bridge/backend.py").read_text())
    missing = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for deco in fn.decorator_list:
            if not (isinstance(deco, ast.Call) and getattr(deco.func, "id", "") == "pyqtSlot"):
                continue
            kinds = [a.value if isinstance(a, ast.Constant) else getattr(a, "id", "") for a in deco.args]
            params = [a.arg for a in fn.args.args[1:]]
            source = ast.unparse(fn)
            for kind, name in zip(kinds, params):
                if kind == "QVariant" and fn.name != "get" and f"_js({name})" not in source \
                        and f"{name}.toVariant()" not in source:
                    missing.append(f"{fn.name}({name})")
    assert missing == []
