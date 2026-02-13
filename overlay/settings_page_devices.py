#!/usr/bin/env python3
"""
JuhRadial MX - Devices Page

DevicesPage: Device information and management.

SPDX-License-Identifier: GPL-3.0
"""

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Gdk, Gio

from i18n import _
from settings_config import get_device_name
from settings_widgets import SettingsCard, SettingRow


class DevicesPage(Gtk.ScrolledWindow):
    """Device information and management page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(32)
        content.set_margin_end(32)

        # Device Information Card
        device_card = SettingsCard(_("Connected Device"))

        # Device name
        device_name = get_device_name()
        name_row = SettingRow(_("Device Name"), _("Your Logitech mouse model"))
        name_label = Gtk.Label(label=device_name)
        name_label.add_css_class("heading")
        name_row.set_control(name_label)
        device_card.append(name_row)

        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep1.set_margin_top(12)
        sep1.set_margin_bottom(12)
        device_card.append(sep1)

        # Connection status
        connection_type = self._get_connection_type()
        conn_row = SettingRow(_("Connection"), _("How your device is connected"))
        conn_icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        if "Bluetooth" in connection_type:
            conn_icon = Gtk.Image.new_from_icon_name("bluetooth-symbolic")
        elif "USB" in connection_type:
            conn_icon = Gtk.Image.new_from_icon_name("usb-symbolic")
        else:
            conn_icon = Gtk.Image.new_from_icon_name("network-wireless-symbolic")

        conn_icon.add_css_class("accent-color")
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
        battery_row = SettingRow(_("Battery Level"), _("Current battery status"))
        battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        battery_icon = Gtk.Image.new_from_icon_name("battery-good-symbolic")
        battery_icon.add_css_class("battery-icon")
        battery_box.append(battery_icon)

        battery_label = Gtk.Label(label=battery_info)
        battery_label.add_css_class("battery-indicator")
        battery_box.append(battery_label)
        battery_row.set_control(battery_box)
        device_card.append(battery_row)

        # Separator
        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep3.set_margin_top(12)
        sep3.set_margin_bottom(12)
        device_card.append(sep3)

        # Firmware version (placeholder)
        fw_row = SettingRow(_("Firmware Version"), _("Device firmware information"))
        fw_label = Gtk.Label(label=_("Managed by LogiOps"))
        fw_label.add_css_class("dim-label")
        fw_row.set_control(fw_label)
        device_card.append(fw_row)

        content.append(device_card)

        # Additional Info Card
        info_card = SettingsCard(_("Device Management"))

        info_label = Gtk.Label()
        info_label.set_markup(
            _(
                "For advanced device configuration (button remapping, scroll settings), "
                "edit <b>/etc/logid.cfg</b> and restart logid."
            )
            + "\n\n"
            'LogiOps docs: <a href="https://github.com/PixlOne/logiops">https://github.com/PixlOne/logiops</a>'
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        # Make links clickable and open in browser
        info_label.connect(
            "activate-link",
            lambda label, uri: (Gtk.show_uri(None, uri, Gdk.CURRENT_TIME), True)[-1],
        )
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
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
            # Try to get battery status as indicator of connection
            result = proxy.call_sync(
                "GetBatteryStatus", None, Gio.DBusCallFlags.NONE, 500, None
            )
            if result:
                return _("USB Receiver / Bluetooth")
        except GLib.Error:
            pass  # Daemon may not be running
        return _("USB Receiver")

    def _get_battery_info(self):
        """Get battery info from daemon"""
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
            result = proxy.call_sync(
                "GetBatteryStatus", None, Gio.DBusCallFlags.NONE, 500, None
            )
            if result:
                percentage, charging = result.unpack()
                if percentage > 0:
                    status = _("Charging") if charging else _("Discharging")
                    return f"{percentage}% ({status})"
                else:
                    # 0% usually means unavailable (logid controlling HID++)
                    return _("Managed by LogiOps")
        except GLib.Error:
            pass  # Daemon may not be running
        return _("Managed by LogiOps")
