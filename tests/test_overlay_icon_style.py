#!/usr/bin/env python3
"""The on-screen radial menu follows Settings → Appearance → Icon style.

"line" draws the 0.4.5 composed slice buttons and line glyphs, "classic" the
0.4.4 glossy buttons and PNG glyphs, "mono" flat single-colour glyphs only.
The overlay resolves the style from config.json (radial.icon_style, with the
older radial.monochrome_icons flag as fallback) on every open and reads the
settings app's own assets, so the live wheel matches the settings previews.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_overlay_icon_style.py -q
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "overlay"))

from PyQt6.QtGui import QColor, QGuiApplication

# QPixmap needs a live QGuiApplication; keep it referenced for the module.
_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None

import overlay_actions  # noqa: E402

ASSETS = REPO_ROOT / "settings-qt" / "assets"


@pytest.fixture
def style(monkeypatch):
    """Set overlay_actions.ICON_STYLE for a test and drop the pixmap caches."""

    def _set(name):
        monkeypatch.setattr(overlay_actions, "ICON_STYLE", name)
        overlay_actions._SLICE_BTN_CACHE.clear()
        overlay_actions._GLYPH_CACHE.clear()

    yield _set
    overlay_actions._SLICE_BTN_CACHE.clear()
    overlay_actions._GLYPH_CACHE.clear()


@pytest.fixture
def default_slices(monkeypatch):
    monkeypatch.setattr(overlay_actions, "ACTIONS", list(overlay_actions.DEFAULT_ACTIONS))
    monkeypatch.setattr(overlay_actions, "ACTION_IDS", list(overlay_actions.DEFAULT_ACTION_IDS))
    monkeypatch.setattr(overlay_actions, "ACTION_ICON_NAMES",
                        list(overlay_actions.DEFAULT_ACTION_ICON_NAMES))
    monkeypatch.setattr(overlay_actions, "MEDIA_PLAYING", False)


# ---- style resolution from config ------------------------------------------

def _with_radial(monkeypatch, radial):
    monkeypatch.setattr(overlay_actions, "_config_radial_section", lambda: radial)


def test_icon_style_from_config(monkeypatch):
    for name in ("line", "classic", "mono"):
        _with_radial(monkeypatch, {"icon_style": name})
        assert overlay_actions.load_icon_style() == name


def test_icon_style_falls_back_to_monochrome_flag(monkeypatch):
    # Configs written before radial.icon_style existed carry only the flag.
    _with_radial(monkeypatch, {"monochrome_icons": True})
    assert overlay_actions.load_icon_style() == "mono"
    _with_radial(monkeypatch, {"monochrome_icons": False})
    assert overlay_actions.load_icon_style() == "line"
    _with_radial(monkeypatch, {})
    assert overlay_actions.load_icon_style() == "line"


def test_icon_style_rejects_unknown_values(monkeypatch):
    _with_radial(monkeypatch, {"icon_style": "neon", "monochrome_icons": True})
    assert overlay_actions.load_icon_style() == "mono"


# ---- asset resolution per style --------------------------------------------

def test_line_uses_current_buttons_and_svg_glyphs():
    assert overlay_actions._slice_button_path("files", "line") == os.path.join(
        overlay_actions._settings_assets_dir(), "slices", "btn_files.png")
    assert overlay_actions._glyph_path("folder-symbolic", "line").endswith(
        os.path.join("icons", "mono", "folder-symbolic.svg"))


def test_classic_prefers_the_0_4_4_sets_then_falls_back():
    classic_btn = overlay_actions._slice_button_path("files", "classic")
    assert classic_btn.endswith(os.path.join("slices", "classic", "btn_files.png"))
    # "none" only exists in the current set: classic falls back like the
    # settings app's Theme.sliceButton does.
    assert overlay_actions._slice_button_path("none", "classic").endswith(
        os.path.join("slices", "btn_none.png"))
    assert overlay_actions._glyph_path("folder-symbolic", "classic").endswith(
        os.path.join("icons", "classic", "mono", "folder-symbolic.png"))


def test_mono_has_no_buttons_only_glyphs(style, default_slices):
    style("mono")
    assert overlay_actions._slice_button_path("files", "mono") is None
    assert overlay_actions.get_slice_button(6, 66) is None
    glyph = overlay_actions.get_style_glyph(6, 30, QColor("#ffffff"))
    assert glyph is not None and glyph.width() == 30


def test_unknown_glyph_name_lets_the_painter_draw_its_own(style, default_slices):
    style("line")
    overlay_actions.ACTION_ICON_NAMES[0] = "no-such-icon-symbolic"  # fixture owns the list
    assert overlay_actions.get_style_glyph(0, 30, QColor("#ffffff")) is None


@pytest.mark.parametrize("name", ["line", "classic"])
def test_buttons_scale_to_the_requested_size(style, default_slices, name):
    style(name)
    btn = overlay_actions.get_slice_button(6, 66)
    assert btn is not None and btn.width() == 66 and btn.height() == 66


def test_glyph_is_tinted_to_the_requested_colour(style, default_slices):
    style("line")
    glyph = overlay_actions.get_style_glyph(6, 30, QColor("#ff0000"))
    img = glyph.toImage()
    opaque = [img.pixelColor(x, y) for x in range(30) for y in range(30)
              if img.pixelColor(x, y).alpha() > 200]
    assert opaque, "glyph rendered nothing"
    assert all(c.red() == 255 and c.green() == 0 and c.blue() == 0 for c in opaque)


def test_play_pause_shows_pause_button_while_playing(style, default_slices, monkeypatch):
    style("line")
    a = overlay_actions.get_slice_button(0, 50)
    monkeypatch.setattr(overlay_actions, "MEDIA_PLAYING", True)
    b = overlay_actions.get_slice_button(0, 50)
    assert a is not None and b is not None
    assert a.toImage() != b.toImage()


def test_cache_is_keyed_by_style(style, default_slices):
    style("line")
    line_btn = overlay_actions.get_slice_button(6, 66)
    style("classic")
    classic_btn = overlay_actions.get_slice_button(6, 66)
    assert line_btn.toImage() != classic_btn.toImage()


# ---- a user-picked app icon wins over the family -----------------------------

def test_user_app_icon_wins_over_button_and_glyph(style, default_slices, tmp_path):
    icon = tmp_path / "app.png"
    icon.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000d49444154789c6360f8cfc00000030101003e6e0"
        "a3b0000000049454e44ae426082"))
    label, atype, cmd, color, _icon, sub = overlay_actions.ACTIONS[6]
    overlay_actions.ACTIONS[6] = (label, atype, cmd, color, os.fspath(icon), sub)  # fixture owns the list
    style("line")
    assert overlay_actions.get_slice_button(6, 66) is None
    assert overlay_actions.get_style_glyph(6, 30, QColor("#ffffff")) is None


# ---- config load keeps ids and names in lockstep with ACTIONS --------------

def _write_config(home, slices, easy_switch=False):
    cfg_dir = home / ".config" / "juhradial"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "radial_menu": {"slices": slices, "easy_switch_shortcuts": easy_switch},
    }))


def test_load_actions_tracks_ids_and_icon_names(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    _write_config(tmp_path, [
        {"label": "Copy", "action_id": "copy", "type": "shortcut",
         "command": "ctrl+c", "color": "blue", "icon": "edit-copy-symbolic"},
        {"label": "Files", "action_id": "files", "type": "exec",
         "command": "dolphin", "color": "teal", "icon": "folder-symbolic"},
    ])
    actions = overlay_actions.load_actions_from_config()
    assert len(actions) == 2
    assert overlay_actions.ACTION_IDS == ["copy", "files"]
    assert overlay_actions.ACTION_ICON_NAMES == ["edit-copy-symbolic", "folder-symbolic"]


def test_easy_switch_slot_maps_to_its_own_button_and_glyph(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    slices = [{"label": f"S{i}", "action_id": "files", "type": "exec",
               "command": "x", "color": "teal", "icon": "folder-symbolic"} for i in range(8)]
    _write_config(tmp_path, slices, easy_switch=True)
    overlay_actions.load_actions_from_config()
    assert overlay_actions.ACTION_IDS[5] == "easy_switch"
    assert overlay_actions.ACTION_ICON_NAMES[5] == "easy-switch"
    assert (ASSETS / "slices" / "btn_easy_switch.png").exists()
    assert (ASSETS / "icons" / "mono" / "easy-switch.svg").exists()


def test_missing_config_resets_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    monkeypatch.setattr(overlay_actions, "ACTION_IDS", ["stale"])
    assert overlay_actions.load_actions_from_config() == overlay_actions.DEFAULT_ACTIONS
    assert overlay_actions.ACTION_IDS == overlay_actions.DEFAULT_ACTION_IDS
    assert overlay_actions.ACTION_ICON_NAMES == overlay_actions.DEFAULT_ACTION_ICON_NAMES


# ---- every default action has a button in both button styles ---------------

def test_every_default_action_has_a_button_in_both_sets():
    for action_id in overlay_actions.DEFAULT_ACTION_IDS + ["pause", "easy_switch"]:
        for name in ("line", "classic"):
            assert overlay_actions._slice_button_path(action_id, name), (action_id, name)
