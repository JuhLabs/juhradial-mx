#!/usr/bin/env python3
"""
JuhRadial MX - Settings Dashboard (Entry Point)

Main application window and GTK4/Adwaita application class.
All UI components are imported from settings_* modules.

SPDX-License-Identifier: GPL-3.0
"""

import gi
import logging
import sys
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Gio, Adw

from i18n import _
from settings_sidebar import SidebarMixin

# Layer 1: Config + Theme
from settings_config import config, get_device_name, get_device_mode, get_device_name_from_daemon, get_minimal_mode, set_minimal_mode
from settings_theme import (
    COLORS,
    CSS,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_MIN_HEIGHT,
)

# Layer 2: Constants + Widgets
from settings_constants import MOUSE_BUTTONS, GENERIC_BUTTONS
from settings_widgets import MouseVisualization, GenericMouseVisualization

# Layer 3: Dialogs
from settings_dialogs import (
    ButtonConfigDialog,
    AddApplicationDialog,
    ApplicationProfilesGridDialog,
)

# Layer 4: Pages
from settings_page_buttons import ButtonsPage
from settings_page_scroll import ScrollPage
from settings_page_haptics import HapticsPage
from settings_page_devices import DevicesPage
from settings_page_easyswitch import EasySwitchPage
from settings_page_flow import FlowPage
from settings_page_settings import SettingsPage
from settings_page_macros import MacrosPage
from settings_page_gaming import GamingPage


