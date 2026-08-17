"""App-picker icon import: resolving/caching a picked app's icon, loading
arbitrary icon-file paths into the overlay's pixmap cache, and submenu rows
that launch an app instead of a URL.

Run: python3 -m pytest tests/test_app_icon_picker.py -q
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, "overlay")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio

from PyQt6.QtGui import QGuiApplication

# QPixmap/QSvgRenderer need a live QGuiApplication (offscreen platform, set
# above) even outside a real display session.
_qt_app = QGuiApplication.instance() or QGuiApplication([])

from overlay_actions import USER_ICONS, load_user_icon, submenu_from_config
from settings_dialog_app_picker import command_for_app, resolve_and_cache_icon


SVG_STUB = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
    '<rect width="16" height="16"/></svg>'
)


def test_command_for_app_strips_field_codes():
    app = SimpleNamespace(get_string=lambda key: "firefox %u")
    assert command_for_app(app) == "firefox"

    app = SimpleNamespace(get_string=lambda key: "code --new-window %F")
    assert command_for_app(app) == "code --new-window"


def test_resolve_and_cache_icon_from_file_icon(tmp_path, monkeypatch):
    src = tmp_path / "app.svg"
    src.write_text(SVG_STUB, encoding="utf-8")

    import settings_config

    monkeypatch.setattr(settings_config.ConfigManager, "CONFIG_DIR", tmp_path / "config")

    app = SimpleNamespace(
        get_icon=lambda: Gio.FileIcon.new(Gio.File.new_for_path(str(src))),
        get_id=lambda: "org.example.App.desktop",
    )
    cached = resolve_and_cache_icon(app)

    assert cached is not None
    assert os.path.isfile(cached)
    assert cached != str(src)  # copied into the cache dir, not the original


def test_resolve_and_cache_icon_returns_none_without_icon():
    app = SimpleNamespace(get_icon=lambda: None, get_id=lambda: "x")
    assert resolve_and_cache_icon(app) is None


def test_load_user_icon_caches_svg(tmp_path):
    USER_ICONS.clear()
    path = tmp_path / "imported.svg"
    path.write_text(SVG_STUB, encoding="utf-8")

    assert load_user_icon(str(path)) is True
    assert str(path) in USER_ICONS

    # Second call hits the cache without re-reading the file.
    assert load_user_icon(str(path)) is True


def test_load_user_icon_rejects_missing_or_relative_paths(tmp_path):
    assert load_user_icon("") is False
    assert load_user_icon("relative/icon.svg") is False
    assert load_user_icon(str(tmp_path / "missing.svg")) is False


def test_submenu_app_entry_round_trips(tmp_path):
    USER_ICONS.clear()
    icon_path = tmp_path / "app-icon.svg"
    icon_path.write_text(SVG_STUB, encoding="utf-8")

    links = [
        {"label": "Files", "type": "exec", "command": "dolphin", "icon": str(icon_path)},
        {"label": "Docs", "url": "https://docs.example.com"},
    ]
    result = submenu_from_config(links)

    assert result == [
        ("Files", "exec", "dolphin", str(icon_path)),
        ("Docs", "url", "https://docs.example.com", "browser"),
    ]
    # The pixmap isn't rendered here - only a plain filesystem check runs at
    # config-load time, since this path also runs at import time (before
    # QApplication exists) and QPixmap/QSvgRenderer would abort the process.
    assert str(icon_path) not in USER_ICONS
    assert load_user_icon(str(icon_path)) is True
    assert str(icon_path) in USER_ICONS


def test_submenu_app_entry_without_command_is_skipped():
    links = [{"label": "Broken", "type": "exec", "command": "", "icon": ""}]
    assert submenu_from_config(links) is None


def test_submenu_app_entry_with_unresolvable_icon_falls_back_to_browser():
    links = [{"label": "Files", "type": "exec", "command": "dolphin", "icon": "/no/such/icon.svg"}]
    result = submenu_from_config(links)
    assert result == [("Files", "exec", "dolphin", "browser")]


def test_loading_config_with_app_icon_does_not_touch_qt_before_app_exists(tmp_path):
    """Regression test: overlay_actions.ACTIONS is built by
    load_actions_from_config() at *import* time (juhradial-overlay.py
    imports overlay_actions before constructing QApplication). If that path
    ever constructs a QPixmap/QSvgRenderer directly, Qt aborts the whole
    process - this bit us in production for a slice with an imported app
    icon. Runs in a fresh subprocess with no QApplication ever created."""
    icon_path = tmp_path / "app-icon.svg"
    icon_path.write_text(SVG_STUB, encoding="utf-8")

    fake_home = tmp_path / "home"
    config_dir = fake_home / ".config" / "juhradial"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "radial_menu": {
                    "slices": [
                        {
                            "label": "App",
                            "type": "exec",
                            "command": "some-app",
                            "color": "green",
                            "icon": str(icon_path),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    overlay_dir = Path(__file__).resolve().parents[1] / "overlay"
    env = {**os.environ, "HOME": str(fake_home)}
    result = subprocess.run(
        [sys.executable, "-c", "import overlay_actions"],
        cwd=str(overlay_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
