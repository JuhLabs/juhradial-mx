#!/usr/bin/env python3
"""
JuhRadial MX - Simple D-Bus Overlay

A lightweight Python/GTK4 overlay that listens for D-Bus signals
from juhradiald and displays the radial menu.

This replaces the KWin script approach for more reliable Wayland support.
"""

import gi
import sys
import signal
import os
import json

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

from gi.repository import Gtk, Gdk, GLib
import dbus
import dbus.mainloop.glib
from dbus.mainloop.glib import DBusGMainLoop
import math
import cairo

# Profile path
PROFILE_PATH = os.path.expanduser("~/.config/juhradial/profiles.json")

# D-Bus constants
DBUS_SERVICE = "org.kde.juhradialmx"
DBUS_PATH = "/org/kde/juhradialmx/Daemon"
DBUS_INTERFACE = "org.kde.juhradialmx.Daemon"

# Menu dimensions
MENU_DIAMETER = 280
CENTER_ZONE_RADIUS = 40
MENU_RADIUS = MENU_DIAMETER // 2

# Theme colors (Catppuccin Mocha)
BG_COLOR = (0.12, 0.12, 0.18, 0.85)  # #1e1e2e with 85% opacity
SURFACE_COLOR = (0.19, 0.20, 0.27, 0.4)  # #313244
ACCENT_COLOR = (0.80, 0.65, 0.97, 1.0)  # #cba6f7
TEXT_COLOR = (0.80, 0.84, 0.96, 1.0)  # #cdd6f4
BORDER_COLOR = (0.27, 0.28, 0.35, 0.6)  # #45475a


