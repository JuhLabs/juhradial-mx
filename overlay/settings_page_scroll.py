#!/usr/bin/env python3
"""
JuhRadial MX - Scroll/Sensitivity Page

ScrollPage with DPIVisualSlider and ScrollWheelVisual widgets.

SPDX-License-Identifier: GPL-3.0
"""

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw

from i18n import _
from settings_config import config, disable_scroll_on_scale
from settings_theme import COLORS
from settings_widgets import SettingsCard, SettingRow


class DPIVisualSlider(Gtk.Box):
    """Visual DPI slider with gradient bar and value display"""

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

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        # DPI value display
        self.dpi_label = Gtk.Label()
        self.dpi_label.add_css_class("title-1")
        self.dpi_label.set_markup(
            f'<span size="xx-large" weight="bold" color="{COLORS["mauve"]}">1600</span>'
        )
        dpi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        dpi_box.append(self.dpi_label)
        dpi_unit = Gtk.Label(label=_("DPI"))
        dpi_unit.add_css_class("dim-label")
        dpi_box.append(dpi_unit)
        header.append(dpi_box)

        self.append(header)

        # Slider with gradient track
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
        # Disable scroll wheel to prevent accidental changes while scrolling page
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
        self.scale.set_value(dpi)

    def get_dpi(self):
        return int(self.scale.get_value())

    def _on_value_changed(self, scale):
        dpi = int(scale.get_value())
        self.dpi_label.set_markup(
            f'<span size="xx-large" weight="bold" color="{COLORS["mauve"]}">{dpi}</span>'
        )
        if self.on_change:
            self.on_change(dpi)


class ScrollWheelVisual(Gtk.DrawingArea):
    """Visual representation of scroll wheel mode"""

    def __init__(self, is_smartshift=True):
        super().__init__()
        self.is_smartshift = is_smartshift
        self.set_content_width(60)
        self.set_content_height(60)
        self.set_draw_func(self._draw)

    def set_smartshift(self, enabled):
        self.is_smartshift = enabled
        self.queue_draw()

    def _draw(self, area, cr, width, height):
        # Draw scroll wheel icon
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 4

        # Outer circle
        cr.set_source_rgba(*self._hex_to_rgba(COLORS["surface1"]))
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()

        # Inner wheel pattern
        color = COLORS["mauve"] if self.is_smartshift else COLORS["subtext0"]
        cr.set_source_rgba(*self._hex_to_rgba(color))

        # Draw ridges
        for i in range(8):
            angle = i * math.pi / 4
            x1 = cx + (radius - 8) * math.cos(angle)
            y1 = cy + (radius - 8) * math.sin(angle)
            x2 = cx + (radius - 2) * math.cos(angle)
            y2 = cy + (radius - 2) * math.sin(angle)
            cr.set_line_width(2)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        # Center dot
        cr.arc(cx, cy, 4, 0, 2 * math.pi)
        cr.fill()

    def _hex_to_rgba(self, hex_color):
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16) / 255
        g = int(hex_color[2:4], 16) / 255
        b = int(hex_color[4:6], 16) / 255
        return (r, g, b, 1.0)


