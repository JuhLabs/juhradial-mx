#!/usr/bin/env python3
"""
JuhRadial MX - Reusable UI Widgets

NavButton, MouseVisualization, SettingsCard, SettingRow — shared widgets
used across pages and dialogs.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import math
import os
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gdk

from i18n import _
from settings_constants import MOUSE_BUTTONS


def _texture_to_pixbuf(texture):
    """Convert Gdk.Texture to GdkPixbuf for cairo rendering."""
    try:
        from gi.repository import GdkPixbuf
        data = texture.save_to_png_bytes()
        loader = GdkPixbuf.PixbufLoader.new_with_type('png')
        loader.write(data.get_data())
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        logging.debug("_texture_to_pixbuf failed", exc_info=True)
        return None


def _rounded_rect(cr, x, y, w, h, r):
    """Draw a rounded rectangle path on a cairo context."""
    cr.new_path()
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    cr.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    cr.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    cr.close_path()


def _resolve_nav_icon(filename):
    """Resolve a nav icon PNG path (dev or installed)."""
    from pathlib import Path
    candidates = [
        Path(__file__).parent.parent / "assets" / filename,
        Path("/usr/share/juhradial/assets") / filename,
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


class NavButton(Gtk.Button):
    """Sidebar navigation button with themed icon badge"""

    def __init__(self, item_id, label, icon_name, on_click=None):
        super().__init__()
        self.item_id = item_id
        self.add_css_class('nav-item')

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Custom PNG icon replaces the badge entirely;
        # symbolic icons keep the old badge wrapper
        if icon_name.endswith(".png"):
            icon_path = _resolve_nav_icon(icon_name)
            if icon_path:
                icon = Gtk.Image.new_from_file(icon_path)
            else:
                icon = Gtk.Image.new_from_icon_name("image-missing")
            icon.set_pixel_size(48)
            icon.add_css_class('nav-icon-img')
            icon.set_valign(Gtk.Align.CENTER)
            box.append(icon)
        else:
            icon_badge = Gtk.Box()
            icon_badge.add_css_class('nav-icon-badge')
            icon_badge.set_valign(Gtk.Align.CENTER)
            icon_badge.set_halign(Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(18)
            icon.add_css_class('nav-icon')
            icon_badge.append(icon)
            box.append(icon_badge)

        label_widget = Gtk.Label(label=label)
        label_widget.set_halign(Gtk.Align.START)
        box.append(label_widget)

        self.set_child(box)

        if on_click:
            self.connect('clicked', lambda _: on_click(item_id))

    def set_active(self, active):
        if active:
            self.add_css_class('active')
        else:
            self.remove_css_class('active')


class MouseVisualization(Gtk.DrawingArea):
    """Interactive mouse visualization with hoverable button labels"""

    def __init__(self, on_button_click=None):
        super().__init__()
        self.on_button_click = on_button_click
        self.hovered_button = None
        self.mouse_image = None
        # Store image rect for button positioning
        self.img_rect = (0, 0, 600, 500)  # (x_offset, y_offset, width, height)
        # Actual drawn label rects for hit testing (populated during draw)
        self._label_rects = {}
        # Motion throttling
        self._last_motion_time = 0

        self.set_content_width(600)
        self.set_content_height(500)
        self.set_draw_func(self._draw)

        # Load mouse image
        image_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '../assets/devices/logitechmouse.png'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets/devices/logitechmouse.png'),
            '/usr/share/juhradial/assets/devices/logitechmouse.png',
        ]

        self._cached_pixbuf = None  # Cache pixbuf conversion (expensive)

        for path in image_paths:
            if os.path.exists(path):
                try:
                    self.mouse_image = Gdk.Texture.new_from_filename(path)
                    self._cached_pixbuf = _texture_to_pixbuf(self.mouse_image)
                    break
                except Exception as e:
                    logging.warning("Failed to load mouse image: %s", e)

        # Mouse tracking
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        self.add_controller(motion)

        # Click handling
        click = Gtk.GestureClick()
        click.connect('released', self._on_click)
        self.add_controller(click)

    def _on_motion(self, controller, x, y):
        # Throttle motion events to ~30fps (33ms between updates)
        current_time = time.monotonic()
        if current_time - self._last_motion_time < 0.033:
            return
        self._last_motion_time = current_time

        old_hovered = self.hovered_button
        self.hovered_button = None

        # Check actual drawn label rects (populated during _draw_button_label)
        for btn_id, (rx, ry, rw, rh) in self._label_rects.items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self.hovered_button = btn_id
                break

        # Also check dot proximity if no label was hit
        if self.hovered_button is None:
            img_x, img_y, img_w, img_h = self.img_rect
            hover_radius_sq = 625  # 25^2
            for btn_id, btn_info in MOUSE_BUTTONS.items():
                dot_x = img_x + btn_info['pos'][0] * img_w
                dot_y = img_y + btn_info['pos'][1] * img_h
                dx = x - dot_x
                dy = y - dot_y
                if dx * dx + dy * dy < hover_radius_sq:
                    self.hovered_button = btn_id
                    break

        if old_hovered != self.hovered_button:
            self.queue_draw()

    def _on_leave(self, controller):
        if self.hovered_button:
            self.hovered_button = None
            self.queue_draw()

    def _on_click(self, gesture, n_press, x, y):
        if self.hovered_button and self.on_button_click:
            self.on_button_click(self.hovered_button)

    def _draw(self, area, cr, width, height):
        # Draw mouse image centered
        if self.mouse_image:
            img_width = self.mouse_image.get_width()
            img_height = self.mouse_image.get_height()

            # Scale to fit
            scale = min(width * 0.7 / img_width, height * 0.8 / img_height)
            scaled_w = img_width * scale
            scaled_h = img_height * scale

            x_offset = (width - scaled_w) / 2
            y_offset = (height - scaled_h) / 2

            # Store image rect for button positioning
            self.img_rect = (x_offset, y_offset, scaled_w, scaled_h)

            cr.save()
            cr.translate(x_offset, y_offset)
            cr.scale(scale, scale)
            if self._cached_pixbuf:
                Gdk.cairo_set_source_pixbuf(cr, self._cached_pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            # Draw placeholder - store rect for button positioning
            self.img_rect = (width * 0.2, height * 0.1, width * 0.6, height * 0.8)
            cr.set_source_rgba(0.3, 0.3, 0.4, 1)
            cr.rectangle(*self.img_rect)
            cr.fill()

            cr.set_source_rgba(0.8, 0.8, 0.9, 1)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(16)
            cr.move_to(width * 0.35, height * 0.5)
            cr.show_text(_("MX Master 4"))

        # Draw button labels (positioned relative to image rect)
        self._label_rects = {}
        for btn_id, btn_info in MOUSE_BUTTONS.items():
            self._draw_button_label(cr, btn_id, btn_info)

    def _draw_button_label(self, cr, btn_id, btn_info):
        # Position buttons relative to the actual mouse image rect
        img_x, img_y, img_w, img_h = self.img_rect
        x = img_x + btn_info['pos'][0] * img_w
        y = img_y + btn_info['pos'][1] * img_h
        label = btn_info['name']
        is_hovered = (btn_id == self.hovered_button)
        line_from = btn_info.get('line_from', 'left')

        # Measure text
        cr.select_font_face("Sans", 0, 1 if is_hovered else 0)
        cr.set_font_size(11)
        extents = cr.text_extents(label)

        padding_x = 14
        padding_y = 8
        box_width = extents.width + padding_x * 2
        box_height = extents.height + padding_y * 2

        # Calculate label position based on line direction
        custom_label_y = btn_info.get('label_y', None)

        if line_from == 'top':
            # Line comes from above, label above the point
            line_length = 60
            label_x = x - box_width / 2
            label_y = y - line_length - box_height
            line_start_x, line_start_y = x, y - 6
            line_end_x, line_end_y = x, label_y + box_height
        elif line_from == 'l_up':
            # L-shaped line: horizontal left, then vertical up to label
            line_length = 60
            label_x = x - line_length - box_width
            # Use custom label_y if provided, otherwise calculate
            if custom_label_y is not None:
                label_y = img_y + custom_label_y * img_h - box_height / 2
            else:
                label_y = y - box_height / 2
            line_start_x, line_start_y = x - 6, y
            line_mid_x = label_x + box_width + 15  # horizontal end point
            line_end_x, line_end_y = label_x + box_width, label_y + box_height / 2
        elif line_from == 'left_short':
            # Short horizontal line (about 25px)
            line_length = 25
            label_x = x - line_length - box_width
            label_y = y - box_height / 2
            line_start_x, line_start_y = x - 6, y
            line_end_x, line_end_y = label_x + box_width, y
        else:
            # Line comes from left, label to the left of point
            line_length = 60
            label_x = x - line_length - box_width
            label_y = y - box_height / 2
            line_start_x, line_start_y = x - 6, y
            line_end_x, line_end_y = label_x + box_width, y

        # Store actual drawn rect for hit testing (FIX: matches drawn geometry)
        self._label_rects[btn_id] = (label_x, label_y, box_width, box_height)

        # Draw shadow first (offset) - deeper shadow for premium feel
        radius = 10
        shadow_offset = 4
        cr.set_source_rgba(0, 0, 0, 0.4)
        _rounded_rect(cr, label_x + shadow_offset, label_y + shadow_offset,
                       box_width, box_height, radius)
        cr.fill()

        # Premium glassmorphism background - dark with cyan glow
        if is_hovered:
            cr.set_source_rgba(0, 0.83, 1, 0.95)  # #00d4ff - Vibrant cyan
        else:
            cr.set_source_rgba(0.1, 0.11, 0.14, 0.92)  # Dark glass matching theme
        _rounded_rect(cr, label_x, label_y, box_width, box_height, radius)
        cr.fill()

        # Glass border - cyan accent glow
        if is_hovered:
            cr.set_source_rgba(1, 1, 1, 0.5)  # White border on hover
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.35)  # Cyan border glow
        cr.set_line_width(1.5)
        _rounded_rect(cr, label_x, label_y, box_width, box_height, radius)
        cr.stroke()

        # Draw text
        if is_hovered:
            cr.set_source_rgba(0.04, 0.05, 0.06, 1)  # Dark text on cyan bg
        else:
            cr.set_source_rgba(0.94, 0.96, 0.97, 1)  # Bright white text
        cr.move_to(label_x + padding_x, label_y + padding_y + extents.height)
        cr.show_text(label)

        # Draw connector line - cyan accent
        if is_hovered:
            cr.set_source_rgba(0, 0.83, 1, 0.9)  # Bright cyan line
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.5)  # Subtle cyan line
        cr.set_line_width(2)
        if line_from == 'l_up':
            # L-shaped: horizontal then vertical up
            cr.move_to(line_start_x, line_start_y)
            cr.line_to(line_mid_x, line_start_y)  # horizontal segment
            cr.line_to(line_mid_x, line_end_y)    # vertical segment up
            cr.line_to(line_end_x, line_end_y)    # short horizontal to label
        else:
            cr.move_to(line_start_x, line_start_y)
            cr.line_to(line_end_x, line_end_y)
        cr.stroke()

        # Draw connector dot on the button - cyan glowing dot
        if is_hovered:
            # Glowing dot on hover
            cr.set_source_rgba(0, 0.83, 1, 0.4)  # Outer glow
            cr.arc(x, y, 8, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0, 0.83, 1, 1)  # Bright cyan dot
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.8)  # Cyan dot
        cr.arc(x, y, 5, 0, 2 * math.pi)
        cr.fill()

        # Dot border - white highlight
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.set_line_width(1.5)
        cr.arc(x, y, 5, 0, 2 * math.pi)
        cr.stroke()

class GenericMouseVisualization(Gtk.DrawingArea):
    """Mouse image visualization for generic (non-Logitech) mice.

    Shows genericmouse.png with labeled button positions and connector lines.
    """

    # Generic mouse button positions (relative to image rect)
    # Tuned for the 3/4-perspective photo (genericmouse.png)
    GENERIC_BUTTONS = {
        "left_click": {
            "name": "Left Click",
            "pos": (0.38, 0.22),
            "line_from": "top",
        },
        "right_click": {
            "name": "Right Click",
            "pos": (0.62, 0.22),
            "line_from": "top",
        },
        "middle_click": {
            "name": "Middle / Scroll",
            "pos": (0.50, 0.30),
            "line_from": "left",
        },
        "side_btn": {
            "name": "Side Button",
            "pos": (0.18, 0.55),
            "line_from": "left",
        },
        "extra_btn": {
            "name": "Extra Button",
            "pos": (0.18, 0.45),
            "line_from": "left",
        },
    }

    def __init__(self, on_button_click=None):
        super().__init__()
        self.mouse_image = None
        self._cached_pixbuf = None
        self._label_rects = {}  # btn_id -> (x, y, w, h) for hit testing
        self._hovered_btn = None
        self._on_button_click = on_button_click
        self._last_motion_time = 0

        self.set_content_width(500)
        self.set_content_height(450)
        self.set_draw_func(self._draw)

        # Enable mouse events for hover/click
        motion_ctrl = Gtk.EventControllerMotion()
        motion_ctrl.connect("motion", self._on_motion)
        motion_ctrl.connect("leave", self._on_leave)
        self.add_controller(motion_ctrl)

        click_ctrl = Gtk.GestureClick()
        click_ctrl.connect("pressed", self._on_click)
        self.add_controller(click_ctrl)

        self.set_cursor_from_name("default")

        image_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '../assets/devices/genericmouse.png'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'assets/devices/genericmouse.png'),
            '/usr/share/juhradial/assets/devices/genericmouse.png',
        ]
        for path in image_paths:
            if os.path.exists(path):
                try:
                    self.mouse_image = Gdk.Texture.new_from_filename(path)
                    self._cached_pixbuf = _texture_to_pixbuf(self.mouse_image)
                except Exception as e:
                    logging.warning("Failed to load generic mouse image: %s", e)
                break

    def _draw(self, area, cr, width, height):
        if self.mouse_image:
            img_w = self.mouse_image.get_width()
            img_h = self.mouse_image.get_height()
            scale = min(width * 0.65 / img_w, height * 0.75 / img_h)
            sw = img_w * scale
            sh = img_h * scale
            x_off = (width - sw) / 2
            y_off = (height - sh) / 2
            img_rect = (x_off, y_off, sw, sh)

            cr.save()
            cr.translate(x_off, y_off)
            cr.scale(scale, scale)
            if self._cached_pixbuf:
                Gdk.cairo_set_source_pixbuf(cr, self._cached_pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            img_rect = (width * 0.2, height * 0.1, width * 0.6, height * 0.8)
            cr.set_source_rgba(0.3, 0.3, 0.4, 1)
            cr.rectangle(*img_rect)
            cr.fill()
            cr.set_source_rgba(0.8, 0.8, 0.9, 1)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(16)
            cr.move_to(width * 0.32, height * 0.5)
            cr.show_text(_("Generic Mouse"))

        self._label_rects = {}
        for btn_id, btn_info in self.GENERIC_BUTTONS.items():
            self._draw_label(cr, img_rect, btn_id, btn_info)

    def _on_motion(self, ctrl, x, y):
        """Track hover over button labels."""
        now = time.monotonic()
        if now - self._last_motion_time < 0.033:
            return
        self._last_motion_time = now

        hit = None
        for btn_id, (rx, ry, rw, rh) in self._label_rects.items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                hit = btn_id
                break
        if hit != self._hovered_btn:
            self._hovered_btn = hit
            self.set_cursor_from_name("pointer" if hit else "default")
            self.queue_draw()

    def _on_leave(self, ctrl):
        if self._hovered_btn:
            self._hovered_btn = None
            self.set_cursor_from_name("default")
            self.queue_draw()

    def _on_click(self, gesture, n_press, x, y):
        """Handle click on a button label."""
        for btn_id, (rx, ry, rw, rh) in self._label_rects.items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                if self._on_button_click:
                    self._on_button_click(btn_id, self.GENERIC_BUTTONS[btn_id])
                return

    def _draw_label(self, cr, img_rect, btn_id, btn_info):
        ix, iy, iw, ih = img_rect
        bx = ix + btn_info['pos'][0] * iw
        by = iy + btn_info['pos'][1] * ih
        label = btn_info['name']
        line_from = btn_info.get('line_from', 'left')
        is_hovered = btn_id == self._hovered_btn

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(11)
        ext = cr.text_extents(label)
        px, py = 12, 7
        bw = ext.width + px * 2
        bh = ext.height + py * 2

        if line_from == 'top':
            lx = bx - bw / 2
            ly = by - 50 - bh
            lsx, lsy = bx, by - 6
            lex, ley = bx, ly + bh
        else:
            lx = bx - 50 - bw
            ly = by - bh / 2
            lsx, lsy = bx - 6, by
            lex, ley = lx + bw, by

        # Store rect for hit testing
        self._label_rects[btn_id] = (lx, ly, bw, bh)

        # Shadow
        cr.set_source_rgba(0, 0, 0, 0.35)
        r = 8
        self._rounded_rect(cr, lx + 3, ly + 3, bw, bh, r)
        cr.fill()

        # Background (brighter on hover)
        if is_hovered:
            cr.set_source_rgba(0.15, 0.18, 0.22, 0.95)
        else:
            cr.set_source_rgba(0.1, 0.11, 0.14, 0.9)
        self._rounded_rect(cr, lx, ly, bw, bh, r)
        cr.fill()

        # Border (brighter on hover)
        accent_a = 0.6 if is_hovered else 0.3
        cr.set_source_rgba(0, 0.83, 1, accent_a)
        cr.set_line_width(1.5 if is_hovered else 1.2)
        self._rounded_rect(cr, lx, ly, bw, bh, r)
        cr.stroke()

        # Text
        cr.set_source_rgba(0.94, 0.96, 0.97, 1)
        cr.move_to(lx + px, ly + py + ext.height)
        cr.show_text(label)

        # Line (brighter on hover)
        line_a = 0.7 if is_hovered else 0.45
        cr.set_source_rgba(0, 0.83, 1, line_a)
        cr.set_line_width(2 if is_hovered else 1.5)
        cr.move_to(lsx, lsy)
        cr.line_to(lex, ley)
        cr.stroke()

        # Dot
        dot_a = 1.0 if is_hovered else 0.8
        cr.set_source_rgba(0, 0.83, 1, dot_a)
        cr.arc(bx, by, 5 if is_hovered else 4, 0, 2 * math.pi)
        cr.fill()

    def _rounded_rect(self, cr, x, y, w, h, r):
        _rounded_rect(cr, x, y, w, h, r)


class PageHeader(Gtk.Box):
    """Consistent page header with icon, title, and subtitle."""

    def __init__(self, icon_name, title, subtitle):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_halign(Gtk.Align.CENTER)
        self.set_margin_top(12)
        self.set_margin_bottom(16)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(48)
        icon.add_css_class('page-header-icon')
        self.append(icon)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class('title-1')
        self.append(title_label)

        subtitle_label = Gtk.Label(label=subtitle)
        subtitle_label.add_css_class('dim-label')
        self.append(subtitle_label)


class SettingsCard(Gtk.Box):
    """A styled settings card"""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class('settings-card')

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class('card-title')
        self.append(title_label)


class SettingRow(Gtk.Box):
    """A row in settings with label and control"""

    def __init__(self, label, description=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class('setting-row')

        # Left side: label and description
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)

        label_widget = Gtk.Label(label=label)
        label_widget.set_halign(Gtk.Align.START)
        label_widget.add_css_class('setting-label')
        text_box.append(label_widget)

        if description:
            desc_widget = Gtk.Label(label=description)
            desc_widget.set_halign(Gtk.Align.START)
            desc_widget.add_css_class('setting-value')
            text_box.append(desc_widget)

        self.append(text_box)

        # Control container (for switch, scale, etc)
        self.control_box = Gtk.Box()
        self.control_box.set_valign(Gtk.Align.CENTER)
        self.append(self.control_box)

    def set_control(self, widget):
        self.control_box.append(widget)


class InfoCard(Gtk.Box):
    """A secondary/informational settings card with quieter styling."""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class('settings-card')
        self.add_css_class('info-card')

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class('card-title')
        self.append(title_label)
