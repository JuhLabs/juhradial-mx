"""MX Keypad: bundled key art, animated pictures, own app profiles and packs
that round-trip (owner requests, session 10)."""
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "settings-qt"))
from PyQt6.QtGui import QColor, QGuiApplication, QImage
import bridge.backend as bk
from bridge import keypad

_app = QGuiApplication.instance() or QGuiApplication([])
ART = Path(__file__).resolve().parents[1] / "settings-qt" / "assets" / "keypad" / "art"


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


def _gif(path, colours):
    from PIL import Image
    frames = [Image.new("RGB", (64, 64), c) for c in colours]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[80, 0, 500][:len(colours)], loop=0)


def test_bundled_art_is_complete_small_and_never_names_juhlabs():
    catalogue = keypad.art_catalogue()
    assert {s["id"] for s in catalogue["sets"]} == {"artsy", "minimal"}
    refs = [f"{s}/{a['id']}" for a in catalogue["art"] for s in a["sets"]]
    assert len(refs) >= 100
    for ref in refs:
        path = keypad.art_path(ref)
        assert path is not None and path.stat().st_size < 60_000
        image = QImage(str(path))
        assert (image.width(), image.height()) == (236, 236)
    names = {p.stem for p in ART.rglob("*.jpg")} | {a["name"].lower() for a in catalogue["art"]}
    assert not any("juhlabs" in n for n in names)
    # References are validated: no paths, no other folders.
    for bad in ("../icons/x", "artsy/../../x", "/etc/passwd", "artsy/Rewind", "other/rewind", 5, None):
        assert keypad.art_path(bad) is None


def test_art_keys_keep_their_label_and_survive_a_save(backend, tmp_path):
    backend.addKeypadPage("Art")
    assert backend.saveKeypadKey(0, 1, {"action": "copy", "label": "Copy", "icon": "", "art": "artsy/rewind"})
    assert backend.saveKeypadKey(0, 2, {"action": "copy", "label": "", "icon": "", "art": "minimal/voice"})
    assert backend.saveKeypadKey(0, 3, {"action": "copy", "label": "X", "icon": "", "art": "artsy/../x"})
    keys = backend.keypadPages[0]["keys"]
    assert keys[0]["art"] == "artsy/rewind" and keys[1]["art"] == "minimal/voice"
    assert "art" not in keys[2]
    plate = QImage(str(tmp_path / "keypad/plates/p0-k1.jpg"))
    # The label band darkens the bottom; the art fills the top.
    assert plate.pixelColor(59, 110).lightness() < plate.pixelColor(59, 40).lightness() + 60
    minimal = QImage(str(tmp_path / "keypad/plates/p0-k2.jpg"))
    # Lighten blend: the minimal art's black ground takes the plate colour.
    corner = minimal.pixelColor(2, 2)
    assert abs(corner.blue() - QColor("#070b14").blue()) < 12


def test_gif_pictures_play_and_stale_frames_are_removed(backend, tmp_path):
    gif = tmp_path / "anim.gif"
    _gif(gif, ["#ff0000", "#00ff00", "#0000ff"])
    picture = backend.importKeypadImage(str(gif))
    assert picture.endswith(".gif")
    backend.addKeypadPage("Anim")
    assert backend.saveKeypadKey(0, 4, {"action": "copy", "label": "", "icon": "", "plate": picture})
    plates = tmp_path / "keypad/plates"
    frames = sorted(plates.glob("p0-k4-a*.jpg"))
    assert [f.name for f in frames] == ["p0-k4-a000.jpg", "p0-k4-a001.jpg", "p0-k4-a002.jpg"]
    assert (plates / "p0-k4.anim").read_text().split() == ["80", "100", "500"]
    assert QImage(str(frames[1])).pixelColor(59, 59).green() > 200
    # A still picture on the same key: the old frames must not play on.
    assert backend.saveKeypadKey(0, 4, {"action": "copy", "label": "Copy", "icon": "edit-copy-symbolic"})
    assert not list(plates.glob("p0-k4-a*.jpg")) and not (plates / "p0-k4.anim").exists()
    # A one-frame GIF is a still picture.
    still = tmp_path / "still.gif"
    _gif(still, ["#ff0000"])
    assert backend.saveKeypadKey(0, 5, {"action": "copy", "label": "", "icon": "", "plate": backend.importKeypadImage(str(still))})
    assert not list(plates.glob("p0-k5*.anim"))


