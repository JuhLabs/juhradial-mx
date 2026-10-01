"""MX Keypad templates from a terminal (issue #168): pages and key images on
systems where the Qt Settings app cannot run, so without QML."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtDBus")
pytest.importorskip("PyQt6.QtSvg")

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "settings-qt" / "bridge" / "keypad_cli.py"
LAUNCHER = REPO / "scripts" / "juhradial-settings.sh"
TEMPLATES = ("everyday", "media", "developer", "meetings")
# Ubuntu 24.04 and Linux Mint 22 ship QtGui and QtSvg for PyQt6 but no QML:
# importing either module there fails, and so it does in this interpreter.
WITHOUT_QML = ("import runpy, sys; sys.modules['PyQt6.QtQml'] = None; sys.modules['PyQt6.QtQuick'] = None; "
               "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')")


def run(tmp_path, *args, command=None):
    # A private home and no session bus: the test must never reach the
    # daemon or the Settings window of the machine it runs on.
    env = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / "config"),
               DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent/juhradial-test-bus")
    command = command or [sys.executable, "-c", WITHOUT_QML, str(CLI)]
    return subprocess.run([*command, *args], env=env, capture_output=True, text=True, timeout=120)


def pages(tmp_path):
    config = tmp_path / "config" / "juhradial" / "config.json"
    return json.loads(config.read_text()).get("keypad", {}).get("pages", []) if config.exists() else []


def plates(tmp_path):
    return sorted((tmp_path / "config" / "juhradial" / "keypad" / "plates").glob("*.jpg"))


def test_a_template_becomes_a_page_with_its_key_images_without_qml(tmp_path):
    result = run(tmp_path, "everyday")
    assert result.returncode == 0, result.stderr
    (page,) = pages(tmp_path)
    assert len(page["keys"]) == 9 and page["name"]
    assert any(key["action"] != "none" for key in page["keys"]), "the template assigns keys"
    images = plates(tmp_path)
    assert [image.name for image in images] == [f"p0-k{key}.jpg" for key in range(1, 10)]
    for image in images:
        data = image.read_bytes()
        assert data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9") and len(data) < 65535


def test_a_second_run_does_not_add_the_page_again(tmp_path):
    assert run(tmp_path, "media").returncode == 0
    again = run(tmp_path, "MEDIA")
    assert again.returncode == 0, again.stderr
    assert len(pages(tmp_path)) == 1
    assert run(tmp_path, "developer").returncode == 0
    assert len(pages(tmp_path)) == 2 and len(plates(tmp_path)) == 18


def test_an_unknown_template_changes_nothing_and_names_the_real_ones(tmp_path):
    result = run(tmp_path, "gaming")
    assert result.returncode == 2
    assert all(name in result.stderr for name in TEMPLATES)
    assert pages(tmp_path) == [] and plates(tmp_path) == []


def test_without_a_name_the_templates_are_listed(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert all(name in result.stdout for name in TEMPLATES)
    assert pages(tmp_path) == [] and plates(tmp_path) == []


def test_the_launcher_runs_it_ahead_of_the_qt_version_check(tmp_path):
    # JUHRADIAL_SETTINGS=gtk is what an old Qt amounts to: the Qt app is skipped.
    command = ["env", "JUHRADIAL_SETTINGS=gtk", "bash", str(LAUNCHER), "--keypad-template"]
    result = run(tmp_path, command=command)
    assert result.returncode == 0, result.stderr
    assert all(name in result.stdout for name in TEMPLATES)
