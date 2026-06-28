#!/usr/bin/env python3
"""Regression tests for radial-menu placement under HiDPI / fractional scaling.

Covers issue #45 (Hyprland mixed-scale dual monitor: menu drifts further from
the cursor the further it is from the top-left) and guards against regressing
issue #25 (KDE Plasma Wayland / 100%, where identity placement is correct).

Root cause: hyprctl cursorpos is in compositor-logical pixels, while
QWidget.move() places windows in Qt's own coordinate space. With mixed/fractional
scaling those spaces differ (Qt may apply a devicePixelRatio, or XWayland scales
the surface), so passing logical coords straight to move() drifts the menu
proportionally to distance from the origin.

Fix: map the cursor's fractional position within its monitor onto the matching Qt
screen's geometry. That fraction is invariant across coordinate spaces, so the
menu lands on the cursor regardless of scale or which layer applies it.
"""

import sys

sys.path.insert(0, ".")

from overlay.overlay_constants import map_logical_to_screen, hyprland_menu_center


def _geo(x, y, w, h, name=None):
    r = {"x": x, "y": y, "width": w, "height": h}
    if name is not None:
        r["name"] = name
    return r


def test_identity_when_geometries_match():
    # No scaling (100%, e.g. KDE Plasma Wayland per issue #25): the monitor's
    # logical geometry equals Qt's screen geometry, so mapping is a no-op.
    mon = {"x": 0, "y": 0, "width": 2560, "height": 1440, "name": "DP-1"}
    geo = _geo(0, 0, 2560, 1440)
    for lx, ly in [(0, 0), (930, 562), (1280, 720), (2559, 1439)]:
        assert map_logical_to_screen(lx, ly, mon, geo) == (lx, ly)


def test_issue45_primary_monitor_scaled_qt_space():
    # Issue #45: cursor at logical (930, 562) on HDMI-A-1 (logical 2560x1440),
    # but Qt reports that screen 1.6x smaller in its own space (2560/1.6=1600,
    # 1440/1.6=900). The menu center must follow the cursor's fraction onto Qt's
    # geometry, not sit at the raw logical coordinate.
    mon = {"x": 0, "y": 0, "width": 2560, "height": 1440, "name": "HDMI-A-1"}
    geo = _geo(0, 0, 1600, 900)
    cx, cy = map_logical_to_screen(930, 562, mon, geo)
    assert cx == round(930 / 2560 * 1600)  # 581
    assert cy == round(562 / 1440 * 900)   # 351


def test_second_monitor_offset_and_scaled():
    # eDP-2 sits to the right (logical 2560x1600 at scale 1.6 -> logical
    # 1600x1000 at logical origin 2560,0). Qt may place it at a different origin
    # and size in its own space; the fraction still maps correctly.
    mon = {"x": 2560, "y": 0, "width": 1600, "height": 1000, "name": "eDP-2"}
    geo = _geo(1600, 0, 1600, 1000)  # Qt origin differs from logical origin
    # cursor at the monitor's own centre -> Qt-space centre of that screen
    cx, cy = map_logical_to_screen(2560 + 800, 500, mon, geo)
    assert cx == 1600 + 800
    assert cy == 500


def test_corners_map_to_corners():
    mon = {"x": 0, "y": 0, "width": 2000, "height": 1000, "name": "X"}
    geo = _geo(100, 50, 1000, 500)
    assert map_logical_to_screen(0, 0, mon, geo) == (100, 50)
    assert map_logical_to_screen(2000, 1000, mon, geo) == (1100, 550)


def test_fraction_invariant_round_trip():
    # The core guarantee: whatever Qt-space geometry a monitor has, the cursor's
    # logical fraction maps to the same fraction of the Qt screen. Verified across
    # a spread of positions and arbitrary Qt scale ratios so the fix holds for any
    # monitor count / scale combination (1..N screens).
    mon = {"x": 1000, "y": 200, "width": 3840, "height": 2160, "name": "M"}
    for ratio in (1.0, 1.25, 1.5, 1.6, 2.0, 2.5):
        geo = _geo(0, 0, round(3840 / ratio), round(2160 / ratio))
        for fxi in range(0, 11):
            for fyi in range(0, 11):
                fx, fy = fxi / 10, fyi / 10
                lx = mon["x"] + fx * mon["width"]
                ly = mon["y"] + fy * mon["height"]
                cx, cy = map_logical_to_screen(lx, ly, mon, geo)
                # recovered fraction within the Qt screen matches the logical one
                rfx = (cx - geo["x"]) / geo["width"]
                rfy = (cy - geo["y"]) / geo["height"]
                assert abs(rfx - fx) < 0.01, f"ratio={ratio} fx={fx} rfx={rfx}"
                assert abs(rfy - fy) < 0.01, f"ratio={ratio} fy={fy} rfy={rfy}"