def test_own_app_profiles_group_pages_with_names_and_icons(backend, monkeypatch):
    apps = [{"id": "org.kde.kate.desktop", "name": "Kate", "icon": "kate", "command": "kate"}]
    backend.listApplications = lambda: apps
    monkeypatch.setattr(bk.Backend, "appClassFor", lambda self, i: "kate" if "kate" in i else "")
    backend.addKeypadPage("Everyday")
    assert backend.addKeypadAppProfile("org.kde.kate.desktop")
    assert backend.addKeypadGroupPage("Kate 2", ["kate"], "")
    assert backend.keypadPages[1] == {**backend.keypadPages[1], "name": "Kate", "apps": ["kate"]}
    groups = backend.keypadGroups()
    assert [g["name"] for g in groups] == ["All apps", "Kate"]
    assert groups[0]["pages"] == [0] and groups[1]["pages"] == [1, 2]
    assert (groups[1]["icon"], groups[1]["iconKind"]) == ("kate", "app")
    assert groups[0]["iconKind"] == "glyph"


def test_profile_rows_carry_an_icon(backend):
    for row in backend.keypadProfiles():
        assert row["icon"] and row["iconKind"] in ("file", "app", "glyph")
        if row["iconKind"] == "file":
            assert Path(row["icon"]).is_file()


def test_exported_pack_round_trips_and_never_imports_foreign_commands(backend, tmp_path):
    apps = [{"id": "kate.desktop", "name": "Kate", "icon": "kate", "command": "kate"}]
    backend.listApplications = lambda: apps
    gif = tmp_path / "anim.gif"
    _gif(gif, ["#ff0000", "#00ff00"])
    backend.addKeypadGroupPage("Mine", ["kate"], "")
    backend.saveKeypadKey(0, 1, {"action": "custom", "label": "Kate", "icon": "",
                                 "custom": {"kind": "command", "value": "kate"}})
    backend.saveKeypadKey(0, 2, {"action": "custom", "label": "Oops", "icon": "",
                                 "custom": {"kind": "command", "value": "rm -rf ~"}})
    backend.saveKeypadKey(0, 3, {"action": "custom", "label": "Hi", "icon": "", "art": "minimal/send",
                                 "custom": {"kind": "text", "value": "hello", "enter": True}})
    backend.saveKeypadKey(0, 4, {"action": "copy", "label": "", "icon": "", "plate": backend.importKeypadImage(str(gif))})
    pack = tmp_path / "mine.zip"
    assert backend.exportKeypadPack(str(pack), [0])
    with zipfile.ZipFile(pack) as zf:
        spec = json.loads(zf.read("portable.json"))
        assert "pictures/p1-k4.gif" in zf.namelist()
    assert spec["pages"][0]["apps"] == ["kate"]
    assert backend.importKeypadPack(str(pack))
    page = backend.keypadPages[1]
    assert page["name"] == "Mine" and page["apps"] == ["kate"]
    keys = page["keys"]
    assert keys[0]["custom"] == {"kind": "command", "value": "kate"}
    # A command that is not an installed app's launch stays unassigned.
    assert keys[1]["action"] == "none" and keys[1]["label"] == "Oops"
    assert keys[2]["art"] == "minimal/send" and keys[2]["custom"]["kind"] == "text"
    assert keys[3]["plate"].endswith(".gif")
    assert (tmp_path / "keypad/plates/p1-k4.anim").is_file()


def test_cli_profiles_that_share_terminals_stay_apart(backend, monkeypatch):
    # Claude Code and Codex CLI both follow terminals: adding one must not
    # mark the other added, and each keeps its own group on the Pages card.
    monkeypatch.setattr(bk.Backend, "_has_command", staticmethod(lambda name: name == "claude"))
    rows = {r["id"]: r for r in backend.keypadProfiles()}
    assert rows["claude-code"]["installed"] and not rows["codex-cli"]["installed"]
    assert backend.applyKeypadProfile("claude-code")
    rows = {r["id"]: r for r in backend.keypadProfiles()}
    assert rows["claude-code"]["added"] and not rows["codex-cli"]["added"]
    assert backend.applyKeypadProfile("codex-cli")
    groups = [g for g in backend.keypadGroups() if g["apps"]]
    assert [g["name"] for g in groups] == ["Claude Code", "Codex CLI"]
    assert backend.addKeypadGroupPage("More", groups[1]["apps"], groups[1]["profile"])
    assert backend.keypadGroups()[-1]["pages"] == [2, 3, 4]
    # The talk key holds Space while pressed; prompts paste by the window.
    talk = backend.keypadPages[0]["keys"][1]
    assert talk["custom"] == {"kind": "shortcut", "value": "space", "hold": True}
    assert backend.applyKeypadProfile("prompts")
    assert backend.keypadPages[-1]["keys"][0]["custom"]["paste_with"] == "auto"
    assert backend.keypadPages[-1]["keys"][0]["art"] == "artsy/rewind-push"


