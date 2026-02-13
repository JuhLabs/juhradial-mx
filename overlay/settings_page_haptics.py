#!/usr/bin/env python3
"""
JuhRadial MX - Haptics Page

HapticsPage: Haptic feedback pattern configuration.

SPDX-License-Identifier: GPL-3.0
"""

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Gio

from i18n import _
from settings_config import config
from settings_widgets import SettingsCard, SettingRow


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

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        card = SettingsCard(_("Haptic Feedback"))

        # Enable/disable switch
        enable_row = SettingRow(
            _("Enable Haptic Feedback"), _("Feel vibrations when using the radial menu")
        )
        enable_switch = Gtk.Switch()
        enable_switch.set_active(config.get("haptics", "enabled", default=True))
        enable_switch.connect(
            "state-set",
            lambda s, state: config.set("haptics", "enabled", state) or False,
        )
        enable_row.set_control(enable_switch)
        card.append(enable_row)

        content.append(card)

        # Per-event haptic patterns
        events_card = SettingsCard(_("Haptic Patterns"))

        # Store dropdowns for "Apply to All" feature
        self.event_dropdowns = {}

        event_settings = [
            ("menu_appear", _("Menu Appear"), _("Pattern when radial menu opens")),
            (
                "slice_change",
                _("Slice Hover"),
                _("Pattern when hovering over different slices"),
            ),
            ("confirm", _("Selection"), _("Pattern when selecting an action")),
            ("invalid", _("Invalid Action"), _("Pattern for blocked/invalid actions")),
        ]

        for key, label, desc in event_settings:
            row = SettingRow(label, desc)
            current_pattern = config.get(
                "haptics", "per_event", key, default="subtle_collision"
            )
            dropdown = self._create_pattern_dropdown(
                current_pattern,
                lambda pattern, k=key: config.set("haptics", "per_event", k, pattern),
            )
            self.event_dropdowns[key] = dropdown
            row.set_control(dropdown)
            events_card.append(row)

        # Add "Apply to All" row
        apply_all_row = SettingRow(
            _("Apply to All"), _("Set all events to the same pattern")
        )
        apply_all_dropdown = self._create_pattern_dropdown(
            "subtle_collision", self._apply_pattern_to_all
        )
        apply_all_row.set_control(apply_all_dropdown)
        events_card.append(apply_all_row)

        content.append(events_card)

        # Test button card
        test_card = SettingsCard(_("Test Haptics"))
        test_row = SettingRow(_("Test Pattern"), _("Feel the selected pattern"))
        test_button = Gtk.Button(label=_("Test"))
        test_button.add_css_class("suggested-action")
        test_button.connect("clicked", self._on_test_clicked)
        test_row.set_control(test_button)
        test_card.append(test_row)

        content.append(test_card)

        self.set_child(content)

    def _create_pattern_dropdown(self, current_value, on_change_callback):
        """Create a dropdown for selecting haptic patterns"""
        dropdown = Gtk.ComboBoxText()

        current_index = 0
        for i, (pattern_id, display_name, _) in enumerate(self.HAPTIC_PATTERNS):
            dropdown.append(pattern_id, display_name)
            if pattern_id == current_value:
                current_index = i

        dropdown.set_active(current_index)
        dropdown.connect(
            "changed", lambda d: self._on_pattern_selected(d, on_change_callback)
        )

        return dropdown

    def _on_pattern_selected(self, dropdown, callback):
        """Handle pattern selection - save and apply instantly"""
        pattern = dropdown.get_active_id()
        if not pattern:
            return

        # Save to config (in-memory)
        callback(pattern)

        # Save config to file so daemon can read it
        config.save(show_toast=False)

        # Reload daemon config to apply instantly
        self._reload_daemon_config()

    def _apply_pattern_to_all(self, pattern):
        """Apply the selected pattern to all event types"""
        if not pattern:
            return

        # Update all per-event patterns in config
        event_keys = ["menu_appear", "slice_change", "confirm", "invalid"]
        for key in event_keys:
            config.set("haptics", "per_event", key, pattern)

        # Update all dropdowns in the UI to match
        # Find the index for this pattern
        pattern_index = 0
        for i, (pattern_id, _, _) in enumerate(self.HAPTIC_PATTERNS):
            if pattern_id == pattern:
                pattern_index = i
                break

        # Update each dropdown's visual selection
        for key, dropdown in self.event_dropdowns.items():
            dropdown.set_active(pattern_index)

        # Save config to file so daemon can read it
        config.save(show_toast=False)

        # Reload daemon config to apply all patterns instantly
        self._reload_daemon_config()

    def _reload_daemon_config(self):
        """Reload daemon config via D-Bus to apply haptic pattern changes instantly"""
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
            proxy.call_sync("ReloadConfig", None, Gio.DBusCallFlags.NONE, 2000, None)
            print("Daemon config reloaded - haptic patterns applied")
        except Exception as e:
            print(f"Failed to reload daemon config: {e}")

    def _on_test_clicked(self, button):
        """Send a test haptic pulse via D-Bus"""
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
            # Trigger haptic with "menu_appear" event to test the pattern
            proxy.call_sync(
                "TriggerHaptic",
                GLib.Variant("(s)", ("menu_appear",)),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            print("Test haptic triggered")
        except Exception as e:
            print(f"Failed to send test haptic: {e}")
