#!/usr/bin/env python3
"""Monitor-switch pulse off KDE (#122): the overlay's 400 ms poll reads the
pointer from the compositor's live source where there is one. XWayland's
pointer stands still while the pointer is over native Wayland windows, so a
crossing there was only noticed once an XWayland window was under it.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_monitor_switch_cursor.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1] / "overlay"))

import overlay_cursor as oc  # noqa: E402


def _sources(monkeypatch, hypr=None, gnome=None, xwayland=(9, 9)):
    monkeypatch.setattr(oc, "get_cursor_position_hyprland", lambda: hypr)
    monkeypatch.setattr(oc, "get_cursor_position_gnome", lambda: gnome)
    monkeypatch.setattr(oc, "get_cursor_position_xwayland", lambda: xwayland)
    monkeypatch.setattr(oc, "_HAS_XWAYLAND", True)


def test_hyprland_and_gnome_use_their_live_pointer(monkeypatch):
    _sources(monkeypatch, hypr=(5, 5), gnome=(7, 7))
    monkeypatch.setattr(oc, "IS_HYPRLAND", True)
    monkeypatch.setattr(oc, "IS_GNOME", False)
    assert oc.get_cursor_position_live() == (5, 5)
    monkeypatch.setattr(oc, "IS_HYPRLAND", False)
    monkeypatch.setattr(oc, "IS_GNOME", True)
    assert oc.get_cursor_position_live() == (7, 7)


def test_xwayland_is_the_fallback(monkeypatch):
    _sources(monkeypatch, gnome=None)
    monkeypatch.setattr(oc, "IS_HYPRLAND", False)
    monkeypatch.setattr(oc, "IS_GNOME", True)   # helper extension not installed
    assert oc.get_cursor_position_live() == (9, 9)
    monkeypatch.setattr(oc, "IS_GNOME", False)
    monkeypatch.setattr(oc, "_HAS_XWAYLAND", False)
    assert oc.get_cursor_position_live() is None
