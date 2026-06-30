"""
JuhRadial MX - Overlay Constants

Geometry constants, DE detection flags, and logging utility shared
across all overlay modules.

SPDX-License-Identifier: GPL-3.0
"""

import os
import time as _time_mod

__all__ = [
    "MENU_RADIUS", "SHADOW_OFFSET", "CENTER_ZONE_RADIUS", "ICON_ZONE_RADIUS",
    "SUBMENU_EXTEND", "WINDOW_SIZE", "compute_ring_scale", "map_logical_to_screen",
    "hyprland_menu_center",
    "IS_HYPRLAND", "IS_GNOME", "IS_COSMIC", "IS_KDE", "IS_SWAY", "IS_NIRI", "IS_X11",
    "_HAS_XWAYLAND",
    "_log",
]

# =============================================================================
# GEOMETRY
# =============================================================================
MENU_RADIUS = 150
SHADOW_OFFSET = 12
CENTER_ZONE_RADIUS = 45
ICON_ZONE_RADIUS = 100
SUBMENU_EXTEND = 80  # Extra space for submenu items beyond main menu
WINDOW_SIZE = (MENU_RADIUS + SHADOW_OFFSET + SUBMENU_EXTEND) * 2

# Ring scaling: the geometry above is the LOGICAL base (tuned at 1440p).
# The window is scaled per-monitor so the ring keeps the same apparent
# size on any resolution — painting applies the factor via QPainter.scale,
# hit-testing divides physical offsets back to logical space.
RING_SCALE_REFERENCE_HEIGHT = 1440
RING_SCALE_MIN = 0.8
RING_SCALE_MAX = 2.0


def compute_ring_scale(monitor_height):
    """Ring scale factor for a monitor of the given pixel height."""
    if not monitor_height:
        return 1.0
    scale = monitor_height / RING_SCALE_REFERENCE_HEIGHT
    return max(RING_SCALE_MIN, min(RING_SCALE_MAX, scale))


def map_logical_to_screen(lx, ly, mon, screen_geo):
    """Map a compositor-logical cursor coordinate into the matching Qt screen's
    coordinate space, by fractional position within the monitor.

    The cursor's fractional position within its monitor (e.g. 0.36 across, 0.39
    down) is invariant across coordinate spaces, so it can be transferred from
    the compositor-logical layout to Qt's own screen geometry without knowing the
    devicePixelRatio or how XWayland scales. This lands QWidget.move() on the
    cursor regardless of per-monitor scale, fractional scaling, or which layer
    (Qt vs XWayland) applies the scaling (issue #45). When the monitor and Qt
    screen geometries match (no scaling, e.g. 100%) it returns (lx, ly) unchanged.

    Args:
        lx, ly: cursor position in compositor-logical pixels (hyprctl cursorpos).
        mon: cursor's monitor as {x, y, width, height} in compositor-logical px.
        screen_geo: matching Qt screen as {x, y, width, height} in Qt point space
            (QScreen.geometry()).

    Returns:
        (cx, cy) menu-center in Qt point space, rounded to ints.
    """
    cx, cy = _map_fraction(lx, ly, mon, screen_geo)
    return (int(round(cx)), int(round(cy)))


def _map_fraction(x, y, src, dst):
    """Map (x, y) from rect ``src`` to rect ``dst`` by fractional position.

    The point's fraction within ``src`` is invariant across coordinate spaces,
    so this transfers it to ``dst`` without knowing any scale factor. Returns
    floats; callers round when they need ints.
    """
    sw = src.get("width") or 1
    sh = src.get("height") or 1
    fx = (x - src.get("x", 0)) / sw
    fy = (y - src.get("y", 0)) / sh
    return (dst.get("x", 0) + fx * (dst.get("width") or 1),
            dst.get("y", 0) + fy * (dst.get("height") or 1))


def _clamp_center(cx, cy, rect, half):
    """Clamp a window center so a ``half``-radius window stays inside ``rect``.

    All values share one coordinate space (``half`` matches ``rect``). If the
    window is larger than the rect (margins cross over), the rect is centred.
    """
    rx, ry = rect.get("x", 0), rect.get("y", 0)
    rw, rh = rect.get("width") or 1, rect.get("height") or 1
    min_x, max_x = rx + half, rx + rw - half
    min_y, max_y = ry + half, ry + rh - half
    cx = min(max(cx, min_x), max_x) if min_x <= max_x else rx + rw / 2
    cy = min(max(cy, min_y), max_y) if min_y <= max_y else ry + rh / 2
    return cx, cy


