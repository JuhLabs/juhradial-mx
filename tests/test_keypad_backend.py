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
    # The app's own Exec command, like the ring's app picker (no gtk-launch dependency).
    assert key["custom"]["value"] == "konsole"
    # Name and icon as the App picker stores them: the editor opens on its App tab.
    assert key["custom"]["label"] == "Konsole" and key["custom"]["icon"]


def test_template_glyphs_are_bundled():
    # Without an icon theme (Hyprland, sway, niri) only the bundled set draws (#34).
    from bridge.keypad import template_keys
    icons = Path(__file__).resolve().parents[1] / "settings-qt" / "assets" / "icons"
    for template in ("everyday", "media", "developer", "meetings"):
        for key in template_keys(template, [], bk.BUTTON_ACTIONS):
            name = key["icon"]
            if name and not name.startswith("desktop:"):
                assert any((icons / d / f"{name}.svg").is_file() for d in ("mono", "nav")), name


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


def test_unknown_glyph_name_still_renders_a_visible_glyph(tmp_path):
    from bridge.keypad import render_plate
    plate = tmp_path / "unknown.jpg"
    render_plate({"icon": "no-such-glyph-symbolic", "label": ""}, plate, lambda _: "")
    image = QImage(str(plate))
    bright = sum(image.pixelColor(x, y).lightness() > 70
                 for x in range(21, 97) for y in range(9, 85))
    assert bright > 150


def test_empty_key_plate_stays_blank(tmp_path):
    from bridge.keypad import empty_key, render_plate
    plate = tmp_path / "empty.jpg"
    render_plate(empty_key(), plate, lambda _: "")
    image = QImage(str(plate))
    assert not any(image.pixelColor(x, y).lightness() > 70
                   for x in range(21, 97) for y in range(9, 85))


def test_bundled_glyph_wins_over_a_theme_colour_fallback(tmp_path, monkeypatch):
    # On Breeze, accessories-calculator-symbolic falls back to the colour app
    # icon, which the plate tint turned into a solid block.
    import bridge.keypad as kp
    from PyQt6.QtGui import QColor, QIcon, QPixmap

    def render(name):
        plate = tmp_path / f"{name}.jpg"
        kp.render_plate({"icon": "accessories-calculator-symbolic", "label": ""}, plate, lambda _: "")
        return QImage(str(plate))

    reference = render("reference")
    solid = QPixmap(64, 64)
    solid.fill(QColor("#3daee9"))
    monkeypatch.setattr(kp.QIcon, "fromTheme", staticmethod(lambda name: QIcon(solid)))
    assert render("themed") == reference


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


def test_page_saves_keep_other_keypad_settings(backend):
    backend.setLocal("keypad", {"enabled": True, "active_page": 0, "pages": [], "brightness": 40})
    assert backend.addKeypadPage("Work")
    assert backend.get("keypad.brightness") == 40


def test_pages_can_belong_to_apps(backend):
    assert backend.addKeypadPage("Code")
    backend.setKeypadPageApps(0, ["Code", " code ", ""])
    assert backend.keypadPages[0]["apps"] == ["code"]
    backend.setKeypadPageApps(0, [])
    assert "apps" not in backend.keypadPages[0]


def test_text_and_held_shortcut_custom_actions(backend):
    clean = bk.Backend._clean_custom
    assert clean({"kind": "text", "value": "  /compact\\n", "enter": True, "paste_with": "ctrl+shift+v"}) == {
        "kind": "text", "value": "  /compact\\n", "enter": True, "paste_with": "ctrl+shift+v"}
    assert clean({"kind": "text", "value": "hi", "paste_with": "rm -rf"}) == {"kind": "text", "value": "hi"}
    assert clean({"kind": "shortcut", "value": "space", "hold": True}) == {"kind": "shortcut", "value": "space", "hold": True}
    assert clean({"kind": "command", "value": "true", "hold": True}) == {"kind": "command", "value": "true"}


def test_a_ready_plate_image_fills_the_key(backend, tmp_path):
    from PyQt6.QtGui import QColor
    from bridge.keypad import render_plate
    red = QImage(300, 200, QImage.Format.Format_RGB32)
    red.fill(QColor("#ff0000"))
    src = tmp_path / "red.png"
    red.save(str(src))
    out = tmp_path / "plate.jpg"
    render_plate({"plate": str(src), "icon": "folder-symbolic", "label": "IGNORED"}, out, lambda _: "")
    image = QImage(str(out))
    assert image.width() == 118 and image.pixelColor(59, 110).red() > 200 and image.pixelColor(5, 5).red() > 200
    assert backend.addKeypadPage("P")
    assert backend.saveKeypadKey(0, 1, {"action": "none", "label": "", "icon": "", "plate": str(src)})
    assert backend.keypadPages[0]["keys"][0]["plate"] == str(src)


