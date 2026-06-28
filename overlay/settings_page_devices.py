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
from settings_widgets import (
    InfoCard,
    LoadingState,
    PageHeader,
    SettingRow,
    SettingsCard,
)


class DevicesPage(Gtk.ScrolledWindow):
    """Device information and management page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._device_mode = get_device_mode()
        self._is_generic = self._device_mode == "generic"

        # Live hardware state (UI-D): populated by daemon signals, primed by
        # the pull getters. Empty until the live card is built (non-generic).
        self._live_subs = []
        self._live_bus = None
        self._live_labels = {}
        self._live_dot = None

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

        # Connection + battery loaded asynchronously
        self._dynamic_loader = LoadingState(
            on_retry=self._load_dynamic_info,
            loading_text=_("Loading device info..."),
            spinner_size=24,
        )
        device_card.append(self._dynamic_loader)
        GLib.idle_add(self._load_dynamic_info)

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

        # Live hardware state card (HID++ only): battery, ratchet, host, DPI
        # reflected live from daemon signals (see _on_map).
        if not self._is_generic:
            content.append(self._build_live_card())
            self.connect("map", self._on_map)
            self.connect("unmap", self._on_unmap)

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

    def _build_dynamic_rows(self, connection_type, battery_info):
        """Build the connection + (optionally) battery rows for the loaded state."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

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
        box.append(conn_row)

        if not self._is_generic and battery_info is not None:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(12)
            sep.set_margin_bottom(12)
            box.append(sep)

            battery_row = SettingRow(_("Battery Level"), _("Current battery status"))
            battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            battery_icon = Gtk.Image.new_from_icon_name("battery-good-symbolic")
            battery_icon.add_css_class("battery-icon")
            battery_box.append(battery_icon)
            battery_label = Gtk.Label(label=battery_info)
            battery_label.add_css_class("battery-indicator")
            battery_box.append(battery_label)
            battery_row.set_control(battery_box)
            box.append(battery_row)

        return box

    def _load_dynamic_info(self):
        """Populate the LoadingState with connection + battery info via D-Bus."""
        try:
            if self._is_generic:
                connection_type = self._detect_generic_connection()
                battery_info = None
            else:
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
                # Connection
                connection_type = _("USB Receiver")
                try:
                    res = proxy.call_sync(
                        "GetBatteryStatus", None, Gio.DBusCallFlags.NONE, 500, None
                    )
                    if res:
                        connection_type = _("USB Receiver / Bluetooth")
                        percentage, charging = res.unpack()
                        if percentage > 0:
                            status = _("Charging") if charging else _("Discharging")
                            battery_info = f"{percentage}% ({status})"
                        else:
                            battery_info = _("Unavailable")
                    else:
                        battery_info = _("Unavailable")
                except GLib.Error as e:
                    raise RuntimeError(str(e)) from e

            content = self._build_dynamic_rows(connection_type, battery_info)
            self._dynamic_loader.set_loaded(content)
        except Exception:
            self._dynamic_loader.set_error(
                _("Could not reach daemon — is it running?"), retry=True
            )
        return False

    # ---------------------------------------------------------- live state (UI-D)
    def _build_live_card(self):
        """Card reflecting live HID++ state pushed by the daemon."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("settings-card")
        card.set_hexpand(True)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=_("LIVE STATE  ·  HARDWARE"))
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        title.add_css_class("section-eyebrow")
        head.append(title)

        self._live_dot = Gtk.Box()
        self._live_dot.add_css_class("connection-dot")
        self._live_dot.add_css_class("disconnected")
        self._live_dot.set_valign(Gtk.Align.CENTER)
        head.append(self._live_dot)

        badge = Gtk.Label(label=_("LIVE"))
        badge.add_css_class("live-badge")
        head.append(badge)
        card.append(head)

        readouts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        readouts.set_homogeneous(True)
        self._live_labels["battery"] = self._make_readout(readouts, _("BATTERY"))
        self._live_labels["ratchet"] = self._make_readout(readouts, _("WHEEL"))
        self._live_labels["host"] = self._make_readout(readouts, _("HOST"))
        self._live_labels["dpi"] = self._make_readout(readouts, _("DPI"))
        card.append(readouts)

        return card

    def _make_readout(self, parent, label_text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        lbl = Gtk.Label(label=label_text)
        lbl.set_halign(Gtk.Align.START)
        lbl.add_css_class("haptic-readout-label")
        box.append(lbl)
        val = Gtk.Label(label="--")
        val.set_halign(Gtk.Align.START)
        val.add_css_class("haptic-readout-num")
        box.append(val)
        parent.append(box)
        return val

    def _on_map(self, *_a):
        if self._live_subs:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            return
        # Empty sender so a daemon restart does not silence us (see CLAUDE.md).
        for signal, handler in (
            ("BatteryChanged", self._on_battery_signal),
            ("RatchetChanged", self._on_ratchet_signal),
            ("HostChanged", self._on_host_signal),
            ("DpiChanged", self._on_dpi_signal),
        ):
            self._live_subs.append(bus.signal_subscribe(
                None, "org.kde.juhradialmx.Daemon", signal,
                "/org/kde/juhradialmx/Daemon", None, Gio.DBusSignalFlags.NONE,
                handler, None,
            ))
        self._live_bus = bus
        GLib.idle_add(self._prime_live)

    def _on_unmap(self, *_a):
        if self._live_bus is not None:
            for sid in self._live_subs:
                self._live_bus.signal_unsubscribe(sid)
        self._live_subs = []

    def _set_live_connected(self):
        if self._live_dot is not None:
            self._live_dot.remove_css_class("disconnected")
            self._live_dot.add_css_class("connected")

    def _prime_live(self):
        """Pull initial values so the readouts are populated before any signal.

        Ratchet/free-spin has no pull getter, so it stays '--' until a
        RatchetChanged signal arrives.
        """
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
        except Exception:
            return False

        any_value = False
        try:
            res = proxy.call_sync(
                "GetBatteryStatus", None, Gio.DBusCallFlags.NONE, 500, None
            )
            percent, charging = res.unpack()
            if percent > 0:
                self._set_battery(percent, _("charging") if charging else "")
                any_value = True
        except GLib.GError:
            # daemon unavailable or method missing; leave this live field empty
            pass
        try:
            res = proxy.call_sync("GetDpi", None, Gio.DBusCallFlags.NONE, 500, None)
            (dpi,) = res.unpack()
            if dpi > 0:
                self._live_labels["dpi"].set_label(str(dpi))
                any_value = True
        except GLib.GError:
            # daemon unavailable or method missing; leave this live field empty
            pass
        try:
            res = proxy.call_sync(
                "GetEasySwitchInfo", None, Gio.DBusCallFlags.NONE, 500, None
            )
            num_hosts, current = res.unpack()
            if num_hosts > 0:
                self._live_labels["host"].set_label(str(current + 1))
                any_value = True
        except GLib.GError:
            # daemon unavailable or method missing; leave this live field empty
            pass

        if any_value:
            self._set_live_connected()
        return False

    def _set_battery(self, percent, status):
        text = f"{percent}%"
        if status:
            text = f"{text} · {status}"
        self._live_labels["battery"].set_label(text)

    def _on_battery_signal(self, _c, _s, _p, _i, _sig, params, _u):
        percent, status = params.unpack()
        self._set_battery(percent, status)
        self._set_live_connected()

    def _on_ratchet_signal(self, _c, _s, _p, _i, _sig, params, _u):
        (ratchet,) = params.unpack()
        self._live_labels["ratchet"].set_label(
            _("RATCHET") if ratchet else _("FREE-SPIN")
        )
        self._set_live_connected()

    def _on_host_signal(self, _c, _s, _p, _i, _sig, params, _u):
        (host,) = params.unpack()
        self._live_labels["host"].set_label(str(host + 1))
        self._set_live_connected()

    def _on_dpi_signal(self, _c, _s, _p, _i, _sig, params, _u):
        (dpi,) = params.unpack()
        self._live_labels["dpi"].set_label(str(dpi))
        self._set_live_connected()

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
        except OSError:
            pass  # HID sysfs scan can fail on some systems
        return _("USB")
