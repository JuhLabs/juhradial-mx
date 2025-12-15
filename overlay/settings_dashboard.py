#!/usr/bin/env python3
"""
JuhRadial MX - Logi Options+ Style Settings Dashboard

A beautiful settings window inspired by Logitech Options+ with:
- Catppuccin Mocha dark theme
- Sidebar navigation (Buttons, Scroll, Haptics, Settings)
- Interactive mouse visualization with hover labels
- Battery and connection status

SPDX-License-Identifier: GPL-3.0
"""

import gi
import sys
import os
import signal
import math
import json
import time
from pathlib import Path

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gdk, GLib, Gio, Adw, Pango, Graphene

# =============================================================================
# CONFIGURATION MANAGER
# =============================================================================
class ConfigManager:
    """Manages JuhRadial MX configuration - shares config with daemon"""

    CONFIG_DIR = Path.home() / ".config" / "juhradial"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    DEFAULT_CONFIG = {
        "haptics": {
            "enabled": True,
            "default_pattern": "subtle_collision",
            "per_event": {
                "menu_appear": "damp_state_change",
                "slice_change": "subtle_collision",
                "confirm": "sharp_state_change",
                "invalid": "angry_alert"
            },
            "debounce_ms": 20,
            "slice_debounce_ms": 20,
            "reentry_debounce_ms": 50
        },
        "theme": "catppuccin-mocha",
        "blur_enabled": True,
        "pointer": {
            "speed": 10,
            "acceleration": True
        },
        "scroll": {
            "natural": False,
            "smooth": True,
            "smartshift": True,
            "smartshift_threshold": 50
        },
        "app": {
            "start_at_login": True,
            "show_tray_icon": True
        },
        "radial_menu": {
            "slices": [
                {"label": "Play/Pause", "type": "exec", "command": "playerctl play-pause", "color": "green", "icon": "media-playback-start-symbolic"},
                {"label": "New Note", "type": "exec", "command": "kwrite", "color": "yellow", "icon": "document-new-symbolic"},
                {"label": "Lock", "type": "exec", "command": "loginctl lock-session", "color": "red", "icon": "system-lock-screen-symbolic"},
                {"label": "Settings", "type": "settings", "command": "", "color": "mauve", "icon": "emblem-system-symbolic"},
                {"label": "Screenshot", "type": "exec", "command": "spectacle", "color": "blue", "icon": "camera-photo-symbolic"},
                {"label": "Emoji", "type": "emoji", "command": "", "color": "pink", "icon": "face-smile-symbolic"},
                {"label": "Files", "type": "exec", "command": "dolphin", "color": "sapphire", "icon": "folder-symbolic"},
                {"label": "AI", "type": "submenu", "command": "", "color": "teal", "icon": "applications-science-symbolic"}
            ]
        }
    }

    def __init__(self):
        self.config = self._load()
        self._toast_callback = None

    def set_toast_callback(self, callback):
        """Set callback for showing toast notifications"""
        self._toast_callback = callback

    def _show_toast(self, message):
        """Show toast if callback is set"""
        if self._toast_callback:
            self._toast_callback(message)

    def _load(self) -> dict:
        """Load config from file or return defaults"""
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                # Merge with defaults to ensure all keys exist
                return self._merge_defaults(loaded)
        except Exception as e:
            print(f"Error loading config: {e}")
        return self.DEFAULT_CONFIG.copy()

    def _merge_defaults(self, loaded: dict) -> dict:
        """Deep merge loaded config with defaults"""
        result = json.loads(json.dumps(self.DEFAULT_CONFIG))  # Deep copy
        self._deep_update(result, loaded)
        return result

    def _deep_update(self, base: dict, updates: dict):
        """Recursively update base dict with updates"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def save(self, show_toast=True):
        """Save config to file and notify daemon"""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            # Notify daemon to reload config
            self._notify_daemon()
            if show_toast:
                self._show_toast("Settings saved")
        except Exception as e:
            print(f"Error saving config: {e}")
            self._show_toast(f"Error saving settings: {e}")

    def _notify_daemon(self):
        """Notify daemon to reload config via D-Bus"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                'org.kde.juhradialmx',
                '/org/kde/juhradialmx/Daemon',
                'org.kde.juhradialmx.Daemon',
                None
            )
            proxy.call_sync('ReloadConfig', None, Gio.DBusCallFlags.NONE, 500, None)
        except Exception:
            pass  # Daemon may not be running

    def apply_to_device(self):
        """Apply settings to device via logiops (requires sudo)"""
        import subprocess
        script_path = Path(__file__).parent.parent / 'scripts' / 'apply-settings.sh'
        if script_path.exists():
            # Run in konsole for sudo password prompt
            subprocess.Popen([
                'konsole', '-e', 'bash', '-c',
                f'{script_path}; echo ""; echo "Press Enter to close..."; read'
            ])

    def get(self, *keys, default=None):
        """Get nested config value"""
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, *keys_and_value):
        """Set nested config value and save"""
        if len(keys_and_value) < 2:
            return
        *keys, value = keys_and_value
        target = self.config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
        self.save()

# Global config instance
config = ConfigManager()

# =============================================================================
# THEME SYSTEM - Load colors from shared theme module
# =============================================================================
from themes import get_colors, get_theme, load_theme_name, get_theme_list, is_dark_theme, THEMES, DEFAULT_THEME

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
IS_DARK_THEME = COLORS.get('is_dark', True)

# =============================================================================
# WINDOW CONFIGURATION
# =============================================================================
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800

# =============================================================================
# MX MASTER 4 BUTTON DEFINITIONS
# Positions for 3/4 angle view (front-top-left perspective)
# Coordinates are normalized (0-1) relative to the drawing area
# line_from: 'top' = line comes from above, 'left' = line comes from left
# =============================================================================
MOUSE_BUTTONS = {
    'middle': {
        'name': 'Middle Button',
        'action': 'Middle Click',
        'pos': (0.58, 0.19),  # Top of MagSpeed scroll wheel
        'line_from': 'top',
    },
    'shift_wheel': {
        'name': 'Shift Wheel Mode',
        'action': 'SmartShift',
        'pos': (0.58, 0.36),  # Square button below scroll wheel
        'line_from': 'top',
    },
    'forward': {
        'name': 'Forward',
        'action': 'Forward',
        'pos': (0.23, 0.40),  # Upper thumb button
        'line_from': 'left',
    },
    'horizontal_scroll': {
        'name': 'Horizontal Scroll',
        'action': 'Scroll Left/Right',
        'pos': (0.24, 0.47),  # Grey thumb wheel
        'line_from': 'left',
    },
    'back': {
        'name': 'Back',
        'action': 'Back',
        'pos': (0.27, 0.54),  # Lower thumb button
        'line_from': 'left',
    },
    'gesture': {
        'name': 'Gestures',
        'action': 'Virtual desktops',
        'pos': (0.26, 0.36),  # Dot on upper thumb area
        'line_from': 'l_up',
        'label_y': 0.34,  # Label Y position (above Forward)
    },
    'thumb': {
        'name': 'Show Actions Ring',
        'action': 'Radial Menu',
        'pos': (0.28, 0.42),  # Dot on lower thumb area
        'line_from': 'l_up',
        'label_y': 0.26,  # Label Y position (above Gestures)
    },
}

# =============================================================================
# SIDEBAR NAVIGATION ITEMS
# =============================================================================
NAV_ITEMS = [
    ('buttons', 'BUTTONS', 'input-mouse-symbolic'),
    ('scroll', 'POINT, SCROLL, PRESS', 'input-touchpad-symbolic'),
    ('haptics', 'HAPTIC FEEDBACK', 'audio-speakers-symbolic'),
    ('easy_switch', 'EASY-SWITCH', 'network-wireless-symbolic'),
    ('flow', 'FLOW', 'view-dual-symbolic'),
    ('settings', 'SETTINGS', 'emblem-system-symbolic'),
]

