"""Regression contracts for user-visible startup latency."""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_PATH = REPO_ROOT / "overlay" / "juhradial-overlay.py"


def _splash_min_display_ms() -> int:
    module = ast.parse(OVERLAY_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SplashScreen":
            continue
        for statement in node.body:
            if (
                isinstance(statement, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "MIN_DISPLAY_MS"
                    for target in statement.targets
                )
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, int)
            ):
                return statement.value.value
    raise AssertionError("SplashScreen.MIN_DISPLAY_MS must be an integer constant")


def test_splash_does_not_mask_a_ready_application_for_two_seconds():
    assert _splash_min_display_ms() <= 350