def test_gate_fixes_rename_profile_carry_and_clean_keys(backend, tmp_path, monkeypatch):
    # Renaming a page updates the "page" keys that go to it (and their label).
    backend.addKeypadPage("Home")
    backend.addKeypadPage("Media")
    go = {"action": "custom", "label": "Media", "icon": "",
          "custom": {"kind": "page", "value": "media", "label": "Media"}}
    assert backend.saveKeypadKey(0, 1, go)
    backend.renameKeypadPage(1, "Music")
    key = backend.keypadPages[0]["keys"][0]
    assert key["custom"]["value"] == "Music" and key["label"] == "Music" and key["custom"]["label"] == "Music"

    # A non-string action is refused instead of raising inside a slot.
    assert backend._clean_keypad_key({"action": ["copy"]}) is None
    assert backend._clean_keypad_key({"action": {"x": 1}}) is None

    # Built-in profile pages carry their group through a pack; unknown ids drop.
    assert backend.applyKeypadProfile("claude-code")
    source = next(i for i, p in enumerate(backend.keypadPages) if p.get("profile") == "claude-code")
    pack = tmp_path / "cc.zip"
    assert backend.exportKeypadPack(str(pack), [source])
    with zipfile.ZipFile(pack) as zf:
        spec = json.loads(zf.read("portable.json"))
    assert spec["pages"][0]["profile"] == "claude-code"
    first = len(backend.keypadPages)
    assert backend.importKeypadPack(str(pack))
    assert backend.keypadPages[first].get("profile") == "claude-code"
    spec["pages"][0]["profile"] = "not-a-profile"
    # A pack key never points at a file on this computer.
    spec["pages"][0]["keys"][0]["juhradial"]["plate"] = str(tmp_path / "config.json")
    forged = tmp_path / "forged.zip"
    with zipfile.ZipFile(forged, "w") as zf:
        zf.writestr("portable.json", json.dumps(spec))
    first = len(backend.keypadPages)
    assert backend.importKeypadPack(str(forged))
    assert "profile" not in backend.keypadPages[first]
    assert "plate" not in backend.keypadPages[first]["keys"][0]

    # Showing a profile page for all apps takes it out of the profile's group.
    backend.setKeypadPageApps(first, [])
    assert "profile" not in backend.keypadPages[first] and "apps" not in backend.keypadPages[first]


def test_cli_tools_are_found_in_user_install_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(bk.shutil, "which", lambda name: None)
    monkeypatch.setattr(bk.pathlib.Path, "home", staticmethod(lambda: tmp_path))
    assert not bk.Backend._has_command("claude")
    for folder, tool in ((".claude/local", "claude"), (".volta/bin", "codex"), (".nvm/versions/node/v22.1.0/bin", "gemini")):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / tool).write_text("")
        assert bk.Backend._has_command(tool), folder


def test_animation_frames_are_decoded_once_per_file_version(tmp_path, monkeypatch):
    gif = tmp_path / "a.gif"
    _gif(gif, ["#ff0000", "#00ff00"])
    reads = []
    real = keypad.QImageReader
    monkeypatch.setattr(keypad, "QImageReader", lambda p: reads.append(p) or real(p))
    first = keypad._animation_frames(gif)
    assert len(first[0]) == 2 and keypad._animation_frames(gif) == first and len(reads) == 1
    os.utime(gif, ns=(1, 1))
    keypad._animation_frames(gif)
    assert len(reads) == 2, "a changed file is decoded again"


def test_cli_profiles_show_the_tools_own_marks_not_generated_art(backend):
    rows = {r["id"]: r for r in backend.keypadProfiles()}
    for pid, mark in (("claude-code", "claude-code.svg"), ("codex-cli", "codex.svg")):
        assert rows[pid]["iconKind"] == "file" and rows[pid]["icon"].endswith("/keypad/brands/" + mark)
    for bad in ("brand/../art/x", "brand/Codex", "brands/codex", "/etc/passwd", None):
        assert keypad.brand_path(bad) is None
