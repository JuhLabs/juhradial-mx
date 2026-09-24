#!/usr/bin/env python3
"""The Qt app's DEFAULT_CONFIG is merged into every save, so each value must
equal what the overlay/daemon assume when the key is absent. Otherwise the
first unrelated save silently changes behaviour (audit P0 #9): the ring grew
an Easy-Switch slice, the Flow edge flipped, English was pinned, games showed
the overlay. Each pin below points at the runtime line that is the truth.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_config_defaults_parity.py -q
"""

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

import bridge.backend as bk  # noqa: E402

D = bk.DEFAULT_CONFIG


def _src(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def test_easy_switch_shortcuts_match_the_overlay():
    assert D["radial_menu"]["easy_switch_shortcuts"] is False
    assert re.search(r'"easy_switch_shortcuts", False', _src("overlay/overlay_actions.py"))


def test_easy_switch_host_os_matches_the_overlay():
    assert D["radial_menu"]["easy_switch_host_os"] == ["unknown"] * 3
    assert '"easy_switch_host_os", ["unknown", "unknown", "unknown"]' in _src("overlay/overlay_actions.py")


def test_flow_direction_matches_the_edge_detector():
    assert D["flow"]["direction"] == "right"
    src = _src("overlay/flow/edge_detector.py")
    assert 'self._flow_direction = "right"' in src
    assert 'flow.get("direction", "right")' in src


def test_gaming_suppress_overlay_matches_the_daemon():
    assert D["gaming"]["suppress_overlay"] is True
    assert re.search(r"suppress_overlay: true", _src("daemon/src/gaming.rs"))


@pytest.mark.parametrize("path", [
    ("language",),                  # absent = desktop locale
    ("pointer", "dpi"),             # the daemon replays present keys at every wake
    ("scroll", "mode"),
    ("scroll", "smartshift_threshold"),
    ("scroll", "natural"),
    ("scroll", "smooth"),
    ("radial", "icon_style"),       # readers default to mono
    ("radial", "monochrome_icons"),
])
def test_keys_that_must_never_be_merged_into_a_save(path):
    node = D
    for key in path[:-1]:
        node = node.get(key, {})
    assert path[-1] not in node


def test_qml_fallbacks_agree_with_the_defaults():
    pages = REPO / "settings-qt" / "qml" / "pages"
    assert 'cfg("radial_menu.easy_switch_shortcuts", false)' in (pages / "EasySwitchPage.qml").read_text()
    assert 'Backend.get("flow.direction", "right")' in (pages / "FlowPage.qml").read_text()
    assert '!cfg("gaming.suppress_overlay", true)' in (pages / "GamingPage.qml").read_text()
    assert 'Backend.get("language", "system")' in (pages / "SettingsPage.qml").read_text()


def test_language_list_offers_system_default_first():
    b = bk.Backend.__new__(bk.Backend)
    langs = bk.Backend.languages(b)
    assert langs[0]["id"] == "system"
