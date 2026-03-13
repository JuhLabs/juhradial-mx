#!/usr/bin/env python3
"""
JuhRadial MX - Macro Recorder

Modal recording dialog with countdown, live event capture via D-Bus,
pulsing indicator, and preview/discard workflow.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Gio, Adw

from i18n import _
from settings_theme import COLORS
from settings_macro_storage import new_action

logger = logging.getLogger(__name__)


class MacroRecorderDialog(Adw.Window):
    """Recording dialog that captures keyboard/mouse events.

    Workflow: Countdown (3-2-1) -> Recording -> Preview -> Add/Discard

    Communicates with daemon via D-Bus:
        StartMacroRecording() - start capture
        StopMacroRecording()  - stop capture
        MacroEventCaptured signal - receives events during recording

    Falls back to local key/mouse capture if daemon is unavailable.
    """

    def __init__(self, parent_window, on_recording_complete=None):
        super().__init__()
        self._parent = parent_window
        self._on_complete = on_recording_complete
        self._recorded_actions = []
        self._state = "idle"  # idle | countdown | recording | preview
        self._countdown_value = 3
        self._countdown_timer = None
        self._pulse_timer = None
        self._pulse_phase = 0.0
        self._record_delays = True
        self._record_mouse = True
        self._last_event_time = None
        self._dbus_proxy = None
        self._signal_sub_id = None

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("Record Macro"))
        self.set_default_size(500, 520)

        # Ensure timers are cleaned up if closed via WM button
        self.connect("close-request", self._on_close_request)

        # Main layout
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class("background")

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        close_btn = Gtk.Button(label=_("Cancel"))
        close_btn.add_css_class("flat")
        close_btn.connect("clicked", lambda _: self._cancel())
        header.pack_start(close_btn)
        content.append(header)

        # Central area
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        center.set_margin_start(24)
        center.set_margin_end(24)
        center.set_margin_top(16)
        center.set_margin_bottom(16)
        center.set_vexpand(True)

        # Status indicator area (countdown/recording/preview)
        self._status_area = Gtk.DrawingArea()
        self._status_area.set_size_request(-1, 100)
        self._status_area.set_draw_func(self._draw_status)
        self._status_area.set_halign(Gtk.Align.FILL)
        center.append(self._status_area)

        # Status label
        self._status_label = Gtk.Label(label=_("Ready to record"))
        self._status_label.add_css_class("title-2")
        self._status_label.set_halign(Gtk.Align.CENTER)
        center.append(self._status_label)

        # Options toggles
        opts_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        opts_box.set_halign(Gtk.Align.CENTER)
        opts_box.set_margin_top(8)

        # Record delays toggle
        delay_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        delay_label = Gtk.Label(label=_("Record delays"))
        delay_label.add_css_class("dim-label")
        delay_box.append(delay_label)
        self._delay_switch = Gtk.Switch()
        self._delay_switch.set_active(True)
        self._delay_switch.set_valign(Gtk.Align.CENTER)
        self._delay_switch.connect(
            "notify::active",
            lambda s, _: setattr(self, "_record_delays", s.get_active()),
        )
        delay_box.append(self._delay_switch)
        opts_box.append(delay_box)

        # Record mouse clicks toggle
        mouse_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mouse_label = Gtk.Label(label=_("Record mouse"))
        mouse_label.add_css_class("dim-label")
        mouse_box.append(mouse_label)
        self._mouse_switch = Gtk.Switch()
        self._mouse_switch.set_active(True)
        self._mouse_switch.set_valign(Gtk.Align.CENTER)
        self._mouse_switch.connect(
            "notify::active",
            lambda s, _: setattr(self, "_record_mouse", s.get_active()),
        )
        mouse_box.append(self._mouse_switch)
        opts_box.append(mouse_box)

        center.append(opts_box)

        # Live event list (scrolled)
        self._events_scrolled = Gtk.ScrolledWindow()
        self._events_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._events_scrolled.set_vexpand(True)
        self._events_scrolled.set_min_content_height(120)

        self._events_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._events_list.set_margin_start(8)
        self._events_list.set_margin_end(8)
        self._events_list.set_margin_top(4)
        self._events_scrolled.set_child(self._events_list)
        center.append(self._events_scrolled)

        # Event count
        self._event_count_label = Gtk.Label(label=_("0 events captured"))
        self._event_count_label.add_css_class("dim-label")
        self._event_count_label.set_halign(Gtk.Align.CENTER)
        center.append(self._event_count_label)

        content.append(center)

        # Bottom buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_bottom(20)

        # Record / Stop button
        self._record_btn = Gtk.Button()
        self._record_btn.add_css_class("destructive-action")
        self._record_btn.set_size_request(180, 44)
        self._update_record_button_label()
        self._record_btn.connect("clicked", self._on_record_toggle)
        btn_box.append(self._record_btn)

        # Add to Timeline (only in preview state)
        self._add_btn = Gtk.Button(label=_("Add to Timeline"))
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.set_size_request(160, 44)
        self._add_btn.set_sensitive(False)
        self._add_btn.connect("clicked", self._on_add_to_timeline)
        btn_box.append(self._add_btn)

        # Discard
        self._discard_btn = Gtk.Button(label=_("Discard"))
        self._discard_btn.add_css_class("flat")
        self._discard_btn.set_sensitive(False)
        self._discard_btn.connect("clicked", self._on_discard)
        btn_box.append(self._discard_btn)

        content.append(btn_box)
        self.set_content(content)

        # Local key capture (fallback when daemon not available)
        self._key_ctrl = Gtk.EventControllerKey()
        self._key_ctrl.connect("key-pressed", self._on_local_key_pressed)
        self._key_ctrl.connect("key-released", self._on_local_key_released)
        self.add_controller(self._key_ctrl)

    # ------------------------------------------------------------------
    # Record button state machine
    # ------------------------------------------------------------------

    def _update_record_button_label(self):
        if self._state == "idle":
            self._record_btn.set_label(_("Start Recording"))
        elif self._state == "countdown":
            self._record_btn.set_label(_("Cancel"))
        elif self._state == "recording":
            self._record_btn.set_label(_("Stop Recording"))
        elif self._state == "preview":
            self._record_btn.set_label(_("Record Again"))

    def _on_record_toggle(self, btn):
        if self._state == "idle" or self._state == "preview":
            self._start_countdown()
        elif self._state == "countdown":
            self._cancel_countdown()
        elif self._state == "recording":
            self._stop_recording()

    def _set_state(self, new_state):
        self._state = new_state
        self._update_record_button_label()

        is_preview = new_state == "preview"
        self._add_btn.set_sensitive(is_preview and len(self._recorded_actions) > 0)
        self._discard_btn.set_sensitive(is_preview and len(self._recorded_actions) > 0)

        # Toggle options are only editable before recording
        can_edit_opts = new_state in ("idle", "preview")
        self._delay_switch.set_sensitive(can_edit_opts)
        self._mouse_switch.set_sensitive(can_edit_opts)

        self._status_area.queue_draw()

    # ------------------------------------------------------------------
    # Countdown
    # ------------------------------------------------------------------

    def _start_countdown(self):
        self._recorded_actions.clear()
        self._clear_events_list()
        self._countdown_value = 3
        self._set_state("countdown")
        self._status_label.set_label(str(self._countdown_value))
        self._countdown_timer = GLib.timeout_add(1000, self._countdown_tick)

    def _countdown_tick(self):
        self._countdown_value -= 1
        if self._countdown_value <= 0:
            self._countdown_timer = None
            self._start_recording()
            return False  # Stop timer
        self._status_label.set_label(str(self._countdown_value))
        self._status_area.queue_draw()
        return True

    def _cancel_countdown(self):
        if self._countdown_timer:
            GLib.source_remove(self._countdown_timer)
            self._countdown_timer = None
        self._set_state("idle")
        self._status_label.set_label(_("Ready to record"))

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _start_recording(self):
        self._set_state("recording")
        self._status_label.set_label(_("Recording..."))
        self._last_event_time = GLib.get_monotonic_time()

        # Start pulse animation
        self._pulse_phase = 0.0
        self._pulse_timer = GLib.timeout_add(33, self._pulse_tick)  # ~30fps

        # Try D-Bus recording via daemon
        self._try_start_dbus_recording()

    def _stop_recording(self):
        # Stop pulse
        if self._pulse_timer:
            GLib.source_remove(self._pulse_timer)
            self._pulse_timer = None

        # Stop D-Bus recording
        self._try_stop_dbus_recording()

        self._set_state("preview")
        count = len(self._recorded_actions)
        self._status_label.set_label(
            _("{} actions recorded").format(count) if count else _("No actions recorded")
        )
        self._event_count_label.set_label(
            _("{} events captured").format(count)
        )

    def _pulse_tick(self):
        self._pulse_phase = (self._pulse_phase + 0.08) % (2 * math.pi)
        self._status_area.queue_draw()
        return self._state == "recording"

    # ------------------------------------------------------------------
    # D-Bus macro recording
    # ------------------------------------------------------------------

    def _try_start_dbus_recording(self):
        """Start macro recording via daemon D-Bus if available."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._dbus_proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
            self._dbus_proxy.call_sync(
                "StartMacroRecording", None, Gio.DBusCallFlags.NONE, 500, None
            )

            # Subscribe to MacroEventCaptured signal
            self._signal_sub_id = bus.signal_subscribe(
                "org.kde.juhradialmx",
                "org.kde.juhradialmx.Daemon",
                "MacroEventCaptured",
                "/org/kde/juhradialmx/Daemon",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_dbus_event,
                None,
            )
            logger.info("Started D-Bus macro recording")
        except GLib.Error as e:
            logger.info("D-Bus macro recording not available, using local capture: %s", e)
            self._dbus_proxy = None

    def _try_stop_dbus_recording(self):
        """Stop D-Bus macro recording."""
        if self._dbus_proxy:
            try:
                self._dbus_proxy.call_sync(
                    "StopMacroRecording", None, Gio.DBusCallFlags.NONE, 500, None
                )
            except GLib.Error as e:
                logger.debug("StopMacroRecording D-Bus call failed: %s", e)
        if self._signal_sub_id is not None:
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                bus.signal_unsubscribe(self._signal_sub_id)
            except GLib.Error as e:
                logger.debug("D-Bus signal unsubscribe failed: %s", e)
            self._signal_sub_id = None

    def _on_dbus_event(self, connection, sender, path, interface, signal, params, user_data):
        """Handle macro event from daemon D-Bus signal."""
        if self._state != "recording":
            return
        try:
            event_type, key_name, keycode = params.unpack()
            self._add_recorded_event(event_type, key_name, keycode)
        except Exception as e:
            logger.warning("Failed to parse D-Bus macro event: %s", e)

    # ------------------------------------------------------------------
    # Local key capture (fallback)
    # ------------------------------------------------------------------

    def _on_local_key_pressed(self, controller, keyval, keycode, state):
        if self._state != "recording":
            # Allow Escape to close during non-recording states
            if keyval == Gdk.KEY_Escape:
                self._cancel()
            return False

        # Escape stops recording
        if keyval == Gdk.KEY_Escape:
            self._stop_recording()
            return True

        key_name = Gdk.keyval_name(keyval) or f"key_{keycode}"
        self._add_recorded_event("key_down", key_name, keycode)
        return True

    def _on_local_key_released(self, controller, keyval, keycode, state):
        if self._state != "recording":
            return False

        key_name = Gdk.keyval_name(keyval) or f"key_{keycode}"
        self._add_recorded_event("key_up", key_name, keycode)
        return True

    def _add_recorded_event(self, event_type, key_name, keycode):
        """Add a recorded event to the list."""
        now = GLib.get_monotonic_time()

        # Insert delay if recording delays
        if self._record_delays and self._last_event_time is not None:
            delay_us = now - self._last_event_time
            delay_ms = int(delay_us / 1000)
            if delay_ms > 5:  # Ignore sub-5ms gaps
                self._recorded_actions.append(new_action("delay", ms=delay_ms))
        self._last_event_time = now

        # Create action
        if event_type in ("key_down", "key_up"):
            action = new_action(event_type, key=key_name, keycode=keycode)
        elif event_type in ("mouse_down", "mouse_up", "mouse_click"):
            action = new_action(event_type, button=key_name)
        else:
            action = new_action(event_type)

        self._recorded_actions.append(action)
        self._add_event_to_list(action)
        self._event_count_label.set_label(
            _("{} events captured").format(len(self._recorded_actions))
        )

    def _add_event_to_list(self, action):
        """Add a visual row to the live events list."""
        atype = action.get("type", "?")
        summary = atype
        if "key" in action:
            summary = f"{atype}: {action['key']}"
        elif "ms" in action:
            summary = f"delay: {action['ms']}ms"

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(4)
        row.set_margin_end(4)
        row.set_margin_top(1)
        row.set_margin_bottom(1)

        icon_name = {
            "key_down": "go-down-symbolic",
            "key_up": "go-up-symbolic",
            "delay": "preferences-system-time-symbolic",
            "mouse_down": "input-mouse-symbolic",
            "mouse_up": "input-mouse-symbolic",
        }.get(atype, "dialog-question-symbolic")

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(14)
        row.append(icon)

        label = Gtk.Label(label=summary)
        label.set_halign(Gtk.Align.START)
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        row.append(label)

        self._events_list.append(row)

        # Auto-scroll to bottom
        adj = self._events_scrolled.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

    def _clear_events_list(self):
        child = self._events_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._events_list.remove(child)
            child = next_child

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_status(self, area, cr, width, height):
        """Draw status indicator: countdown number, pulsing dot, or checkmark."""
        cx, cy = width / 2, height / 2

        accent = COLORS.get("accent", "#00d4ff")
        ar = int(accent[1:3], 16) / 255.0
        ag = int(accent[3:5], 16) / 255.0
        ab = int(accent[5:7], 16) / 255.0

        if self._state == "countdown":
            # Large countdown number
            cr.select_font_face("Sans", 0, 1)  # Bold
            cr.set_font_size(64)
            text = str(self._countdown_value)
            ext = cr.text_extents(text)
            cr.move_to(cx - ext.width / 2, cy + ext.height / 2)
            cr.set_source_rgba(ar, ag, ab, 0.9)
            cr.show_text(text)

        elif self._state == "recording":
            # Pulsing red dot
            pulse = (math.sin(self._pulse_phase) + 1.0) / 2.0  # 0..1
            red_r = int(COLORS.get("red", "#f38ba8")[1:3], 16) / 255.0
            red_g = int(COLORS.get("red", "#f38ba8")[3:5], 16) / 255.0
            red_b = int(COLORS.get("red", "#f38ba8")[5:7], 16) / 255.0

            # Outer glow
            glow_r = 20 + pulse * 10
            import cairo
            glow = cairo.RadialGradient(cx, cy, 0, cx, cy, glow_r)
            glow.add_color_stop_rgba(0, red_r, red_g, red_b, 0.3 + pulse * 0.3)
            glow.add_color_stop_rgba(1, red_r, red_g, red_b, 0)
            cr.set_source(glow)
            cr.arc(cx, cy, glow_r, 0, 2 * math.pi)
            cr.fill()

            # Inner dot
            dot_r = 10 + pulse * 3
            cr.set_source_rgba(red_r, red_g, red_b, 0.8 + pulse * 0.2)
            cr.arc(cx, cy, dot_r, 0, 2 * math.pi)
            cr.fill()

        elif self._state == "preview":
            # Checkmark icon
            cr.set_source_rgba(
                int(COLORS.get("green", "#a6e3a1")[1:3], 16) / 255.0,
                int(COLORS.get("green", "#a6e3a1")[3:5], 16) / 255.0,
                int(COLORS.get("green", "#a6e3a1")[5:7], 16) / 255.0,
                0.9,
            )
            cr.set_line_width(4)
            cr.set_line_cap(1)  # ROUND
            cr.move_to(cx - 16, cy)
            cr.line_to(cx - 4, cy + 14)
            cr.line_to(cx + 18, cy - 12)
            cr.stroke()

        else:
            # Idle - subtle circle
            cr.set_source_rgba(ar, ag, ab, 0.15)
            cr.arc(cx, cy, 24, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(ar, ag, ab, 0.4)
            cr.set_line_width(2)
            cr.arc(cx, cy, 24, 0, 2 * math.pi)
            cr.stroke()

    # ------------------------------------------------------------------
    # Final actions
    # ------------------------------------------------------------------

    def _on_add_to_timeline(self, btn):
        """Send recorded actions to the parent."""
        if self._on_complete and self._recorded_actions:
            self._on_complete(list(self._recorded_actions))
        self.close()

    def _on_discard(self, btn):
        """Discard recorded actions and reset."""
        self._recorded_actions.clear()
        self._clear_events_list()
        self._set_state("idle")
        self._status_label.set_label(_("Ready to record"))
        self._event_count_label.set_label(_("0 events captured"))

    def _on_close_request(self, *_args):
        """Handle WM close button - ensure timers are cleaned up."""
        self._cleanup_timers()
        return False  # Allow the close to proceed

    def _cleanup_timers(self):
        """Stop all GLib timers and D-Bus recording."""
        if self._state == "recording":
            self._stop_recording()
        if self._countdown_timer:
            GLib.source_remove(self._countdown_timer)
            self._countdown_timer = None
        if self._pulse_timer:
            GLib.source_remove(self._pulse_timer)
            self._pulse_timer = None
        self._try_stop_dbus_recording()

    def _cancel(self):
        """Cancel and close the dialog."""
        self._cleanup_timers()
        self.close()
