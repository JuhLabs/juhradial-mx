#!/usr/bin/env python3
"""
JuhRadial MX - Reusable UI Widgets

NavButton, MouseVisualization, SettingsCard, SettingRow — shared widgets
used across pages and dialogs.

SPDX-License-Identifier: GPL-3.0
"""

import os
import math
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gdk

from i18n import _
from settings_constants import MOUSE_BUTTONS


class NavButton(Gtk.Button):
    """Sidebar navigation button"""

    def __init__(self, item_id, label, icon_name, on_click=None):
        super().__init__()
        self.item_id = item_id
        self.add_css_class('nav-item')

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        box.append(icon)

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
        # Cache for hit regions (computed when img_rect changes)
        self._hit_cache = None
        self._cached_img_rect = None
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
                    self._cached_pixbuf = self._texture_to_pixbuf(self.mouse_image)
                    break
                except Exception as e:
                    print(f"Failed to load image: {e}")

        # Mouse tracking
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        self.add_controller(motion)

        # Click handling
        click = Gtk.GestureClick()
        click.connect('released', self._on_click)
        self.add_controller(click)

    def _compute_hit_regions(self):
        """Pre-compute hit regions for all buttons (called when img_rect changes)"""
        img_x, img_y, img_w, img_h = self.img_rect
        hit_regions = {}

        for btn_id, btn_info in MOUSE_BUTTONS.items():
            btn_x = img_x + btn_info['pos'][0] * img_w
            btn_y = img_y + btn_info['pos'][1] * img_h
            line_from = btn_info.get('line_from', 'left')
            custom_label_y = btn_info.get('label_y', None)

            # Label box dimensions
            label_width = 130
            label_height = 28

            # Calculate label position based on line direction
            if line_from == 'top':
                line_length = 60
                lx = btn_x - label_width / 2
                ly = btn_y - line_length - label_height
            elif line_from == 'l_up':
                line_length = 60
                lx = btn_x - line_length - label_width
                if custom_label_y is not None:
                    ly = img_y + custom_label_y * img_h - label_height / 2
                else:
                    ly = btn_y - label_height / 2
            elif line_from == 'left_short':
                line_length = 25
                lx = btn_x - line_length - label_width
                ly = btn_y - label_height / 2
            else:
                line_length = 60
                lx = btn_x - line_length - label_width
                ly = btn_y - label_height / 2

            hit_regions[btn_id] = {
                'dot_x': btn_x,
                'dot_y': btn_y,
                'label_x': lx,
                'label_y': ly,
                'label_w': label_width,
                'label_h': label_height,
            }

        return hit_regions

    def _on_motion(self, controller, x, y):
        # Throttle motion events to ~30fps (33ms between updates)
        current_time = time.monotonic()
        if current_time - self._last_motion_time < 0.033:
            return
        self._last_motion_time = current_time

        # Rebuild hit cache if img_rect changed
        if self._hit_cache is None or self._cached_img_rect != self.img_rect:
            self._hit_cache = self._compute_hit_regions()
            self._cached_img_rect = self.img_rect

        # Check if hovering over any button region
        old_hovered = self.hovered_button
        self.hovered_button = None

        # Use squared distance comparison (625 = 25^2) to avoid sqrt
        hover_radius_sq = 625

        for btn_id, region in self._hit_cache.items():
            # Check dot (squared distance - no sqrt needed)
            dx = x - region['dot_x']
            dy = y - region['dot_y']
            if dx * dx + dy * dy < hover_radius_sq:
                self.hovered_button = btn_id
                break

            # Check label box
            lx, ly = region['label_x'], region['label_y']
            lw, lh = region['label_w'], region['label_h']
            if lx <= x <= lx + lw and ly <= y <= ly + lh:
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

        # Draw shadow first (offset) - deeper shadow for premium feel
        cr.set_source_rgba(0, 0, 0, 0.4)
        radius = 10
        shadow_offset = 4
        cr.new_path()
        cr.arc(label_x + radius + shadow_offset, label_y + radius + shadow_offset, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius + shadow_offset, label_y + radius + shadow_offset, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius + shadow_offset, label_y + box_height - radius + shadow_offset, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius + shadow_offset, label_y + box_height - radius + shadow_offset, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.fill()

        # Premium glassmorphism background - dark with cyan glow
        if is_hovered:
            # Hover: vibrant cyan gradient
            cr.set_source_rgba(0, 0.83, 1, 0.95)  # #00d4ff - Vibrant cyan
        else:
            # Normal: dark glass with subtle cyan tint
            cr.set_source_rgba(0.1, 0.11, 0.14, 0.92)  # Dark glass matching theme

        cr.new_path()
        cr.arc(label_x + radius, label_y + radius, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + box_height - radius, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius, label_y + box_height - radius, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.fill()

        # Glass border - cyan accent glow
        if is_hovered:
            cr.set_source_rgba(1, 1, 1, 0.5)  # White border on hover
        else:
            cr.set_source_rgba(0, 0.83, 1, 0.35)  # Cyan border glow
        cr.set_line_width(1.5)
        cr.new_path()
        cr.arc(label_x + radius, label_y + radius, radius, math.pi, 1.5 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
        cr.arc(label_x + box_width - radius, label_y + box_height - radius, radius, 0, 0.5 * math.pi)
        cr.arc(label_x + radius, label_y + box_height - radius, radius, 0.5 * math.pi, math.pi)
        cr.close_path()
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

    def _texture_to_pixbuf(self, texture):
        """Convert Gdk.Texture to GdkPixbuf for cairo rendering"""
        try:
            from gi.repository import GdkPixbuf

            # Get texture data as PNG bytes and convert to pixbuf
            data = texture.save_to_png_bytes()
            loader = GdkPixbuf.PixbufLoader.new_with_type('png')
            loader.write(data.get_data())
            loader.close()
            return loader.get_pixbuf()
        except Exception as e:
            print(f"Texture conversion error: {e}")
            return None


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
