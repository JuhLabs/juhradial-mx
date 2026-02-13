#!/usr/bin/env python3
"""
JuhRadial MX - Settings Page

SettingsPage: Appearance, language, and application settings.

SPDX-License-Identifier: GPL-3.0
"""

import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw

from i18n import _, SUPPORTED_LANGUAGES
from settings_config import ConfigManager, config, get_device_name
import settings_theme
from settings_widgets import SettingsCard, SettingRow
from themes import get_theme_list


class SettingsPage(Gtk.ScrolledWindow):
    """General settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Appearance settings
        appearance_card = SettingsCard(_("Appearance"))

        theme_row = SettingRow(
            _("Theme"), _("Choose color theme for radial menu and settings")
        )
        theme_dropdown = Gtk.DropDown()
        theme_list = get_theme_list()
        self._theme_keys = [t[0] for t in theme_list]
        theme_options = Gtk.StringList.new([t[1] for t in theme_list])
        theme_dropdown.set_model(theme_options)
        # Set current theme
        current_theme = config.get("theme", default="juhradial-mx")
        if current_theme in self._theme_keys:
            theme_dropdown.set_selected(self._theme_keys.index(current_theme))
        else:
            theme_dropdown.set_selected(0)
        theme_dropdown.connect("notify::selected", self._on_theme_changed)
        theme_row.set_control(theme_dropdown)
        appearance_card.append(theme_row)

        blur_row = SettingRow(
            _("Blur Effect"), _("Enable background blur for radial menu")
        )
        blur_switch = Gtk.Switch()
        blur_switch.set_active(config.get("blur_enabled", default=True))
        blur_switch.connect(
            "state-set", lambda s, state: config.set("blur_enabled", state) or False
        )
        blur_row.set_control(blur_switch)
        appearance_card.append(blur_row)

        # Language selector
        lang_row = SettingRow(_("Language"), _("Choose display language"))
        lang_dropdown = Gtk.DropDown()
        lang_keys = list(SUPPORTED_LANGUAGES.keys())
        lang_labels = list(SUPPORTED_LANGUAGES.values())
        lang_model = Gtk.StringList.new(lang_labels)
        lang_dropdown.set_model(lang_model)
        # Set current selection from config
        current_lang = config.get("language", default="system")
        if current_lang in lang_keys:
            lang_dropdown.set_selected(lang_keys.index(current_lang))

        def _on_language_changed(dropdown, _param):
            idx = dropdown.get_selected()
            if idx < len(lang_keys):
                config.set("language", lang_keys[idx])
                config.save(show_toast=False)
                # Reload translations and recreate window
                from i18n import reload_language

                reload_language()
                app = self.get_root().get_application()
                if app:
                    # hold() prevents app from quitting when last window closes
                    app.hold()
                    self.get_root().close()

                    def _recreate_window():
                        app.activate()
                        # Navigate back to settings page
                        windows = app.get_windows()
                        if windows:
                            windows[0]._on_nav_clicked("settings")
                        app.release()
                        return False

                    GLib.idle_add(_recreate_window)

        lang_dropdown.connect("notify::selected", _on_language_changed)
        lang_row.set_control(lang_dropdown)
        appearance_card.append(lang_row)

        content.append(appearance_card)

        # App settings
        app_card = SettingsCard(_("Application"))

        startup_row = SettingRow(
            _("Start at Login"), _("Launch JuhRadial MX when you log in")
        )
        startup_switch = Gtk.Switch()
        startup_switch.set_active(config.get("app", "start_at_login", default=True))
        startup_switch.connect("state-set", self._on_startup_changed)
        startup_row.set_control(startup_switch)
        app_card.append(startup_row)

        tray_row = SettingRow(_("Show Tray Icon"), _("Display icon in system tray"))
        tray_switch = Gtk.Switch()
        tray_switch.set_active(config.get("app", "show_tray_icon", default=True))
        tray_switch.connect(
            "state-set",
            lambda s, state: config.set("app", "show_tray_icon", state) or False,
        )
        tray_row.set_control(tray_switch)
        app_card.append(tray_row)

        content.append(app_card)

        # Device info - fetch from daemon if available
        info_card = SettingsCard(_("Device Information"))

        # Try to get actual device info from daemon
        device_name = get_device_name()
        connection_type = _("Not available")
        battery_level = _("Not available")

        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
            # Get battery status
            result = proxy.call_sync(
                "GetBatteryStatus", None, Gio.DBusCallFlags.NONE, 500, None
            )
            if result:
                percentage, charging = result.unpack()
                if percentage > 0:
                    status = _("Charging") if charging else _("Discharging")
                    battery_level = f"{percentage}% ({status})"
                    connection_type = _("Connected")
        except GLib.Error:
            pass  # Daemon may not be running

        info_items = [
            (_("Device"), device_name),
            (_("Battery"), battery_level),
            (_("Status"), connection_type),
        ]

        for label, value in info_items:
            row = SettingRow(label, value)
            info_card.append(row)

        content.append(info_card)

        # Danger zone
        danger_card = SettingsCard(_("Reset"))

        reset_row = SettingRow(
            _("Restore Defaults"), _("Reset all settings to factory defaults")
        )
        reset_btn = Gtk.Button(label=_("Reset"))
        reset_btn.add_css_class("danger-btn")
        reset_btn.connect("clicked", self._on_reset_clicked)
        reset_row.set_control(reset_btn)
        danger_card.append(reset_row)

        content.append(danger_card)

        self.set_child(content)

    def _on_theme_changed(self, dropdown, _):
        """Handle theme selection change - applies to both overlay and settings"""
        import subprocess

        selected = dropdown.get_selected()
        if 0 <= selected < len(self._theme_keys):
            theme = self._theme_keys[selected]
            config.set("theme", theme)
            config.save(show_toast=False)  # Save immediately so overlay picks it up
            print(f"Theme changed to: {theme}")

            # Reload CSS for the settings window
            self._reload_theme_css()

            # Restart the overlay to apply the new theme
            overlay_path = None
            try:
                # Kill the old overlay
                subprocess.run(
                    ["pkill", "-f", "juhradial-overlay.py"],
                    capture_output=True,
                    timeout=2,
                )
                # Start new overlay with new theme
                overlay_path = Path(__file__).parent / "juhradial-overlay.py"
                subprocess.Popen(
                    ["python3", str(overlay_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                print("Overlay restarted with new theme")
            except Exception as e:
                print(f"Could not restart overlay: {e}")

    def _reload_theme_css(self):
        """Reload CSS with new theme colors"""
        # Update the module-level COLORS that generate_css() reads from
        settings_theme.COLORS = settings_theme.load_colors()

        # Regenerate CSS with new colors
        new_css = settings_theme.generate_css()

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
        config.set("app", "start_at_login", state)
        # Create or remove autostart file
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_file = autostart_dir / "juhradial-mx.desktop"

        if state:
            # Create autostart entry
            autostart_dir.mkdir(parents=True, exist_ok=True)
            # Get the script path dynamically
            script_dir = Path(__file__).resolve().parent.parent
            exec_path = script_dir / "juhradial-mx.sh"
            # Fallback to installed location if not found
            if not exec_path.exists():
                exec_path = Path("/usr/bin/juhradial-mx")
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
            autostart_file.write_text(desktop_content, encoding="utf-8")
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
            heading=_("Settings Reset"),
            body=_(
                "All settings have been restored to defaults. Please restart JuhRadial MX for changes to take effect."
            ),
        )
        dialog.add_response("ok", _("OK"))
        dialog.present(self.get_root())
