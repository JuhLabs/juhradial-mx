#!/usr/bin/env python3
"""The settings app's image://icon provider honours the icon style segment.

"classic" must resolve the 0.4.4 PNG masters before the SVG family of the
same name (the directory order is the precedence), "line" never touches the
classic sets, and unknown names still fall through to the theme lookup.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_icon_provider_styles.py -q
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtQuick")

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_QT = REPO_ROOT / "settings-qt"

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None


@pytest.fixture(scope="module")
def settings_main():
    sys.path.insert(0, os.fspath(SETTINGS_QT))
    spec = importlib.util.spec_from_file_location("settings_qt_main", SETTINGS_QT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider(settings_main, monkeypatch):
    calls = []
    original = settings_main.IconProvider._render_svg

    def recording(path, w, h):
        calls.append(Path(path))
        return original(path, w, h)

    monkeypatch.setattr(settings_main.IconProvider, "_render_svg", staticmethod(recording))
    return settings_main.IconProvider(), calls


def test_classic_uses_the_png_master_when_one_exists(provider, settings_main):
    icon_provider, svg_calls = provider
    name = "folder-symbolic"
    assert (settings_main.CLASSIC_DIRS[0] / f"{name}.png").exists()
    assert (settings_main.MONO_DIR / f"{name}.svg").exists()
    pm = icon_provider._base(name, 24, 24, "classic")
    assert not pm.isNull()
    assert svg_calls == [], "classic style rendered the SVG family instead of its PNG master"


def test_classic_falls_back_to_the_svg_family(provider, settings_main):
    icon_provider, svg_calls = provider
    name = "heart-symbolic"
    assert not (settings_main.CLASSIC_DIRS[0] / f"{name}.png").exists()
    assert (settings_main.MONO_DIR / f"{name}.svg").exists()
    pm = icon_provider._base(name, 24, 24, "classic")
    assert not pm.isNull()
    assert svg_calls == [settings_main.MONO_DIR / f"{name}.svg"]


def test_line_renders_the_svg_family(provider, settings_main):
    icon_provider, svg_calls = provider
    pm = icon_provider._base("folder-symbolic", 24, 24, "line")
    assert not pm.isNull()
    assert svg_calls == [settings_main.MONO_DIR / "folder-symbolic.svg"]


def test_request_parses_tint_and_style(provider):
    icon_provider, svg_calls = provider
    from PyQt6.QtCore import QSize
    pm, size = icon_provider.requestPixmap("FF0000/classic/folder-symbolic", QSize(20, 20))
    assert size.width() == 20 and size.height() == 20
    assert svg_calls == []
