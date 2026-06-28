#!/usr/bin/env python3
"""
JuhRadial MX - Settings Page

SettingsPage: Appearance, language, and application settings.

SPDX-License-Identifier: GPL-3.0
"""

import json
import logging
import math
import shutil
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio, Adw

from i18n import _, SUPPORTED_LANGUAGES
from settings_config import ConfigManager, config
from settings_constants import (
    SUPPORTED_DES,
    DE_COMMAND_MAP,
    detect_desktop_environment,
    get_de_key,
)
import settings_theme
from settings_widgets import SettingsCard, SettingRow, PageHeader, _resolve_asset_path
from themes import get_theme_list

logger = logging.getLogger(__name__)


def _hex_rgb(hex_color, default=(0.31, 0.94, 0.79)):
    try:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
    except Exception:
        return default


class ThemePreview(Gtk.Box):
    """Live preview card: an Actions Ring rendered in the selected theme's
    colors, so users can see the theme they are choosing before applying it."""

    SLICES = 8

    def __init__(self, theme_key):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("settings-card")
        self._colors = {}
        self._name = ""

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        eyebrow = Gtk.Label(label=_("ACTIONS RING"))
        eyebrow.set_halign(Gtk.Align.START)
        eyebrow.set_hexpand(True)
        eyebrow.add_css_class("section-eyebrow")
        head.append(eyebrow)
        badge = Gtk.Label(label=_("%d SLICES") % self.SLICES)
        badge.add_css_class("live-badge")
        head.append(badge)
        self.append(head)

        self._area = Gtk.DrawingArea()
        self._area.set_content_height(210)
        self._area.set_hexpand(True)
        self._area.set_draw_func(self._draw)
        self.append(self._area)

        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._name_label = Gtk.Label(label="")
        self._name_label.set_halign(Gtk.Align.START)
        self._name_label.set_hexpand(True)
        self._name_label.add_css_class("setting-label")
        foot.append(self._name_label)
        self._swatches = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._swatches.set_valign(Gtk.Align.CENTER)
        foot.append(self._swatches)
        self.append(foot)

        self.set_theme(theme_key)

    def set_theme(self, theme_key):
        from themes import get_theme, get_colors, get_radial_image
        theme = get_theme(theme_key)
        self._colors = get_colors(theme_key)
        self._name = theme.get("name", theme_key)
        self._name_label.set_label(_("Theme: %s") % self._name)
        # Only the 3D themes ship bespoke wheel art (radial_image set). The menu
        # draws every vector theme live (code slices in theme colours, no PNG),
        # so the preview does the same in _draw_vector_ring instead of faking a
        # chrome PNG. This makes each code theme read as its own colour, exactly
        # like the on-device menu.
        self._wheel = None
        wheel_name = get_radial_image(theme_key)
        if wheel_name:
            path = _resolve_asset_path("radial-wheels/" + wheel_name)
            if path:
                try:
                    self._wheel = GdkPixbuf.Pixbuf.new_from_file(path)
                except Exception:
                    self._wheel = None
        child = self._swatches.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._swatches.remove(child)
            child = nxt
        for key in ["accent", "accent2", "green", "yellow", "red", "mauve"]:
            color = self._colors.get(key)
            if not color:
                continue
            dot = Gtk.DrawingArea()
            dot.set_content_width(14)
            dot.set_content_height(14)
            dot.set_draw_func(self._draw_swatch, color)
            self._swatches.append(dot)
        self._area.queue_draw()

    @staticmethod
    def _draw_swatch(area, cr, w, h, color):
        r, g, b = _hex_rgb(color)
        cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 2 * math.pi)
        cr.set_source_rgb(r, g, b)
        cr.fill()

    def _draw(self, area, cr, width, height):
        if width <= 0 or height <= 0:
            return
        cx, cy = width / 2.0, height / 2.0
        if self._wheel is not None:
            # 3D theme: ship-as-is bespoke wheel art.
            iw, ih = self._wheel.get_width(), self._wheel.get_height()
            if iw > 0 and ih > 0:
                scale = min(width, height) / max(iw, ih) * 0.92
                dw, dh = iw * scale, ih * scale
                cr.save()
                cr.translate(cx - dw / 2.0, cy - dh / 2.0)
                cr.scale(scale, scale)
                Gdk.cairo_set_source_pixbuf(cr, self._wheel, 0, 0)
                cr.paint()
                cr.restore()
            return
        # Vector theme: render the same code-drawn ring the menu paints, in this
        # theme's colours (base disc, surface slices, accent highlight + center).
        self._draw_vector_ring(cr, cx, cy, min(width, height) / 2.0 * 0.92)

    def _draw_vector_ring(self, cr, cx, cy, R):
        # Mirrors overlay_painting.py vector mode: MENU_RADIUS=150,
        # CENTER_ZONE_RADIUS=45, slices span [center+6 .. menu-6].
        c = self._colors
        ro, ri, cz = R * 0.96, R * 0.34, R * 0.30
        br, bg, bb = _hex_rgb(c.get("base") or "#1e1e2e")
        s0r, s0g, s0b = _hex_rgb(c.get("surface0") or "#313244")
        s2r, s2g, s2b = _hex_rgb(c.get("surface2") or "#585b70")
        ar, ag, ab = _hex_rgb(c.get("accent"))
        # Backing disc + outer border
        cr.set_source_rgba(br, bg, bb, 0.92)
        cr.arc(cx, cy, R, 0, 2 * math.pi)
        cr.fill()
        cr.set_line_width(2)
        cr.set_source_rgba(s2r, s2g, s2b, 0.6)
        cr.arc(cx, cy, R, 0, 2 * math.pi)
        cr.stroke()
        # 8 slices; the top slice is highlighted in the theme accent (mirrors the
        # menu's selection highlight), the rest are neutral surface fills.
        for i in range(8):
            a0 = math.radians(i * 45 - 22.5 - 90)
            a1 = math.radians(i * 45 + 22.5 - 90)
            cr.new_path()
            cr.arc(cx, cy, ro, a0, a1)
            cr.arc_negative(cx, cy, ri, a1, a0)
            cr.close_path()
            if i == 0:
                cr.set_source_rgba(ar, ag, ab, 0.55)
                cr.fill_preserve()
                cr.set_line_width(1.5)
                cr.set_source_rgba(ar, ag, ab, 0.9)
            else:
                cr.set_source_rgba(s0r, s0g, s0b, 0.55)
                cr.fill_preserve()
                cr.set_line_width(1.2)
                cr.set_source_rgba(s2r, s2g, s2b, 0.5)
            cr.stroke()
        # Center zone + accent hub
        cr.set_source_rgba(br, bg, bb, 0.97)
        cr.arc(cx, cy, cz, 0, 2 * math.pi)
        cr.fill_preserve()
        cr.set_line_width(2)
        cr.set_source_rgba(s2r, s2g, s2b, 0.6)
        cr.stroke()
        cr.set_source_rgba(ar, ag, ab, 0.9)
        cr.arc(cx, cy, cz * 0.34, 0, 2 * math.pi)
        cr.fill()