# =============================================================================
# CSS STYLESHEET - ADAPTIVE THEME SYSTEM
# Supports both dark and light themes with proper color handling
# =============================================================================
def generate_css():
    """Generate CSS with current theme colors - call when theme changes"""
    is_dark = COLORS.get('is_dark', True)

    # Parse accent colors to RGB for dynamic opacity values
    accent = COLORS.get('accent', '#00d4ff')
    accent2 = COLORS.get('accent2', '#0abdc6')
    ar, ag, ab = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    a2r, a2g, a2b = int(accent2[1:3], 16), int(accent2[3:5], 16), int(accent2[5:7], 16)

    # Dynamic accent opacity variants
    accent_05 = f'rgba({ar}, {ag}, {ab}, 0.05)'
    accent_08 = f'rgba({ar}, {ag}, {ab}, 0.08)'
    accent_10 = f'rgba({ar}, {ag}, {ab}, 0.1)'
    accent_12 = f'rgba({ar}, {ag}, {ab}, 0.12)'
    accent_15 = f'rgba({ar}, {ag}, {ab}, 0.15)'
    accent_20 = f'rgba({ar}, {ag}, {ab}, 0.2)'
    accent_25 = f'rgba({ar}, {ag}, {ab}, 0.25)'
    accent_30 = f'rgba({ar}, {ag}, {ab}, 0.3)'
    accent_35 = f'rgba({ar}, {ag}, {ab}, 0.35)'
    accent_40 = f'rgba({ar}, {ag}, {ab}, 0.4)'
    accent_50 = f'rgba({ar}, {ag}, {ab}, 0.5)'

    # Dynamic accent2 opacity variants
    accent2_05 = f'rgba({a2r}, {a2g}, {a2b}, 0.05)'
    accent2_08 = f'rgba({a2r}, {a2g}, {a2b}, 0.08)'
    accent2_10 = f'rgba({a2r}, {a2g}, {a2b}, 0.1)'
    accent2_15 = f'rgba({a2r}, {a2g}, {a2b}, 0.15)'

    # Theme-aware color adjustments
    if is_dark:
        # Dark theme: use dark backgrounds with light accents
        shadow_color = 'rgba(0, 0, 0, 0.4)'
        shadow_color_strong = 'rgba(0, 0, 0, 0.5)'
        hover_bg = f"linear-gradient(135deg, {COLORS['surface1']} 0%, {COLORS['surface0']} 100%)"
        card_bg = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['base']} 100%)"
        border_subtle = 'rgba(255, 255, 255, 0.1)'
        border_very_subtle = 'rgba(255, 255, 255, 0.05)'
        border_faint = 'rgba(255, 255, 255, 0.03)'
        text_on_accent = COLORS['crust']
        elevated_bg = f"linear-gradient(135deg, rgba(26, 29, 36, 0.95) 0%, rgba(18, 20, 24, 0.9) 100%)"
        elevated_bg_hover = f"linear-gradient(135deg, rgba(36, 40, 50, 0.5) 0%, rgba(26, 29, 36, 0.3) 100%)"
        tooltip_bg = 'linear-gradient(135deg, rgba(26, 29, 36, 0.98) 0%, rgba(18, 20, 24, 0.95) 100%)'
    else:
        # Light theme: use light backgrounds with darker accents
        shadow_color = 'rgba(0, 0, 0, 0.1)'
        shadow_color_strong = 'rgba(0, 0, 0, 0.15)'
        hover_bg = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['surface1']} 100%)"
        card_bg = f"linear-gradient(135deg, {COLORS['base']} 0%, {COLORS['mantle']} 100%)"
        border_subtle = 'rgba(0, 0, 0, 0.1)'
        border_very_subtle = 'rgba(0, 0, 0, 0.06)'
        border_faint = 'rgba(0, 0, 0, 0.04)'
        text_on_accent = '#ffffff'
        elevated_bg = f"linear-gradient(135deg, {COLORS['base']} 0%, {COLORS['surface0']} 100%)"
        elevated_bg_hover = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['surface1']} 100%)"
        tooltip_bg = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['mantle']} 100%)"

    return f"""
/* ============================================
   GLOBAL TRANSITIONS & ANIMATIONS
   ============================================ */
@keyframes pulse-glow {{
    0%, 100% {{ box-shadow: 0 0 20px {COLORS['accent_glow']}; }}
    50% {{ box-shadow: 0 0 35px {COLORS['accent_glow']}; }}
}}

@keyframes subtle-pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.85; }}
}}

@keyframes slide-in {{
    from {{ opacity: 0; transform: translateX(20px); }}
    to {{ opacity: 1; transform: translateX(0); }}
}}

/* ============================================
   MAIN WINDOW
   ============================================ */
window.settings-window {{
    background: linear-gradient(180deg, {COLORS['crust']} 0%, {COLORS['mantle']} 100%);
}}

/* ============================================
   HEADER BAR - Premium Glass Effect
   ============================================ */
.header-area {{
    background: {COLORS['mantle']};
    padding: 18px 28px;
    border-bottom: 1px solid {border_subtle};
    box-shadow: 0 4px 24px {shadow_color};
}}

.device-title {{
    font-size: 26px;
    font-weight: 700;
    color: {COLORS['text']};
    letter-spacing: 0.5px;
}}

.add-app-btn {{
    background: {COLORS['surface0']};
    color: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    border-radius: 10px;
    padding: 10px 20px;
    font-weight: 600;
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.add-app-btn:hover {{
    background: {COLORS['accent']};
    color: {text_on_accent};
    box-shadow: 0 4px 20px {COLORS['accent_glow']};
    transform: translateY(-1px);
}}

/* ============================================
   SIDEBAR NAVIGATION - Sleek & Modern
   ============================================ */
.sidebar {{
    background: {COLORS['mantle']};
    padding: 12px 10px;
    min-width: 230px;
    border-right: 1px solid {border_subtle};
    box-shadow: 4px 0 24px {shadow_color};
}}

.nav-item {{
    padding: 16px 18px;
    border-radius: 12px;
    margin: 4px 0;
    color: {COLORS['subtext0']};
    font-weight: 500;
    font-size: 13px;
    letter-spacing: 0.3px;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid transparent;
}}

.nav-item:hover {{
    background: {hover_bg};
    color: {COLORS['text']};
    border-color: {COLORS['accent_glow_light']};
    transform: translateX(4px);
    box-shadow: 0 4px 16px {shadow_color};
}}

.nav-item.active {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    font-weight: 600;
    box-shadow: 0 4px 20px {COLORS['accent_glow']};
    border-color: transparent;
}}

.nav-item.active:hover {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    transform: translateX(4px);
    box-shadow: 0 6px 28px {COLORS['accent_glow']};
}}

/* ============================================
   MAIN CONTENT AREA
   ============================================ */
.content-area {{
    background: {COLORS['base']};
}}

/* ============================================
   MOUSE VISUALIZATION AREA
   ============================================ */
.mouse-area {{
    background: radial-gradient(ellipse at center, {COLORS['surface0']} 0%, {COLORS['base']} 70%);
    padding: 40px;
}}

/* ============================================
   BUTTON LABELS ON MOUSE - Premium Floating Tags
   ============================================ */
.button-label {{
    background: {card_bg};
    color: {COLORS['text']};
    padding: 10px 16px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    box-shadow: 0 4px 20px {shadow_color_strong};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid {border_subtle};
}}

.button-label:hover {{
    background: {COLORS['surface1']};
    border-color: {COLORS['accent']};
    box-shadow: 0 6px 28px {COLORS['accent_glow']};
    color: {COLORS['accent']};
}}

.button-label.highlighted {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    box-shadow: 0 6px 28px {COLORS['accent_glow']};
    border-color: transparent;
}}

/* ============================================
   SETTINGS CARDS - Glassmorphism Effect
   ============================================ */
.settings-card {{
    background: {card_bg};
    border-radius: 16px;
    padding: 24px;
    margin: 14px;
    border: 1px solid {border_subtle};
    box-shadow: 0 8px 32px {shadow_color};
    transition: all 300ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.settings-card:hover {{
    border-color: {COLORS['accent_glow_light']};
    box-shadow: 0 12px 40px {shadow_color_strong};
    transform: translateY(-2px);
}}

.card-title {{
    font-size: 17px;
    font-weight: 700;
    color: {COLORS['text']};
    margin-bottom: 18px;
    letter-spacing: 0.5px;
    padding-bottom: 12px;
    border-bottom: 1px solid {border_subtle};
}}

/* ============================================
   SETTINGS ROWS - Interactive List Items
   ============================================ */
.setting-row {{
    padding: 14px 12px;
    border-radius: 10px;
    margin: 4px 0;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid transparent;
}}

.setting-row:hover {{
    background: {hover_bg};
    border-color: {border_subtle};
    transform: translateX(4px);
}}

.setting-label {{
    color: {COLORS['text']};
    font-size: 14px;
    font-weight: 500;
}}

.setting-value {{
    color: {COLORS['subtext0']};
    font-size: 13px;
}}

/* ============================================
   STATUS BAR - Premium Bottom Bar
   ============================================ */
.status-bar {{
    background: {COLORS['crust']};
    padding: 14px 28px;
    border-top: 1px solid {border_subtle};
    box-shadow: 0 -4px 24px {shadow_color};
}}

.battery-icon {{
    color: {COLORS['green']};
    opacity: 0.9;
}}

.battery-indicator {{
    color: {COLORS['green']};
    font-weight: 600;
}}

.connection-icon {{
    color: {COLORS['accent']};
    opacity: 0.8;
}}

.connection-status {{
    color: {COLORS['subtext1']};
    font-size: 13px;
    font-weight: 500;
}}

/* ============================================
   SWITCHES - Modern Toggle Design
   ============================================ */
switch {{
    background: linear-gradient(135deg, {COLORS['surface1']} 0%, {COLORS['surface2']} 100%);
    border-radius: 16px;
    min-width: 52px;
    min-height: 28px;
    border: 1px solid {border_very_subtle};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

switch:hover {{
    border-color: {accent_30};
}}

switch:checked {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    box-shadow: 0 2px 12px {accent_40};
    border-color: transparent;
}}

switch slider {{
    background: linear-gradient(135deg, {COLORS['text']} 0%, {COLORS['subtext1']} 100%);
    border-radius: 14px;
    min-width: 24px;
    min-height: 24px;
    margin: 2px;
    box-shadow: 0 2px 8px {shadow_color};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

switch:checked slider {{
    background: {COLORS['text']};
    box-shadow: 0 2px 8px {shadow_color_strong};
}}

/* ============================================
   SCALES/SLIDERS - Premium Slider Design
   ============================================ */
scale trough {{
    background: linear-gradient(90deg, {COLORS['surface1']} 0%, {COLORS['surface2']} 100%);
    border-radius: 6px;
    min-height: 8px;
    border: 1px solid {border_faint};
}}

scale highlight {{
    background: linear-gradient(90deg, {COLORS['accent2']} 0%, {COLORS['accent']} 100%);
    border-radius: 6px;
    box-shadow: 0 0 12px {accent_30};
}}

scale slider {{
    background: linear-gradient(135deg, {COLORS['text']} 0%, {COLORS['subtext1']} 100%);
    border-radius: 50%;
    min-width: 22px;
    min-height: 22px;
    box-shadow: 0 2px 8px {shadow_color_strong};
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: none;
}}

scale slider:hover {{
    box-shadow: 0 4px 16px {accent_30}, 0 2px 8px {shadow_color_strong};
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
}}

/* ============================================
   SCROLLBAR - Minimal Modern Design
   ============================================ */
scrollbar {{
    background: transparent;
}}

scrollbar slider {{
    background: linear-gradient(180deg, {COLORS['surface2']} 0%, {COLORS['overlay0']} 100%);
    border-radius: 6px;
    min-width: 8px;
    transition: all 200ms ease;
    border: 1px solid {border_faint};
}}

scrollbar slider:hover {{
    background: linear-gradient(180deg, {COLORS['overlay0']} 0%, {COLORS['overlay1']} 100%);
    min-width: 10px;
}}

/* ============================================
   PRIMARY BUTTONS - Accent Gradient
   ============================================ */
.primary-btn {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    border: none;
    border-radius: 12px;
    padding: 12px 24px;
    font-weight: 700;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 16px {accent_30};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.primary-btn:hover {{
    background: linear-gradient(135deg, {COLORS['accent2']} 0%, {COLORS['accent']} 100%);
    box-shadow: 0 6px 24px {accent_50};
    transform: translateY(-2px);
}}

.primary-btn:active {{
    transform: translateY(0);
    box-shadow: 0 2px 8px {accent_30};
}}

/* ============================================
   DANGER BUTTONS - Warning Style
   ============================================ */
.danger-btn {{
    background: transparent;
    color: {COLORS['red']};
    border: 2px solid rgba(255, 82, 82, 0.5);
    border-radius: 12px;
    padding: 12px 24px;
    font-weight: 600;
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.danger-btn:hover {{
    background: rgba(255, 82, 82, 0.15);
    border-color: {COLORS['red']};
    box-shadow: 0 4px 20px rgba(255, 82, 82, 0.25);
    transform: translateY(-2px);
}}

/* ============================================
   SECONDARY/GHOST BUTTONS
   ============================================ */
.secondary-btn {{
    background: transparent;
    color: {COLORS['accent']};
    border: 1px solid {accent_30};
    border-radius: 10px;
    padding: 10px 20px;
    font-weight: 600;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.secondary-btn:hover {{
    background: {accent_10};
    border-color: {COLORS['accent']};
    box-shadow: 0 4px 16px {accent_20};
}}

/* ============================================
   DROPDOWN/COMBOBOX STYLING
   ============================================ */
dropdown {{
    background: linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['surface1']} 100%);
    border: 1px solid {accent_15};
    border-radius: 10px;
    padding: 8px 16px;
    color: {COLORS['text']};
    transition: all 200ms ease;
}}

dropdown:hover {{
    border-color: {accent_40};
    box-shadow: 0 4px 16px {accent_15};
}}

dropdown popover {{
    background: {COLORS['surface0']};
    border: 1px solid {accent_20};
    border-radius: 12px;
    box-shadow: 0 8px 32px {shadow_color_strong};
}}

/* ============================================
   ENTRY/INPUT FIELDS
   ============================================ */
entry {{
    background: {COLORS['surface0']};
    border: 1px solid {COLORS['surface1']};
    border-radius: 10px;
    padding: 10px 14px;
    color: {COLORS['text']};
    transition: all 200ms ease;
}}

entry:focus {{
    border-color: {COLORS['accent']};
    box-shadow: 0 0 0 3px {accent_15}, 0 4px 16px {accent_10};
}}

/* ============================================
   TOOLTIPS
   ============================================ */
tooltip {{
    background: {tooltip_bg};
    border: 1px solid {accent_20};
    border-radius: 10px;
    padding: 10px 14px;
    box-shadow: 0 8px 32px {shadow_color_strong};
    color: {COLORS['text']};
}}

/* ============================================
   SPECIAL EFFECTS - Glow Classes
   ============================================ */
.glow-accent {{
    box-shadow: 0 0 20px {COLORS['accent_glow']};
}}

.glow-pulse {{
    animation: pulse-glow 2s ease-in-out infinite;
}}

.animate-slide-in {{
    animation: slide-in 300ms cubic-bezier(0.4, 0, 0.2, 1);
}}

/* ============================================
   HAPTIC PATTERN LIST ITEMS
   ============================================ */
.haptic-pattern-item {{
    padding: 14px 16px;
    border-radius: 10px;
    margin: 4px 0;
    background: transparent;
    border: 1px solid transparent;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.haptic-pattern-item:hover {{
    background: {accent_08};
    border-color: {accent_15};
}}

.haptic-pattern-item.selected {{
    background: linear-gradient(135deg, {accent_15} 0%, {accent2_10} 100%);
    border-color: {COLORS['accent']};
    box-shadow: 0 4px 16px {accent_20};
}}

/* ============================================
   SECTION DIVIDERS
   ============================================ */
.section-divider {{
    background: linear-gradient(90deg, transparent 0%, {accent_30} 50%, transparent 100%);
    min-height: 1px;
    margin: 20px 0;
}}

/* ============================================
   BUTTON ASSIGNMENT UI - Premium Design
   ============================================ */
.button-assignment-card {{
    background: {elevated_bg};
    border-radius: 16px;
    padding: 20px;
    margin: 12px 0;
    border: 1px solid {accent_08};
    box-shadow: 0 8px 32px {shadow_color_strong};
}}

.button-assignment-header {{
    font-size: 15px;
    font-weight: 700;
    color: {COLORS['accent']};
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid {accent_15};
}}

.button-row {{
    background: {elevated_bg_hover};
    border-radius: 12px;
    padding: 14px 16px;
    margin: 6px 0;
    border: 1px solid {border_faint};
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.button-row:hover {{
    background: linear-gradient(135deg, {accent_12} 0%, {accent2_08} 100%);
    border-color: {accent_25};
    transform: translateX(4px);
    box-shadow: 0 4px 16px {accent_15};
}}

.button-icon-box {{
    background: linear-gradient(135deg, {accent_20} 0%, {accent2_15} 100%);
    border-radius: 10px;
    padding: 10px;
    min-width: 42px;
    min-height: 42px;
    border: 1px solid {accent_20};
}}

.button-icon {{
    color: {COLORS['accent']};
}}

.button-name {{
    font-size: 15px;
    font-weight: 600;
    color: {COLORS['text']};
    letter-spacing: 0.3px;
}}

.button-action {{
    font-size: 13px;
    font-weight: 500;
    color: {COLORS['accent']};
    padding: 4px 10px;
    background: {accent_10};
    border-radius: 6px;
    border: 1px solid {accent_20};
}}

.button-arrow {{
    color: {COLORS['subtext0']};
    padding: 8px;
    border-radius: 8px;
    transition: all 200ms ease;
}}

.button-arrow:hover {{
    background: {accent_15};
    color: {COLORS['accent']};
}}

/* Radial Menu Card - Featured Style */
.radial-menu-card {{
    background: linear-gradient(135deg, {accent_08} 0%, {accent2_05} 100%);
    border-radius: 16px;
    padding: 24px;
    margin: 20px 0 12px 0;
    border: 1px solid {accent_20};
    box-shadow: 0 8px 32px {accent_10}, 0 4px 16px {shadow_color};
}}

.radial-menu-card:hover {{
    border-color: {accent_35};
    box-shadow: 0 12px 40px {accent_15}, 0 6px 20px {shadow_color_strong};
}}

.radial-icon-large {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    border-radius: 14px;
    padding: 16px;
    min-width: 56px;
    min-height: 56px;
    box-shadow: 0 4px 16px {accent_35};
}}

.radial-icon-large image {{
    color: {text_on_accent};
}}

.radial-title {{
    font-size: 18px;
    font-weight: 700;
    color: {COLORS['text']};
    letter-spacing: 0.5px;
}}

.radial-subtitle {{
    font-size: 13px;
    color: {COLORS['subtext1']};
    margin-top: 4px;
}}

.configure-radial-btn {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 16px {accent_35};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.configure-radial-btn:hover {{
    box-shadow: 0 6px 24px {accent_50};
    transform: translateY(-2px);
}}

/* Slice Row Styling */
.slice-row {{
    background: {COLORS['surface0']};
    border-radius: 8px;
    padding: 10px 12px;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid transparent;
}}

.slice-row:hover {{
    background: {COLORS['surface1']};
    border-color: {accent_20};
}}

.slice-icon {{
    color: {COLORS['subtext1']};
    opacity: 0.8;
}}

.slice-label {{
    font-size: 13px;
    font-weight: 500;
    color: {COLORS['text']};
}}

.slice-edit-btn {{
    opacity: 0.5;
    transition: opacity 200ms;
}}

.slice-row:hover .slice-edit-btn {{
    opacity: 1;
}}

/* Color Picker Buttons */
.color-btn-green {{ background: #00e676; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-green:checked {{ border-color: white; box-shadow: 0 0 8px #00e676; }}
.color-btn-yellow {{ background: #ffd54f; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-yellow:checked {{ border-color: white; box-shadow: 0 0 8px #ffd54f; }}
.color-btn-red {{ background: #ff5252; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-red:checked {{ border-color: white; box-shadow: 0 0 8px #ff5252; }}
.color-btn-mauve {{ background: #b388ff; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-mauve:checked {{ border-color: white; box-shadow: 0 0 8px #b388ff; }}
.color-btn-blue {{ background: #4a9eff; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-blue:checked {{ border-color: white; box-shadow: 0 0 8px #4a9eff; }}
.color-btn-pink {{ background: #ff80ab; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-pink:checked {{ border-color: white; box-shadow: 0 0 8px #ff80ab; }}
.color-btn-sapphire {{ background: #00b4d8; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-sapphire:checked {{ border-color: white; box-shadow: 0 0 8px #00b4d8; }}
.color-btn-teal {{ background: #0abdc6; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-teal:checked {{ border-color: white; box-shadow: 0 0 8px #0abdc6; }}

/* Preset Action Buttons */
.preset-btn {{
    background: {COLORS['surface0']};
    border: 1px solid {COLORS['surface2']};
    border-radius: 8px;
    padding: 8px 12px;
    transition: all 200ms;
}}

.preset-btn:hover {{
    background: {COLORS['surface1']};
    border-color: {COLORS['accent']};
}}

/* Section Header */
.section-header {{
    font-size: 12px;
    font-weight: 600;
    color: {COLORS['subtext0']};
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 12px;
    margin-top: 8px;
}}

/* ============================================
   PREMIUM HEADER STYLING
   ============================================ */
.app-title {{
    font-size: 22px;
    font-weight: 800;
    color: {COLORS['text']};
    letter-spacing: 0.5px;
}}

.app-title-accent {{
    color: {COLORS['accent']};
}}

.app-subtitle {{
    font-size: 11px;
    font-weight: 500;
    color: {COLORS['subtext0']};
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 2px;
}}

.logo-container {{
    background: linear-gradient(135deg, {accent_15} 0%, {accent2_10} 100%);
    border-radius: 12px;
    padding: 8px;
    border: 1px solid {accent_20};
    box-shadow: 0 4px 16px {accent_15};
}}

.device-badge {{
    background: linear-gradient(135deg, rgba(0, 230, 118, 0.15) 0%, rgba(0, 200, 100, 0.1) 100%);
    border: 1px solid rgba(0, 230, 118, 0.3);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    color: {COLORS['green']};
    letter-spacing: 0.5px;
}}

.header-divider {{
    background: linear-gradient(90deg, {accent_40} 0%, {accent_10} 100%);
    min-width: 2px;
    min-height: 36px;
    border-radius: 1px;
    margin: 0 16px;
}}
"""

# Generate CSS at module load time
CSS = generate_css()


class NavButton(Gtk.Button):
    """Sidebar navigation button"""

    def __init__(self, item_id, label, icon_name, on_click=None):
        super().__init__()
        self.item_id = item_id
        self.add_css_class('nav-item')

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        box.append(icon)

        label_widget = Gtk.Label(label=label)
        label_widget.set_halign(Gtk.Align.START)
        box.append(label_widget)

        self.set_child(box)

        if on_click:
            self.connect('clicked', lambda _: on_click(item_id))

    def set_active(self, active):
        if active:
            self.add_css_class('active')
        else:
            self.remove_css_class('active')


