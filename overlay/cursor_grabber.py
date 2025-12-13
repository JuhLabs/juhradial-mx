#!/usr/bin/env python3
"""
JuhRadial MX - GTK4 Layer Shell Cursor Grabber

Uses gtk4-layer-shell with BOTTOM layer for non-blocking cursor position capture.
This overlay is invisible and click-through by default. When activated by the
daemon (via temp file), it temporarily captures one click to get cursor coordinates,
then immediately returns to click-through mode.

Key features:
- Layer::BOTTOM - sits below all windows, never blocks
- Empty input region by default - all clicks pass through
- Temporary input capture only when activated
- Emits D-Bus ShowMenu(x, y) signal after capturing coordinates

SPDX-License-Identifier: GPL-3.0
"""

# CRITICAL: Load gtk4-layer-shell BEFORE importing GTK to fix linking order
# See: https://github.com/wmww/gtk4-layer-shell/blob/main/linking.md
# Must use RTLD_GLOBAL so symbols are available to subsequently loaded libraries
from ctypes import CDLL, RTLD_GLOBAL
import os

# Force Wayland backend for GTK
os.environ['GDK_BACKEND'] = 'wayland'

try:
    CDLL('libgtk4-layer-shell.so', mode=RTLD_GLOBAL)
    print("Preloaded libgtk4-layer-shell.so successfully")
except OSError as e:
    print(f"WARNING: Could not preload libgtk4-layer-shell.so: {e}")

import gi
import sys
import signal
import os
import time

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

# Try to load gtk4-layer-shell, fall back to basic mode if not available
try:
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk4LayerShell
    HAS_LAYER_SHELL = True
except (ValueError, ImportError):
    HAS_LAYER_SHELL = False
    print("WARNING: gtk4-layer-shell not available, using fallback mode")

from gi.repository import Gtk, Gdk, GLib
import dbus
import dbus.mainloop.glib

# Activation file - daemon creates this to signal capture should happen
ACTIVATE_FILE = "/tmp/juhradial-grabber-active"

# D-Bus connection
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
proxy = None


def get_proxy():
    """Get or create D-Bus proxy to daemon"""
    global proxy
    if proxy is None:
        try:
            proxy = bus.get_object("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon")
        except Exception as e:
            print(f"D-Bus proxy error: {e}")
    return proxy


def is_active():
    """Check if grabber should process clicks (activation file exists and is recent)"""
    try:
        if os.path.exists(ACTIVATE_FILE):
            mtime = os.path.getmtime(ACTIVATE_FILE)
            # Active for 500ms max
            if time.time() - mtime < 0.5:
                return True
            else:
                # Clean up stale file
                try:
                    os.unlink(ACTIVATE_FILE)
                except:
                    pass
    except:
        pass
    return False


