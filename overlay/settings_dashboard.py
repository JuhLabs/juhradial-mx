#!/usr/bin/env python3
"""
JuhRadial MX - Settings Dashboard (Entry Point)

Main application window and GTK4/Adwaita application class.
All UI components are imported from settings_* modules.

SPDX-License-Identifier: GPL-3.0
"""

import gi
import sys
import signal
from pathlib import Path

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Gio, Adw

from i18n import _

# Layer 1: Config + Theme
from settings_config import config, get_device_name
from settings_theme import (
    COLORS,
    CSS,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_MIN_HEIGHT,
)

# Layer 2: Constants + Widgets
from settings_constants import MOUSE_BUTTONS, NAV_ITEMS
from settings_widgets import NavButton, MouseVisualization

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


# =============================================================================
# SETTINGS WINDOW
# =============================================================================
class SettingsWindow(Adw.ApplicationWindow):
    """Main settings window"""

    def __init__(self, app):
        super().__init__(application=app, title=_("JuhRadial MX Settings"))
        self.add_css_class("settings-window")

        # Reload config from disk to ensure we have latest values
        config.reload()

        # Match Adwaita palette to selected theme
        style_manager = Adw.StyleManager.get_default()
        if COLORS.get("is_dark", True):
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)

        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_size_request(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # Set window icon for Wayland (fixes yellow default icon)
        icon_path = Path(__file__).parent.parent / "assets" / "juhradial-mx.svg"
        if icon_path.exists():
            self.set_icon_name(None)  # Clear any default
            # Load and set icon from file
            try:
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

        # Add logo and title to header bar (left-aligned above sidebar)
        title_box = self._create_title_widget()
        headerbar.set_title_widget(Gtk.Box())  # Empty title to prevent default
        headerbar.pack_start(title_box)

        # Add application button to header bar
        add_app_btn = Gtk.Button(label=_("+ ADD APPLICATION"))
        add_app_btn.add_css_class("add-app-btn")
        add_app_btn.connect("clicked", self._on_add_application)
        headerbar.pack_end(add_app_btn)

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

        # Setup UPower signal monitoring for instant battery updates (system events)
        self._setup_upower_signals()
        # Start battery update timer (2 seconds for responsive charging status)
        self._battery_timer_id = GLib.timeout_add_seconds(2, self._update_battery)
        # Initial battery update
        GLib.idle_add(self._update_battery)

        # Connect close-request to clean up resources
        self.connect("close-request", self._on_close_request)

    def show_toast(self, message, timeout=2):
        """Show a toast notification"""
        toast = Adw.Toast(title=message)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def _on_close_request(self, window):
        """Clean up resources when window is closed"""
        # Stop battery polling timer
        if hasattr(self, "_battery_timer_id") and self._battery_timer_id:
            GLib.source_remove(self._battery_timer_id)
            self._battery_timer_id = None
            print("Battery timer stopped")

        # Clean up FlowPage Zeroconf if it exists
        flow_page = self.content_stack.get_child_by_name("flow")
        if flow_page and hasattr(flow_page, "cleanup"):
            flow_page.cleanup()

        # Clear toast callback to avoid dangling reference
        config.set_toast_callback(None)

        print("Settings window cleanup complete")
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
            print(f"Failed to connect to D-Bus: {e}")
            self.dbus_proxy = None

    def _setup_upower_signals(self):
        """Setup UPower D-Bus signals for instant battery charging updates"""
        try:
            system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

            # Subscribe to UPower device changed signals
            # This catches battery state changes (charging/discharging)
            system_bus.signal_subscribe(
                "org.freedesktop.UPower",  # sender
                "org.freedesktop.DBus.Properties",  # interface
                "PropertiesChanged",  # signal name
                None,  # object path (all devices)
                None,  # arg0 (interface name filter)
                Gio.DBusSignalFlags.NONE,
                self._on_upower_changed,  # callback
                None,  # user data
            )

            # Also listen for device added/removed (e.g., USB charger connected)
            system_bus.signal_subscribe(
                "org.freedesktop.UPower",
                "org.freedesktop.UPower",
                "DeviceAdded",
                "/org/freedesktop/UPower",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_upower_device_event,
                None,
            )
            system_bus.signal_subscribe(
                "org.freedesktop.UPower",
                "org.freedesktop.UPower",
                "DeviceRemoved",
                "/org/freedesktop/UPower",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_upower_device_event,
                None,
            )

            print("UPower signal monitoring enabled for instant battery updates")
        except Exception as e:
            print(f"Could not setup UPower signals: {e}")
            print("Falling back to polling only")

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
        if (
            self.dbus_proxy is None
            or self.battery_label is None
            or not self._battery_available
        ):
            return self._battery_available  # Stop timer if battery not available

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

                # 0% means battery info unavailable (logid controls HID++)
                if percentage == 0:
                    self.battery_label.set_label(_("LogiOps"))
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
            print(f"Battery update failed: {e}")

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

        # JuhRadial MX header: logo icon + text
        script_dir = Path(__file__).resolve().parent
        logo_paths = [
            script_dir.parent / "docs" / "radiallogo_icon.png",
            script_dir / "assets" / "radiallogo_icon.png",
            Path("/usr/share/juhradial/radiallogo_icon.png"),
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
            fallback_icon = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
            fallback_icon.set_pixel_size(28)
            logo_container.append(fallback_icon)

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

        # Device badge
        device_badge = Gtk.Label(label=get_device_name().upper())
        device_badge.add_css_class("device-badge")
        device_badge.set_valign(Gtk.Align.CENTER)
        title_box.append(device_badge)

        return title_box

    def _create_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.add_css_class("sidebar")

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
        dev_label.set_markup(
            f'<span size="small" color="{COLORS["subtext0"]}">'
            + _("Developed by")
            + "</span>"
        )
        dev_label.set_halign(Gtk.Align.START)
        credits_box.append(dev_label)

        name_label = Gtk.Label()
        name_label.set_markup(
            f'<span size="small" weight="bold" color="{COLORS["text"]}">JuhLabs (Julian Hermstad)</span>'
        )
        name_label.set_halign(Gtk.Align.START)
        credits_box.append(name_label)

        # Description
        desc_label = Gtk.Label()
        desc_label.set_markup(
            f'<span size="x-small" color="{COLORS["subtext0"]}">'
            + _(
                "Free &amp; open source software.\nIf you enjoy this project,\nconsider supporting development."
            )
            + "</span>"
        )
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_margin_top(4)
        credits_box.append(desc_label)

        # Donate button
        donate_btn = Gtk.Button()
        donate_btn.add_css_class("donate-btn")
        donate_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        donate_box.set_halign(Gtk.Align.CENTER)
        coffee_icon = Gtk.Label(label="\u2615")  # Coffee emoji
        donate_box.append(coffee_icon)
        donate_label = Gtk.Label(label=_("Buy me a coffee"))
        donate_box.append(donate_label)
        donate_btn.set_child(donate_box)
        donate_btn.set_margin_top(8)
        donate_btn.connect("clicked", self._on_donate_clicked)
        credits_box.append(donate_btn)

        sidebar.append(credits_box)

        return sidebar

    def _on_donate_clicked(self, button):
        """Open PayPal donation link"""
        import subprocess

        subprocess.Popen(["xdg-open", "https://paypal.me/LangbachHermstad"])

    def _on_add_application(self, button):
        """Open dialog to add per-application profile"""
        dialog = AddApplicationDialog(self)
        dialog.present()

    def _on_grid_view_toggle(self, button):
        """Toggle grid view for application profiles"""
        dialog = ApplicationProfilesGridDialog(self)
        dialog.present()

    def _create_pages(self):
        # Buttons page with mouse visualization
        buttons_page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Mouse visualization (left side)
        mouse_viz = MouseVisualization(on_button_click=self._on_mouse_button_click)
        mouse_viz.set_hexpand(True)
        buttons_page.append(mouse_viz)

        # Settings panel (right side)
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
        self.content_stack.add_named(HapticsPage(), "haptics")
        self.content_stack.add_named(DevicesPage(), "devices")
        self.content_stack.add_named(EasySwitchPage(), "easy_switch")
        # FlowPage is lazy-loaded when navigated to (avoids Zeroconf at startup)
        self._flow_page_placeholder = Gtk.Box()
        self.content_stack.add_named(self._flow_page_placeholder, "flow")
        self.content_stack.add_named(SettingsPage(), "settings")

    def _create_status_bar(self):
        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status.add_css_class("status-bar")

        # Battery section
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
        if (
            item_id == "flow"
            and hasattr(self, "_flow_page_placeholder")
            and self._flow_page_placeholder
        ):
            self.content_stack.remove(self._flow_page_placeholder)
            self._flow_page_placeholder = None
            flow_page = FlowPage()
            self.content_stack.add_named(flow_page, "flow")

        # Switch page
        self.content_stack.set_visible_child_name(item_id)

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
        # Ensure all windows get their cleanup called
        for window in self.get_windows():
            if hasattr(window, "_on_close_request"):
                window._on_close_request(window)
        Adw.Application.do_shutdown(self)
        print("Settings application shutdown complete")


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # GTK4/Adwaita handles single-instance automatically via D-Bus
    # Using application_id='org.kde.juhradialmx.settings' with DEFAULT_FLAGS
    # If another instance is launched, it activates the existing window
    print("JuhRadial MX Settings Dashboard")
    print("  Theme: Catppuccin Mocha")
    print(f"  Size: {WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    app = SettingsApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