class SettingsPage(Gtk.ScrolledWindow):
    """General settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Page header
        header = PageHeader(
            "emblem-system-symbolic",
            _("Settings"),
            _("Appearance, language, and application preferences"),
        )
        content.append(header)

        # Appearance settings
        appearance_card = SettingsCard(_("Appearance"))

        theme_row = SettingRow(
            _("Theme"), _("Choose color theme for radial menu and settings")
        )
        theme_dropdown = Gtk.DropDown()
        theme_list = get_theme_list()
        self._theme_keys = [t[0] for t in theme_list]
        theme_options = Gtk.StringList.new([t[1] for t in theme_list])
        theme_dropdown.set_model(theme_options)
        # Set current theme
        current_theme = config.get("theme", default="phosphor")
        if current_theme in self._theme_keys:
            theme_dropdown.set_selected(self._theme_keys.index(current_theme))
        else:
            theme_dropdown.set_selected(0)
        theme_dropdown.connect("notify::selected", self._on_theme_changed)
        theme_row.set_control(theme_dropdown)
        appearance_card.append(theme_row)

        # Live preview of the selected theme (recolors on change)
        self._theme_preview = ThemePreview(current_theme)
        appearance_card.append(self._theme_preview)

        blur_row = SettingRow(
            _("Blur Effect"), _("Enable background blur for radial menu")
        )
        blur_switch = Gtk.Switch()
        blur_switch.set_active(config.get("blur_enabled", default=True))
        blur_switch.connect(
            "state-set", lambda s, state: config.set("blur_enabled", state) or False
        )
        blur_row.set_control(blur_switch)
        appearance_card.append(blur_row)

        # Language selector
        lang_row = SettingRow(_("Language"), _("Choose display language"))
        lang_dropdown = Gtk.DropDown()
        lang_keys = list(SUPPORTED_LANGUAGES.keys())
        lang_labels = list(SUPPORTED_LANGUAGES.values())
        lang_model = Gtk.StringList.new(lang_labels)
        lang_dropdown.set_model(lang_model)
        # Set current selection from config
        current_lang = config.get("language", default="system")
        if current_lang in lang_keys:
            lang_dropdown.set_selected(lang_keys.index(current_lang))

        def _on_language_changed(dropdown, _param):
            idx = dropdown.get_selected()
            if idx < len(lang_keys):
                config.set("language", lang_keys[idx])
                config.save(show_toast=False)
                # Reload translations and recreate window
                from i18n import reload_language

                reload_language()
                # Notify overlay process to reload translations immediately
                try:
                    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                    bus.emit_signal(
                        None,  # broadcast
                        "/org/kde/juhradialmx/Settings",
                        "org.kde.juhradialmx.Settings",
                        "LanguageChanged",
                        GLib.Variant("(s)", (lang_keys[idx],)),
                    )
                except GLib.Error as e:
                    logger.debug("LanguageChanged D-Bus signal failed: %s", e)
                app = self.get_root().get_application()
                if app:
                    # hold() prevents app from quitting when last window closes
                    app.hold()
                    self.get_root().close()

                    def _recreate_window():
                        app.activate()
                        # Navigate back to settings page
                        windows = app.get_windows()
                        if windows:
                            windows[0]._on_nav_clicked("settings")
                        app.release()
                        return False

                    GLib.idle_add(_recreate_window)

        lang_dropdown.connect("notify::selected", _on_language_changed)
        lang_row.set_control(lang_dropdown)
        appearance_card.append(lang_row)

        content.append(appearance_card)

        # Desktop Environment selector
        de_card = SettingsCard(_("Desktop Environment"))

        detected_de = detect_desktop_environment()
        detected_label = next(
            (label for key, label in SUPPORTED_DES if key == detected_de),
            detected_de,
        )

        de_row = SettingRow(
            _("Desktop"),
            _("Commands for screenshot, files, etc. adapt to your DE (detected: {})").format(
                detected_label
            ),
        )
        de_dropdown = Gtk.DropDown()
        self._de_keys = [key for key, _ in SUPPORTED_DES]
        de_labels = [label for _, label in SUPPORTED_DES]
        de_labels[0] = f"{de_labels[0]} ({detected_label})"
        de_model = Gtk.StringList.new(de_labels)
        de_dropdown.set_model(de_model)
        current_de = config.get("desktop_environment", default="auto")
        if current_de in self._de_keys:
            de_dropdown.set_selected(self._de_keys.index(current_de))
        de_dropdown.connect("notify::selected", self._on_de_changed)
        de_row.set_control(de_dropdown)
        de_card.append(de_row)

        apply_de_row = SettingRow(
            _("Apply DE Defaults"),
            _("Update radial menu commands to match selected desktop"),
        )
        apply_de_btn = Gtk.Button(label=_("Apply"))
        apply_de_btn.add_css_class("suggested-action")
        apply_de_btn.connect("clicked", self._on_apply_de_defaults)
        apply_de_row.set_control(apply_de_btn)
        de_card.append(apply_de_row)

        content.append(de_card)

        # App settings
        app_card = SettingsCard(_("Application"))

        startup_row = SettingRow(
            _("Start at Login"), _("Launch JuhRadial MX when you log in")
        )
        startup_switch = Gtk.Switch()
        startup_switch.set_active(config.get("app", "start_at_login", default=True))
        startup_switch.connect("state-set", self._on_startup_changed)
        startup_row.set_control(startup_switch)
        app_card.append(startup_row)

        tray_row = SettingRow(_("Show Tray Icon"), _("Display icon in system tray"))
        tray_switch = Gtk.Switch()
        tray_switch.set_active(config.get("app", "show_tray_icon", default=True))
        tray_switch.connect(
            "state-set",
            lambda s, state: config.set("app", "show_tray_icon", state) or False,
        )
        tray_row.set_control(tray_switch)
        app_card.append(tray_row)

        content.append(app_card)

        # Device Information used to live here — moved to the Devices tab
        # where it actually belongs. Settings is for application preferences.

        # Restore defaults — kept as a single flat row at the bottom of the
        # page rather than its own one-row card. The CSS treats danger-btn
        # as the destructive affordance; that's enough chrome on its own.
        reset_row = SettingRow(
            _("Restore Defaults"),
            _("Reset all settings to factory defaults"),
        )
        reset_btn = Gtk.Button(label=_("Reset"))
        reset_btn.add_css_class("danger-btn")
        reset_btn.connect("clicked", self._on_reset_clicked)
        reset_row.set_control(reset_btn)
        reset_row.set_margin_top(16)
        content.append(reset_row)

        # Wrap in Adw.Clamp for responsive centering
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(content)
        self.set_child(clamp)

    def _on_de_changed(self, dropdown, _param):
        """Handle DE selection change - saves preference."""
        idx = dropdown.get_selected()
        if 0 <= idx < len(self._de_keys):
            de_key = self._de_keys[idx]
            config.set("desktop_environment", de_key)
            config.save(show_toast=False)
            logger.info("Desktop environment set to: %s", de_key)

    def _on_apply_de_defaults(self, button):
        """Apply DE-specific default commands to radial menu slices."""
        de_key = get_de_key(config.get("desktop_environment", default="auto"))
        commands = DE_COMMAND_MAP.get(de_key, DE_COMMAND_MAP["generic"])

        slices = config.get("radial_menu", "slices", default=[])
        changed = []
        for slice_data in slices:
            action_id = slice_data.get("action_id", "")
            if action_id in commands:
                new_type, new_cmd = commands[action_id]
                old_cmd = slice_data.get("command", "")
                slice_data["type"] = new_type
                slice_data["command"] = new_cmd
                if old_cmd != new_cmd:
                    changed.append(slice_data.get("label", action_id))

        config.set("radial_menu", "slices", slices)
        config.save(show_toast=False)

        if changed:
            de_label = next(
                (label for key, label in SUPPORTED_DES if key == de_key), de_key
            )
            msg = _("Updated for {}: {}").format(de_label, ", ".join(changed))
        else:
            msg = _("All commands already match selected DE")

        dialog = Adw.AlertDialog(
            heading=_("Desktop Commands Updated"),
            body=msg,
        )
        dialog.add_response("ok", _("OK"))
        dialog.present(self.get_root())

    def _on_theme_changed(self, dropdown, _):
        """Handle theme selection change - applies to both overlay and settings"""
        selected = dropdown.get_selected()
        if 0 <= selected < len(self._theme_keys):
            theme = self._theme_keys[selected]
            config.set("theme", theme)
            config.save(show_toast=False)  # Save immediately so overlay picks it up
            logger.info("Theme changed to: %s", theme)

            # Update the live preview card
            if hasattr(self, "_theme_preview"):
                self._theme_preview.set_theme(theme)

            # Reload CSS for the settings window
            self._reload_theme_css()

            # Restart the overlay (debounced) so rapid selection (e.g. keyboard
            # navigation) coalesces into ONE restart and cannot race two overlay
            # instances into existence.
            if getattr(self, "_overlay_restart_id", None):
                GLib.source_remove(self._overlay_restart_id)
            self._overlay_restart_id = GLib.timeout_add(450, self._restart_overlay)

    def _restart_overlay(self):
        self._overlay_restart_id = None
        import subprocess

        try:
            subprocess.run(
                ["pkill", "-f", "[j]uhradial-overlay.py"],
                capture_output=True,
                timeout=2,
            )
            overlay_path = Path(__file__).parent / "juhradial-overlay.py"
            subprocess.Popen(
                ["python3", str(overlay_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Overlay restarted with new theme")
        except Exception as e:
            logger.error("Could not restart overlay: %s", e)
        return False

    def _reload_theme_css(self):
        """Reload CSS with new theme colors"""
        # Update the module-level COLORS used for CSS generation
        settings_theme.COLORS = settings_theme.load_colors()

        # Keep Adwaita widget palette aligned with selected dark/light theme
        style_manager = Adw.StyleManager.get_default()
        if settings_theme.COLORS.get("is_dark", True):
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)

        # Regenerate CSS with new colors
        new_css = settings_theme._generate_css(settings_theme.COLORS)
        settings_theme.CSS = new_css

        # Reuse the single startup provider (update in place) so repeated
        # theme switches do not stack a new provider each time.
        provider = getattr(settings_theme, "CSS_PROVIDER", None)
        if provider is not None:
            provider.load_from_data(new_css.encode())
        else:
            provider = Gtk.CssProvider()
            provider.load_from_data(new_css.encode())
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            settings_theme.CSS_PROVIDER = provider
        logger.info("Settings CSS reloaded with new theme")

    def _on_startup_changed(self, switch, state):
        """Handle start at login toggle"""
        config.set("app", "start_at_login", state)
        # Create or remove autostart file
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_file = autostart_dir / "juhradial-mx.desktop"

        if state:
            # Create autostart entry
            autostart_dir.mkdir(parents=True, exist_ok=True)
            # Get the script path dynamically
            script_dir = Path(__file__).resolve().parent.parent
            exec_path = script_dir / "scripts" / "juhradial-mx.sh"
            # Fallback to the installed launcher if the dev script isn't present.
            # The launcher installs to /usr/local/bin (not /usr/bin), so resolve
            # it on PATH via shutil.which and fall back to that explicit path;
            # writing /usr/bin/juhradial-mx gave autostart status=127.
            if not exec_path.exists():
                resolved = shutil.which("juhradial-mx")
                exec_path = Path(resolved) if resolved else Path("/usr/local/bin/juhradial-mx")
            desktop_content = f"""[Desktop Entry]
Type=Application
Name=JuhRadial MX
Comment=Radial menu for Logitech MX Master
Exec={exec_path}
Icon=juhradial-mx
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
"""
            autostart_file.write_text(desktop_content, encoding="utf-8")
            logger.info("Created autostart: %s", autostart_file)
        else:
            # Remove autostart entry
            if autostart_file.exists():
                autostart_file.unlink()
                logger.info("Removed autostart: %s", autostart_file)
        return False

    def _on_reset_clicked(self, button):
        """Reset all settings to defaults"""
        config.config = json.loads(json.dumps(ConfigManager.DEFAULT_CONFIG))
        config.save()
        logger.info("Settings reset to defaults")
        # Show notification
        dialog = Adw.AlertDialog(
            heading=_("Settings Reset"),
            body=_(
                "All settings have been restored to defaults. Please restart JuhRadial MX for changes to take effect."
            ),
        )
        dialog.add_response("ok", _("OK"))
        dialog.present(self.get_root())