def _bounding_box(rects):
    """Union bounding box of a list of {x, y, width, height} rects."""
    x0 = min(r["x"] for r in rects)
    y0 = min(r["y"] for r in rects)
    x1 = max(r["x"] + r["width"] for r in rects)
    y1 = max(r["y"] + r["height"] for r in rects)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def hyprland_menu_center(lx, ly, cursor_mon, hypr_monitors, qt_screens):
    """Menu-center in Qt point space for a Hyprland compositor-logical cursor.

    Tiered so it is exact when it can be and still corrects the drift when it
    cannot, across any monitor count / scale mix (issue #45). Each tier reduces
    to identity at 100% scaling, so single-scale setups are never regressed.

    1. Per-monitor: map the cursor's fraction within its monitor onto the Qt
       screen with the same connector name. Exact whether Qt or XWayland applies
       the scaling, because that screen's geometry is already in move() space.
    2. Global affine: if no Qt screen name matches (XWayland sometimes exposes
       generic output names), map the cursor's fraction across the whole logical
       desktop onto the whole Qt desktop. Name-agnostic and exact under
       XWayland's single global-scale model.
    3. Identity: if Qt screen geometry is unavailable, pass the coordinate
       through unchanged (current behaviour).

    Args:
        lx, ly: cursor in compositor-logical pixels.
        cursor_mon: cursor's monitor {x, y, width, height, name} (logical px).
        hypr_monitors: all monitors as logical {x, y, width, height, name}.
        qt_screens: all Qt screens as {x, y, width, height, name} (point space).
    """
    if cursor_mon and qt_screens:
        name = cursor_mon.get("name")
        for screen in qt_screens:
            if name and screen.get("name") == name:
                return map_logical_to_screen(lx, ly, cursor_mon, screen)

    if hypr_monitors and qt_screens:
        return map_logical_to_screen(
            lx, ly, _bounding_box(hypr_monitors), _bounding_box(qt_screens)
        )

    return (int(round(lx)), int(round(ly)))


def _select_screens(cursor_mon, hypr_monitors, qt_screens):
    """Return the (logical_rect, qt_rect) pair to map between, mirroring the
    tiers of hyprland_menu_center. Returns (None, None) for identity passthrough
    (no Qt screen info), where logical space already equals move() space.
    """
    if cursor_mon and qt_screens:
        name = cursor_mon.get("name")
        for screen in qt_screens:
            if name and screen.get("name") == name:
                return cursor_mon, screen
    if hypr_monitors and qt_screens:
        return _bounding_box(hypr_monitors), _bounding_box(qt_screens)
    return None, None


def map_and_clamp_menu(lx, ly, cursor_mon, hypr_monitors, qt_screens, window_size):
    """Place the menu for a Hyprland logical cursor and clamp it on-screen.

    Maps the cursor into Qt space (so QWidget.move() lands on the cursor under
    mixed/fractional scaling, issue #45) and then clamps the window in Qt space
    using the Qt-space half-window. Clamping must happen AFTER the mapping:
    clamping in logical space with a Qt-space margin leaves a residual corner
    overflow when the logical and Qt monitor geometries differ by a per-monitor
    scale. The logical center is back-derived from the clamped Qt center so hover
    hit-testing (which polls the logical cursor) stays aligned with the visible
    ring.

    Returns a dict:
        qt_center      (cx, cy) menu center in Qt point space
        qt_origin      (x, y) top-left for QWidget.move()
        logical_center (cx, cy) menu center in compositor-logical space
    """
    half = window_size // 2
    logical_rect, qt_rect = _select_screens(cursor_mon, hypr_monitors, qt_screens)

    if qt_rect is None:
        # Identity passthrough: no Qt geometry, so logical == move() space.
        qx, qy = (lx, ly)
        if cursor_mon:
            qx, qy = _clamp_center(lx, ly, cursor_mon, half)
        qx, qy = int(round(qx)), int(round(qy))
        return {
            "qt_center": (qx, qy),
            "qt_origin": (qx - half, qy - half),
            "logical_center": (qx, qy),
        }

    qx, qy = _map_fraction(lx, ly, logical_rect, qt_rect)
    qx, qy = _clamp_center(qx, qy, qt_rect, half)
    lcx, lcy = _map_fraction(qx, qy, qt_rect, logical_rect)

    qx, qy = int(round(qx)), int(round(qy))
    return {
        "qt_center": (qx, qy),
        "qt_origin": (qx - half, qy - half),
        "logical_center": (int(round(lcx)), int(round(lcy))),
    }

# =============================================================================
# DESKTOP ENVIRONMENT DETECTION FLAGS
# =============================================================================
IS_HYPRLAND = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") is not None
IS_GNOME = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
IS_COSMIC = "COSMIC" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
_desktop_upper = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
IS_KDE = "KDE" in _desktop_upper or "PLASMA" in _desktop_upper
IS_SWAY = os.environ.get("SWAYSOCK") is not None
# niri exposes NIRI_SOCKET; it has no cursor IPC and tiles XWayland toplevels,
# so the menu uses the raw override-redirect XWayland sync path (like COSMIC).
IS_NIRI = os.environ.get("NIRI_SOCKET") is not None
IS_X11 = os.environ.get("XDG_SESSION_TYPE", "").lower() == "x11"
_HAS_XWAYLAND = os.environ.get("DISPLAY") is not None


# =============================================================================
# LOGGING
# =============================================================================
_LOG_DIR = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_CACHE_HOME") or "/tmp"
_LOG_PATH = os.path.join(_LOG_DIR, "juhradial-overlay.log")


def _log(msg):
    """Write debug message to log file (stdout may be /dev/null)."""
    try:
        with open(_LOG_PATH, "a") as f:
            f.write(f"[{_time_mod.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        return  # Cannot log — filesystem issue, silently skip
