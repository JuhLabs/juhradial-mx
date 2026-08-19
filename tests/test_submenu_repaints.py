"""Behavioral regressions for stable submenu repaint scheduling."""

import ast
import math
from pathlib import Path
from types import SimpleNamespace


OVERLAY_PATH = Path(__file__).resolve().parents[1] / "overlay" / "juhradial-overlay.py"


def _radial_menu_method(name: str):
    module = ast.parse(OVERLAY_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "RadialMenu":
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef) and statement.name == name:
                    namespace = {
                        "math": math,
                        "MENU_RADIUS": 100,
                        "overlay_actions": SimpleNamespace(ACTIONS=[]),
                        "get_cursor_pos": lambda: (0, -50),
                        "_log": lambda _message: None,
                    }
                    exec(
                        compile(
                            ast.Module(body=[statement], type_ignores=[]),
                            f"<RadialMenu.{name}>",
                            "exec",
                        ),
                        namespace,
                    )
                    return namespace[name]
    raise AssertionError(f"RadialMenu.{name} not found")


class _Timer:
    def __init__(self, active=True):
        self.active = active
        self.stop_calls = 0
        self.start_calls = 0

    def isActive(self):
        return self.active

    def start(self):
        self.active = True
        self.start_calls += 1

    def stop(self):
        self.active = False
        self.stop_calls += 1


class _MenuHarness:
    def __init__(self, highlighted_subitem=-1, subitem_result=-1):
        self.menu_center_x = 0
        self.menu_center_y = 0
        self.ring_scale = 1.0
        self.win_px = 200
        self.toggle_mode = False
        self.submenu_active = True
        self.submenu_slice = 0
        self.submenu_progress = 1.0
        self.highlighted_subitem = highlighted_subitem
        self.highlighted_slice = 0
        self.slice_highlights = [0.0] * 8
        self.flash_progress = 0.0
        self.flash_slice = -1
        self.bloom_progress = 1.0
        self.center_pulse = 1.0
        self._anim_timer = _Timer()
        self._subitem_result = subitem_result
        self.update_calls = 0
        self.haptic_events = []

    def _hover_gate(self, *_args):
        return True

    def _get_center_radius(self):
        return 10

    def _get_subitem_at_position(self, *_args):
        return self._subitem_result

    def _update_kde_mask(self):
        pass

    def _trigger_haptic(self, event):
        self.haptic_events.append(event)

    def update(self):
        self.update_calls += 1


class _Point:
    def x(self):
        return 100

    def y(self):
        return 50


class _MouseEvent:
    def position(self):
        return _Point()


def test_cursor_poll_does_not_repaint_an_already_clear_submenu_highlight():
    menu = _MenuHarness(highlighted_subitem=-1, subitem_result=-1)

    _radial_menu_method("_poll_cursor")(menu)

    assert menu.highlighted_subitem == -1
    assert menu.update_calls == 0


def test_mouse_move_does_not_repaint_an_already_clear_submenu_highlight():
    menu = _MenuHarness(highlighted_subitem=-1, subitem_result=-1)

    _radial_menu_method("mouseMoveEvent")(menu, _MouseEvent())

    assert menu.highlighted_subitem == -1
    assert menu.update_calls == 0


def test_clearing_a_real_submenu_highlight_repaints_once():
    menu = _MenuHarness(highlighted_subitem=2, subitem_result=-1)

    _radial_menu_method("_poll_cursor")(menu)

    assert menu.highlighted_subitem == -1
    assert menu.update_calls == 1


def test_changing_the_highlighted_subitem_repaints_once():
    menu = _MenuHarness(highlighted_subitem=1, subitem_result=2)

    _radial_menu_method("_poll_cursor")(menu)

    assert menu.highlighted_subitem == 2
    assert menu.update_calls == 1


def test_changing_the_highlighted_subitem_triggers_haptic():
    menu = _MenuHarness(highlighted_subitem=1, subitem_result=2)

    _radial_menu_method("_poll_cursor")(menu)

    assert menu.haptic_events == ["slice_change"]


def test_clearing_the_highlighted_subitem_does_not_trigger_haptic():
    menu = _MenuHarness(highlighted_subitem=2, subitem_result=-1)

    _radial_menu_method("_poll_cursor")(menu)

    assert menu.haptic_events == []


def test_mouse_move_changing_the_highlighted_subitem_triggers_haptic():
    menu = _MenuHarness(highlighted_subitem=1, subitem_result=2)

    _radial_menu_method("mouseMoveEvent")(menu, _MouseEvent())

    assert menu.haptic_events == ["slice_change"]


def test_mouse_move_clearing_the_highlighted_subitem_does_not_trigger_haptic():
    menu = _MenuHarness(highlighted_subitem=2, subitem_result=-1)

    _radial_menu_method("mouseMoveEvent")(menu, _MouseEvent())

    assert menu.haptic_events == []


def test_submenu_animation_keeps_repainting_until_settled():
    menu = _MenuHarness()
    menu.submenu_progress = 0.5

    _radial_menu_method("_tick_animations")(menu)

    assert menu.submenu_progress > 0.5
    assert menu.update_calls == 1
    assert menu._anim_timer.stop_calls == 0


def test_settled_animation_stops_without_an_extra_repaint():
    menu = _MenuHarness()
    menu.highlighted_slice = -1

    _radial_menu_method("_tick_animations")(menu)

    assert menu.update_calls == 0
    assert menu._anim_timer.stop_calls == 1
