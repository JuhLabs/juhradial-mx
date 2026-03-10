"""
JuhRadial MX - Settings Sidebar Mixin

Sidebar creation and related methods (donate card, heart animation,
exit button) extracted from SettingsWindow for modularity.

SPDX-License-Identifier: GPL-3.0
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Adw

from i18n import _
from settings_theme import COLORS
from settings_constants import get_nav_items_for_mode
from settings_widgets import NavButton


class SidebarMixin:
    """Mixin providing sidebar creation and related methods for SettingsWindow."""

    def _create_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.add_css_class("sidebar")

        self.nav_buttons = {}

        # Filter sidebar tabs based on device mode
        visible_nav = get_nav_items_for_mode(self._device_mode)

        for item_id, label, icon in visible_nav:
            btn = NavButton(item_id, label, icon, on_click=self._on_nav_clicked)
            self.nav_buttons[item_id] = btn
            sidebar.append(btn)

        # Spacer to push credits to bottom
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(12)
        sep.set_margin_bottom(8)
        sidebar.append(sep)

        # Credits section with gradient card
        credits_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        credits_box.add_css_class("donate-card")
        credits_box.set_margin_start(8)
        credits_box.set_margin_end(8)
        credits_box.set_margin_bottom(8)

        # Developer info
        dev_label = Gtk.Label()
        dev_label.set_markup(
            f'<span size="small" color="{COLORS["subtext0"]}">'
            + _("Developed by")
            + "</span>"
        )
        dev_label.set_halign(Gtk.Align.START)
        credits_box.append(dev_label)

        name_label = Gtk.Label()
        name_label.set_markup(
            f'<span size="small" weight="bold" color="{COLORS["text"]}">JuhLabs (Julian Hermstad)</span>'
        )
        name_label.set_halign(Gtk.Align.START)
        credits_box.append(name_label)

        # Website link
        site_label = Gtk.Label()
        site_label.set_markup(
            f'<span size="x-small"><a href="https://www.juhlabs.com">www.juhlabs.com</a></span>'
        )
        site_label.set_halign(Gtk.Align.START)
        site_label.set_margin_top(2)
        site_label.connect(
            "activate-link",
            lambda label, uri: (Gtk.show_uri(None, uri, Gdk.CURRENT_TIME), True)[-1],
        )
        credits_box.append(site_label)

        # Description
        desc_label = Gtk.Label()
        desc_label.set_markup(
            f'<span size="x-small" color="{COLORS["subtext0"]}">'
            + _(
                "Free &amp; open source software.\nIf you enjoy this project,\nconsider supporting development."
            )
            + "</span>"
        )
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_margin_top(4)
        credits_box.append(desc_label)

        # Glowing heart (Cairo-drawn with breathing animation)
        self._heart_area = Gtk.DrawingArea()
        self._heart_area.set_size_request(40, 40)
        self._heart_area.set_halign(Gtk.Align.CENTER)
        self._heart_area.set_margin_top(6)
        self._heart_breath = 0.0
        self._heart_area.set_draw_func(self._draw_heart)
        self._heart_timer = GLib.timeout_add(30, self._tick_heart)
        credits_box.append(self._heart_area)

        # Donate button
        donate_btn = Gtk.Button()
        donate_btn.add_css_class("donate-btn")
        donate_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        donate_box.set_halign(Gtk.Align.CENTER)
        donate_label = Gtk.Label(label=_("Buy me a coffee"))
        donate_box.append(donate_label)
        donate_btn.set_child(donate_box)
        donate_btn.set_margin_top(4)
        donate_btn.connect("clicked", self._on_donate_clicked)
        credits_box.append(donate_btn)

        sidebar.append(credits_box)

        # Exit button - kills daemon, overlay, and settings
        exit_btn = Gtk.Button()
        exit_btn.add_css_class("destructive-action")
        exit_btn.set_margin_start(8)
        exit_btn.set_margin_end(8)
        exit_btn.set_margin_bottom(12)
        exit_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        exit_box.set_halign(Gtk.Align.CENTER)
        exit_icon = Gtk.Image.new_from_icon_name("application-exit-symbolic")
        exit_box.append(exit_icon)
        exit_label = Gtk.Label(label=_("Exit JuhRadial MX"))
        exit_box.append(exit_label)
        exit_btn.set_child(exit_box)
        exit_btn.connect("clicked", self._on_exit_clicked)
        sidebar.append(exit_btn)

        return sidebar

    def _tick_heart(self):
        """Advance breathing cycle and redraw the heart."""
        import math
        self._heart_breath = (self._heart_breath + 0.03) % (2 * math.pi)
        self._heart_area.queue_draw()
        return True

    def _draw_heart(self, area, cr, width, height):
        """Draw a glowing heart with Cairo."""
        import math
        import cairo

        t = (math.sin(self._heart_breath) + 1.0) / 2.0  # 0..1 breathing
        cx, cy = width / 2, height / 2 + 2
        scale = 0.38 + t * 0.04  # subtle size pulse

        # Parse accent color
        r, g, b = self._parse_hex_color(COLORS.get("accent", "#cba6f7"))

        # Outer glow (soft radial gradient)
        glow_alpha = 0.15 + t * 0.2
        glow_r = 18 + t * 6
        pat = cairo.RadialGradient(cx, cy, 0, cx, cy, glow_r)
        pat.add_color_stop_rgba(0, r, g, b, glow_alpha)
        pat.add_color_stop_rgba(1, r, g, b, 0)
        cr.set_source(pat)
        cr.arc(cx, cy, glow_r, 0, 2 * math.pi)
        cr.fill()

        # Draw heart shape
        cr.save()
        cr.translate(cx, cy)
        cr.scale(scale, scale)
        cr.move_to(0, 10)
        cr.curve_to(-20, -6, -12, -22, 0, -12)
        cr.curve_to(12, -22, 20, -6, 0, 10)
        cr.close_path()
        cr.restore()

        # Fill with gradient
        heart_alpha = 0.75 + t * 0.25
        cr.set_source_rgba(r, g, b, heart_alpha)
        cr.fill_preserve()

        # Thin bright outline
        cr.set_source_rgba(r, g, b, 0.4 + t * 0.3)
        cr.set_line_width(0.6)
        cr.stroke()

    @staticmethod
    def _parse_hex_color(hex_color):
        """Parse '#rrggbb' to (r, g, b) floats 0..1."""
        h = hex_color.lstrip("#")
        if len(h) == 6:
            return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
        return 0.8, 0.6, 0.9  # fallback lavender

    def _on_donate_clicked(self, button):
        """Open PayPal donation link"""
        root = self.get_root() if hasattr(self, "get_root") else None
        Gtk.show_uri(root, "https://paypal.me/LangbachHermstad", Gdk.CURRENT_TIME)

    def _on_exit_clicked(self, button):
        """Show confirmation dialog, then kill daemon + overlay + settings."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=_("Exit JuhRadial MX?"),
            body=_(
                "This will stop the daemon, radial overlay, and close settings. "
                "The radial wheel and all features will be unavailable until you "
                "restart JuhRadial MX."
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("exit", _("Exit"))
        dialog.set_response_appearance("exit", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(dlg, response):
            if response == "exit":
                import subprocess
                # Kill daemon and overlay (settings exits via GTK quit)
                subprocess.run(
                    ["pkill", "-f", "juhradiald"],
                    capture_output=True, timeout=2,
                )
                subprocess.run(
                    ["pkill", "-f", "juhradial-overlay"],
                    capture_output=True, timeout=2,
                )
                self.get_application().quit()

        dialog.connect("response", on_response)
        dialog.present()