class MouseVisualization(Gtk.DrawingArea):
    """Interactive mouse visualization with hoverable button labels"""

    def __init__(self, on_button_click=None):
        super().__init__()
        self.on_button_click = on_button_click
        self.hovered_button = None
        self.mouse_image = None
        # Store image rect for button positioning
        self.img_rect = (0, 0, 600, 500)  # (x_offset, y_offset, width, height)
        # Cache for hit regions (computed when img_rect changes)
        self._hit_cache = None
        self._cached_img_rect = None
        # Motion throttling
        self._last_motion_time = 0

        self.set_content_width(600)
        self.set_content_height(500)
        self.set_draw_func(self._draw)

        # Load mouse image
        image_paths = [
            os.path.join(os.path.dirname(__file__), '../assets/devices/logitechmouse.png'),
            os.path.join(os.path.dirname(__file__), 'assets/devices/logitechmouse.png'),
            '/usr/share/juhradialmx/devices/logitechmouse.png',
        ]

        for path in image_paths:
            if os.path.exists(path):
                try:
                    self.mouse_image = Gdk.Texture.new_from_filename(path)
                    break
                except Exception as e:
                    print(f"Failed to load image: {e}")

        # Mouse tracking
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        self.add_controller(motion)

        # Click handling
        click = Gtk.GestureClick()
        click.connect('released', self._on_click)
        self.add_controller(click)

    def _compute_hit_regions(self):
        """Pre-compute hit regions for all buttons (called when img_rect changes)"""
        img_x, img_y, img_w, img_h = self.img_rect
        hit_regions = {}

        for btn_id, btn_info in MOUSE_BUTTONS.items():
            btn_x = img_x + btn_info['pos'][0] * img_w
            btn_y = img_y + btn_info['pos'][1] * img_h
            line_from = btn_info.get('line_from', 'left')
            custom_label_y = btn_info.get('label_y', None)

            # Label box dimensions
            label_width = 130
            label_height = 28

            # Calculate label position based on line direction
            if line_from == 'top':
                line_length = 60
                lx = btn_x - label_width / 2
                ly = btn_y - line_length - label_height
            elif line_from == 'l_up':
                line_length = 60
                lx = btn_x - line_length - label_width
                if custom_label_y is not None:
                    ly = img_y + custom_label_y * img_h - label_height / 2
                else:
                    ly = btn_y - label_height / 2
            elif line_from == 'left_short':
                line_length = 25
                lx = btn_x - line_length - label_width
                ly = btn_y - label_height / 2
            else:
                line_length = 60
                lx = btn_x - line_length - label_width
                ly = btn_y - label_height / 2

            hit_regions[btn_id] = {
                'dot_x': btn_x,
                'dot_y': btn_y,
                'label_x': lx,
                'label_y': ly,
                'label_w': label_width,
                'label_h': label_height,
            }

        return hit_regions

    def _on_motion(self, controller, x, y):
        # Throttle motion events to ~30fps (33ms between updates)
        current_time = time.monotonic()
        if current_time - self._last_motion_time < 0.033:
            return
        self._last_motion_time = current_time

        # Rebuild hit cache if img_rect changed
        if self._hit_cache is None or self._cached_img_rect != self.img_rect:
            self._hit_cache = self._compute_hit_regions()
            self._cached_img_rect = self.img_rect

        # Check if hovering over any button region
        old_hovered = self.hovered_button
        self.hovered_button = None

        # Use squared distance comparison (625 = 25^2) to avoid sqrt
        hover_radius_sq = 625

        for btn_id, region in self._hit_cache.items():
            # Check dot (squared distance - no sqrt needed)
            dx = x - region['dot_x']
            dy = y - region['dot_y']
            if dx * dx + dy * dy < hover_radius_sq:
                self.hovered_button = btn_id
                break

            # Check label box
            lx, ly = region['label_x'], region['label_y']
            lw, lh = region['label_w'], region['label_h']
            if lx <= x <= lx + lw and ly <= y <= ly + lh:
                self.hovered_button = btn_id
                break

        if old_hovered != self.hovered_button:
            self.queue_draw()

    def _on_leave(self, controller):
        if self.hovered_button:
            self.hovered_button = None
            self.queue_draw()

    def _on_click(self, gesture, n_press, x, y):
        if self.hovered_button and self.on_button_click:
            self.on_button_click(self.hovered_button)

    def _draw(self, area, cr, width, height):
        # Draw mouse image centered
        if self.mouse_image:
            img_width = self.mouse_image.get_width()
            img_height = self.mouse_image.get_height()

            # Scale to fit
            scale = min(width * 0.7 / img_width, height * 0.8 / img_height)
            scaled_w = img_width * scale
            scaled_h = img_height * scale

            x_offset = (width - scaled_w) / 2
            y_offset = (height - scaled_h) / 2

            # Store image rect for button positioning
            self.img_rect = (x_offset, y_offset, scaled_w, scaled_h)

            cr.save()
            cr.translate(x_offset, y_offset)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, self._texture_to_pixbuf(self.mouse_image), 0, 0)
            cr.paint()
            cr.restore()
        else:
            # Draw placeholder - store rect for button positioning
            self.img_rect = (width * 0.2, height * 0.1, width * 0.6, height * 0.8)
            cr.set_source_rgba(0.3, 0.3, 0.4, 1)
            cr.rectangle(*self.img_rect)
            cr.fill()

            cr.set_source_rgba(0.8, 0.8, 0.9, 1)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(16)
            cr.move_to(width * 0.35, height * 0.5)
            cr.show_text("MX Master 4")

        # Draw button labels (positioned relative to image rect)
        for btn_id, btn_info in MOUSE_BUTTONS.items():
            self._draw_button_label(cr, btn_id, btn_info)

    def _draw_button_label(self, cr, btn_id, btn_info):
        # Position buttons relative to the actual mouse image rect
        img_x, img_y, img_w, img_h = self.img_rect
        x = img_x + btn_info['pos'][0] * img_w
        y = img_y + btn_info['pos'][1] * img_h
        label = btn_info['name']
        is_hovered = (btn_id == self.hovered_button)
        line_from = btn_info.get('line_from', 'left')

        # Measure text
        cr.select_font_face("Sans", 0, 1 if is_hovered else 0)
        cr.set_font_size(11)
        extents = cr.text_extents(label)

        padding_x = 14
        padding_y = 8
        box_width = extents.width + padding_x * 2
        box_height = extents.height + padding_y * 2

        # Calculate label position based on line direction
        custom_label_y = btn_info.get('label_y', None)

        if line_from == 'top':
            # Line comes from above, label above the point
            line_length = 60
            label_x = x - box_width / 2
            label_y = y - line_length - box_height
            line_start_x, line_start_y = x, y - 6
            line_end_x, line_end_y = x, label_y + box_height
        elif line_from == 'l_up':
            # L-shaped line: horizontal left, then vertical up to label
            line_length = 60
            label_x = x - line_length - box_width
            # Use custom label_y if provided, otherwise calculate
            if custom_label_y is not None:
                label_y = img_y + custom_label_y * img_h - box_height / 2
            else:
                label_y = y - box_height / 2
            line_start_x, line_start_y = x - 6, y
            line_mid_x = label_x + box_width + 15  # horizontal end point
            line_end_x, line_end_y = label_x + box_width, label_y + box_height / 2
        elif line_from == 'left_short':
            # Short horizontal line (about 25px)
            line_length = 25
            label_x = x - line_length - box_width
            label_y = y - box_height / 2
            line_start_x, line_start_y = x - 6, y
            line_end_x, line_end_y = label_x + box_width, y
        else:
            # Line comes from left, label to the left of point
            line_length = 60
            label_x = x - line_length - box_width
            label_y = y - box_height / 2
            line_start_x, line_start_y = x - 6, y
            line_end_x, line_end_y = label_x + box_width, y

        # Draw shadow first (offset) - deeper shadow for premium feel
        cr.set_source_rgba(0, 0, 0, 0.4)
        radius = 10
        shadow_offset = 4
        cr.new_path()
        cr.arc(label_x + radius + shadow_offset, label_y + radius + shadow_offset, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius + shadow_offset, label_y + radius + shadow_offset, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius + shadow_offset, label_y + box_height - radius + shadow_offset, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius + shadow_offset, label_y + box_height - radius + shadow_offset, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.fill()

        # Premium glassmorphism background - dark with cyan glow
        if is_hovered:
            # Hover: vibrant cyan gradient
            cr.set_source_rgba(0, 0.83, 1, 0.95)  # #00d4ff - Vibrant cyan
        else:
            # Normal: dark glass with subtle cyan tint
            cr.set_source_rgba(0.1, 0.11, 0.14, 0.92)  # Dark glass matching theme

        cr.new_path()
        cr.arc(label_x + radius, label_y + radius, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + box_height - radius, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius, label_y + box_height - radius, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.fill()

        # Glass border - cyan accent glow
        if is_hovered:
            cr.set_source_rgba(1, 1, 1, 0.5)  # White border on hover
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.35)  # Cyan border glow
        cr.set_line_width(1.5)
        cr.new_path()
        cr.arc(label_x + radius, label_y + radius, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + box_height - radius, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius, label_y + box_height - radius, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.stroke()

        # Draw text
        if is_hovered:
            cr.set_source_rgba(0.04, 0.05, 0.06, 1)  # Dark text on cyan bg
        else:
            cr.set_source_rgba(0.94, 0.96, 0.97, 1)  # Bright white text
        cr.move_to(label_x + padding_x, label_y + padding_y + extents.height)
        cr.show_text(label)

        # Draw connector line - cyan accent
        if is_hovered:
            cr.set_source_rgba(0, 0.83, 1, 0.9)  # Bright cyan line
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.5)  # Subtle cyan line
        cr.set_line_width(2)
        if line_from == 'l_up':
            # L-shaped: horizontal then vertical up
            cr.move_to(line_start_x, line_start_y)
            cr.line_to(line_mid_x, line_start_y)  # horizontal segment
            cr.line_to(line_mid_x, line_end_y)    # vertical segment up
            cr.line_to(line_end_x, line_end_y)    # short horizontal to label
        else:
            cr.move_to(line_start_x, line_start_y)
            cr.line_to(line_end_x, line_end_y)
        cr.stroke()

        # Draw connector dot on the button - cyan glowing dot
        if is_hovered:
            # Glowing dot on hover
            cr.set_source_rgba(0, 0.83, 1, 0.4)  # Outer glow
            cr.arc(x, y, 8, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0, 0.83, 1, 1)  # Bright cyan dot
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.8)  # Cyan dot
        cr.arc(x, y, 5, 0, 2 * math.pi)
        cr.fill()

        # Dot border - white highlight
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.set_line_width(1.5)
        cr.arc(x, y, 5, 0, 2 * math.pi)
        cr.stroke()

    def _texture_to_pixbuf(self, texture):
        """Convert Gdk.Texture to GdkPixbuf for cairo rendering"""
        try:
            from gi.repository import GdkPixbuf
            width = texture.get_width()
            height = texture.get_height()

            # Get texture data
            data = texture.save_to_png_bytes()
            loader = GdkPixbuf.PixbufLoader.new_with_type('png')
            loader.write(data.get_data())
            loader.close()
            return loader.get_pixbuf()
        except Exception as e:
            print(f"Texture conversion error: {e}")
            return None


class SettingsCard(Gtk.Box):
    """A styled settings card"""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class('settings-card')

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class('card-title')
        self.append(title_label)


class SettingRow(Gtk.Box):
    """A row in settings with label and control"""

    def __init__(self, label, description=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class('setting-row')

        # Left side: label and description
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)

        label_widget = Gtk.Label(label=label)
        label_widget.set_halign(Gtk.Align.START)
        label_widget.add_css_class('setting-label')
        text_box.append(label_widget)

        if description:
            desc_widget = Gtk.Label(label=description)
            desc_widget.set_halign(Gtk.Align.START)
            desc_widget.add_css_class('setting-value')
            text_box.append(desc_widget)

        self.append(text_box)

        # Control container (for switch, scale, etc)
        self.control_box = Gtk.Box()
        self.control_box.set_valign(Gtk.Align.CENTER)
        self.append(self.control_box)

    def set_control(self, widget):
        self.control_box.append(widget)


# Default actions for each button (used for restore)
DEFAULT_BUTTON_ACTIONS = {
    'middle': 'Middle Click',
    'shift_wheel': 'SmartShift',
    'forward': 'Forward',
    'horizontal_scroll': 'Scroll Left/Right',
    'back': 'Back',
    'gesture': 'Virtual Desktops',
    'thumb': 'Radial Menu',
}

# Available actions for button assignment
BUTTON_ACTIONS = [
    ('middle_click', 'Middle Click'),
    ('back', 'Back'),
    ('forward', 'Forward'),
    ('copy', 'Copy'),
    ('paste', 'Paste'),
    ('undo', 'Undo'),
    ('redo', 'Redo'),
    ('screenshot', 'Screenshot'),
    ('smartshift', 'SmartShift'),
    ('scroll_left_right', 'Scroll Left/Right'),
    ('volume_up', 'Volume Up'),
    ('volume_down', 'Volume Down'),
    ('play_pause', 'Play/Pause'),
    ('mute', 'Mute'),
    ('radial_menu', 'Radial Menu'),
    ('virtual_desktops', 'Virtual Desktops'),
    ('zoom_in', 'Zoom In'),
    ('zoom_out', 'Zoom Out'),
    ('none', 'Do Nothing'),
    ('custom', 'Custom Action...'),
]


class ButtonConfigDialog(Adw.Window):
    """Dialog for configuring a mouse button action"""

    def __init__(self, parent, button_id, button_info):
        super().__init__()
        self.button_id = button_id
        self.button_info = button_info
        self.selected_action = None
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(f'Configure {button_info["name"]}')
        self.set_default_size(420, 550)

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class('background')

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.add_css_class('flat')
        cancel_btn.connect('clicked', lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label='Save')
        save_btn.add_css_class('suggested-action')
        save_btn.connect('clicked', self._on_save)
        header.pack_end(save_btn)

        content.append(header)

        # Current button info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_margin_start(24)
        info_box.set_margin_end(24)
        info_box.set_margin_top(16)
        info_box.set_margin_bottom(8)

        # Header with title and restore button
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        button_label = Gtk.Label(label=button_info['name'])
        button_label.add_css_class('title-2')
        button_label.set_halign(Gtk.Align.START)
        button_label.set_hexpand(True)
        header_row.append(button_label)

        # Restore default button
        restore_btn = Gtk.Button(label='Restore Default')
        restore_btn.add_css_class('flat')
        restore_btn.add_css_class('dim-label')
        restore_btn.connect('clicked', self._on_restore_default)
        header_row.append(restore_btn)

        info_box.append(header_row)

        current_label = Gtk.Label(label=f"Current: {button_info.get('action', 'Not set')}")
        current_label.add_css_class('dim-label')
        current_label.set_halign(Gtk.Align.START)
        info_box.append(current_label)

        content.append(info_box)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        content.append(sep)

        # Scrollable action list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('boxed-list')
        self.list_box.set_margin_start(16)
        self.list_box.set_margin_end(16)
        self.list_box.set_margin_top(16)
        self.list_box.set_margin_bottom(16)

        # Find current action
        current_action = button_info.get('action', '')

        for action_id, action_name in BUTTON_ACTIONS:
            row = Adw.ActionRow()
            row.set_title(action_name)
            row.set_activatable(True)
            row.action_id = action_id
            row.action_name = action_name

            # Radio-style indicator
            radio = Gtk.CheckButton()
            radio.set_active(action_name == current_action)
            radio.set_sensitive(False)  # Visual only
            row.add_prefix(radio)
            row.radio = radio

            if action_name == current_action:
                self.selected_action = (action_id, action_name)
                self.list_box.select_row(row)

            self.list_box.append(row)

        self.list_box.connect('row-selected', self._on_row_selected)
        scrolled.set_child(self.list_box)
        content.append(scrolled)

        self.set_content(content)

    def _on_row_selected(self, list_box, row):
        if row is None:
            return

        # Update radio buttons visually
        child = list_box.get_first_child()
        while child:
            if hasattr(child, 'radio'):
                child.radio.set_active(child == row)
            child = child.get_next_sibling()

        if hasattr(row, 'action_id'):
            self.selected_action = (row.action_id, row.action_name)

    def _on_restore_default(self, button):
        """Restore button to default action"""
        default_action = DEFAULT_BUTTON_ACTIONS.get(self.button_id, 'Middle Click')

        # Find and select the default action row
        child = self.list_box.get_first_child()
        while child:
            if hasattr(child, 'action_name') and child.action_name == default_action:
                self.list_box.select_row(child)
                break
            child = child.get_next_sibling()

    def _on_save(self, button):
        if self.selected_action:
            action_id, action_name = self.selected_action

            # Update the MOUSE_BUTTONS dict
            if self.button_id in MOUSE_BUTTONS:
                MOUSE_BUTTONS[self.button_id]['action'] = action_name

            # Save to config
            buttons_config = config.get('buttons', default={})
            buttons_config[self.button_id] = action_id
            config.set('buttons', buttons_config)

            print(f'Button {self.button_id} configured to: {action_name}')

        self.close()


