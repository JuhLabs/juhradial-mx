#!/usr/bin/env python3
"""
JuhRadial MX - Flow Page

FlowPage UI layout and toggle handlers for multi-computer control.
Network discovery and pairing logic lives in settings_flow_discovery.py.

SPDX-License-Identifier: GPL-3.0
"""

import importlib.util
import logging
import os
import socket
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Adw

from i18n import _
from settings_config import config, disable_scroll_on_scale
from settings_widgets import SettingRow
from settings_flow_discovery import FlowDiscoveryMixin

# Flow module availability check only. The Flow server/indicator (PyQt6) are
# started in the overlay process, NEVER here in the GTK settings process.
FLOW_MODULE_AVAILABLE = importlib.util.find_spec("flow") is not None

logger = logging.getLogger(__name__)

# DropDown index for each peer direction (matches direction_dropdown order).
_DIRECTION_INDEX = {"right": 0, "left": 1, "top": 2, "bottom": 3}
# Segmented control only exposes the three useful edges.
_SEGMENT_INDEX = {"right": 0, "left": 1, "top": 2}


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
        self._active_edge = config.get("flow", "direction", default="right")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_start(22)
        outer.set_margin_end(22)
        outer.set_margin_top(22)
        outer.set_margin_bottom(22)

        outer.append(self._build_header())
        outer.append(self._build_topology_card())

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        body.set_homogeneous(True)
        body.append(self._build_link_status_card())
        body.append(self._build_sharing_card())
        outer.append(body)

        # Gate edge-dependent controls on whether cross-screen cursor is on.
        self._set_flow_dependents_sensitive(
            config.get("flow", "enabled", default=False)
        )

        # Poll JuhFlow status every 3 seconds (drives companion + link status).
        self._update_juhflow_status()
        self._juhflow_poll = GLib.timeout_add(3000, self._update_juhflow_status)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1180)
        clamp.set_tightening_threshold(900)
        clamp.set_child(outer)
        self.set_child(clamp)

        # Try to discover computers on startup
        GLib.idle_add(self._discover_computers)

    # ----------------------------------------------------------------- header
    def _build_header(self):
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)

        eyebrow = Gtk.Label(label=_("CONFIGURE  ·  FLOW"))
        eyebrow.set_halign(Gtk.Align.START)
        eyebrow.add_css_class("section-eyebrow")
        text_box.append(eyebrow)

        title = Gtk.Label(label=_("JuhFlow"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("page-display-title")
        text_box.append(title)

        subtitle = Gtk.Label(
            label=_(
                "One mouse across every machine: glide to a screen edge and the "
                "cursor crosses over, encrypted end to end."
            )
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_wrap(True)
        subtitle.set_xalign(0)
        subtitle.add_css_class("setting-desc")
        text_box.append(subtitle)
        return text_box

    # --------------------------------------------------------------- topology
    def _build_topology_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("settings-card")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctitle = Gtk.Label(label=_("LINKED COMPUTERS  ·  TOPOLOGY"))
        ctitle.set_halign(Gtk.Align.START)
        ctitle.set_hexpand(True)
        ctitle.add_css_class("section-eyebrow")
        head.append(ctitle)
        enc = Gtk.Label(label=_("ENCRYPTED"))
        enc.add_css_class("live-badge")
        head.append(enc)
        card.append(head)

        topo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        topo.append(self._build_this_computer())
        topo.append(self._build_link_viz())
        topo.append(self._build_peers_area())
        card.append(topo)
        return card

    def _build_this_computer(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("info-card")
        box.set_valign(Gtk.Align.CENTER)
        box.set_size_request(232, -1)

        ident = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        icon.set_pixel_size(32)
        icon.add_css_class("accent-color")
        ident.append(icon)

        ident_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        ident_text.set_hexpand(True)
        host = Gtk.Label(label=self._hostname())
        host.set_halign(Gtk.Align.START)
        host.add_css_class("heading")
        ident_text.append(host)
        sub = Gtk.Label(label="{}  ·  {}".format(self._distro(), self._local_ip()))
        sub.set_halign(Gtk.Align.START)
        sub.add_css_class("caption")
        ident_text.append(sub)
        ident.append(ident_text)
        box.append(ident)

        this_badge = Gtk.Label(label=_("THIS COMPUTER"))
        this_badge.set_halign(Gtk.Align.START)
        this_badge.add_css_class("badge")
        box.append(this_badge)

        self._edge_label = Gtk.Label()
        self._edge_label.set_halign(Gtk.Align.START)
        self._edge_label.add_css_class("section-eyebrow")
        self._update_edge_label(config.get("flow", "direction", default="right"))
        box.append(self._edge_label)
        return box

    def _build_link_viz(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        arrow_in = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow_in.add_css_class("dim-label")
        box.append(arrow_in)

        lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        lock.set_pixel_size(28)
        lock.add_css_class("accent-color")
        box.append(lock)

        arrow_out = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow_out.add_css_class("dim-label")
        box.append(arrow_out)
        return box

    def _build_peers_area(self):
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        area.set_hexpand(True)

        peers_title = Gtk.Label(label=_("DISCOVERED PEERS"))
        peers_title.set_halign(Gtk.Align.START)
        peers_title.add_css_class("section-eyebrow")
        area.append(peers_title)

        # JuhFlow companion status row (status dot/label + Connect button).
        self._juhflow_control_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        self._juhflow_status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6
        )
        # Inline spinner shown until the first poll completes
        self._juhflow_initial_spinner = Gtk.Spinner()
        self._juhflow_initial_spinner.set_size_request(16, 16)
        self._juhflow_initial_spinner.start()
        self._juhflow_status_box.append(self._juhflow_initial_spinner)
        self._juhflow_dot = Gtk.Box()
        self._juhflow_dot.set_size_request(10, 10)
        self._juhflow_dot.set_halign(Gtk.Align.CENTER)
        self._juhflow_dot.set_valign(Gtk.Align.CENTER)
        self._juhflow_dot.add_css_class("connection-dot")
        self._juhflow_dot.set_visible(False)
        self._juhflow_status_box.append(self._juhflow_dot)
        self._juhflow_label = Gtk.Label(label="")
        self._juhflow_label.add_css_class("caption")
        self._juhflow_label.set_visible(False)
        self._juhflow_status_box.append(self._juhflow_label)
        self._juhflow_status_box.set_hexpand(True)
        self._juhflow_status_box.set_halign(Gtk.Align.START)
        self._juhflow_first_poll_done = False
        self._juhflow_control_box.append(self._juhflow_status_box)

        self._juhflow_connect_btn = Gtk.Button(label=_("Connect"))
        self._juhflow_connect_btn.add_css_class("suggested-action")
        self._juhflow_connect_btn.add_css_class("caption")
        self._juhflow_connect_btn.set_visible(False)
        self._juhflow_connect_btn.connect("clicked", self._on_juhflow_connect)
        self._juhflow_control_box.append(self._juhflow_connect_btn)
        area.append(self._juhflow_control_box)

        # Discovered-computers list (peers render here via the discovery mixin).
        self.computers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.no_computers_label = Gtk.Label(label=_("No other computers detected"))
        self.no_computers_label.add_css_class("dim-label")
        self.no_computers_label.add_css_class("caption")
        self.no_computers_label.set_halign(Gtk.Align.START)
        self.no_computers_label.set_margin_top(4)
        self.no_computers_label.set_margin_bottom(4)
        self.computers_box.append(self.no_computers_label)
        area.append(self.computers_box)

        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        scan_box.set_halign(Gtk.Align.END)
        self.scan_button = Gtk.Button(label=_("Scan Network"))
        self.scan_button.add_css_class("secondary-btn")
        self.scan_button.connect("clicked", self._on_scan_clicked)
        scan_box.append(self.scan_button)
        area.append(scan_box)
        return area

    # ------------------------------------------------------------ link status
    def _build_link_status_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("settings-card")
        card.set_hexpand(True)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=_("LINK STATUS"))
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        title.add_css_class("section-eyebrow")
        head.append(title)
        self._ls_secure_badge = Gtk.Label(label=_("SECURE"))
        self._ls_secure_badge.add_css_class("badge")
        head.append(self._ls_secure_badge)
        card.append(head)

        # Link status row: connection dot + state text.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("setting-row")
        lbl = Gtk.Label(label=_("Link status"))
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        lbl.add_css_class("setting-label")
        row.append(lbl)
        state_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        state_box.set_valign(Gtk.Align.CENTER)
        self._ls_dot = Gtk.Box()
        self._ls_dot.set_size_request(9, 9)
        self._ls_dot.set_valign(Gtk.Align.CENTER)
        self._ls_dot.add_css_class("connection-dot")
        self._ls_dot.add_css_class("disconnected")
        state_box.append(self._ls_dot)
        self._ls_status = Gtk.Label(label=_("Disconnected"))
        self._ls_status.add_css_class("setting-value")
        state_box.append(self._ls_status)
        row.append(state_box)
        card.append(row)

        self._ls_encryption = self._status_row(card, _("Encryption"))
        self._ls_latency = self._status_row(card, _("Latency"))
        self._ls_throughput = self._status_row(card, _("Throughput"))
        self._ls_paired = self._status_row(card, _("Paired since"))
        return card

    def _status_row(self, parent, label_text):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("setting-row")
        lbl = Gtk.Label(label=label_text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        lbl.add_css_class("setting-label")
        row.append(lbl)
        val = Gtk.Label(label="—")
        val.set_halign(Gtk.Align.END)
        val.add_css_class("setting-value")
        row.append(val)
        parent.append(row)
        return val

    # -------------------------------------------------------- sharing controls
    def _build_sharing_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("settings-card")
        card.set_hexpand(True)

        title = Gtk.Label(label=_("SHARING CONTROLS"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("section-eyebrow")
        title.set_margin_bottom(6)
        card.append(title)

        # Share clipboard
        clip_row = SettingRow(
            _("Share clipboard"), _("Copy on one machine, paste on the other")
        )
        self._share_clipboard_switch = Gtk.Switch()
        self._share_clipboard_switch.set_valign(Gtk.Align.CENTER)
        self._share_clipboard_switch.set_active(
            config.get("flow", "share_clipboard", default=True)
        )
        self._share_clipboard_switch.connect(
            "state-set", self._on_share_clipboard_toggled
        )
        clip_row.set_control(self._share_clipboard_switch)
        card.append(clip_row)

        # (File-transfer-on-cross intentionally omitted: no transport exists
        # yet, so a toggle here would be a silent no-op.)

        # Cross-screen cursor = the Flow master enable (flow.enabled)
        cursor_row = SettingRow(
            _("Cross-screen cursor"),
            _("Move the pointer between linked computers"),
        )
        self.flow_switch = Gtk.Switch()
        self.flow_switch.set_valign(Gtk.Align.CENTER)
        self.flow_switch.set_active(config.get("flow", "enabled", default=False))
        self.flow_switch.connect("state-set", self._on_flow_toggled)
        cursor_row.set_control(self.flow_switch)
        card.append(cursor_row)

        # Edge to cross = flow.direction, shown as a segmented LEFT/RIGHT/TOP.
        # direction_dropdown stays the authoritative model whose handler persists
        # the value; the segmented control drives it.
        self.direction_dropdown = Gtk.DropDown.new_from_strings(
            [_("Right"), _("Left"), _("Top"), _("Bottom")]
        )
        current_dir = config.get("flow", "direction", default="right")
        self.direction_dropdown.set_selected(_DIRECTION_INDEX.get(current_dir, 0))
        self.direction_dropdown.set_sensitive(
            config.get("flow", "enabled", default=False)
        )
        self.direction_dropdown.connect("notify::selected", self._on_direction_changed)

        edge_row = SettingRow(
            _("Edge to cross"), _("Which screen edge crosses to the peer")
        )
        self._edge_segmented = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._edge_segmented.add_css_class("linked")
        self._edge_segments = {}
        for edge_key, label in (("left", _("Left")), ("right", _("Right")), ("top", _("Top"))):
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(edge_key == current_dir)
            btn.connect("toggled", self._on_edge_segment_toggled, edge_key)
            self._edge_segments[edge_key] = btn
            self._edge_segmented.append(btn)
        edge_row.set_control(self._edge_segmented)
        card.append(edge_row)

        # Edge sensitivity = flow.edge_sensitivity (0-100).
        sens_row = SettingRow(
            _("Edge sensitivity"), _("How eagerly the edge triggers a crossing")
        )
        self._sensitivity_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 5
        )
        self._sensitivity_scale.set_value(
            config.get("flow", "edge_sensitivity", default=50)
        )
        self._sensitivity_scale.set_draw_value(False)
        self._sensitivity_scale.set_size_request(170, -1)
        self._sensitivity_scale.set_valign(Gtk.Align.CENTER)
        disable_scroll_on_scale(self._sensitivity_scale)
        self._sensitivity_scale.connect("value-changed", self._on_sensitivity_changed)
        sens_row.set_control(self._sensitivity_scale)
        card.append(sens_row)

        # ---- Indicator & display (kept controls) ----
        disp_title = Gtk.Label(label=_("INDICATOR & DISPLAY"))
        disp_title.set_halign(Gtk.Align.START)
        disp_title.add_css_class("section-header")
        card.append(disp_title)

        # Edge trigger toggle (flow.edge_trigger)
        edge_trig_row = SettingRow(
            _("Switch at screen edge"),
            _("Move the cursor to the edge to switch computers"),
        )
        self.edge_switch = Gtk.Switch()
        self.edge_switch.set_valign(Gtk.Align.CENTER)
        self.edge_switch.set_active(config.get("flow", "edge_trigger", default=True))
        self.edge_switch.set_sensitive(config.get("flow", "enabled", default=False))
        self.edge_switch.connect("state-set", self._on_edge_toggled)
        edge_trig_row.set_control(self.edge_switch)
        card.append(edge_trig_row)

        # Monitor selection (flow.monitor)
        mon_row = SettingRow(
            _("Monitor"), _("Screen to show the indicator and detect edges on")
        )
        self._monitor_connectors = self._get_monitor_connectors()
        monitor_labels = [_("Auto")] + [
            f"{c['connector']} ({c['width']}x{c['height']})"
            for c in self._monitor_connectors
        ]
        self.monitor_dropdown = Gtk.DropDown.new_from_strings(monitor_labels)
        current_monitor = config.get("flow", "monitor", default="")
        dropdown_idx = 0
        if current_monitor:
            for i, c in enumerate(self._monitor_connectors):
                if c["connector"] == current_monitor:
                    dropdown_idx = i + 1
                    break
        if dropdown_idx < len(monitor_labels):
            self.monitor_dropdown.set_selected(dropdown_idx)
        self.monitor_dropdown.set_sensitive(
            config.get("flow", "enabled", default=False)
        )
        self.monitor_dropdown.connect("notify::selected", self._on_monitor_changed)
        mon_row.set_control(self.monitor_dropdown)
        card.append(mon_row)

        # Hide indicator (flow.hide_indicator)
        hide_row = SettingRow(
            _("Hide indicator"), _("Use Flow without the visual edge indicator")
        )
        self.hide_indicator_switch = Gtk.Switch()
        self.hide_indicator_switch.set_valign(Gtk.Align.CENTER)
        self.hide_indicator_switch.set_active(
            config.get("flow", "hide_indicator", default=False)
        )
        self.hide_indicator_switch.set_sensitive(
            config.get("flow", "enabled", default=False)
        )
        self.hide_indicator_switch.connect("state-set", self._on_hide_indicator_toggled)
        hide_row.set_control(self.hide_indicator_switch)
        card.append(hide_row)

        # Extend edge zone (flow.extend_edge_zone)
        extend_row = SettingRow(
            _("Extend edge trigger area"),
            _("Trigger across the full screen edge, not just the indicator zone"),
        )
        self.extend_zone_switch = Gtk.Switch()
        self.extend_zone_switch.set_valign(Gtk.Align.CENTER)
        self.extend_zone_switch.set_active(
            config.get("flow", "extend_edge_zone", default=False)
        )
        self.extend_zone_switch.set_sensitive(
            config.get("flow", "enabled", default=False)
        )
        self.extend_zone_switch.connect("state-set", self._on_extend_zone_toggled)
        extend_row.set_control(self.extend_zone_switch)
        card.append(extend_row)
        return card

    # ------------------------------------------------------------ this-computer
    def _hostname(self):
        try:
            return socket.gethostname()
        except OSError:
            return "this-computer"

    def _distro(self):
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            logger.debug("could not read /etc/os-release", exc_info=True)
        return "Linux"

    def _local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    def _update_edge_label(self, direction):
        self._edge_label.set_text(
            _("→ {} EDGE → PEER").format(direction.upper())
        )

    # ----------------------------------------------------------------- handlers
    def _set_flow_dependents_sensitive(self, state):
        """Enable/disable the edge-dependent controls in one place."""
        for w in (
            self.edge_switch,
            self.direction_dropdown,
            self.monitor_dropdown,
            self.hide_indicator_switch,
            self.extend_zone_switch,
            self._edge_segmented,
            self._sensitivity_scale,
        ):
            w.set_sensitive(state)

    def _on_flow_toggled(self, switch, state):
        """Handle the cross-screen cursor (Flow master) toggle."""
        if self._programmatic_toggle:
            return True
        config.set("flow", "enabled", state, auto_save=True)
        self._set_flow_dependents_sensitive(state)
        # The Flow server + edge indicator are PyQt6 (QWidget) and MUST run in
        # the overlay process (which owns the QApplication). Constructing a
        # QWidget here in the GTK settings process aborts the whole app, so we
        # only persist config and let the overlay (re)start to apply it.
        self._apply_flow_via_overlay()
        return False

    def _apply_flow_via_overlay(self):
        """Restart the overlay (debounced) so it applies the saved Flow config
        in its own PyQt6 process. The Flow server/indicator are NEVER started
        from the GTK settings process (no QApplication -> Qt abort)."""
        if getattr(self, "_flow_restart_id", None):
            GLib.source_remove(self._flow_restart_id)
        self._flow_restart_id = GLib.timeout_add(500, self._restart_overlay_for_flow)

    def _restart_overlay_for_flow(self):
        self._flow_restart_id = None
        import subprocess
        from pathlib import Path
        try:
            subprocess.run(
                ["pkill", "-f", "[j]uhradial-overlay.py"], capture_output=True, timeout=2
            )
            overlay_path = Path(__file__).parent / "juhradial-overlay.py"
            subprocess.Popen(
                ["python3", str(overlay_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Overlay restarted to apply Flow config")
        except Exception as e:
            logger.error("Could not restart overlay for Flow: %s", e)
        return False

    def _on_direction_changed(self, dropdown, _pspec):
        """Persist the peer direction and re-apply Flow via the overlay.

        Only saves config + applies via the overlay process (never imports the
        PyQt6 Flow module here, which would abort the GTK app)."""
        idx = dropdown.get_selected()
        direction_values = ["right", "left", "top", "bottom"]
        direction = direction_values[idx] if idx < len(direction_values) else "right"
        config.set("flow", "direction", direction, auto_save=True)
        self._update_edge_label(direction)
        self._sync_segment_from_direction(direction)
        logger.info("Direction set to: %s", direction)
        self._apply_flow_via_overlay()

    def _sync_segment_from_direction(self, direction):
        """Reflect the active direction in the segmented control (no recursion)."""
        self._active_edge = direction
        for key, btn in self._edge_segments.items():
            btn.handler_block_by_func(self._on_edge_segment_toggled)
            btn.set_active(key == direction)
            btn.handler_unblock_by_func(self._on_edge_segment_toggled)

    def _on_edge_segment_toggled(self, btn, edge_key):
        """Drive direction_dropdown (the authoritative model) from the segments."""
        if not btn.get_active():
            # Disallow deselecting the active edge: restore from saved direction.
            self._sync_segment_from_direction(
                config.get("flow", "direction", default="right")
            )
            return
        self.direction_dropdown.set_selected(_SEGMENT_INDEX[edge_key])

    def _on_share_clipboard_toggled(self, switch, state):
        """Handle the share-clipboard toggle (flow.share_clipboard)."""
        config.set("flow", "share_clipboard", state, auto_save=True)
        self._apply_flow_via_overlay()
        return False

    def _on_sensitivity_changed(self, scale):
        """Handle the edge-sensitivity slider (flow.edge_sensitivity)."""
        config.set(
            "flow", "edge_sensitivity", int(round(scale.get_value())), auto_save=True
        )
        self._apply_flow_via_overlay()

    def _on_edge_toggled(self, switch, state):
        """Handle edge trigger toggle"""
        config.set("flow", "edge_trigger", state, auto_save=True)
        # Edge detector is PyQt6 and lives in the overlay process; apply there.
        self._apply_flow_via_overlay()
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
            logger.debug("Flow status file not available")
        # Fallback: try in-process bridge (works if settings started flow)
        if not peers and FLOW_MODULE_AVAILABLE:
            try:
                from flow import get_juhflow_bridge
                bridge = get_juhflow_bridge()
                if bridge:
                    peers = bridge.get_peers()
            except Exception:
                logger.debug("JuhFlow bridge not available in separate process")

        # First poll: hide spinner and reveal real status widgets
        if not self._juhflow_first_poll_done:
            self._juhflow_first_poll_done = True
            self._juhflow_initial_spinner.stop()
            self._juhflow_initial_spinner.set_visible(False)
            self._juhflow_dot.set_visible(True)
            self._juhflow_label.set_visible(True)

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

        self._update_link_status(peers)
        return True  # Keep polling

    def _update_link_status(self, peers):
        """Refresh the LINK STATUS card from the current peer list."""
        if peers:
            peer = peers[0]
            self._ls_dot.remove_css_class("disconnected")
            self._ls_dot.add_css_class("connected")
            name = peer.get("hostname", "")
            self._ls_status.set_text(
                _("Connected - {}").format(name) if name else _("Connected")
            )
            self._ls_status.remove_css_class("dim-label")
            self._ls_status.add_css_class("success")
            self._ls_encryption.set_text("TLS 1.3  ·  ChaCha20-Poly1305")
            connected_at = peer.get("connected_at", 0) or 0
            self._ls_paired.set_text(
                self._format_since(connected_at) if connected_at else "—"
            )
            # Latency/throughput have no measurement source yet; show real values
            # once the bridge reports them, otherwise the em-dash placeholder.
            self._ls_latency.set_text(self._format_metric(peer.get("latency_ms"), "ms"))
            self._ls_throughput.set_text(
                self._format_metric(peer.get("throughput_mbps"), "Mb/s")
            )
            self._ls_secure_badge.add_css_class("success")
        else:
            self._ls_dot.remove_css_class("connected")
            self._ls_dot.add_css_class("disconnected")
            self._ls_status.set_text(_("Disconnected"))
            self._ls_status.remove_css_class("success")
            self._ls_status.add_css_class("dim-label")
            for lbl in (
                self._ls_encryption,
                self._ls_latency,
                self._ls_throughput,
                self._ls_paired,
            ):
                lbl.set_text("—")
            self._ls_secure_badge.remove_css_class("success")

    @staticmethod
    def _format_metric(value, unit):
        if value is None:
            return "—"
        return "{} {}".format(value, unit)

    @staticmethod
    def _format_since(ts):
        delta = max(0, int(time.time() - ts))
        if delta < 60:
            return "{}s".format(delta)
        if delta < 3600:
            return "{}m".format(delta // 60)
        if delta < 86400:
            return "{}h".format(delta // 3600)
        return "{}d".format(delta // 86400)

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

        # Apply via the overlay process (Flow server/bridge/indicator are PyQt6
        # and crash if constructed here in the GTK settings process).
        self._apply_flow_via_overlay()

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
            logger.debug("GDK display unavailable for monitor enumeration")
        return result
