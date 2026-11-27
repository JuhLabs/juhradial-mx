#!/usr/bin/env python3
"""A picker declared inside another popup still gets a usable list (#206).

The pickers sized themselves against `parent.height`; declared inside a small
popup (the custom action editor, the slice editor) that parent is the small
popup, so Custom action -> App -> Choose... showed a title, a search field and
a list of negative height. These load the real components offscreen, nested
the way the editors nest them, in a window of a normal size.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_nested_popup_sizing.py -q
"""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtQml")
pytest.importorskip("PyQt6.QtQuick")
REPO = Path(__file__).resolve().parents[1]
COMPONENTS = REPO / "settings-qt" / "qml" / "components"
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

from PyQt6.QtCore import QObject, QUrl, pyqtSlot  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication([])
assert _app is not None

from bridge import compat  # noqa: E402
from bridge.theme import Theme  # noqa: E402

ROW = 52 + 4  # one application row and the list spacing


class StubBackend(QObject):
    @pyqtSlot(result="QVariantList")
    def listApplications(self):
        return [
            {"id": "org.example.Files.desktop", "name": "Files", "command": "files", "icon": ""},
            {"id": "org.example.Editor.desktop", "name": "Editor", "command": "editor", "icon": ""},
        ]

    @pyqtSlot(result="QVariantList")
    def listMacros(self):
        return []

    @pyqtSlot(result="QVariantList")
    def pluginActions(self):
        return []

    @pyqtSlot(result="QVariantList")
    def keypadArt(self):
        return []


WINDOW = b"""
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as B

Window {
    width: 900; height: 700; visible: true
    property alias host: host
    property alias picker: picker
    B.Popup {
        id: host
        width: 320; height: 200
        %s { id: picker }
    }
}
"""


def _wait(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _open_nested(kind):
    engine = QQmlEngine()
    theme, backend = Theme(probe_desktop=False), StubBackend()
    # The stand-ins for what an older Qt lacks (6.4 has no QtQuick.Effects).
    compat.install(engine, theme)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("Backend", backend)
    component = QQmlComponent(engine)
    # A url inside components/ resolves the picker by its file name.
    component.setData(WINDOW % kind.encode(), QUrl.fromLocalFile(os.fspath(COMPONENTS / "_nested_test.qml")))
    window = component.create()
    assert window is not None, [e.toString() for e in component.errors()]
    host, picker = window.property("host"), window.property("picker")
    host.open()
    assert _wait(lambda: host.property("opened"))
    picker.open()
    assert _wait(lambda: picker.property("opened"))
    # engine, theme, backend and window stay referenced until the asserts run
    return (engine, theme, backend, window), picker


def _child_of_class(item, name):
    for child in item.childItems():
        if name in child.metaObject().className():
            return child
    return None


def test_app_picker_inside_a_small_popup_shows_its_list():
    _keep, picker = _open_nested("AppPicker")
    listview = _child_of_class(picker.property("contentItem"), "ListView")
    assert listview is not None
    assert listview.property("count") == 2
    assert picker.property("height") >= 300, picker.property("height")
    assert listview.height() >= 2 * ROW, listview.height()


def test_action_picker_inside_a_small_popup_shows_its_grid():
    _keep, picker = _open_nested("ActionPicker")
    scroller = _child_of_class(picker.property("contentItem"), "ScrollView")
    assert scroller is not None
    assert picker.property("height") >= 300, picker.property("height")
    assert scroller.height() >= 2 * 46, scroller.height()


def test_key_art_picker_inside_a_small_popup_shows_its_grid():
    _keep, picker = _open_nested("KeypadArtPicker")
    grid = _child_of_class(picker.property("contentItem"), "GridView")
    assert grid is not None
    assert picker.property("height") >= 300, picker.property("height")
    assert grid.height() >= grid.property("cellHeight"), grid.height()


def test_custom_action_editor_inside_a_smaller_item_is_not_clipped():
    # The keypad key editor declares this editor inside its own Column, which
    # is smaller than the window, like the small popup here.
    _keep, editor = _open_nested("CustomActionEditor")
    assert editor.property("height") == editor.property("implicitHeight")


def test_picker_list_height_is_never_negative():
    # A window shorter than the picker's own chrome must not give the list a
    # negative height.
    for name in ("AppPicker.qml", "ActionPicker.qml", "KeypadArtPicker.qml"):
        text = (COMPONENTS / name).read_text(encoding="utf-8")
        assert "parent ? parent.height" not in text, name
        assert "Math.max(0," in text, name
