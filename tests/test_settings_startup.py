"""Regression contracts for a responsive Settings window startup."""

import ast
import os
from collections.abc import Callable
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import cast


REPO_ROOT = Path(__file__).resolve().parents[1]
SCROLL_PAGE_PATH = REPO_ROOT / "overlay" / "settings_page_scroll.py"
SETTINGS_DASHBOARD_PATH = REPO_ROOT / "overlay" / "settings_dashboard.py"
SETTINGS_WIDGETS_PATH = REPO_ROOT / "overlay" / "settings_widgets.py"
OVERLAY_ACTIONS_PATH = REPO_ROOT / "overlay" / "overlay_actions.py"


def _scroll_page_method(name: str) -> ast.FunctionDef:
    module = ast.parse(SCROLL_PAGE_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "ScrollPage":
            continue
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == name:
                return statement
    raise AssertionError(f"ScrollPage.{name} must exist")


def _load_device_settings_method() -> ast.FunctionDef:
    return _scroll_page_method("_load_device_settings")


def _settings_window_method(name: str) -> ast.FunctionDef:
    module = ast.parse(SETTINGS_DASHBOARD_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SettingsWindow":
            continue
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == name:
                return statement
    raise AssertionError(f"SettingsWindow.{name} must exist")


def _calls_named(method: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def test_initial_scroll_device_read_does_not_block_the_gtk_main_thread():
    method = _load_device_settings_method()
    calls = [
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    ]

    assert "call_sync" not in calls
    assert "_get_dbus_proxy" not in calls
    assert "bus_get" in calls


def test_initial_scroll_device_reads_never_overwrite_local_edits():
    initial_load = _load_device_settings_method()
    initial_apply = _scroll_page_method("_apply_initial_scroll_state")
    saved_mode = _scroll_page_method("_apply_saved_scroll_mode")
    handlers = [
        _scroll_page_method("_on_smartshift_support_loaded"),
        _scroll_page_method("_on_smartshift_loaded"),
        _scroll_page_method("_on_hiresscroll_loaded"),
    ]
    local_edit_handlers = [
        _scroll_page_method("_on_mode_changed"),
        _scroll_page_method("_on_sensitivity_changed"),
        _scroll_page_method("_on_smooth_changed"),
    ]

    def method_calls(method: ast.FunctionDef, name: str) -> bool:
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == name
            for node in ast.walk(method)
        )

    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "_initial_scroll_state_generation"
            for target in node.targets
        )
        for node in ast.walk(initial_load)
    )
    assert all(method_calls(handler, "_has_local_scroll_state_edits") for handler in handlers)
    assert all(method_calls(handler, "_mark_scroll_state_user_edit") for handler in local_edit_handlers)
    assert method_calls(saved_mode, "_has_local_scroll_state_edits")
    assert method_calls(initial_apply, "set_value")


def test_delayed_smartshift_reply_is_ignored_after_local_edit():
    config_writes = []

    class FakeConfig:
        @staticmethod
        def get(_section, key, default=None):
            return "smartshift" if key == "mode" else default

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
        def get_child_value(self, index):
            return FakeValue((True, 64)[index])

    class FakeProxy:
        @staticmethod
        def call_finish(_result):
            return FakeResult()

    class FakeControl:
        def __init__(self):
            self.calls = []

        def set_mode(self, value):
            self.calls.append(("mode", value))

        def set_value(self, value):
            self.calls.append(("value", value))

        def set_visible(self, value):
            self.calls.append(("visible", value))

    namespace: dict[str, object] = {
        "config": FakeConfig(),
        "GLib": SimpleNamespace(Error=Exception),
    }
    method_names = [
        "_mark_scroll_state_user_edit",
        "_has_local_scroll_state_edits",
        "_apply_initial_scroll_state",
        "_apply_saved_scroll_mode",
        "_on_smartshift_loaded",
    ]
    methods: list[ast.stmt] = [_scroll_page_method(name) for name in method_names]
    exec(compile(ast.Module(body=methods, type_ignores=[]), "<scroll-page>", "exec"), namespace)

    page = SimpleNamespace(
        _scroll_state_generation=0,
        _initial_scroll_state_generation=0,
        _applying_initial_scroll_state=False,
        mode_selector=FakeControl(),
        sens_scale=FakeControl(),
        sensitivity_box=FakeControl(),
        smooth_switch=FakeControl(),
        _update_sens_label=lambda _value: None,
    )
    for name in method_names:
        setattr(page, name, MethodType(cast(Callable, namespace[name]), page))

    page._mark_scroll_state_user_edit()
    page._on_smartshift_loaded(FakeProxy(), object(), None)

    assert page.mode_selector.calls == []
    assert page.sens_scale.calls == []
    assert page.sensitivity_box.calls == []
    assert config_writes == []


