"""Ring geometry invariants: what is drawn must be where it is hit-tested.

Guards the two regressions from #147 (paint centre vs hit origin under a
per-monitor ring_scale; submenu fan spread shared by painter and hit-test) and
the #134 follow-up (icons, submenu items and the centre label follow the
configured ring size, with hit radii scaling alongside the drawn radii).
"""

import ast
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_DIR = ROOT / "overlay"
OVERLAY_PATH = OVERLAY_DIR / "juhradial-overlay.py"
PAINTING_PATH = OVERLAY_DIR / "overlay_painting.py"

if str(OVERLAY_DIR) not in sys.path:
    sys.path.insert(0, str(OVERLAY_DIR))

from overlay_constants import MENU_RADIUS, ICON_ZONE_RADIUS, SUBMENU_EXTEND, SHADOW_OFFSET  # noqa: E402
import overlay_actions  # noqa: E402


def _class_method(path, class_name, method_name, namespace):
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef) and statement.name == method_name:
                    exec(
                        compile(ast.Module(body=[statement], type_ignores=[]), f"<{class_name}.{method_name}>", "exec"),
                        namespace,
                    )
                    return namespace[method_name]
    raise AssertionError(f"{class_name}.{method_name} not found in {path.name}")


def _mixin(params):
    """Painting-mixin helpers bound to a stub, with RADIAL_PARAMS = params."""
    namespace = {"overlay_actions": SimpleNamespace(RADIAL_PARAMS=params), "math": math}
    stub = SimpleNamespace()
    for name in ("_get_ui_scale", "_subitem_paint_radius", "_subitem_hit_radius", "_paint_origin"):
        fn = _class_method(PAINTING_PATH, "RadialMenuPaintingMixin", name, namespace)
        setattr(stub, name, fn.__get__(stub))
    return stub


@pytest.mark.parametrize("ring_scale", [1.0, 1.2, 1.5, 2.0])
@pytest.mark.parametrize("half_base", [242, 300, 363])
def test_paint_origin_lands_on_hit_test_origin(ring_scale, half_base):
    # _get_win_px() always returns an even device-pixel size.
    stub = _mixin({})
    stub.win_px = int(round(half_base * ring_scale)) * 2
    stub.ring_scale = ring_scale
    cx, cy = stub._paint_origin()
    # The painter is scaled by ring_scale, so the drawn centre in device px is
    # cx * ring_scale; hit-testing measures from win_px / 2 (#147, fix 1).
    assert cx == cy
    assert cx * ring_scale == pytest.approx(stub.win_px / 2)


def test_submenu_spread_is_shared_by_painter_and_hit_test():
    for path in (OVERLAY_PATH, PAINTING_PATH):
        src = path.read_text(encoding="utf-8")
        assert "spread = SUBMENU_ITEM_SPREAD_DEG" in src, f"{path.name} does not use the shared spread"
        assert re.search(r"^\s*spread = \d", src, re.M) is None, f"{path.name} hardcodes a spread"


@pytest.mark.parametrize("ui_scale", [0.8, 1.0, 1.25, 1.5, 2.0])
def test_submenu_hit_radius_covers_drawn_radius_at_every_ring_size(ui_scale):
    stub = _mixin({"ui_scale": ui_scale})
    assert stub._get_ui_scale() == ui_scale
    assert stub._subitem_paint_radius() == pytest.approx(24 * ui_scale)
    assert stub._subitem_hit_radius() == pytest.approx(32 * ui_scale)
    assert stub._subitem_hit_radius() >= stub._subitem_paint_radius()


def test_default_ring_has_unit_ui_scale():
    stub = _mixin(None)
    assert stub._get_ui_scale() == 1.0
    assert stub._subitem_paint_radius() == 24
    assert stub._subitem_hit_radius() == 32


def test_hit_test_and_painter_read_the_same_subitem_helpers():
    overlay_src = OVERLAY_PATH.read_text(encoding="utf-8")
    painting_src = PAINTING_PATH.read_text(encoding="utf-8")
    assert "SUBITEM_SIZE = self._subitem_hit_radius()" in overlay_src
    assert "SUBITEM_RADIUS = self._subitem_paint_radius()" in painting_src
    assert re.search(r"^\s*SUBITEM_(SIZE|RADIUS) = \d", overlay_src + painting_src, re.M) is None


def test_apply_ring_geometry_scales_pixel_sizes_with_the_ring():
    theme = {"icon_scale": 1.1, "center_font_size": 12, "image_size": 300}
    outer = MENU_RADIUS * 1.5
    params = overlay_actions.apply_ring_geometry(theme, outer, None)
    assert params is not theme, "must not mutate the theme's own params"
    assert params["ring_outer"] == outer
    assert params["ui_scale"] == pytest.approx(1.5)
    assert params["icon_radius"] == pytest.approx(ICON_ZONE_RADIUS * 1.5)
    assert params["shadow_offset"] == pytest.approx(SHADOW_OFFSET * 1.5)
    assert params["submenu_extend"] == pytest.approx(SUBMENU_EXTEND * 1.5)
    assert params["image_size"] == 450
    assert params["icon_scale"] == pytest.approx(1.1 * 1.5)
    assert params["center_font_size"] == pytest.approx(18)
    assert params["center_min_font_size"] == pytest.approx(7 * 1.5)
    assert "center_radius" not in params, "inner radius untouched when not configured"


def test_apply_ring_geometry_inner_only_and_unset():
    theme = {"icon_scale": 1.0}
    assert overlay_actions.apply_ring_geometry(theme, None, None) is theme
    params = overlay_actions.apply_ring_geometry(theme, None, 60)
    assert params["ring_inner"] == 60 and params["center_radius"] == 60
    assert "ui_scale" not in params and params["icon_scale"] == 1.0


def test_apply_ring_geometry_default_ring_is_identity_scale():
    params = overlay_actions.apply_ring_geometry(None, MENU_RADIUS, None)
    assert params["ui_scale"] == 1.0
    assert params["icon_scale"] == 1.0
    assert params["center_font_size"] == 11
    assert params["icon_radius"] == ICON_ZONE_RADIUS
