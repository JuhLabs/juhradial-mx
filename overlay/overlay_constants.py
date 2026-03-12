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
    "SUBMENU_EXTEND", "WINDOW_SIZE",
    "IS_HYPRLAND", "IS_GNOME", "IS_COSMIC", "IS_KDE", "IS_SWAY", "IS_X11",
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

# =============================================================================
# DESKTOP ENVIRONMENT DETECTION FLAGS
# =============================================================================
IS_HYPRLAND = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") is not None
IS_GNOME = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
IS_COSMIC = "COSMIC" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
_desktop_upper = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
IS_KDE = "KDE" in _desktop_upper or "PLASMA" in _desktop_upper
IS_SWAY = os.environ.get("SWAYSOCK") is not None
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
