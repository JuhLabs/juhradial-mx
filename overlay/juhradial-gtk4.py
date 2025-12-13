#!/usr/bin/env python3
"""
JuhRadial MX - GTK4 + Layer Shell Radial Menu

Uses gtk4-layer-shell for proper Wayland overlay support.
The layer-shell protocol gives us real cursor coordinates on input events.

Flow:
1. Daemon detects button press → emits D-Bus signal
2. We inject a fake middle-click via ydotool
3. Layer-shell overlay captures the click with REAL screen coordinates
4. Show radial menu at those exact coordinates

SPDX-License-Identifier: GPL-3.0
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')

from gi.repository import Gtk, Gdk, GLib, Gio, Gtk4LayerShell
import cairo
import math
import subprocess
import os
import sys

# D-Bus constants
DBUS_NAME = "org.kde.juhradialmx"
DBUS_PATH = "/org/kde/juhradialmx/Daemon"
DBUS_INTERFACE = "org.kde.juhradialmx.Daemon"

# =============================================================================
# GEOMETRY
# =============================================================================
MENU_DIAMETER = 300
MENU_RADIUS = 150
CENTER_ZONE_RADIUS = 45
ICON_ZONE_RADIUS = 100
EDGE_MARGIN = 20

# =============================================================================
# CATPPUCCIN MOCHA PALETTE (as RGB tuples 0-1)
# =============================================================================
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))

COLORS = {
    'crust':    hex_to_rgb('#11111b'),
    'base':     hex_to_rgb('#1e1e2e'),
    'surface0': hex_to_rgb('#313244'),
    'surface1': hex_to_rgb('#45475a'),
    'surface2': hex_to_rgb('#585b70'),
    'text':     hex_to_rgb('#cdd6f4'),
    'subtext1': hex_to_rgb('#bac2de'),
    'lavender': hex_to_rgb('#b4befe'),
    'blue':     hex_to_rgb('#89b4fa'),
    'sapphire': hex_to_rgb('#74c7ec'),
    'teal':     hex_to_rgb('#94e2d5'),
    'green':    hex_to_rgb('#a6e3a1'),
    'yellow':   hex_to_rgb('#f9e2af'),
    'peach':    hex_to_rgb('#fab387'),
    'mauve':    hex_to_rgb('#cba6f7'),
    'pink':     hex_to_rgb('#f5c2e7'),
    'red':      hex_to_rgb('#f38ba8'),
}

# =============================================================================
# ACTIONS - Logitech Options+ defaults adapted for Linux
# =============================================================================
ACTIONS = [
    ("Play/Pause",   "exec",    "playerctl play-pause",           "green",    "play_pause"),
    ("New Note",     "exec",    "kwrite",                         "yellow",   "note"),
    ("Lock",         "exec",    "loginctl lock-session",          "red",      "lock"),
    ("Settings",     "settings", "",                              "mauve",    "settings"),
    ("Screenshot",   "exec",    "spectacle",                      "blue",     "screenshot"),
    ("Emoji",        "emoji",   "",                               "pink",     "emoji"),
    ("Files",        "exec",    "dolphin",                        "sapphire", "folder"),
    ("AI",           "url",     "https://claude.ai",              "teal",     "ai"),
]


class CaptureOverlay(Gtk.Window):
    """
    Fullscreen transparent layer-shell overlay for capturing cursor position.

    This uses wlr-layer-shell protocol which gives us REAL screen coordinates
    when we receive input events - this is the key to making it work on Wayland.
    """

    def __init__(self, on_position_captured):
        super().__init__()
        self.on_position_captured = on_position_captured
        self.waiting_for_click = False

        # Initialize as layer-shell surface
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

        # Anchor to all edges = fullscreen
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)

        # Exclusive zone = 0 means don't reserve space
        Gtk4LayerShell.set_exclusive_zone(self, -1)

        # Make transparent
        self.set_opacity(0.01)  # Nearly invisible but receives input

        # Create drawing area (needed for input)
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self._on_draw)
        self.set_child(self.drawing_area)

        # Button press handler - specifically for middle-click
        self.click_gesture = Gtk.GestureClick.new()
        self.click_gesture.set_button(2)  # Middle button
        self.click_gesture.connect("pressed", self._on_middle_click)
        self.drawing_area.add_controller(self.click_gesture)

        # Also catch ANY click for more reliability
        self.click_any = Gtk.GestureClick.new()
        self.click_any.set_button(0)  # Any button
        self.click_any.connect("pressed", self._on_any_click)
        self.drawing_area.add_controller(self.click_any)

        self.hide()

    def _on_draw(self, area, cr, width, height):
        """Draw transparent background"""
        cr.set_source_rgba(0, 0, 0, 0.01)
        cr.paint()

    def start_capture(self):
        """Show overlay and wait for click"""
        self.waiting_for_click = True
        self.present()
        print("Capture overlay active - waiting for click...")

    def stop_capture(self):
        """Hide the overlay"""
        self.waiting_for_click = False
        self.hide()

    def _on_middle_click(self, gesture, n_press, x, y):
        """Handle middle-click - this gives us cursor position!"""
        if self.waiting_for_click:
            print(f"Middle-click captured at ({x}, {y})")
            self.waiting_for_click = False
            self.hide()
            GLib.idle_add(self.on_position_captured, int(x), int(y))
            return True
        return False

    def _on_any_click(self, gesture, n_press, x, y):
        """Fallback: capture any click"""
        if self.waiting_for_click:
            button = gesture.get_current_button()
            print(f"Click captured (button {button}) at ({x}, {y})")
            self.waiting_for_click = False
            self.hide()
            GLib.idle_add(self.on_position_captured, int(x), int(y))
            return True
        return False


class RadialMenuWindow(Gtk.Window):
    """The radial menu overlay using layer-shell"""

    def __init__(self, on_action_executed):
        super().__init__()
        self.highlighted_slice = -1
        self.on_action_executed = on_action_executed
        self.menu_x = 0
        self.menu_y = 0

        # Initialize as layer-shell surface
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)

        # Don't anchor - we'll position with margins
        Gtk4LayerShell.set_exclusive_zone(self, -1)

        # Window setup
        self.set_default_size(MENU_DIAMETER + 24, MENU_DIAMETER + 24)

        # Drawing area
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_content_width(MENU_DIAMETER + 24)
        self.drawing_area.set_content_height(MENU_DIAMETER + 24)
        self.drawing_area.set_draw_func(self._on_draw)
        self.set_child(self.drawing_area)

        # Motion tracking
        self.motion_controller = Gtk.EventControllerMotion.new()
        self.motion_controller.connect("motion", self._on_motion)
        self.drawing_area.add_controller(self.motion_controller)

        # Click handling (button release triggers action)
        self.click_gesture = Gtk.GestureClick.new()
        self.click_gesture.connect("released", self._on_click_released)
        self.drawing_area.add_controller(self.click_gesture)

        # ESC to cancel
        self.key_controller = Gtk.EventControllerKey.new()
        self.key_controller.connect("key-pressed", self._on_key)
        self.add_controller(self.key_controller)

        self.hide()

    def show_at(self, x, y):
        """Show menu centered at screen coordinates"""
        self.menu_x = x
        self.menu_y = y
        self.highlighted_slice = -1

        # Get screen dimensions
        display = Gdk.Display.get_default()
        width = 1920
        height = 1080
        if display:
            monitors = display.get_monitors()
            if monitors.get_n_items() > 0:
                geom = monitors.get_item(0).get_geometry()
                width = geom.width
                height = geom.height

        # Calculate position with edge clamping
        half_size = (MENU_DIAMETER + 24) // 2
        x = max(half_size + EDGE_MARGIN, min(x, width - half_size - EDGE_MARGIN))
        y = max(half_size + EDGE_MARGIN, min(y, height - half_size - EDGE_MARGIN))

        # For layer-shell, we position using margins from edges
        # Calculate margins to center at (x, y)
        left_margin = x - half_size
        top_margin = y - half_size

        # Reset anchors for positioning
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, False)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, False)

        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, top_margin)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, left_margin)

        print(f"Showing menu at ({x}, {y}) with margins (left={left_margin}, top={top_margin})")
        self.present()
        self.drawing_area.queue_draw()

    def hide_menu(self, execute=True):
        """Hide menu and optionally execute action"""
        if execute and self.highlighted_slice >= 0:
            action = ACTIONS[self.highlighted_slice]
            self._execute_action(action)
        self.hide()
        if self.on_action_executed:
            self.on_action_executed()

    def _on_motion(self, controller, x, y):
        """Track mouse to highlight slices"""
        cx = (MENU_DIAMETER + 24) / 2
        cy = (MENU_DIAMETER + 24) / 2

        dx = x - cx
        dy = y - cy
        distance = math.sqrt(dx * dx + dy * dy)

        if distance < CENTER_ZONE_RADIUS or distance > MENU_RADIUS:
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        if new_slice != self.highlighted_slice:
            self.highlighted_slice = new_slice
            self.drawing_area.queue_draw()

    def _on_click_released(self, gesture, n_press, x, y):
        """Execute selected action on release"""
        self.hide_menu(execute=True)

    def _on_key(self, controller, keyval, keycode, state):
        """Handle key press (ESC to cancel)"""
        if keyval == Gdk.KEY_Escape:
            self.hide_menu(execute=False)
            return True
        return False

    def _on_draw(self, area, cr, width, height):
        """Draw the radial menu"""
        cx = width / 2
        cy = height / 2

        # Clear (transparent)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # Shadow
        cr.set_source_rgba(0, 0, 0, 0.4)
        cr.arc(cx + 4, cy + 6, MENU_RADIUS, 0, 2 * math.pi)
        cr.fill()

        # Main background
        r, g, b = COLORS['base']
        cr.set_source_rgba(r, g, b, 0.92)
        cr.arc(cx, cy, MENU_RADIUS, 0, 2 * math.pi)
        cr.fill()

        # Border
        r, g, b = COLORS['surface2']
        cr.set_source_rgba(r, g, b, 0.6)
        cr.set_line_width(2)
        cr.arc(cx, cy, MENU_RADIUS, 0, 2 * math.pi)
        cr.stroke()

        # Slices
        for i in range(8):
            self._draw_slice(cr, cx, cy, i)

        # Center
        self._draw_center(cr, cx, cy)

    def _draw_slice(self, cr, cx, cy, index):
        """Draw a single slice"""
        is_highlighted = (index == self.highlighted_slice)
        action = ACTIONS[index]
        accent = COLORS[action[3]]

        start_angle = math.radians(index * 45 - 22.5 - 90)
        end_angle = math.radians(index * 45 + 22.5 - 90)
        outer_r = MENU_RADIUS - 6
        inner_r = CENTER_ZONE_RADIUS + 6

        # Slice fill
        if is_highlighted:
            r, g, b = accent
            cr.set_source_rgba(r, g, b, 0.45)
        else:
            r, g, b = COLORS['surface0']
            cr.set_source_rgba(r, g, b, 0.4)

        cr.new_path()
        cr.arc(cx, cy, outer_r, start_angle, end_angle)
        cr.arc_negative(cx, cy, inner_r, end_angle, start_angle)
        cr.close_path()
        cr.fill()

        # Slice border
        if is_highlighted:
            r, g, b = accent
            cr.set_source_rgba(r, g, b, 0.85)
        else:
            r, g, b = COLORS['surface2']
            cr.set_source_rgba(r, g, b, 0.35)
        cr.set_line_width(1)
        cr.new_path()
        cr.arc(cx, cy, outer_r, start_angle, end_angle)
        cr.arc_negative(cx, cy, inner_r, end_angle, start_angle)
        cr.close_path()
        cr.stroke()

        # Icon position
        icon_angle = math.radians(index * 45 - 90)
        icon_x = cx + ICON_ZONE_RADIUS * math.cos(icon_angle)
        icon_y = cy + ICON_ZONE_RADIUS * math.sin(icon_angle)

        # Icon circle
        icon_radius = 22
        if is_highlighted:
            r, g, b = accent
            cr.set_source_rgba(r, g, b, 0.95)
        else:
            r, g, b = COLORS['surface1']
            cr.set_source_rgba(r, g, b, 0.85)
        cr.arc(icon_x, icon_y, icon_radius, 0, 2 * math.pi)
        cr.fill()

        # Icon
        if is_highlighted:
            r, g, b = COLORS['text']
        else:
            r, g, b = COLORS['subtext1']
        cr.set_source_rgba(r, g, b, 1.0)
        self._draw_icon(cr, icon_x, icon_y, action[4], icon_radius * 0.7)

    def _draw_icon(self, cr, cx, cy, icon_type, size):
        """Draw icon at position"""
        cr.set_line_width(2)

        if icon_type == "play_pause":
            s = size * 0.5
            cr.move_to(cx - s * 0.4, cy - s)
            cr.line_to(cx - s * 0.4, cy + s)
            cr.line_to(cx + s * 0.6, cy)
            cr.close_path()
            cr.fill()

        elif icon_type == "note":
            w, h = size * 0.6, size * 0.8
            cr.rectangle(cx - w/2, cy - h/2, w, h)
            cr.stroke()
            for i in range(3):
                y = cy - h/4 + i * size * 0.2
                cr.move_to(cx - w/3, y)
                cr.line_to(cx + w/3, y)
                cr.stroke()

        elif icon_type == "lock":
            w, h = size * 0.5, size * 0.4
            cr.rectangle(cx - w/2, cy, w, h)
            cr.stroke()
            cr.arc(cx, cy, w * 0.4, math.pi, 0)
            cr.stroke()

        elif icon_type == "settings":
            cr.arc(cx, cy, size * 0.2, 0, 2 * math.pi)
            cr.stroke()
            for i in range(8):
                angle = i * math.pi / 4
                inner, outer = size * 0.25, size * 0.4
                cr.move_to(cx + inner * math.cos(angle), cy + inner * math.sin(angle))
                cr.line_to(cx + outer * math.cos(angle), cy + outer * math.sin(angle))
                cr.stroke()

        elif icon_type == "screenshot":
            s, corner = size * 0.4, size * 0.15
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                cr.move_to(cx + dx * s, cy + dy * (s - corner))
                cr.line_to(cx + dx * s, cy + dy * s)
                cr.line_to(cx + dx * (s - corner), cy + dy * s)
            cr.stroke()
            cr.arc(cx, cy, size * 0.1, 0, 2 * math.pi)
            cr.stroke()

        elif icon_type == "emoji":
            cr.arc(cx, cy, size * 0.4, 0, 2 * math.pi)
            cr.stroke()
            cr.arc(cx - size * 0.15, cy - size * 0.1, size * 0.06, 0, 2 * math.pi)
            cr.fill()
            cr.arc(cx + size * 0.15, cy - size * 0.1, size * 0.06, 0, 2 * math.pi)
            cr.fill()
            cr.arc(cx, cy + size * 0.05, size * 0.2, 0.2, math.pi - 0.2)
            cr.stroke()

        elif icon_type == "folder":
            w, h = size * 0.6, size * 0.45
            tab_w = w * 0.3
            cr.move_to(cx - w/2, cy - h/2 + h * 0.2)
            cr.line_to(cx - w/2, cy + h/2)
            cr.line_to(cx + w/2, cy + h/2)
            cr.line_to(cx + w/2, cy - h/2 + h * 0.2)
            cr.line_to(cx - w/2 + tab_w + h * 0.1, cy - h/2 + h * 0.2)
            cr.line_to(cx - w/2 + tab_w, cy - h/2)
            cr.line_to(cx - w/2, cy - h/2)
            cr.close_path()
            cr.stroke()

        elif icon_type == "ai":
            def sparkle(x, y, s):
                cr.move_to(x, y - s)
                cr.curve_to(x + s * 0.1, y - s * 0.1, x + s * 0.1, y - s * 0.1, x + s, y)
                cr.curve_to(x + s * 0.1, y + s * 0.1, x + s * 0.1, y + s * 0.1, x, y + s)
                cr.curve_to(x - s * 0.1, y + s * 0.1, x - s * 0.1, y + s * 0.1, x - s, y)
                cr.curve_to(x - s * 0.1, y - s * 0.1, x - s * 0.1, y - s * 0.1, x, y - s)
                cr.fill()
            sparkle(cx, cy, size * 0.35)
            sparkle(cx + size * 0.3, cy - size * 0.25, size * 0.12)

    def _draw_center(self, cr, cx, cy):
        """Draw center zone"""
        r, g, b = COLORS['base']
        cr.set_source_rgba(r, g, b, 0.97)
        cr.arc(cx, cy, CENTER_ZONE_RADIUS, 0, 2 * math.pi)
        cr.fill()

        r, g, b = COLORS['surface2']
        cr.set_source_rgba(r, g, b, 0.6)
        cr.set_line_width(2)
        cr.arc(cx, cy, CENTER_ZONE_RADIUS, 0, 2 * math.pi)
        cr.stroke()

        # Label
        r, g, b = COLORS['subtext1']
        cr.set_source_rgba(r, g, b, 1.0)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)

        text = ACTIONS[self.highlighted_slice][0] if self.highlighted_slice >= 0 else "Drag"
        extents = cr.text_extents(text)
        cr.move_to(cx - extents.width / 2, cy + extents.height / 4)
        cr.show_text(text)

    def _execute_action(self, action):
        """Execute the selected action"""
        cmd_type, cmd, label = action[1], action[2], action[0]
        print(f"Executing: {label}")

        try:
            if cmd_type == "exec":
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif cmd_type == "url":
                subprocess.Popen(["xdg-open", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif cmd_type == "emoji":
                for method in [["plasma-emojier"], ["qdbus6", "org.kde.krunner", "/App", "querySingleRunner", "emoji", ""]]:
                    try:
                        subprocess.Popen(method, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        break
                    except:
                        continue
            elif cmd_type == "settings":
                subprocess.Popen(["notify-send", "JuhRadial MX", "Settings UI coming soon!", "-i", "preferences-system"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error executing action: {e}")


class JuhRadialApp(Gtk.Application):
    """Main application"""

    def __init__(self):
        super().__init__(application_id="org.kde.juhradialmx.overlay",
                        flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.capture_overlay = None
        self.menu_window = None
        self.dbus_connection = None

    def do_activate(self):
        # Create menu window
        self.menu_window = RadialMenuWindow(self._on_menu_closed)
        self.add_window(self.menu_window)

        # Create capture overlay
        self.capture_overlay = CaptureOverlay(self._on_position_captured)
        self.add_window(self.capture_overlay)

        # Setup D-Bus
        self._setup_dbus()

        print("\n" + "=" * 60)
        print("  JuhRadial MX - GTK4 + Layer Shell (Wayland Native)")
        print("=" * 60)
        print("\n  Using layer-shell for proper Wayland overlay support")
        print("  Press gesture button to activate!")
        print("\n  Actions (clockwise from top):")
        directions = ["Top", "Top-Right", "Right", "Bottom-Right",
                     "Bottom", "Bottom-Left", "Left", "Top-Left"]
        for i, action in enumerate(ACTIONS):
            print(f"    {directions[i]:12} -> {action[0]}")
        print("\n" + "=" * 60 + "\n")

    def _setup_dbus(self):
        """Setup D-Bus signal listener"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            bus.signal_subscribe(
                DBUS_NAME, DBUS_INTERFACE, "MenuRequested", DBUS_PATH,
                None, Gio.DBusSignalFlags.NONE, self._on_menu_requested
            )

            bus.signal_subscribe(
                DBUS_NAME, DBUS_INTERFACE, "HideMenu", DBUS_PATH,
                None, Gio.DBusSignalFlags.NONE, self._on_hide_menu
            )

            self.dbus_connection = bus
            print("D-Bus: Connected and listening")

        except Exception as e:
            print(f"D-Bus setup failed: {e}")
            print("Running in demo mode...")
            GLib.timeout_add(2000, self._demo_show)

    def _on_menu_requested(self, connection, sender, path, interface, signal, params):
        """Handle MenuRequested signal from daemon"""
        daemon_x, daemon_y = params.unpack()
        print(f"MenuRequested (daemon: {daemon_x}, {daemon_y})")

        # Inject middle-click to capture real cursor position
        self._inject_click_and_capture()

    def _on_hide_menu(self, connection, sender, path, interface, signal, params):
        """Handle HideMenu signal"""
        print("HideMenu signal received")
        if self.menu_window:
            self.menu_window.hide_menu(execute=True)

    def _inject_click_and_capture(self):
        """Inject middle-click and capture position via overlay"""
        # Show capture overlay first
        self.capture_overlay.start_capture()

        # Then inject middle-click via ydotool (after brief delay for overlay to appear)
        GLib.timeout_add(10, self._do_inject)

    def _do_inject(self):
        """Actually inject the click"""
        try:
            subprocess.Popen(["ydotool", "click", "0xC0"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Injected middle-click via ydotool")
        except Exception as e:
            print(f"ydotool failed: {e}")
            # Fallback to screen center
            self._fallback_position()
        return False

    def _fallback_position(self):
        """Fallback to screen center if ydotool fails"""
        display = Gdk.Display.get_default()
        if display:
            monitors = display.get_monitors()
            if monitors.get_n_items() > 0:
                geom = monitors.get_item(0).get_geometry()
                self._on_position_captured(geom.width // 2, geom.height // 2)

    def _on_position_captured(self, x, y):
        """Called when cursor position is captured"""
        print(f"Position captured: ({x}, {y})")
        self.capture_overlay.stop_capture()
        if self.menu_window:
            self.menu_window.show_at(x, y)
        return False

    def _on_menu_closed(self):
        """Called when menu is closed"""
        pass

    def _demo_show(self):
        """Demo: show menu at center"""
        self._fallback_position()
        return False


def main():
    # Force Wayland backend - MUST be set before any GTK initialization
    os.environ["GDK_BACKEND"] = "wayland"

    # Check if we're actually on Wayland
    if "WAYLAND_DISPLAY" not in os.environ:
        print("WARNING: Not running on Wayland, layer-shell won't work!")
        print("Falling back to X11 mode...")
        os.environ["GDK_BACKEND"] = "x11"

    app = JuhRadialApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