def test_app_profiles_rank_by_use_and_add_app_pages(backend, monkeypatch, tmp_path):
    catalogue = [
        {"id": "general", "name": "General", "apps": [], "pages": [{"name": "General", "keys": [{"label": "Play", "icon": "media-playback-start-symbolic", "action": "play_pause"}]}]},
        {"id": "browser", "name": "Web browser", "apps": ["firefox", "google-chrome"], "desktop_ids": ["org.mozilla.firefox.desktop"],
         "pages": [{"name": "Browser", "keys": [{"label": "Back", "icon": "go-previous-symbolic", "action": "back"},
                                               {"label": "Find", "icon": "edit-find-symbolic", "action": "custom", "custom": {"kind": "shortcut", "value": "ctrl+f"}},
                                               {"label": "Bad", "icon": "x", "action": "no_such_action"}]}]},
        {"id": "code", "name": "VS Code", "apps": ["code"], "desktop_ids": ["code.desktop"], "pages": [{"name": "Code", "keys": []}]},
    ]
    monkeypatch.setattr(bk.Backend, "_keypad_catalogue", lambda self: catalogue)
    monkeypatch.setattr(bk.Backend, "_app_usage", staticmethod(lambda: {"code": 7200, "firefox": 60}))
    backend.listApplications = lambda: [{"id": "org.mozilla.firefox.desktop"}]
    ranked = [p["id"] for p in backend.keypadProfiles()]
    assert ranked[0] == "code" and set(ranked) == {"general", "browser", "code"}
    assert backend.applyKeypadProfile("browser")
    page = backend.keypadPages[-1]
    assert page["apps"] == ["firefox", "google-chrome"] and page["name"] == "Browser"
    assert page["keys"][0]["action"] == "back" and page["keys"][1]["custom"] == {"kind": "shortcut", "value": "ctrl+f"}
    assert page["keys"][2]["action"] == "none" and len(page["keys"]) == 9
    assert next(p for p in backend.keypadProfiles() if p["id"] == "browser")["added"]
    assert backend.applyKeypadProfile("general") and "apps" not in backend.keypadPages[-1]
    assert not backend.applyKeypadProfile("missing")


def test_label_only_key_draws_a_big_centred_label(tmp_path):
    from bridge.keypad import render_plate
    plate = tmp_path / "label.jpg"
    render_plate({"icon": "", "label": "Deploy"}, plate, lambda _: "")
    image = QImage(str(plate))
    bright_centre = sum(image.pixelColor(x, y).lightness() > 120 for x in range(10, 108) for y in range(45, 75))
    assert bright_centre > 80


def test_pack_import_keeps_pictures_and_maps_only_sure_actions(backend, tmp_path):
    pack = tmp_path / "MyPack"
    (pack / "profiles").mkdir(parents=True)
    (pack / "icons" / "keys-118" / "artsy").mkdir(parents=True)
    img = QImage(118, 118, QImage.Format.Format_RGB32)
    img.fill(0)
    img.save(str(pack / "icons" / "keys-118" / "artsy" / "l-code.jpg"))
    (pack / "profiles" / "portable.json").write_text(json.dumps({"pages": [
        {"title": "HOME", "mac_profiles": {"general": 0}, "keys": [
            {"slot": 0, "id": "l-code", "label": "VS Code", "action": {"kind": "launch", "name": "Visual Studio Code"}},
            {"slot": 1, "id": "esc", "label": "Esc", "action": {"kind": "keys", "combo": "escape"}},
            {"slot": 2, "id": "mission", "label": "Mission", "action": {"kind": "keys", "combo": "primary+tab"}},
            {"slot": 3, "id": "ctx", "label": "Context", "action": {"kind": "type", "text": "/context", "enter": True,
                                                                   "target": "claude-code-terminal"}}]},
        {"title": "CODE", "mac_profiles": {"vscode": 0}, "keys": []}]}))
    backend.listApplications = lambda: [{"id": "code.desktop", "name": "Visual Studio Code", "command": "code"}]
    assert backend.importKeypadPack(str(pack))
    home, code = backend.keypadPages[-2:]
    assert "apps" not in home and code["apps"] == ["code", "code-oss", "vscodium"]
    k = home["keys"]
    assert k[0]["custom"]["value"] == "code" and k[0]["plate"].endswith("artsy/l-code.jpg")
    assert k[1]["custom"] == {"kind": "shortcut", "value": "Escape"}
    assert k[2]["action"] == "none" and k[2]["label"] == "Mission"
    assert k[3]["custom"] == {"kind": "text", "value": "/context", "enter": True, "paste_with": "ctrl+shift+v"}
    assert not backend.importKeypadPack(str(tmp_path / "missing"))


def test_shipped_app_profiles_are_complete(backend):
    # Every catalogue key must survive validation and draw a bundled glyph (#34).
    root = Path(__file__).resolve().parents[1] / "settings-qt" / "assets"
    catalogue = json.loads((root / "keypad" / "profiles.json").read_text(encoding="utf-8"))["profiles"]
    icons = {p.stem for d in ("mono", "nav") for p in (root / "icons" / d).glob("*.svg")}
    backend.listApplications = lambda: []
    assert len(catalogue) >= 20
    for prof in catalogue:
        assert len(prof["pages"]) in (1, 2) and len({p["id"] for p in catalogue}) == len(catalogue)
        before = len(backend.keypadPages)
        assert backend.applyKeypadProfile(prof["id"]), prof["id"]
        for src, page in zip(prof["pages"], backend.keypadPages[before:]):
            assert len(src["keys"]) == 9
            for raw, key in zip(src["keys"], page["keys"]):
                assert raw["icon"] in icons, (prof["id"], raw["icon"])
                assert len(raw["label"]) <= 10, raw["label"]
                assert raw.get("action", "none") == "none" or key["action"] != "none", (prof["id"], raw["label"])
