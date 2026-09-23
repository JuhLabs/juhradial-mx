#!/usr/bin/env python3
"""The Qt settings app carries every 0.4.4-era GTK behaviour it replaced.

Each test names the feature it guards: the PR #123 SmartShift mapping, the
Actions Ring geometry clamps (#134), quick links stored where the overlay
reads them (0.4.3), the app picker's command rule and icon cache (#117),
the autostart entry (#129, #32) and the connection link (0.4.4 Devices row).

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_settings_qt_parity.py -q
"""

import ast
import json
import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))
sys.path.insert(0, os.fspath(REPO_ROOT / "overlay"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None

import bridge.backend as bk  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _gtk_static(module_path, class_name, names):
    """Exec the named @staticmethods of a GTK page class without importing
    Gtk (the module pulls in gi at import time)."""
    tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name in names:
                    stmt.decorator_list = []
                    exec(compile(ast.Module(body=[stmt], type_ignores=[]), module_path, "exec"), ns)
    missing = [n for n in names if n not in ns]
    assert not missing, f"{missing} not found in {class_name}"
    return types.SimpleNamespace(**{n: ns[n] for n in names})


@pytest.fixture
def backend(tmp_path, monkeypatch):
    """A Backend on a scratch config dir with no autostart side effects."""
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    return bk.Backend()


def _disk(tmp_path):
    return json.loads((tmp_path / "config.json").read_text())


# ---------------------------------------------------------------------------
# SmartShift sensitivity (PR #123)
# ---------------------------------------------------------------------------

def test_smartshift_mapping_matches_pr_123_table():
    for ui, dev in ((1, 1), (25, 13), (50, 25), (75, 37), (100, 49)):
        assert bk.Backend._dev_threshold(ui) == dev


def test_smartshift_mapping_is_monotonic_and_stays_automatic():
    values = [bk.Backend._dev_threshold(ui) for ui in range(1, 101)]
    assert values == sorted(values)
    assert min(values) == 1 and max(values) == 49  # 0 = free-spin, 50+ = ratchet-only


def test_smartshift_readback_round_trips_every_device_value():
    for dev in range(1, 50):
        assert bk.Backend._dev_threshold(bk.Backend._ui_threshold(dev)) == dev


def test_smartshift_mapping_equals_the_gtk_app():
    gtk = _gtk_static(REPO_ROOT / "overlay" / "settings_page_scroll.py", "ScrollPage",
                      ["_smartshift_ui_to_device", "_smartshift_device_to_ui"])
    for ui in range(1, 101):
        assert bk.Backend._dev_threshold(ui) == gtk._smartshift_ui_to_device(ui)
    for dev in range(1, 50):
        assert bk.Backend._ui_threshold(dev) == gtk._smartshift_device_to_ui(dev)


# ---------------------------------------------------------------------------
# Actions Ring geometry (#134)
# ---------------------------------------------------------------------------

def test_ring_constants_match_the_overlay_and_gtk_clamps():
    import overlay_constants
    import re
    assert bk.RING_OUTER_DEFAULT == overlay_constants.MENU_RADIUS
    assert bk.RING_INNER_DEFAULT == overlay_constants.CENTER_ZONE_RADIUS
    src = (REPO_ROOT / "overlay" / "settings_config.py").read_text()
    gtk = {k: int(v) for k, v in re.findall(r"^(RING_\w+) = (\d+)", src, re.M)}
    assert (gtk["RING_OUTER_RADIUS_MIN"], gtk["RING_OUTER_RADIUS_MAX"]) == (bk.RING_OUTER_MIN, bk.RING_OUTER_MAX)
    assert (gtk["RING_INNER_RADIUS_MIN"], gtk["RING_INNER_RADIUS_MARGIN"]) == (bk.RING_INNER_MIN, bk.RING_INNER_MARGIN)


def test_ring_geometry_clamps_and_resets(backend, tmp_path):
    assert backend.ringGeometry()["custom"] is False
    backend.setRingOuter(999)
    assert _disk(tmp_path)["radial"]["outer_radius"] == bk.RING_OUTER_MAX
    backend.setRingInner(240)  # pulled under outer - margin
    assert _disk(tmp_path)["radial"]["inner_radius"] == bk.RING_OUTER_MAX - bk.RING_INNER_MARGIN
    backend.setRingOuter(100)  # shrinking the ring drags a too-large centre zone in
    assert _disk(tmp_path)["radial"]["inner_radius"] == 100 - bk.RING_INNER_MARGIN
    assert backend.ringGeometry()["custom"] is True
    backend.resetRingGeometry()
    radial = _disk(tmp_path)["radial"]
    assert radial["outer_radius"] is None and radial["inner_radius"] is None
    geo = backend.ringGeometry()
    assert (geo["outer"], geo["inner"], geo["custom"]) == (bk.RING_OUTER_DEFAULT, bk.RING_INNER_DEFAULT, False)


# ---------------------------------------------------------------------------
# Quick links live on the submenu slice (0.4.3, what the overlay reads)
# ---------------------------------------------------------------------------

def _submenu_slice(tmp_path):
    return next(s for s in _disk(tmp_path)["radial_menu"]["slices"] if s["type"] == "submenu")


def test_quick_links_are_written_to_the_submenu_slice(backend, tmp_path):
    backend.setAiLinks([
        {"name": "Docs", "url": "docs.example.com"},
        {"name": "Editor", "command": "code --new-window", "icon": "/tmp/code.png"},
    ])
    assert _submenu_slice(tmp_path)["submenu"] == [
        {"label": "Docs", "url": "https://docs.example.com"},
        {"label": "Editor", "type": "exec", "command": "code --new-window", "icon": "/tmp/code.png"},
    ]
    rows = backend.aiLinks()
    assert [(r["name"], r["url"], r["command"]) for r in rows] == [
        ("Docs", "https://docs.example.com", ""), ("Editor", "", "code --new-window")]


def test_quick_links_cap_at_four_like_the_overlay(backend, tmp_path):
    backend.setAiLinks([{"name": f"L{i}", "url": f"https://l{i}.example"} for i in range(6)])
    assert len(_submenu_slice(tmp_path)["submenu"]) == 4


def test_quick_links_migrate_from_the_old_ai_links_key(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    (tmp_path / "config.json").write_text(json.dumps({
        "radial_menu": {"ai_links": [{"name": "Kagi", "url": "https://kagi.com", "icon": "browser"}]}}))
    b = bk.Backend()
    assert [(r["name"], r["url"]) for r in b.aiLinks()] == [("Kagi", "https://kagi.com")]
    b.setAiLinks(b.aiLinks())
    assert _submenu_slice(tmp_path)["submenu"] == [{"label": "Kagi", "url": "https://kagi.com"}]
    assert "ai_links" not in _disk(tmp_path)["radial_menu"]


def test_empty_quick_links_show_the_ai_defaults(backend):
    names = [r["name"] for r in backend.aiLinks()]
    assert names == ["Claude", "ChatGPT", "Gemini", "Perplexity"]


# ---------------------------------------------------------------------------
# Pick application (#117)
# ---------------------------------------------------------------------------

def test_exec_field_codes_are_stripped_like_the_gtk_picker():
    cases = {"firefox %u": "firefox", "code --new-window %F": "code --new-window",
             "notify-send 100%% done": "notify-send 100% done", "  env FOO=1 app %i %c ": "env FOO=1 app"}
    for exec_line, want in cases.items():
        assert bk.Backend._command_for_exec(exec_line) == want


def test_set_app_points_a_slice_at_the_application(backend, tmp_path):
    backend.slices.setAction(6, "files")
    backend.slices.setApp(6, "firefox", "Firefox", "/tmp/firefox.png")
    s = _disk(tmp_path)["radial_menu"]["slices"][6]
    assert (s["type"], s["command"], s["icon"], s["label"]) == ("exec", "firefox", "/tmp/firefox.png", "Firefox")
    backend.slices.setLabel(6, "Browser")
    backend.slices.setApp(6, "chromium", "Chromium", "")
    s = _disk(tmp_path)["radial_menu"]["slices"][6]
    assert (s["label"], s["icon"]) == ("Browser", "/tmp/firefox.png")  # a custom label and icon stay


def test_cache_app_icon_writes_the_overlay_icon_cache(backend, tmp_path, monkeypatch):
    gi = pytest.importorskip("gi")
    from gi.repository import Gio
    icon_src = tmp_path / "src.png"
    from PyQt6.QtGui import QPixmap
    pm = QPixmap(8, 8)
    pm.fill()
    assert pm.save(str(icon_src), "PNG")
    desktop = tmp_path / "juhtest.desktop"
    desktop.write_text(f"[Desktop Entry]\nType=Application\nName=JuhTest\nExec=true\nIcon={icon_src}\n")
    app = Gio.DesktopAppInfo.new_from_filename(str(desktop))
    monkeypatch.setattr(Gio.DesktopAppInfo, "new", staticmethod(lambda _id: app))
    path = backend.cacheAppIcon("juhtest.desktop")
    assert path == str(tmp_path / "icons" / "juhtest.desktop.png")
    assert Path(path).is_file()


# ---------------------------------------------------------------------------
# Autostart entry (#129, #32)
# ---------------------------------------------------------------------------

def test_launcher_is_never_the_bare_daemon(monkeypatch):
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    launcher = bk.Backend._find_launcher()
    assert "juhradiald" not in launcher
    assert launcher.endswith("juhradial-mx.sh") or launcher == "juhradial-mx"


def test_start_at_login_writes_and_removes_the_entry(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(bk.Backend, "_find_launcher", classmethod(lambda cls: "/usr/local/bin/juhradial-mx"))
    backend.setStartAtLogin(True)
    text = bk.AUTOSTART.read_text()
    assert "Exec=/usr/local/bin/juhradial-mx" in text and "X-GNOME-Autostart-enabled=true" in text
    backend.setStartAtLogin(False)
    assert not bk.AUTOSTART.exists()
    assert _disk(tmp_path)["app"]["start_at_login"] is False


def test_stale_autostart_exec_is_repaired_at_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    autostart = tmp_path / "autostart" / "juhradial-mx.desktop"
    monkeypatch.setattr(bk, "AUTOSTART", autostart)
    launcher = tmp_path / "juhradial-mx"
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: str(launcher)))
    autostart.parent.mkdir(parents=True)
    autostart.write_text("[Desktop Entry]\nType=Application\nExec=/usr/bin/juhradial-mx\n")
    bk.Backend()
    assert f"Exec={launcher}" in autostart.read_text()


def test_missing_autostart_is_created_only_for_an_installed_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    autostart = tmp_path / "autostart" / "juhradial-mx.desktop"
    monkeypatch.setattr(bk, "AUTOSTART", autostart)
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    bk.Backend()
    assert not autostart.exists(), "a bare checkout must not make itself the login autostart"
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: "/usr/local/bin/juhradial-mx"))
    bk.Backend()
    assert "Exec=/usr/local/bin/juhradial-mx" in autostart.read_text()


