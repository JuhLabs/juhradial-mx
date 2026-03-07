#!/usr/bin/env python3
"""
JuhRadial MX - Flow Page

FlowPage UI layout and toggle handlers for multi-computer control.
Network discovery and pairing logic lives in settings_flow_discovery.py.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Gio, Adw

from i18n import _
from settings_config import config
from settings_widgets import SettingsCard, SettingRow, PageHeader, InfoCard
from settings_flow_discovery import FlowServiceListener, FlowDiscoveryMixin

# Flow module for multi-computer control
try:
    from flow import (
        start_flow_server,
        stop_flow_server,
        get_flow_server,
        get_linked_computers,
        FlowClient,
        FLOW_PORT,
    )

    FLOW_MODULE_AVAILABLE = True
except ImportError:
    FLOW_MODULE_AVAILABLE = False

logger = logging.getLogger(__name__)


class FlowPage(FlowDiscoveryMixin, Gtk.ScrolledWindow):
    """Flow multi-computer control settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.discovered_computers = {}  # Store discovered computers
        self._zeroconf = None  # Track Zeroconf instance for cleanup
        self._registered_services = []  # Track registered ServiceInfo for unregistration
        self._programmatic_toggle = False  # Guard against re-entrant signal
        self._connect_reset_timer = None  # Timer for connect button reset

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        main_box.set_margin_top(24)
        main_box.set_margin_bottom(24)

        # Page header
        header = PageHeader(
            "view-dual-symbolic",
            _("JuhFlow"),
            _("Seamlessly move between computers"),
        )
        main_box.append(header)

        # Enable Flow Card
        enable_card = SettingsCard(_("Flow Control"))

        enable_row = SettingRow(
            _("Enable Flow"), _("Control multiple computers with one mouse")
        )
        self.flow_switch = Gtk.Switch()
        self.flow_switch.set_active(config.get("flow", "enabled", default=False))
        self.flow_switch.connect("state-set", self._on_flow_toggled)
        enable_row.set_control(self.flow_switch)
        enable_card.append(enable_row)

        # Edge trigger option
        edge_row = SettingRow(
            _("Switch at screen edge"), _("Move cursor to edge to switch computers")
        )
        self.edge_switch = Gtk.Switch()
        self.edge_switch.set_active(config.get("flow", "edge_trigger", default=True))
        self.edge_switch.set_sensitive(config.get("flow", "enabled", default=False))
        self.edge_switch.connect("state-set", self._on_edge_toggled)
        edge_row.set_control(self.edge_switch)
        enable_card.append(edge_row)

        # Flow direction - which edge the peer is on
        direction_row = SettingRow(
            _("Peer direction"), _("Which screen edge to cross to the other computer")
        )
        self.direction_dropdown = Gtk.DropDown.new_from_strings(
            [_("Right"), _("Left"), _("Top"), _("Bottom")]
        )
        direction_map = {"right": 0, "left": 1, "top": 2, "bottom": 3}
        current_dir = config.get("flow", "direction", default="right")
        self.direction_dropdown.set_selected(direction_map.get(current_dir, 0))
        self.direction_dropdown.set_sensitive(config.get("flow", "enabled", default=False))
        self.direction_dropdown.connect("notify::selected", self._on_direction_changed)
        direction_row.set_control(self.direction_dropdown)
        enable_card.append(direction_row)

        # Monitor selection for multi-monitor setups
        monitor_row = SettingRow(
            _("Monitor"), _("Which screen to show the indicator and detect edges on")
        )
        self._monitor_connectors = self._get_monitor_connectors()
        monitor_labels = [_("Auto")] + [
            f"{c['connector']} ({c['width']}x{c['height']})"
            for c in self._monitor_connectors
        ]
        self.monitor_dropdown = Gtk.DropDown.new_from_strings(monitor_labels)
        current_monitor = config.get("flow", "monitor", default="")
        # "" = Auto (index 0), connector name = find matching index
        dropdown_idx = 0
        if current_monitor:
            for i, c in enumerate(self._monitor_connectors):
                if c["connector"] == current_monitor:
                    dropdown_idx = i + 1
                    break
        if dropdown_idx < len(monitor_labels):
            self.monitor_dropdown.set_selected(dropdown_idx)
        self.monitor_dropdown.set_sensitive(config.get("flow", "enabled", default=False))
        self.monitor_dropdown.connect("notify::selected", self._on_monitor_changed)
        monitor_row.set_control(self.monitor_dropdown)
        enable_card.append(monitor_row)

        # JuhFlow companion status + connect button
        juhflow_row = SettingRow(
            _("JuhFlow companion"), _("Mac/Windows companion app status")
        )
        self._juhflow_control_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        self._juhflow_status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6
        )
        self._juhflow_dot = Gtk.Box()
        self._juhflow_dot.set_size_request(8, 8)
        self._juhflow_dot.add_css_class("connection-dot")
        self._juhflow_status_box.append(self._juhflow_dot)
        self._juhflow_label = Gtk.Label(label=_("Checking..."))
        self._juhflow_label.add_css_class("caption")
        self._juhflow_status_box.append(self._juhflow_label)
        self._juhflow_control_box.append(self._juhflow_status_box)

        self._juhflow_connect_btn = Gtk.Button(label=_("Connect"))
        self._juhflow_connect_btn.add_css_class("suggested-action")
        self._juhflow_connect_btn.add_css_class("caption")
        self._juhflow_connect_btn.connect("clicked", self._on_juhflow_connect)
        self._juhflow_control_box.append(self._juhflow_connect_btn)

        juhflow_row.set_control(self._juhflow_control_box)
        enable_card.append(juhflow_row)

        # Poll JuhFlow status every 3 seconds
        self._update_juhflow_status()
        self._juhflow_poll = GLib.timeout_add(3000, self._update_juhflow_status)

        main_box.append(enable_card)

        # Indicator Card
        indicator_card = SettingsCard(_("Indicator"))

        # Hide indicator toggle
        hide_row = SettingRow(
            _("Hide indicator"), _("Use Flow without the visual edge indicator")
        )
        self.hide_indicator_switch = Gtk.Switch()
        self.hide_indicator_switch.set_active(
            config.get("flow", "hide_indicator", default=False)
        )
        self.hide_indicator_switch.set_sensitive(
            config.get("flow", "enabled", default=False)
        )
        self.hide_indicator_switch.connect("state-set", self._on_hide_indicator_toggled)
        hide_row.set_control(self.hide_indicator_switch)
        indicator_card.append(hide_row)

        # Extend edge zone toggle
        extend_row = SettingRow(
            _("Extend edge trigger area"),
            _("Trigger across the full screen edge instead of just the indicator zone"),
        )
        self.extend_zone_switch = Gtk.Switch()
        self.extend_zone_switch.set_active(
            config.get("flow", "extend_edge_zone", default=False)
        )
        self.extend_zone_switch.set_sensitive(
            config.get("flow", "enabled", default=False)
        )
        self.extend_zone_switch.connect("state-set", self._on_extend_zone_toggled)
        extend_row.set_control(self.extend_zone_switch)
        indicator_card.append(extend_row)

        main_box.append(indicator_card)

        # Detected Computers Card
        computers_card = SettingsCard(_("Computers on Network"))

        self.computers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.computers_box.set_margin_top(8)
        self.computers_box.set_margin_bottom(8)

        # Placeholder for no computers detected
        self.no_computers_label = Gtk.Label(label=_("No other computers detected"))
        self.no_computers_label.add_css_class("dim-label")
        self.no_computers_label.set_margin_top(16)
        self.no_computers_label.set_margin_bottom(16)
        self.computers_box.append(self.no_computers_label)

        computers_card.append(self.computers_box)

        # Scan button
        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        scan_box.set_halign(Gtk.Align.END)
        scan_box.set_margin_top(8)

        self.scan_button = Gtk.Button(label=_("Scan Network"))
        self.scan_button.add_css_class("suggested-action")
        self.scan_button.connect("clicked", self._on_scan_clicked)
        scan_box.append(self.scan_button)

        computers_card.append(scan_box)

        main_box.append(computers_card)

        # How Flow Works Card (quieter styling)
        info_card = InfoCard(_("How Flow Works"))
        info_label = Gtk.Label()
        info_label.set_markup(
            "<b>" + _("Overview") + "</b>\n"
            + _(
                "Flow lets you control multiple computers with one mouse. "
                "Move your cursor to a screen edge and it seamlessly jumps "
                "to the other computer - just like Logitech Options+ Flow."
            )
            + "\n\n"
            "<b>" + _("Security") + "</b>\n"
            + _(
                "All communication is end-to-end encrypted using X25519 key exchange, "
                "HKDF-SHA256 key derivation, and AES-256-GCM authenticated encryption - "
                "the same cryptographic standard as Logi Options+ Flow."
            )
            + "\n\n"
            "<b>" + _("How it connects") + "</b>\n"
            "  \u2022 " + _("Computers discover each other via mDNS on your local network") + "\n"
            "  \u2022 " + _("A secure handshake exchanges encryption keys between devices") + "\n"
            "  \u2022 " + _("The JuhFlow companion app bridges Linux and macOS/Windows") + "\n"
            "  \u2022 " + _("Edge detection triggers a host switch command to your mouse") + "\n\n"
            "<b>" + _("Requirements") + "</b>\n"
            "  \u2022 " + _("JuhRadial MX on Linux") + "\n"
            "  \u2022 " + _("JuhFlow companion app on macOS (or Windows)") + "\n"
            "  \u2022 " + _("Both computers on the same local network") + "\n"
            "  \u2022 " + _("Logitech MX mouse with Easy-Switch")
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        info_card.append(info_label)

        main_box.append(info_card)

        # Wrap in Adw.Clamp for responsive centering
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(main_box)
        self.set_child(clamp)

        # Try to discover computers on startup
        GLib.idle_add(self._discover_computers)

    def _on_flow_toggled(self, switch, state):
        """Handle Flow enable/disable toggle"""
        if self._programmatic_toggle:
            return True
        config.set("flow", "enabled", state, auto_save=True)
        # Enable/disable sub-controls based on Flow state
        self.edge_switch.set_sensitive(state)
        self.direction_dropdown.set_sensitive(state)
        self.monitor_dropdown.set_sensitive(state)
        self.hide_indicator_switch.set_sensitive(state)
        self.extend_zone_switch.set_sensitive(state)

        if FLOW_MODULE_AVAILABLE:
            if state:
                # Start the Flow server
                def on_host_change(new_host):
                    """Called when another computer changes hosts"""
                    logger.info("Received host change request: %s", new_host)
                    # Switch our devices via D-Bus
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
                        proxy.call_sync(
                            "SetHost",
                            GLib.Variant("(y)", (new_host,)),
                            Gio.DBusCallFlags.NONE,
                            5000,
                            None,
                        )
                    except Exception as e:
                        logger.error("Error switching host: %s", e)

                start_flow_server(on_host_change=on_host_change)

                # Enable edge detection if configured
                edge_enabled = config.get("flow", "edge_trigger", default=True)
                if edge_enabled:
                    try:
                        from flow import get_edge_detector
                        detector = get_edge_detector()
                        if detector:
                            detector.set_enabled(True)
                    except Exception:
                        pass

                logger.info("Server started")
            else:
                # Stop the Flow server
                stop_flow_server()
                logger.info("Server stopped")

        return False

    def _on_direction_changed(self, dropdown, _pspec):
        """Handle flow direction change"""
        idx = dropdown.get_selected()
        direction_values = ["right", "left", "top", "bottom"]
        direction = direction_values[idx] if idx < len(direction_values) else "right"
        config.set("flow", "direction", direction, auto_save=True)
        logger.info("Direction set to: %s", direction)

        # Update the indicator position if running
        if FLOW_MODULE_AVAILABLE:
            try:
                from flow import _flow_indicator
                if _flow_indicator:
                    _flow_indicator.configure(direction)
            except Exception:
                pass

    def _on_edge_toggled(self, switch, state):
        """Handle edge trigger toggle"""
        config.set("flow", "edge_trigger", state, auto_save=True)

        # Wire to actual edge detector
        if FLOW_MODULE_AVAILABLE:
            try:
                from flow import get_edge_detector
                detector = get_edge_detector()
                if detector:
                    detector.set_enabled(state)
            except Exception as e:
                logger.error("Edge toggle error: %s", e)
        return False

    def _on_monitor_changed(self, dropdown, _pspec):
        """Handle monitor selection change."""
        idx = dropdown.get_selected()
        # Index 0 = Auto (""), index 1+ = connector name (stable across reboots)
        if idx == 0 or idx - 1 >= len(self._monitor_connectors):
            monitor_val = ""
        else:
            monitor_val = self._monitor_connectors[idx - 1]["connector"]
        config.set("flow", "monitor", monitor_val, auto_save=True)
        logger.info("Monitor set to %s", "auto" if not monitor_val else monitor_val)

    def _on_hide_indicator_toggled(self, switch, state):
        """Handle hide indicator toggle."""
        config.set("flow", "hide_indicator", state, auto_save=True)
        logger.debug("Hide indicator: %s", state)
        return False

    def _on_extend_zone_toggled(self, switch, state):
        """Handle extend edge zone toggle."""
        config.set("flow", "extend_edge_zone", state, auto_save=True)
        logger.debug("Extend edge zone: %s", state)
        return False

    def _update_juhflow_status(self):
        """Check if JuhFlow companion app is connected via bridge.

        Reads the status file written by the overlay process's bridge,
        since settings runs in a separate process and can't access the
        bridge directly.
        """
        peers = []
        # First try the status file (written by the overlay's bridge)
        try:
            import json as _json
            status_path = os.path.join(
                os.path.expanduser("~"), ".config", "juhradial", "flow_status.json"
            )
            with open(status_path) as f:
                status = _json.load(f)
            # Only trust status if updated within the last 10 seconds
            if time.time() - status.get("updated_at", 0) < 10:
                peers = status.get("peers", [])
        except (FileNotFoundError, ValueError):
            pass
        # Fallback: try in-process bridge (works if settings started flow)
        if not peers and FLOW_MODULE_AVAILABLE:
            try:
                from flow import get_juhflow_bridge
                bridge = get_juhflow_bridge()
                if bridge:
                    peers = bridge.get_peers()
            except Exception:
                pass

        if peers:
            name = peers[0].get("hostname", "Mac")
            self._juhflow_dot.remove_css_class("disconnected")
            self._juhflow_dot.add_css_class("connected")
            self._juhflow_label.set_text(_("Connected - {}").format(name))
            self._juhflow_label.remove_css_class("dim-label")
            self._juhflow_label.add_css_class("success")
            self._juhflow_connect_btn.set_visible(False)
        else:
            self._juhflow_dot.remove_css_class("connected")
            self._juhflow_dot.add_css_class("disconnected")
            self._juhflow_label.set_text(_("Not connected"))
            self._juhflow_label.remove_css_class("success")
            self._juhflow_label.add_css_class("dim-label")
            self._juhflow_connect_btn.set_visible(True)
        return True  # Keep polling

    def _on_juhflow_connect(self, button):
        """Start Flow server and JuhFlow bridge to find companion apps."""
        button.set_sensitive(False)
        button.set_label(_("Connecting..."))

        # Enable flow if not already (block signal to avoid double server start)
        if not config.get("flow", "enabled", default=False):
            config.set("flow", "enabled", True, auto_save=True)
            self._programmatic_toggle = True
            self.flow_switch.set_active(True)
            self._programmatic_toggle = False

        # Start the flow server (which starts the bridge + indicator)
        if FLOW_MODULE_AVAILABLE:
            try:
                server = get_flow_server()
                if not server:
                    start_flow_server()
                    logger.info("Started via Connect button")
            except Exception as e:
                logger.error("Connect error: %s", e)

        # Re-enable button after a delay
        def _reset():
            self._connect_reset_timer = None
            button.set_sensitive(True)
            button.set_label(_("Connect"))
            return False
        self._connect_reset_timer = GLib.timeout_add(3000, _reset)

    def _get_monitor_connectors(self):
        """Get list of monitor connector info from GDK.

        Returns list of dicts with 'connector', 'width', 'height'.
        Connector names (e.g. DP-1, HDMI-1) are stable across reboots
        unlike index-based selection.
        """
        result = []
        try:
            display = Gdk.Display.get_default()
            if display:
                monitors = display.get_monitors()
                for i in range(monitors.get_n_items()):
                    mon = monitors.get_item(i)
                    connector = mon.get_connector() or f"Monitor-{i + 1}"
                    geom = mon.get_geometry()
                    result.append({
                        "connector": connector,
                        "width": geom.width,
                        "height": geom.height,
                    })
        except Exception:
            pass
        return result

