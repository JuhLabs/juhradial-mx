#!/usr/bin/env python3
"""
JuhRadial MX - Gaming Mode Page

Gaming mode settings: master toggle, overlay suppression, DPI profiles,
and navigation to macros page.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw

from i18n import _
from settings_config import config
from settings_theme import COLORS
from settings_widgets import SettingsCard, SettingRow, PageHeader, InfoCard

logger = logging.getLogger(__name__)

# Default DPI profile presets
DEFAULT_DPI_PROFILES = [
    {"name": "Precision", "dpi": 400, "color": "blue"},
    {"name": "Normal", "dpi": 1000, "color": "green"},
    {"name": "Fast", "dpi": 3200, "color": "red"},
]

DPI_PROFILE_COLORS = {
    "blue": COLORS.get("blue", "#89b4fa"),
    "green": COLORS.get("green", "#a6e3a1"),
    "red": COLORS.get("red", "#f38ba8"),
}


class GamingPage(Gtk.ScrolledWindow):
    """Gaming mode configuration page."""

    def __init__(self, parent_window=None, on_open_macros=None):
        super().__init__()
        self._parent_window = parent_window
        self._on_open_macros = on_open_macros
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Page header
        header = PageHeader(
            "input-gaming-symbolic",
            _("Gaming Mode"),
            _("Optimize your mouse for gaming"),
        )
        content.append(header)

        # =============================================
        # GAMING MODE MASTER TOGGLE
        # =============================================
        toggle_card = SettingsCard(_("Gaming Mode"))

        # Master toggle
        master_row = SettingRow(
            _("Enable Gaming Mode"),
            _("Activate gaming-optimized settings"),
        )
        self._master_switch = Gtk.Switch()
        self._master_switch.set_valign(Gtk.Align.CENTER)
        self._master_switch.set_active(
            config.get("gaming", "enabled", default=False)
        )
        self._master_switch.connect("state-set", self._on_master_toggled)
        master_row.set_control(self._master_switch)
        toggle_card.append(master_row)

        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep1.set_margin_top(8)
        sep1.set_margin_bottom(8)
        toggle_card.append(sep1)

        # Suppress overlay toggle
        overlay_row = SettingRow(
            _("Suppress Overlay"),
            _("Prevent radial menu from appearing during gaming"),
        )
        self._overlay_switch = Gtk.Switch()
        self._overlay_switch.set_valign(Gtk.Align.CENTER)
        self._overlay_switch.set_active(
            config.get("gaming", "suppress_overlay", default=True)
        )
        self._overlay_switch.connect("state-set", self._on_overlay_toggled)
        overlay_row.set_control(self._overlay_switch)
        toggle_card.append(overlay_row)

        content.append(toggle_card)

        # =============================================
        # DPI PROFILES
        # =============================================
        dpi_card = SettingsCard(_("DPI Profiles"))

        # Active profile selector
        active_row = SettingRow(
            _("Active Profile"),
            _("Currently active DPI preset"),
        )
        active_idx = config.get("gaming", "active_dpi_profile", default=1)
        profiles = config.get("gaming", "dpi_profiles", default=DEFAULT_DPI_PROFILES)

        profile_names = Gtk.StringList()
        for p in profiles:
            profile_names.append(_(p.get("name", "Profile")))

        self._profile_dropdown = Gtk.DropDown(model=profile_names)
        self._profile_dropdown.set_selected(active_idx)
        self._profile_dropdown.connect("notify::selected", self._on_active_profile_changed)
        active_row.set_control(self._profile_dropdown)
        dpi_card.append(active_row)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(8)
        sep2.set_margin_bottom(8)
        dpi_card.append(sep2)

        # DPI profile slots
        self._dpi_rows = []
        for i, profile in enumerate(profiles):
            row = self._create_dpi_profile_row(i, profile)
            self._dpi_rows.append(row)
            dpi_card.append(row)

            if i < len(profiles) - 1:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                sep.set_margin_top(4)
                sep.set_margin_bottom(4)
                dpi_card.append(sep)

        content.append(dpi_card)

        # =============================================
        # MACROS NAVIGATION
        # =============================================
        macros_card = SettingsCard(_("Macros"))

        macros_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        macros_row.add_css_class("button-row")

        macro_icon_box = Gtk.Box()
        macro_icon_box.add_css_class("button-icon-box")
        macro_icon_box.set_valign(Gtk.Align.CENTER)
        macro_icon = Gtk.Image.new_from_icon_name("applications-science-symbolic")
        macro_icon.set_pixel_size(20)
        macro_icon.add_css_class("button-icon")
        macro_icon_box.append(macro_icon)
        macros_row.append(macro_icon_box)

        macro_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        macro_text.set_hexpand(True)
        macro_text.set_valign(Gtk.Align.CENTER)

        macro_title = Gtk.Label(label=_("Manage Macros"))
        macro_title.set_halign(Gtk.Align.START)
        macro_title.add_css_class("button-name")
        macro_text.append(macro_title)

        macro_desc = Gtk.Label(label=_("Create, edit, and assign macro sequences"))
        macro_desc.set_halign(Gtk.Align.START)
        macro_desc.add_css_class("button-action")
        macro_text.append(macro_desc)

        macros_row.append(macro_text)

        macro_arrow = Gtk.Button()
        macro_arrow.set_child(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        macro_arrow.add_css_class("button-arrow")
        macro_arrow.add_css_class("flat")
        macro_arrow.set_valign(Gtk.Align.CENTER)
        macro_arrow.connect("clicked", lambda _: self._navigate_to_macros())
        macros_row.append(macro_arrow)

        # Make row clickable
        click = Gtk.GestureClick()
        click.connect("released", lambda g, n, x, y: self._navigate_to_macros())
        macros_row.add_controller(click)

        macros_card.append(macros_row)
        content.append(macros_card)

        # =============================================
        # INFO CARD
        # =============================================
        info_card = InfoCard(_("About Gaming Mode"))

        info_text = _(
            "Gaming mode optimizes your mouse for gaming by switching to "
            "a dedicated DPI profile and optionally suppressing the radial "
            "menu overlay to prevent accidental activation.\n\n"
            "DPI profiles let you quickly switch between precision (low DPI), "
            "normal (medium DPI), and fast (high DPI) sensitivities. "
            "Macros allow you to record and replay complex input sequences."
        )
        info_label = Gtk.Label(label=info_text)
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        info_card.append(info_label)

        content.append(info_card)

        # Wrap in Adw.Clamp
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(content)
        self.set_child(clamp)

    def set_parent_window(self, window):
        """Set parent window reference (deferred from constructor)."""
        self._parent_window = window

    # ------------------------------------------------------------------
    # DPI profile row
    # ------------------------------------------------------------------

    def _create_dpi_profile_row(self, index, profile):
        """Create an editable DPI profile row."""
        color_name = profile.get("color", "green")
        color_hex = DPI_PROFILE_COLORS.get(color_name, COLORS.get("accent", "#00d4ff"))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("setting-row")

        # Color dot
        color_dot = Gtk.DrawingArea()
        color_dot.set_size_request(12, 12)
        color_dot.set_valign(Gtk.Align.CENTER)

        r = int(color_hex[1:3], 16) / 255.0
        g = int(color_hex[3:5], 16) / 255.0
        b = int(color_hex[5:7], 16) / 255.0

        def draw_dot(area, cr, w, h, _r=r, _g=g, _b=b):
            cr.set_source_rgb(_r, _g, _b)
            cr.arc(w / 2, h / 2, 5, 0, 2 * 3.14159)
            cr.fill()

        color_dot.set_draw_func(draw_dot)
        row.append(color_dot)

        # Name (editable)
        name_entry = Gtk.Entry()
        name_entry.set_text(profile.get("name", f"Profile {index + 1}"))
        name_entry.set_size_request(120, -1)
        name_entry.add_css_class("flat")
        name_entry.connect(
            "changed",
            lambda e, idx=index: self._on_profile_name_changed(idx, e.get_text()),
        )
        row.append(name_entry)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row.append(spacer)

        # DPI value with spin button
        dpi_adj = Gtk.Adjustment(
            value=profile.get("dpi", 800),
            lower=100,
            upper=25600,
            step_increment=50,
            page_increment=200,
        )
        dpi_spin = Gtk.SpinButton(adjustment=dpi_adj, climb_rate=1, digits=0)
        dpi_spin.set_size_request(100, -1)
        dpi_spin.connect(
            "value-changed",
            lambda s, idx=index: self._on_dpi_changed(idx, int(s.get_value())),
        )
        row.append(dpi_spin)

        dpi_label = Gtk.Label(label=_("DPI"))
        dpi_label.add_css_class("dim-label")
        row.append(dpi_label)

        return row

    # ------------------------------------------------------------------
    # Config handlers
    # ------------------------------------------------------------------

    def _on_master_toggled(self, switch, state):
        """Handle gaming mode master toggle."""
        config.set("gaming", "enabled", state)
        config.save()
        logger.info("Gaming mode %s", "enabled" if state else "disabled")
        return False

    def _on_overlay_toggled(self, switch, state):
        """Handle overlay suppression toggle."""
        config.set("gaming", "suppress_overlay", state)
        config.save()
        return False

    def _on_active_profile_changed(self, dropdown, _pspec):
        """Handle active DPI profile change."""
        idx = dropdown.get_selected()
        config.set("gaming", "active_dpi_profile", idx)
        config.save()
        logger.info("Active DPI profile changed to %d", idx)

    def _on_profile_name_changed(self, index, name):
        """Handle DPI profile name edit."""
        profiles = config.get("gaming", "dpi_profiles", default=DEFAULT_DPI_PROFILES)
        if index < len(profiles):
            profiles[index]["name"] = name
            config.set("gaming", "dpi_profiles", profiles)
            # Don't auto-save on every keystroke - will save on next toggle or window close

    def _on_dpi_changed(self, index, dpi):
        """Handle DPI value change."""
        profiles = config.get("gaming", "dpi_profiles", default=DEFAULT_DPI_PROFILES)
        if index < len(profiles):
            profiles[index]["dpi"] = dpi
            config.set("gaming", "dpi_profiles", profiles)
            config.save()
            logger.info("DPI profile %d set to %d", index, dpi)

    def _navigate_to_macros(self):
        """Navigate to the macros page."""
        if self._on_open_macros:
            self._on_open_macros()
