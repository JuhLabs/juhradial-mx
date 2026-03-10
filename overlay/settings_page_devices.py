#!/usr/bin/env python3
"""
JuhRadial MX - Devices Page

DevicesPage: Device information and management.

SPDX-License-Identifier: GPL-3.0
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, Gio, GLib, Adw

from i18n import _
from settings_config import get_device_name, get_device_mode, get_device_name_from_daemon
from settings_theme import COLORS
from settings_widgets import SettingsCard, SettingRow, PageHeader, InfoCard


class DevicesPage(Gtk.ScrolledWindow):
    """Device information and management page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._device_mode = get_device_mode()
        self._is_generic = self._device_mode == "generic"

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Page header
        header = PageHeader(
            "computer-symbolic",
            _("Devices"),
            _("Connected device information"),
        )
        content.append(header)

        # Generic mode banner
        if self._is_generic:
            banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            banner.add_css_class("card")
            banner.set_margin_bottom(8)

            banner_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
            banner_icon.set_pixel_size(24)
            banner.append(banner_icon)

            banner_label = Gtk.Label()
            banner_label.set_markup(
                f'<span weight="bold">{_("Generic Mouse Mode")}</span>'
                f' - {_("Some features require a Logitech MX mouse")}'
            )
            banner_label.set_wrap(True)
            banner_label.set_halign(Gtk.Align.START)
            banner.append(banner_label)

            banner.set_margin_top(12)
            banner.set_margin_bottom(12)
            banner.set_margin_start(12)
            banner.set_margin_end(12)

            content.append(banner)

        # Device Information Card
        device_card = SettingsCard(_("Connected Device"))

        # Device image (generic vs Logitech)
        if self._is_generic:
            device_image_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            device_image_box.set_halign(Gtk.Align.CENTER)
            device_image_box.set_margin_top(8)
            device_image_box.set_margin_bottom(16)

            # Try multiple paths for the generic mouse image
            generic_img_path = (
                Path(__file__).resolve().parent.parent
                / "assets" / "devices" / "genericmouse.png"
            )
            if not generic_img_path.exists():
                generic_img_path = Path("/usr/share/juhradial/assets/devices/genericmouse.png")
            if generic_img_path.exists():
                try:
                    from gi.repository import GdkPixbuf

                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(generic_img_path), -1, 120, True
                    )
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    img_widget = Gtk.Picture.new_for_paintable(texture)
                    device_image_box.append(img_widget)
                except Exception:
                    fallback = Gtk.Label(label=_("Generic Mouse"))
                    fallback.add_css_class("title-2")
                    device_image_box.append(fallback)
            else:
                # Image file doesn't exist yet - show text fallback
                fallback_icon = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
                fallback_icon.set_pixel_size(64)
                device_image_box.append(fallback_icon)

                fallback_text = Gtk.Label(label=_("Generic Mouse"))
                fallback_text.add_css_class("title-2")
                fallback_text.set_margin_start(12)
                device_image_box.append(fallback_text)

            device_card.append(device_image_box)

        # Device name
        device_name = (
            get_device_name_from_daemon() if self._is_generic else get_device_name()
        )
        subtitle = (
            _("Your connected mouse")
            if self._is_generic
            else _("Your Logitech mouse model")
        )
        name_row = SettingRow(_("Device Name"), subtitle)
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
        if self._is_generic:
            conn_row = SettingRow(_("Connection"), _("How your device is connected"))
            conn_icon_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8
            )
            # Generic mice: simple USB or Bluetooth detection
            conn_type = self._detect_generic_connection()
            if "Bluetooth" in conn_type:
                conn_icon = Gtk.Image.new_from_icon_name("bluetooth-symbolic")
            else:
                conn_icon = Gtk.Image.new_from_icon_name("usb-symbolic")
            conn_icon.add_css_class("accent-color")
            conn_icon_box.append(conn_icon)
            conn_label = Gtk.Label(label=conn_type)
            conn_icon_box.append(conn_label)
            conn_row.set_control(conn_icon_box)
            device_card.append(conn_row)
        else:
            connection_type = self._get_connection_type()
            conn_row = SettingRow(
                _("Connection"), _("How your device is connected")
            )
            conn_icon_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8
            )

            if "Bluetooth" in connection_type:
                conn_icon = Gtk.Image.new_from_icon_name("bluetooth-symbolic")
            elif "USB" in connection_type:
                conn_icon = Gtk.Image.new_from_icon_name("usb-symbolic")
            else:
                conn_icon = Gtk.Image.new_from_icon_name(
                    "network-wireless-symbolic"
                )

            conn_icon.add_css_class("accent-color")
            conn_icon_box.append(conn_icon)

            conn_label = Gtk.Label(label=connection_type)
            conn_icon_box.append(conn_label)
            conn_row.set_control(conn_icon_box)
            device_card.append(conn_row)

        # Battery section - only for Logitech (HID++ battery reporting)
        if not self._is_generic:
            # Separator
            sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep2.set_margin_top(12)
            sep2.set_margin_bottom(12)
            device_card.append(sep2)

            # Battery level
            battery_info = self._get_battery_info()
            battery_row = SettingRow(
                _("Battery Level"), _("Current battery status")
            )
            battery_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8
            )

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
        fw_label = Gtk.Label(label=_("Managed by JuhRadial MX"))
        fw_label.add_css_class("dim-label")
        fw_row.set_control(fw_label)
        device_card.append(fw_row)

        content.append(device_card)

        # Additional Info Card (quieter styling)
        info_card = InfoCard(_("Device Management"))

        if self._is_generic:
            info_text = _(
                "JuhRadial MX is running in generic mouse mode. "
                "The radial menu, button keybinds, and pointer speed are fully "
                "available. HID++ features (haptics, SmartShift, Easy-Switch, "
                "Flow) require a Logitech MX mouse."
            )
        else:
            info_text = _(
                "JuhRadial MX handles device configuration natively via HID++. "
                "Button remapping, scroll settings, and haptics are all managed "
                "through this settings window."
            )

        info_label = Gtk.Label()
        info_label.set_markup(
            info_text
            + "\n\n"
            'GitHub: <a href="https://github.com/JuhLabs/juhradial-mx">'
            "https://github.com/JuhLabs/juhradial-mx</a>"
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

        # Wrap in Adw.Clamp for responsive centering
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(content)
        self.set_child(clamp)

    def _detect_generic_connection(self):
        """Detect connection type for a generic (non-Logitech) mouse.

        Checks /sys/bus/hid/devices/ for Bluetooth bus type.
        Returns 'Bluetooth' or 'USB'.
        """
        try:
            from pathlib import Path as _Path

            hid_path = _Path("/sys/bus/hid/devices/")
            if hid_path.exists():
                for device in hid_path.iterdir():
                    # HID device names: BBBB:VVVV:PPPP.NNNN
                    # Bus type 0005 = Bluetooth, 0003 = USB
                    name = device.name.upper()
                    if name.startswith("0005:"):
                        # Check if this is a mouse (has input with mouse capabilities)
                        uevent = device / "uevent"
                        if uevent.exists():
                            text = uevent.read_text(errors="ignore")
                            if "MOUSE" in text.upper() or "POINTER" in text.upper():
                                return _("Bluetooth")
        except Exception:
            pass  # HID sysfs scan can fail on some systems
        return _("USB")

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
                    # 0% usually means battery info unavailable
                    return _("Unavailable")
        except GLib.Error:
            pass  # Daemon may not be running
        return _("Unavailable")
