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
    "IS_HYPRLAND", "IS_GNOME", "IS_COSMIC", "_HAS_XWAYLAND",
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
_HAS_XWAYLAND = os.environ.get("DISPLAY") is not None


# =============================================================================
# LOGGING
# =============================================================================
def _log(msg):
    """Write debug message to log file (stdout may be /dev/null)."""
    try:
        with open("/tmp/juhradial-overlay.log", "a") as f:
            f.write(f"[{_time_mod.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        return  # Cannot log — filesystem issue, silently skip
