"""MX Keypad plates, templates and config round trips without hardware."""
import json
import os
import sys
import shlex
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "settings-qt"))
from PyQt6.QtGui import QGuiApplication, QImage
import bridge.backend as bk

_app = QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    monkeypatch.setattr(bk.Daemon, "call_then", lambda self, method, cb, *args: cb(None))
    monkeypatch.setattr(bk.Daemon, "call_async", lambda *args: None)
    b = bk.Backend()
    b.listApplications = lambda: []
    yield b
    b._keypad_timer.stop()


def test_plate_size_magic_and_dark_background(backend, tmp_path):
    backend.addKeypadPage("Work")
    assert backend.saveKeypadKey(0, 1, {"action": "copy", "label": "COPY", "icon": "edit-copy-symbolic"})
    files = sorted((tmp_path / "keypad/plates").glob("*.jpg"))
    assert len(files) == 9
    for file in files:
        assert file.read_bytes().startswith(b"\xff\xd8\xff")
        image = QImage(str(file))
        assert (image.width(), image.height()) == (118, 118)
        assert image.pixelColor(0, 0).lightness() < 30
    assert (tmp_path / "keypad/plates/p0-k1.jpg").stat().st_size < 65535


def test_page_crud_and_undo_roundtrip(backend):
    backend.addKeypadPage("One")
    backend.addKeypadPage("Two")
    backend.renameKeypadPage(0, "Work")
    backend.moveKeypadPage(0, 1)
    assert [p["name"] for p in backend.keypadPages] == ["Two", "Work"]
    snapshot = backend.deleteKeypadPage(0)
    assert [p["name"] for p in backend.keypadPages] == ["Work"]
    backend.restoreKeypadPages(snapshot)
    stored = json.loads(bk.CONFIG.read_text())["keypad"]
    assert [p["name"] for p in stored["pages"]] == ["Two", "Work"]
    assert all(len(p["keys"]) == 9 for p in stored["pages"])
    backend._load()
    assert backend.keypadPages == stored["pages"]


def test_templates_only_offer_supported_actions_and_installed_apps(backend):
    known = {row[0] for row in bk.BUTTON_ACTIONS}
    for template in backend.keypadTemplates():
        assert backend.applyKeypadTemplate(template["id"])
        for key in backend.keypadPages[-1]["keys"]:
            assert key["action"] in known
            if key["action"] == "custom":
                assert bk.Backend._clean_custom(key["custom"]) is not None
                if key["custom"]["kind"] == "command":
                    tool = shlex.split(key["custom"]["value"])[0]
                    assert tool in {"wpctl", "pactl"} and shutil.which(tool)
    backend.listApplications = lambda: [{"id": "org.kde.konsole.desktop", "name": "Konsole",
                                       "icon": "utilities-terminal", "command": "konsole"}]
    assert backend.applyKeypadTemplate("developer")
    key = backend.keypadPages[-1]["keys"][0]
    assert key["custom"]["kind"] == "command"
    assert "org.kde.konsole.desktop" in key["custom"]["value"]


def test_invalid_key_and_page_edits_leave_config_unchanged(backend):
    backend.addKeypadPage("Work")
    before = json.dumps(backend.keypadPages)
    assert not backend.saveKeypadKey(0, 10, {"action": "copy"})
    assert not backend.saveKeypadKey(0, 1, {"action": "not_an_action"})
    assert not backend.saveKeypadKey(0, 1, {"action": "custom", "custom": {"kind": "shortcut", "value": "ctrl++"}})
    backend.moveKeypadPage(0, -1)
    assert before == json.dumps(backend.keypadPages)


def test_refresh_follows_render_and_reload_and_page_is_a_byte(backend, monkeypatch):
    calls = []
    def call(self, method, callback, *args):
        calls.append((method, args))
        if method == "RefreshKeypadPlates":
            assert (bk.CONFIG_DIR / "keypad/plates/p0-k1.jpg").is_file()
        callback([True, "MX Keypad", 0, 1] if method == "GetKeypadStatus" else [])
    monkeypatch.setattr(bk.Daemon, "call_then", call)
    backend.addKeypadPage("Work")
    methods = [m for m, _ in calls]
    assert methods.index("ReloadConfig") < methods.index("RefreshKeypadPlates")
    backend.setKeypadPage(0)
    arg = next(args[0] for method, args in reversed(calls) if method == "SetKeypadPage")
    assert type(arg) is type(bk._u8(0))


def test_hardware_page_turn_survives_the_next_edit(backend, monkeypatch):
    backend.addKeypadPage("One")
    backend.addKeypadPage("Two")
    monkeypatch.setattr(bk.Daemon, "call_then", lambda self, method, cb, *args:
                        cb([True, "MX Keypad", 0, 2] if method == "GetKeypadStatus" else []))
    backend.refreshKeypadStatus()
    assert backend.keypadStatus["active_page"] == 0
    backend.renameKeypadPage(0, "Work")
    assert json.loads(bk.CONFIG.read_text())["keypad"]["active_page"] == 0


def test_delayed_status_cannot_revert_a_page_selection(backend, monkeypatch):
    backend.addKeypadPage("One")
    backend.addKeypadPage("Two")
    callbacks = []
    def call(self, method, cb, *args):
        if method == "GetKeypadStatus":
            callbacks.append(cb)
        else:
            cb([])
    monkeypatch.setattr(bk.Daemon, "call_then", call)
    backend.refreshKeypadStatus()
    backend.setKeypadPage(0)
    callbacks.pop(0)([True, "MX Keypad", 1, 2])
    assert backend.keypadStatus["active_page"] == 0


def test_unresolved_application_icon_still_renders_a_visible_glyph(tmp_path):
    from bridge.keypad import render_plate
    plate = tmp_path / "fallback.jpg"
    render_plate({"icon": "desktop:missing.desktop", "label": ""}, plate, lambda _: "")
    image = QImage(str(plate))
    bright = sum(image.pixelColor(x, y).lightness() > 70
                 for x in range(21, 97) for y in range(9, 85))
    assert bright > 150


def test_deleting_a_page_updates_the_visible_key_editor(backend):
    from PyQt6.QtCore import QObject, QUrl
    from PyQt6.QtQml import QQmlComponent, QQmlEngine
    from bridge.theme import Theme
    backend.addKeypadPage("One")
    backend.saveKeypadKey(0, 1, {"action": "copy", "label": "COPY"})
    backend.addKeypadPage("Two")
    backend.saveKeypadKey(1, 1, {"action": "paste", "label": "PASTE"})
    backend.setKeypadPage(0)
    engine = QQmlEngine()
    theme = Theme()
    context = engine.rootContext()
    context.setContextProperty("Backend", backend)
    context.setContextProperty("Theme", theme)
    settings = Path(__file__).resolve().parents[1] / "settings-qt"
    context.setContextProperty("assetsDir", (settings / "assets").as_uri())
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(settings / "qml/pages/KeypadPage.qml")))
    page = component.create(context)
    assert page is not None, [e.toString() for e in component.errors()]
    editor = next(child for child in page.findChildren(QObject)
                  if child.metaObject().indexOfProperty("draft") >= 0)
    assert editor.property("draft")["label"] == "COPY"
    backend.keypadKeyPressed.emit(0, 3)
    assert page.property("litKey") == 3
    backend.keypadKeyPressed.emit(1, 7)
    assert page.property("litKey") == 3
    backend.deleteKeypadPage(0)
    assert editor.property("draft")["label"] == "PASTE"
    page.deleteLater()
