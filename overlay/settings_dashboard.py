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
import socket
import threading
from pathlib import Path

# Try to import zeroconf for mDNS discovery
try:
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ServiceInfo
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    print("[Flow] zeroconf not installed - run: pip install zeroconf")

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
            ],
            "easy_switch_shortcuts": False
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

    def reload(self):
        """Reload config from disk - useful when settings window reopens"""
        self.config = self._load()
        return self.config

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
        """Save config to file atomically and notify daemon"""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            # Atomic write: write to temp file, then rename (atomic on POSIX)
            temp_path = self.CONFIG_FILE.with_suffix('.json.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            # Atomic rename - replaces old file safely
            os.replace(temp_path, self.CONFIG_FILE)
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
        import shlex
        script_path = Path(__file__).parent.parent / 'scripts' / 'apply-settings.sh'
        if script_path.exists() and not script_path.is_symlink():
            # Run in konsole for sudo password prompt
            # Use shlex.quote to prevent command injection
            safe_path = shlex.quote(str(script_path))
            subprocess.Popen([
                'konsole', '-e', 'bash', '-c',
                f'{safe_path}; echo ""; echo "Press Enter to close..."; read'
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

    def set(self, *keys_and_value, auto_save=False):
        """Set nested config value and optionally save

        Args:
            *keys_and_value: Keys path followed by value
            auto_save: If False (default), just update in-memory. Use Apply button to save.
        """
        if len(keys_and_value) < 2:
            return
        *keys, value = keys_and_value
        target = self.config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
        if auto_save:
            self.save()

# Global config instance
config = ConfigManager()

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def disable_scroll_on_scale(scale):
    """Disable scroll wheel on Gtk.Scale to prevent accidental value changes

    This prevents scroll events from changing slider values when scrolling
    in a ScrolledWindow. The slider will only respond to:
    - Direct click and drag
    - Arrow keys when focused
    """
    # Add scroll controller that consumes scroll events (returns True)
    scroll_controller = Gtk.EventControllerScroll.new(
        Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.HORIZONTAL
    )
    # Set to CAPTURE phase to intercept before the Scale widget sees it
    scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    # Handler that consumes the scroll event (prevents it from reaching Scale)
    scroll_controller.connect('scroll', lambda controller, dx, dy: True)
    scale.add_controller(scroll_controller)

def detect_logitech_mouse():
    """Detect connected Logitech mouse name"""
    import subprocess
    import shutil
    from pathlib import Path

    # Logitech vendor ID
    LOGITECH_VENDOR = '046d'

    # Known MX Master device IDs and names (direct USB connection)
    DEVICE_NAMES = {
        'b034': 'MX Master 4',
        'b035': 'MX Master 4',
        'b023': 'MX Master 3S',
        'b028': 'MX Master 3S',
        'b024': 'MX Master 3',
        '4082': 'MX Master 3',
        '4069': 'MX Master 2S',
        '4041': 'MX Master',
    }

    try:
        # Method 1: Check HID devices for direct USB connection
        hid_path = Path('/sys/bus/hid/devices/')
        if hid_path.exists():
            for device in hid_path.iterdir():
                name = device.name.upper()
                if LOGITECH_VENDOR.upper() in name:
                    parts = name.split(':')
                    if len(parts) >= 3:
                        product_id = parts[2].split('.')[0].lower()
                        if product_id in DEVICE_NAMES:
                            return DEVICE_NAMES[product_id]

        # Method 2: Check logid config for device name
        logid_cfg = Path('/etc/logid.cfg')
        if logid_cfg.exists():
            try:
                with open(logid_cfg, 'r', encoding='utf-8') as f:
                    content = f.read()
                    import re
                    match = re.search(r'name:\s*"([^"]+)"', content)
                    if match:
                        return match.group(1)
            except Exception:
                pass

        # Method 3: Try libinput
        result = subprocess.run(
            ['libinput', 'list-devices'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'MX Master' in line and 'Device:' in line:
                    return line.split('Device:')[1].strip()

    except Exception as e:
        print(f"Device detection error: {e}")

    return 'MX Master 4'  # Default fallback

# Cache the detected device name
_detected_device = None

def get_device_name():
    """Get detected device name (cached)"""
    global _detected_device
    if _detected_device is None:
        _detected_device = detect_logitech_mouse()
    return _detected_device

# =============================================================================
# THEME SYSTEM - Load colors from shared theme module
# =============================================================================
from themes import get_colors, get_theme, load_theme_name, get_theme_list, is_dark_theme, THEMES, DEFAULT_THEME

# Flow module for multi-computer control
# Inspired by logitech-flow-kvm by Adam Coddington (coddingtonbear)
# https://github.com/coddingtonbear/logitech-flow-kvm
try:
    from flow import (
        start_flow_server, stop_flow_server, get_flow_server,
        get_linked_computers, FlowClient, FLOW_PORT
    )
    FLOW_MODULE_AVAILABLE = True
except ImportError:
    FLOW_MODULE_AVAILABLE = False
    print("[Warning] Flow module not available")

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
    ('scroll', 'SENSITIVITY', 'input-touchpad-symbolic'),
    ('haptics', 'HAPTIC FEEDBACK', 'audio-speakers-symbolic'),
    ('devices', 'DEVICES', 'computer-symbolic'),
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
   EASY-SWITCH SHORTCUTS CARD
   ============================================ */
.easyswitch-shortcuts-card {{
    background: {elevated_bg};
    border-radius: 12px;
    padding: 16px 20px;
    margin: 12px 0;
    border: 1px solid {accent_08};
    box-shadow: 0 4px 16px {shadow_color};
}}

.easyswitch-row {{
    padding: 4px 0;
}}

.easyswitch-icon-box {{
    background: linear-gradient(135deg, {accent_20} 0%, {accent2_15} 100%);
    border-radius: 10px;
    padding: 10px;
    min-width: 42px;
    min-height: 42px;
    border: 1px solid {accent_20};
}}

.easyswitch-icon {{
    color: {COLORS['accent']};
}}

.easyswitch-title {{
    font-size: 14px;
    font-weight: 600;
    color: {COLORS['text']};
    letter-spacing: 0.3px;
}}

.easyswitch-desc {{
    font-size: 12px;
    color: {COLORS['subtext0']};
    opacity: 0.85;
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
# Radial menu action definitions: (action_id, display_name, icon, type, command, color)
RADIAL_ACTIONS = [
    ('play_pause', 'Play/Pause', 'media-playback-start-symbolic', 'exec', 'playerctl play-pause', 'green'),
    ('screenshot', 'Screenshot', 'camera-photo-symbolic', 'exec', 'flameshot gui', 'purple'),
    ('lock', 'Lock Screen', 'system-lock-screen-symbolic', 'exec', 'loginctl lock-session', 'red'),
    ('settings', 'Settings', 'preferences-system-symbolic', 'settings', '', 'blue'),
    ('files', 'Files', 'system-file-manager-symbolic', 'exec', 'dolphin', 'orange'),
    ('emoji', 'Emoji Picker', 'face-smile-symbolic', 'exec', 'ibus emoji', 'yellow'),
    ('new_note', 'New Note', 'document-new-symbolic', 'exec', 'kwrite', 'yellow'),
    ('ai', 'AI Assistant', 'dialog-information-symbolic', 'submenu', '', 'teal'),
    ('copy', 'Copy', 'edit-copy-symbolic', 'shortcut', 'ctrl+c', 'blue'),
    ('paste', 'Paste', 'edit-paste-symbolic', 'shortcut', 'ctrl+v', 'blue'),
    ('undo', 'Undo', 'edit-undo-symbolic', 'shortcut', 'ctrl+z', 'blue'),
    ('redo', 'Redo', 'edit-redo-symbolic', 'shortcut', 'ctrl+shift+z', 'blue'),
    ('cut', 'Cut', 'edit-cut-symbolic', 'shortcut', 'ctrl+x', 'blue'),
    ('select_all', 'Select All', 'edit-select-all-symbolic', 'shortcut', 'ctrl+a', 'blue'),
    ('close_window', 'Close Window', 'window-close-symbolic', 'shortcut', 'alt+F4', 'red'),
    ('minimize', 'Minimize', 'window-minimize-symbolic', 'shortcut', 'super+d', 'blue'),
    ('volume_up', 'Volume Up', 'audio-volume-high-symbolic', 'exec', 'pactl set-sink-volume @DEFAULT_SINK@ +5%', 'green'),
    ('volume_down', 'Volume Down', 'audio-volume-low-symbolic', 'exec', 'pactl set-sink-volume @DEFAULT_SINK@ -5%', 'green'),
    ('mute', 'Mute', 'audio-volume-muted-symbolic', 'exec', 'pactl set-sink-mute @DEFAULT_SINK@ toggle', 'red'),
    ('next_track', 'Next Track', 'media-skip-forward-symbolic', 'exec', 'playerctl next', 'green'),
    ('prev_track', 'Previous Track', 'media-skip-backward-symbolic', 'exec', 'playerctl previous', 'green'),
    ('none', 'Do Nothing', 'action-unavailable-symbolic', 'none', '', 'gray'),
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
            slices = self.profile.get('slices', [])
            current_slice = slices[i] if i < len(slices) else {}
            current_label = current_slice.get('label', '')

            # Action dropdown
            dropdown = Gtk.DropDown()
            action_names = [name for _, name, _, _, _, _ in RADIAL_ACTIONS]
            dropdown.set_model(Gtk.StringList.new(action_names))

            # Find current action index by matching label
            for idx, (_, name, _, _, _, _) in enumerate(RADIAL_ACTIONS):
                if name == current_label:
                    dropdown.set_selected(idx)
                    break

            dropdown.set_hexpand(True)
            self.slice_dropdowns[i] = dropdown
            slice_box.append(dropdown)

            content.append(slice_box)

        scrolled.set_child(content)
        main_box.append(scrolled)

        self.set_content(main_box)

    def _load_profile(self):
        """Load the current radial menu from config.json"""
        config_path = Path.home() / '.config' / 'juhradial' / 'config.json'
        try:
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    # Return the radial_menu section
                    return config_data.get('radial_menu', {})
        except Exception as e:
            print(f"Failed to load config: {e}")
        return {}

    def _on_save(self, _):
        """Save the radial menu configuration to config.json"""
        config_path = Path.home() / '.config' / 'juhradial' / 'config.json'

        # Build new slices config in the format the overlay expects
        slices = []
        for i in range(8):
            dropdown = self.slice_dropdowns[i]
            selected = dropdown.get_selected()
            if 0 <= selected < len(RADIAL_ACTIONS):
                action_id, label, icon, action_type, command, color = RADIAL_ACTIONS[selected]
                slices.append({
                    'label': label,
                    'type': action_type,
                    'command': command,
                    'color': color,
                    'icon': icon,
                })

        # Load existing config and update radial_menu.slices
        try:
            config_data = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

            if 'radial_menu' not in config_data:
                config_data['radial_menu'] = {}

            config_data['radial_menu']['slices'] = slices

            # Save
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)

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
        # EASY-SWITCH SHORTCUTS CARD
        # =============================================
        easyswitch_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        easyswitch_card.add_css_class('easyswitch-shortcuts-card')

        # Create a row with icon, text, and switch
        easyswitch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        easyswitch_row.add_css_class('easyswitch-row')

        # Icon box
        es_icon_box = Gtk.Box()
        es_icon_box.add_css_class('easyswitch-icon-box')
        es_icon_box.set_valign(Gtk.Align.CENTER)
        es_icon = Gtk.Image.new_from_icon_name('network-wireless-symbolic')
        es_icon.set_pixel_size(20)
        es_icon.add_css_class('easyswitch-icon')
        es_icon_box.append(es_icon)
        easyswitch_row.append(es_icon_box)

        # Text content
        es_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        es_text_box.set_hexpand(True)
        es_text_box.set_valign(Gtk.Align.CENTER)

        es_title = Gtk.Label(label='Easy-Switch Shortcuts')
        es_title.set_halign(Gtk.Align.START)
        es_title.add_css_class('easyswitch-title')
        es_text_box.append(es_title)

        es_desc = Gtk.Label(label='Replace Emoji with Easy-Switch 1, 2, 3 submenu')
        es_desc.set_halign(Gtk.Align.START)
        es_desc.add_css_class('easyswitch-desc')
        es_text_box.append(es_desc)

        easyswitch_row.append(es_text_box)

        # Switch
        self.easyswitch_switch = Gtk.Switch()
        self.easyswitch_switch.set_valign(Gtk.Align.CENTER)
        self.easyswitch_switch.set_active(self.config_manager.get('radial_menu', 'easy_switch_shortcuts', default=False))
        self.easyswitch_switch.connect('state-set', self._on_easyswitch_toggled)
        easyswitch_row.append(self.easyswitch_switch)

        easyswitch_card.append(easyswitch_row)
        content.append(easyswitch_card)

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

    def _on_easyswitch_toggled(self, switch, state):
        """Handle Easy-Switch shortcuts toggle"""
        self.config_manager.set('radial_menu', 'easy_switch_shortcuts', state)
        self.config_manager.save()

        # Update the Emoji slice row to show status
        if 5 in self.slice_rows:
            row = self.slice_rows[5]
            for child in row:
                if isinstance(child, Gtk.Label):
                    if state:
                        child.set_text('Easy-Switch')
                    else:
                        # Restore original label from config
                        slices = self._get_current_slices()
                        if len(slices) > 5:
                            child.set_text(slices[5].get('label', 'Emoji'))
                    break

        return False  # Allow switch to change state


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
        # Disable scroll wheel to prevent accidental changes while scrolling page
        disable_scroll_on_scale(self.scale)
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
    """Sensitivity settings page - Mouse pointer, scroll wheel, and button sensitivity"""

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

        self.status_label = Gtk.Label(label='Settings are up to date')
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

        smartshift_desc = Gtk.Label(label='Auto-switch to free-spin when scrolling fast, return to ratchet when slow')
        smartshift_desc.set_halign(Gtk.Align.START)
        smartshift_desc.set_wrap(True)
        smartshift_desc.set_max_width_chars(60)
        smartshift_desc.add_css_class('dim-label')
        smartshift_content.append(smartshift_desc)

        smartshift_box.append(smartshift_content)
        scroll_card.append(smartshift_box)

        # Threshold slider
        threshold_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        threshold_box.set_margin_start(76)  # Align with text above

        threshold_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        threshold_label = Gtk.Label(label='Switch Threshold')
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
        ratchet_label = Gtk.Label(label='Stay ratchet')
        ratchet_label.add_css_class('dim-label')
        threshold_slider_box.append(ratchet_label)

        self.threshold_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.threshold_scale.set_hexpand(True)
        self.threshold_scale.set_draw_value(False)
        self.threshold_scale.set_value(config.get('scroll', 'smartshift_threshold', default=50))
        self.threshold_scale.connect('value-changed', self._on_threshold_changed)
        self._update_threshold_label(self.threshold_scale.get_value())
        # Disable scroll wheel to prevent accidental changes while scrolling page
        disable_scroll_on_scale(self.threshold_scale)
        threshold_slider_box.append(self.threshold_scale)

        freespin_label = Gtk.Label(label='Easy free-spin')
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
        self.natural_switch = Gtk.Switch()
        self.natural_switch.set_active(config.get('scroll', 'natural', default=False))
        self.natural_switch.connect('state-set', self._on_natural_changed)
        direction_row.set_control(self.natural_switch)
        scroll_card.append(direction_row)

        # High-resolution scrolling (HiRes mode)
        smooth_row = SettingRow('High-Resolution Scroll', 'More scroll events for smoother, faster scrolling')
        self.smooth_switch = Gtk.Switch()
        self.smooth_switch.set_active(config.get('scroll', 'smooth', default=True))
        self.smooth_switch.connect('state-set', self._on_smooth_changed)
        smooth_row.set_control(self.smooth_switch)
        scroll_card.append(smooth_row)

        # Separator before scroll speed
        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep3.set_margin_top(16)
        sep3.set_margin_bottom(16)
        scroll_card.append(sep3)

        # Scroll Speed slider for main wheel
        scroll_speed_row = SettingRow('Scroll Speed', 'Lines scrolled per wheel notch')
        scroll_speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        scroll_speed_scale.set_value(config.get('scroll', 'speed', default=3))
        scroll_speed_scale.set_size_request(200, -1)
        scroll_speed_scale.set_draw_value(False)
        scroll_speed_scale.connect('value-changed', self._on_scroll_speed_changed)
        disable_scroll_on_scale(scroll_speed_scale)
        scroll_speed_row.set_control(scroll_speed_scale)
        scroll_card.append(scroll_speed_row)

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
        # Disable scroll wheel to prevent accidental changes while scrolling page
        disable_scroll_on_scale(thumb_scale)
        thumb_speed_row.set_control(thumb_scale)
        thumb_card.append(thumb_speed_row)

        thumb_invert_row = SettingRow('Invert Direction', 'Reverse thumb wheel scroll direction')
        thumb_invert = Gtk.Switch()
        thumb_invert.set_active(config.get('thumbwheel', 'invert', default=False))
        thumb_invert.connect('state-set', lambda s, state: config.set('thumbwheel', 'invert', state) or False)
        thumb_invert_row.set_control(thumb_invert)
        thumb_card.append(thumb_invert_row)

        content.append(thumb_card)

        self.set_child(content)

        # Load SmartShift and HiResScroll settings from device on startup
        self._load_smartshift_settings()
        self._load_hiresscroll_settings()

    def _on_dpi_changed(self, dpi):
        # Convert DPI to speed (1-20) for config (no auto-save to avoid lag)
        speed = max(1, min(20, (dpi - 400) // 400 + 1))
        config.set('pointer', 'speed', speed)
        config.set('pointer', 'dpi', dpi)
        # Apply to hardware via D-Bus
        self._apply_dpi_to_device(dpi)
        # Also apply pointer speed via gsettings (software multiplier)
        self._apply_pointer_speed(dpi)
        # Show pending changes indicator
        self._show_pending_changes()

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

        # Apply to device via D-Bus
        threshold = int(self.threshold_scale.get_value())
        # Convert UI percentage (1-100) to device threshold (0-255)
        # Lower threshold = more sensitive, so we invert the percentage
        device_threshold = int((100 - threshold) * 2.55)
        self._apply_smartshift_to_device(state, device_threshold)

        return False

    def _on_threshold_changed(self, scale):
        value = int(scale.get_value())
        config.set('scroll', 'smartshift_threshold', value)
        self._update_threshold_label(value)

        # Apply to device via D-Bus
        enabled = self.smartshift_switch.get_active()
        # Convert UI percentage (1-100) to device threshold (0-255)
        # Lower threshold = more sensitive, so we invert the percentage
        device_threshold = int((100 - value) * 2.55)
        self._apply_smartshift_to_device(enabled, device_threshold)

        self._show_pending_changes()

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
        # Also apply to device via D-Bus HiResScroll
        self._apply_hiresscroll_to_device()
        return False

    def _on_smooth_changed(self, switch, state):
        """Handle high-resolution scroll toggle change"""
        config.set('scroll', 'smooth', state)
        # Apply to device via D-Bus HiResScroll
        self._apply_hiresscroll_to_device()
        return False

    def _on_scroll_speed_changed(self, scale):
        """Handle scroll speed slider change"""
        value = int(scale.get_value())
        config.set('scroll', 'speed', value)
        # Apply scroll lines setting via imwheel or gsettings
        self._apply_scroll_speed(value)

    def _apply_scroll_speed(self, lines):
        """Apply scroll speed multiplier - works on GNOME, KDE, Hyprland, etc."""
        import subprocess
        import os

        # Convert lines (1-10) to a scroll factor (0.5 to 2.0)
        # lines=1 -> 0.5x, lines=5 -> 1.0x (default), lines=10 -> 2.0x
        scroll_factor = 0.5 + (lines - 1) * 0.167  # Linear interpolation

        # Try different desktop environments
        desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
        session = os.environ.get('XDG_SESSION_TYPE', '').lower()

        # GNOME/Mutter on Wayland
        if 'gnome' in desktop or 'mutter' in desktop:
            try:
                # GNOME uses libinput, scroll factor via experimental settings
                subprocess.run([
                    'gsettings', 'set', 'org.gnome.mutter', 'experimental-features',
                    "['scale-monitor-framebuffer']"
                ], capture_output=True, timeout=2)
            except Exception:
                pass

        # KDE Plasma
        if 'kde' in desktop or 'plasma' in desktop:
            try:
                # KDE stores scroll settings in kcminputrc
                kwinrc = os.path.expanduser('~/.config/kcminputrc')
                # Update or create the scroll factor setting
                subprocess.run([
                    'kwriteconfig5', '--file', 'kcminputrc',
                    '--group', 'Mouse', '--key', 'ScrollFactor',
                    str(scroll_factor)
                ], capture_output=True, timeout=2)
            except Exception:
                pass

        # Hyprland
        hypr_sig = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
        if hypr_sig:
            try:
                # Hyprland supports runtime scroll_factor change
                subprocess.run([
                    'hyprctl', 'keyword', 'input:scroll_factor', str(scroll_factor)
                ], capture_output=True, timeout=2)
                print(f"Hyprland scroll_factor set to {scroll_factor:.2f}")
            except Exception:
                pass

        # Sway
        if 'sway' in desktop.lower():
            try:
                # Get device name and set scroll factor
                result = subprocess.run(
                    ['swaymsg', '-t', 'get_inputs'],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    import json
                    inputs = json.loads(result.stdout)
                    for inp in inputs:
                        if 'pointer' in inp.get('type', ''):
                            name = inp.get('identifier', '')
                            subprocess.run([
                                'swaymsg', 'input', name, 'scroll_factor', str(scroll_factor)
                            ], capture_output=True, timeout=2)
            except Exception:
                pass

        # X11 fallback with imwheel (if available)
        if session == 'x11':
            try:
                # Create/update imwheel config for scroll multiplier
                imwheel_config = os.path.expanduser('~/.imwheelrc')
                # lines value directly maps to scroll multiplier
                config_content = f'''".*"
None,      Up,   Button4, {lines}
None,      Down, Button5, {lines}
'''
                with open(imwheel_config, 'w', encoding='utf-8') as f:
                    f.write(config_content)
                # Restart imwheel if running
                subprocess.run(['pkill', 'imwheel'], capture_output=True, timeout=2)
                subprocess.run(['imwheel', '-b', '45'], capture_output=True, timeout=2)
            except Exception:
                pass

        print(f"Scroll speed set to {lines} lines (factor: {scroll_factor:.2f})")

    def _apply_hiresscroll_to_device(self):
        """Apply HiResScroll settings - first try D-Bus, then update logid config"""
        hires = config.get('scroll', 'smooth', default=True)
        invert = config.get('scroll', 'natural', default=False)
        target = False  # Default to False

        # Try D-Bus first
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
            proxy.call_sync(
                'SetHiresscrollMode',
                GLib.Variant('(bbb)', (hires, invert, target)),
                Gio.DBusCallFlags.NONE,
                2000,
                None
            )
            print(f"HiResScroll applied via D-Bus: hires={hires}, invert={invert}")
            return
        except GLib.Error as e:
            print(f"D-Bus failed (logid may be blocking): {e.message}")
        except Exception as e:
            print(f"D-Bus failed: {e}")

        # D-Bus failed, settings will apply after logid restart
        print(f"HiResScroll saved to config (requires logid restart to apply)")

    def _load_hiresscroll_settings(self):
        """Load HiResScroll settings from device via D-Bus on startup"""
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

            # Get current HiResScroll configuration
            result = proxy.call_sync(
                'GetHiresscrollMode',
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None
            )

            if result:
                hires = result.get_child_value(0).get_boolean()
                invert = result.get_child_value(1).get_boolean()
                # target = result.get_child_value(2).get_boolean()  # Not used in UI

                # Update UI to match device
                if hasattr(self, 'smooth_switch'):
                    self.smooth_switch.set_active(hires)
                    config.set('scroll', 'smooth', hires)

                # Note: Natural scrolling is controlled by gsettings, not device
                # so we don't update it from device settings

                print(f"Loaded HiResScroll from device: hires={hires}, invert={invert}")
        except GLib.Error as e:
            print(f"D-Bus error getting HiResScroll: {e.message}")
        except Exception as e:
            print(f"Failed to get HiResScroll via D-Bus: {e}")

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

    def _show_pending_changes(self):
        """Show that there are unsaved changes"""
        if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
            self.status_icon.set_from_icon_name('dialog-warning-symbolic')
            self.status_label.set_text('Click Apply to save changes')

    def _on_apply_clicked(self, button):
        """Apply all settings via logiops and save config"""
        # Save config to file (this will show toast)
        config.save()
        # Apply to device hardware
        config.apply_to_device()
        # Update status
        if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
            self.status_icon.set_from_icon_name('emblem-ok-symbolic')
            self.status_label.set_text('Settings applied!')
            # Reset after delay
            GLib.timeout_add(3000, self._reset_status)

    def _reset_status(self):
        if hasattr(self, 'status_label'):
            self.status_label.set_text('Settings are up to date')
        return False

    def _load_smartshift_settings(self):
        """Load SmartShift settings from device via D-Bus on startup"""
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

            # Check if SmartShift is supported
            supported = proxy.call_sync(
                'SmartShiftSupported',
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None
            )

            if supported and supported.get_child_value(0).get_boolean():
                # Get current SmartShift configuration
                result = proxy.call_sync(
                    'GetSmartShift',
                    None,
                    Gio.DBusCallFlags.NONE,
                    2000,
                    None
                )

                if result:
                    enabled = result.get_child_value(0).get_boolean()
                    device_threshold = result.get_child_value(1).get_byte()

                    # Convert device threshold (0-255) to UI percentage (1-100)
                    # Device: lower = more sensitive, so we invert it
                    ui_threshold = 100 - int(device_threshold / 2.55)
                    ui_threshold = max(1, min(100, ui_threshold))

                    # Update UI elements
                    self.smartshift_switch.set_active(enabled)
                    self.threshold_scale.set_value(ui_threshold)
                    self.threshold_scale.set_sensitive(enabled)
                    self.scroll_visual.set_smartshift(enabled)

                    # Update config
                    config.set('scroll', 'smartshift', enabled)
                    config.set('scroll', 'smartshift_threshold', ui_threshold)

                    print(f"SmartShift loaded: enabled={enabled}, threshold={ui_threshold}%")
            else:
                # SmartShift not supported, disable UI
                self.smartshift_switch.set_sensitive(False)
                self.threshold_scale.set_sensitive(False)
                print("SmartShift not supported on this device")

        except GLib.Error as e:
            print(f"D-Bus error loading SmartShift settings: {e.message}")
        except Exception as e:
            print(f"Failed to load SmartShift settings: {e}")

    def _apply_smartshift_to_device(self, enabled, threshold):
        """Apply SmartShift settings directly to the mouse via D-Bus"""
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

            # Call SetSmartShift with enabled and threshold
            proxy.call_sync(
                'SetSmartShift',
                GLib.Variant('(by)', (enabled, threshold)),
                Gio.DBusCallFlags.NONE,
                2000,
                None
            )

            # Update status to show SmartShift was applied
            if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                self.status_icon.set_from_icon_name('emblem-ok-symbolic')
                mode = 'enabled' if enabled else 'disabled'
                self.status_label.set_text(f'SmartShift {mode}')
                GLib.timeout_add(2000, self._reset_status)

            print(f"SmartShift applied: enabled={enabled}, threshold={threshold}")

        except GLib.Error as e:
            print(f"D-Bus error setting SmartShift: {e.message}")
            if hasattr(self, 'status_icon') and hasattr(self, 'status_label'):
                self.status_icon.set_from_icon_name('dialog-warning-symbolic')
                self.status_label.set_text('SmartShift error: daemon not running?')
                GLib.timeout_add(3000, self._reset_status)
        except Exception as e:
            print(f"Failed to set SmartShift via D-Bus: {e}")


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
        dropdown.connect('changed', lambda d: self._on_pattern_selected(d, on_change_callback))

        return dropdown

    def _on_pattern_selected(self, dropdown, callback):
        """Handle pattern selection - save and apply instantly"""
        pattern = dropdown.get_active_id()
        if not pattern:
            return

        # Save to config (in-memory)
        callback(pattern)

        # Save config to file so daemon can read it
        config.save(show_toast=False)

        # Reload daemon config to apply instantly
        self._reload_daemon_config()

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

        # Save config to file so daemon can read it
        config.save(show_toast=False)

        # Reload daemon config to apply all patterns instantly
        self._reload_daemon_config()

    def _reload_daemon_config(self):
        """Reload daemon config via D-Bus to apply haptic pattern changes instantly"""
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
            proxy.call_sync('ReloadConfig', None, Gio.DBusCallFlags.NONE, 2000, None)
            print("Daemon config reloaded - haptic patterns applied")
        except Exception as e:
            print(f"Failed to reload daemon config: {e}")

    def _on_test_clicked(self, button):
        """Send a test haptic pulse via D-Bus"""
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
            # Trigger haptic with "menu_appear" event to test the pattern
            proxy.call_sync(
                'TriggerHaptic',
                GLib.Variant('(s)', ('menu_appear',)),
                Gio.DBusCallFlags.NONE,
                2000,
                None
            )
            print("Test haptic triggered")
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
        device_name = get_device_name()
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
            config.save(show_toast=False)  # Save immediately so overlay picks it up
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


class DevicesPage(Gtk.ScrolledWindow):
    """Device information and management page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(32)
        content.set_margin_end(32)

        # Device Information Card
        device_card = SettingsCard('Connected Device')

        # Device name
        device_name = get_device_name()
        name_row = SettingRow('Device Name', 'Your Logitech mouse model')
        name_label = Gtk.Label(label=device_name)
        name_label.add_css_class('heading')
        name_row.set_control(name_label)
        device_card.append(name_row)

        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep1.set_margin_top(12)
        sep1.set_margin_bottom(12)
        device_card.append(sep1)

        # Connection status
        connection_type = self._get_connection_type()
        conn_row = SettingRow('Connection', 'How your device is connected')
        conn_icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        if 'Bluetooth' in connection_type:
            conn_icon = Gtk.Image.new_from_icon_name('bluetooth-symbolic')
        elif 'USB' in connection_type:
            conn_icon = Gtk.Image.new_from_icon_name('usb-symbolic')
        else:
            conn_icon = Gtk.Image.new_from_icon_name('network-wireless-symbolic')

        conn_icon.add_css_class('accent-color')
        conn_icon_box.append(conn_icon)

        conn_label = Gtk.Label(label=connection_type)
        conn_icon_box.append(conn_label)
        conn_row.set_control(conn_icon_box)
        device_card.append(conn_row)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(12)
        sep2.set_margin_bottom(12)
        device_card.append(sep2)

        # Battery level
        battery_info = self._get_battery_info()
        battery_row = SettingRow('Battery Level', 'Current battery status')
        battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        battery_icon = Gtk.Image.new_from_icon_name('battery-good-symbolic')
        battery_icon.add_css_class('battery-icon')
        battery_box.append(battery_icon)

        battery_label = Gtk.Label(label=battery_info)
        battery_label.add_css_class('battery-indicator')
        battery_box.append(battery_label)
        battery_row.set_control(battery_box)
        device_card.append(battery_row)

        # Separator
        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep3.set_margin_top(12)
        sep3.set_margin_bottom(12)
        device_card.append(sep3)

        # Firmware version (placeholder)
        fw_row = SettingRow('Firmware Version', 'Device firmware information')
        fw_label = Gtk.Label(label='Managed by LogiOps')
        fw_label.add_css_class('dim-label')
        fw_row.set_control(fw_label)
        device_card.append(fw_row)

        content.append(device_card)

        # Additional Info Card
        info_card = SettingsCard('Device Management')

        info_label = Gtk.Label()
        info_label.set_markup(
            'For advanced device configuration (button remapping, scroll settings), '
            'edit <b>/etc/logid.cfg</b> and restart logid.\n\n'
            'LogiOps docs: <a href="https://github.com/PixlOne/logiops">https://github.com/PixlOne/logiops</a>'
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        # Make links clickable and open in browser
        info_label.connect('activate-link', lambda label, uri: (Gtk.show_uri(None, uri, Gdk.CURRENT_TIME), True)[-1])
        info_card.append(info_label)

        content.append(info_card)

        self.set_child(content)

    def _get_connection_type(self):
        """Get connection type from daemon or detect"""
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
            # Try to get battery status as indicator of connection
            result = proxy.call_sync('GetBatteryStatus', None, Gio.DBusCallFlags.NONE, 500, None)
            if result:
                return 'USB Receiver / Bluetooth'
        except Exception:
            pass
        return 'USB Receiver'

    def _get_battery_info(self):
        """Get battery info from daemon"""
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
            result = proxy.call_sync('GetBatteryStatus', None, Gio.DBusCallFlags.NONE, 500, None)
            if result:
                percentage, charging = result.unpack()
                if percentage > 0:
                    status = 'Charging' if charging else 'Discharging'
                    return f'{percentage}% ({status})'
                else:
                    # 0% usually means unavailable (logid controlling HID++)
                    return 'Managed by LogiOps'
        except Exception:
            pass
        return 'Managed by LogiOps'


class FlowServiceListener:
    """mDNS service listener for discovering computers on the network"""

    def __init__(self, flow_page):
        self.flow_page = flow_page
        self.seen_ips = set()  # Track IPs to avoid duplicates

    def remove_service(self, zeroconf, type_, name):
        print(f"[Flow] Service removed: {name}")

    def add_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if info:
            addresses = info.parsed_addresses()
            ip = addresses[0] if addresses else None
            if not ip or ip in self.seen_ips:
                return  # Skip if no IP or already seen
            self.seen_ips.add(ip)

            # Determine device/software type from service type
            if "juhradialmx" in type_:
                software = "JuhRadialMX"
            elif "logi" in type_.lower():
                software = "Logi Options+"
            elif "companion-link" in type_ or "airplay" in type_ or "raop" in type_:
                software = "macOS"
            elif "smb" in type_:
                software = "Windows/Samba"
            elif "workstation" in type_:
                software = "Linux"
            elif "rdp" in type_:
                software = "Windows RDP"
            elif "sftp" in type_ or "ssh" in type_:
                software = "SSH Server"
            else:
                software = "Computer"

            # Clean up name - remove service suffix
            clean_name = name.split("._")[0] if "._" in name else name
            # Remove MAC address prefix if present (e.g., "8E46296F5480@MacBook M4")
            if "@" in clean_name:
                clean_name = clean_name.split("@")[1]

            self.flow_page.add_discovered_computer(clean_name, ip, info.port, software, type_)

    def update_service(self, zeroconf, type_, name):
        pass  # Handle service updates if needed


class FlowPage(Gtk.ScrolledWindow):
    """Flow multi-computer control settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.discovered_computers = {}  # Store discovered computers

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        main_box.set_margin_start(32)
        main_box.set_margin_end(32)
        main_box.set_margin_top(32)
        main_box.set_margin_bottom(32)

        # Header with Flow icon and description
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_box.set_halign(Gtk.Align.CENTER)
        header_box.set_margin_bottom(16)

        header_icon = Gtk.Image.new_from_icon_name('view-dual-symbolic')
        header_icon.set_pixel_size(48)
        header_icon.add_css_class('accent-color')
        header_box.append(header_icon)

        header_title = Gtk.Label(label='Logitech Flow')
        header_title.add_css_class('title-1')
        header_box.append(header_title)

        header_subtitle = Gtk.Label(label='Seamlessly move between computers')
        header_subtitle.add_css_class('dim-label')
        header_box.append(header_subtitle)

        main_box.append(header_box)

        # Enable Flow Card
        enable_card = SettingsCard('Flow Control')

        enable_row = SettingRow('Enable Flow', 'Control multiple computers with one mouse')
        self.flow_switch = Gtk.Switch()
        self.flow_switch.set_active(config.get('flow', 'enabled', default=False))
        self.flow_switch.connect('state-set', self._on_flow_toggled)
        enable_row.set_control(self.flow_switch)
        enable_card.append(enable_row)

        # Edge trigger option
        edge_row = SettingRow('Switch at screen edge', 'Move cursor to edge to switch computers')
        self.edge_switch = Gtk.Switch()
        self.edge_switch.set_active(config.get('flow', 'edge_trigger', default=True))
        self.edge_switch.set_sensitive(config.get('flow', 'enabled', default=False))
        self.edge_switch.connect('state-set', self._on_edge_toggled)
        edge_row.set_control(self.edge_switch)
        enable_card.append(edge_row)

        main_box.append(enable_card)

        # Detected Computers Card
        computers_card = SettingsCard('Computers on Network')

        self.computers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.computers_box.set_margin_top(8)
        self.computers_box.set_margin_bottom(8)

        # Placeholder for no computers detected
        self.no_computers_label = Gtk.Label(label='No other computers detected')
        self.no_computers_label.add_css_class('dim-label')
        self.no_computers_label.set_margin_top(16)
        self.no_computers_label.set_margin_bottom(16)
        self.computers_box.append(self.no_computers_label)

        computers_card.append(self.computers_box)

        # Scan button
        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        scan_box.set_halign(Gtk.Align.END)
        scan_box.set_margin_top(8)

        self.scan_button = Gtk.Button(label='Scan Network')
        self.scan_button.add_css_class('suggested-action')
        self.scan_button.connect('clicked', self._on_scan_clicked)
        scan_box.append(self.scan_button)

        computers_card.append(scan_box)

        main_box.append(computers_card)

        # How Flow Works Card
        info_card = SettingsCard('How Flow Works')
        info_label = Gtk.Label()
        info_label.set_markup(
            'Logitech Flow allows you to seamlessly control multiple computers\n'
            'with a single mouse by moving your cursor to the edge of the screen.\n\n'
            '<b>Requirements:</b>\n'
            '  \u2022 JuhRadialMX running on all computers\n'
            '  \u2022 Computers connected to the same network\n'
            '  \u2022 Flow enabled on all devices\n\n'
            '<b>Features:</b>\n'
            '  \u2022 Move cursor between screens seamlessly\n'
            '  \u2022 Copy and paste across computers\n'
            '  \u2022 Transfer files by dragging'
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        info_card.append(info_label)

        main_box.append(info_card)

        self.set_child(main_box)

        # Try to discover computers on startup
        GLib.idle_add(self._discover_computers)

    def _on_flow_toggled(self, switch, state):
        """Handle Flow enable/disable toggle"""
        config.set('flow', 'enabled', state)
        # Enable/disable edge trigger based on Flow state
        self.edge_switch.set_sensitive(state)

        if FLOW_MODULE_AVAILABLE:
            if state:
                # Start the Flow server
                def on_host_change(new_host):
                    """Called when another computer changes hosts"""
                    print(f"[Flow] Received host change request: {new_host}")
                    # Switch our devices via D-Bus
                    try:
                        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                        proxy = Gio.DBusProxy.new_sync(
                            bus, Gio.DBusProxyFlags.NONE, None,
                            'org.kde.juhradialmx',
                            '/org/kde/juhradialmx/Daemon',
                            'org.kde.juhradialmx.Daemon',
                            None
                        )
                        proxy.call_sync('SetHost', GLib.Variant('(y)', (new_host,)),
                                       Gio.DBusCallFlags.NONE, 5000, None)
                    except Exception as e:
                        print(f"[Flow] Error switching host: {e}")

                start_flow_server(on_host_change=on_host_change)
                print("[Flow] Server started")
            else:
                # Stop the Flow server
                stop_flow_server()
                print("[Flow] Server stopped")

        return False

    def _on_edge_toggled(self, switch, state):
        """Handle edge trigger toggle"""
        config.set('flow', 'edge_trigger', state)
        return False

    def _on_scan_clicked(self, button):
        """Scan network for other computers running JuhRadialMX"""
        self.scan_button.set_sensitive(False)
        self.scan_button.set_label('Scanning...')
        GLib.timeout_add(1500, self._finish_scan)

    def _finish_scan(self):
        """Complete the network scan"""
        self.scan_button.set_sensitive(True)
        self.scan_button.set_label('Scan Network')
        # Update UI with discovered computers
        GLib.idle_add(self._update_computers_list, list(self.discovered_computers.values()))
        return False

    def _discover_computers(self):
        """Discover other computers on the network running JuhRadialMX or Logi Options+"""
        if not ZEROCONF_AVAILABLE:
            print("[Flow] zeroconf not available, cannot discover computers")
            self._update_computers_list([])
            return False

        # Service types to scan for
        # - JuhRadialMX instances
        # - Logi Options+ Flow (various possible service names)
        # - Common device services to find Macs, PCs, etc.
        SERVICE_TYPES = [
            "_juhradialmx._tcp.local.",
            "_logiflow._tcp.local.",
            "_logitechflow._tcp.local.",
            "_logi-options._tcp.local.",
            # Common computer/device services
            "_companion-link._tcp.local.",  # Apple devices
            "_airplay._tcp.local.",          # AirPlay (Mac, Apple TV)
            "_smb._tcp.local.",              # Windows/Samba file sharing
            "_workstation._tcp.local.",      # Linux workstations
            "_sftp-ssh._tcp.local.",         # SSH/SFTP servers
            "_rdp._tcp.local.",              # Windows Remote Desktop
        ]

        # Start background discovery thread
        def discover_thread():
            try:
                zc = Zeroconf()
                listener = FlowServiceListener(self)
                browsers = []

                # Browse for all service types
                for svc_type in SERVICE_TYPES:
                    try:
                        browser = ServiceBrowser(zc, svc_type, listener)
                        browsers.append(browser)
                        print(f"[Flow] Browsing for {svc_type}")
                    except Exception as e:
                        print(f"[Flow] Failed to browse {svc_type}: {e}")

                # Also register this computer as a JuhRadialMX service
                self._register_service(zc)

                # Keep browsing for a few seconds
                time.sleep(4)

                # Update UI on main thread
                GLib.idle_add(self._update_computers_list, list(self.discovered_computers.values()))

            except Exception as e:
                print(f"[Flow] Discovery error: {e}")
                GLib.idle_add(self._update_computers_list, [])

        thread = threading.Thread(target=discover_thread, daemon=True)
        thread.start()
        return False

    def _register_service(self, zc):
        """Register this computer as a Flow-compatible service"""
        try:
            hostname = socket.gethostname()
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            # Official Logi Options+ Flow port is 59866 (TCP)
            FLOW_PORT = 59866

            # Register as JuhRadialMX service
            info_juh = ServiceInfo(
                "_juhradialmx._tcp.local.",
                f"{hostname}._juhradialmx._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=FLOW_PORT,
                properties={'version': '1.0', 'hostname': hostname, 'flow': 'compatible'},
            )
            zc.register_service(info_juh)
            print(f"[Flow] Registered JuhRadialMX service: {hostname} at {local_ip}:{FLOW_PORT}")

            # Also register as potential Logi Flow compatible service
            # Logi Options+ may look for these service types
            for svc_type in ["_logiflow._tcp.local.", "_logitechflow._tcp.local."]:
                try:
                    info_logi = ServiceInfo(
                        svc_type,
                        f"{hostname}.{svc_type}",
                        addresses=[socket.inet_aton(local_ip)],
                        port=FLOW_PORT,
                        properties={'version': '1.0', 'hostname': hostname, 'platform': 'linux'},
                    )
                    zc.register_service(info_logi)
                    print(f"[Flow] Registered {svc_type}: {hostname}")
                except Exception as e:
                    print(f"[Flow] Could not register {svc_type}: {e}")

        except Exception as e:
            print(f"[Flow] Failed to register service: {e}")

    def add_discovered_computer(self, name, ip, port, software="Unknown", service_type=""):
        """Called by ServiceListener when a computer is found"""
        # Don't add ourselves
        try:
            my_hostname = socket.gethostname()
            if name.startswith(my_hostname):
                return
        except:
            pass

        # Clean up service name from the display name
        clean_name = name
        for suffix in ['._juhradialmx._tcp.local.', '._logiflow._tcp.local.',
                       '._logitechflow._tcp.local.', '._logi-options._tcp.local.']:
            clean_name = clean_name.replace(suffix, '')

        self.discovered_computers[name] = {
            'name': clean_name,
            'ip': ip,
            'port': port,
            'software': software,
            'service_type': service_type
        }
        print(f"[Flow] Discovered: {clean_name} at {ip}:{port} (Software: {software})")

    def _update_computers_list(self, computers):
        """Update the list of detected computers"""
        # Clear existing items except the placeholder
        while child := self.computers_box.get_first_child():
            self.computers_box.remove(child)

        if not computers:
            # Show placeholder
            self.no_computers_label = Gtk.Label(label='No other computers detected')
            self.no_computers_label.add_css_class('dim-label')
            self.no_computers_label.set_margin_top(16)
            self.no_computers_label.set_margin_bottom(16)
            self.computers_box.append(self.no_computers_label)
        else:
            # Show detected computers
            for computer in computers:
                computer_widget = self._create_computer_widget(computer)
                self.computers_box.append(computer_widget)

    def _create_computer_widget(self, computer):
        """Create a widget for a detected computer"""
        computer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        computer_box.set_margin_start(8)
        computer_box.set_margin_end(8)

        # Status indicator
        indicator = Gtk.Box()
        indicator.set_size_request(12, 12)
        indicator.add_css_class('connection-dot')
        indicator.add_css_class('connected')
        computer_box.append(indicator)

        # Computer icon
        comp_icon = Gtk.Image.new_from_icon_name('computer-symbolic')
        comp_icon.set_pixel_size(24)
        comp_icon.add_css_class('accent-color')
        computer_box.append(comp_icon)

        # Name and status
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        name_label = Gtk.Label(label=computer.get('name', 'Unknown'))
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class('heading')
        text_box.append(name_label)

        # IP and software info row
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.set_halign(Gtk.Align.START)

        ip_label = Gtk.Label(label=computer.get('ip', ''))
        ip_label.add_css_class('dim-label')
        ip_label.add_css_class('caption')
        info_box.append(ip_label)

        # Software badge
        software = computer.get('software', 'Unknown')
        software_label = Gtk.Label(label=software)
        software_label.add_css_class('caption')
        if software == 'JuhRadialMX':
            software_label.add_css_class('accent-color')
        elif software == 'Logi Options+':
            software_label.add_css_class('warning')
        else:
            software_label.add_css_class('dim-label')
        info_box.append(software_label)

        text_box.append(info_box)

        computer_box.append(text_box)

        # Link button - show for compatible computers
        software = computer.get('software', 'Unknown')
        if software == 'JuhRadialMX':
            link_btn = Gtk.Button(label='Link')
            link_btn.add_css_class('suggested-action')
            link_btn.connect('clicked', self._on_link_clicked, computer)
            computer_box.append(link_btn)
        elif software in ('Logi Options+', 'macOS', 'Windows/Samba', 'Windows RDP', 'Linux', 'SSH Server', 'Computer'):
            # These are computers that could potentially run JuhRadialMX
            info_label = Gtk.Label(label='Install JuhRadialMX')
            info_label.set_tooltip_text('Install JuhRadialMX on this computer to enable Flow linking')
            info_label.add_css_class('dim-label')
            info_label.add_css_class('caption')
            computer_box.append(info_label)
        else:
            # Unknown devices
            pass  # Just show the device without any action button

        return computer_box

    def _on_link_clicked(self, button, computer):
        """Handle click on Link button to pair with another computer"""
        if not FLOW_MODULE_AVAILABLE:
            print("[Flow] Flow module not available")
            return

        # Get the Flow server and generate a pairing code
        server = get_flow_server()
        if not server:
            print("[Flow] Flow server not running - enable Flow first")
            return

        computer_name = computer.get('name', 'Unknown')
        computer_ip = computer.get('ip', '')
        computer_port = computer.get('port', FLOW_PORT)

        print(f"[Flow] Initiating link with {computer_name} at {computer_ip}:{computer_port}")

        # Show a pairing dialog
        self._show_pairing_dialog(computer_name, computer_ip, computer_port)

    def _show_pairing_dialog(self, computer_name, computer_ip, computer_port):
        """Show a dialog to pair with another computer"""
        # Create the dialog
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            heading=f'Link with {computer_name}',
            body=f'Enter the pairing code shown on {computer_name} to link the computers.\n\n'
                 f'If you don\'t see a pairing code, open Flow settings on the other computer.'
        )

        # Add entry for pairing code
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)

        code_entry = Gtk.Entry()
        code_entry.set_placeholder_text('Enter 6-digit pairing code')
        code_entry.set_max_length(6)
        code_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        content_box.append(code_entry)

        dialog.set_extra_child(content_box)

        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('link', 'Link')
        dialog.set_response_appearance('link', Adw.ResponseAppearance.SUGGESTED)

        def on_response(dialog, response):
            if response == 'link':
                pairing_code = code_entry.get_text().strip()
                if len(pairing_code) == 6:
                    self._complete_pairing(computer_name, computer_ip, computer_port, pairing_code)
                else:
                    print("[Flow] Invalid pairing code - must be 6 digits")

        dialog.connect('response', on_response)
        dialog.present()

    def _complete_pairing(self, computer_name, computer_ip, computer_port, pairing_code):
        """Complete the pairing process with another computer"""
        if not FLOW_MODULE_AVAILABLE:
            return

        # Create a Flow client and try to pair
        client = FlowClient(computer_ip, computer_port)
        my_hostname = socket.gethostname()

        if client.pair(pairing_code, my_hostname):
            # Save the linked computer
            linked_computers = get_linked_computers()
            linked_computers.add_computer(computer_name, computer_ip, computer_port, client.token)
            print(f"[Flow] Successfully linked with {computer_name}")

            # Show success toast
            toast = Adw.Toast(title=f'Linked with {computer_name}')
            toast.set_timeout(3)
            # Find the toast overlay and show the toast
            window = self.get_root()
            if hasattr(window, 'toast_overlay'):
                window.toast_overlay.add_toast(toast)
        else:
            print(f"[Flow] Failed to link with {computer_name}")


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


class EasySwitchPage(Gtk.ScrolledWindow):
    """Easy-Switch configuration page - shows paired hosts and current slot"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.slot_buttons = []
        self.slot_labels = []
        self.host_names = []
        self.num_hosts = 0
        self.current_host = 0
        self.daemon_proxy = None  # Store D-Bus proxy for reuse

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(32)
        content.set_margin_end(32)

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_box.set_halign(Gtk.Align.CENTER)
        header_box.set_margin_bottom(16)

        header_icon = Gtk.Image.new_from_icon_name('network-wireless-symbolic')
        header_icon.set_pixel_size(48)
        header_icon.add_css_class('accent-color')
        header_box.append(header_icon)

        header_title = Gtk.Label(label='Easy-Switch')
        header_title.add_css_class('title-1')
        header_box.append(header_title)

        header_subtitle = Gtk.Label(label='Switch between paired computers')
        header_subtitle.add_css_class('dim-label')
        header_box.append(header_subtitle)

        content.append(header_box)

        # Host Slots Card
        self.slots_card = SettingsCard('Paired Computers')

        # Will be populated by _load_host_info
        self.slots_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.slots_box.set_margin_top(8)
        self.slots_box.set_margin_bottom(8)
        self.slots_card.append(self.slots_box)

        content.append(self.slots_card)

        # Info Card
        info_card = SettingsCard('About Easy-Switch')
        info_label = Gtk.Label()
        info_label.set_markup(
            'Easy-Switch allows your mouse to connect to multiple computers.\n'
            'Use the button on your mouse to switch between paired devices.\n\n'
            '<b>Note:</b> Host names are read from the device and reflect\n'
            'the computer names set during pairing.'
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        info_card.append(info_label)

        content.append(info_card)

        self.set_child(content)

        # Load host info from D-Bus
        GLib.idle_add(self._load_host_info)

    def _create_slot_widget(self, slot_index, is_current=False):
        """Create a clickable widget for a single Easy-Switch slot"""
        # Create the content box for the button
        slot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        slot_box.set_margin_start(8)
        slot_box.set_margin_end(8)
        slot_box.set_margin_top(8)
        slot_box.set_margin_bottom(8)

        # Slot indicator
        indicator = Gtk.Box()
        indicator.set_size_request(12, 12)
        indicator.add_css_class('connection-dot')
        if is_current:
            indicator.add_css_class('connected')
        else:
            indicator.add_css_class('disconnected')
        slot_box.append(indicator)

        # Computer icon
        conn_icon = Gtk.Image.new_from_icon_name('computer-symbolic')
        conn_icon.set_pixel_size(24)
        if is_current:
            conn_icon.add_css_class('accent-color')
        else:
            conn_icon.add_css_class('dim-label')
        slot_box.append(conn_icon)

        # Name and status
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        # Get host name if available
        host_name = f'Slot {slot_index + 1}'
        if slot_index < len(self.host_names) and self.host_names[slot_index]:
            host_name = self.host_names[slot_index]

        name_label = Gtk.Label(label=host_name)
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class('heading')
        text_box.append(name_label)
        self.slot_labels.append(name_label)

        status_text = 'Connected' if is_current else 'Click to switch'
        status_label = Gtk.Label(label=status_text)
        status_label.set_halign(Gtk.Align.START)
        status_label.add_css_class('dim-label')
        status_label.add_css_class('caption')
        text_box.append(status_label)

        slot_box.append(text_box)

        # Status badge or switch indicator
        if is_current:
            badge = Gtk.Label(label='Active')
            badge.add_css_class('success')
            badge.add_css_class('badge')
            slot_box.append(badge)
        else:
            # Add arrow icon to indicate clickable
            arrow_icon = Gtk.Image.new_from_icon_name('go-next-symbolic')
            arrow_icon.set_pixel_size(16)
            arrow_icon.add_css_class('dim-label')
            slot_box.append(arrow_icon)

        # Wrap in a button for clickability
        host_button = Gtk.Button()
        host_button.add_css_class('flat')
        host_button.set_child(slot_box)
        host_button.connect('clicked', self._on_host_clicked, slot_index)

        # Make current host button less prominent (already connected)
        if is_current:
            host_button.set_sensitive(False)

        self.slot_buttons.append(host_button)
        return host_button

    def _on_host_clicked(self, button, host_index):
        """Handle click on a host slot to switch to that host"""
        if host_index == self.current_host:
            return  # Already on this host

        print(f"Switching to host {host_index}...")

        try:
            if self.daemon_proxy:
                # Call SetHost with the host index (y = uint8/byte)
                self.daemon_proxy.call_sync(
                    'SetHost',
                    GLib.Variant('(y)', (host_index,)),
                    Gio.DBusCallFlags.NONE,
                    5000,  # 5 second timeout for host switch
                    None
                )
                print(f"Successfully requested switch to host {host_index}")

                # Update current host and refresh display
                self.current_host = host_index
                self._update_slot_display()
            else:
                print("D-Bus proxy not available")
        except Exception as e:
            print(f"Failed to switch host: {e}")

    def _load_host_info(self):
        """Load host information from daemon via D-Bus"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.daemon_proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                'org.kde.juhradialmx',
                '/org/kde/juhradialmx/Daemon',
                'org.kde.juhradialmx.Daemon',
                None
            )

            # Get Easy-Switch info (num_hosts, current_host)
            try:
                result = self.daemon_proxy.call_sync('GetEasySwitchInfo', None, Gio.DBusCallFlags.NONE, 2000, None)
                if result:
                    self.num_hosts, self.current_host = result.unpack()
                    print(f"Easy-Switch: {self.num_hosts} hosts, current={self.current_host}")
            except Exception as e:
                print(f"Could not get Easy-Switch info: {e}")
                self.num_hosts = 3  # Default to 3 slots
                self.current_host = 0

            # Get host names
            try:
                result = self.daemon_proxy.call_sync('GetHostNames', None, Gio.DBusCallFlags.NONE, 2000, None)
                if result:
                    self.host_names = list(result.unpack()[0])
                    print(f"Host names: {self.host_names}")
            except Exception as e:
                print(f"Could not get host names: {e}")
                self.host_names = []

            # Update UI with slots
            self._update_slot_display()

        except Exception as e:
            print(f"Failed to connect to D-Bus: {e}")
            # Show error state
            error_label = Gtk.Label(label='Could not connect to daemon')
            error_label.add_css_class('dim-label')
            self.slots_box.append(error_label)

        return False  # Don't repeat

    def _update_slot_display(self):
        """Update the slot display with host information"""
        # Clear existing slots
        while child := self.slots_box.get_first_child():
            self.slots_box.remove(child)

        self.slot_labels = []
        self.slot_buttons = []

        # Create slot widgets (now buttons)
        num_slots = max(self.num_hosts, 3)  # Show at least 3 slots
        for i in range(num_slots):
            is_current = (i == self.current_host)
            slot_widget = self._create_slot_widget(i, is_current)
            self.slots_box.append(slot_widget)

            # Add separator except for last
            if i < num_slots - 1:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                sep.set_margin_top(4)
                sep.set_margin_bottom(4)
                self.slots_box.append(sep)


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

        # Reload config from disk to ensure we have latest values
        config.reload()

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

                # 0% means battery info unavailable (logid controls HID++)
                if percentage == 0:
                    self.battery_label.set_label('LogiOps')
                    if self.battery_icon:
                        self.battery_icon.set_from_icon_name('battery-missing-symbolic')
                    return True

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
        device_badge = Gtk.Label(label=get_device_name().upper())
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
        self.content_stack.add_named(DevicesPage(), 'devices')
        self.content_stack.add_named(EasySwitchPage(), 'easy_switch')
        self.content_stack.add_named(FlowPage(), 'flow')
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
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS  # Enables single-instance via D-Bus
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
        # Single-instance logic: check if window already exists
        windows = self.get_windows()
        if windows:
            # Window already exists - bring it to front
            windows[0].present()
            return

        # No window exists - create new one
        win = SettingsWindow(self)
        win.present()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # GTK4/Adwaita handles single-instance automatically via D-Bus
    # Using application_id='org.kde.juhradialmx.settings' with DEFAULT_FLAGS
    # If another instance is launched, it activates the existing window
    print('JuhRadial MX Settings Dashboard')
    print('  Theme: Catppuccin Mocha')
    print(f'  Size: {WINDOW_WIDTH}x{WINDOW_HEIGHT}')

    app = SettingsApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