# Radial menu slice actions
RADIAL_ACTIONS = [
    ('copy', 'Copy', 'edit-copy-symbolic'),
    ('paste', 'Paste', 'edit-paste-symbolic'),
    ('undo', 'Undo', 'edit-undo-symbolic'),
    ('redo', 'Redo', 'edit-redo-symbolic'),
    ('cut', 'Cut', 'edit-cut-symbolic'),
    ('select_all', 'Select All', 'edit-select-all-symbolic'),
    ('screenshot', 'Screenshot', 'camera-photo-symbolic'),
    ('close_window', 'Close Window', 'window-close-symbolic'),
    ('minimize', 'Minimize', 'window-minimize-symbolic'),
    ('maximize', 'Maximize', 'window-maximize-symbolic'),
    ('volume_up', 'Volume Up', 'audio-volume-high-symbolic'),
    ('volume_down', 'Volume Down', 'audio-volume-low-symbolic'),
    ('mute', 'Mute', 'audio-volume-muted-symbolic'),
    ('play_pause', 'Play/Pause', 'media-playback-start-symbolic'),
    ('next_track', 'Next Track', 'media-skip-forward-symbolic'),
    ('prev_track', 'Previous Track', 'media-skip-backward-symbolic'),
    ('zoom_in', 'Zoom In', 'zoom-in-symbolic'),
    ('zoom_out', 'Zoom Out', 'zoom-out-symbolic'),
    ('new_tab', 'New Tab', 'tab-new-symbolic'),
    ('close_tab', 'Close Tab', 'window-close-symbolic'),
    ('refresh', 'Refresh', 'view-refresh-symbolic'),
    ('home', 'Home', 'go-home-symbolic'),
    ('back', 'Back', 'go-previous-symbolic'),
    ('forward', 'Forward', 'go-next-symbolic'),
    ('none', 'Do Nothing', 'action-unavailable-symbolic'),
]


class RadialMenuConfigDialog(Adw.Window):
    """Dialog for configuring the radial menu slices"""

    def __init__(self, parent):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title('Configure Radial Menu')
        self.set_default_size(600, 700)

        # Load current profile
        self.profile = self._load_profile()

        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label='Save')
        save_btn.add_css_class('suggested-action')
        save_btn.connect('clicked', self._on_save)
        header.pack_end(save_btn)

        main_box.append(header)

        # Scrollable content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Description
        desc = Gtk.Label(label='Configure the 8 actions in your radial menu. Click on a slice to change its action.')
        desc.set_wrap(True)
        desc.set_margin_bottom(16)
        content.append(desc)

        # Slice configuration list
        self.slice_dropdowns = {}

        for i in range(8):
            slice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            slice_box.add_css_class('setting-row')

            # Slice number and current action
            slice_label = Gtk.Label(label=f'Slice {i + 1}')
            slice_label.set_width_chars(8)
            slice_label.set_xalign(0)
            slice_box.append(slice_label)

            # Get current slice config
            current_slice = self.profile.get('slices', [{}] * 8)[i] if i < len(self.profile.get('slices', [])) else {}
            current_action = current_slice.get('action_id', 'none')

            # Action dropdown
            dropdown = Gtk.DropDown()
            action_names = [name for _, name, _ in RADIAL_ACTIONS]
            dropdown.set_model(Gtk.StringList.new(action_names))

            # Find current action index
            action_ids = [aid for aid, _, _ in RADIAL_ACTIONS]
            if current_action in action_ids:
                dropdown.set_selected(action_ids.index(current_action))

            dropdown.set_hexpand(True)
            self.slice_dropdowns[i] = dropdown
            slice_box.append(dropdown)

            content.append(slice_box)

        scrolled.set_child(content)
        main_box.append(scrolled)

        self.set_content(main_box)

    def _load_profile(self):
        """Load the current radial menu profile"""
        profile_path = Path.home() / '.config' / 'juhradial' / 'profiles.json'
        try:
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                    # Return the default profile
                    return profiles.get('default', {})
        except Exception as e:
            print(f"Failed to load profile: {e}")
        return {}

    def _on_save(self, _):
        """Save the radial menu configuration"""
        profile_path = Path.home() / '.config' / 'juhradial' / 'profiles.json'

        # Build new slices config
        slices = []
        for i in range(8):
            dropdown = self.slice_dropdowns[i]
            selected = dropdown.get_selected()
            if 0 <= selected < len(RADIAL_ACTIONS):
                action_id, action_name, icon = RADIAL_ACTIONS[selected]
                slices.append({
                    'action_id': action_id,
                    'label': action_name,
                    'icon': icon,
                })

        # Load existing profiles and update
        try:
            profiles = {}
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)

            if 'default' not in profiles:
                profiles['default'] = {}

            profiles['default']['slices'] = slices

            # Save
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, indent=2)

            print("Radial menu configuration saved!")

            # Notify daemon to reload
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    'org.kde.juhradialmx',
                    '/org/kde/juhradialmx/Daemon',
                    'org.kde.juhradialmx.Daemon',
                    None
                )
                proxy.call_sync('ReloadConfig', None, Gio.DBusCallFlags.NONE, 500, None)
            except Exception:
                pass

        except Exception as e:
            print(f"Failed to save profile: {e}")

        self.close()


class ButtonsPage(Gtk.ScrolledWindow):
    """Buttons configuration page - Premium UI Design"""

    # Icon mapping for each button type
    BUTTON_ICONS = {
        'middle': 'input-mouse-symbolic',
        'shift_wheel': 'media-playlist-shuffle-symbolic',
        'forward': 'go-next-symbolic',
        'horizontal_scroll': 'object-flip-horizontal-symbolic',
        'back': 'go-previous-symbolic',
        'gesture': 'input-touchpad-symbolic',
        'thumb': 'view-app-grid-symbolic',
    }

    # Color hex values for slice indicators
    SLICE_COLORS = {
        'green': '#00e676',
        'yellow': '#ffd54f',
        'red': '#ff5252',
        'mauve': '#b388ff',
        'blue': '#4a9eff',
        'pink': '#ff80ab',
        'sapphire': '#00b4d8',
        'teal': '#0abdc6',
    }

    def __init__(self, on_button_config=None, parent_window=None, config_manager=None):
        super().__init__()
        self.on_button_config = on_button_config
        self.parent_window = parent_window
        self.config_manager = config_manager
        self.slice_rows = {}  # Store slice row widgets for updating
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        # =============================================
        # ACTIONS RING CARD - Shows all 8 slices
        # =============================================
        radial_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        radial_card.add_css_class('radial-menu-card')

        # Header row
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header_row.set_margin_bottom(12)

        # Large radial icon
        radial_icon_box = Gtk.Box()
        radial_icon_box.add_css_class('radial-icon-large')
        radial_icon_box.set_valign(Gtk.Align.CENTER)
        radial_icon = Gtk.Image.new_from_icon_name('view-app-grid-symbolic')
        radial_icon.set_pixel_size(28)
        radial_icon_box.append(radial_icon)
        header_row.append(radial_icon_box)

        # Text content
        radial_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        radial_text.set_hexpand(True)
        radial_text.set_valign(Gtk.Align.CENTER)

        radial_title = Gtk.Label(label='Actions Ring')
        radial_title.set_halign(Gtk.Align.START)
        radial_title.add_css_class('radial-title')
        radial_text.append(radial_title)

        radial_subtitle = Gtk.Label(label='Click any action to customize')
        radial_subtitle.set_halign(Gtk.Align.START)
        radial_subtitle.add_css_class('radial-subtitle')
        radial_text.append(radial_subtitle)

        header_row.append(radial_text)
        radial_card.append(header_row)

        # Slices container - 2 columns of 4 slices
        slices_grid = Gtk.Grid()
        slices_grid.set_column_spacing(12)
        slices_grid.set_row_spacing(8)
        slices_grid.set_column_homogeneous(True)

        # Load current slices from config
        slices = self._get_current_slices()

        # Position labels (clockwise from top)
        position_labels = ['Top', 'Top Right', 'Right', 'Bottom Right', 'Bottom', 'Bottom Left', 'Left', 'Top Left']

        for i, slice_data in enumerate(slices):
            row = i % 4
            col = i // 4
            slice_widget = self._create_slice_row(i, slice_data, position_labels[i])
            self.slice_rows[i] = slice_widget
            slices_grid.attach(slice_widget, col, row, 1, 1)

        radial_card.append(slices_grid)
        content.append(radial_card)

        # =============================================
        # BUTTON ASSIGNMENTS CARD
        # =============================================
        assignments_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        assignments_card.add_css_class('button-assignment-card')

        # Card header
        header = Gtk.Label(label='Button Assignments')
        header.set_halign(Gtk.Align.START)
        header.add_css_class('button-assignment-header')
        assignments_card.append(header)

        # Button rows container
        self.button_rows = {}
        self.action_labels = {}

        for btn_id, btn_info in MOUSE_BUTTONS.items():
            row = self._create_button_row(btn_id, btn_info)
            self.button_rows[btn_id] = row
            assignments_card.append(row)

        content.append(assignments_card)
        self.set_child(content)

    def _create_button_row(self, btn_id, btn_info):
        """Create a premium styled button assignment row"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.add_css_class('button-row')

        # Icon box
        icon_box = Gtk.Box()
        icon_box.add_css_class('button-icon-box')
        icon_box.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name(self.BUTTON_ICONS.get(btn_id, 'input-mouse-symbolic'))
        icon.set_pixel_size(20)
        icon.add_css_class('button-icon')
        icon_box.append(icon)
        row.append(icon_box)

        # Text content
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        name_label = Gtk.Label(label=btn_info['name'])
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class('button-name')
        text_box.append(name_label)

        # Action badge
        action_label = Gtk.Label(label=btn_info['action'])
        action_label.set_halign(Gtk.Align.START)
        action_label.add_css_class('button-action')
        text_box.append(action_label)
        self.action_labels[btn_id] = action_label

        row.append(text_box)

        # Arrow button
        arrow = Gtk.Button()
        arrow.set_child(Gtk.Image.new_from_icon_name('go-next-symbolic'))
        arrow.add_css_class('button-arrow')
        arrow.add_css_class('flat')
        arrow.set_valign(Gtk.Align.CENTER)
        arrow.connect('clicked', lambda _, bid=btn_id: self._on_button_click(bid))
        row.append(arrow)

        # Make entire row clickable
        row_click = Gtk.GestureClick()
        row_click.connect('released', lambda g, n, x, y, bid=btn_id: self._on_button_click(bid))
        row.add_controller(row_click)

        return row

    def _on_button_click(self, button_id):
        """Handle button configuration click"""
        if self.on_button_config:
            self.on_button_config(button_id)

    def _on_configure_radial(self):
        """Open radial menu configuration"""
        if self.parent_window:
            dialog = RadialMenuConfigDialog(self.parent_window)
            dialog.present()

    def refresh_button_labels(self):
        """Refresh the button action labels after config change"""
        for btn_id, action_label in self.action_labels.items():
            if btn_id in MOUSE_BUTTONS:
                action_label.set_text(MOUSE_BUTTONS[btn_id]['action'])

    def _get_current_slices(self):
        """Get the current radial menu slices from config"""
        if self.config_manager:
            slices = self.config_manager.get('radial_menu.slices', default=[])
            if slices:
                return slices
        # Return defaults if no config
        return ConfigManager.DEFAULT_CONFIG['radial_menu']['slices']

    def _create_slice_row(self, index, slice_data, position_label):
        """Create a compact slice row widget"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class('slice-row')

        # Color indicator dot
        color_name = slice_data.get('color', 'teal')
        color_hex = self.SLICE_COLORS.get(color_name, '#0abdc6')

        color_dot = Gtk.DrawingArea()
        color_dot.set_size_request(10, 10)
        color_dot.set_valign(Gtk.Align.CENTER)

        def draw_dot(area, cr, width, height):
            # Parse color
            r = int(color_hex[1:3], 16) / 255.0
            g = int(color_hex[3:5], 16) / 255.0
            b = int(color_hex[5:7], 16) / 255.0
            # Draw filled circle
            cr.set_source_rgb(r, g, b)
            cr.arc(width / 2, height / 2, 4, 0, 2 * 3.14159)
            cr.fill()

        color_dot.set_draw_func(draw_dot)
        row.append(color_dot)

        # Icon
        icon_name = slice_data.get('icon', 'application-x-executable-symbolic')
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        icon.add_css_class('slice-icon')
        row.append(icon)

        # Label
        label = Gtk.Label(label=slice_data.get('label', f'Slice {index + 1}'))
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.add_css_class('slice-label')
        label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(label)

        # Edit button (arrow)
        edit_btn = Gtk.Button()
        edit_btn.set_child(Gtk.Image.new_from_icon_name('go-next-symbolic'))
        edit_btn.add_css_class('slice-edit-btn')
        edit_btn.add_css_class('flat')
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.connect('clicked', lambda _, idx=index: self._on_edit_slice(idx))
        row.append(edit_btn)

        # Make entire row clickable
        row_click = Gtk.GestureClick()
        row_click.connect('released', lambda g, n, x, y, idx=index: self._on_edit_slice(idx))
        row.add_controller(row_click)

        return row

    def _on_edit_slice(self, slice_index):
        """Open dialog to edit a specific slice"""
        if self.parent_window:
            dialog = SliceConfigDialog(self.parent_window, slice_index, self.config_manager, self._on_slice_saved)
            dialog.present()

    def _on_slice_saved(self):
        """Called when a slice is saved - refresh the UI"""
        # Refresh slices display
        slices = self._get_current_slices()
        position_labels = ['Top', 'Top Right', 'Right', 'Bottom Right', 'Bottom', 'Bottom Left', 'Left', 'Top Left']

        for i, slice_data in enumerate(slices):
            if i in self.slice_rows:
                # Update the existing row's content
                row = self.slice_rows[i]
                # Find and update the label
                for child in row:
                    if isinstance(child, Gtk.Label):
                        child.set_text(slice_data.get('label', f'Slice {i + 1}'))
                        break


