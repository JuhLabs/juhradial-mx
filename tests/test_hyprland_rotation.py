#!/usr/bin/env python3
"""Hyprland portrait-monitor menu drift (issue #78).

`hyprctl monitors -j` reports width/height as the PRE-rotation mode size, but
the layout `hyprctl cursorpos` lives in uses the transformed size. Without the
swap a 1920x1080 panel rotated to portrait produced a 1920x1080 logical rect
while Qt reported the same screen as 1080x1920, so the fraction mapping divided
the vertical position by 1080 instead of 1920 and the ring landed at the bottom
of the screen no matter where the cursor was.

Run: python3 -m pytest tests/test_hyprland_rotation.py -q
"""

import sys

# overlay_cursor uses flat imports (matching the installed layout), so put
# the overlay dir itself on the path.
sys.path.insert(0, "overlay")

import overlay_cursor
from overlay_constants import map_and_clamp_menu

get_monitor_at_cursor = overlay_cursor.get_monitor_at_cursor
hypr_logical_rect = overlay_cursor.hypr_logical_rect

# DP-1 landscape at the origin, DP-2 a 1920x1080 panel rotated 270 next to it.
LANDSCAPE = {"x": 0, "y": 0, "width": 2560, "height": 1440, "scale": 1.0,
             "transform": 0, "name": "DP-1"}
PORTRAIT = {"x": 2560, "y": 0, "width": 1920, "height": 1080, "scale": 1.0,
            "transform": 3, "name": "DP-2"}
QT_SCREENS = [
    {"x": 0, "y": 0, "width": 2560, "height": 1440, "name": "DP-1"},
    {"x": 2560, "y": 0, "width": 1080, "height": 1920, "name": "DP-2"},
]
WIN = 484  # half = 242


def test_rotated_monitor_rect_is_transposed():
    rect = hypr_logical_rect(PORTRAIT)
    assert (rect["width"], rect["height"]) == (1080, 1920)


def test_unrotated_monitor_rect_is_unchanged():
    rect = hypr_logical_rect(LANDSCAPE)
    assert (rect["width"], rect["height"]) == (2560, 1440)


def test_flipped_rotations_swap_too():
    # Hyprland transforms 1/3/5/7 are the 90/270 variants, flipped included.
    for transform in (1, 3, 5, 7):
        rect = hypr_logical_rect({**PORTRAIT, "transform": transform})
        assert (rect["width"], rect["height"]) == (1080, 1920), transform
    for transform in (0, 2, 4, 6):
        rect = hypr_logical_rect({**PORTRAIT, "transform": transform})
        assert (rect["width"], rect["height"]) == (1920, 1080), transform


def test_missing_transform_field_behaves_as_unrotated():
    bare = {k: v for k, v in PORTRAIT.items() if k != "transform"}
    assert hypr_logical_rect(bare)["width"] == 1920


def test_fractional_scale_still_truncates():
    # Issue #45 expectations depend on truncation, not rounding.
    scaled = {**LANDSCAPE, "scale": 1.5}
    assert hypr_logical_rect(scaled) == {
        "x": 0, "y": 0, "width": 1706, "height": 960, "name": "DP-1",
    }


def test_menu_lands_on_the_cursor_on_the_portrait_monitor():
    rects = [hypr_logical_rect(LANDSCAPE), hypr_logical_rect(PORTRAIT)]
    mon = rects[1]
    # Dead centre of the portrait screen: 2560 + 540, 1920 / 2.
    placement = map_and_clamp_menu(3100, 960, mon, rects, QT_SCREENS, WIN)
    assert placement["qt_center"] == (3100, 960)


def test_lower_half_of_the_portrait_monitor_is_not_clamped_to_the_bottom():
    rects = [hypr_logical_rect(LANDSCAPE), hypr_logical_rect(PORTRAIT)]
    mon = rects[1]
    placement = map_and_clamp_menu(3100, 1600, mon, rects, QT_SCREENS, WIN)
    assert placement["qt_center"] == (3100, 1600)


def test_the_last_column_of_a_fractionally_scaled_monitor_still_matches(monkeypatch):
    # 2560 / 1.5 = 1706.67 logical, so x=1706 is the last reachable column.
    # Rounding the rect before the containment test would drop it into the
    # neighbouring monitor and open the ring there (issue #8).
    monitors = [
        {"x": 0, "y": 0, "width": 2560, "height": 1440, "scale": 1.5,
         "transform": 0, "name": "DP-1", "focused": False},
        {"x": 1707, "y": 0, "width": 1920, "height": 1080, "scale": 1.0,
         "transform": 0, "name": "DP-2", "focused": True},
    ]
    monkeypatch.setattr(overlay_cursor, "_monitors_cache", monitors)
    assert get_monitor_at_cursor(1706, 500)["name"] == "DP-1"
    assert get_monitor_at_cursor(1707, 500)["name"] == "DP-2"
