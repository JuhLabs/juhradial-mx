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
            "intensity": 50,
            "per_event": {
                "menu_appear": 20,
                "slice_change": 40,
                "confirm": 80,
                "invalid": 30
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
# CATPPUCCIN MOCHA PALETTE
# =============================================================================
COLORS = {
    'crust':     '#11111b',
    'mantle':    '#181825',
    'base':      '#1e1e2e',
    'surface0':  '#313244',
    'surface1':  '#45475a',
    'surface2':  '#585b70',
    'overlay0':  '#6c7086',
    'overlay1':  '#7f849c',
    'text':      '#cdd6f4',
    'subtext1':  '#bac2de',
    'subtext0':  '#a6adc8',
    'lavender':  '#b4befe',
    'blue':      '#89b4fa',
    'sapphire':  '#74c7ec',
    'teal':      '#94e2d5',
    'green':     '#a6e3a1',
    'yellow':    '#f9e2af',
    'peach':     '#fab387',
    'maroon':    '#eba0ac',
    'red':       '#f38ba8',
    'mauve':     '#cba6f7',
    'pink':      '#f5c2e7',
    'flamingo':  '#f2cdcd',
    'rosewater': '#f5e0dc',
}

# =============================================================================
# WINDOW CONFIGURATION
# =============================================================================
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800

# =============================================================================
# MX MASTER 4 BUTTON DEFINITIONS
# Positions adjusted for real mouse photo (3/4 angle view from left)
# Coordinates are normalized (0-1) relative to the drawing area
# Dots should be placed directly ON the physical buttons
# =============================================================================
MOUSE_BUTTONS = {
    'middle': {
        'name': 'Middle button',
        'action': 'Middle Click',
        'pos': (0.30, 0.02),  # Scroll wheel - top center
    },
    'shift_wheel': {
        'name': 'Shift wheel mode',
        'action': 'SmartShift',
        'pos': (0.38, 0.11),  # Mode shift button - behind scroll wheel
    },
    'forward': {
        'name': 'Forward',
        'action': 'Forward',
        'pos': (0.12, 0.30),  # Upper thumb button - left side
    },
    'back': {
        'name': 'Back',
        'action': 'Back',
        'pos': (0.18, 0.48),  # Lower thumb button - below forward
    },
    'horizontal_scroll': {
        'name': 'Horizontal scroll',
        'action': 'Scroll Left/Right',
        'pos': (0.14, 0.38),  # Thumb wheel
    },
    'gesture': {
        'name': 'Gestures',
        'action': 'Virtual desktops',
        'pos': (0.20, 0.58),  # Gesture button - textured thumb rest area
    },
    'thumb': {
        'name': 'Show Actions Ring',
        'action': 'Radial Menu',
        'pos': (0.25, 0.70),  # Lower thumb rest - radial menu trigger
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
# CSS STYLESHEET - CATPPUCCIN MOCHA
# =============================================================================
CSS = f"""
/* Main window */
window.settings-window {{
    background: {COLORS['crust']};
}}

/* Header bar */
.header-area {{
    background: {COLORS['mantle']};
    padding: 16px 24px;
    border-bottom: 1px solid {COLORS['surface0']};
}}

.device-title {{
    font-size: 24px;
    font-weight: bold;
    color: {COLORS['text']};
}}

.add-app-btn {{
    background: transparent;
    color: {COLORS['lavender']};
    border: none;
    padding: 8px 16px;
    font-weight: 500;
}}

.add-app-btn:hover {{
    background: {COLORS['surface0']};
    border-radius: 6px;
}}

/* Sidebar navigation */
.sidebar {{
    background: {COLORS['mantle']};
    padding: 8px;
    min-width: 220px;
}}

.nav-item {{
    padding: 14px 16px;
    border-radius: 8px;
    margin: 2px 0;
    color: {COLORS['subtext0']};
    font-weight: 500;
    font-size: 13px;
}}

.nav-item:hover {{
    background: {COLORS['surface0']};
    color: {COLORS['text']};
}}

.nav-item.active {{
    background: {COLORS['lavender']};
    color: {COLORS['crust']};
}}

.nav-item.active:hover {{
    background: {COLORS['lavender']};
}}

/* Main content area */
.content-area {{
    background: {COLORS['base']};
}}

/* Mouse visualization area */
.mouse-area {{
    background: {COLORS['base']};
    padding: 40px;
}}

/* Button labels on mouse */
.button-label {{
    background: {COLORS['text']};
    color: {COLORS['crust']};
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}

.button-label.highlighted {{
    background: {COLORS['green']};
    color: {COLORS['crust']};
}}

/* Settings cards */
.settings-card {{
    background: {COLORS['surface0']};
    border-radius: 12px;
    padding: 20px;
    margin: 12px;
}}

.card-title {{
    font-size: 16px;
    font-weight: bold;
    color: {COLORS['text']};
    margin-bottom: 16px;
}}

/* Settings rows */
.setting-row {{
    padding: 12px 8px;
    border-bottom: 1px solid {COLORS['surface1']};
    border-radius: 8px;
    margin: 2px 0;
    transition: background-color 150ms ease;
}}

.setting-row:hover {{
    background-color: {COLORS['surface1']};
}}

.setting-row:last-child {{
    border-bottom: none;
}}

.setting-label {{
    color: {COLORS['text']};
    font-size: 14px;
}}

.setting-value {{
    color: {COLORS['subtext0']};
    font-size: 13px;
}}

/* Bottom status bar */
.status-bar {{
    background: {COLORS['mantle']};
    padding: 12px 24px;
    border-top: 1px solid {COLORS['surface0']};
}}

.battery-indicator {{
    color: {COLORS['green']};
    font-weight: 500;
}}

.connection-status {{
    color: {COLORS['subtext0']};
    font-size: 13px;
}}

/* Switches */
switch {{
    background: {COLORS['surface1']};
    border-radius: 14px;
    min-width: 48px;
    min-height: 26px;
}}

switch:checked {{
    background: {COLORS['lavender']};
}}

switch slider {{
    background: {COLORS['text']};
    border-radius: 12px;
    min-width: 22px;
    min-height: 22px;
    margin: 2px;
}}

/* Scales/Sliders */
scale trough {{
    background: {COLORS['surface1']};
    border-radius: 4px;
    min-height: 6px;
}}

scale highlight {{
    background: {COLORS['lavender']};
    border-radius: 4px;
}}

scale slider {{
    background: {COLORS['text']};
    border-radius: 50%;
    min-width: 18px;
    min-height: 18px;
}}

/* Scrollbar */
scrollbar {{
    background: transparent;
}}

scrollbar slider {{
    background: {COLORS['surface2']};
    border-radius: 4px;
    min-width: 8px;
}}

scrollbar slider:hover {{
    background: {COLORS['overlay0']};
}}

/* Button styling */
.primary-btn {{
    background: {COLORS['lavender']};
    color: {COLORS['crust']};
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: 600;
}}

.primary-btn:hover {{
    background: {COLORS['blue']};
}}

.danger-btn {{
    background: transparent;
    color: {COLORS['red']};
    border: 1px solid {COLORS['red']};
    border-radius: 8px;
    padding: 10px 20px;
}}

.danger-btn:hover {{
    background: rgba(243, 139, 168, 0.1);
}}
"""


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

        self.set_content_width(600)
        self.set_content_height(500)
        self.set_draw_func(self._draw)

        # Load mouse image
        image_paths = [
            os.path.join(os.path.dirname(__file__), '../assets/devices/mx_master_4.png'),
            os.path.join(os.path.dirname(__file__), 'assets/devices/mx_master_4.png'),
            '/usr/share/juhradialmx/devices/mx_master_4.png',
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

    def _on_motion(self, controller, x, y):
        # Use image rect for button positioning
        img_x, img_y, img_w, img_h = self.img_rect

        # Check if hovering over any button region
        old_hovered = self.hovered_button
        self.hovered_button = None

        for btn_id, btn_info in MOUSE_BUTTONS.items():
            btn_x = img_x + btn_info['pos'][0] * img_w
            btn_y = img_y + btn_info['pos'][1] * img_h

            # Check distance from button dot
            dist = math.sqrt((x - btn_x)**2 + (y - btn_y)**2)
            if dist < 30:  # Hover radius for dot
                self.hovered_button = btn_id
                break

            # Also check if hovering over the label box (offset to the right)
            label_x = btn_x + 20
            label_y = btn_y - 20  # Approximate label center
            label_width = 120  # Approximate label width
            label_height = 30  # Approximate label height

            if (label_x <= x <= label_x + label_width and
                label_y <= y <= label_y + label_height):
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

        # Measure text
        cr.select_font_face("Sans", 0, 1 if is_hovered else 0)
        cr.set_font_size(12)
        extents = cr.text_extents(label)

        padding_x = 12
        padding_y = 8
        box_width = extents.width + padding_x * 2
        box_height = extents.height + padding_y * 2

        # Draw connector dot
        cr.set_source_rgba(0.8, 0.8, 0.9, 0.8)
        cr.arc(x, y, 4, 0, 2 * math.pi)
        cr.fill()

        # Offset label position
        label_x = x + 20
        label_y = y - box_height / 2

        # Draw label background
        if is_hovered:
            cr.set_source_rgba(0.65, 0.89, 0.63, 1)  # Green
        else:
            cr.set_source_rgba(0.95, 0.95, 0.97, 1)  # White

        # Rounded rectangle
        radius = 6
        cr.new_path()
        cr.arc(label_x + radius, label_y + radius, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + box_height - radius, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius, label_y + box_height - radius, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.fill()

        # Draw shadow
        cr.set_source_rgba(0, 0, 0, 0.15)
        cr.new_path()
        cr.arc(label_x + radius + 2, label_y + radius + 2, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius + 2, label_y + radius + 2, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius + 2, label_y + box_height - radius + 2, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius + 2, label_y + box_height - radius + 2, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.fill()

        # Draw text
        cr.set_source_rgba(0.07, 0.07, 0.1, 1)  # Dark text
        cr.move_to(label_x + padding_x, label_y + padding_y + extents.height)
        cr.show_text(label)

        # Draw connector line
        cr.set_source_rgba(0.8, 0.8, 0.9, 0.5)
        cr.set_line_width(1)
        cr.move_to(x + 4, y)
        cr.line_to(label_x, y)
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
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(f'Configure {button_info["name"]}')
        self.set_default_size(400, 500)

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda _: self.close())
        header.pack_start(cancel_btn)

        content.append(header)

        # Scrollable action list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        list_box.add_css_class('boxed-list')
        list_box.set_margin_start(20)
        list_box.set_margin_end(20)
        list_box.set_margin_top(20)
        list_box.set_margin_bottom(20)

        # Find current action
        current_action = button_info.get('action', '')

        for action_id, action_name in BUTTON_ACTIONS:
            row = Adw.ActionRow()
            row.set_title(action_name)
            row.action_id = action_id

            # Check mark for current selection
            if action_name == current_action:
                check = Gtk.Image.new_from_icon_name('object-select-symbolic')
                check.add_css_class('accent')
                row.add_suffix(check)
                list_box.select_row(row)

            list_box.append(row)

        list_box.connect('row-activated', self._on_row_activated)
        scrolled.set_child(list_box)
        content.append(scrolled)

        self.set_content(content)

    def _on_row_activated(self, list_box, row):
        if hasattr(row, 'action_id'):
            action_id = row.action_id
            action_name = row.get_title()

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
    """Buttons configuration page"""

    def __init__(self, on_button_config=None, parent_window=None):
        super().__init__()
        self.on_button_config = on_button_config
        self.parent_window = parent_window
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Button assignments card
        card = SettingsCard('Button Assignments')
        self.button_rows = {}

        for btn_id, btn_info in MOUSE_BUTTONS.items():
            row = SettingRow(btn_info['name'], f"Currently: {btn_info['action']}")

            # Arrow button - connect to callback
            arrow = Gtk.Button()
            arrow.set_child(Gtk.Image.new_from_icon_name('go-next-symbolic'))
            arrow.add_css_class('flat')
            arrow.connect('clicked', lambda _, bid=btn_id: self._on_button_click(bid))
            row.set_control(arrow)

            # Make entire row clickable
            row_click = Gtk.GestureClick()
            row_click.connect('released', lambda g, n, x, y, bid=btn_id: self._on_button_click(bid))
            row.add_controller(row_click)

            self.button_rows[btn_id] = row
            card.append(row)

        content.append(card)

        # Radial menu card
        radial_card = SettingsCard('Radial Menu Configuration')

        radial_row = SettingRow('Configure Actions Ring', 'Customize the 8 actions in your radial menu')
        configure_btn = Gtk.Button(label='Configure')
        configure_btn.add_css_class('primary-btn')
        configure_btn.connect('clicked', lambda _: self._on_configure_radial())
        radial_row.set_control(configure_btn)
        radial_card.append(radial_row)

        content.append(radial_card)

        self.set_child(content)

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
        for btn_id, row in self.button_rows.items():
            if btn_id in MOUSE_BUTTONS:
                # Find and update the description label
                text_box = row.get_first_child()
                if text_box:
                    children = []
                    child = text_box.get_first_child()
                    while child:
                        children.append(child)
                        child = child.get_next_sibling()
                    if len(children) > 1:
                        children[1].set_text(f"Currently: {MOUSE_BUTTONS[btn_id]['action']}")


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
        # Apply immediately via gsettings
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
    """Haptic feedback settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        card = SettingsCard('Haptic Feedback')

        enable_row = SettingRow('Enable Haptic Feedback', 'Feel subtle vibrations when scrolling')
        enable_switch = Gtk.Switch()
        enable_switch.set_active(config.get('haptics', 'enabled', default=True))
        enable_switch.connect('state-set', lambda s, state: config.set('haptics', 'enabled', state) or False)
        enable_row.set_control(enable_switch)
        card.append(enable_row)

        intensity_row = SettingRow('Feedback Intensity')
        intensity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        intensity_scale.set_value(config.get('haptics', 'intensity', default=50))
        intensity_scale.set_size_request(200, -1)
        intensity_scale.set_draw_value(True)
        intensity_scale.connect('value-changed', lambda s: config.set('haptics', 'intensity', int(s.get_value())))
        intensity_row.set_control(intensity_scale)
        card.append(intensity_row)

        content.append(card)

        # Per-event haptics
        events_card = SettingsCard('Per-Event Intensity')

        event_settings = [
            ('menu_appear', 'Menu Appear', 'Vibration when menu opens'),
            ('slice_change', 'Slice Change', 'Vibration when hovering different slices'),
            ('confirm', 'Confirm Selection', 'Vibration when selecting an action'),
            ('invalid', 'Invalid Action', 'Vibration for invalid actions'),
        ]

        for key, label, desc in event_settings:
            row = SettingRow(label, desc)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            scale.set_value(config.get('haptics', 'per_event', key, default=50))
            scale.set_size_request(150, -1)
            scale.set_draw_value(False)
            scale.connect('value-changed', lambda s, k=key: config.set('haptics', 'per_event', k, int(s.get_value())))
            row.set_control(scale)
            events_card.append(row)

        content.append(events_card)

        self.set_child(content)


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

        theme_row = SettingRow('Theme', 'Choose the color theme for the radial menu')
        theme_dropdown = Gtk.DropDown()
        theme_options = Gtk.StringList.new([
            'Catppuccin Mocha',   # Dark
            'Catppuccin Latte',   # Light
            'Nord',               # Dark
            'Dracula',            # Dark
            'Light',              # Clean white
            'Solarized Light',    # Light
            'GitHub Light',       # Light
            'System'
        ])
        theme_dropdown.set_model(theme_options)
        # Set current theme
        current_theme = config.get('theme', default='catppuccin-mocha')
        theme_map = {
            'catppuccin-mocha': 0,
            'catppuccin-latte': 1,
            'nord': 2,
            'dracula': 3,
            'light': 4,
            'solarized-light': 5,
            'github-light': 6,
            'system': 7
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

        # Device info
        info_card = SettingsCard('Device Information')

        info_items = [
            ('Device', 'MX Master 4'),
            ('Serial', 'AB12-CD34-EF56'),
            ('Firmware', '12.00.008'),
            ('Connection', 'Bolt USB Receiver'),
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
        """Handle theme selection change"""
        import subprocess

        theme_values = [
            'catppuccin-mocha',
            'catppuccin-latte',
            'nord',
            'dracula',
            'light',
            'solarized-light',
            'github-light',
            'system'
        ]
        selected = dropdown.get_selected()
        if 0 <= selected < len(theme_values):
            theme = theme_values[selected]
            config.set('theme', theme)
            print(f"Theme changed to: {theme}")

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

        # Start battery update timer (every 10 seconds for responsive charging status)
        GLib.timeout_add_seconds(10, self._update_battery)
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
        """Create the title widget with logo and app name for the header bar"""
        # Container for logo + text
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title_box.set_valign(Gtk.Align.CENTER)

        # JuhRadial MX header: logo icon + text
        script_dir = Path(__file__).resolve().parent
        logo_paths = [
            script_dir.parent / 'docs' / 'radiallogo_icon.png',
            script_dir / 'assets' / 'radiallogo_icon.png',
            Path('/usr/share/juhradial/radiallogo_icon.png'),
        ]

        # Load logo icon with proper scaling
        from gi.repository import GdkPixbuf
        for img_path in logo_paths:
            if img_path.exists():
                try:
                    # Load and scale to 28px height, preserve aspect ratio
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(img_path), -1, 28, True
                    )
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    logo_widget = Gtk.Picture.new_for_paintable(texture)
                    logo_widget.set_valign(Gtk.Align.CENTER)
                    title_box.append(logo_widget)
                    print(f"Header logo loaded from: {img_path}")
                except Exception as e:
                    print(f"Failed to load header logo: {e}")
                break

        # Add text label
        title = Gtk.Label(label='JuhRadial MX')
        title.add_css_class('title-2')
        title.set_valign(Gtk.Align.CENTER)
        title_box.append(title)

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
        self.buttons_settings = ButtonsPage(on_button_config=self._on_mouse_button_click, parent_window=self)
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

        # Battery
        battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Store as instance variables for D-Bus updates
        self.battery_label = Gtk.Label(label='--')
        self.battery_label.add_css_class('battery-indicator')
        battery_box.append(self.battery_label)

        self.battery_icon = Gtk.Image.new_from_icon_name('battery-good-symbolic')
        battery_box.append(self.battery_icon)

        # Bolt indicator
        bolt_icon = Gtk.Image.new_from_icon_name('bluetooth-active-symbolic')
        battery_box.append(bolt_icon)

        status.append(battery_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        status.append(spacer)

        # Connection status
        conn_label = Gtk.Label(label='Connected via Bolt USB Receiver')
        conn_label.add_css_class('connection-status')
        status.append(conn_label)

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
