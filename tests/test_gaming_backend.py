#!/usr/bin/env python3
"""Gaming tab: the switch shows the daemon's state (no optimistic flip),
presets reach the daemon (1 to 5, 12-character names, snapped DPI, the
active one kept pointing at the same preset through moves and removals),
and the defaults match daemon config.rs.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_gaming_backend.py -q
"""
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None

import bridge.backend as bk  # noqa: E402


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    b.calls, b.replies = [], {}
    b.daemon._available = True
    b.daemon.call_async = lambda *a, **k: None
    b.daemon.call_then = lambda m, cb, *a: (b.calls.append((m, a)), cb(b.replies.get(m, [])))
    return b


def test_switch_follows_the_daemon_not_the_click(backend):
    backend.setGamingMode(True)
    assert backend.calls[-1] == ("SetGamingMode", (True,))
    assert backend.gamingMode is False          # until GamingModeChanged
    backend.replies["GetGamingStatus"] = [True, True, 2, 1000, True, True]
    backend._set_gaming_live(True)
    assert backend.gamingMode is True
    assert backend.gamingStatus == {"auto": True, "stage": 2, "dpi": 1000,
                                    "gamemodeInstalled": True, "gamemodeActive": True}


def test_presets_edit_move_and_remove(backend):
    assert [p["name"] for p in backend.gamingPresets()] == ["Precision", "Normal", "Fast"]
    backend.setGamingPreset(0, "name", "  A very long preset name ")
    backend.setGamingPreset(0, "dpi", 433)
    p0 = backend.gamingPresets()[0]
    assert p0["name"] == "A very long " and p0["dpi"] == 450
    backend.setActiveGamingPreset(2)
    backend.moveGamingPreset(2, -1)             # the active preset moves with it
    assert backend.get("gaming.active_dpi_profile") == 1
    assert backend.gamingPresets()[1]["name"] == "Fast"
    backend.removeGamingPreset(0)               # before the active one
    assert backend.get("gaming.active_dpi_profile") == 0
    for _ in range(6):
        backend.addGamingPreset()
    assert len(backend.gamingPresets()) == 5
    while len(backend.gamingPresets()) > 1:
        backend.removeGamingPreset(0)
    backend.removeGamingPreset(0)               # never below one
    assert len(backend.gamingPresets()) == 1


def test_defaults_match_the_daemon():
    rs = (REPO / "daemon" / "src" / "config.rs").read_text()
    presets = re.findall(r'\("(\w+)", (\d+), "(\w+)"\)', rs.split("fn default_gaming_presets")[1][:300])
    assert [(n, int(d), c) for n, d, c in presets] == [
        (p["name"], p["dpi"], p["color"]) for p in bk.DEFAULT_CONFIG["gaming"]["dpi_profiles"]]
    assert bk.DEFAULT_CONFIG["gaming"]["suppress_overlay"] is True
    assert "fn default_active_preset() -> usize { 1 }" in rs
    assert bk.DEFAULT_CONFIG["gaming"]["active_dpi_profile"] == 1
