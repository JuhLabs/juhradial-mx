#!/usr/bin/env python3
"""
JuhRadial MX - Theme System

Theme loading and CSS generation for the settings dashboard.
Supports dark and light themes with dynamic accent colors.

SPDX-License-Identifier: GPL-3.0
"""

from themes import get_colors, is_dark_theme
from settings_css import generate_css as _generate_css


# =============================================================================
# THEME LOADING
# =============================================================================
def load_colors():
    """Load colors from the current theme with glow color computed"""
    colors = get_colors().copy()
    # Add computed glow color based on accent
    accent = colors.get('accent', '#00d4ff')
    # Parse hex to RGB for glow
    r = int(accent[1:3], 16)
    g = int(accent[3:5], 16)
    b = int(accent[5:7], 16)
    colors['accent_glow'] = f'rgba({r}, {g}, {b}, 0.4)'
    colors['accent_glow_light'] = f'rgba({r}, {g}, {b}, 0.15)'
    # Add missing legacy colors if needed
    colors.setdefault('maroon', '#ff8a80')
    colors.setdefault('flamingo', '#f8bbd9')
    colors.setdefault('rosewater', '#fce4ec')
    # Add is_dark flag for CSS generation
    colors['is_dark'] = is_dark_theme()
    return colors

# Load initial colors
COLORS = load_colors()

# =============================================================================
# WINDOW CONFIGURATION
# =============================================================================
WINDOW_WIDTH = 1400   # Fallback if screen detection fails
WINDOW_HEIGHT = 950   # Fallback if screen detection fails
WINDOW_MIN_WIDTH = 400  # Can be narrow - content scrolls horizontally
WINDOW_MIN_HEIGHT = 300

# Generate CSS at module load time
CSS = _generate_css(COLORS)
