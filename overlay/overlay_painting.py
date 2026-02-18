"""
JuhRadial MX - Overlay Painting Mixin

All drawing/rendering methods for the radial menu, extracted as a mixin
class to keep the main overlay file focused on logic.

IMPORTANT: Mutable globals (COLORS, ACTIONS, RADIAL_IMAGE, RADIAL_PARAMS,
AI_ICONS) are accessed via the overlay_actions module attribute
(e.g. overlay_actions.COLORS) so that reassignment in on_show is visible.

SPDX-License-Identifier: GPL-3.0
"""

import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QFontMetrics,
    QPainterPath,
)

import overlay_actions
from overlay_constants import (
    MENU_RADIUS,
    CENTER_ZONE_RADIUS,
    ICON_ZONE_RADIUS,
    WINDOW_SIZE,
)
from i18n import _


class RadialMenuPaintingMixin:
    """Mixin providing all paint/draw methods for RadialMenu."""

    def paintEvent(self, event):
        # During COSMIC XWayland cursor sync, paint a near-invisible fill
        # instead of the radial menu.  Alpha 2/255 ≈ 0.8% opacity black —
        # invisible to the eye but ensures XWayland commits the surface so
        # COSMIC routes pointer events through the window.
        if getattr(self, '_paint_suppressed', False):
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0, 2))
            p.end()
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = WINDOW_SIZE / 2
        cy = WINDOW_SIZE / 2

        if overlay_actions.RADIAL_IMAGE is not None:
            # === 3D Image Mode ===
            # Draw the pre-rendered 3D radial wheel image centered
            img_x = cx - overlay_actions.RADIAL_IMAGE.width() / 2
            img_y = cy - overlay_actions.RADIAL_IMAGE.height() / 2
            p.drawPixmap(int(img_x), int(img_y), overlay_actions.RADIAL_IMAGE)

            # Draw highlight on hovered slice (translucent overlay)
            if self.highlighted_slice >= 0:
                self._draw_3d_slice_highlight(p, cx, cy, self.highlighted_slice)

            # Draw icons floating on the 3D image
            for i in range(8):
                self._draw_3d_icon(p, cx, cy, i)
        else:
            # === Vector Mode (original) ===
            # Shadow
            shadow_color = QColor(0, 0, 0, 100)
            p.setBrush(QBrush(shadow_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx + 4, cy + 6), MENU_RADIUS, MENU_RADIUS)

            # Main background
            base_color = QColor(overlay_actions.COLORS["base"])
            base_color.setAlpha(235)
            p.setBrush(QBrush(base_color))
            p.drawEllipse(QPointF(cx, cy), MENU_RADIUS, MENU_RADIUS)

            # Border
            border_color = QColor(overlay_actions.COLORS["surface2"])
            border_color.setAlpha(150)
            p.setPen(QPen(border_color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), MENU_RADIUS, MENU_RADIUS)

            # Draw slices
            for i in range(8):
                self._draw_slice(p, cx, cy, i)

        # Draw submenu if active (same for both modes)
        if self.submenu_active and self.submenu_slice >= 0:
            self._draw_submenu(p, cx, cy)

        # Center zone (same for both modes)
        self._draw_center(p, cx, cy)

        p.end()

    def _draw_3d_slice_highlight(self, p, cx, cy, index):
        """Draw a translucent highlight on the hovered slice for 3D mode."""
        params = overlay_actions.RADIAL_PARAMS or {}
        outer_r = params.get("ring_outer", MENU_RADIUS - 6)
        inner_r = params.get("ring_inner", CENTER_ZONE_RADIUS + 6)
        fill_rgba = params.get("highlight_fill", (255, 255, 255, 45))
        border_rgba = params.get("highlight_border", (255, 255, 255, 90))

        start_angle = index * 45 - 22.5 - 90

        path = QPainterPath()
        inner_start_x = cx + inner_r * math.cos(math.radians(start_angle))
        inner_start_y = cy + inner_r * math.sin(math.radians(start_angle))
        path.moveTo(inner_start_x, inner_start_y)

        outer_start_x = cx + outer_r * math.cos(math.radians(start_angle))
        outer_start_y = cy + outer_r * math.sin(math.radians(start_angle))
        path.lineTo(outer_start_x, outer_start_y)

        outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
        path.arcTo(outer_rect, -start_angle, -45)

        end_angle = start_angle + 45
        inner_end_x = cx + inner_r * math.cos(math.radians(end_angle))
        inner_end_y = cy + inner_r * math.sin(math.radians(end_angle))
        path.lineTo(inner_end_x, inner_end_y)

        inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
        path.arcTo(inner_rect, -end_angle, 45)
        path.closeSubpath()

        p.setBrush(QBrush(QColor(*fill_rgba)))
        p.setPen(QPen(QColor(*border_rgba), 1.5))
        p.drawPath(path)

    def _draw_badge_shape(self, p, x, y, shape, params, angle_deg, size_extra=0):
        """Draw a badge shape centered at (x,y), oriented radially outward."""
        scale = params.get("icon_scale", 1.0)
        if shape == "circle":
            r = params.get("icon_bg_radius", 20) * scale + size_extra
            p.drawEllipse(QPointF(x, y), r, r)
        elif shape == "rounded_rect":
            w = params.get("icon_bg_width", 40) * scale + size_extra * 2
            h = params.get("icon_bg_height", 40) * scale + size_extra * 2
            cr = params.get("icon_bg_corner_radius", 6) * scale
            p.save()
            p.translate(x, y)
            p.rotate(angle_deg + 90)
            p.drawRoundedRect(QRectF(-w / 2, -h / 2, w, h), cr, cr)
            p.restore()
        elif shape == "diamond":
            w = params.get("icon_bg_width", 34) * scale + size_extra * 2
            h = params.get("icon_bg_height", 38) * scale + size_extra * 2
            p.save()
            p.translate(x, y)
            p.rotate(angle_deg + 90)
            path = QPainterPath()
            path.moveTo(0, -h / 2)
            path.lineTo(w / 2, 0)
            path.lineTo(0, h / 2)
            path.lineTo(-w / 2, 0)
            path.closeSubpath()
            p.drawPath(path)
            p.restore()
        elif shape == "hexagon":
            r = params.get("icon_bg_radius", 20) * scale + size_extra
            p.save()
            p.translate(x, y)
            p.rotate(angle_deg + 90)
            path = QPainterPath()
            for i in range(6):
                a = math.radians(i * 60 - 90)
                hx = r * math.cos(a)
                hy = r * math.sin(a)
                if i == 0:
                    path.moveTo(hx, hy)
                else:
                    path.lineTo(hx, hy)
            path.closeSubpath()
            p.drawPath(path)
            p.restore()

    def _draw_3d_icon(self, p, cx, cy, index):
        """Draw an icon on the 3D radial image with per-theme badge shape."""
        params = overlay_actions.RADIAL_PARAMS or {}
        icon_radius = params.get("icon_radius", ICON_ZONE_RADIUS)
        icon_rgb = params.get("icon_color", (255, 255, 255))
        shadow_alpha = params.get("icon_shadow_alpha", 100)
        glow_rgba = params.get("hover_glow", (255, 255, 255, 55))
        scale = params.get("icon_scale", 1.0)
        bold = params.get("icon_bold", 1.2)

        # Badge params
        bg_rgba = params.get("icon_bg")
        bg_border_rgba = params.get("icon_bg_border")
        bg_shape = params.get("icon_bg_shape", "circle")
        border_w = params.get("icon_bg_border_width", 1.5)

        is_highlighted = index == self.highlighted_slice
        action = overlay_actions.ACTIONS[index]

        angle_deg = index * 45 - 90
        icon_angle = math.radians(angle_deg)
        icon_x = cx + icon_radius * math.cos(icon_angle)
        icon_y = cy + icon_radius * math.sin(icon_angle)

        # Drop shadow (skip if alpha is 0)
        if shadow_alpha > 0:
            p.setBrush(QBrush(QColor(0, 0, 0, shadow_alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            if bg_rgba:
                self._draw_badge_shape(
                    p,
                    icon_x + 1.5,
                    icon_y + 2.5,
                    bg_shape,
                    params,
                    angle_deg,
                    size_extra=2,
                )
            else:
                p.drawEllipse(
                    QPointF(icon_x + 1.5, icon_y + 2.5), 22 * scale, 22 * scale
                )

        # Background badge
        if bg_rgba:
            if is_highlighted:
                bg_color = QColor(
                    bg_rgba[0], bg_rgba[1], bg_rgba[2], min(255, bg_rgba[3] + 40)
                )
            else:
                bg_color = QColor(*bg_rgba)
            p.setBrush(QBrush(bg_color))
            if bg_border_rgba:
                p.setPen(QPen(QColor(*bg_border_rgba), border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            self._draw_badge_shape(p, icon_x, icon_y, bg_shape, params, angle_deg)

        # Hover glow outline (outside the badge)
        if is_highlighted:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(*glow_rgba), 3 * scale))
            if bg_rgba:
                self._draw_badge_shape(
                    p, icon_x, icon_y, bg_shape, params, angle_deg, size_extra=4
                )
            else:
                p.drawEllipse(QPointF(icon_x, icon_y), 26 * scale, 26 * scale)

        # Draw icon - brighten and scale up on hover for better feedback
        if is_highlighted:
            icon_color = QColor(
                min(255, icon_rgb[0] + 40),
                min(255, icon_rgb[1] + 40),
                min(255, icon_rgb[2] + 40),
            )
            hover_bold = bold * 1.12
        else:
            icon_color = QColor(*icon_rgb)
            hover_bold = bold
        icon_size = 26 * 0.65 * scale
        p.save()
        p.translate(icon_x, icon_y)
        p.scale(hover_bold, hover_bold)
        self._draw_icon(p, 0, 0, action[4], icon_size, icon_color)
        p.restore()

    def _draw_slice(self, p, cx, cy, index):
        is_highlighted = index == self.highlighted_slice
        action = overlay_actions.ACTIONS[index]

        start_angle = index * 45 - 22.5 - 90
        outer_r = MENU_RADIUS - 6
        inner_r = CENTER_ZONE_RADIUS + 6

        # Create slice path
        path = QPainterPath()
        # Start at inner arc
        inner_start_x = cx + inner_r * math.cos(math.radians(start_angle))
        inner_start_y = cy + inner_r * math.sin(math.radians(start_angle))
        path.moveTo(inner_start_x, inner_start_y)

        # Line to outer arc start
        outer_start_x = cx + outer_r * math.cos(math.radians(start_angle))
        outer_start_y = cy + outer_r * math.sin(math.radians(start_angle))
        path.lineTo(outer_start_x, outer_start_y)

        # Outer arc
        outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
        path.arcTo(outer_rect, -start_angle, -45)

        # Line to inner arc end
        end_angle = start_angle + 45
        inner_end_x = cx + inner_r * math.cos(math.radians(end_angle))
        inner_end_y = cy + inner_r * math.sin(math.radians(end_angle))
        path.lineTo(inner_end_x, inner_end_y)

        # Inner arc back
        inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
        path.arcTo(inner_rect, -end_angle, 45)

        path.closeSubpath()

        # Fill slice - neutral hover (no color, just brightness)
        if is_highlighted:
            fill = QColor(255, 255, 255)  # White overlay for hover
            fill.setAlpha(45)
        else:
            fill = overlay_actions.COLORS["surface0"]
            fill.setAlpha(80)
        p.setBrush(QBrush(fill))

        # Slice border - subtle, neutral
        if is_highlighted:
            stroke = QColor(255, 255, 255)
            stroke.setAlpha(120)
        else:
            stroke = overlay_actions.COLORS["surface2"]
            stroke.setAlpha(60)
        p.setPen(QPen(stroke, 1.5 if is_highlighted else 1))

        p.drawPath(path)

        # Icon position (center of slice)
        icon_angle = math.radians(index * 45 - 90)
        icon_x = cx + ICON_ZONE_RADIUS * math.cos(icon_angle)
        icon_y = cy + ICON_ZONE_RADIUS * math.sin(icon_angle)

        # Icon circle background - larger, neutral colors
        icon_radius = 26
        if is_highlighted:
            icon_bg = overlay_actions.COLORS["surface2"]
            icon_bg.setAlpha(255)
            # Add subtle glow ring
            glow = QColor(255, 255, 255)
            glow.setAlpha(40)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 3))
            p.drawEllipse(QPointF(icon_x, icon_y), icon_radius + 2, icon_radius + 2)
        else:
            icon_bg = overlay_actions.COLORS["surface1"]
            icon_bg.setAlpha(230)
        p.setBrush(QBrush(icon_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(icon_x, icon_y), icon_radius, icon_radius)

        # Draw icon - brighter on hover
        if is_highlighted:
            icon_color = overlay_actions.COLORS["text"]
        else:
            icon_color = overlay_actions.COLORS["subtext1"]
        self._draw_icon(p, icon_x, icon_y, action[4], icon_radius * 0.65, icon_color)

    def _draw_icon(self, p, cx, cy, icon_type, size, color):
        # Thicker strokes for better visibility
        p.setPen(QPen(color, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if icon_type == "play_pause":
            # Play triangle - larger and filled
            s = size * 0.55
            path = QPainterPath()
            path.moveTo(cx - s * 0.35, cy - s)
            path.lineTo(cx - s * 0.35, cy + s)
            path.lineTo(cx + s * 0.7, cy)
            path.closeSubpath()
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)

        elif icon_type == "note":
            # Notepad with lines
            w, h = size * 0.65, size * 0.85
            p.setPen(QPen(color, 2))
            p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), 2, 2)
            for i in range(3):
                y = cy - h / 4 + i * size * 0.22
                p.drawLine(QPointF(cx - w / 3, y), QPointF(cx + w / 3, y))

        elif icon_type == "lock":
            # Padlock
            w, h = size * 0.55, size * 0.45
            p.setPen(QPen(color, 2.5))
            p.drawRoundedRect(QRectF(cx - w / 2, cy, w, h), 3, 3)
            # Shackle
            path = QPainterPath()
            path.arcMoveTo(QRectF(cx - w * 0.35, cy - w * 0.5, w * 0.7, w * 0.7), 0)
            path.arcTo(QRectF(cx - w * 0.35, cy - w * 0.5, w * 0.7, w * 0.7), 0, 180)
            p.drawPath(path)

        elif icon_type == "settings":
            # Gear icon - improved
            p.setPen(QPen(color, 2))
            p.drawEllipse(QPointF(cx, cy), size * 0.18, size * 0.18)
            for i in range(6):
                angle = i * math.pi / 3
                inner, outer = size * 0.28, size * 0.45
                x1 = cx + inner * math.cos(angle)
                y1 = cy + inner * math.sin(angle)
                x2 = cx + outer * math.cos(angle)
                y2 = cy + outer * math.sin(angle)
                p.setPen(QPen(color, 3))
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        elif icon_type == "screenshot":
            # Camera/screenshot corners - bolder
            s, corner = size * 0.42, size * 0.18
            p.setPen(QPen(color, 2.5))
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                p.drawLine(
                    QPointF(cx + dx * s, cy + dy * (s - corner)),
                    QPointF(cx + dx * s, cy + dy * s),
                )
                p.drawLine(
                    QPointF(cx + dx * s, cy + dy * s),
                    QPointF(cx + dx * (s - corner), cy + dy * s),
                )
            # Center dot
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), size * 0.12, size * 0.12)

        elif icon_type == "emoji":
            # Smiley face
            p.setPen(QPen(color, 2))
            p.drawEllipse(QPointF(cx, cy), size * 0.45, size * 0.45)
            # Eyes
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(
                QPointF(cx - size * 0.16, cy - size * 0.12), size * 0.055, size * 0.055
            )
            p.drawEllipse(
                QPointF(cx + size * 0.16, cy - size * 0.12), size * 0.055, size * 0.055
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Smile arc - smaller and centered
            p.setPen(QPen(color, 1.8))
            path = QPainterPath()
            path.arcMoveTo(
                QRectF(cx - size * 0.15, cy - size * 0.02, size * 0.30, size * 0.22),
                210,
            )
            path.arcTo(
                QRectF(cx - size * 0.15, cy - size * 0.02, size * 0.30, size * 0.22),
                210,
                120,
            )
            p.drawPath(path)

        elif icon_type == "folder":
            # Folder icon - cleaner
            w, h = size * 0.65, size * 0.5
            tab_w = w * 0.35
            p.setPen(QPen(color, 2))
            path = QPainterPath()
            path.moveTo(cx - w / 2, cy - h / 2 + h * 0.25)
            path.lineTo(cx - w / 2, cy + h / 2)
            path.lineTo(cx + w / 2, cy + h / 2)
            path.lineTo(cx + w / 2, cy - h / 2 + h * 0.25)
            path.lineTo(cx - w / 2 + tab_w + h * 0.1, cy - h / 2 + h * 0.25)
            path.lineTo(cx - w / 2 + tab_w, cy - h / 2)
            path.lineTo(cx - w / 2, cy - h / 2)
            path.closeSubpath()
            p.drawPath(path)

        elif icon_type == "ai":
            # Sparkle - larger size for better visibility
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            s = size * 0.55  # Increased from 0.35 for bigger icon
            path = QPainterPath()
            path.moveTo(cx, cy - s)
            path.cubicTo(
                cx + s * 0.12, cy - s * 0.12, cx + s * 0.12, cy - s * 0.12, cx + s, cy
            )
            path.cubicTo(
                cx + s * 0.12, cy + s * 0.12, cx + s * 0.12, cy + s * 0.12, cx, cy + s
            )
            path.cubicTo(
                cx - s * 0.12, cy + s * 0.12, cx - s * 0.12, cy + s * 0.12, cx - s, cy
            )
            path.cubicTo(
                cx - s * 0.12, cy - s * 0.12, cx - s * 0.12, cy - s * 0.12, cx, cy - s
            )
            p.drawPath(path)
            # Small sparkle - also slightly larger
            s2 = size * 0.18  # Increased from 0.12
            sx, sy = cx + size * 0.38, cy - size * 0.32  # Moved outward a bit
            path2 = QPainterPath()
            path2.moveTo(sx, sy - s2)
            path2.cubicTo(
                sx + s2 * 0.1, sy - s2 * 0.1, sx + s2 * 0.1, sy - s2 * 0.1, sx + s2, sy
            )
            path2.cubicTo(
                sx + s2 * 0.1, sy + s2 * 0.1, sx + s2 * 0.1, sy + s2 * 0.1, sx, sy + s2
            )
            path2.cubicTo(
                sx - s2 * 0.1, sy + s2 * 0.1, sx - s2 * 0.1, sy + s2 * 0.1, sx - s2, sy
            )
            path2.cubicTo(
                sx - s2 * 0.1, sy - s2 * 0.1, sx - s2 * 0.1, sy - s2 * 0.1, sx, sy - s2
            )
            p.drawPath(path2)

        # Submenu item icons
        elif icon_type == "claude":
            # Claude sparkle/star icon
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            s = size * 0.45
            path = QPainterPath()
            path.moveTo(cx, cy - s)
            path.cubicTo(
                cx + s * 0.15, cy - s * 0.15, cx + s * 0.15, cy - s * 0.15, cx + s, cy
            )
            path.cubicTo(
                cx + s * 0.15, cy + s * 0.15, cx + s * 0.15, cy + s * 0.15, cx, cy + s
            )
            path.cubicTo(
                cx - s * 0.15, cy + s * 0.15, cx - s * 0.15, cy + s * 0.15, cx - s, cy
            )
            path.cubicTo(
                cx - s * 0.15, cy - s * 0.15, cx - s * 0.15, cy - s * 0.15, cx, cy - s
            )
            p.drawPath(path)

        elif icon_type == "chatgpt":
            # ChatGPT circular logo
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), size * 0.35, size * 0.35)
            # Inner pattern
            p.drawEllipse(QPointF(cx, cy), size * 0.15, size * 0.15)

        elif icon_type == "gemini":
            # Gemini twin stars
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            for offset in [-size * 0.18, size * 0.18]:
                s = size * 0.22
                scx = cx + offset
                path = QPainterPath()
                path.moveTo(scx, cy - s)
                path.lineTo(scx + s * 0.3, cy)
                path.lineTo(scx, cy + s)
                path.lineTo(scx - s * 0.3, cy)
                path.closeSubpath()
                p.drawPath(path)

        elif icon_type == "perplexity":
            # Perplexity search/question
            p.setPen(QPen(color, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Magnifying glass
            p.drawEllipse(
                QPointF(cx - size * 0.08, cy - size * 0.08), size * 0.25, size * 0.25
            )
            p.drawLine(
                QPointF(cx + size * 0.1, cy + size * 0.1),
                QPointF(cx + size * 0.3, cy + size * 0.3),
            )

        elif icon_type == "easy_switch":
            # Easy-Switch icon - wireless/connection symbol
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Three curved lines (signal arcs)
            for i in range(3):
                arc_size = size * (0.2 + i * 0.15)
                arc_rect = QRectF(
                    cx - arc_size, cy - arc_size, arc_size * 2, arc_size * 2
                )
                p.drawArc(arc_rect, 45 * 16, 90 * 16)
            # Center dot
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), size * 0.1, size * 0.1)

        elif icon_type in ("host1", "host2", "host3"):
            # Host icons - numbered circles for easy identification
            host_num = icon_type[-1]  # Get "1", "2", or "3"
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), size * 0.4, size * 0.4)
            # Draw number
            font = QFont("Sans", int(size * 0.45))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QPen(color))
            text_rect = QRectF(cx - size * 0.3, cy - size * 0.3, size * 0.6, size * 0.6)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, host_num)

    def _draw_submenu(self, p, cx, cy):
        """Draw submenu items when active."""
        submenu = overlay_actions.ACTIONS[self.submenu_slice][5]
        if not submenu:
            return

        # Calculate parent slice angle
        parent_angle = self.submenu_slice * 45 - 90

        # Submenu items positioned in an arc beyond the main menu
        SUBMENU_RADIUS = MENU_RADIUS + 45
        SUBITEM_RADIUS = 24  # Size of each subitem circle

        num_items = len(submenu)
        spread = 18  # Degrees between items

        for i, item in enumerate(submenu):
            is_highlighted = i == self.highlighted_subitem

            # Calculate position
            offset = (i - (num_items - 1) / 2) * spread
            item_angle = math.radians(parent_angle + offset)
            item_x = cx + SUBMENU_RADIUS * math.cos(item_angle)
            item_y = cy + SUBMENU_RADIUS * math.sin(item_angle)

            # Shadow for subitem
            shadow = QColor(0, 0, 0, 80)
            p.setBrush(QBrush(shadow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(
                QPointF(item_x + 2, item_y + 3), SUBITEM_RADIUS, SUBITEM_RADIUS
            )

            # Background
            if is_highlighted:
                bg = overlay_actions.COLORS["surface2"]
                bg.setAlpha(255)
                # Glow ring
                glow = QColor(255, 255, 255, 60)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(glow, 3))
                p.drawEllipse(
                    QPointF(item_x, item_y), SUBITEM_RADIUS + 3, SUBITEM_RADIUS + 3
                )
            else:
                bg = overlay_actions.COLORS["surface1"]
                bg.setAlpha(240)

            p.setBrush(QBrush(bg))
            border = (
                overlay_actions.COLORS["surface2"] if not is_highlighted else QColor(255, 255, 255, 150)
            )
            p.setPen(QPen(border, 1.5))
            p.drawEllipse(QPointF(item_x, item_y), SUBITEM_RADIUS, SUBITEM_RADIUS)

            # Icon - use SVG if available, fallback to drawn icon
            icon_name = item[3]  # e.g., "claude", "chatgpt", etc.
            if icon_name in overlay_actions.AI_ICONS:
                # Render SVG icon
                icon_size = SUBITEM_RADIUS * 1.4  # Size of icon
                icon_rect = QRectF(
                    item_x - icon_size / 2, item_y - icon_size / 2, icon_size, icon_size
                )
                overlay_actions.AI_ICONS[icon_name].render(p, icon_rect)
            else:
                # Fallback to drawn icon
                icon_color = overlay_actions.COLORS["text"] if is_highlighted else overlay_actions.COLORS["subtext1"]
                self._draw_icon(
                    p, item_x, item_y, icon_name, SUBITEM_RADIUS * 0.7, icon_color
                )

    def _draw_center(self, p, cx, cy):
        params = overlay_actions.RADIAL_PARAMS or {}
        center_bg = params.get("center_bg")
        center_radius = self._get_center_radius()

        if center_bg:
            # 3D themed center zone
            p.setBrush(QBrush(QColor(*center_bg)))
            border_rgba = params.get("center_border", (150, 150, 150, 150))
            border_w = params.get("center_border_width", 2.0)
            p.setPen(QPen(QColor(*border_rgba), border_w))
            p.drawEllipse(QPointF(cx, cy), center_radius, center_radius)
            text_rgb = params.get("center_text_color", (200, 200, 200))
            text_color = QColor(*text_rgb)
        else:
            # Original vector mode center
            base = QColor(overlay_actions.COLORS["base"])
            base.setAlpha(247)
            p.setBrush(QBrush(base))
            border = QColor(overlay_actions.COLORS["surface2"])
            border.setAlpha(150)
            p.setPen(QPen(border, 2))
            p.drawEllipse(QPointF(cx, cy), center_radius, center_radius)
            text_color = QColor(overlay_actions.COLORS["subtext1"])

        # Label text - show submenu item name if hovering one
        if self.submenu_active and self.highlighted_subitem >= 0:
            submenu = overlay_actions.ACTIONS[self.submenu_slice][5]
            text = submenu[self.highlighted_subitem][0] if submenu else "AI"
        elif self.highlighted_slice >= 0:
            text = overlay_actions.ACTIONS[self.highlighted_slice][0]
        else:
            text = _("Drag")
        base_font_size = int(params.get("center_font_size", 11))
        min_font_size = int(params.get("center_min_font_size", 7))
        font_bold = bool(params.get("center_font_bold", False))

        text = self._wrap_center_text(text)

        text_width = center_radius * 1.7
        text_height = center_radius * 1.2
        text_rect = QRectF(
            cx - text_width / 2,
            cy - text_height / 2,
            text_width,
            text_height,
        )
        text_flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap

        font_size = base_font_size
        font = QFont("Sans", font_size)
        font.setBold(font_bold)
        metrics = QFontMetrics(font)
        bounds = metrics.boundingRect(text_rect.toRect(), int(text_flags), text)

        while font_size > min_font_size and (
            bounds.width() > text_rect.width() or bounds.height() > text_rect.height()
        ):
            font_size -= 1
            font.setPointSize(font_size)
            metrics = QFontMetrics(font)
            bounds = metrics.boundingRect(text_rect.toRect(), int(text_flags), text)

        p.setFont(font)
        p.setPen(QPen(text_color))

        if bounds.width() > text_rect.width() or bounds.height() > text_rect.height():
            elided = metrics.elidedText(
                text.replace("\n", " "),
                Qt.TextElideMode.ElideRight,
                int(text_rect.width()),
            )
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided)
        else:
            p.drawText(text_rect, text_flags, text)

    def _wrap_center_text(self, text):
        if not text or "\n" in text:
            return text

        if len(text) <= 10 or " " not in text:
            return text

        words = text.split()
        if len(words) == 2:
            return "\n".join(words)

        total = sum(len(word) for word in words)
        half = total / 2
        count = 0
        split_index = 1
        for idx, word in enumerate(words, start=1):
            count += len(word)
            if count >= half:
                split_index = idx
                break

        return " ".join(words[:split_index]) + "\n" + " ".join(words[split_index:])