def test_degenerate_monitor_size_does_not_crash():
    # Defensive: a zero-sized monitor must not raise ZeroDivisionError.
    mon = {"x": 0, "y": 0, "width": 0, "height": 0, "name": "bad"}
    geo = _geo(0, 0, 1920, 1080)
    cx, cy = map_logical_to_screen(0, 0, mon, geo)
    assert isinstance(cx, int) and isinstance(cy, int)


# --- tiered orchestrator: hyprland_menu_center -----------------------------

# Issue #45 exact scenario: HDMI-A-1 scale 1.0 (logical 2560x1440) at 0,0 and
# eDP-2 scale 1.6 (logical 1600x1000) at 2560,0. Qt reports both screens 1.6x
# smaller in its own space (the overshoot factor seen in the report).
HYPR_MONS_45 = [
    {"x": 0, "y": 0, "width": 2560, "height": 1440, "name": "HDMI-A-1"},
    {"x": 2560, "y": 0, "width": 1600, "height": 1000, "name": "eDP-2"},
]
QT_SCREENS_45 = [
    _geo(0, 0, 1600, 900, "HDMI-A-1"),
    _geo(1600, 0, 1000, 625, "eDP-2"),
]


def test_orchestrator_name_match_issue45():
    # Cursor at logical (930, 562) on HDMI-A-1 -> mapped onto Qt's HDMI geometry.
    cursor_mon = HYPR_MONS_45[0]
    cx, cy = hyprland_menu_center(930, 562, cursor_mon, HYPR_MONS_45, QT_SCREENS_45)
    assert (cx, cy) == (round(930 / 2560 * 1600), round(562 / 1440 * 900))  # (581, 351)


def test_orchestrator_name_match_second_monitor():
    # Cursor on the fractional-scaled laptop screen maps onto its Qt geometry.
    cursor_mon = HYPR_MONS_45[1]
    lx, ly = 2560 + 800, 500  # centre of eDP-2 in logical space
    cx, cy = hyprland_menu_center(lx, ly, cursor_mon, HYPR_MONS_45, QT_SCREENS_45)
    # centre of eDP-2's Qt geometry (1600 + 1000/2, 625/2)
    assert (cx, cy) == (1600 + 500, round(625 / 2))


def test_orchestrator_falls_back_to_global_affine_when_names_differ():
    # XWayland may expose generic output names. With no name match, the global
    # affine over the desktop bounding box still removes the drift.
    qt_generic = [
        _geo(0, 0, 1600, 900, "XWAYLAND0"),
        _geo(1600, 0, 1000, 625, "XWAYLAND1"),
    ]
    cursor_mon = HYPR_MONS_45[0]
    cx, cy = hyprland_menu_center(930, 562, cursor_mon, HYPR_MONS_45, qt_generic)
    # logical desktop bbox: 0..4160 x 0..1440 ; qt bbox: 0..2600 x 0..900
    assert cx == round(930 / 4160 * 2600)
    assert cy == round(562 / 1440 * 900)


def test_orchestrator_identity_single_scale():
    # Single monitor at 100%: Qt geometry equals logical, mapping is a no-op.
    mons = [{"x": 0, "y": 0, "width": 2560, "height": 1440, "name": "DP-1"}]
    qt = [_geo(0, 0, 2560, 1440, "DP-1")]
    for lx, ly in [(0, 0), (930, 562), (2559, 1439)]:
        assert hyprland_menu_center(lx, ly, mons[0], mons, qt) == (lx, ly)


def test_orchestrator_identity_when_no_qt_screens():
    # No Qt screen info -> pass through unchanged (current behaviour preserved).
    mon = {"x": 0, "y": 0, "width": 2560, "height": 1440, "name": "DP-1"}
    assert hyprland_menu_center(930, 562, mon, [mon], []) == (930, 562)


def test_orchestrator_five_monitors_name_match():
    # Five monitors in a row, each mapped onto its own Qt geometry. Confirms the
    # fix scales to many displays.
    mons, qts = [], []
    lx0 = 0
    qx0 = 0
    for i in range(5):
        w = 1920
        mons.append({"x": lx0, "y": 0, "width": w, "height": 1080, "name": f"DP-{i}"})
        qts.append(_geo(qx0, 0, w // 2, 540, f"DP-{i}"))  # Qt 2x smaller
        lx0 += w
        qx0 += w // 2
    # cursor near right edge of the 4th monitor (index 3)
    lx = mons[3]["x"] + 1900
    cx, cy = hyprland_menu_center(lx, 500, mons[3], mons, qts)
    assert cx == qts[3]["x"] + round(1900 / 1920 * 960)
    assert cy == round(500 / 1080 * 540)


if __name__ == "__main__":
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failures else 0)
