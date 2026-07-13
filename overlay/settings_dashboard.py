#!/usr/bin/env python3
"""
JuhRadial MX - Settings Dashboard (Entry Point)

Main application window and GTK4/Adwaita application class.
All UI components are imported from settings_* modules.

SPDX-License-Identifier: GPL-3.0
"""

import ctypes
import ctypes.util
import gi
import logging
import os
import sys
import signal
from pathlib import Path

# Set process name to "juhradial-settings" for system monitors
try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    _libc.prctl(15, b"juhradial-settings", 0, 0, 0)  # PR_SET_NAME = 15
except (OSError, AttributeError):
    pass  # prctl may not be available on all platforms

logger = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Gio, Adw

from i18n import _
from settings_sidebar import SidebarMixin

# Layer 1: Config + Theme
from settings_config import config, get_device_name, get_device_mode, get_device_name_from_daemon, get_minimal_mode, set_minimal_mode, clear_device_mode_cache
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
from settings_widgets import MouseVisualization, GenericMouseVisualization, _resolve_asset_path

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

        # Screen-aware sizing: use 70% of screen width, 75% of screen height
        # This leaves room for panels/taskbars on all DEs (GNOME top bar, KDE panel, etc.)
        # Falls back to WINDOW_WIDTH/HEIGHT constants if detection fails
        w, h = WINDOW_WIDTH, WINDOW_HEIGHT
        try:
            display = Gdk.Display.get_default()
            if display:
                monitors = display.get_monitors()
                if monitors.get_n_items() > 0:
                    mon = monitors.get_item(0)
                    geom = mon.get_geometry()
                    w = max(WINDOW_MIN_WIDTH, min(int(geom.width * 0.70), 2400))
                    h = max(WINDOW_MIN_HEIGHT, min(int(geom.height * 0.75), 1200))
        except (AttributeError, ValueError):
            pass  # GDK monitor detection can fail in headless or early init
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
        self._low_batt_notified = False  # one desktop notification per low-battery episode

        # Create proper header bar with window controls
        headerbar = Adw.HeaderBar()
        headerbar.set_show_end_title_buttons(True)  # Close, minimize, maximize
        headerbar.set_show_start_title_buttons(True)

        # Add logo and title to header bar (left-aligned above sidebar)
        title_box = self._create_title_widget()
        headerbar.set_title_widget(self._create_search_widget())
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

        # Sidebar (carries its own hairline border-right; no extra separator)
        sidebar = self._create_sidebar()
        content_box.append(sidebar)

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
            # Initial battery update — one-shot via idle. Same `and False`
            # guard as in _on_upower_device_added; without it the idle
            # callback re-fires every loop tick.
            GLib.idle_add(lambda: self._update_battery() and False)

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
                # One-shot: _update_battery returns True (to repeat the 2s timer),
                # so guard with `and False` or this idle source spins forever and
                # leaks CPU after the window closes.
                GLib.idle_add(lambda: self._update_battery() and False)
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
                    # Schedule immediate battery update on main thread.
                    # One-shot: _update_battery returns True, so without `and
                    # False` each UPower signal would leak a CPU-spinning idle
                    # source that survives window close (issue #32).
                    GLib.idle_add(lambda: self._update_battery() and False)

    def _on_upower_device_event(
        self, connection, sender, path, interface, signal, params, user_data
    ):
        """Handle UPower device added/removed - charger connected/disconnected"""
        # Immediate battery update when a device is added/removed.
        # _update_battery returns True to keep its 2s timer running, so we
        # wrap with `and False` to make this one-shot in the idle queue
        # (otherwise the idle callback re-fires on every loop tick = tight
        # loop with thousands of D-Bus calls per second when daemon is down).
        GLib.idle_add(lambda: self._update_battery() and False)

    def _maybe_notify_low_battery(self, percentage, is_charging):
        """Fire one desktop notification when the mouse battery gets low.

        Resets once charging or comfortably above the threshold, so a single
        low episode notifies exactly once (no spam from the 2s poll)."""
        LOW = 15
        if is_charging or percentage > LOW + 5:
            self._low_batt_notified = False
            return
        if percentage <= LOW and not self._low_batt_notified:
            self._low_batt_notified = True
            try:
                app = self.get_application() or Gio.Application.get_default()
                if app is not None:
                    notif = Gio.Notification.new(_("JuhRadial MX"))
                    notif.set_body(_("Mouse battery low: %d%%") % percentage)
                    notif.set_priority(Gio.NotificationPriority.HIGH)
                    notif.set_icon(Gio.ThemedIcon.new("battery-caution-symbolic"))
                    app.send_notification("juhradial-low-battery", notif)
            except Exception as e:
                logger.debug("low-battery notify failed: %s", e)

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

                self._maybe_notify_low_battery(percentage, is_charging)

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

    def _create_search_widget(self):
        """Header search box: type to find a setting, click a result to jump."""
        self._search_index = [
            (_("Button Assignments"), "buttons", "button remap middle back forward shift wheel click"),
            (_("Actions Ring"), "buttons", "radial menu slices gestures wheel"),
            (_("Scroll Speed"), "scroll", "scroll wheel lines sensitivity"),
            (_("SmartShift"), "scroll", "ratchet free spin scroll wheel"),
            (_("Smooth Scrolling"), "scroll", "high resolution hires scroll"),
            (_("Natural Scrolling"), "scroll", "invert scroll direction"),
            (_("Thumb Wheel"), "scroll", "thumbwheel volume zoom horizontal scroll"),
            (_("Haptic Feedback"), "haptics", "vibration actuator waveform pattern pulse"),
            (_("Battery"), "devices", "charge level power"),
            (_("DPI"), "devices", "pointer speed sensitivity resolution"),
            (_("Device Info"), "devices", "model firmware connection"),
            (_("Easy-Switch"), "easy_switch", "host paired computers switch bluetooth"),
            (_("Flow"), "flow", "multi computer share clipboard cross"),
            (_("Macros"), "macros", "automation record keystrokes sequence"),
            (_("Gaming Mode"), "gaming", "dpi presets sniper performance"),
            (_("Theme"), "settings", "appearance color dark light radial wheel"),
            (_("Tray Icon"), "settings", "system tray"),
            (_("Start at Login"), "settings", "autostart startup boot"),
            (_("Language"), "settings", "locale translation"),
        ]
        self._page_titles = {
            "buttons": _("Buttons"), "scroll": _("Point & Scroll"),
            "haptics": _("Haptics"), "devices": _("Devices"),
            "easy_switch": _("Easy-Switch"), "flow": _("Flow"),
            "macros": _("Macros"), "gaming": _("Gaming"), "settings": _("Settings"),
        }
        entry = Gtk.SearchEntry()
        entry.set_placeholder_text(_("Search settings"))
        entry.add_css_class("header-search")
        entry.set_max_width_chars(34)
        entry.set_width_chars(24)
        self._search_entry = entry

        self._search_listbox = Gtk.ListBox()
        self._search_listbox.add_css_class("search-results")
        self._search_listbox.connect("row-activated", self._on_search_result)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(340)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(self._search_listbox)

        # autohide False so typing keeps focus; we pop it down on empty/select/esc.
        self._search_popover = Gtk.Popover()
        self._search_popover.set_autohide(False)
        self._search_popover.set_has_arrow(False)
        self._search_popover.set_position(Gtk.PositionType.BOTTOM)
        self._search_popover.set_parent(entry)
        self._search_popover.set_child(scroller)

        entry.connect("search-changed", self._on_search_changed)
        entry.connect("stop-search", lambda e: self._search_popover.popdown())
        return entry

    def _on_search_changed(self, entry):
        query = entry.get_text().strip().lower()
        child = self._search_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._search_listbox.remove(child)
            child = nxt
        if not query:
            self._search_popover.popdown()
            return
        # Only offer results whose page exists in the current device mode
        # (haptics/easy_switch/flow are absent in generic-mouse mode).
        matches = [
            item for item in self._search_index
            if (query in item[0].lower() or query in item[2])
            and self.content_stack.get_child_by_name(item[1]) is not None
        ]
        for label, page_id, _kw in matches[:10]:
            row = Gtk.ListBoxRow()
            row._page_id = page_id
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(7)
            box.set_margin_bottom(7)
            box.set_margin_start(12)
            box.set_margin_end(12)
            name = Gtk.Label(label=label)
            name.set_halign(Gtk.Align.START)
            page = Gtk.Label(label=self._page_titles.get(page_id, page_id))
            page.add_css_class("dim-label")
            page.set_hexpand(True)
            page.set_halign(Gtk.Align.END)
            box.append(name)
            box.append(page)
            row.set_child(box)
            self._search_listbox.append(row)
        if not matches:
            row = Gtk.ListBoxRow()
            row._page_id = None
            row.set_selectable(False)
            empty = Gtk.Label(label=_("No matching settings"))
            empty.add_css_class("dim-label")
            empty.set_margin_top(10)
            empty.set_margin_bottom(10)
            row.set_child(empty)
            self._search_listbox.append(row)
        self._search_popover.popup()

    def _on_search_result(self, _listbox, row):
        page_id = getattr(row, "_page_id", None)
        if page_id:
            self._on_nav_clicked(page_id)
        self._search_popover.popdown()
        self._search_entry.set_text("")

    def _create_title_widget(self):
        """Create the premium title widget with logo, app name, and device badge"""
        # Main container
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        title_box.set_valign(Gtk.Align.CENTER)

        # Logo container with glow effect
        logo_container = Gtk.Box()
        logo_container.add_css_class("logo-container")
        logo_container.set_valign(Gtk.Align.CENTER)

        # Main brand logo (the radial-wheel mark)
        logo_path = _resolve_asset_path("juhradial-mx.svg")
        if logo_path:
            logo_widget = Gtk.Image.new_from_file(logo_path)
        else:
            logo_widget = Gtk.Image.new_from_icon_name("image-missing")
        logo_widget.set_pixel_size(40)
        logo_widget.set_valign(Gtk.Align.CENTER)
        logo_container.append(logo_widget)

        title_box.append(logo_container)

        # Text content - title and subtitle
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)

        # App title with accent color on "MX" (uses CSS classes for dynamic theming)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_row.set_halign(Gtk.Align.START)
        title_juh = Gtk.Label(label="JuhRadial")
        title_juh.add_css_class("app-title")
        title_row.append(title_juh)
        title_mx = Gtk.Label(label="MX")
        title_mx.add_css_class("app-title")
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
        mode = "generic" if switch.get_active() else "auto"
        config.set("device_mode", mode, auto_save=True)
        # Clear cached mode so next launch picks up the new value
        clear_device_mode_cache()
        # Show toast and restart settings window to rebuild sidebar/pages
        self.show_toast(_("Restarting settings..."), timeout=1)
        GLib.timeout_add(500, self._restart_window)

    def _restart_window(self):
        """Close and reopen the settings window to apply mode change."""
        app = self.get_application()
        self.close()
        def _reopen():
            clear_device_mode_cache()  # Clear right before new window
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
            buttons_page.add_css_class("mouse-stage")

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
            buttons_page.add_css_class("mouse-stage")

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

        # The first visible page is Buttons. Build Point & Scroll lazily because
        # its hardware-state reads are independent of the initial screen.
        self._scroll_page_placeholder = Gtk.Box()
        self.content_stack.add_named(self._scroll_page_placeholder, "scroll")
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
        self.content_stack.add_named(MacrosPage(parent_window=self), "macros")
        self.content_stack.add_named(
            GamingPage(
                parent_window=self,
                on_open_macros=lambda: self._on_nav_clicked("macros"),
            ),
            "gaming",
        )

    def _create_status_bar(self):
        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status.add_css_class("status-bar")

        # Battery section - hide for generic mice (no HID++ battery reporting)
        if not self._is_generic:
            battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            battery_box.add_css_class("battery-pill")
            battery_box.set_valign(Gtk.Align.CENTER)

            # Battery icon (left of percentage)
            self.battery_icon = Gtk.Image.new_from_icon_name("battery-good-symbolic")
            self.battery_icon.set_pixel_size(20)
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

        # Lazy-load Point & Scroll after the first frame. Its daemon reads can
        # be slow while HID++ is reconnecting, but must not delay opening the
        # default Buttons page.
        if (
            item_id == "scroll"
            and hasattr(self, "_scroll_page_placeholder")
            and self._scroll_page_placeholder is not None
        ):
            self.content_stack.remove(self._scroll_page_placeholder)
            self._scroll_page_placeholder = None
            self.content_stack.add_named(ScrollPage(), "scroll")

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
            from settings_page_flow import FlowPage
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

        # Keep a single provider so live theme switches update in place
        sys.modules["settings_theme"].CSS_PROVIDER = css_provider

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

        # Dev-only: render the window to a PNG and quit (set JUH_SHOT=/path).
        # WM-independent capture; used only for design verification screenshots.
        shot = os.environ.get("JUH_SHOT")
        if shot:
            shot_page = os.environ.get("JUH_SHOT_PAGE")
            if shot_page:
                try:
                    win._on_nav_clicked(shot_page)
                except Exception as e:
                    logger.error("self-shot nav failed: %s", e)
            def _grab():
                try:
                    from gi.repository import Graphene
                    w = win.get_width() or WINDOW_WIDTH
                    h = win.get_height() or WINDOW_HEIGHT
                    paintable = Gtk.WidgetPaintable.new(win)
                    snapshot = Gtk.Snapshot()
                    paintable.snapshot(snapshot, w, h)
                    node = snapshot.to_node()
                    renderer = win.get_renderer()
                    if node is not None and renderer is not None:
                        tex = renderer.render_texture(node, Graphene.Rect().init(0, 0, w, h))
                        tex.save_to_png(shot)
                        logger.info("self-shot saved: %s", shot)
                except Exception as e:
                    logger.error("self-shot failed: %s", e)
                self.quit()
                return False
            GLib.timeout_add(1200, _grab)

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
