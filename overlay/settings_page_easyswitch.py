#!/usr/bin/env python3
"""
JuhRadial MX - Easy-Switch Page

EasySwitchPage and PlaceholderPage for device switching.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw

from i18n import _
from settings_widgets import GeneratedAssetHero, SettingsCard, PageHeader, InfoCard, LoadingState
from settings_config import config

logger = logging.getLogger(__name__)

# OS options for Easy-Switch host identification
OS_OPTIONS = [
    ("linux", "Linux"),
    ("windows", "Windows"),
    ("macos", "macOS"),
    ("ios", "iOS"),
    ("android", "Android"),
    ("chromeos", "ChromeOS"),
    ("unknown", "Unknown"),
]


class PlaceholderPage(Gtk.Box):
    """Placeholder for unimplemented pages"""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        icon.set_pixel_size(48)
        icon.set_opacity(0.5)
        self.append(icon)

        label = Gtk.Label(label=f"{title}\n" + _("Coming Soon"))
        label.set_justify(Gtk.Justification.CENTER)
        label.set_opacity(0.6)
        self.append(label)


class EasySwitchPage(Gtk.ScrolledWindow):
    """Easy-Switch configuration page - shows paired hosts and current slot"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.slot_buttons = []
        self.slot_labels = []
        self.host_names = []
        self.num_hosts = 0
        self.current_host = 0
        self.daemon_proxy = None  # Store D-Bus proxy for reuse

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Page header
        header = PageHeader(
            "network-wireless-symbolic",
            _("Easy-Switch"),
            _("Switch between paired computers"),
        )
        content.append(header)
        content.append(
            GeneratedAssetHero("settings-generated/easyswitch.png", max_height=190)
        )

        # Action buttons below header
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_box.set_halign(Gtk.Align.CENTER)
        actions_box.set_margin_bottom(8)

        refresh_btn = Gtk.Button(label=_("Refresh"))
        refresh_btn.add_css_class("suggested-action")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        actions_box.append(refresh_btn)

        self.detected_slots_label = Gtk.Label(label="")
        self.detected_slots_label.add_css_class("dim-label")
        actions_box.append(self.detected_slots_label)

        content.append(actions_box)

        # Host Slots Card
        self.slots_card = SettingsCard(_("Paired Computers"))

        # Will be populated by _load_host_info
        self.slots_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.slots_box.set_margin_top(8)
        self.slots_box.set_margin_bottom(8)
        self.slots_loader = LoadingState(
            on_retry=self._on_refresh_clicked_no_btn,
            loading_text=_("Loading paired computers..."),
            spinner_size=24,
        )
        self.slots_card.append(self.slots_loader)

        content.append(self.slots_card)

        # Info Card (quieter styling)
        info_card = InfoCard(_("About Easy-Switch"))
        info_label = Gtk.Label()
        info_label.set_markup(
            _(
                "Easy-Switch allows your mouse to connect to multiple computers.\n"
                "Use the button on your mouse to switch between paired devices."
            )
            + "\n\n"
            "<b>"
            + _("Note:")
            + "</b> "
            + _(
                "Host names are read from the device and reflect\n"
                "the computer names set during pairing."
            )
            + "\n\n"
            + _(
                "Slots are auto-detected from your mouse pairing state. "
                "Add or remove pairings on the mouse/receiver side, then press Refresh here."
            )
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        info_card.append(info_label)

        content.append(info_card)

        # Wrap in Adw.Clamp for responsive centering
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(content)
        self.set_child(clamp)

        # Load host info from D-Bus
        GLib.idle_add(self._load_host_info)

    def _create_slot_widget(self, slot_index, is_current=False):
        """Create a clickable widget for a single Easy-Switch slot"""
        # Outer container: button on the left, OS dropdown on the right
        outer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Create the content box for the button
        slot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        slot_box.set_margin_start(8)
        slot_box.set_margin_end(8)
        slot_box.set_margin_top(8)
        slot_box.set_margin_bottom(8)

        # Slot indicator
        indicator = Gtk.Box()
        indicator.set_size_request(12, 12)
        indicator.add_css_class("connection-dot")
        if is_current:
            indicator.add_css_class("connected")
        else:
            indicator.add_css_class("disconnected")
        slot_box.append(indicator)

        # Computer icon
        conn_icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        conn_icon.set_pixel_size(24)
        if is_current:
            conn_icon.add_css_class("accent-color")
        else:
            conn_icon.add_css_class("dim-label")
        slot_box.append(conn_icon)

        # Name and status
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        # Get host name if available
        host_name = _("Slot {}").format(slot_index + 1)
        if slot_index < len(self.host_names) and self.host_names[slot_index]:
            host_name = self.host_names[slot_index]

        name_label = Gtk.Label(label=host_name)
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class("heading")
        text_box.append(name_label)
        self.slot_labels.append(name_label)

        status_text = _("Connected") if is_current else _("Click to switch")
        status_label = Gtk.Label(label=status_text)
        status_label.set_halign(Gtk.Align.START)
        status_label.add_css_class("dim-label")
        status_label.add_css_class("caption")
        text_box.append(status_label)

        slot_box.append(text_box)

        # Status badge or switch indicator
        if is_current:
            badge = Gtk.Label(label=_("Active"))
            badge.add_css_class("success")
            badge.add_css_class("badge")
            slot_box.append(badge)
        else:
            # Add arrow icon to indicate clickable
            arrow_icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow_icon.set_pixel_size(16)
            arrow_icon.add_css_class("dim-label")
            slot_box.append(arrow_icon)

        # Wrap in a button for clickability
        host_button = Gtk.Button()
        host_button.add_css_class("flat")
        host_button.set_hexpand(True)
        host_button.set_child(slot_box)
        host_button.connect("clicked", self._on_host_clicked, slot_index)

        # Make current host button less prominent (already connected)
        if is_current:
            host_button.set_sensitive(False)

        self.slot_buttons.append(host_button)
        outer_box.append(host_button)

        # OS type dropdown (outside button so it's always interactive)
        os_types = config.get("radial_menu", "easy_switch_host_os", default=["linux", "unknown", "unknown"])
        current_os = os_types[slot_index] if slot_index < len(os_types) else "unknown"

        os_labels = [label for _, label in OS_OPTIONS]
        os_model = Gtk.StringList.new(os_labels)
        os_dropdown = Gtk.DropDown(model=os_model)
        os_dropdown.set_valign(Gtk.Align.CENTER)

        # Set current selection
        os_keys = [key for key, _ in OS_OPTIONS]
        if current_os in os_keys:
            os_dropdown.set_selected(os_keys.index(current_os))
        else:
            os_dropdown.set_selected(len(os_keys) - 1)  # "unknown"

        os_dropdown.connect("notify::selected", self._on_os_changed, slot_index)
        outer_box.append(os_dropdown)

        return outer_box

    def _on_host_clicked(self, button, host_index):
        """Handle click on a host slot to switch to that host"""
        if host_index == self.current_host:
            return  # Already on this host

        logger.info("Switching to host %s...", host_index)

        try:
            if self.daemon_proxy:
                # Call SetHost with the host index (y = uint8/byte)
                self.daemon_proxy.call_sync(
                    "SetHost",
                    GLib.Variant("(y)", (host_index,)),
                    Gio.DBusCallFlags.NONE,
                    5000,  # 5 second timeout for host switch
                    None,
                )
                logger.info("Successfully requested switch to host %s", host_index)

                # Update current host and refresh display
                self.current_host = host_index
                self._update_slot_display()
            else:
                logger.warning("D-Bus proxy not available")
        except Exception as e:
            logger.error("Failed to switch host: %s", e)

    def _on_os_changed(self, dropdown, _pspec, slot_index):
        """Handle OS type change for a host slot"""
        selected = dropdown.get_selected()
        os_keys = [key for key, _ in OS_OPTIONS]
        os_type = os_keys[selected] if selected < len(os_keys) else "unknown"

        os_types = list(config.get("radial_menu", "easy_switch_host_os", default=["linux", "unknown", "unknown"]))
        # Extend list if needed
        while len(os_types) <= slot_index:
            os_types.append("unknown")
        os_types[slot_index] = os_type
        config.set("radial_menu", "easy_switch_host_os", os_types, auto_save=True)

    def _load_host_info(self):
        """Load host information from daemon via D-Bus"""
        try:
            if self.daemon_proxy is None:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self.daemon_proxy = Gio.DBusProxy.new_sync(
                    bus,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    "org.kde.juhradialmx",
                    "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon",
                    None,
                )

            # Get Easy-Switch info (num_hosts, current_host)
            try:
                result = self.daemon_proxy.call_sync(
                    "GetEasySwitchInfo", None, Gio.DBusCallFlags.NONE, 2000, None
                )
                if result:
                    self.num_hosts, self.current_host = result.unpack()
                    logger.info(
                        "Easy-Switch: %s hosts, current=%s", self.num_hosts, self.current_host
                    )
            except Exception as e:
                logger.warning("Could not get Easy-Switch info: %s", e)
                self.num_hosts = 3  # Default to 3 slots
                self.current_host = 0

            # Get host names
            try:
                result = self.daemon_proxy.call_sync(
                    "GetHostNames", None, Gio.DBusCallFlags.NONE, 2000, None
                )
                if result:
                    self.host_names = list(result.unpack()[0])
                    logger.debug("Host names: %s", self.host_names)
            except Exception as e:
                logger.warning("Could not get host names: %s", e)
                self.host_names = []

            # Update UI with slots
            self._update_slot_display()
            self.slots_loader.set_loaded(self.slots_box)

        except Exception as e:
            logger.error("Failed to connect to D-Bus: %s", e)
            self.slots_loader.set_error(
                _("Could not reach daemon — is it running?"), retry=True
            )

        return False  # Don't repeat

    def _on_refresh_clicked(self, _button):
        """Refresh host information from daemon"""
        self.daemon_proxy = None
        self.slots_loader.set_loading()
        GLib.idle_add(self._load_host_info)

    def _on_refresh_clicked_no_btn(self):
        """Retry callback variant for the inline LoadingState button."""
        self.daemon_proxy = None
        GLib.idle_add(self._load_host_info)

    def _update_slot_display(self):
        """Update the slot display with host information"""
        # Clear existing slots
        while child := self.slots_box.get_first_child():
            self.slots_box.remove(child)

        self.slot_labels = []
        self.slot_buttons = []

        # Show detected slot count in header
        if self.num_hosts > 0:
            self.detected_slots_label.set_label(
                _("Detected slots: {}").format(self.num_hosts)
            )
        else:
            self.detected_slots_label.set_label(_("Detected slots: --"))

        # Create slot widgets (now buttons)
        num_slots = self.num_hosts if self.num_hosts > 0 else 3
        for i in range(num_slots):
            is_current = i == self.current_host
            slot_widget = self._create_slot_widget(i, is_current)
            self.slots_box.append(slot_widget)

            # Add separator except for last
            if i < num_slots - 1:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                sep.set_margin_top(4)
                sep.set_margin_bottom(4)
                self.slots_box.append(sep)
