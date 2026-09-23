"""Regression contracts for user-visible startup latency.

The overlay used to open a branded splash on every launch that stayed up for a
minimum display time and then waited for the daemon; 0.4.5 removed it (the
tray icon is the only startup feedback). Guard against a splash, or any other
minimum-display wait, coming back.
"""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_PATH = REPO_ROOT / "overlay" / "juhradial-overlay.py"


def _overlay_module():
    return ast.parse(OVERLAY_PATH.read_text(encoding="utf-8"))


def test_overlay_has_no_startup_splash():
    classes = {node.name for node in _overlay_module().body if isinstance(node, ast.ClassDef)}
    assert "SplashScreen" not in classes, "the startup splash was removed in 0.4.5; do not bring it back"


def test_overlay_has_no_minimum_display_wait():
    source = OVERLAY_PATH.read_text(encoding="utf-8")
    assert "MIN_DISPLAY_MS" not in source
    assert "Waiting for daemon" not in source