class ScrollPage(Gtk.ScrolledWindow):
    """Sensitivity settings page - Mouse pointer, scroll wheel, and button sensitivity"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(32)
        content.set_margin_end(32)

        # ═══════════════════════════════════════════════════════════════
        # POINTER SPEED SECTION
        # ═══════════════════════════════════════════════════════════════
        pointer_card = SettingsCard(_("Pointer"))

        # DPI Visual Slider
        self.dpi_slider = DPIVisualSlider(on_change=self._on_dpi_changed)
        # Convert saved speed (1-20) to DPI (400-8000)
        saved_speed = config.get("pointer", "speed", default=10)
        initial_dpi = 400 + (saved_speed - 1) * 400
        self.dpi_slider.set_dpi(min(initial_dpi, 8000))
        pointer_card.append(self.dpi_slider)

        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep1.set_margin_top(16)
        sep1.set_margin_bottom(16)
        pointer_card.append(sep1)

        # Acceleration profile
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

        # ═══════════════════════════════════════════════════════════════
        # APPLY SECTION
        # ═══════════════════════════════════════════════════════════════
        apply_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        apply_card.add_css_class("card")
        apply_card.set_margin_top(8)

        # Status indicator
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.status_box.set_halign(Gtk.Align.CENTER)

        self.status_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.status_box.append(self.status_icon)

        self.status_label = Gtk.Label(label=_("Settings are up to date"))
        self.status_label.add_css_class("dim-label")
        self.status_box.append(self.status_label)

        apply_card.append(self.status_box)

        # Apply button
        apply_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        apply_btn_box.set_halign(Gtk.Align.CENTER)

        apply_btn = Gtk.Button()
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_size_request(220, 40)

        apply_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_content.set_halign(Gtk.Align.CENTER)
        apply_icon = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        apply_content.append(apply_icon)
        apply_label = Gtk.Label(label=_("Apply to Device"))
        apply_content.append(apply_label)
        apply_btn.set_child(apply_content)
        apply_btn.connect("clicked", self._on_apply_clicked)

        apply_btn_box.append(apply_btn)
        apply_card.append(apply_btn_box)

        # Note
        note = Gtk.Label()
        note.set_markup(
            f'<span size="small" color="{COLORS["subtext0"]}">'
            + _(
                "Applies DPI, SmartShift, and scroll settings via logiops (requires sudo)"
            )
            + "</span>"
        )
        note.set_halign(Gtk.Align.CENTER)
        apply_card.append(note)

        content.append(apply_card)

        # ═══════════════════════════════════════════════════════════════
        # SCROLL WHEEL SECTION
        # ═══════════════════════════════════════════════════════════════
        scroll_card = SettingsCard(_("Scroll Wheel"))

        # SmartShift with visual
        smartshift_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        smartshift_box.set_margin_bottom(8)

        self.scroll_visual = ScrollWheelVisual(
            config.get("scroll", "smartshift", default=True)
        )
        smartshift_box.append(self.scroll_visual)

        smartshift_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        smartshift_content.set_hexpand(True)

        smartshift_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        smartshift_title = Gtk.Label(label=_("SmartShift"))
        smartshift_title.set_halign(Gtk.Align.START)
        smartshift_title.add_css_class("heading")
        smartshift_header.append(smartshift_title)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        smartshift_header.append(spacer)

        self.smartshift_switch = Gtk.Switch()
        self.smartshift_switch.set_active(
            config.get("scroll", "smartshift", default=True)
        )
        self.smartshift_switch.connect("state-set", self._on_smartshift_changed)
        smartshift_header.append(self.smartshift_switch)

        smartshift_content.append(smartshift_header)

        smartshift_desc = Gtk.Label(
            label=_(
                "Auto-switch to free-spin when scrolling fast, return to ratchet when slow"
            )
        )
        smartshift_desc.set_halign(Gtk.Align.START)
        smartshift_desc.set_wrap(True)
        smartshift_desc.set_max_width_chars(60)
        smartshift_desc.add_css_class("dim-label")
        smartshift_content.append(smartshift_desc)

        smartshift_box.append(smartshift_content)
        scroll_card.append(smartshift_box)

        # Threshold slider
        threshold_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        threshold_box.set_margin_start(76)  # Align with text above

        threshold_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        threshold_label = Gtk.Label(label=_("Switch Threshold"))
        threshold_label.set_halign(Gtk.Align.START)
        threshold_label_box.append(threshold_label)

        spacer2 = Gtk.Box()
        spacer2.set_hexpand(True)
        threshold_label_box.append(spacer2)

        self.threshold_value = Gtk.Label()
        self.threshold_value.add_css_class("dim-label")
        threshold_label_box.append(self.threshold_value)
        threshold_box.append(threshold_label_box)

        threshold_slider_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        ratchet_label = Gtk.Label(label=_("Stay ratchet"))
        ratchet_label.add_css_class("dim-label")
        threshold_slider_box.append(ratchet_label)

        self.threshold_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1, 100, 1
        )
        self.threshold_scale.set_hexpand(True)
        self.threshold_scale.set_draw_value(False)
        self.threshold_scale.set_value(
            config.get("scroll", "smartshift_threshold", default=50)
        )
        self.threshold_scale.connect("value-changed", self._on_threshold_changed)
        self._update_threshold_label(self.threshold_scale.get_value())
        # Disable scroll wheel to prevent accidental changes while scrolling page
        disable_scroll_on_scale(self.threshold_scale)
        threshold_slider_box.append(self.threshold_scale)

        freespin_label = Gtk.Label(label=_("Easy free-spin"))
        freespin_label.add_css_class("dim-label")
        threshold_slider_box.append(freespin_label)

        threshold_box.append(threshold_slider_box)
        scroll_card.append(threshold_box)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(16)
        sep2.set_margin_bottom(16)
        scroll_card.append(sep2)

        # Scroll direction
        direction_row = SettingRow(
            _("Natural Scrolling"),
            _("Scroll content in the direction of finger movement"),
        )
        self.natural_switch = Gtk.Switch()
        self.natural_switch.set_active(config.get("scroll", "natural", default=False))
        self.natural_switch.connect("state-set", self._on_natural_changed)
        direction_row.set_control(self.natural_switch)
        scroll_card.append(direction_row)

        # High-resolution scrolling (HiRes mode)
        smooth_row = SettingRow(
            _("High-Resolution Scroll"),
            _("More scroll events for smoother, faster scrolling"),
        )
        self.smooth_switch = Gtk.Switch()
        self.smooth_switch.set_active(config.get("scroll", "smooth", default=True))
        self.smooth_switch.connect("state-set", self._on_smooth_changed)
        smooth_row.set_control(self.smooth_switch)
        scroll_card.append(smooth_row)

        # Separator before scroll speed
        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep3.set_margin_top(16)
        sep3.set_margin_bottom(16)
        scroll_card.append(sep3)

        # Scroll Speed slider for main wheel
        scroll_speed_row = SettingRow(
            _("Scroll Speed"), _("Lines scrolled per wheel notch")
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

        content.append(scroll_card)

        # ═══════════════════════════════════════════════════════════════
        # THUMB WHEEL SECTION
        # ═══════════════════════════════════════════════════════════════
        thumb_card = SettingsCard(_("Thumb Wheel"))

        thumb_speed_row = SettingRow(
            _("Scroll Speed"), _("Horizontal scroll sensitivity")
        )
        thumb_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        thumb_scale.set_value(config.get("thumbwheel", "speed", default=5))
        thumb_scale.set_size_request(200, -1)
        thumb_scale.set_draw_value(False)
        thumb_scale.connect(
            "value-changed",
            lambda s: config.set("thumbwheel", "speed", int(s.get_value())),
        )
        # Disable scroll wheel to prevent accidental changes while scrolling page
        disable_scroll_on_scale(thumb_scale)
        thumb_speed_row.set_control(thumb_scale)
        thumb_card.append(thumb_speed_row)

        thumb_invert_row = SettingRow(
            _("Invert Direction"), _("Reverse thumb wheel scroll direction")
        )
        thumb_invert = Gtk.Switch()
        thumb_invert.set_active(config.get("thumbwheel", "invert", default=False))
        thumb_invert.connect(
            "state-set",
            lambda s, state: config.set("thumbwheel", "invert", state) or False,
        )
        thumb_invert_row.set_control(thumb_invert)
        thumb_card.append(thumb_invert_row)

        content.append(thumb_card)

        self.set_child(content)

        # Load SmartShift and HiResScroll settings from device on startup
        self._load_smartshift_settings()
        self._load_hiresscroll_settings()

    def _on_dpi_changed(self, dpi):
        # Convert DPI to speed (1-20) for config (no auto-save to avoid lag)
        speed = max(1, min(20, (dpi - 400) // 400 + 1))
        config.set("pointer", "speed", speed)
        config.set("pointer", "dpi", dpi)
        # Apply to hardware via D-Bus
        self._apply_dpi_to_device(dpi)
        # Also apply pointer speed via gsettings (software multiplier)
        self._apply_pointer_speed(dpi)
        # Show pending changes indicator
        self._show_pending_changes()

    def _on_accel_changed(self, combo):
        profile = combo.get_active_id()
        config.set("pointer", "accel_profile", profile)
        # Apply immediately
        try:
            import subprocess

            subprocess.run(
                [
                    "gsettings",
                    "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "accel-profile",
                    profile,
                ],
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pass  # gsettings not available

    def _on_smartshift_changed(self, switch, state):
        config.set("scroll", "smartshift", state)
        self.scroll_visual.set_smartshift(state)
        self.threshold_scale.set_sensitive(state)

        # Apply to device via D-Bus
        threshold = int(self.threshold_scale.get_value())
        # Convert UI percentage (1-100) to device threshold (0-255)
        # Lower threshold = more sensitive, so we invert the percentage
        device_threshold = int((100 - threshold) * 2.55)
        self._apply_smartshift_to_device(state, device_threshold)

        return False

    def _on_threshold_changed(self, scale):
        value = int(scale.get_value())
        config.set("scroll", "smartshift_threshold", value)
        self._update_threshold_label(value)

        # Apply to device via D-Bus
        enabled = self.smartshift_switch.get_active()
        # Convert UI percentage (1-100) to device threshold (0-255)
        # Lower threshold = more sensitive, so we invert the percentage
        device_threshold = int((100 - value) * 2.55)
        self._apply_smartshift_to_device(enabled, device_threshold)

        self._show_pending_changes()

    def _update_threshold_label(self, value):
        self.threshold_value.set_text(f"{int(value)}%")

    def _on_natural_changed(self, switch, state):
        config.set("scroll", "natural", state)
        # Apply immediately via gsettings
        try:
            import subprocess

            subprocess.run(
                [
                    "gsettings",
                    "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "natural-scroll",
                    "true" if state else "false",
                ],
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pass  # gsettings not available
        # Also apply to device via D-Bus HiResScroll
        self._apply_hiresscroll_to_device()
        return False

    def _on_smooth_changed(self, switch, state):
        """Handle high-resolution scroll toggle change"""
        config.set("scroll", "smooth", state)
        # Apply to device via D-Bus HiResScroll
        self._apply_hiresscroll_to_device()
        return False

    def _on_scroll_speed_changed(self, scale):
        """Handle scroll speed slider change"""
        value = int(scale.get_value())
        config.set("scroll", "speed", value)
        # Apply scroll lines setting via imwheel or gsettings
        self._apply_scroll_speed(value)

    def _apply_scroll_speed(self, lines):
        """Apply scroll speed multiplier - works on GNOME, KDE, Hyprland, etc."""
        import subprocess
        import os

        # Convert lines (1-10) to a scroll factor (0.5 to 2.0)
        # lines=1 -> 0.5x, lines=5 -> 1.0x (default), lines=10 -> 2.0x
        scroll_factor = 0.5 + (lines - 1) * 0.167  # Linear interpolation

        # Try different desktop environments
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()

        # GNOME/Mutter on Wayland
        if "gnome" in desktop or "mutter" in desktop:
            try:
                # GNOME uses libinput, scroll factor via experimental settings
                subprocess.run(
                    [
                        "gsettings",
                        "set",
                        "org.gnome.mutter",
                        "experimental-features",
                        "['scale-monitor-framebuffer']",
                    ],
                    capture_output=True,
                    timeout=2,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass  # gsettings not available

        # KDE Plasma
        if "kde" in desktop or "plasma" in desktop:
            try:
                # KDE stores scroll settings in kcminputrc
                subprocess.run(
                    [
                        "kwriteconfig5",
                        "--file",
                        "kcminputrc",
                        "--group",
                        "Mouse",
                        "--key",
                        "ScrollFactor",
                        str(scroll_factor),
                    ],
                    capture_output=True,
                    timeout=2,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass  # kwriteconfig5 not available

        # Hyprland
        hypr_sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if hypr_sig:
            try:
                # Hyprland supports runtime scroll_factor change
                subprocess.run(
                    ["hyprctl", "keyword", "input:scroll_factor", str(scroll_factor)],
                    capture_output=True,
                    timeout=2,
                )
                print(f"Hyprland scroll_factor set to {scroll_factor:.2f}")
            except (FileNotFoundError, subprocess.SubprocessError):
                pass  # hyprctl not available

        # Sway
        if "sway" in desktop.lower():
            try:
                # Get device name and set scroll factor
                result = subprocess.run(
                    ["swaymsg", "-t", "get_inputs"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    inputs = json.loads(result.stdout)
                    for inp in inputs:
                        if "pointer" in inp.get("type", ""):
                            name = inp.get("identifier", "")
                            subprocess.run(
                                [
                                    "swaymsg",
                                    "input",
                                    name,
                                    "scroll_factor",
                                    str(scroll_factor),
                                ],
                                capture_output=True,
                                timeout=2,
                            )
            except (
                FileNotFoundError,
                subprocess.SubprocessError,
                json.JSONDecodeError,
            ):
                pass  # swaymsg not available

        # X11 fallback with imwheel (if available)
        if session == "x11":
            try:
                # Create/update imwheel config for scroll multiplier
                imwheel_config = os.path.expanduser("~/.imwheelrc")
                # lines value directly maps to scroll multiplier
                config_content = f"""".*"
