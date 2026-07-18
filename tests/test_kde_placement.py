#!/usr/bin/env python3
"""KDE Wayland second-monitor drift regression (KWin-logical vs Qt space).

Real reported layout: DP-2 4K @125% (logical 3072x1728 at 0,0; Qt rect
identical) + DP-1 1080p @100% (logical 1920x1080 at 3072,648; Qt rect
1920x1080 at 3840,810 - same size, SHIFTED ORIGIN). Raw passthrough of the
KWin-logical cursor put the menu 768px left / 162px up on DP-1 while DP-2
looked perfect. The fix maps by fractional position per connector name
through the wheel-math core, which reduces to identity on DP-2.

Run: python3 -m pytest tests/test_kde_placement.py -q
"""

import json
import sys

# overlay_cursor uses flat imports (matching the installed layout), so put
# the overlay dir itself on the path.
sys.path.insert(0, "overlay")

from overlay_constants import map_and_clamp_menu
from overlay_cursor import _parse_kscreen_json, find_monitor_at

KDE_LOGICAL = [
    {"x": 0, "y": 0, "width": 3072, "height": 1728, "name": "DP-2"},
    {"x": 3072, "y": 648, "width": 1920, "height": 1080, "name": "DP-1"},
]
QT_SCREENS = [
    {"x": 0, "y": 0, "width": 3072, "height": 1728, "name": "DP-2"},
    {"x": 3840, "y": 810, "width": 1920, "height": 1080, "name": "DP-1"},
]
WIN = 484  # half = 242


def test_main_monitor_identity():
    # DP-2 logical rect == Qt rect -> mapping must be exact identity.
    mon = find_monitor_at(616, 984, KDE_LOGICAL)
    assert mon["name"] == "DP-2"
    p = map_and_clamp_menu(616, 984, mon, KDE_LOGICAL, QT_SCREENS, WIN)
    assert p["qt_center"] == (616, 984)


def test_second_monitor_origin_shift_corrected():
    # Cursor from the real drift report log: (4800, 1426) on DP-1.
    # Fraction in logical DP-1: (0.9, 778/1080). Same fraction in Qt DP-1
    # = (5568, 1588); x clamps to 3840+1920-242 = 5518.
    mon = find_monitor_at(4800, 1426, KDE_LOGICAL)
    assert mon["name"] == "DP-1"
    p = map_and_clamp_menu(4800, 1426, mon, KDE_LOGICAL, QT_SCREENS, WIN)
    assert p["qt_center"] == (5518, 1588)
    ox, oy = p["qt_origin"]
    assert 3840 <= ox and ox + WIN <= 3840 + 1920
    assert 810 <= oy and oy + WIN <= 810 + 1080


def test_second_monitor_center_no_clamp():
    # Dead centre of DP-1 logically -> dead centre of DP-1's Qt rect.
    p = map_and_clamp_menu(3072 + 960, 648 + 540,
                           KDE_LOGICAL[1], KDE_LOGICAL, QT_SCREENS, WIN)
    assert p["qt_center"] == (3840 + 960, 810 + 540)


def _kscreen_doc(outputs):
    return json.dumps({"outputs": outputs}) + "\ntrailing non-json noise"


def test_parse_kscreen_json_scale_and_rotation():
    doc = _kscreen_doc([
        {
            "name": "DP-2", "enabled": True, "pos": {"x": 0, "y": 0},
            "scale": 1.25, "rotation": 1, "currentModeId": "10",
            "modes": [{"id": "10", "size": {"width": 3840, "height": 2160}}],
        },
        {
            # Portrait: rotation 2 (90 degrees) swaps width/height.
            "name": "DP-1", "enabled": True, "pos": {"x": 3072, "y": 0},
            "scale": 1.0, "rotation": 2, "currentModeId": "2",
            "modes": [{"id": "2", "size": {"width": 1920, "height": 1080}}],
        },
        {"name": "DP-3", "enabled": False, "pos": {"x": 0, "y": 0}},
    ])
    rects = _parse_kscreen_json(doc)
    assert rects == [
        {"x": 0, "y": 0, "width": 3072, "height": 1728, "name": "DP-2"},
        {"x": 3072, "y": 0, "width": 1080, "height": 1920, "name": "DP-1"},
    ]


def test_find_monitor_at_boundaries():
    assert find_monitor_at(3071, 1000, KDE_LOGICAL)["name"] == "DP-2"
    assert find_monitor_at(3072, 1000, KDE_LOGICAL)["name"] == "DP-1"
    assert find_monitor_at(9999, 9999, KDE_LOGICAL) is None


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
                fails += 1
    sys.exit(1 if fails else 0)
