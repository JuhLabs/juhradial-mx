"""Regression tests for SmartShift sensitivity and mode readback."""

import ast
from collections.abc import Callable
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import cast


SCROLL_PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "overlay"
    / "settings_page_scroll.py"
)


def _scroll_page_method(name: str) -> ast.FunctionDef:
    module = ast.parse(SCROLL_PAGE_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "ScrollPage":
            continue
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == name:
                return statement
    raise AssertionError(f"ScrollPage.{name} must exist")


def _load_method(name: str, namespace=None):
    method = _scroll_page_method(name)
    method.decorator_list = []
    scope = {} if namespace is None else dict(namespace)
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "<scroll-page>", "exec"),
        scope,
    )
    return scope[name]


def test_easy_to_hard_maps_to_automatic_thresholds_in_order():
    ui_to_device = _load_method("_smartshift_ui_to_device")

    assert [ui_to_device(value) for value in (1, 25, 50, 75, 100)] == [
        1,
        13,
        25,
        37,
        49,
    ]
    thresholds = [ui_to_device(value) for value in range(1, 101)]
    assert thresholds == sorted(thresholds)
    assert min(thresholds) == 1
    assert max(thresholds) == 49


def test_every_automatic_threshold_round_trips_exactly():
    ui_to_device = _load_method("_smartshift_ui_to_device")
    device_to_ui = _load_method("_smartshift_device_to_ui")

    for threshold in range(1, 50):
        assert ui_to_device(device_to_ui(threshold)) == threshold


def test_device_readback_uses_dbus_mode_contract_and_preserves_sensitivity():
    config_writes = []

    class FakeConfig:
        @staticmethod
        def get(_section, key, default=None):
            return 72 if key == "smartshift_threshold" else default

        @staticmethod
        def set(section, key, value):
            config_writes.append((section, key, value))

    class FakeValue:
        def __init__(self, value):
            self.value = value

        def get_boolean(self):
            return self.value

        def get_byte(self):
            return self.value

    class FakeResult:
        def __init__(self, enabled, threshold):
            self.values = (enabled, threshold)

        def get_child_value(self, index):
            return FakeValue(self.values[index])

    class FakeProxy:
        def __init__(self, enabled, threshold):
            self.result = FakeResult(enabled, threshold)

        def call_finish(self, _async_result):
            return self.result

    method = _load_method(
        "_on_smartshift_loaded",
        {
            "config": FakeConfig(),
            "GLib": SimpleNamespace(Error=Exception),
        },
    )
    device_to_ui = _load_method("_smartshift_device_to_ui")
    applied = []
    page = SimpleNamespace(
        _has_local_scroll_state_edits=lambda: False,
        _apply_saved_scroll_mode=lambda: None,
        _apply_initial_scroll_state=lambda **state: applied.append(state),
        _smartshift_device_to_ui=device_to_ui,
    )
    page._on_smartshift_loaded = MethodType(cast(Callable, method), page)

    cases = [
        (False, 0, "ratchet", 72),
        (True, 0, "freespin", 72),
        (True, 25, "smartshift", 50),
    ]
    for enabled, threshold, expected_mode, expected_sensitivity in cases:
        page._on_smartshift_loaded(FakeProxy(enabled, threshold), object(), None)
        assert applied[-1] == {
            "mode": expected_mode,
            "threshold": expected_sensitivity,
        }

    assert config_writes[-2:] == [
        ("scroll", "mode", "smartshift"),
        ("scroll", "smartshift_threshold", 50),
    ]
