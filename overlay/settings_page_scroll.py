#!/usr/bin/env python3
"""
JuhRadial MX - Scroll/Sensitivity Page

Pointer speed, scroll wheel mode, and thumb wheel settings.
Matches Logi Options+ card-based layout.

SPDX-License-Identifier: GPL-3.0
"""

import json
import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw

from i18n import _
from settings_config import config, disable_scroll_on_scale, get_device_mode
from settings_theme import COLORS
from settings_widgets import SettingsCard, SettingRow, PageHeader

logger = logging.getLogger(__name__)


class DPIVisualSlider(Gtk.Box):
    """Visual DPI slider with value display"""

    def __init__(self, on_change=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.on_change = on_change

        # Header with title and DPI value
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=_("Pointer Speed"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("heading")
        subtitle = Gtk.Label(label=_("Adjust tracking sensitivity"))
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        title_box.append(title)
        title_box.append(subtitle)
        header.append(title_box)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        # DPI value display - clickable to type exact value
        self._dpi_stack = Gtk.Stack()
        self._dpi_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._dpi_stack.set_transition_duration(150)

        # Page 1: styled label (default view).
        # The numeric value is overwritten by ScrollPage right after construction
        # via set_dpi(); the placeholder here is just a sane default so the
        # label has correct sizing/markup before the real value arrives.
        self.dpi_label = Gtk.Label()
        self.dpi_label.add_css_class("title-1")
        self._render_dpi_label(1600)
        self.dpi_label.set_cursor_from_name("pointer")
        self.dpi_label.set_tooltip_text(_("Click to type a value"))
        label_click = Gtk.GestureClick()
        label_click.connect("released", self._on_dpi_label_clicked)
        self.dpi_label.add_controller(label_click)
        self._dpi_stack.add_named(self.dpi_label, "label")

        # Page 2: spin button for manual entry
        self._dpi_spin = Gtk.SpinButton.new_with_range(400, 8000, 100)
        self._dpi_spin.set_width_chars(5)
        self._dpi_spin.set_valign(Gtk.Align.CENTER)
        self._dpi_spin.connect("activate", self._on_dpi_spin_activate)
        self._dpi_spin.connect("value-changed", self._on_dpi_spin_changed)
        spin_focus = Gtk.EventControllerFocus()
        spin_focus.connect("leave", self._on_dpi_spin_focus_out)
        self._dpi_spin.add_controller(spin_focus)
        self._dpi_stack.add_named(self._dpi_spin, "spin")

        self._dpi_stack.set_visible_child_name("label")

        dpi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        dpi_box.append(self._dpi_stack)
        dpi_unit = Gtk.Label(label=_("DPI"))
        dpi_unit.add_css_class("dim-label")
        dpi_box.append(dpi_unit)
        header.append(dpi_box)

        self.append(header)

        # Slider
        slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        slow_label = Gtk.Label(label=_("Slow"))
        slow_label.add_css_class("dim-label")
        slider_box.append(slow_label)

        self.scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 400, 8000, 100
        )
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(300, -1)
        self.scale.connect("value-changed", self._on_value_changed)
        disable_scroll_on_scale(self.scale)
        slider_box.append(self.scale)

        fast_label = Gtk.Label(label=_("Fast"))
        fast_label.add_css_class("dim-label")
        slider_box.append(fast_label)

        self.append(slider_box)

        # Preset buttons
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preset_box.set_halign(Gtk.Align.CENTER)
        preset_box.set_margin_top(8)

        for dpi in [800, 1600, 3200, 4000]:
            btn = Gtk.Button(label=str(dpi))
            btn.add_css_class("flat")
            btn.connect("clicked", lambda b, d=dpi: self.set_dpi(d))
            preset_box.append(btn)

        self.append(preset_box)

    def set_dpi(self, dpi):
        # Always sync the label too. If `dpi` equals the scale's current value,
        # `set_value` won't fire `value-changed`, so `_on_value_changed` would
        # never run and the markup would stay at its placeholder. Render
        # explicitly here to guarantee the visible label matches the config.
        self._render_dpi_label(int(dpi))
        self.scale.set_value(dpi)

    def get_dpi(self):
        return int(self.scale.get_value())

    def _render_dpi_label(self, dpi):
        # Use the current theme's accent color, not a hardcoded mauve. Falls
        # back to text color if accent isn't set. The Workbench register uses
        # the accent only for state — this is the one place where a value is
        # the state (the live DPI), so accent is appropriate.
        accent = COLORS.get("accent", COLORS.get("text", "#000"))
        self.dpi_label.set_markup(
            f'<span size="xx-large" weight="bold" color="{accent}">{int(dpi)}</span>'
        )

    def _on_value_changed(self, scale):
        dpi = int(scale.get_value())
        self._render_dpi_label(dpi)
        if self.on_change:
            self.on_change(dpi)

    def _on_dpi_label_clicked(self, gesture, n_press, x, y):
        """Switch to spin button for manual DPI entry."""
        self._dpi_spin.set_value(self.scale.get_value())
        self._dpi_stack.set_visible_child_name("spin")
        self._dpi_spin.grab_focus()
        self._dpi_spin.select_region(0, -1)

    def _on_dpi_spin_activate(self, spin):
        """Enter pressed - apply and switch back to label."""
        self._apply_spin_value()

    def _on_dpi_spin_focus_out(self, controller):
        """Focus lost - apply and switch back to label."""
        self._apply_spin_value()

    def _on_dpi_spin_changed(self, spin):
        """Live update slider as user changes spin value."""
        dpi = int(spin.get_value())
        # Round to nearest 100
        dpi = round(dpi / 100) * 100
        dpi = max(400, min(8000, dpi))
        self.scale.set_value(dpi)

    def _apply_spin_value(self):
        """Apply spin button value and switch back to label display."""
        dpi = int(self._dpi_spin.get_value())
        dpi = round(dpi / 100) * 100
        dpi = max(400, min(8000, dpi))
        self.scale.set_value(dpi)
        self._dpi_stack.set_visible_child_name("label")


class WheelModeSelector(Gtk.Box):
    """3-mode segmented control: Ratchet / SmartShift / Free-spin.

    Matches the Logi Options+ mode selector.
    """

    MODES = [
        ("ratchet", "Ratchet"),
        ("smartshift", "SmartShift"),
        ("freespin", "Free-spin"),
    ]

    def __init__(self, on_change=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.on_change = on_change
        self._buttons = {}
        self._active_mode = "smartshift"

        self.add_css_class("linked")

        for mode_id, label in self.MODES:
            btn = Gtk.ToggleButton(label=_(label))
            btn.set_hexpand(True)
            btn.connect("toggled", self._on_toggled, mode_id)
            self._buttons[mode_id] = btn
            self.append(btn)

    def set_mode(self, mode):
        """Set active mode without triggering callback."""
        if mode not in self._buttons:
            mode = "smartshift"
        self._active_mode = mode
        for mid, btn in self._buttons.items():
            btn.handler_block_by_func(self._on_toggled)
            btn.set_active(mid == mode)
            btn.handler_unblock_by_func(self._on_toggled)

    def get_mode(self):
        return self._active_mode

    def _on_toggled(self, btn, mode_id):
        if not btn.get_active():
            # Prevent deselecting the active button
            if mode_id == self._active_mode:
                btn.set_active(True)
            return
        # Deselect other buttons
        self._active_mode = mode_id
        for mid, other in self._buttons.items():
            if mid != mode_id:
                other.handler_block_by_func(self._on_toggled)
                other.set_active(False)
                other.handler_unblock_by_func(self._on_toggled)
        if self.on_change:
            self.on_change(mode_id)


class ScrollPage(Gtk.ScrolledWindow):
    """Sensitivity settings - pointer, scroll wheel, and thumb wheel.

    Layout matches Logi Options+ card-based design.
    In generic mouse mode, Logitech-only widgets (WheelModeSelector,
    SmartShift sensitivity, thumb wheel) are hidden.
    """

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
            "input-touchpad-symbolic",
            _("Point & Scroll"),
            _("Pointer speed, scroll wheel, and thumb wheel"),
        )
        content.append(header)

        # ---- POINTER SPEED ----
        pointer_card = SettingsCard(_("Pointer Speed"))

        self.dpi_slider = DPIVisualSlider(on_change=self._on_dpi_changed)
        # Prefer the raw DPI key. Fall back to the legacy "speed" slot
        # (1..20 -> 400..8000 DPI) so existing configs from before the
        # pointer.dpi key existed keep working without resetting to the
        # default. Once the user touches the slider, both keys get rewritten
        # and pointer.dpi becomes the source of truth on subsequent loads.
        saved_dpi = config.get("pointer", "dpi", default=None)
        if saved_dpi is None:
            saved_speed = config.get("pointer", "speed", default=10)
            saved_dpi = 400 + (saved_speed - 1) * 400
        initial_dpi = max(400, min(8000, int(saved_dpi)))
        self.dpi_slider.set_dpi(initial_dpi)
        pointer_card.append(self.dpi_slider)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(16)
        sep.set_margin_bottom(16)
        pointer_card.append(sep)

        accel_row = SettingRow(
            _("Acceleration Profile"), _("How pointer speed scales with movement")
        )
        accel_combo = Gtk.ComboBoxText()
        accel_combo.append("adaptive", _("Adaptive (Recommended)"))
        accel_combo.append("flat", _("Flat (Linear)"))
        accel_combo.append("default", _("System Default"))
        current_accel = config.get("pointer", "accel_profile", default="adaptive")
        accel_combo.set_active_id(current_accel)
        accel_combo.connect("changed", self._on_accel_changed)
        accel_row.set_control(accel_combo)
        pointer_card.append(accel_row)

        content.append(pointer_card)

        # ---- SCROLL WHEEL ----
        scroll_card = SettingsCard(_("Scroll Wheel"))

        # Wheel mode selector and SmartShift - Logitech only (HID++)
        # Wrap in a container so we can hide them together in generic mode
        self._logitech_wheel_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0
        )

        # Mode selector (Ratchet / SmartShift / Free-spin)
        mode_label = Gtk.Label(label=_("Wheel Mode"))
        mode_label.set_halign(Gtk.Align.START)
        mode_label.add_css_class("heading")
        mode_label.set_margin_bottom(8)
        self._logitech_wheel_box.append(mode_label)

        self.mode_selector = WheelModeSelector(on_change=self._on_mode_changed)
        self.mode_selector.set_margin_bottom(16)
        self._logitech_wheel_box.append(self.mode_selector)

        # SmartShift sensitivity (only visible in smartshift mode)
        self.sensitivity_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8
        )
        self.sensitivity_box.set_margin_bottom(8)

        sens_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        sens_label = Gtk.Label(label=_("Sensitivity"))
        sens_label.set_halign(Gtk.Align.START)
        sens_label_box.append(sens_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        sens_label_box.append(spacer)

        # Clickable sensitivity value - Stack with label and spin button
        self._sens_stack = Gtk.Stack()
        self._sens_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._sens_stack.set_transition_duration(150)

        self.sens_value_label = Gtk.Label()
        self.sens_value_label.add_css_class("dim-label")
        self.sens_value_label.set_cursor_from_name("pointer")
        self.sens_value_label.set_tooltip_text(_("Click to type a value"))
        sens_label_click = Gtk.GestureClick()
        sens_label_click.connect("released", self._on_sens_label_clicked)
        self.sens_value_label.add_controller(sens_label_click)
        self._sens_stack.add_named(self.sens_value_label, "label")

        self._sens_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self._sens_spin.set_width_chars(4)
        self._sens_spin.set_valign(Gtk.Align.CENTER)
        self._sens_spin.connect("activate", self._on_sens_spin_activate)
        self._sens_spin.connect("value-changed", self._on_sens_spin_changed)
        sens_spin_focus = Gtk.EventControllerFocus()
        sens_spin_focus.connect("leave", self._on_sens_spin_focus_out)
        self._sens_spin.add_controller(sens_spin_focus)
        self._sens_stack.add_named(self._sens_spin, "spin")

        self._sens_stack.set_visible_child_name("label")
        sens_label_box.append(self._sens_stack)
        self.sensitivity_box.append(sens_label_box)

        sens_slider_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        easy_label = Gtk.Label(label=_("Easy"))
        easy_label.add_css_class("dim-label")
        sens_slider_box.append(easy_label)

        self.sens_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1, 100, 1
        )
        self.sens_scale.set_hexpand(True)
        self.sens_scale.set_draw_value(False)
        self.sens_scale.set_value(
            config.get("scroll", "smartshift_threshold", default=50)
        )
        self.sens_scale.connect("value-changed", self._on_sensitivity_changed)
        self._update_sens_label(self.sens_scale.get_value())
        disable_scroll_on_scale(self.sens_scale)
        sens_slider_box.append(self.sens_scale)

        hard_label = Gtk.Label(label=_("Hard"))
        hard_label.add_css_class("dim-label")
        sens_slider_box.append(hard_label)

        self.sensitivity_box.append(sens_slider_box)
        self._logitech_wheel_box.append(self.sensitivity_box)

        self._logitech_wheel_sep = Gtk.Separator(
            orientation=Gtk.Orientation.HORIZONTAL
        )
        self._logitech_wheel_sep.set_margin_top(8)
        self._logitech_wheel_sep.set_margin_bottom(16)
        self._logitech_wheel_box.append(self._logitech_wheel_sep)

        scroll_card.append(self._logitech_wheel_box)

        # Hide WheelModeSelector + SmartShift in generic mode
        if self._is_generic:
            self._logitech_wheel_box.set_visible(False)

        # Scroll speed
        scroll_speed_row = SettingRow(
            _("Speed"), _("Lines scrolled per wheel notch")
        )
        scroll_speed_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1, 10, 1
        )
        scroll_speed_scale.set_value(config.get("scroll", "speed", default=3))
        scroll_speed_scale.set_size_request(200, -1)
        scroll_speed_scale.set_draw_value(False)
        scroll_speed_scale.connect("value-changed", self._on_scroll_speed_changed)
        disable_scroll_on_scale(scroll_speed_scale)
        scroll_speed_row.set_control(scroll_speed_scale)
        scroll_card.append(scroll_speed_row)

        # Direction
        direction_row = SettingRow(
            _("Natural Scrolling"),
            _("Content follows finger direction"),
        )
        self.natural_switch = Gtk.Switch()
        self.natural_switch.set_active(
            config.get("scroll", "natural", default=False)
        )
        self.natural_switch.connect("state-set", self._on_natural_changed)
        direction_row.set_control(self.natural_switch)
        scroll_card.append(direction_row)

        # Smooth scrolling
        smooth_row = SettingRow(
            _("Smooth Scrolling"),
            _("High-resolution scroll for smoother movement"),
        )
        self.smooth_switch = Gtk.Switch()
        self.smooth_switch.set_active(
            config.get("scroll", "smooth", default=True)
        )
        self.smooth_switch.connect("state-set", self._on_smooth_changed)
        smooth_row.set_control(self.smooth_switch)
        scroll_card.append(smooth_row)

        content.append(scroll_card)

        # ---- THUMB WHEEL ---- (Logitech only - MX Master has thumb wheel)
        self._thumb_card = SettingsCard(_("Thumb Wheel"))

        thumb_speed_row = SettingRow(
            _("Speed"), _("Horizontal scroll sensitivity")
        )
        thumb_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1, 10, 1
        )
        thumb_scale.set_value(config.get("thumbwheel", "speed", default=5))
        thumb_scale.set_size_request(200, -1)
        thumb_scale.set_draw_value(False)
        thumb_scale.connect(
            "value-changed",
            lambda s: config.set("thumbwheel", "speed", int(s.get_value())),
        )
        disable_scroll_on_scale(thumb_scale)
        thumb_speed_row.set_control(thumb_scale)
        self._thumb_card.append(thumb_speed_row)

        thumb_invert_row = SettingRow(
            _("Invert Direction"), _("Reverse thumb wheel scroll direction")
        )
        thumb_invert = Gtk.Switch()
        thumb_invert.set_active(
            config.get("thumbwheel", "invert", default=False)
        )
        thumb_invert.connect(
            "state-set",
            lambda s, state: config.set("thumbwheel", "invert", state) or False,
        )
        thumb_invert_row.set_control(thumb_invert)
        self._thumb_card.append(thumb_invert_row)

        content.append(self._thumb_card)

        # Hide thumb wheel card in generic mode
        if self._is_generic:
            self._thumb_card.set_visible(False)

        # Wrap in Adw.Clamp for responsive centering
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(content)
        self.set_child(clamp)

        # Load device state and set mode selector
        self._load_device_settings()

    # ------------------------------------------------------------------
    # Mode selector
    # ------------------------------------------------------------------
    def _on_mode_changed(self, mode):
        """Handle wheel mode change from segmented control."""
        config.set("scroll", "mode", mode)
        # Show/hide sensitivity slider
        self.sensitivity_box.set_visible(mode == "smartshift")

        # Apply to device
        if mode == "ratchet":
            self._apply_smartshift_to_device(False, 0)
        elif mode == "freespin":
            # Free-spin: wheel_mode=1 (freespin), auto_disengage=0 (no auto-switch)
            self._apply_smartshift_to_device_raw(1, 0)
        else:
            # SmartShift
            threshold = int(self.sens_scale.get_value())
            device_threshold = int((100 - threshold) * 2.55)
            self._apply_smartshift_to_device(True, device_threshold)

    def _on_sensitivity_changed(self, scale):
        value = int(scale.get_value())
        config.set("scroll", "smartshift_threshold", value)
        self._update_sens_label(value)

        # Apply to device
        device_threshold = int((100 - value) * 2.55)
        self._apply_smartshift_to_device(True, device_threshold)

    def _update_sens_label(self, value):
        self.sens_value_label.set_text(f"{int(value)}%")

    def _on_sens_label_clicked(self, gesture, n_press, x, y):
        """Switch to spin button for manual sensitivity entry."""
        self._sens_spin.set_value(self.sens_scale.get_value())
        self._sens_stack.set_visible_child_name("spin")
        self._sens_spin.grab_focus()
        self._sens_spin.select_region(0, -1)

    def _on_sens_spin_activate(self, spin):
        """Enter pressed - apply and switch back to label."""
        self._apply_sens_spin_value()

    def _on_sens_spin_focus_out(self, controller):
        """Focus lost - apply and switch back to label."""
        self._apply_sens_spin_value()

    def _on_sens_spin_changed(self, spin):
        """Live update slider as user changes spin value."""
        value = int(spin.get_value())
        value = max(1, min(100, value))
        self.sens_scale.set_value(value)

    def _apply_sens_spin_value(self):
        """Apply spin value and switch back to label display."""
        value = int(self._sens_spin.get_value())
        value = max(1, min(100, value))
        self.sens_scale.set_value(value)
        self._sens_stack.set_visible_child_name("label")

    # ------------------------------------------------------------------
    # Pointer speed
    # ------------------------------------------------------------------
    def _on_dpi_changed(self, dpi):
        # pointer.dpi is the source of truth (raw 400..8000 DPI).
        # pointer.speed is kept in sync as a 1..20 slot for backwards
        # compatibility with any reader that still expects the old format.
        speed = max(1, min(20, (dpi - 400) // 400 + 1))
        config.set("pointer", "speed", speed)
        config.set("pointer", "dpi", dpi, auto_save=True)
        # In generic mode, skip HID++ DPI - only use gsettings/libinput
        if not self._is_generic:
            self._apply_dpi_to_device(dpi)
        self._apply_pointer_speed(dpi)

    def _on_accel_changed(self, combo):
        profile = combo.get_active_id()
        config.set("pointer", "accel_profile", profile)
        try:
            import subprocess
            subprocess.run(
                [
                    "gsettings", "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "accel-profile", profile,
                ],
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

    # ------------------------------------------------------------------
    # Scroll settings
    # ------------------------------------------------------------------
    def _on_natural_changed(self, switch, state):
        config.set("scroll", "natural", state)
        try:
            import subprocess
            subprocess.run(
                [
                    "gsettings", "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "natural-scroll", "true" if state else "false",
                ],
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        if not self._is_generic:
            self._apply_hiresscroll_to_device()
        return False

    def _on_smooth_changed(self, switch, state):
        config.set("scroll", "smooth", state)
        if not self._is_generic:
            self._apply_hiresscroll_to_device()
        return False

    def _on_scroll_speed_changed(self, scale):
        value = int(scale.get_value())
        config.set("scroll", "speed", value)
        self._apply_scroll_speed(value)

    def _apply_scroll_speed(self, lines):
        """Apply scroll speed multiplier - works on GNOME, KDE, Hyprland, etc."""
        import subprocess
        import os

        scroll_factor = 0.5 + (lines - 1) * 0.167
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()

        if "gnome" in desktop or "mutter" in desktop:
            try:
                subprocess.run(
                    [
                        "gsettings", "set", "org.gnome.mutter",
                        "experimental-features",
                        "['scale-monitor-framebuffer']",
                    ],
                    capture_output=True, timeout=2,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass

        if "kde" in desktop or "plasma" in desktop:
            try:
                subprocess.run(
                    [
                        "kwriteconfig5", "--file", "kcminputrc",
                        "--group", "Mouse", "--key", "ScrollFactor",
                        str(scroll_factor),
                    ],
                    capture_output=True, timeout=2,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass

        hypr_sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if hypr_sig:
            try:
                subprocess.run(
                    ["hyprctl", "keyword", "input:scroll_factor",
                     str(scroll_factor)],
                    capture_output=True, timeout=2,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass

        if "sway" in desktop.lower():
            try:
                result = subprocess.run(
                    ["swaymsg", "-t", "get_inputs"],
                    capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0:
                    inputs = json.loads(result.stdout)
                    for inp in inputs:
                        if "pointer" in inp.get("type", ""):
                            name = inp.get("identifier", "")
                            subprocess.run(
                                ["swaymsg", "input", name,
                                 "scroll_factor", str(scroll_factor)],
                                capture_output=True, timeout=2,
                            )
            except (FileNotFoundError, subprocess.SubprocessError,
                    json.JSONDecodeError):
                pass

        if session == "x11":
            try:
                import os as _os
                imwheel_config = _os.path.expanduser("~/.imwheelrc")
                config_content = f"""".*"
None,      Up,   Button4, {lines}
None,      Down, Button5, {lines}
"""
                with open(imwheel_config, "w", encoding="utf-8") as f:
                    f.write(config_content)
                uid = str(_os.getuid())
                subprocess.run(
                    ["pkill", "-u", uid, "imwheel"],
                    capture_output=True, timeout=2,
                )
                subprocess.run(
                    ["imwheel", "-b", "45"],
                    capture_output=True, timeout=2,
                )
            except (FileNotFoundError, subprocess.SubprocessError, OSError):
                pass

    # ------------------------------------------------------------------
    # D-Bus device methods
    # ------------------------------------------------------------------
    def _get_dbus_proxy(self):
        """Get a cached D-Bus proxy to the daemon."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            return Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
        except Exception:
            return None

    def _apply_dpi_to_device(self, dpi):
        proxy = self._get_dbus_proxy()
        if not proxy:
            return
        try:
            proxy.call_sync(
                "SetDpi",
                GLib.Variant("(q)", (dpi,)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
        except GLib.Error as e:
            logger.error("D-Bus error setting DPI: %s", e.message)

    def _apply_pointer_speed(self, dpi):
        try:
            import subprocess
            speed = (dpi - 4200) / 3800
            speed = max(-1.0, min(1.0, speed))
            subprocess.run(
                [
                    "gsettings", "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "speed", str(speed),
                ],
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

    def _apply_smartshift_to_device(self, enabled, threshold):
        """Apply SmartShift via the simplified D-Bus API."""
        proxy = self._get_dbus_proxy()
        if not proxy:
            return
        try:
            proxy.call_sync(
                "SetSmartShift",
                GLib.Variant("(by)", (enabled, threshold)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
        except GLib.Error as e:
            logger.error("D-Bus error setting SmartShift: %s", e.message)

    def _apply_smartshift_to_device_raw(self, wheel_mode, auto_disengage):
        """Set SmartShift with explicit wheel_mode for free-spin support.

        Free-spin = wheel_mode=1, auto_disengage=0 (no auto-switch).
        Falls back to the simplified API if direct call fails.
        """
        proxy = self._get_dbus_proxy()
        if not proxy:
            return
        # Use the simplified API: enabled=True with the given threshold.
        # wheel_mode=1 + auto_disengage=0 -> freespin on the daemon side.
        try:
            proxy.call_sync(
                "SetSmartShift",
                GLib.Variant("(by)", (bool(wheel_mode), auto_disengage)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
        except GLib.Error as e:
            logger.error("D-Bus error setting wheel mode: %s", e.message)

    def _apply_hiresscroll_to_device(self):
        hires = config.get("scroll", "smooth", default=True)
        invert = config.get("scroll", "natural", default=False)
        proxy = self._get_dbus_proxy()
        if not proxy:
            return
        try:
            proxy.call_sync(
                "SetHiresscrollMode",
                GLib.Variant("(bbb)", (hires, invert, False)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
        except GLib.Error as e:
            logger.error("D-Bus HiResScroll failed: %s", e.message)

    # ------------------------------------------------------------------
    # Load device state on startup
    # ------------------------------------------------------------------
    def _load_device_settings(self):
        """Load SmartShift and HiResScroll settings from device.

        In generic mode, skip all HID++ device queries - just use config values.
        """
        if self._is_generic:
            # No HID++ device to query; use saved config for basic scroll settings
            return

        proxy = self._get_dbus_proxy()
        if not proxy:
            # Fall back to config
            mode = config.get("scroll", "mode", default="smartshift")
            self.mode_selector.set_mode(mode)
            self.sensitivity_box.set_visible(mode == "smartshift")
            return

        # Load SmartShift
        try:
            supported = proxy.call_sync(
                "SmartShiftSupported", None,
                Gio.DBusCallFlags.NONE, 2000, None,
            )
            if supported and supported.get_child_value(0).get_boolean():
                result = proxy.call_sync(
                    "GetSmartShift", None,
                    Gio.DBusCallFlags.NONE, 2000, None,
                )
                if result:
                    enabled = result.get_child_value(0).get_boolean()
                    device_threshold = result.get_child_value(1).get_byte()

                    # Determine mode from device + saved config
                    saved_mode = config.get("scroll", "mode", default=None)
                    if saved_mode == "freespin":
                        mode = "freespin"
                    elif enabled:
                        mode = "smartshift"
                    else:
                        mode = "ratchet"

                    # Convert device threshold to UI percentage
                    ui_threshold = 100 - int(device_threshold / 2.55)
                    ui_threshold = max(1, min(100, ui_threshold))

                    self.mode_selector.set_mode(mode)
                    self.sens_scale.set_value(ui_threshold)
                    self.sensitivity_box.set_visible(mode == "smartshift")

                    config.set("scroll", "mode", mode)
                    config.set("scroll", "smartshift_threshold", ui_threshold)
            else:
                # SmartShift not supported
                self.mode_selector.set_sensitive(False)
                self.sensitivity_box.set_visible(False)
        except GLib.Error as e:
            logger.error("D-Bus error loading SmartShift: %s", e.message)
            mode = config.get("scroll", "mode", default="smartshift")
            self.mode_selector.set_mode(mode)
            self.sensitivity_box.set_visible(mode == "smartshift")

        # Load HiResScroll
        try:
            result = proxy.call_sync(
                "GetHiresscrollMode", None,
                Gio.DBusCallFlags.NONE, 2000, None,
            )
            if result:
                hires = result.get_child_value(0).get_boolean()
                self.smooth_switch.set_active(hires)
                config.set("scroll", "smooth", hires)
        except GLib.Error as e:
            logger.error("D-Bus error loading HiResScroll: %s", e.message)
