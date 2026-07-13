"""Regression contracts for a responsive Settings window startup."""

import ast
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast


REPO_ROOT = Path(__file__).resolve().parents[1]
SCROLL_PAGE_PATH = REPO_ROOT / "overlay" / "settings_page_scroll.py"
SETTINGS_DASHBOARD_PATH = REPO_ROOT / "overlay" / "settings_dashboard.py"
SETTINGS_WIDGETS_PATH = REPO_ROOT / "overlay" / "settings_widgets.py"
OVERLAY_ACTIONS_PATH = REPO_ROOT / "overlay" / "overlay_actions.py"


def _load_device_settings_method() -> ast.FunctionDef:
    module = ast.parse(SCROLL_PAGE_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "ScrollPage":
            continue
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == "_load_device_settings":
                return statement
    raise AssertionError("ScrollPage._load_device_settings must exist")


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