def test_valid_autostart_entry_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    autostart = tmp_path / "autostart" / "juhradial-mx.desktop"
    monkeypatch.setattr(bk, "AUTOSTART", autostart)
    launcher = tmp_path / "mine"
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: str(launcher)))
    autostart.parent.mkdir(parents=True)
    original = f"[Desktop Entry]\nType=Application\nExec={launcher} --flag\n"
    autostart.write_text(original)
    bk.Backend()
    assert autostart.read_text() == original


# ---------------------------------------------------------------------------
# Connection link (0.4.4 Devices row)
# ---------------------------------------------------------------------------

def _hid(tmp_path, *names):
    root = tmp_path / "hid"
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        (root / n).mkdir()
    return str(root)


def test_connection_names_bolt_unifying_usb_and_bluetooth(tmp_path):
    detect = bk.Backend._detect_connection
    assert detect(hid_root=_hid(tmp_path, "0003:046D:C548.0007")) == "Bolt receiver"
    assert detect(hid_root=_hid(tmp_path / "u", "0003:046D:C52B.0002")) == "Unifying receiver"
    assert detect(hid_root=_hid(tmp_path / "p", "0003:046D:B034.0004")) == "USB receiver"
    assert detect(hid_root=_hid(tmp_path / "b", "0005:046D:B034.0009")) == "Bluetooth"
    assert detect(hid_root=_hid(tmp_path / "bb", "0003:046D:C548.0007", "0005:046D:B034.0009")) == "Bolt receiver + Bluetooth"
    assert detect(hid_root=_hid(tmp_path / "n", "0003:1532:0084.0001")) == "USB receiver"
    assert detect(hid_root=str(tmp_path / "missing")) == "USB receiver"


def test_generic_mice_only_tell_bluetooth_from_usb(tmp_path):
    detect = bk.Backend._detect_connection
    assert detect(generic=True, hid_root=_hid(tmp_path, "0005:1532:0084.0001")) == "Bluetooth"
    assert detect(generic=True, hid_root=_hid(tmp_path / "u", "0003:1532:0084.0001")) == "USB"


def test_device_name_refresh_updates_the_live_name(backend):
    seen = []
    backend.liveChanged.connect(lambda: seen.append(backend.deviceName))
    backend._set_device_name_live("MX Master 3S")
    assert backend.deviceName == "MX Master 3S" and seen
    backend._set_device_name_live("")
    assert backend.deviceName == "MX Master 3S"


# ---------------------------------------------------------------------------
# Defaults the installer relies on
# ---------------------------------------------------------------------------

def test_start_at_login_defaults_on_like_the_gtk_app_and_installer():
    assert bk.DEFAULT_CONFIG["app"]["start_at_login"] is True
    assert "ai_links" not in bk.DEFAULT_CONFIG["radial_menu"]