class SliceConfigDialog(Adw.Window):
    """Dialog for configuring a single radial menu slice"""

    # Available action types
    ACTION_TYPES = [
        ('exec', 'Run Command', 'Execute a shell command'),
        ('url', 'Open URL', 'Open a web address'),
        ('settings', 'Open Settings', 'Open JuhRadial settings'),
        ('emoji', 'Emoji Picker', 'Show emoji picker'),
        ('submenu', 'Submenu', 'Show a submenu with more options'),
    ]

    # Preset actions for quick selection
    PRESET_ACTIONS = [
        ('Play/Pause', 'exec', 'playerctl play-pause', 'green', 'media-playback-start-symbolic'),
        ('Next Track', 'exec', 'playerctl next', 'green', 'media-skip-forward-symbolic'),
        ('Previous Track', 'exec', 'playerctl previous', 'green', 'media-skip-backward-symbolic'),
        ('Volume Up', 'exec', 'pactl set-sink-volume @DEFAULT_SINK@ +5%', 'blue', 'audio-volume-high-symbolic'),
        ('Volume Down', 'exec', 'pactl set-sink-volume @DEFAULT_SINK@ -5%', 'blue', 'audio-volume-low-symbolic'),
        ('Mute', 'exec', 'pactl set-sink-mute @DEFAULT_SINK@ toggle', 'blue', 'audio-volume-muted-symbolic'),
        ('Screenshot', 'exec', 'spectacle', 'blue', 'camera-photo-symbolic'),
        ('Screenshot Area', 'exec', 'spectacle -r', 'blue', 'camera-photo-symbolic'),
        ('Lock Screen', 'exec', 'loginctl lock-session', 'red', 'system-lock-screen-symbolic'),
        ('Files', 'exec', 'dolphin', 'sapphire', 'folder-symbolic'),
        ('Terminal', 'exec', 'konsole', 'teal', 'utilities-terminal-symbolic'),
        ('Browser', 'exec', 'xdg-open https://', 'blue', 'web-browser-symbolic'),
        ('New Note', 'exec', 'kwrite', 'yellow', 'document-new-symbolic'),
        ('Calculator', 'exec', 'kcalc', 'mauve', 'accessories-calculator-symbolic'),
        ('Settings', 'settings', '', 'mauve', 'emblem-system-symbolic'),
        ('Emoji Picker', 'emoji', '', 'pink', 'face-smile-symbolic'),
    ]

    # Available colors
    COLORS = ['green', 'yellow', 'red', 'mauve', 'blue', 'pink', 'sapphire', 'teal']

    def __init__(self, parent, slice_index, config_manager, on_save_callback=None):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(f'Configure Slice {slice_index + 1}')
        self.set_default_size(500, 600)

        self.slice_index = slice_index
        self.config_manager = config_manager
        self.on_save_callback = on_save_callback

        # Load current slice data
        slices = config_manager.get('radial_menu.slices', default=[])
        if slice_index < len(slices):
            self.slice_data = slices[slice_index].copy()
        else:
            self.slice_data = ConfigManager.DEFAULT_CONFIG['radial_menu']['slices'][slice_index].copy()

        self._build_ui()

    def _build_ui(self):
        """Build the dialog UI"""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label='Save')
        save_btn.add_css_class('suggested-action')
        save_btn.connect('clicked', self._on_save)
        header.pack_end(save_btn)

        main_box.append(header)

        # Scrollable content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # ===============================
        # PRESET ACTIONS SECTION
        # ===============================
        preset_label = Gtk.Label(label='Quick Actions')
        preset_label.set_halign(Gtk.Align.START)
        preset_label.add_css_class('heading')
        content.append(preset_label)

        preset_flow = Gtk.FlowBox()
        preset_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        preset_flow.set_max_children_per_line(3)
        preset_flow.set_min_children_per_line(2)
        preset_flow.set_column_spacing(8)
        preset_flow.set_row_spacing(8)

        for label, action_type, command, color, icon in self.PRESET_ACTIONS:
            btn = Gtk.Button()
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            btn_icon = Gtk.Image.new_from_icon_name(icon)
            btn_icon.set_pixel_size(14)
            btn_box.append(btn_icon)
            btn_label = Gtk.Label(label=label)
            btn_label.set_ellipsize(Pango.EllipsizeMode.END)
            btn_box.append(btn_label)
            btn.set_child(btn_box)
            btn.add_css_class('preset-btn')
            btn.connect('clicked', lambda _, l=label, t=action_type, c=command, co=color, ic=icon:
                        self._apply_preset(l, t, c, co, ic))
            preset_flow.append(btn)

        content.append(preset_flow)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        content.append(sep)

        # ===============================
        # CUSTOM CONFIGURATION
        # ===============================
        custom_label = Gtk.Label(label='Custom Configuration')
        custom_label.set_halign(Gtk.Align.START)
        custom_label.add_css_class('heading')
        content.append(custom_label)

        # Label entry
        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label_title = Gtk.Label(label='Label')
        label_title.set_halign(Gtk.Align.START)
        label_title.add_css_class('dim-label')
        label_box.append(label_title)

        self.label_entry = Gtk.Entry()
        self.label_entry.set_text(self.slice_data.get('label', ''))
        self.label_entry.set_placeholder_text('Enter action label')
        label_box.append(self.label_entry)
        content.append(label_box)

        # Action type dropdown
        type_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        type_title = Gtk.Label(label='Action Type')
        type_title.set_halign(Gtk.Align.START)
        type_title.add_css_class('dim-label')
        type_box.append(type_title)

        self.type_dropdown = Gtk.DropDown()
        type_names = [name for _, name, _ in self.ACTION_TYPES]
        self.type_dropdown.set_model(Gtk.StringList.new(type_names))

        # Set current type
        current_type = self.slice_data.get('type', 'exec')
        type_ids = [tid for tid, _, _ in self.ACTION_TYPES]
        if current_type in type_ids:
            self.type_dropdown.set_selected(type_ids.index(current_type))

        self.type_dropdown.connect('notify::selected', self._on_type_changed)
        type_box.append(self.type_dropdown)
        content.append(type_box)

        # Command entry
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.cmd_title = Gtk.Label(label='Command')
        self.cmd_title.set_halign(Gtk.Align.START)
        self.cmd_title.add_css_class('dim-label')
        cmd_box.append(self.cmd_title)

        self.command_entry = Gtk.Entry()
        self.command_entry.set_text(self.slice_data.get('command', ''))
        self.command_entry.set_placeholder_text('e.g., playerctl play-pause')
        cmd_box.append(self.command_entry)
        self.cmd_box = cmd_box
        content.append(cmd_box)

        # Color picker
        color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        color_title = Gtk.Label(label='Color')
        color_title.set_halign(Gtk.Align.START)
        color_title.add_css_class('dim-label')
        color_box.append(color_title)

        color_flow = Gtk.FlowBox()
        color_flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        color_flow.set_max_children_per_line(8)
        color_flow.set_min_children_per_line(8)
        color_flow.set_column_spacing(8)

        self.color_buttons = {}
        current_color = self.slice_data.get('color', 'teal')

        for color in self.COLORS:
            btn = Gtk.ToggleButton()
            btn.set_size_request(32, 32)
            btn.add_css_class(f'color-btn-{color}')
            if color == current_color:
                btn.set_active(True)
            btn.connect('toggled', lambda b, c=color: self._on_color_selected(c, b))
            self.color_buttons[color] = btn
            color_flow.append(btn)

        color_box.append(color_flow)
        content.append(color_box)

        # Icon selector
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        icon_title = Gtk.Label(label='Icon')
        icon_title.set_halign(Gtk.Align.START)
        icon_title.add_css_class('dim-label')
        icon_box.append(icon_title)

        self.icon_entry = Gtk.Entry()
        self.icon_entry.set_text(self.slice_data.get('icon', 'application-x-executable-symbolic'))
        self.icon_entry.set_placeholder_text('Icon name (e.g., folder-symbolic)')
        icon_box.append(self.icon_entry)
        content.append(icon_box)

        scrolled.set_child(content)
        main_box.append(scrolled)
        self.set_content(main_box)

        # Update command visibility based on type
        self._update_command_visibility()

    def _apply_preset(self, label, action_type, command, color, icon):
        """Apply a preset action"""
        self.label_entry.set_text(label)
        self.command_entry.set_text(command)
        self.icon_entry.set_text(icon)

        # Set type dropdown
        type_ids = [tid for tid, _, _ in self.ACTION_TYPES]
        if action_type in type_ids:
            self.type_dropdown.set_selected(type_ids.index(action_type))

        # Set color
        for c, btn in self.color_buttons.items():
            btn.set_active(c == color)

    def _on_type_changed(self, dropdown, _):
        """Handle action type change"""
        self._update_command_visibility()

    def _update_command_visibility(self):
        """Show/hide command entry based on action type"""
        selected = self.type_dropdown.get_selected()
        type_id = self.ACTION_TYPES[selected][0] if selected < len(self.ACTION_TYPES) else 'exec'

        # Command is needed for exec and url types
        needs_command = type_id in ('exec', 'url')
        self.cmd_box.set_visible(needs_command)

        if type_id == 'url':
            self.cmd_title.set_text('URL')
            self.command_entry.set_placeholder_text('e.g., https://claude.ai')
        else:
            self.cmd_title.set_text('Command')
            self.command_entry.set_placeholder_text('e.g., playerctl play-pause')

    def _on_color_selected(self, color, button):
        """Handle color selection - ensure only one is selected"""
        if button.get_active():
            for c, btn in self.color_buttons.items():
                if c != color and btn.get_active():
                    btn.set_active(False)

    def _on_save(self, button):
        """Save the slice configuration"""
        # Get selected type
        selected_type = self.type_dropdown.get_selected()
        type_id = self.ACTION_TYPES[selected_type][0] if selected_type < len(self.ACTION_TYPES) else 'exec'

        # Get selected color
        selected_color = 'teal'
        for color, btn in self.color_buttons.items():
            if btn.get_active():
                selected_color = color
                break

        # Build slice data
        new_slice = {
            'label': self.label_entry.get_text() or f'Slice {self.slice_index + 1}',
            'type': type_id,
            'command': self.command_entry.get_text(),
            'color': selected_color,
            'icon': self.icon_entry.get_text() or 'application-x-executable-symbolic',
        }

        # Update config
        slices = self.config_manager.get('radial_menu.slices', default=[])

        # Ensure we have 8 slices
        while len(slices) < 8:
            slices.append(ConfigManager.DEFAULT_CONFIG['radial_menu']['slices'][len(slices)])

        slices[self.slice_index] = new_slice
        self.config_manager.set('radial_menu.slices', slices)
        self.config_manager.save()

        # Call callback to refresh UI
        if self.on_save_callback:
            self.on_save_callback()

        self.close()


class DPIVisualSlider(Gtk.Box):
    """Visual DPI slider with gradient bar and value display"""

    def __init__(self, on_change=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.on_change = on_change

        # Header with title and DPI value
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label='Pointer Speed')
        title.set_halign(Gtk.Align.START)
        title.add_css_class('heading')
        subtitle = Gtk.Label(label='Adjust tracking sensitivity')
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class('dim-label')
        title_box.append(title)
        title_box.append(subtitle)
        header.append(title_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        # DPI value display
        self.dpi_label = Gtk.Label()
        self.dpi_label.add_css_class('title-1')
        self.dpi_label.set_markup(f'<span size="xx-large" weight="bold" color="{COLORS["mauve"]}">1600</span>')
        dpi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        dpi_box.append(self.dpi_label)
        dpi_unit = Gtk.Label(label='DPI')
        dpi_unit.add_css_class('dim-label')
        dpi_box.append(dpi_unit)
        header.append(dpi_box)

        self.append(header)

        # Slider with gradient track
        slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        slow_label = Gtk.Label(label='Slow')
        slow_label.add_css_class('dim-label')
        slider_box.append(slow_label)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 400, 8000, 100)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(300, -1)
        self.scale.connect('value-changed', self._on_value_changed)
        slider_box.append(self.scale)

        fast_label = Gtk.Label(label='Fast')
        fast_label.add_css_class('dim-label')
        slider_box.append(fast_label)

        self.append(slider_box)

        # Preset buttons
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preset_box.set_halign(Gtk.Align.CENTER)
        preset_box.set_margin_top(8)

        for dpi in [800, 1600, 3200, 4000]:
            btn = Gtk.Button(label=str(dpi))
            btn.add_css_class('flat')
            btn.connect('clicked', lambda b, d=dpi: self.set_dpi(d))
            preset_box.append(btn)

        self.append(preset_box)

    def set_dpi(self, dpi):
        self.scale.set_value(dpi)

    def get_dpi(self):
        return int(self.scale.get_value())

    def _on_value_changed(self, scale):
        dpi = int(scale.get_value())
        self.dpi_label.set_markup(f'<span size="xx-large" weight="bold" color="{COLORS["mauve"]}">{dpi}</span>')
        if self.on_change:
            self.on_change(dpi)


class ScrollWheelVisual(Gtk.DrawingArea):
    """Visual representation of scroll wheel mode"""

    def __init__(self, is_smartshift=True):
        super().__init__()
        self.is_smartshift = is_smartshift
        self.set_content_width(60)
        self.set_content_height(60)
        self.set_draw_func(self._draw)

    def set_smartshift(self, enabled):
        self.is_smartshift = enabled
        self.queue_draw()

    def _draw(self, area, cr, width, height):
        # Draw scroll wheel icon
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 4

        # Outer circle
        cr.set_source_rgba(*self._hex_to_rgba(COLORS['surface1']))
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()

        # Inner wheel pattern
        color = COLORS['mauve'] if self.is_smartshift else COLORS['subtext0']
        cr.set_source_rgba(*self._hex_to_rgba(color))

        # Draw ridges
        for i in range(8):
            angle = i * math.pi / 4
            x1 = cx + (radius - 8) * math.cos(angle)
            y1 = cy + (radius - 8) * math.sin(angle)
            x2 = cx + (radius - 2) * math.cos(angle)
            y2 = cy + (radius - 2) * math.sin(angle)
            cr.set_line_width(2)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        # Center dot
        cr.arc(cx, cy, 4, 0, 2 * math.pi)
        cr.fill()

    def _hex_to_rgba(self, hex_color):
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16) / 255
        g = int(hex_color[2:4], 16) / 255
        b = int(hex_color[4:6], 16) / 255
        return (r, g, b, 1.0)


