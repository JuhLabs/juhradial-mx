#!/usr/bin/env python3
"""Issue #59: a click outside the ring dismisses the menu, in toggle mode only.

Closed as completed, but the scrim lived only on the feat/qt-qml-ui branch and
never shipped (audit P0 #2). These pin the behaviour PRD section 9 asks for:
quick tap -> toggle mode shows the scrim (unless radial.click_outside_closes
is false), hold-and-release never shows it, a click on the scrim closes the
menu without executing and the scrim can never outlive the ring.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_overlay_scrim.py -q
"""

import ast
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtCore")

from PyQt6.QtCore import pyqtSlot  # noqa: E402

OVERLAY = Path(__file__).resolve().parents[1] / "overlay" / "juhradial-overlay.py"


def _tree():
    return ast.parse(OVERLAY.read_text(encoding="utf-8"))


def _menu_method(name):
    cls = next(n for n in _tree().body if isinstance(n, ast.ClassDef) and n.name == "RadialMenu")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    ns = {"pyqtSlot": pyqtSlot}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(OVERLAY), "exec"), ns)
    return ns[name]


class _Scrim:
    def __init__(self):
        self.visible = False
        self.lowered = False

    def cover_all(self):
        pass

    def show(self):
        self.visible = True

    def lower(self):
        self.lowered = True

    def hide(self):
        self.visible = False

    def isVisible(self):
        return self.visible


def _menu(held_ms, click_outside=True):
    closed = []
    m = SimpleNamespace(
        TAP_THRESHOLD_MS=250, toggle_mode=False, show_time=time.time() - held_ms / 1000,
        cursor_timer=SimpleNamespace(start=lambda: None), _scrim=_Scrim(),
        isVisible=lambda: True, raise_=lambda: None,
        _click_outside_closes=lambda: click_outside,
        _close_menu=lambda execute=True: closed.append(execute),
    )
    return m, closed


def test_quick_tap_opens_toggle_mode_with_the_scrim_behind_the_ring():
    m, closed = _menu(held_ms=40)
    _menu_method("on_hide")(m)
    assert m.toggle_mode and m._scrim.visible and m._scrim.lowered and closed == []


def test_opt_out_leaves_toggle_mode_without_a_scrim():
    m, closed = _menu(held_ms=40, click_outside=False)
    _menu_method("on_hide")(m)
    assert m.toggle_mode and not m._scrim.visible


def test_hold_and_release_never_shows_the_scrim():
    m, closed = _menu(held_ms=900)
    _menu_method("on_hide")(m)
    assert not m._scrim.visible and closed == [True]


def _scrim_method(name):
    cls = next(n for n in _tree().body if isinstance(n, ast.ClassDef) and n.name == "_DismissScrim")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(OVERLAY), "exec"), ns)
    return ns[name]


class _FakeScrim:
    def __init__(self, ring_visible=True):
        self.visible = True
        self.order = []
        self._ring = SimpleNamespace(isVisible=lambda: ring_visible)
        self._on_dismiss = lambda: self.order.append(("dismiss", self.visible))

    def hide(self):
        self.visible = False


def test_clicking_the_scrim_dismisses_without_executing_and_hides_first():
    s = _FakeScrim()
    _scrim_method("mousePressEvent")(s, None)
    assert s.order == [("dismiss", False)]


def test_watchdog_hides_a_scrim_that_outlived_the_ring():
    s = _FakeScrim(ring_visible=False)
    _scrim_method("_check_ring")(s)
    assert not s.visible
    alive = _FakeScrim(ring_visible=True)
    _scrim_method("_check_ring")(alive)
    assert alive.visible


def test_scrim_never_takes_focus():
    src = OVERLAY.read_text(encoding="utf-8")
    cls = src[src.index("class _DismissScrim(QWidget):"):]
    for flag in ("WindowDoesNotAcceptFocus", "WA_ShowWithoutActivating", "BypassWindowManagerHint"):
        assert flag in cls


def test_every_close_path_hides_the_scrim():
    src = OVERLAY.read_text(encoding="utf-8")
    close = src[src.index("    def _close_menu(self, execute=True):"):]
    close = close[:close.index("\n    def ", 10)]
    assert "self._scrim.hide()" in close
    hide = src[src.index("    def hideEvent(self, event):"):]
    assert "self._scrim.hide()" in hide[:400]
    # the setting the Settings toggle writes is the one the overlay reads
    assert '.get("click_outside_closes", True)' in src


# ---- Settings > Startup > Show tray icon (was a dead toggle) ----

def _module_function(name):
    fn = next(n for n in _tree().body if isinstance(n, ast.FunctionDef) and n.name == name)
    from pathlib import Path as _P
    ns = {"Path": _P}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(OVERLAY), "exec"), ns)
    return ns[name], ns


def test_tray_icon_follows_the_setting(tmp_path, monkeypatch):
    wanted, ns = _module_function("tray_icon_wanted")
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "juhradial"
    cfg.mkdir(parents=True)
    assert wanted() is True                          # no config: shown
    (cfg / "config.json").write_text('{"app": {"show_tray_icon": false}}')
    assert wanted() is False
    (cfg / "config.json").write_text('{"app": {}}')
    assert wanted() is True


def test_tray_visibility_is_applied_at_start_and_followed_live():
    src = OVERLAY.read_text(encoding="utf-8")
    assert "tray.setVisible(tray_icon_wanted())" in src
    assert "app.tray_watch = follow_tray_setting(app, app.tray)" in src
    assert "from pathlib import Path" in src