def test_scroll_page_is_created_only_when_the_user_navigates_to_it():
    initializer = _settings_window_method("_create_pages")
    navigator = _settings_window_method("_on_nav_clicked")

    assert not _calls_named(initializer, "ScrollPage")
    assert _calls_named(navigator, "ScrollPage")


def test_mouse_visualization_decodes_the_png_only_once():
    source = SETTINGS_WIDGETS_PATH.read_text(encoding="utf-8")

    assert "Gdk.Texture.new_from_filename" not in source
    assert "save_to_png_bytes" not in source
    assert source.count("GdkPixbuf.Pixbuf.new_from_file(path)") == 2


def test_flow_dependencies_are_imported_only_on_flow_navigation():
    module = ast.parse(SETTINGS_DASHBOARD_PATH.read_text(encoding="utf-8"))
    navigator = _settings_window_method("_on_nav_clicked")

    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "settings_page_flow"
        for node in module.body
    )
    assert any(
        isinstance(node, ast.ImportFrom) and node.module == "settings_page_flow"
        for node in ast.walk(navigator)
    )


def test_only_kde_plasma_reuses_an_existing_settings_window(monkeypatch):
    module = ast.parse(OVERLAY_ACTIONS_PATH.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_requires_settings_relaunch"
    )
    namespace: dict[str, object] = {"os": os}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "<helper>", "exec"), namespace)
    requires_relaunch = cast(Callable[[], bool], namespace["_requires_settings_relaunch"])

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert requires_relaunch() is False

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert requires_relaunch() is True


def test_kde_settings_launch_activates_without_process_checks(monkeypatch):
    module = ast.parse(OVERLAY_ACTIONS_PATH.read_text(encoding="utf-8"))
    functions: list[ast.stmt] = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_requires_settings_relaunch", "open_settings"}
    ]

    class FakeSubprocess:
        DEVNULL = object()

        def __init__(self):
            self.run_calls = []
            self.popen_calls = []

        def run(self, *args, **kwargs):
            self.run_calls.append((args, kwargs))
            return SimpleNamespace(returncode=0)

        def Popen(self, *args, **kwargs):
            self.popen_calls.append((args, kwargs))

    fake_subprocess = FakeSubprocess()
    namespace: dict[str, object] = {
        "__file__": str(OVERLAY_ACTIONS_PATH),
        "os": os,
        "subprocess": fake_subprocess,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<overlay-actions>", "exec"), namespace)
    open_settings = cast(Callable[[], None], namespace["open_settings"])

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    open_settings()

    assert fake_subprocess.run_calls == []
    assert len(fake_subprocess.popen_calls) == 1
    popen_args, popen_kwargs = fake_subprocess.popen_calls[0]
    assert popen_args[0][0] == "python3"
    assert popen_args[0][1].endswith("settings_dashboard.py")
    assert popen_kwargs == {
        "stdout": fake_subprocess.DEVNULL,
        "stderr": fake_subprocess.DEVNULL,
    }