class RadialMenuOverlay(Gtk.Window):
    """Radial menu overlay window"""

    def __init__(self, app):
        super().__init__(application=app)
        self.set_decorated(False)
        self.set_default_size(MENU_DIAMETER, MENU_DIAMETER)
        self.set_resizable(False)

        # Make window transparent
        self.set_opacity(0.0)

        # Slice state
        self.highlighted_slice = -1

        # Load profile
        self.profile = self._load_profile()
        self.slices = self.profile.get("slices", [])

        # Fallback labels if profile is empty
        if not self.slices:
            self.slices = [
                {"label": d, "icon": d, "type": "none", "value": ""}
                for d in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            ]

        # Create drawing area
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self.on_draw)
        self.set_child(self.drawing_area)

        # Track mouse motion
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self.on_motion)
        self.add_controller(motion)

        # Connect to D-Bus signals
        self._setup_dbus()

        print(f"RadialMenuOverlay: Loaded {len(self.slices)} slices from profile")
        print("RadialMenuOverlay: Initialized, waiting for D-Bus signals...")

    def _load_profile(self):
        """Load the default profile from config"""
        try:
            if os.path.exists(PROFILE_PATH):
                with open(PROFILE_PATH, 'r') as f:
                    data = json.load(f)
                profiles = data.get("profiles", [])
                # Find default profile
                for p in profiles:
                    if p.get("name") == "default":
                        print(f"RadialMenuOverlay: Loaded profile '{p.get('name')}'")
                        return p
                # Return first profile if no default
                if profiles:
                    return profiles[0]
        except Exception as e:
            print(f"RadialMenuOverlay: Error loading profile: {e}")
        return {"slices": []}

    def _setup_dbus(self):
        """Subscribe to D-Bus signals from daemon"""
        try:
            bus = dbus.SessionBus()

            # Subscribe to MenuRequested signal
            bus.add_signal_receiver(
                self._on_menu_requested,
                signal_name="MenuRequested",
                dbus_interface=DBUS_INTERFACE,
                path=DBUS_PATH
            )

            # Subscribe to HideMenu signal
            bus.add_signal_receiver(
                self._on_hide_menu,
                signal_name="HideMenu",
                dbus_interface=DBUS_INTERFACE,
                path=DBUS_PATH
            )

            print("RadialMenuOverlay: D-Bus signals connected")

        except Exception as e:
            print(f"RadialMenuOverlay: D-Bus error: {e}")

    def _on_menu_requested(self, x, y):
        """Handle MenuRequested signal from daemon"""
        print(f"RadialMenuOverlay: MenuRequested at ({x}, {y})")
        self.show_at(int(x), int(y))

    def _on_hide_menu(self):
        """Handle HideMenu signal from daemon"""
        print("RadialMenuOverlay: HideMenu received")
        self.hide_menu()

    def show_at(self, x, y):
        """Show the menu centered at screen coordinates"""
        # Position window so menu is centered on cursor
        self.move_to(x - MENU_RADIUS, y - MENU_RADIUS)
        self.set_opacity(1.0)
        self.present()
        self.highlighted_slice = -1
        self.drawing_area.queue_draw()
        print(f"RadialMenuOverlay: Shown at ({x}, {y})")

    def move_to(self, x, y):
        """Move window to position (GTK4 doesn't have move(), use surface)"""
        # In Wayland, window positioning is handled by the compositor
        # For X11, we can try to position via realize
        surface = self.get_surface()
        if surface:
            try:
                # This may not work on Wayland, but worth trying
                surface.set_device_cursor(None, None)
            except:
                pass

        # Store position for reference
        self._pos_x = x
        self._pos_y = y

    def hide_menu(self):
        """Hide the menu"""
        self.set_opacity(0.0)
        self.hide()
        self.highlighted_slice = -1
        print("RadialMenuOverlay: Hidden")

    def on_motion(self, controller, x, y):
        """Handle mouse motion within the menu"""
        if self.get_opacity() < 0.5:
            return

        # Calculate which slice cursor is in
        new_slice = self._calculate_slice(x, y)

        if new_slice != self.highlighted_slice:
            self.highlighted_slice = new_slice
            self.drawing_area.queue_draw()

    def _calculate_slice(self, x, y):
        """Calculate which slice the cursor is in"""
        dx = x - MENU_RADIUS
        dy = y - MENU_RADIUS

        distance = math.sqrt(dx * dx + dy * dy)

        # Center zone
        if distance < CENTER_ZONE_RADIUS:
            return -1

        # Calculate angle (0 = North, clockwise)
        angle = math.degrees(math.atan2(dx, -dy))
        angle = (angle + 360) % 360

        # Map to slice (each 45 degrees, offset by 22.5 for centering)
        return int(((angle + 22.5) % 360) / 45)

    def on_draw(self, area, cr, width, height):
        """Draw the radial menu"""
        cx, cy = width / 2, height / 2

        # Clear with transparency
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # Draw background circle
        cr.arc(cx, cy, MENU_RADIUS - 2, 0, 2 * math.pi)
        cr.set_source_rgba(*BG_COLOR)
        cr.fill_preserve()
        cr.set_source_rgba(*BORDER_COLOR)
        cr.set_line_width(1)
        cr.stroke()

        # Draw 8 slices
        for i in range(8):
            is_highlighted = (i == self.highlighted_slice)
            self._draw_slice(cr, cx, cy, i, is_highlighted)

        # Draw center zone
        cr.arc(cx, cy, CENTER_ZONE_RADIUS, 0, 2 * math.pi)
        cr.set_source_rgba(*SURFACE_COLOR)
        cr.fill_preserve()
        cr.set_source_rgba(*BORDER_COLOR)
        cr.stroke()

        # Center text
        cr.set_source_rgba(*TEXT_COLOR)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        text = "Release" if self.highlighted_slice >= 0 else "Drag"
        extents = cr.text_extents(text)
        cr.move_to(cx - extents.width / 2, cy + extents.height / 2)
        cr.show_text(text)

    def _draw_slice(self, cr, cx, cy, index, is_highlighted):
        """Draw a single slice wedge"""
        inner_radius = CENTER_ZONE_RADIUS + 2
        outer_radius = MENU_RADIUS - 10

        # Calculate angles (each slice is 45 degrees)
        start_angle = math.radians(index * 45 - 112.5)
        end_angle = math.radians(index * 45 - 67.5)

        # Draw wedge path
        cr.new_path()
        cr.arc(cx, cy, outer_radius, start_angle, end_angle)
        cr.arc_negative(cx, cy, inner_radius, end_angle, start_angle)
        cr.close_path()

        # Fill
        if is_highlighted:
            cr.set_source_rgba(SURFACE_COLOR[0], SURFACE_COLOR[1], SURFACE_COLOR[2], 0.5)
        else:
            cr.set_source_rgba(*SURFACE_COLOR)
        cr.fill_preserve()

        # Border
        if is_highlighted:
            cr.set_source_rgba(*ACCENT_COLOR)
            cr.set_line_width(2)
        else:
            cr.set_source_rgba(*BORDER_COLOR)
            cr.set_line_width(1)
        cr.stroke()

        # Get slice data from profile
        slice_data = self.slices[index] if index < len(self.slices) else {}
        icon = slice_data.get("icon", "?")
        label = slice_data.get("label", "")

        # Draw icon (emoji)
        icon_angle = math.radians(index * 45 - 90)
        icon_distance = (inner_radius + outer_radius) / 2 - 5
        icon_x = cx + math.cos(icon_angle) * icon_distance
        icon_y = cy + math.sin(icon_angle) * icon_distance

        cr.set_source_rgba(TEXT_COLOR[0], TEXT_COLOR[1], TEXT_COLOR[2], 1.0 if is_highlighted else 0.7)
        cr.select_font_face("Noto Color Emoji", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(22)
        extents = cr.text_extents(icon)
        cr.move_to(icon_x - extents.width / 2, icon_y + extents.height / 2)
        cr.show_text(icon)

        # Draw label below icon (if highlighted)
        if is_highlighted and label:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(9)
            cr.set_source_rgba(TEXT_COLOR[0], TEXT_COLOR[1], TEXT_COLOR[2], 0.9)
            label_y = icon_y + 18
            extents = cr.text_extents(label)
            cr.move_to(icon_x - extents.width / 2, label_y)
            cr.show_text(label)


class RadialApp(Gtk.Application):
    """GTK4 Application wrapper"""

    def __init__(self):
        super().__init__(application_id="org.juhradialmx.overlay")

    def do_activate(self):
        self.win = RadialMenuOverlay(self)
        # Don't show initially - wait for D-Bus signal
        print("RadialApp: Ready, waiting for D-Bus signals...")


def main():
    # Initialize D-Bus main loop
    DBusGMainLoop(set_as_default=True)

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    print("JuhRadial MX Overlay starting...")
    print(f"  Listening on D-Bus: {DBUS_SERVICE}")

    app = RadialApp()
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