class CursorGrabber(Gtk.Window):
    """
    Fullscreen transparent layer-shell overlay for cursor position tracking.

    Tracks mouse motion continuously and reports position when daemon requests it.
    Uses OVERLAY layer with input passthrough so it never blocks normal input.
    """

    def __init__(self, app):
        super().__init__(application=app)
        self.set_decorated(False)
        self._capturing = False  # Track capture state

        # Current cursor position (tracked via motion events)
        self._cursor_x = 0
        self._cursor_y = 0

        # Get total screen bounds across all monitors
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        max_w, max_h = 0, 0
        for i in range(monitors.get_n_items()):
            geo = monitors.get_item(i).get_geometry()
            max_w = max(max_w, geo.x + geo.width)
            max_h = max(max_h, geo.y + geo.height)

        self.screen_width = max_w
        self.screen_height = max_h
        self.set_default_size(max_w, max_h)

        if HAS_LAYER_SHELL:
            self._setup_layer_shell()
        else:
            self._setup_fallback()

        # Motion tracking - this is the key to getting cursor position on Wayland
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("enter", self._on_enter)
        self.add_controller(motion)

        # Middle-click gesture (button 2) - fallback
        click = Gtk.GestureClick()
        click.set_button(2)
        click.connect("pressed", self.on_click)
        self.add_controller(click)

        # Also catch left-click as fallback
        click_left = Gtk.GestureClick()
        click_left.set_button(1)
        click_left.connect("pressed", self.on_click)
        self.add_controller(click_left)

        # Poll for activation file - fast polling for responsiveness
        GLib.timeout_add(10, self._check_activation)

        self.present()
        print(f"GRABBER: Ready ({max_w}x{max_h}) - Layer shell: {HAS_LAYER_SHELL}")

    def _on_motion(self, controller, x, y):
        """Track mouse motion - continuously update cursor position"""
        self._cursor_x = int(x)
        self._cursor_y = int(y)

    def _on_enter(self, controller, x, y):
        """Track when mouse enters the overlay"""
        self._cursor_x = int(x)
        self._cursor_y = int(y)

    def _setup_layer_shell(self):
        """Configure as layer-shell surface for cursor tracking"""
        # Initialize layer shell
        Gtk4LayerShell.init_for_window(self)

        # Use BACKGROUND layer - sits below all windows but can track pointer motion
        # This allows us to track cursor position without blocking any input
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.BACKGROUND)

        # No keyboard interaction
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

        # Anchor to all edges = fullscreen
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)

        # Don't reserve any space
        Gtk4LayerShell.set_exclusive_zone(self, -1)

        # Fully transparent
        self.set_opacity(0.0)

        # Input passthrough - clicks go through, but we still get motion events
        self._set_input_passthrough(True)

    def _setup_fallback(self):
        """Fallback for non-layer-shell systems"""
        self.set_opacity(0.01)  # Nearly invisible

    def _set_input_passthrough(self, passthrough):
        """
        Control whether clicks pass through or are captured.

        passthrough=True: Empty input region, all clicks go to windows below
        passthrough=False: Full input region, we capture all clicks
        """
        if not HAS_LAYER_SHELL:
            return

        # Get the GDK surface
        surface = self.get_surface()
        if surface is None:
            return

        try:
            import cairo
            if passthrough:
                # Empty region = all clicks pass through
                region = cairo.Region()
            else:
                # Full region = capture all clicks
                region = cairo.Region(cairo.RectangleInt(
                    x=0, y=0,
                    width=self.screen_width,
                    height=self.screen_height
                ))
            surface.set_input_region(region)
        except Exception as e:
            print(f"GRABBER: Failed to set input region: {e}")

    def _check_activation(self):
        """Periodically check if we should report cursor position"""
        active = is_active()

        if active and not self._capturing:
            # Daemon requested cursor position - report immediately using tracked position
            self._capturing = True
            x, y = self._cursor_x, self._cursor_y
            print(f"GRABBER: Activated - reporting position ({x}, {y})")

            # Clean up activation file
            try:
                os.unlink(ACTIVATE_FILE)
            except:
                pass

            # Emit D-Bus ShowMenu signal with tracked cursor position
            p = get_proxy()
            if p:
                try:
                    p.ShowMenu(x, y, dbus_interface="org.kde.juhradialmx.Daemon")
                    print(f"GRABBER: ShowMenu({x}, {y}) sent")
                except Exception as e:
                    print(f"GRABBER: D-Bus error: {e}")

            # Reset capture state
            self._capturing = False

        return True  # Continue polling

    def on_click(self, gesture, n_press, x, y):
        """Handle click - capture coordinates and emit D-Bus signal"""
        if not is_active():
            # Not activated - this shouldn't happen with proper input region,
            # but just in case, ignore the click
            return

        # Immediately disable input capture (restore click-through)
        self._capturing = False
        self._set_input_passthrough(True)

        # Clean up activation file
        try:
            os.unlink(ACTIVATE_FILE)
        except:
            pass

        x, y = int(x), int(y)
        print(f"GRABBER: Captured ({x},{y}) -> ShowMenu")

        # Emit D-Bus ShowMenu signal
        p = get_proxy()
        if p:
            try:
                p.ShowMenu(x, y, dbus_interface="org.kde.juhradialmx.Daemon")
            except Exception as e:
                print(f"GRABBER: D-Bus error: {e}")


class GrabberApp(Gtk.Application):
    """GTK4 Application wrapper"""

    def __init__(self):
        super().__init__(application_id="org.juhradialmx.grabber")

    def do_activate(self):
        CursorGrabber(self)


def main():
    # Force Wayland backend if available
    if "WAYLAND_DISPLAY" in os.environ:
        os.environ["GDK_BACKEND"] = "wayland"

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    print("JuhRadial MX Cursor Grabber starting...")
    print(f"  Layer shell available: {HAS_LAYER_SHELL}")
    print(f"  Activation file: {ACTIVATE_FILE}")

    app = GrabberApp()
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
