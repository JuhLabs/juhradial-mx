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


def test_key_plates_device_images_match_the_layout_the_page_uses():
    import re
    qml = (Path(__file__).resolve().parents[1] / "settings-qt/qml/pages/KeypadPage.qml").read_text()
    body = qml[qml.index("id: body"):qml.index("SegmentedControl {", qml.index("id: body"))]
    aspect = float(re.search(r"height: width \* ([0-9.]+)", body).group(1))
    rects = [[float(v) for v in m] for m in re.findall(r"\[([0-9.]+), ([0-9.]+), ([0-9.]+), ([0-9.]+)\]", body)]
    keys, buttons = rects[:9], rects[9:]
    assert len(keys) == 9 and len(buttons) == 2
    for colour in ("pale", "graphite"):
        image = QImage(str(Path(__file__).resolve().parents[1] / f"settings-qt/assets/devices/mx_keypad_front_{colour}.png"))
        assert not image.isNull() and abs(image.height() / image.width() - aspect) < 0.002
        at = lambda fx, fy: image.pixelColor(int(fx * image.width()), int(fy * image.height()))
        assert at(0.01, 0.01).alpha() == 0, "transparent around the body"
        for x, y, w, h in keys:
            glass = at(x + w / 2, y + h / 2)
            assert glass.lightness() < 25 and glass.alpha() == 255, (colour, x, y)
        for x, y, w, h in buttons:
            assert at(x + w / 2, y + h / 2).lightness() > at(keys[0][0] + 0.1, keys[0][1] + 0.08).lightness() + 20


def test_rename_follows_only_keys_that_reach_that_page(backend, tmp_path):
    # The daemon takes "next"/"previous" as steps and a name as its FIRST page.
    for name in ("Home", "Code", "Code", "Next"):
        backend.addKeypadPage(name)
    go = lambda value: {"action": "custom", "label": value, "icon": "", "custom": {"kind": "page", "value": value}}
    assert backend.saveKeypadKey(0, 1, go("Code"))
    assert backend.saveKeypadKey(0, 2, go("next"))
    backend.renameKeypadPage(2, "Code JB")      # the second "Code": no key reached it
    backend.renameKeypadPage(3, "Tools")        # "next" is a step, not this page
    keys = backend.keypadPages[0]["keys"]
    assert keys[0]["custom"]["value"] == "Code" and keys[1]["custom"]["value"] == "next"
    backend.renameKeypadPage(1, "Editor")       # the first "Code" is the one it opens
    assert backend.keypadPages[0]["keys"][0]["custom"]["value"] == "Editor"


def test_a_forged_pack_profile_cannot_break_the_import(backend, tmp_path):
    notes = []
    backend.notify = lambda text, kind: notes.append(kind)
    forged = tmp_path / "forged.zip"
    page = {"title": "X", "apps": ["code"], "profile": ["claude-code"], "keys": []}
    with zipfile.ZipFile(forged, "w") as zf:
        zf.writestr("portable.json", json.dumps({"pages": [page]}))
    assert backend.importKeypadPack(str(forged))
    assert "profile" not in backend.keypadPages[-1] and notes[-1] == "success"


def test_only_animations_are_kept_and_the_newest_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(keypad, "_ANIMATIONS", {})
    monkeypatch.setattr(keypad, "_ANIMATIONS_KEPT", 2)
    still = tmp_path / "still.png"
    QImage(8, 8, QImage.Format.Format_RGB32).save(str(still))
    assert keypad._animation_frames(still) == ([], []) and keypad._ANIMATIONS == {}
    gifs = []
    for n in range(3):
        gifs.append(tmp_path / f"g{n}.gif")
        _gif(gifs[-1], ["#ff0000", "#00ff00"])
    keypad._animation_frames(gifs[0])
    keypad._animation_frames(gifs[1])
    keypad._animation_frames(gifs[0])           # a hit makes it the newest
    keypad._animation_frames(gifs[2])           # evicts the oldest: g1
    kept = {Path(k[0]).name for k in keypad._ANIMATIONS}
    assert kept == {"g0.gif", "g2.gif"}