class ScrollPage(Gtk.ScrolledWindow):
    """Point, Scroll, Press settings page - Logi Options+ inspired design"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(32)
        content.set_margin_end(32)

        # ═══════════════════════════════════════════════════════════════
        # POINTER SPEED SECTION
        # ═══════════════════════════════════════════════════════════════
        pointer_card = SettingsCard('Pointer')

        # DPI Visual Slider
        self.dpi_slider = DPIVisualSlider(on_change=self._on_dpi_changed)
        # Convert saved speed (1-20) to DPI (400-8000)
        saved_speed = config.get('pointer', 'speed', default=10)
        initial_dpi = 400 + (saved_speed - 1) * 400
        self.dpi_slider.set_dpi(min(initial_dpi, 8000))
        pointer_card.append(self.dpi_slider)

        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep1.set_margin_top(16)
        sep1.set_margin_bottom(16)
        pointer_card.append(sep1)

        # Acceleration profile
        accel_row = SettingRow('Acceleration Profile', 'How pointer speed scales with movement')
        accel_combo = Gtk.ComboBoxText()
        accel_combo.append('adaptive', 'Adaptive (Recommended)')
        accel_combo.append('flat', 'Flat (Linear)')
        accel_combo.append('default', 'System Default')
        current_accel = config.get('pointer', 'accel_profile', default='adaptive')
        accel_combo.set_active_id(current_accel)
        accel_combo.connect('changed', self._on_accel_changed)
        accel_row.set_control(accel_combo)
        pointer_card.append(accel_row)

        content.append(pointer_card)

        # ═══════════════════════════════════════════════════════════════
        # SCROLL WHEEL SECTION
        # ═══════════════════════════════════════════════════════════════
        scroll_card = SettingsCard('Scroll Wheel')

        # SmartShift with visual
        smartshift_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        smartshift_box.set_margin_bottom(8)

        self.scroll_visual = ScrollWheelVisual(config.get('scroll', 'smartshift', default=True))
        smartshift_box.append(self.scroll_visual)

        smartshift_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        smartshift_content.set_hexpand(True)

        smartshift_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        smartshift_title = Gtk.Label(label='SmartShift')
        smartshift_title.set_halign(Gtk.Align.START)
        smartshift_title.add_css_class('heading')
        smartshift_header.append(smartshift_title)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        smartshift_header.append(spacer)

        self.smartshift_switch = Gtk.Switch()
        self.smartshift_switch.set_active(config.get('scroll', 'smartshift', default=True))
        self.smartshift_switch.connect('state-set', self._on_smartshift_changed)
        smartshift_header.append(self.smartshift_switch)

        smartshift_content.append(smartshift_header)

        smartshift_desc = Gtk.Label(label='Automatically switch between ratchet and free-spin modes based on scroll speed')
        smartshift_desc.set_halign(Gtk.Align.START)
        smartshift_desc.set_wrap(True)
        smartshift_desc.set_max_width_chars(50)
        smartshift_desc.add_css_class('dim-label')
        smartshift_content.append(smartshift_desc)

        smartshift_box.append(smartshift_content)
        scroll_card.append(smartshift_box)

        # Threshold slider
        threshold_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        threshold_box.set_margin_start(76)  # Align with text above

        threshold_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        threshold_label = Gtk.Label(label='Sensitivity')
        threshold_label.set_halign(Gtk.Align.START)
        threshold_label_box.append(threshold_label)

        spacer2 = Gtk.Box()
        spacer2.set_hexpand(True)
        threshold_label_box.append(spacer2)

        self.threshold_value = Gtk.Label()
        self.threshold_value.add_css_class('dim-label')
        threshold_label_box.append(self.threshold_value)
        threshold_box.append(threshold_label_box)

        threshold_slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ratchet_label = Gtk.Label(label='Ratchet')
        ratchet_label.add_css_class('dim-label')
        threshold_slider_box.append(ratchet_label)

        self.threshold_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.threshold_scale.set_hexpand(True)
        self.threshold_scale.set_draw_value(False)
        self.threshold_scale.set_value(config.get('scroll', 'smartshift_threshold', default=50))
        self.threshold_scale.connect('value-changed', self._on_threshold_changed)
        self._update_threshold_label(self.threshold_scale.get_value())
        threshold_slider_box.append(self.threshold_scale)

        freespin_label = Gtk.Label(label='Free-spin')
        freespin_label.add_css_class('dim-label')
        threshold_slider_box.append(freespin_label)

        threshold_box.append(threshold_slider_box)
        scroll_card.append(threshold_box)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(16)
        sep2.set_margin_bottom(16)
        scroll_card.append(sep2)

        # Scroll direction
        direction_row = SettingRow('Natural Scrolling', 'Scroll content in the direction of finger movement')
        direction_switch = Gtk.Switch()
        direction_switch.set_active(config.get('scroll', 'natural', default=False))
        direction_switch.connect('state-set', self._on_natural_changed)
        direction_row.set_control(direction_switch)
        scroll_card.append(direction_row)

        # Smooth scrolling
        smooth_row = SettingRow('Smooth Scrolling', 'Enable high-resolution scrolling')
        smooth_switch = Gtk.Switch()
        smooth_switch.set_active(config.get('scroll', 'smooth', default=True))
        smooth_switch.connect('state-set', lambda s, state: config.set('scroll', 'smooth', state) or False)
        smooth_row.set_control(smooth_switch)
        scroll_card.append(smooth_row)

        # Separator before scroll speed
        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep3.set_margin_top(16)
        sep3.set_margin_bottom(16)
        scroll_card.append(sep3)

        # Scroll Speed slider
        scroll_speed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        scroll_speed_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        scroll_speed_label = Gtk.Label(label='Scroll Speed')
        scroll_speed_label.set_halign(Gtk.Align.START)
        scroll_speed_label.add_css_class('heading')
        scroll_speed_label_box.append(scroll_speed_label)

        spacer_speed = Gtk.Box()
        spacer_speed.set_hexpand(True)
        scroll_speed_label_box.append(spacer_speed)

        self.scroll_speed_value = Gtk.Label()
        self.scroll_speed_value.add_css_class('dim-label')
        scroll_speed_label_box.append(self.scroll_speed_value)
        scroll_speed_box.append(scroll_speed_label_box)

        scroll_speed_desc = Gtk.Label(label='Control scroll wheel resolution (fewer events = slower scrolling)')
        scroll_speed_desc.set_halign(Gtk.Align.START)
        scroll_speed_desc.set_wrap(True)
        scroll_speed_desc.set_max_width_chars(50)
        scroll_speed_desc.add_css_class('dim-label')
        scroll_speed_box.append(scroll_speed_desc)

        scroll_speed_slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        slow_label = Gtk.Label(label='Slow')
        slow_label.add_css_class('dim-label')
        scroll_speed_slider_box.append(slow_label)

        # Slider from 10 to 200 (percentage), default 100 (normal)
        self.scroll_speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 200, 5)
        self.scroll_speed_scale.set_hexpand(True)
        self.scroll_speed_scale.set_draw_value(False)
        self.scroll_speed_scale.set_value(config.get('scroll', 'speed', default=100))
        self.scroll_speed_scale.add_mark(100, Gtk.PositionType.BOTTOM, None)  # Mark at 100% (normal)
        self.scroll_speed_scale.connect('value-changed', self._on_scroll_speed_changed)
        self._update_scroll_speed_label(self.scroll_speed_scale.get_value())
        scroll_speed_slider_box.append(self.scroll_speed_scale)

        fast_label = Gtk.Label(label='Fast')
        fast_label.add_css_class('dim-label')
        scroll_speed_slider_box.append(fast_label)

        scroll_speed_box.append(scroll_speed_slider_box)
        scroll_card.append(scroll_speed_box)

        content.append(scroll_card)

        # ═══════════════════════════════════════════════════════════════
        # THUMB WHEEL SECTION
        # ═══════════════════════════════════════════════════════════════
        thumb_card = SettingsCard('Thumb Wheel')

        thumb_speed_row = SettingRow('Scroll Speed', 'Horizontal scroll sensitivity')
        thumb_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        thumb_scale.set_value(config.get('thumbwheel', 'speed', default=5))
        thumb_scale.set_size_request(200, -1)
        thumb_scale.set_draw_value(False)
        thumb_scale.connect('value-changed', lambda s: config.set('thumbwheel', 'speed', int(s.get_value())))
        thumb_speed_row.set_control(thumb_scale)
        thumb_card.append(thumb_speed_row)

        thumb_invert_row = SettingRow('Invert Direction', 'Reverse thumb wheel scroll direction')
        thumb_invert = Gtk.Switch()
        thumb_invert.set_active(config.get('thumbwheel', 'invert', default=False))
        thumb_invert.connect('state-set', lambda s, state: config.set('thumbwheel', 'invert', state) or False)
        thumb_invert_row.set_control(thumb_invert)
        thumb_card.append(thumb_invert_row)

        content.append(thumb_card)

        # ═══════════════════════════════════════════════════════════════
        # APPLY SECTION
        # ═══════════════════════════════════════════════════════════════
        apply_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        apply_card.add_css_class('card')
        apply_card.set_margin_top(8)

        # Status indicator
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.status_box.set_halign(Gtk.Align.CENTER)

        self.status_icon = Gtk.Image.new_from_icon_name('emblem-ok-symbolic')
        self.status_box.append(self.status_icon)

        self.status_label = Gtk.Label(label='Settings saved automatically')
        self.status_label.add_css_class('dim-label')
        self.status_box.append(self.status_label)

        apply_card.append(self.status_box)

        # Apply button
        apply_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        apply_btn_box.set_halign(Gtk.Align.CENTER)

        apply_btn = Gtk.Button()
        apply_btn.add_css_class('suggested-action')
        apply_btn.set_size_request(220, 40)

        apply_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_content.set_halign(Gtk.Align.CENTER)
        apply_icon = Gtk.Image.new_from_icon_name('emblem-synchronizing-symbolic')
        apply_content.append(apply_icon)
        apply_label = Gtk.Label(label='Apply to Device')
        apply_content.append(apply_label)
        apply_btn.set_child(apply_content)
        apply_btn.connect('clicked', self._on_apply_clicked)

        apply_btn_box.append(apply_btn)
        apply_card.append(apply_btn_box)

        # Note
        note = Gtk.Label()
        note.set_markup(f'<span size="small" color="{COLORS["subtext0"]}">Applies DPI, SmartShift, and scroll settings via logiops (requires sudo)</span>')
        note.set_halign(Gtk.Align.CENTER)
        apply_card.append(note)

        content.append(apply_card)

        self.set_child(content)

    def _on_dpi_changed(self, dpi):
        # Convert DPI to speed (1-20) for config
        speed = max(1, min(20, (dpi - 400) // 400 + 1))
        config.set('pointer', 'speed', speed)
        config.set('pointer', 'dpi', dpi)
        # Apply to hardware via D-Bus
        self._apply_dpi_to_device(dpi)
        # Also apply pointer speed via gsettings (software multiplier)
        self._apply_pointer_speed(dpi)

    def _on_accel_changed(self, combo):
        profile = combo.get_active_id()
        config.set('pointer', 'accel_profile', profile)
        # Apply immediately
        try:
            import subprocess
            subprocess.run(['gsettings', 'set', 'org.gnome.desktop.peripherals.mouse',
                           'accel-profile', profile], capture_output=True)
        except Exception:
            pass

    def _on_smartshift_changed(self, switch, state):
        config.set('scroll', 'smartshift', state)
        self.scroll_visual.set_smartshift(state)
        self.threshold_scale.set_sensitive(state)
        return False

    def _on_threshold_changed(self, scale):
        value = int(scale.get_value())
        config.set('scroll', 'smartshift_threshold', value)
        self._update_threshold_label(value)

    def _update_threshold_label(self, value):
        self.threshold_value.set_text(f'{int(value)}%')

    def _on_natural_changed(self, switch, state):
        config.set('scroll', 'natural', state)
        # Apply immediately via gsettings
        try:
            import subprocess
            subprocess.run(['gsettings', 'set', 'org.gnome.desktop.peripherals.mouse',
                           'natural-scroll', 'true' if state else 'false'], capture_output=True)
        except Exception:
            pass
        return False

    def _on_scroll_speed_changed(self, scale):
        """Handle scroll speed slider change

        Uses Solaar to control MX Master 4 scroll speed via HID++:
        - hires-smooth-resolution: On = fast (many events), Off = slow (fewer events)
        - Slider maps: 10-50% = slow (hires off), 51-200% = fast (hires on)
        """
        value = int(scale.get_value())
        config.set('scroll', 'speed', value)
        self._update_scroll_speed_label(value)
        # Apply via Solaar HID++ command
        self._apply_scroll_speed_solaar(value)

    def _update_scroll_speed_label(self, value):
        """Update the scroll speed percentage label"""
        if value <= 50:
            self.scroll_speed_value.set_text(f'{int(value)}% (Slow)')
        else:
            self.scroll_speed_value.set_text(f'{int(value)}% (Fast)')

    def _apply_scroll_speed_solaar(self, speed_percent):
        """Apply scroll speed to MX Master 4 via Solaar HID++ commands

        Controls the hires-smooth-resolution setting:
        - True (on): High-resolution mode, many scroll events = fast scrolling
        - False (off): Low-resolution mode, fewer scroll events = slow scrolling

        Slider mapping:
        - 10-50%: hires-smooth-resolution = false (slow)
        - 51-200%: hires-smooth-resolution = true (fast/normal)
        """
        import subprocess
        import shutil

        # Check if solaar is available (used for HID++ communication)
        solaar_path = shutil.which('solaar')
        if not solaar_path:
            print("solaar not found - cannot control scroll speed")
            if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                self.status_icon.set_from_icon_name('dialog-warning-symbolic')
                self.status_label.set_text('Install solaar package')
                GLib.timeout_add(3000, self._reset_status)
            return

        try:
            # Determine hires mode based on slider position
            # 50% or below = slow (hires off), above 50% = fast (hires on)
            hires_enabled = speed_percent > 50
            hires_value = 'true' if hires_enabled else 'false'

            # Apply via Solaar
            result = subprocess.run(
                [solaar_path, 'config', 'MX Master 4', 'hires-smooth-resolution', hires_value],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                mode = 'Fast (HiRes)' if hires_enabled else 'Slow (Standard)'
                print(f"Applied scroll speed: {mode}")
                if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                    self.status_icon.set_from_icon_name('emblem-ok-symbolic')
                    self.status_label.set_text(f'Scroll: {mode}')
                    GLib.timeout_add(2000, self._reset_status)
            else:
                print(f"Solaar error: {result.stderr}")
                # Try alternative device name
                result2 = subprocess.run(
                    [solaar_path, 'config', 'MX Master 4', 'hires-smooth-resolution', hires_value],
                    capture_output=True, text=True, timeout=10
                )
                if result2.returncode != 0:
                    if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                        self.status_icon.set_from_icon_name('dialog-warning-symbolic')
                        self.status_label.set_text('Mouse not found')
                        GLib.timeout_add(3000, self._reset_status)

        except subprocess.TimeoutExpired:
            print("Solaar command timed out")
        except Exception as e:
            print(f"Failed to apply scroll speed: {e}")

    def _apply_pointer_speed(self, dpi):
        """Apply pointer speed via gsettings (-1.0 to 1.0)"""
        try:
            import subprocess
            # Convert DPI (400-8000) to gsettings speed (-1.0 to 1.0)
            speed = (dpi - 4200) / 3800  # Maps 400->-1.0, 8000->1.0
            speed = max(-1.0, min(1.0, speed))
            subprocess.run(['gsettings', 'set', 'org.gnome.desktop.peripherals.mouse',
                           'speed', str(speed)], capture_output=True)
        except Exception:
            pass

    def _apply_dpi_to_device(self, dpi):
        """Apply DPI directly to the mouse via D-Bus"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                'org.kde.juhradialmx',
                '/org/kde/juhradialmx/Daemon',
                'org.kde.juhradialmx.Daemon',
                None
            )
            # Call SetDpi with the DPI value
            proxy.call_sync('SetDpi', GLib.Variant('(q)', (dpi,)), Gio.DBusCallFlags.NONE, 2000, None)
            # Update status to show DPI was applied
            if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                self.status_icon.set_from_icon_name('emblem-ok-symbolic')
                self.status_label.set_text(f'DPI set to {dpi}')
                GLib.timeout_add(2000, self._reset_status)
        except GLib.Error as e:
            print(f"D-Bus error setting DPI: {e.message}")
            if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                self.status_icon.set_from_icon_name('dialog-warning-symbolic')
                self.status_label.set_text(f'DPI error: daemon not running?')
                GLib.timeout_add(3000, self._reset_status)
        except Exception as e:
            print(f"Failed to set DPI via D-Bus: {e}")

    def _on_apply_clicked(self, button):
        """Apply all settings via logiops"""
        config.apply_to_device()
        # Update status
        self.status_icon.set_from_icon_name('emblem-ok-symbolic')
        self.status_label.set_text('Settings applied!')
        # Reset after delay
        GLib.timeout_add(3000, self._reset_status)

    def _reset_status(self):
        self.status_label.set_text('Settings saved automatically')
        return False


class HapticsPage(Gtk.ScrolledWindow):
    """Haptic feedback settings page - MX Master 4 haptic patterns"""

    # MX Master 4 haptic waveform patterns (from Logitech HID++ spec)
    HAPTIC_PATTERNS = [
        ('sharp_state_change', 'Sharp Click', 'Crisp, sharp feedback'),
        ('damp_state_change', 'Soft Click', 'Softer, dampened feedback'),
        ('sharp_collision', 'Sharp Bump', 'Strong collision feedback'),
        ('damp_collision', 'Soft Bump', 'Gentle collision feedback'),
        ('subtle_collision', 'Subtle', 'Very light, subtle feedback'),
        ('whisper_collision', 'Whisper', 'Barely perceptible feedback'),
        ('happy_alert', 'Happy', 'Positive notification feel'),
        ('angry_alert', 'Alert', 'Warning/error feel'),
        ('completed', 'Complete', 'Success/completion feel'),
        ('square', 'Square Wave', 'Mechanical square pattern'),
        ('wave', 'Wave', 'Smooth wave pattern'),
        ('firework', 'Firework', 'Burst pattern'),
        ('mad', 'Strong Alert', 'Strong error pattern'),
        ('knock', 'Knock', 'Knocking pattern'),
        ('jingle', 'Jingle', 'Musical jingle pattern'),
        ('ringing', 'Ringing', 'Ring/vibrate pattern'),
    ]

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        card = SettingsCard('Haptic Feedback')

        # Enable/disable switch
        enable_row = SettingRow('Enable Haptic Feedback', 'Feel vibrations when using the radial menu')
        enable_switch = Gtk.Switch()
        enable_switch.set_active(config.get('haptics', 'enabled', default=True))
        enable_switch.connect('state-set', lambda s, state: config.set('haptics', 'enabled', state) or False)
        enable_row.set_control(enable_switch)
        card.append(enable_row)

        content.append(card)

        # Per-event haptic patterns
        events_card = SettingsCard('Haptic Patterns')

        # Store dropdowns for "Apply to All" feature
        self.event_dropdowns = {}

        event_settings = [
            ('menu_appear', 'Menu Appear', 'Pattern when radial menu opens'),
            ('slice_change', 'Slice Hover', 'Pattern when hovering over different slices'),
            ('confirm', 'Selection', 'Pattern when selecting an action'),
            ('invalid', 'Invalid Action', 'Pattern for blocked/invalid actions'),
        ]

        for key, label, desc in event_settings:
            row = SettingRow(label, desc)
            current_pattern = config.get('haptics', 'per_event', key, default='subtle_collision')
            dropdown = self._create_pattern_dropdown(
                current_pattern,
                lambda pattern, k=key: config.set('haptics', 'per_event', k, pattern)
            )
            self.event_dropdowns[key] = dropdown
            row.set_control(dropdown)
            events_card.append(row)

        # Add "Apply to All" row
        apply_all_row = SettingRow('Apply to All', 'Set all events to the same pattern')
        apply_all_dropdown = self._create_pattern_dropdown(
            'subtle_collision',
            self._apply_pattern_to_all
        )
        apply_all_row.set_control(apply_all_dropdown)
        events_card.append(apply_all_row)

        content.append(events_card)

        # Test button card
        test_card = SettingsCard('Test Haptics')
        test_row = SettingRow('Test Pattern', 'Feel the selected pattern')
        test_button = Gtk.Button(label='Test')
        test_button.add_css_class('suggested-action')
        test_button.connect('clicked', self._on_test_clicked)
        test_row.set_control(test_button)
        test_card.append(test_row)

        content.append(test_card)

        self.set_child(content)

    def _create_pattern_dropdown(self, current_value, on_change_callback):
        """Create a dropdown for selecting haptic patterns"""
        dropdown = Gtk.ComboBoxText()

        current_index = 0
        for i, (pattern_id, display_name, _) in enumerate(self.HAPTIC_PATTERNS):
            dropdown.append(pattern_id, display_name)
            if pattern_id == current_value:
                current_index = i

        dropdown.set_active(current_index)
        dropdown.connect('changed', lambda d: on_change_callback(d.get_active_id()) if d.get_active_id() else None)

        return dropdown

    def _apply_pattern_to_all(self, pattern):
        """Apply the selected pattern to all event types"""
        if not pattern:
            return

        # Update all per-event patterns in config
        event_keys = ['menu_appear', 'slice_change', 'confirm', 'invalid']
        for key in event_keys:
            config.set('haptics', 'per_event', key, pattern)

        # Update all dropdowns in the UI to match
        # Find the index for this pattern
        pattern_index = 0
        for i, (pattern_id, _, _) in enumerate(self.HAPTIC_PATTERNS):
            if pattern_id == pattern:
                pattern_index = i
                break

        # Update each dropdown's visual selection
        for key, dropdown in self.event_dropdowns.items():
            dropdown.set_active(pattern_index)

    def _on_test_clicked(self, button):
        """Send a test haptic pulse via D-Bus"""
        try:
            import subprocess
            # Trigger haptic via D-Bus - daemon will use the current default pattern
            subprocess.run([
                'dbus-send', '--session', '--type=method_call',
                '--dest=org.kde.juhradialmx',
                '/org/kde/juhradialmx/Daemon',
                'org.kde.juhradialmx.Daemon.TestHaptic'
            ], check=False, capture_output=True)
        except Exception as e:
            print(f"Failed to send test haptic: {e}")


