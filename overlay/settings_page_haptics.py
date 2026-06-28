#!/usr/bin/env python3
"""
JuhRadial MX - Haptics Page

HapticsPage: Haptic feedback configuration with a live actuator-trace
visualization. The waveform panel is a Cairo-drawn, animated damped pulse
that reflects the selected waveform preset; the per-event list and Test
pulse drive the real daemon (HID++ predefined waveforms) over D-Bus.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw

from i18n import _
from settings_config import config
from settings_widgets import SettingsCard, SettingRow
import settings_theme

logger = logging.getLogger(__name__)


def _hex_rgb(hex_color, default=(0.31, 0.94, 0.79)):
    """Parse '#rrggbb' to a (r, g, b) float tuple."""
    try:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
    except Exception:
        return default


class HapticsPage(Gtk.ScrolledWindow):
    """Haptic feedback settings page - MX Master 4 haptic patterns"""

    # MX Master 4 haptic waveform patterns (from Logitech HID++ spec)
    HAPTIC_PATTERNS = [
        ("sharp_state_change", _("Sharp Click"), _("Crisp, sharp feedback")),
        ("damp_state_change", _("Soft Click"), _("Softer, dampened feedback")),
        ("sharp_collision", _("Sharp Bump"), _("Strong collision feedback")),
        ("damp_collision", _("Soft Bump"), _("Gentle collision feedback")),
        ("subtle_collision", _("Subtle"), _("Very light, subtle feedback")),
        ("whisper_collision", _("Whisper"), _("Barely perceptible feedback")),
        ("happy_alert", _("Happy"), _("Positive notification feel")),
        ("angry_alert", _("Alert"), _("Warning/error feel")),
        ("completed", _("Complete"), _("Success/completion feel")),
        ("square", _("Square Wave"), _("Mechanical square pattern")),
        ("wave", _("Wave"), _("Smooth wave pattern")),
        ("firework", _("Firework"), _("Burst pattern")),
        ("mad", _("Strong Alert"), _("Strong error pattern")),
        ("knock", _("Knock"), _("Knocking pattern")),
        ("jingle", _("Jingle"), _("Musical jingle pattern")),
        ("ringing", _("Ringing"), _("Ring/vibrate pattern")),
    ]

    # Waveform presets shown under the trace. Each maps to a real HID++ pattern
    # for Test, and carries display-only descriptors of how the pulse feels.
    # key: (label, hid_pattern, intensity_pct, duration_ms, sharpness)
    PRESETS = [
        ("tick", _("Tick"), "sharp_state_change", 55, 6, _("Sharp")),
        ("bump", _("Bump"), "damp_collision", 72, 18, _("High")),
        ("pulse", _("Pulse"), "subtle_collision", 60, 24, _("Soft")),
        ("ramp", _("Ramp"), "wave", 68, 30, _("Medium")),
        ("double", _("Double"), "knock", 80, 36, _("Sharp")),
        ("off", _("Off"), None, 0, 0, _("None")),
    ]

    # Frames per fire cycle at ~40ms/frame: fast = snappy, slow = drawn out.
    PRESET_FIRE = {"tick": 16, "bump": 26, "pulse": 30, "ramp": 42, "double": 32}

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._phase = 0.0
        self._preset_key = "bump"
        self._preset_buttons = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(22)
        outer.set_margin_bottom(22)
        outer.set_margin_start(22)
        outer.set_margin_end(22)

        outer.append(self._build_header())

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        body.set_homogeneous(True)
        body.append(self._build_waveform_card())
        body.append(self._build_events_card())
        outer.append(body)
        self._body = body

        # Master switch gates the body so "off" reads as designed.
        self._set_dependents_sensitive(config.get("haptics", "enabled", default=True))

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1180)
        clamp.set_tightening_threshold(900)
        clamp.set_child(outer)
        self.set_child(clamp)

        # Animate the trace ONLY while it is mapped (visible) AND haptics is
        # enabled, so a hidden tab / minimized window / OFF state idles (no CPU).
        self._anim_id = None
        self._anim_active = config.get("haptics", "enabled", default=True)
        self._trace.connect("map", self._start_anim)
        self._trace.connect("unmap", self._stop_anim)
        self.connect("destroy", self._on_destroy)

    # ----------------------------------------------------------------- header
    def _build_header(self):
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)

        eyebrow = Gtk.Label(label=_("CONFIGURE  ·  HAPTICS"))
        eyebrow.set_halign(Gtk.Align.START)
        eyebrow.add_css_class("section-eyebrow")
        text_box.append(eyebrow)

        title = Gtk.Label(label=_("Haptic Feedback"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("page-display-title")
        text_box.append(title)

        subtitle = Gtk.Label(
            label=_("Every detent, gesture and snap is a tuned pulse on the actuator.")
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("setting-desc")
        text_box.append(subtitle)
        head.append(text_box)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        controls.set_valign(Gtk.Align.CENTER)

        enable_switch = Gtk.Switch()
        enable_switch.set_valign(Gtk.Align.CENTER)
        enable_switch.set_active(config.get("haptics", "enabled", default=True))
        enable_switch.connect("state-set", self._on_haptics_toggled)
        controls.append(enable_switch)

        test_button = Gtk.Button(label=_("Test pulse"))
        test_button.add_css_class("suggested-action")
        test_button.connect("clicked", self._on_test_clicked)
        controls.append(test_button)
        head.append(controls)

        return head

    # ------------------------------------------------------------- left card
    def _build_waveform_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("settings-card")
        card.set_hexpand(True)

        # Card head: title + LIVE badge
        chead = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctitle = Gtk.Label(label=_("WAVEFORM  ·  ACTUATOR TRACE"))
        ctitle.set_halign(Gtk.Align.START)
        ctitle.set_hexpand(True)
        ctitle.add_css_class("section-eyebrow")
        chead.append(ctitle)
        live = Gtk.Label(label=_("LIVE"))
        live.add_css_class("live-badge")
        chead.append(live)
        card.append(chead)

        # The animated trace
        self._trace = Gtk.DrawingArea()
        self._trace.set_content_height(132)
        self._trace.set_hexpand(True)
        self._trace.add_css_class("waveform-trace")
        self._trace.set_draw_func(self._draw_waveform)
        card.append(self._trace)

        # Readouts: PATTERN / INTENSITY / DURATION / SHARPNESS
        readouts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        readouts.set_homogeneous(True)
        self._ro_pattern = self._make_readout(readouts, _("PATTERN"))
        self._ro_intensity = self._make_readout(readouts, _("INTENSITY"))
        self._ro_duration = self._make_readout(readouts, _("DURATION"))
        self._ro_sharpness = self._make_readout(readouts, _("SHARPNESS"))
        card.append(readouts)

        # Preset label + chips
        plabel = Gtk.Label(label=_("WAVEFORM PRESET"))
        plabel.set_halign(Gtk.Align.START)
        plabel.add_css_class("section-eyebrow")
        plabel.set_margin_top(4)
        card.append(plabel)

        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for key, label, _hid, _i, _d, _s in self.PRESETS:
            btn = Gtk.Button(label=label)
            btn.add_css_class("preset-btn")
            btn.connect("clicked", self._on_preset_clicked, key)
            self._preset_buttons[key] = btn
            chips.append(btn)
        card.append(chips)

        self._select_preset(self._preset_key)
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

    # ------------------------------------------------------------ right card
    def _build_events_card(self):
        card = SettingsCard(_("Per-Event Patterns"))
        card.set_hexpand(True)

        self.event_dropdowns = {}
        event_settings = [
            ("menu_appear", _("Menu Appear"), _("Pattern when the radial menu opens")),
            ("slice_change", _("Slice Hover"), _("Pattern when hovering ring sectors")),
            ("confirm", _("Selection"), _("Pattern when selecting an action")),
            ("invalid", _("Invalid Action"), _("Pattern for blocked actions")),
        ]
        for key, label, desc in event_settings:
            row = SettingRow(label, desc)
            current = config.get("haptics", "per_event", key, default="subtle_collision")
            dropdown = self._create_pattern_dropdown(
                current, lambda pattern, k=key: config.set("haptics", "per_event", k, pattern)
            )
            self.event_dropdowns[key] = dropdown
            row.set_control(dropdown)
            card.append(row)

        apply_all_row = SettingRow(_("Apply to All"), _("Set every event to one pattern"))
        apply_all_dropdown = self._create_pattern_dropdown(
            "subtle_collision", self._apply_pattern_to_all
        )
        apply_all_row.set_control(apply_all_dropdown)
        card.append(apply_all_row)

        self._events_card = card
        return card

    # ----------------------------------------------------------- animation
    def _start_anim(self, *_a):
        if self._anim_id is None and self._anim_active:
            self._anim_id = GLib.timeout_add(40, self._on_tick)

    def _stop_anim(self, *_a):
        if self._anim_id is not None:
            GLib.source_remove(self._anim_id)
            self._anim_id = None

    def _on_tick(self):
        self._phase += 1
        self._trace.queue_draw()
        return True

    def _on_destroy(self, *_a):
        self._stop_anim()

    def _draw_waveform(self, area, cr, width, height):
        w, h = float(width), float(height)
        mid = h * 0.5
        accent = _hex_rgb(settings_theme.COLORS.get("accent", "#4FEFC9"))
        ar, ag, ab = accent

        # Grid
        cr.set_line_width(1.0)
        cr.set_source_rgba(1, 1, 1, 0.05)
        for i in range(1, 5):
            x = w * i / 5.0
            cr.move_to(x, 8)
            cr.line_to(x, h - 8)
        for j in range(1, 3):
            y = h * j / 3.0
            cr.move_to(8, y)
            cr.line_to(w - 8, y)
        cr.stroke()

        # Baseline
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.move_to(8, mid)
        cr.line_to(w - 8, mid)
        cr.stroke()

        if self._preset_key == "off":
            return

        # Re-fire envelope: the pulse "plays" at the pattern's own speed, then
        # fades and re-fires, so the trace shows the actual waveform firing
        # repeatedly (fast for Tick, slow for Ramp) rather than a static shimmer.
        period = self.PRESET_FIRE.get(self._preset_key, 28)
        cyc = (self._phase % period) / period
        env = math.exp(-3.2 * cyc)
        amp = h * 0.40 * (0.14 + 0.86 * env)

        n = 160
        pts = []
        for i in range(n + 1):
            t = i / n
            x = 10 + t * (w - 20)
            y = mid - self._sample(t, self._preset_key) * amp
            pts.append((x, y))

        # Glow pass (brighter while firing)
        cr.set_line_width(6.0)
        cr.set_source_rgba(ar, ag, ab, 0.12 + 0.14 * env)
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()

        # Crisp pass
        cr.set_line_width(2.0)
        cr.set_source_rgba(ar, ag, ab, 0.95)
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()

        # Playhead sweeps left->right across one fire cycle
        idx = int(cyc * n)
        dx, dy = pts[idx]
        cr.set_source_rgba(ar, ag, ab, 0.9)
        cr.arc(dx, dy, 3.0, 0, math.pi * 2)
        cr.fill()
        cr.set_source_rgba(ar, ag, ab, 0.22)
        cr.arc(dx, dy, 6.5, 0, math.pi * 2)
        cr.fill()

    @staticmethod
    def _sample(t, key):
        """Static damped actuator pulse shape in [-1, 1] for the preset.

        The carrier frequency + decay differ per pattern so the curve reads as
        that pattern; the firing animation comes from the amplitude envelope in
        _draw_waveform, not from shifting this shape.
        """
        if key == "off":
            return 0.0
        if key == "tick":
            return math.exp(-22 * t) * math.sin(2 * math.pi * 3 * t)
        if key == "bump":
            return math.exp(-5.0 * t) * math.sin(2 * math.pi * 5 * t)
        if key == "pulse":
            env = math.exp(-((t - 0.16) ** 2) / 0.004)
            return env * math.sin(2 * math.pi * 1.3 * t)
        if key == "ramp":
            return (1 - math.exp(-7 * t)) * math.exp(-2.4 * t) * math.sin(2 * math.pi * 4 * t)
        if key == "double":
            b1 = math.exp(-12 * t) * math.sin(2 * math.pi * 6 * t)
            b2 = 0.0
            if t > 0.36:
                b2 = math.exp(-12 * (t - 0.36)) * math.sin(2 * math.pi * 6 * (t - 0.36))
            return 0.85 * (b1 + b2)
        return math.exp(-5 * t) * math.sin(2 * math.pi * 5 * t)

    # -------------------------------------------------------------- presets
    def _on_preset_clicked(self, _button, key):
        self._select_preset(key)
        # Choosing a waveform preset also applies its underlying HID pattern to
        # every per-event slot, so the per-event list on the right matches the
        # preset the user picked (off leaves the per-event choices untouched).
        info = next((p for p in self.PRESETS if p[0] == key), None)
        if info is not None and key != "off":
            self._apply_pattern_to_all(info[2])

    def _select_preset(self, key):
        self._preset_key = key
        info = next((p for p in self.PRESETS if p[0] == key), None)
        if info is None:
            return
        _k, label, _hid, intensity, duration, sharpness = info
        self._ro_pattern.set_label(label.upper())
        self._ro_intensity.set_label(f"{intensity}%")
        self._ro_duration.set_label(f"{duration} ms")
        self._ro_sharpness.set_label(sharpness)
        for k, btn in self._preset_buttons.items():
            if k == key:
                btn.add_css_class("selected")
            else:
                btn.remove_css_class("selected")
        if self._trace is not None:
            self._trace.queue_draw()
        # 'off' has no waveform to animate -> idle the timer; others resume.
        if hasattr(self, "_anim_id"):
            if key == "off":
                self._stop_anim()
            elif self._anim_active and self._trace.get_mapped():
                self._start_anim()

    def _set_dependents_sensitive(self, enabled):
        self._body.set_sensitive(enabled)
        # Idle the animation when haptics is OFF (no wasted CPU on the trace).
        self._anim_active = enabled
        if hasattr(self, "_anim_id"):
            self._start_anim() if enabled else self._stop_anim()

    def _on_haptics_toggled(self, switch, state):
        config.set("haptics", "enabled", state)
        config.save(show_toast=False)
        self._set_dependents_sensitive(state)
        self._reload_daemon_config()
        return False

    # ----------------------------------------------------- pattern dropdowns
    def _create_pattern_dropdown(self, current_value, on_change_callback):
        labels = [display_name for _id, display_name, _desc in self.HAPTIC_PATTERNS]
        dropdown = Gtk.DropDown.new_from_strings(labels)
        current_index = 0
        for i, (pattern_id, _name, _desc) in enumerate(self.HAPTIC_PATTERNS):
            if pattern_id == current_value:
                current_index = i
                break
        dropdown.set_selected(current_index)
        dropdown.connect(
            "notify::selected",
            lambda d, _p: self._on_pattern_selected(d, on_change_callback),
        )
        return dropdown

    def _on_pattern_selected(self, dropdown, callback):
        if getattr(self, "_bulk_apply", False):
            return  # bulk "Apply to All" saves + reloads once at the end
        idx = dropdown.get_selected()
        if idx >= len(self.HAPTIC_PATTERNS):
            return
        pattern = self.HAPTIC_PATTERNS[idx][0]
        callback(pattern)
        config.save(show_toast=False)
        self._reload_daemon_config()

    def _apply_pattern_to_all(self, pattern):
        if not pattern:
            return
        for key in ["menu_appear", "slice_change", "confirm", "invalid"]:
            config.set("haptics", "per_event", key, pattern)
        pattern_index = 0
        for i, (pattern_id, _pname, _pdesc) in enumerate(self.HAPTIC_PATTERNS):
            if pattern_id == pattern:
                pattern_index = i
                break
        # Suppress per-dropdown save/reload while syncing the UI; one save+reload below.
        self._bulk_apply = True
        for key, dropdown in self.event_dropdowns.items():
            dropdown.set_selected(pattern_index)
        self._bulk_apply = False
        config.save(show_toast=False)
        self._reload_daemon_config()

    # ---------------------------------------------------------------- daemon
    def _get_daemon_proxy(self):
        if not hasattr(self, "_daemon_proxy") or self._daemon_proxy is None:
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self._daemon_proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    "org.kde.juhradialmx",
                    "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon",
                    None,
                )
            except Exception:
                self._daemon_proxy = None
        return self._daemon_proxy

    def _reload_daemon_config(self):
        proxy = self._get_daemon_proxy()
        if not proxy:
            logger.warning("Cannot reload daemon config: D-Bus proxy unavailable")
            return
        try:
            proxy.call_sync("ReloadConfig", None, Gio.DBusCallFlags.NONE, 2000, None)
            logger.info("Daemon config reloaded - haptic patterns applied")
        except Exception as e:
            logger.error("Failed to reload daemon config: %s", e)
            self._daemon_proxy = None

    def _on_test_clicked(self, button):
        if not config.get("haptics", "enabled", default=True):
            return  # master switch OFF -> Test does nothing (matches daemon gate)
        proxy = self._get_daemon_proxy()
        if not proxy:
            logger.warning("Cannot test haptic: D-Bus proxy unavailable")
            return
        info = next((p for p in self.PRESETS if p[0] == self._preset_key), None)
        hid = info[2] if info else None
        if not hid:
            return  # "off" preset has no waveform
        # Play the exact selected preset waveform via the dedicated daemon method
        # (TriggerHaptic only accepts UX event names; TriggerHapticPattern plays
        # a named MX4 waveform).
        try:
            proxy.call_sync(
                "TriggerHapticPattern",
                GLib.Variant("(s)", (hid,)),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            logger.info("Test haptic pattern: %s", hid)
        except Exception as e:
            logger.error("Failed to send test haptic: %s", e)
            self._daemon_proxy = None