None,      Up,   Button4, {lines}
None,      Down, Button5, {lines}
"""
                with open(imwheel_config, "w", encoding="utf-8") as f:
                    f.write(config_content)
                # Restart imwheel if running
                uid = str(os.getuid())
                subprocess.run(["pkill", "-u", uid, "imwheel"], capture_output=True, timeout=2)
                subprocess.run(["imwheel", "-b", "45"], capture_output=True, timeout=2)
            except (FileNotFoundError, subprocess.SubprocessError, OSError):
                pass  # imwheel not available

        print(f"Scroll speed set to {lines} lines (factor: {scroll_factor:.2f})")

    def _apply_hiresscroll_to_device(self):
        """Apply HiResScroll settings - first try D-Bus, then update logid config"""
        hires = config.get("scroll", "smooth", default=True)
        invert = config.get("scroll", "natural", default=False)
        target = False  # Default to False

        # Try D-Bus first
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
                "SetHiresscrollMode",
                GLib.Variant("(bbb)", (hires, invert, target)),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            print(f"HiResScroll applied via D-Bus: hires={hires}, invert={invert}")
            return
        except GLib.Error as e:
            print(f"D-Bus failed (logid may be blocking): {e.message}")
        except Exception as e:
            print(f"D-Bus failed: {e}")

        # D-Bus failed, settings will apply after logid restart
        print(f"HiResScroll saved to config (requires logid restart to apply)")

    def _load_hiresscroll_settings(self):
        """Load HiResScroll settings from device via D-Bus on startup"""
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

            # Get current HiResScroll configuration
            result = proxy.call_sync(
                "GetHiresscrollMode", None, Gio.DBusCallFlags.NONE, 2000, None
            )

            if result:
                hires = result.get_child_value(0).get_boolean()
                invert = result.get_child_value(1).get_boolean()
                # target = result.get_child_value(2).get_boolean()  # Not used in UI

                # Update UI to match device
                if hasattr(self, "smooth_switch"):
                    self.smooth_switch.set_active(hires)
                    config.set("scroll", "smooth", hires)

                # Note: Natural scrolling is controlled by gsettings, not device
                # so we don't update it from device settings

                print(f"Loaded HiResScroll from device: hires={hires}, invert={invert}")
        except GLib.Error as e:
            print(f"D-Bus error getting HiResScroll: {e.message}")
        except Exception as e:
            print(f"Failed to get HiResScroll via D-Bus: {e}")

    def _apply_pointer_speed(self, dpi):
        """Apply pointer speed via gsettings (-1.0 to 1.0)"""
        try:
            import subprocess

            # Convert DPI (400-8000) to gsettings speed (-1.0 to 1.0)
            speed = (dpi - 4200) / 3800  # Maps 400->-1.0, 8000->1.0
            speed = max(-1.0, min(1.0, speed))
            subprocess.run(
                [
                    "gsettings",
                    "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "speed",
                    str(speed),
                ],
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pass  # gsettings not available

    def _apply_dpi_to_device(self, dpi):
        """Apply DPI directly to the mouse via D-Bus"""
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
            # Call SetDpi with the DPI value
            proxy.call_sync(
                "SetDpi",
                GLib.Variant("(q)", (dpi,)),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            # Update status to show DPI was applied
            if hasattr(self, "status_icon") and hasattr(self, "status_label"):
                self.status_icon.set_from_icon_name("emblem-ok-symbolic")
                self.status_label.set_text(_("DPI set to {}").format(dpi))
                GLib.timeout_add(2000, self._reset_status)
        except GLib.Error as e:
            print(f"D-Bus error setting DPI: {e.message}")
            if hasattr(self, "status_icon") and hasattr(self, "status_label"):
                self.status_icon.set_from_icon_name("dialog-warning-symbolic")
                self.status_label.set_text(_("DPI error: daemon not running?"))
                GLib.timeout_add(3000, self._reset_status)
        except Exception as e:
            print(f"Failed to set DPI via D-Bus: {e}")

    def _show_pending_changes(self):
        """Show that there are unsaved changes"""
        if hasattr(self, "status_icon") and hasattr(self, "status_label"):
            self.status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.status_label.set_text(_("Click Apply to save changes"))

    def _on_apply_clicked(self, button):
        """Apply all settings via logiops and save config"""
        # Save config to file (this will show toast)
        config.save()
        # Apply to device hardware
        config.apply_to_device()
        # Update status
        if hasattr(self, "status_icon") and hasattr(self, "status_label"):
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.status_label.set_text(_("Settings applied!"))
            # Reset after delay
            GLib.timeout_add(3000, self._reset_status)

    def _reset_status(self):
        if hasattr(self, "status_label"):
            self.status_label.set_text(_("Settings are up to date"))
        return False

    def _load_smartshift_settings(self):
        """Load SmartShift settings from device via D-Bus on startup"""
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

            # Check if SmartShift is supported
            supported = proxy.call_sync(
                "SmartShiftSupported", None, Gio.DBusCallFlags.NONE, 2000, None
            )

            if supported and supported.get_child_value(0).get_boolean():
                # Get current SmartShift configuration
                result = proxy.call_sync(
                    "GetSmartShift", None, Gio.DBusCallFlags.NONE, 2000, None
                )

                if result:
                    enabled = result.get_child_value(0).get_boolean()
                    device_threshold = result.get_child_value(1).get_byte()

                    # Convert device threshold (0-255) to UI percentage (1-100)
                    # Device: lower = more sensitive, so we invert it
                    ui_threshold = 100 - int(device_threshold / 2.55)
                    ui_threshold = max(1, min(100, ui_threshold))

                    # Update UI elements
                    self.smartshift_switch.set_active(enabled)
                    self.threshold_scale.set_value(ui_threshold)
                    self.threshold_scale.set_sensitive(enabled)
                    self.scroll_visual.set_smartshift(enabled)

                    # Update config
                    config.set("scroll", "smartshift", enabled)
                    config.set("scroll", "smartshift_threshold", ui_threshold)

                    print(
                        f"SmartShift loaded: enabled={enabled}, threshold={ui_threshold}%"
                    )
            else:
                # SmartShift not supported, disable UI
                self.smartshift_switch.set_sensitive(False)
                self.threshold_scale.set_sensitive(False)
                print("SmartShift not supported on this device")

        except GLib.Error as e:
            print(f"D-Bus error loading SmartShift settings: {e.message}")
        except Exception as e:
            print(f"Failed to load SmartShift settings: {e}")

    def _apply_smartshift_to_device(self, enabled, threshold):
        """Apply SmartShift settings directly to the mouse via D-Bus"""
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

            # Call SetSmartShift with enabled and threshold
            proxy.call_sync(
                "SetSmartShift",
                GLib.Variant("(by)", (enabled, threshold)),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )

            # Update status to show SmartShift was applied
            if hasattr(self, "status_icon") and hasattr(self, "status_label"):
                self.status_icon.set_from_icon_name("emblem-ok-symbolic")
                mode = _("enabled") if enabled else _("disabled")
                self.status_label.set_text(_("SmartShift {}").format(mode))
                GLib.timeout_add(2000, self._reset_status)

            print(f"SmartShift applied: enabled={enabled}, threshold={threshold}")

        except GLib.Error as e:
            print(f"D-Bus error setting SmartShift: {e.message}")
            if hasattr(self, "status_icon") and hasattr(self, "status_label"):
                self.status_icon.set_from_icon_name("dialog-warning-symbolic")
                self.status_label.set_text(_("SmartShift error: daemon not running?"))
                GLib.timeout_add(3000, self._reset_status)
        except Exception as e:
            print(f"Failed to set SmartShift via D-Bus: {e}")