class SettingsPage(Gtk.ScrolledWindow):
    """General settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Appearance settings
        appearance_card = SettingsCard('Appearance')

        theme_row = SettingRow('Theme', 'Choose color theme for radial menu and settings')
        theme_dropdown = Gtk.DropDown()
        theme_options = Gtk.StringList.new([
            'JuhRadial MX (Premium)',  # Premium cyan theme
            'Catppuccin Mocha',        # Dark
            'Nord',                    # Arctic bluish
            'Dracula',                 # Purple accents
            'Catppuccin Latte',        # Light
            'GitHub Light',            # Light
            'Solarized Light',         # Light
        ])
        theme_dropdown.set_model(theme_options)
        # Set current theme
        current_theme = config.get('theme', default='juhradial-mx')
        theme_map = {
            'juhradial-mx': 0,
            'catppuccin-mocha': 1,
            'nord': 2,
            'dracula': 3,
            'catppuccin-latte': 4,
            'github-light': 5,
            'solarized-light': 6,
        }
        theme_dropdown.set_selected(theme_map.get(current_theme, 0))
        theme_dropdown.connect('notify::selected', self._on_theme_changed)
        theme_row.set_control(theme_dropdown)
        appearance_card.append(theme_row)

        blur_row = SettingRow('Blur Effect', 'Enable background blur for radial menu')
        blur_switch = Gtk.Switch()
        blur_switch.set_active(config.get('blur_enabled', default=True))
        blur_switch.connect('state-set', lambda s, state: config.set('blur_enabled', state) or False)
        blur_row.set_control(blur_switch)
        appearance_card.append(blur_row)

        content.append(appearance_card)

        # App settings
        app_card = SettingsCard('Application')

        startup_row = SettingRow('Start at Login', 'Launch JuhRadial MX when you log in')
        startup_switch = Gtk.Switch()
        startup_switch.set_active(config.get('app', 'start_at_login', default=True))
        startup_switch.connect('state-set', self._on_startup_changed)
        startup_row.set_control(startup_switch)
        app_card.append(startup_row)

        tray_row = SettingRow('Show Tray Icon', 'Display icon in system tray')
        tray_switch = Gtk.Switch()
        tray_switch.set_active(config.get('app', 'show_tray_icon', default=True))
        tray_switch.connect('state-set', lambda s, state: config.set('app', 'show_tray_icon', state) or False)
        tray_row.set_control(tray_switch)
        app_card.append(tray_row)

        content.append(app_card)

        # Device info - fetch from daemon if available
        info_card = SettingsCard('Device Information')

        # Try to get actual device info from daemon
        device_name = 'MX Master 4'  # Default
        connection_type = 'Not available'
        battery_level = 'Not available'

        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                'org.kde.juhradialmx',
                '/org/kde/juhradialmx/Daemon',
                'org.kde.juhradialmx.Daemon',
                None
            )
            # Get battery status
            result = proxy.call_sync('GetBatteryStatus', None, Gio.DBusCallFlags.NONE, 500, None)
            if result:
                percentage, charging = result.unpack()
                if percentage > 0:
                    status = 'Charging' if charging else 'Discharging'
                    battery_level = f'{percentage}% ({status})'
                    connection_type = 'Connected'
        except Exception:
            pass  # Daemon may not be running

        info_items = [
            ('Device', device_name),
            ('Battery', battery_level),
            ('Status', connection_type),
        ]

        for label, value in info_items:
            row = SettingRow(label, value)
            info_card.append(row)

        content.append(info_card)

        # Danger zone
        danger_card = SettingsCard('Reset')

        reset_row = SettingRow('Restore Defaults', 'Reset all settings to factory defaults')
        reset_btn = Gtk.Button(label='Reset')
        reset_btn.add_css_class('danger-btn')
        reset_btn.connect('clicked', self._on_reset_clicked)
        reset_row.set_control(reset_btn)
        danger_card.append(reset_row)

        content.append(danger_card)

        self.set_child(content)

    def _on_theme_changed(self, dropdown, _):
        """Handle theme selection change - applies to both overlay and settings"""
        import subprocess

        theme_values = [
            'juhradial-mx',
            'catppuccin-mocha',
            'nord',
            'dracula',
            'catppuccin-latte',
            'github-light',
            'solarized-light',
        ]
        selected = dropdown.get_selected()
        if 0 <= selected < len(theme_values):
            theme = theme_values[selected]
            config.set('theme', theme)
            print(f"Theme changed to: {theme}")

            # Reload CSS for the settings window
            self._reload_theme_css()

            # Restart the overlay to apply the new theme
            try:
                # Kill the old overlay
                subprocess.run(['pkill', '-f', 'juhradial-overlay.py'],
                             capture_output=True, timeout=2)
                # Start new overlay with new theme
                overlay_path = Path(__file__).parent / 'juhradial-overlay.py'
                subprocess.Popen(['python3', str(overlay_path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("Overlay restarted with new theme")
            except Exception as e:
                print(f"Could not restart overlay: {e}")

    def _reload_theme_css(self):
        """Reload CSS with new theme colors"""
        global COLORS
        # Reload colors from the new theme
        COLORS = load_colors()

        # Regenerate CSS with new colors
        new_css = generate_css()

        # Apply new CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(new_css.encode())

        # Get the display and apply
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        print("Settings CSS reloaded with new theme")

    def _on_startup_changed(self, switch, state):
        """Handle start at login toggle"""
        config.set('app', 'start_at_login', state)
        # Create or remove autostart file
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_file = autostart_dir / "juhradial-mx.desktop"

        if state:
            # Create autostart entry
            autostart_dir.mkdir(parents=True, exist_ok=True)
            # Get the script path dynamically
            script_dir = Path(__file__).resolve().parent.parent
            exec_path = script_dir / 'juhradial-mx.sh'
            # Fallback to installed location if not found
            if not exec_path.exists():
                exec_path = Path('/usr/bin/juhradial-mx')
            desktop_content = f"""[Desktop Entry]