# =============================================================================
# SETTINGS WINDOW
# =============================================================================
class SettingsWindow(SidebarMixin, Adw.ApplicationWindow):
    """Main settings window"""

    def __init__(self, app):
        super().__init__(application=app, title=_("JuhRadial MX Settings"))
        self.add_css_class("settings-window")

        # Reload config from disk to ensure we have latest values
        config.reload()

        # Detect device mode once at startup (cached for lifetime)
        self._device_mode = get_device_mode()
        self._is_generic = self._device_mode == "generic"
        self._restarting = False  # Guard against double-click on mode toggle

        # Match Adwaita palette to selected theme
        style_manager = Adw.StyleManager.get_default()
        if COLORS.get("is_dark", True):
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)

        # Screen-aware sizing: use 75% of screen width, 85% of screen height
        # Falls back to WINDOW_WIDTH/HEIGHT constants if detection fails
        w, h = WINDOW_WIDTH, WINDOW_HEIGHT
        try:
            display = Gdk.Display.get_default()
            if display:
                monitors = display.get_monitors()
                if monitors.get_n_items() > 0:
                    mon = monitors.get_item(0)
                    geom = mon.get_geometry()
                    w = max(WINDOW_MIN_WIDTH, min(int(geom.width * 0.75), 2400))
                    h = max(WINDOW_MIN_HEIGHT, min(int(geom.height * 0.85), 1600))
        except Exception:
            pass
        self.set_default_size(w, h)
        self.set_size_request(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # Set window icon for Wayland (fixes yellow default icon)
        icon_path = Path(__file__).parent.parent / "assets" / "juhradial-mx.svg"
        if icon_path.exists():
            try:
                # For GTK4/Adwaita, we need to use the default icon theme
                # Create a paintable from the SVG
                display = Gdk.Display.get_default()
                theme = Gtk.IconTheme.get_for_display(display)
                # Add our assets directory to the icon search path
                theme.add_search_path(str(icon_path.parent))
                self.set_icon_name("juhradial-mx")
            except Exception as e:
                logger.warning("Could not set window icon: %s", e)

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

        # Add logo and title to header bar (left-aligned above sidebar)
        title_box = self._create_title_widget()
        headerbar.set_title_widget(Gtk.Box())  # Empty title to prevent default
        headerbar.pack_start(title_box)

        # Add application button to header bar
        add_app_btn = Gtk.Button(label=_("+ ADD APPLICATION"))
        add_app_btn.add_css_class("add-app-btn")
        add_app_btn.connect("clicked", self._on_add_application)
        headerbar.pack_end(add_app_btn)

        # Mode toggles box (Minimal + Generic)
        toggles_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        # Minimal mode toggle
        minimal_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        minimal_label = Gtk.Label(label=_("Minimal Radial HUD"))
        minimal_label.add_css_class("dim-label")
        minimal_box.append(minimal_label)
        minimal_info_btn = Gtk.Button()
        minimal_info_btn.set_child(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        minimal_info_btn.add_css_class("flat")
        minimal_info_btn.add_css_class("dim-label")
        minimal_info_btn.set_tooltip_text(_("Show a minimal radial wheel with icons only - no pizza slices or labels"))
        minimal_info_btn.set_valign(Gtk.Align.CENTER)
        minimal_box.append(minimal_info_btn)
        self._minimal_switch = Gtk.Switch()
        self._minimal_switch.set_valign(Gtk.Align.CENTER)
        self._minimal_switch.set_active(get_minimal_mode())
        self._minimal_switch.connect("notify::active", self._on_minimal_mode_toggled)
        minimal_box.append(self._minimal_switch)
        toggles_box.append(minimal_box)

        # Generic mouse mode toggle
        generic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        generic_label = Gtk.Label(label=_("Generic Mouse Mode"))
        generic_label.add_css_class("dim-label")
        generic_box.append(generic_label)
        generic_info_btn = Gtk.Button()
        generic_info_btn.set_child(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        generic_info_btn.add_css_class("flat")
        generic_info_btn.add_css_class("dim-label")
        generic_info_btn.set_tooltip_text(_("Enable for non-Logitech mice. Disables HID++ features like haptics and Easy-Switch."))
        generic_info_btn.set_valign(Gtk.Align.CENTER)
        generic_box.append(generic_info_btn)
        self._generic_switch = Gtk.Switch()
        self._generic_switch.set_valign(Gtk.Align.CENTER)
        configured = config.get("device_mode", default="auto")
        self._generic_switch.set_active(configured == "generic")
        self._generic_switch.connect("notify::active", self._on_generic_mode_toggled)
        generic_box.append(self._generic_switch)
        toggles_box.append(generic_box)

        headerbar.pack_end(toggles_box)

        # Grid view toggle
        grid_btn = Gtk.Button()
        grid_btn.set_child(Gtk.Image.new_from_icon_name("view-grid-symbolic"))
        grid_btn.add_css_class("flat")
        grid_btn.connect("clicked", self._on_grid_view_toggle)
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
        self._on_nav_clicked("buttons")

        # Battery polling - only for Logitech mode (generic mice don't report battery)
        self._battery_timer_id = None
        if not self._is_generic:
            # Setup UPower signal monitoring for instant battery updates (system events)
            self._setup_upower_signals()
            # Start battery update timer (2 seconds for responsive charging status)
            self._battery_timer_id = GLib.timeout_add_seconds(2, self._update_battery)
            # Initial battery update
            GLib.idle_add(self._update_battery)

        # Pause timers when window is hidden, resume when shown
        self.connect("notify::visible", self._on_visibility_changed)

        # Connect close-request to clean up resources
        self.connect("close-request", self._on_close_request)

    def show_toast(self, message, timeout=2):
        """Show a toast notification"""
        toast = Adw.Toast(title=message)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def _on_visibility_changed(self, window, pspec):
        """Pause/resume polling timers when window visibility changes."""
        if self.get_visible():
            # Resume timers
            if not self._is_generic and not self._battery_timer_id:
                self._battery_timer_id = GLib.timeout_add_seconds(2, self._update_battery)
                GLib.idle_add(self._update_battery)
            if hasattr(self, "_heart_timer") and not self._heart_timer:
                self._heart_timer = GLib.timeout_add(30, self._tick_heart)
        else:
            # Pause timers
            if self._battery_timer_id:
                GLib.source_remove(self._battery_timer_id)
                self._battery_timer_id = None
            if hasattr(self, "_heart_timer") and self._heart_timer:
                GLib.source_remove(self._heart_timer)
                self._heart_timer = None

    def _on_close_request(self, window):
        """Clean up resources when window is closed"""
        # Stop battery polling timer
        if hasattr(self, "_battery_timer_id") and self._battery_timer_id:
            GLib.source_remove(self._battery_timer_id)
            self._battery_timer_id = None
            logger.debug("Battery timer stopped")

        # Stop heart animation timer
        if hasattr(self, "_heart_timer") and self._heart_timer:
            GLib.source_remove(self._heart_timer)
            self._heart_timer = None

        # Unsubscribe UPower signals
        if hasattr(self, "_system_bus") and self._system_bus:
            for sub_id in getattr(self, "_upower_signal_ids", []):
                self._system_bus.signal_unsubscribe(sub_id)
            self._upower_signal_ids = []

        # Clean up FlowPage (Zeroconf + poll timer)
        flow_page = self.content_stack.get_child_by_name("flow")
        if flow_page and hasattr(flow_page, "cleanup"):
            flow_page.cleanup()

        # Clear toast callback to avoid dangling reference
        config.set_toast_callback(None)

        logger.debug("Settings window cleanup complete")
        return False  # Allow window to close

    def _init_dbus(self):
        """Initialize D-Bus connection to daemon"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.dbus_proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
        except Exception as e:
            logger.error("Failed to connect to D-Bus: %s", e)
            self.dbus_proxy = None

    def _setup_upower_signals(self):
        """Setup UPower D-Bus signals for instant battery charging updates"""
        self._system_bus = None
        self._upower_signal_ids = []
        try:
            self._system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

            # Subscribe to UPower device changed signals
            # This catches battery state changes (charging/discharging)
            sub_id = self._system_bus.signal_subscribe(
                "org.freedesktop.UPower",  # sender
                "org.freedesktop.DBus.Properties",  # interface
                "PropertiesChanged",  # signal name
                None,  # object path (all devices)
                None,  # arg0 (interface name filter)
                Gio.DBusSignalFlags.NONE,
                self._on_upower_changed,  # callback
                None,  # user data
            )
            self._upower_signal_ids.append(sub_id)

            # Also listen for device added/removed (e.g., USB charger connected)
            sub_id = self._system_bus.signal_subscribe(
                "org.freedesktop.UPower",
                "org.freedesktop.UPower",
                "DeviceAdded",
                "/org/freedesktop/UPower",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_upower_device_event,
                None,
            )
            self._upower_signal_ids.append(sub_id)

            sub_id = self._system_bus.signal_subscribe(
                "org.freedesktop.UPower",
                "org.freedesktop.UPower",
                "DeviceRemoved",
                "/org/freedesktop/UPower",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_upower_device_event,
                None,
            )
            self._upower_signal_ids.append(sub_id)

            logger.debug("UPower signal monitoring enabled for instant battery updates")
        except Exception as e:
            logger.warning("Could not setup UPower signals: %s", e)
            logger.warning("Falling back to polling only")

    def _on_upower_changed(
        self, connection, sender, path, interface, signal, params, user_data
    ):
        """Handle UPower property changes - triggers instant battery update"""
        # Only respond to battery-related property changes
        if params:
            changed_props = params.unpack()
            if len(changed_props) > 0:
                interface_name = changed_props[0]
                # Check if this is a battery device property change
                if "UPower" in interface_name or "Device" in interface_name:
                    # Schedule immediate battery update on main thread
                    GLib.idle_add(self._update_battery)

    def _on_upower_device_event(
        self, connection, sender, path, interface, signal, params, user_data
    ):
        """Handle UPower device added/removed - charger connected/disconnected"""
        # Immediate battery update when a device is added/removed
        GLib.idle_add(self._update_battery)

    def _update_battery(self):
        """Fetch battery status from daemon via D-Bus"""
        if not self._battery_available:
            return False  # Stop timer - battery not supported by daemon
        if self.dbus_proxy is None or self.battery_label is None:
            return False  # Stop timer - no D-Bus connection or UI not ready

        try:
            # Call GetBatteryStatus method
            result = self.dbus_proxy.call_sync(
                "GetBatteryStatus",
                None,
                Gio.DBusCallFlags.NONE,
                1000,  # timeout ms
                None,
            )
            if result:
                percentage, is_charging = result.unpack()

                # 0% means battery info unavailable
                if percentage == 0:
                    self.battery_label.set_label(_("N/A"))
                    if self.battery_icon:
                        self.battery_icon.set_from_icon_name("battery-missing-symbolic")
                    return True

                # Show charging indicator in label with ⚡ symbol
                if is_charging:
                    self.battery_label.set_label(f"⚡ {percentage}%")
                else:
                    self.battery_label.set_label(f"{percentage}%")

                # Update icon based on level and charging status
                if is_charging:
                    if percentage >= 80:
                        icon = "battery-full-charging-symbolic"
                    elif percentage >= 50:
                        icon = "battery-good-charging-symbolic"
                    elif percentage >= 20:
                        icon = "battery-low-charging-symbolic"
                    else:
                        icon = "battery-caution-charging-symbolic"
                else:
                    if percentage >= 80:
                        icon = "battery-full-symbolic"
                    elif percentage >= 50:
                        icon = "battery-good-symbolic"
                    elif percentage >= 20:
                        icon = "battery-low-symbolic"
                    else:
                        icon = "battery-caution-symbolic"

                if self.battery_icon:
                    self.battery_icon.set_from_icon_name(icon)
        except Exception as e:
            if "UnknownMethod" in str(e):
                # Daemon doesn't support battery status yet - stop polling
                self._battery_available = False
                self.battery_label.set_label(_("N/A"))
                return False  # Stop timer
            logger.warning("Battery update failed: %s", e)

        return True  # Keep timer running

    def _create_title_widget(self):
        """Create the premium title widget with logo, app name, and device badge"""
        # Main container
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        title_box.set_valign(Gtk.Align.CENTER)

        # Logo container with glow effect
        logo_container = Gtk.Box()
        logo_container.add_css_class("logo-container")
        logo_container.set_valign(Gtk.Align.CENTER)

        # 3D radial wheel icon drawn with Cairo gradients
        logo_widget = Gtk.DrawingArea()
        logo_widget.set_content_width(34)
        logo_widget.set_content_height(34)
        logo_widget.set_draw_func(self._draw_logo_icon)
        logo_widget.set_valign(Gtk.Align.CENTER)
        logo_container.append(logo_widget)

        title_box.append(logo_container)

        # Text content - title and subtitle
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)

        # App title with accent color on "MX" (uses CSS classes for dynamic theming)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_row.set_halign(Gtk.Align.START)
        title_juh = Gtk.Label()
        title_juh.set_markup('<span weight="800" size="large">JuhRadial</span>')
        title_juh.add_css_class("app-title")
        title_row.append(title_juh)
        title_mx = Gtk.Label()
        title_mx.set_markup('<span weight="800" size="large">MX</span>')
        title_mx.add_css_class("app-title-accent")
        title_row.append(title_mx)
        text_box.append(title_row)

        # Subtitle
        subtitle = Gtk.Label(label=_("MOUSE CONFIGURATION"))
        subtitle.add_css_class("app-subtitle")
        subtitle.set_halign(Gtk.Align.START)
        text_box.append(subtitle)

        title_box.append(text_box)

        # Vertical divider
        divider = Gtk.Box()
        divider.add_css_class("header-divider")
        title_box.append(divider)

        # Device badge - use daemon name in generic mode
        badge_name = (
            get_device_name_from_daemon() if self._is_generic else get_device_name()
        )
        device_badge = Gtk.Label(label=badge_name.upper())
        device_badge.add_css_class("device-badge")
        device_badge.set_valign(Gtk.Align.CENTER)
        title_box.append(device_badge)

        return title_box

    def _draw_logo_icon(self, area, cr, width, height):
        """Draw a 3D radial wheel icon using Cairo gradients."""
        import math
        import cairo

        cx, cy = width / 2, height / 2
        r_outer = min(width, height) / 2 - 1
        r_inner = r_outer * 0.38

        # Parse accent color
        accent = COLORS.get("accent", "#00d4ff")
        ar = int(accent[1:3], 16) / 255
        ag = int(accent[3:5], 16) / 255
        ab = int(accent[5:7], 16) / 255

        # Outer ring - 3D metallic gradient
        ring_grad = cairo.RadialGradient(cx - 4, cy - 4, r_inner, cx, cy, r_outer)
        ring_grad.add_color_stop_rgba(0.0, ar * 1.4, ag * 1.4, ab * 1.4, 0.95)
        ring_grad.add_color_stop_rgba(0.5, ar * 0.7, ag * 0.7, ab * 0.7, 0.9)
        ring_grad.add_color_stop_rgba(1.0, ar * 0.3, ag * 0.3, ab * 0.3, 0.85)

        cr.arc(cx, cy, r_outer, 0, math.pi * 2)
        cr.arc_negative(cx, cy, r_inner + 1, math.pi * 2, 0)
        cr.set_source(ring_grad)
        cr.fill()

        # Segment lines (radial spokes) - 6 segments
        cr.set_line_width(0.8)
        cr.set_source_rgba(0, 0, 0, 0.35)
        for i in range(6):
            angle = i * math.pi / 3 - math.pi / 6
            x1 = cx + r_inner * math.cos(angle)
            y1 = cy + r_inner * math.sin(angle)
            x2 = cx + r_outer * math.cos(angle)
            y2 = cy + r_outer * math.sin(angle)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
        cr.stroke()

        # Top highlight arc (3D shine)
        cr.save()
        cr.arc(cx, cy, r_outer, 0, math.pi * 2)
        cr.clip()
        shine = cairo.LinearGradient(cx, cy - r_outer, cx, cy)
        shine.add_color_stop_rgba(0.0, 1, 1, 1, 0.25)
        shine.add_color_stop_rgba(1.0, 1, 1, 1, 0.0)
        cr.rectangle(0, 0, width, height / 2)
        cr.set_source(shine)
        cr.fill()
        cr.restore()

        # Inner circle - dark recessed center with 3D depth
        center_grad = cairo.RadialGradient(cx - 1.5, cy - 1.5, 0, cx, cy, r_inner)
        center_grad.add_color_stop_rgba(0.0, 0.25, 0.25, 0.3, 1.0)
        center_grad.add_color_stop_rgba(0.7, 0.1, 0.1, 0.15, 1.0)
        center_grad.add_color_stop_rgba(1.0, ar * 0.4, ag * 0.4, ab * 0.4, 0.8)
        cr.arc(cx, cy, r_inner, 0, math.pi * 2)
        cr.set_source(center_grad)
        cr.fill()

        # Center dot - tiny bright highlight
        cr.arc(cx - 1, cy - 1, 2, 0, math.pi * 2)
        cr.set_source_rgba(1, 1, 1, 0.4)
        cr.fill()

    def _on_add_application(self, button):
        """Open dialog to add per-application profile"""
        dialog = AddApplicationDialog(self)
        dialog.present()

    def _on_minimal_mode_toggled(self, switch, _pspec):
        """Toggle minimal radial wheel mode (icons only, no pizza slices)."""
        set_minimal_mode(switch.get_active())
        label = _("Minimal mode on") if switch.get_active() else _("Minimal mode off")
        self.show_toast(label, timeout=1)

    def _on_generic_mode_toggled(self, switch, _pspec):
        """Toggle between generic and auto (Logitech) device mode. Restarts settings."""
        if self._restarting:
            return
        self._restarting = True
        import settings_config as _sc
        mode = "generic" if switch.get_active() else "auto"
        config.set("device_mode", mode, auto_save=True)
        # Clear cached mode so next launch picks up the new value
        _sc._cached_device_mode = None
        # Show toast and restart settings window to rebuild sidebar/pages
        self.show_toast(_("Restarting settings..."), timeout=1)
        GLib.timeout_add(500, self._restart_window)

    def _restart_window(self):
        """Close and reopen the settings window to apply mode change."""
        import settings_config as _sc
        app = self.get_application()
        self.close()
        def _reopen():
            _sc._cached_device_mode = None  # Clear right before new window
            config.reload()  # Re-read from disk
            SettingsWindow(app).present()
            return False
        GLib.idle_add(_reopen)
        return False

    def _on_grid_view_toggle(self, button):
        """Toggle grid view for application profiles"""
        dialog = ApplicationProfilesGridDialog(self)
        dialog.present()

    def _create_pages(self):
        if self._is_generic:
            # Generic mode: generic mouse photo + buttons config
            buttons_page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

            generic_viz = GenericMouseVisualization(
                on_button_click=self._on_generic_button_click
            )
            generic_viz.set_hexpand(True)
            buttons_page.append(generic_viz)

            self.buttons_settings = ButtonsPage(
                on_button_config=self._on_mouse_button_click,
                parent_window=self,
                config_manager=config,
                generic_mode=True,
            )
            self.buttons_settings.set_size_request(400, -1)
            buttons_page.append(self.buttons_settings)

            self.content_stack.add_named(buttons_page, "buttons")
        else:
            # Logitech mode: mouse visualization + buttons config
            buttons_page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

            mouse_viz = MouseVisualization(on_button_click=self._on_mouse_button_click)
            mouse_viz.set_hexpand(True)
            buttons_page.append(mouse_viz)

            self.buttons_settings = ButtonsPage(
                on_button_config=self._on_mouse_button_click,
                parent_window=self,
                config_manager=config,
            )
            self.buttons_settings.set_size_request(400, -1)
            buttons_page.append(self.buttons_settings)

            self.content_stack.add_named(buttons_page, "buttons")

        # Other pages
        self.content_stack.add_named(ScrollPage(), "scroll")
        self.content_stack.add_named(DevicesPage(), "devices")
        self.content_stack.add_named(SettingsPage(), "settings")

        # Logitech-only pages - skip in generic mode
        if not self._is_generic:
            self.content_stack.add_named(HapticsPage(), "haptics")
            self.content_stack.add_named(EasySwitchPage(), "easy_switch")
            # FlowPage is lazy-loaded when navigated to (avoids Zeroconf at startup)
            self._flow_page_placeholder = Gtk.Box()
            self.content_stack.add_named(self._flow_page_placeholder, "flow")

        # Macros and Gaming - available in all modes
        self.content_stack.add_named(MacrosPage(), "macros")
        self.content_stack.add_named(GamingPage(), "gaming")

    def _create_status_bar(self):
        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status.add_css_class("status-bar")

        # Battery section - hide for generic mice (no HID++ battery reporting)
        if not self._is_generic:
            battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            # Battery icon (left of percentage)
            self.battery_icon = Gtk.Image.new_from_icon_name("battery-good-symbolic")
            self.battery_icon.add_css_class("battery-icon")
            battery_box.append(self.battery_icon)

            # Store as instance variables for D-Bus updates
            self.battery_label = Gtk.Label(label="--")
            self.battery_label.add_css_class("battery-indicator")
            battery_box.append(self.battery_label)

            status.append(battery_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        status.append(spacer)

        # Connection status with icon
        conn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        if self._is_generic:
            # Generic mode: show mouse icon + "Generic Mouse"
            self.conn_icon = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
            self.conn_icon.add_css_class("connection-icon")
            conn_box.append(self.conn_icon)

            self.conn_label = Gtk.Label(label=_("Generic Mouse"))
            self.conn_label.add_css_class("connection-status")
            conn_box.append(self.conn_label)
        else:
            # Connection icon (USB receiver)
            self.conn_icon = Gtk.Image.new_from_icon_name(
                "network-wireless-signal-excellent-symbolic"
            )
            self.conn_icon.add_css_class("connection-icon")
            conn_box.append(self.conn_icon)

            self.conn_label = Gtk.Label(label=_("Logi Bolt USB"))
            self.conn_label.add_css_class("connection-status")
            conn_box.append(self.conn_label)

        status.append(conn_box)

        return status

    def _on_nav_clicked(self, item_id):
        # Update active state
        for btn_id, btn in self.nav_buttons.items():
            btn.set_active(btn_id == item_id)

        # Lazy-load FlowPage on first navigation to avoid Zeroconf startup cost
        # (only in Logitech mode - flow tab is hidden in generic mode)
        if (
            item_id == "flow"
            and not self._is_generic
            and hasattr(self, "_flow_page_placeholder")
            and self._flow_page_placeholder
        ):
            self.content_stack.remove(self._flow_page_placeholder)
            self._flow_page_placeholder = None
            flow_page = FlowPage()
            self.content_stack.add_named(flow_page, "flow")

        # Switch page
        self.content_stack.set_visible_child_name(item_id)

    def _on_generic_button_click(self, button_id, button_info=None):
        """Open button configuration dialog for generic mouse buttons"""
        if button_id in GENERIC_BUTTONS:
            dialog = ButtonConfigDialog(self, button_id, GENERIC_BUTTONS[button_id])
            dialog.connect("close-request", lambda _: self._on_dialog_closed())
            dialog.present()

    def _on_mouse_button_click(self, button_id):
        """Open button configuration dialog"""
        if button_id in MOUSE_BUTTONS:
            dialog = ButtonConfigDialog(self, button_id, MOUSE_BUTTONS[button_id])
            dialog.connect("close-request", lambda _: self._on_dialog_closed())
            dialog.present()

    def _on_dialog_closed(self):
        """Refresh UI after dialog closes"""
        if hasattr(self, "buttons_settings"):
            self.buttons_settings.refresh_button_labels()


# =============================================================================
# APPLICATION
# =============================================================================
class SettingsApp(Adw.Application):
    """GTK4/Adwaita Application"""

    def __init__(self):
        super().__init__(
            application_id="org.kde.juhradialmx.settings",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,  # Enables single-instance via D-Bus
        )

    def do_startup(self):
        Adw.Application.do_startup(self)

        # Load CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS.encode())

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
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

    def do_shutdown(self):
        """Clean up all resources on application exit"""
        # Window cleanup is handled by the close-request signal - no need to call manually
        Adw.Application.do_shutdown(self)
        logger.debug("Settings application shutdown complete")


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # GTK4/Adwaita handles single-instance automatically via D-Bus
    # Using application_id='org.kde.juhradialmx.settings' with DEFAULT_FLAGS
    # If another instance is launched, it activates the existing window
    logger.info("JuhRadial MX Settings Dashboard")
    logger.info("  Theme: Catppuccin Mocha")
    logger.info("  Size: %dx%d", WINDOW_WIDTH, WINDOW_HEIGHT)

    app = SettingsApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