def test_folder_pages_are_marked_and_travel_in_packs(backend, tmp_path):
    backend.addKeypadPage("Home")
    backend.addKeypadPage("Tools")
    backend.setKeypadPageFolder(1, True)
    assert backend.keypadPages[1]["folder"] is True and "folder" not in backend.keypadPages[0]
    pack = tmp_path / "f.zip"
    assert backend.exportKeypadPack(str(pack), [1])
    assert backend.importKeypadPack(str(pack))
    assert backend.keypadPages[2]["folder"] is True
    backend.setKeypadPageFolder(1, False)
    assert "folder" not in backend.keypadPages[1]


def test_two_state_keys_render_both_plates_and_clean_up(backend, tmp_path):
    backend.addKeypadPage("Home")
    second = {"action": "custom", "label": "Unmute", "icon": "",
              "custom": {"kind": "shortcut", "value": "ctrl+shift+m"}}
    key = {"action": "mute", "label": "Mute", "icon": "", "states": [second]}
    assert backend.saveKeypadKey(0, 2, key)
    stored = backend.keypadPages[0]["keys"][1]
    assert stored["states"][0]["label"] == "Unmute" and "states" not in stored["states"][0]
    plates = tmp_path / "keypad/plates"
    assert (plates / "p0-k2.jpg").is_file() and (plates / "p0-k2-s1.jpg").is_file()
    # A second state that cannot run makes the whole key unsavable.
    assert not backend.saveKeypadKey(0, 2, {**key, "states": [{"action": "custom", "custom": {"kind": "shortcut", "value": "!!"}}]})
    assert backend.saveKeypadKey(0, 2, {"action": "mute", "label": "Mute", "icon": ""})
    assert "states" not in backend.keypadPages[0]["keys"][1]
    assert not (plates / "p0-k2-s1.jpg").exists(), "the old state's plate must not show"


def test_a_pack_state_never_points_at_a_local_file(backend, tmp_path):
    raw = {"slot": 0, "id": "p1-k1", "juhradial": {"action": "mute", "label": "M", "icon": "", "custom": {},
           "states": [{"action": "copy", "label": "C", "icon": "", "custom": {}, "plate": str(tmp_path / "config.json")}]}}
    (tmp_path / "config.json").write_text("{}")
    key = backend._own_pack_key(raw, "", [], tmp_path)
    assert key["states"][0]["label"] == "C" and "plate" not in key["states"][0]


def test_key_style_colours_the_plate_and_can_hide_the_label(backend, tmp_path):
    backend.addKeypadPage("Home")
    assert backend.saveKeypadKey(0, 1, {"action": "copy", "label": "Copy", "icon": "edit-copy-symbolic",
                                        "style": {"background": "#0D2A4A", "hide_label": True, "evil": "x"}})
    assert backend.keypadPages[0]["keys"][0]["style"] == {"background": "#0d2a4a", "hide_label": True}
    assert backend.saveKeypadKey(0, 2, {"action": "copy", "label": "Copy", "icon": "edit-copy-symbolic",
                                        "style": {"background": "red; x", "hide_label": "yes"}})
    assert "style" not in backend.keypadPages[0]["keys"][1], "only #rrggbb and a real true are kept"
    plates = tmp_path / "keypad/plates"
    styled, plain = QImage(str(plates / "p0-k1.jpg")), QImage(str(plates / "p0-k2.jpg"))
    corner = styled.pixelColor(2, 2)
    assert abs(corner.red() - 0x0d) < 10 and abs(corner.blue() - 0x4a) < 10
    # The label band (bottom middle) holds light text on the plain key only.
    band = lambda img: max(img.pixelColor(x, 104).lightness() for x in range(30, 88))
    assert band(plain) > 120 and band(styled) < 90


@pytest.mark.parametrize("own", [False, True])
def test_a_pack_key_id_cannot_reach_a_file_outside_the_pack(backend, tmp_path, own):
    secret = tmp_path / "private"
    secret.mkdir()
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(secret / "secret.jpg"))
    raw = {"slot": 0, "id": "../" * 12 + str(secret / "secret").lstrip("/"), "label": "x"}
    if own:
        raw.update(juhradial={"action": "none", "label": "x", "icon": "", "custom": {}}, picture=True)
    pack = tmp_path / "p.zip"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("portable.json", json.dumps({"pages": [{"title": "P", "keys": [raw]}]}))
        zf.writestr("keys-118/artsy/k1.jpg", b"")
    assert backend.importKeypadPack(str(pack))
    assert "private" not in str(backend.keypadPages[-1]["keys"][0].get("plate", ""))
