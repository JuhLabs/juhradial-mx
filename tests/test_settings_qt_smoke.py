"""Smoke tests for the Qt/QML settings app (settings-qt/).

Runs the app's own offscreen checks: every QML page compiles against the real
Theme/Backend context, and the config backend round-trips through a temp
config. Skipped where PyQt6's QML module is missing; the QML compile is also
skipped on Qt < 6.5 (no QtQuick.Effects), which is exactly when the launcher
falls back to the GTK settings app.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QT_DIR = ROOT / "settings-qt"

pytest.importorskip("PyQt6.QtQml")


def _run_tool(name):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run(
        [sys.executable, str(QT_DIR / "tools" / name)],
        capture_output=True,
        text=True,
        env=env,
        timeout=240,
    )


def test_every_qml_page_compiles():
    result = _run_tool("qml_check.py")
    output = result.stdout + result.stderr
    if result.returncode != 0 and "QtQuick.Effects" in output:
        pytest.skip("QtQuick.Effects (Qt >= 6.5) is not installed")
    assert result.returncode == 0, output
    assert "ALL OK" in result.stdout, output


def test_backend_config_round_trip():
    result = _run_tool("backend_test.py")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ALL PASS" in result.stdout, output
    assert "[FAIL]" not in result.stdout, output


def test_theme_assets_are_shipped():
    sys.path.insert(0, str(QT_DIR))
    from bridge.theme import THEMES, WHEELS  # noqa: E402

    wallpapers = QT_DIR / "assets" / "wallpapers"
    wheels = QT_DIR / "assets" / "wheels"
    missing = [key for (_n, key, _a, _h, _ac) in THEMES if not (wallpapers / f"wp_{key}.jpg").exists()]
    assert not missing, f"themes without a wallpaper: {missing}"
    missing_wheels = [key for (_n, key) in WHEELS if not (wheels / f"wheel_{key}.png").exists()]
    assert not missing_wheels, f"wheels without an image: {missing_wheels}"


def test_shipped_tree_stays_small():
    # The original design tree was 142 MB of PNG masters; only the compressed
    # runtime assets belong in the repo (wallpapers as JPEG, tiles at 256 px,
    # wheels at 512 px). Keep the whole app under 20 MB.
    total = sum(p.stat().st_size for p in QT_DIR.rglob("*") if p.is_file() and ".venv" not in p.parts)
    assert total < 20 * 1024 * 1024, f"settings-qt is {total / 1048576:.1f} MB"