Type=Application
Name=JuhRadial MX
Comment=Radial menu for Logitech MX Master
Exec={exec_path}
Icon=org.juhlabs.JuhRadialMX
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
"""
            autostart_file.write_text(desktop_content, encoding='utf-8')
            print(f"Created autostart: {autostart_file}")
        else:
            # Remove autostart entry
            if autostart_file.exists():
                autostart_file.unlink()
                print(f"Removed autostart: {autostart_file}")
        return False

    def _on_reset_clicked(self, button):
        """Reset all settings to defaults"""
        global config
        config.config = json.loads(json.dumps(ConfigManager.DEFAULT_CONFIG))
        config.save()
        print("Settings reset to defaults")
        # Show notification
        dialog = Adw.AlertDialog(
            heading="Settings Reset",
            body="All settings have been restored to defaults. Please restart JuhRadial MX for changes to take effect."
        )
        dialog.add_response("ok", "OK")
        dialog.present(self.get_root())


class PlaceholderPage(Gtk.Box):
    """Placeholder for unimplemented pages"""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name('dialog-information-symbolic')
        icon.set_pixel_size(48)
        icon.set_opacity(0.5)
        self.append(icon)

        label = Gtk.Label(label=f'{title}\nComing Soon')
        label.set_justify(Gtk.Justification.CENTER)
        label.set_opacity(0.6)
        self.append(label)


class AddApplicationDialog(Adw.Window):
    """Dialog for adding a per-application profile"""

    def __init__(self, parent):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title('Add Application Profile')
        self.set_default_size(500, 600)

        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda _: self.close())
        header.pack_start(cancel_btn)

        main_box.append(header)

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Description
        desc = Gtk.Label(label='Create a custom profile for a specific application.\nThe radial menu will use this profile when the application is active.')
        desc.set_wrap(True)
        desc.set_margin_bottom(16)
        content.append(desc)

        # Application selection
        app_card = SettingsCard('Select Application')

        # Running apps list
        running_label = Gtk.Label(label='Running Applications:')
        running_label.set_halign(Gtk.Align.START)
        running_label.set_margin_top(8)
        app_card.append(running_label)

        # Scrollable app list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)

        self.app_list = Gtk.ListBox()
        self.app_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.app_list.add_css_class('boxed-list')

        # Get running applications
        self._populate_running_apps()

        scrolled.set_child(self.app_list)
        app_card.append(scrolled)

        # Or enter manually
        manual_label = Gtk.Label(label='Or enter application class manually:')
        manual_label.set_halign(Gtk.Align.START)
        manual_label.set_margin_top(16)
        app_card.append(manual_label)

        self.app_entry = Gtk.Entry()
        self.app_entry.set_placeholder_text('e.g., firefox, code, gimp')
        self.app_entry.set_margin_top(8)
        app_card.append(self.app_entry)

        content.append(app_card)

        # Add button
        add_btn = Gtk.Button(label='Add Profile')
        add_btn.add_css_class('suggested-action')
        add_btn.set_margin_top(16)
        add_btn.connect('clicked', self._on_add_clicked)
        content.append(add_btn)

        main_box.append(content)
        self.set_content(main_box)

    def _populate_running_apps(self):
        """Get list of running applications using D-Bus and process detection"""
        import subprocess
        import re

        apps = set()

        try:
            # Method 1: Get running KDE apps from D-Bus session bus
            # Apps register as org.kde.<appname>-<pid> or similar patterns
            result = subprocess.run(
                ['qdbus-qt6'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()
                    # Match patterns like org.kde.dolphin-12345
                    match = re.match(r'org\.kde\.(\w+)-\d+', line)
                    if match:
                        app_name = match.group(1)
                        if app_name not in ('KWin', 'plasmashell', 'kded', 'kglobalaccel'):
                            apps.add(app_name)
                    # Also match org.mozilla.firefox, org.chromium, etc.
                    match = re.match(r'org\.(\w+)\.(\w+)', line)
                    if match:
                        org, app = match.group(1), match.group(2)
                        if org in ('mozilla', 'chromium', 'gnome', 'gtk'):
                            apps.add(app.lower())
        except Exception as e:
            print(f"D-Bus app detection failed: {e}")

        try:
            # Method 2: Check for GUI processes with known .desktop files
            # Look at running processes and match against installed apps
            desktop_dirs = [
                Path('/usr/share/applications'),
                Path.home() / '.local/share/applications',
                Path('/var/lib/flatpak/exports/share/applications'),
                Path.home() / '.local/share/flatpak/exports/share/applications',
            ]

            # Get all installed app names from .desktop files
            installed_apps = {}
            for desktop_dir in desktop_dirs:
                if desktop_dir.exists():
                    for desktop_file in desktop_dir.glob('*.desktop'):
                        try:
                            content = desktop_file.read_text()
                            # Extract Exec line to get binary name
                            for line in content.split('\n'):
                                if line.startswith('Exec='):
                                    exec_cmd = line[5:].split()[0]  # Get first word after Exec=
                                    binary = Path(exec_cmd).name
                                    # Map binary to desktop file name (app name)
                                    app_name = desktop_file.stem
                                    # Use shorter name if it's a reverse-domain style
                                    if '.' in app_name:
                                        parts = app_name.split('.')
                                        app_name = parts[-1] if len(parts) > 2 else app_name
                                    installed_apps[binary] = app_name
                                    break
                        except Exception:
                            pass

            # Get running process names
            result = subprocess.run(['ps', '-eo', 'comm', '--no-headers'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                running_procs = set(result.stdout.strip().split('\n'))
                for proc in running_procs:
                    proc = proc.strip()
                    if proc in installed_apps:
                        apps.add(installed_apps[proc])
                    # Also check common GUI apps directly
                    elif proc in ('firefox', 'chrome', 'chromium', 'code', 'konsole',
                                 'dolphin', 'kate', 'okular', 'gwenview', 'spectacle',
                                 'gimp', 'blender', 'inkscape', 'kwrite', 'vlc', 'mpv',
                                 'obs', 'slack', 'discord', 'telegram-desktop', 'signal-desktop',
                                 'spotify', 'thunderbird', 'evolution', 'nautilus', 'gedit'):
                        apps.add(proc)
        except Exception as e:
            print(f"Process detection failed: {e}")

        # Add some common apps that user might want (grayed out if not detected)
        common_apps = ['firefox', 'chrome', 'code', 'gimp', 'blender', 'inkscape',
                      'libreoffice', 'konsole', 'dolphin', 'okular', 'gwenview',
                      'kate', 'kwrite', 'spectacle', 'vlc', 'obs']

        # Combine detected apps with common apps (detected first)
        all_apps = list(apps)
        for app in common_apps:
            if app not in apps:
                all_apps.append(app)

        # Populate list
        for app in all_apps[:30]:  # Limit to 30 apps
            row = Adw.ActionRow()
            row.set_title(app)
            row.app_name = app

            # Mark as running if detected
            if app in apps:
                row.set_subtitle("Running")

            # Add checkmark suffix (hidden initially)
            check = Gtk.Image.new_from_icon_name('object-select-symbolic')
            check.set_visible(False)
            row.add_suffix(check)
            row.check_icon = check

            self.app_list.append(row)

        if not all_apps:
            # Add placeholder if nothing found
            row = Adw.ActionRow()
            row.set_title('(Enter app name manually below)')
            self.app_list.append(row)

        self.app_list.connect('row-selected', self._on_app_selected)

    def _on_app_selected(self, list_box, row):
        """Handle app selection"""
        # Clear all checkmarks
        child = list_box.get_first_child()
        while child:
            if hasattr(child, 'check_icon'):
                child.check_icon.set_visible(False)
            child = child.get_next_sibling()

        # Show checkmark on selected
        if row and hasattr(row, 'check_icon'):
            row.check_icon.set_visible(True)
            if hasattr(row, 'app_name'):
                self.app_entry.set_text(row.app_name)

    def _on_add_clicked(self, button):
        """Add the application profile"""
        app_name = self.app_entry.get_text().strip()

        if not app_name:
            dialog = Adw.AlertDialog(
                heading="No Application Selected",
                body="Please select or enter an application name."
            )
            dialog.add_response("ok", "OK")
            dialog.present(self)
            return

        # Save profile
        profile_path = Path.home() / '.config' / 'juhradial' / 'profiles.json'

        try:
            profiles = {}
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)

            # Create app-specific profile (copy from default)
            default_profile = profiles.get('default', {})
            profiles[app_name] = {
                'name': app_name,
                'slices': default_profile.get('slices', []),
                'app_class': app_name,
            }

            # Save
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, indent=2)

            print(f"Created profile for: {app_name}")

            # Show success and close
            self.close()

            # Show toast in parent (if supported)
            toast = Adw.Toast(title=f"Profile created for {app_name}")
            toast.set_timeout(2)
            # Note: Would need ToastOverlay in parent for this to work

        except Exception as e:
            print(f"Failed to save profile: {e}")
            dialog = Adw.AlertDialog(
                heading="Error",
                body=f"Failed to create profile: {e}"
            )
            dialog.add_response("ok", "OK")
            dialog.present(self)


class SettingsWindow(Adw.ApplicationWindow):
    """Main settings window"""

    def __init__(self, app):
        super().__init__(application=app, title='JuhRadial MX Settings')
        self.add_css_class('settings-window')

        # Force dark theme
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)

        # Set window icon for Wayland (fixes yellow default icon)
        icon_path = Path(__file__).parent.parent / "assets" / "juhradial-mx.svg"
        if icon_path.exists():
            self.set_icon_name(None)  # Clear any default
            # Load and set icon from file
            try:
                icon_file = Gio.File.new_for_path(str(icon_path))
                icon = Gio.FileIcon.new(icon_file)
                # For GTK4/Adwaita, we need to use the default icon theme
                # Create a paintable from the SVG
                display = Gdk.Display.get_default()
                theme = Gtk.IconTheme.get_for_display(display)
                # Add our assets directory to the icon search path
                theme.add_search_path(str(icon_path.parent))
            except Exception as e:
                print(f"Could not set window icon: {e}")

        # D-Bus connection for daemon communication
        self.dbus_proxy = None
        self._init_dbus()

        # Battery UI elements (set in _create_status_bar)
        self.battery_label = None
        self.battery_icon = None
        self._battery_available = True  # Set to False if daemon doesn't support battery

        # Create proper header bar with window controls
        headerbar = Adw.HeaderBar()
        headerbar.set_show_end_title_buttons(True)  # Close, minimize, maximize
        headerbar.set_show_start_title_buttons(True)

        # Add logo and title to header bar
        title_box = self._create_title_widget()
        headerbar.set_title_widget(title_box)

        # Add application button to header bar
        add_app_btn = Gtk.Button(label='+ ADD APPLICATION')
        add_app_btn.add_css_class('add-app-btn')
        add_app_btn.connect('clicked', self._on_add_application)
        headerbar.pack_end(add_app_btn)

        # Grid view toggle
        grid_btn = Gtk.Button()
        grid_btn.set_child(Gtk.Image.new_from_icon_name('view-grid-symbolic'))
        grid_btn.add_css_class('flat')
        grid_btn.connect('clicked', self._on_grid_view_toggle)
        headerbar.pack_end(grid_btn)

        # Main content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_box.set_vexpand(True)

        # Sidebar
        sidebar = self._create_sidebar()
        content_box.append(sidebar)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(sep)

        # Main content with mouse visualization and settings
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_hexpand(True)

        # Create pages
        self._create_pages()

        content_box.append(self.content_stack)

        # Create main vertical layout with status bar
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(content_box)

        # Status bar
        status_bar = self._create_status_bar()
        main_box.append(status_bar)

        # Use ToolbarView to properly integrate header bar with content
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(headerbar)
        toolbar_view.set_content(main_box)

        # Wrap in ToastOverlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(toolbar_view)

        self.set_content(self.toast_overlay)

        # Connect config to show toasts in this window
        config.set_toast_callback(self.show_toast)

        # Select first nav item
        self._on_nav_clicked('buttons')

        # Setup UPower signal monitoring for instant battery updates (system events)
        self._setup_upower_signals()
        # Start battery update timer (2 seconds for responsive charging status)
        # This frequent polling is fine since settings window is only open briefly
        GLib.timeout_add_seconds(2, self._update_battery)
        # Initial battery update
        GLib.idle_add(self._update_battery)

    def show_toast(self, message, timeout=2):
        """Show a toast notification"""
        toast = Adw.Toast(title=message)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def _init_dbus(self):
        """Initialize D-Bus connection to daemon"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.dbus_proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                'org.kde.juhradialmx',
                '/org/kde/juhradialmx/Daemon',
                'org.kde.juhradialmx.Daemon',
                None
            )
        except Exception as e:
            print(f"Failed to connect to D-Bus: {e}")
            self.dbus_proxy = None

    def _setup_upower_signals(self):
        """Setup UPower D-Bus signals for instant battery charging updates"""
        try:
            system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

            # Subscribe to UPower device changed signals
            # This catches battery state changes (charging/discharging)
            system_bus.signal_subscribe(
                'org.freedesktop.UPower',          # sender
                'org.freedesktop.DBus.Properties', # interface
                'PropertiesChanged',               # signal name
                None,                              # object path (all devices)
                None,                              # arg0 (interface name filter)
                Gio.DBusSignalFlags.NONE,
                self._on_upower_changed,           # callback
                None                               # user data
            )

            # Also listen for device added/removed (e.g., USB charger connected)
            system_bus.signal_subscribe(
                'org.freedesktop.UPower',
                'org.freedesktop.UPower',
                'DeviceAdded',
                '/org/freedesktop/UPower',
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_upower_device_event,
                None
            )
            system_bus.signal_subscribe(
                'org.freedesktop.UPower',
                'org.freedesktop.UPower',
                'DeviceRemoved',
                '/org/freedesktop/UPower',
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_upower_device_event,
                None
            )

            print("UPower signal monitoring enabled for instant battery updates")
        except Exception as e:
            print(f"Could not setup UPower signals: {e}")
            print("Falling back to polling only")

    def _on_upower_changed(self, connection, sender, path, interface, signal, params, user_data):
        """Handle UPower property changes - triggers instant battery update"""
        # Only respond to battery-related property changes
        if params:
            changed_props = params.unpack()
            if len(changed_props) > 0:
                interface_name = changed_props[0]
                # Check if this is a battery device property change
                if 'UPower' in interface_name or 'Device' in interface_name:
                    # Schedule immediate battery update on main thread
                    GLib.idle_add(self._update_battery)

    def _on_upower_device_event(self, connection, sender, path, interface, signal, params, user_data):
        """Handle UPower device added/removed - charger connected/disconnected"""
        # Immediate battery update when a device is added/removed
        GLib.idle_add(self._update_battery)

    def _update_battery(self):
        """Fetch battery status from daemon via D-Bus"""
        if self.dbus_proxy is None or self.battery_label is None or not self._battery_available:
            return self._battery_available  # Stop timer if battery not available

        try:
            # Call GetBatteryStatus method
            result = self.dbus_proxy.call_sync(
                'GetBatteryStatus',
                None,
                Gio.DBusCallFlags.NONE,
                1000,  # timeout ms
                None
            )
            if result:
                percentage, is_charging = result.unpack()

                # Show charging indicator in label with ⚡ symbol
                if is_charging:
                    self.battery_label.set_label(f'⚡ {percentage}%')
                else:
                    self.battery_label.set_label(f'{percentage}%')

                # Update icon based on level and charging status
                if is_charging:
                    if percentage >= 80:
                        icon = 'battery-full-charging-symbolic'
                    elif percentage >= 50:
                        icon = 'battery-good-charging-symbolic'
                    elif percentage >= 20:
                        icon = 'battery-low-charging-symbolic'
                    else:
                        icon = 'battery-caution-charging-symbolic'
                else:
                    if percentage >= 80:
                        icon = 'battery-full-symbolic'
                    elif percentage >= 50:
                        icon = 'battery-good-symbolic'
                    elif percentage >= 20:
                        icon = 'battery-low-symbolic'
                    else:
                        icon = 'battery-caution-symbolic'

                if self.battery_icon:
                    self.battery_icon.set_from_icon_name(icon)
        except Exception as e:
            if 'UnknownMethod' in str(e):
                # Daemon doesn't support battery status yet - stop polling
                self._battery_available = False
                self.battery_label.set_label('N/A')
                return False  # Stop timer
            print(f"Battery update failed: {e}")

        return True  # Keep timer running

    def _create_title_widget(self):
        """Create the premium title widget with logo, app name, and device badge"""
        # Main container
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        title_box.set_valign(Gtk.Align.CENTER)

        # Logo container with glow effect
        logo_container = Gtk.Box()
        logo_container.add_css_class('logo-container')
        logo_container.set_valign(Gtk.Align.CENTER)

        # JuhRadial MX header: logo icon + text
        script_dir = Path(__file__).resolve().parent
        logo_paths = [
            script_dir.parent / 'docs' / 'radiallogo_icon.png',
            script_dir / 'assets' / 'radiallogo_icon.png',
            Path('/usr/share/juhradial/radiallogo_icon.png'),
        ]

        # Load logo icon with proper scaling
        from gi.repository import GdkPixbuf
        logo_loaded = False
        for img_path in logo_paths:
            if img_path.exists():
                try:
                    # Load and scale to 32px height, preserve aspect ratio
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(img_path), -1, 32, True
                    )
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    logo_widget = Gtk.Picture.new_for_paintable(texture)
                    logo_widget.set_valign(Gtk.Align.CENTER)
                    logo_container.append(logo_widget)
                    logo_loaded = True
                    print(f"Header logo loaded from: {img_path}")
                except Exception as e:
                    print(f"Failed to load header logo: {e}")
                break

        # Fallback icon if logo not loaded
        if not logo_loaded:
            fallback_icon = Gtk.Image.new_from_icon_name('input-mouse-symbolic')
            fallback_icon.set_pixel_size(28)
            logo_container.append(fallback_icon)

        title_box.append(logo_container)

        # Text content - title and subtitle
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)

        # App title with accent color on "MX"
        title = Gtk.Label()
        title.set_markup(f'<span weight="800" size="large">JuhRadial</span> <span weight="800" size="large" color="{COLORS["accent"]}">MX</span>')
        title.set_halign(Gtk.Align.START)
        text_box.append(title)

        # Subtitle
        subtitle = Gtk.Label(label='MOUSE CONFIGURATION')
        subtitle.add_css_class('app-subtitle')
        subtitle.set_halign(Gtk.Align.START)
        text_box.append(subtitle)

        title_box.append(text_box)

        # Vertical divider
        divider = Gtk.Box()
        divider.add_css_class('header-divider')
        title_box.append(divider)

        # Device badge
        device_badge = Gtk.Label(label='MX MASTER 3S')
        device_badge.add_css_class('device-badge')
        device_badge.set_valign(Gtk.Align.CENTER)
        title_box.append(device_badge)

        return title_box

    def _create_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.add_css_class('sidebar')

        self.nav_buttons = {}

        for item_id, label, icon in NAV_ITEMS:
            btn = NavButton(item_id, label, icon, on_click=self._on_nav_clicked)
            self.nav_buttons[item_id] = btn
            sidebar.append(btn)

        # Spacer to push credits to bottom
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(12)
        sep.set_margin_bottom(8)
        sidebar.append(sep)

        # Credits section
        credits_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        credits_box.set_margin_start(8)
        credits_box.set_margin_end(8)
        credits_box.set_margin_bottom(8)

        # Developer info
        dev_label = Gtk.Label()
        dev_label.set_markup(f'<span size="small" color="{COLORS["subtext0"]}">Developed by</span>')
        dev_label.set_halign(Gtk.Align.START)
        credits_box.append(dev_label)

        name_label = Gtk.Label()
        name_label.set_markup(f'<span size="small" weight="bold" color="{COLORS["text"]}">JuhLabs (Julian Hermstad)</span>')
        name_label.set_halign(Gtk.Align.START)
        credits_box.append(name_label)

        # Description
        desc_label = Gtk.Label()
        desc_label.set_markup(f'<span size="x-small" color="{COLORS["subtext0"]}">Free &amp; open source software.\nIf you enjoy this project,\nconsider supporting development.</span>')
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_margin_top(4)
        credits_box.append(desc_label)

        # Donate button
        donate_btn = Gtk.Button()
        donate_btn.add_css_class('suggested-action')
        donate_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        donate_box.set_halign(Gtk.Align.CENTER)
        coffee_icon = Gtk.Label(label="\u2615")  # Coffee emoji
        donate_box.append(coffee_icon)
        donate_label = Gtk.Label(label="Buy me a coffee")
        donate_box.append(donate_label)
        donate_btn.set_child(donate_box)
        donate_btn.set_margin_top(8)
        donate_btn.connect('clicked', self._on_donate_clicked)
        credits_box.append(donate_btn)

        sidebar.append(credits_box)

        return sidebar

    def _on_donate_clicked(self, button):
        """Open PayPal donation link"""
        import subprocess
        subprocess.Popen(['xdg-open', 'https://paypal.me/LangbachHermstad'])

    def _on_add_application(self, button):
        """Open dialog to add per-application profile"""
        dialog = AddApplicationDialog(self)
        dialog.present()

    def _on_grid_view_toggle(self, button):
        """Toggle grid view for application profiles"""
        # TODO: Implement grid view toggle
        dialog = Adw.AlertDialog(
            heading="Grid View",
            body="Application profiles grid view coming soon!\n\nThis will show all your per-app profiles in a visual grid."
        )
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def _create_pages(self):
        # Buttons page with mouse visualization
        buttons_page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Mouse visualization (left side)
        mouse_viz = MouseVisualization(on_button_click=self._on_mouse_button_click)
        mouse_viz.set_hexpand(True)
        buttons_page.append(mouse_viz)

        # Settings panel (right side)
        self.buttons_settings = ButtonsPage(on_button_config=self._on_mouse_button_click, parent_window=self, config_manager=config)
        self.buttons_settings.set_size_request(400, -1)
        buttons_page.append(self.buttons_settings)

        self.content_stack.add_named(buttons_page, 'buttons')

        # Other pages
        self.content_stack.add_named(ScrollPage(), 'scroll')
        self.content_stack.add_named(HapticsPage(), 'haptics')
        self.content_stack.add_named(PlaceholderPage('Easy-Switch'), 'easy_switch')
        self.content_stack.add_named(PlaceholderPage('Flow'), 'flow')
        self.content_stack.add_named(SettingsPage(), 'settings')

    def _create_status_bar(self):
        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status.add_css_class('status-bar')

        # Battery section
        battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Battery icon (left of percentage)
        self.battery_icon = Gtk.Image.new_from_icon_name('battery-good-symbolic')
        self.battery_icon.add_css_class('battery-icon')
        battery_box.append(self.battery_icon)

        # Store as instance variables for D-Bus updates
        self.battery_label = Gtk.Label(label='--')
        self.battery_label.add_css_class('battery-indicator')
        battery_box.append(self.battery_label)

        status.append(battery_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        status.append(spacer)

        # Connection status with icon
        conn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Connection icon (USB receiver)
        self.conn_icon = Gtk.Image.new_from_icon_name('network-wireless-signal-excellent-symbolic')
        self.conn_icon.add_css_class('connection-icon')
        conn_box.append(self.conn_icon)

        self.conn_label = Gtk.Label(label='Logi Bolt USB')
        self.conn_label.add_css_class('connection-status')
        conn_box.append(self.conn_label)

        status.append(conn_box)

        return status

    def _on_nav_clicked(self, item_id):
        # Update active state
        for btn_id, btn in self.nav_buttons.items():
            btn.set_active(btn_id == item_id)

        # Switch page
        self.content_stack.set_visible_child_name(item_id)

    def _on_mouse_button_click(self, button_id):
        """Open button configuration dialog"""
        if button_id in MOUSE_BUTTONS:
            dialog = ButtonConfigDialog(self, button_id, MOUSE_BUTTONS[button_id])
            dialog.connect('close-request', lambda _: self._on_dialog_closed())
            dialog.present()

    def _on_dialog_closed(self):
        """Refresh UI after dialog closes"""
        if hasattr(self, 'buttons_settings'):
            self.buttons_settings.refresh_button_labels()


class SettingsApp(Adw.Application):
    """GTK4/Adwaita Application"""

    def __init__(self):
        super().__init__(
            application_id='org.kde.juhradialmx.settings',
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_startup(self):
        Adw.Application.do_startup(self)

        # Load CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS.encode())

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        win = SettingsWindow(self)
        win.present()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    print('JuhRadial MX Settings Dashboard')
    print('  Theme: Catppuccin Mocha')
    print(f'  Size: {WINDOW_WIDTH}x{WINDOW_HEIGHT}')

    app = SettingsApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
