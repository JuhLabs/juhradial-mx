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

        # Clear entire surface to fully transparent - prevents opaque rectangle
        # artifacts on KDE Plasma with shader/animated wallpapers
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        cx = WINDOW_SIZE / 2
        cy = WINDOW_SIZE / 2

        # Menu open bloom - scale transform around center
        bloom = getattr(self, 'bloom_progress', 1.0)
        if bloom < 1.0:
            t = bloom
            # OutCubic easing for smooth deceleration
            t = t - 1.0
            eased = t * t * t + 1.0
            scale = 0.92 + 0.08 * eased  # 0.92 -> 1.0
            p.save()
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.translate(-cx, -cy)

        minimal = overlay_actions.MINIMAL_MODE

        if overlay_actions.RADIAL_IMAGE is not None:
            # === 3D Image Mode ===
            if not minimal:
                # Draw the pre-rendered 3D radial wheel image centered
                img_x = cx - overlay_actions.RADIAL_IMAGE.width() / 2
                img_y = cy - overlay_actions.RADIAL_IMAGE.height() / 2
                p.drawPixmap(int(img_x), int(img_y), overlay_actions.RADIAL_IMAGE)

                # Draw highlight on slices with active animation
                highlights = getattr(self, 'slice_highlights', [0.0] * 8)
                for i in range(8):
                    if highlights[i] > 0:
                        self._draw_3d_slice_highlight(p, cx, cy, i, highlights[i])

            # Draw icons floating on the 3D image
            for i in range(8):
                self._draw_3d_icon(p, cx, cy, i)
        else:
            # === Vector Mode (original) ===
            if not minimal:
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
            else:
                # Minimal mode - draw only floating icons (no slices)
                for i in range(8):
                    self._draw_minimal_icon(p, cx, cy, i)

        # Draw submenu if active (same for both modes)
        if self.submenu_active and self.submenu_slice >= 0:
            self._draw_submenu(p, cx, cy)

        # Selection flash overlay - brief white flash on selected slice
        flash_idx = getattr(self, 'flash_slice', -1)
        flash_alpha = getattr(self, 'flash_progress', 0.0)
        if flash_idx >= 0 and flash_alpha > 0:
            if minimal:
                self._draw_minimal_flash(p, cx, cy, flash_idx, flash_alpha)
            else:
                self._draw_flash(p, cx, cy, flash_idx, flash_alpha)

        # Center zone (same for both modes)
        self._draw_center(p, cx, cy)

        # Restore bloom scale transform
        if bloom < 1.0:
            p.restore()

        p.end()

    def _draw_3d_slice_highlight(self, p, cx, cy, index, progress=1.0):
        """Draw a translucent highlight on a slice for 3D mode, scaled by progress."""
        params = overlay_actions.RADIAL_PARAMS or {}
        outer_r = params.get("ring_outer", MENU_RADIUS - 6)
        inner_r = params.get("ring_inner", CENTER_ZONE_RADIUS + 6)
        fill_base = params.get("highlight_fill", (255, 255, 255, 45))
        border_base = params.get("highlight_border", (255, 255, 255, 90))
        fill_rgba = (*fill_base[:3], int(fill_base[3] * progress))
        border_rgba = (*border_base[:3], int(border_base[3] * progress))

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

    def _draw_flash(self, p, cx, cy, index, progress):
        """Draw a white flash overlay on a slice for selection feedback."""
        params = overlay_actions.RADIAL_PARAMS or {}
        outer_r = params.get("ring_outer", MENU_RADIUS - 6)
        inner_r = params.get("ring_inner", CENTER_ZONE_RADIUS + 6)

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

        p.setBrush(QBrush(QColor(255, 255, 255, int(120 * progress))))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

    def _draw_minimal_flash(self, p, cx, cy, index, progress):
        """Draw a circular white flash on an icon for minimal mode selection feedback."""
        icon_angle = math.radians(index * 45 - 90)
        icon_x = cx + ICON_ZONE_RADIUS * math.cos(icon_angle)
        icon_y = cy + ICON_ZONE_RADIUS * math.sin(icon_angle)
        flash_radius = 30
        p.setBrush(QBrush(QColor(255, 255, 255, int(120 * progress))))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(icon_x, icon_y), flash_radius, flash_radius)

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

        h = getattr(self, 'slice_highlights', [0.0] * 8)[index]
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

        # Background badge - alpha boost interpolated by highlight progress
        if bg_rgba:
            bg_color = QColor(
                bg_rgba[0], bg_rgba[1], bg_rgba[2],
                min(255, bg_rgba[3] + int(40 * h))
            )
            p.setBrush(QBrush(bg_color))
            if bg_border_rgba:
                p.setPen(QPen(QColor(*bg_border_rgba), border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            self._draw_badge_shape(p, icon_x, icon_y, bg_shape, params, angle_deg)

        # Hover glow outline - scaled by highlight progress
        if h > 0:
            glow_color = QColor(
                glow_rgba[0], glow_rgba[1], glow_rgba[2],
                int(glow_rgba[3] * h)
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow_color, 3 * scale))
            if bg_rgba:
                self._draw_badge_shape(
                    p, icon_x, icon_y, bg_shape, params, angle_deg, size_extra=4
                )
            else:
                p.drawEllipse(QPointF(icon_x, icon_y), 26 * scale, 26 * scale)

        # Draw icon - brightness and scale interpolated by highlight progress
        brightness = int(40 * h)
        icon_color = QColor(
            min(255, icon_rgb[0] + brightness),
            min(255, icon_rgb[1] + brightness),
            min(255, icon_rgb[2] + brightness),
        )
        hover_bold = bold * (1.0 + 0.12 * h)
        icon_size = 26 * 0.65 * scale
        p.save()
        p.translate(icon_x, icon_y)
        p.scale(hover_bold, hover_bold)
        self._draw_icon(p, 0, 0, action[4], icon_size, icon_color)
        p.restore()

    def _draw_slice(self, p, cx, cy, index):
        h = getattr(self, 'slice_highlights', [0.0] * 8)[index]
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

        # Fill slice - base fill always drawn
        fill = QColor(overlay_actions.COLORS["surface0"])
        fill.setAlpha(80)
        p.setBrush(QBrush(fill))

        # Border - interpolate from surface2@60 toward white@120
        base_s = overlay_actions.COLORS["surface2"]
        stroke = QColor(
            int(base_s.red() + (255 - base_s.red()) * h),
            int(base_s.green() + (255 - base_s.green()) * h),
            int(base_s.blue() + (255 - base_s.blue()) * h),
            int(60 + 60 * h),
        )
        p.setPen(QPen(stroke, 1.0 + 0.5 * h))
        p.drawPath(path)

        # Hover white overlay - fades in with highlight progress
        if h > 0:
            hover = QColor(255, 255, 255, int(45 * h))
            p.setBrush(QBrush(hover))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)

        # Icon position (center of slice)
        icon_angle = math.radians(index * 45 - 90)
        icon_x = cx + ICON_ZONE_RADIUS * math.cos(icon_angle)
        icon_y = cy + ICON_ZONE_RADIUS * math.sin(icon_angle)

        # Glow ring - fades in with highlight
        icon_radius = 26
        if h > 0:
            glow = QColor(255, 255, 255, int(40 * h))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 3))
            p.drawEllipse(QPointF(icon_x, icon_y), icon_radius + 2, icon_radius + 2)

        # Icon background - interpolate from surface1@230 to surface2@255
        c1 = overlay_actions.COLORS["surface1"]
        c2 = overlay_actions.COLORS["surface2"]
        icon_bg = QColor(
            int(c1.red() + (c2.red() - c1.red()) * h),
            int(c1.green() + (c2.green() - c1.green()) * h),
            int(c1.blue() + (c2.blue() - c1.blue()) * h),
            int(230 + 25 * h),
        )
        p.setBrush(QBrush(icon_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(icon_x, icon_y), icon_radius, icon_radius)

        # Icon color - interpolate from subtext1 to text
        ct1 = overlay_actions.COLORS["subtext1"]
        ct2 = overlay_actions.COLORS["text"]
        icon_color = QColor(
            int(ct1.red() + (ct2.red() - ct1.red()) * h),
            int(ct1.green() + (ct2.green() - ct1.green()) * h),
            int(ct1.blue() + (ct2.blue() - ct1.blue()) * h),
        )
        self._draw_icon(p, icon_x, icon_y, action[4], icon_radius * 0.65, icon_color)

    def _draw_minimal_icon(self, p, cx, cy, index):
        """Draw a floating icon without slice background (vector minimal mode)."""
        h = getattr(self, 'slice_highlights', [0.0] * 8)[index]
        action = overlay_actions.ACTIONS[index]

        # Icon position - same circular arrangement as normal slices
        icon_angle = math.radians(index * 45 - 90)
        icon_x = cx + ICON_ZONE_RADIUS * math.cos(icon_angle)
        icon_y = cy + ICON_ZONE_RADIUS * math.sin(icon_angle)

        icon_radius = 26

        # Subtle hover glow circle behind icon
        if h > 0:
            glow = QColor(255, 255, 255, int(40 * h))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 3))
            p.drawEllipse(QPointF(icon_x, icon_y), icon_radius + 2, icon_radius + 2)

        # Icon background circle - interpolate from surface1@230 to surface2@255
        c1 = overlay_actions.COLORS["surface1"]
        c2 = overlay_actions.COLORS["surface2"]
        icon_bg = QColor(
            int(c1.red() + (c2.red() - c1.red()) * h),
            int(c1.green() + (c2.green() - c1.green()) * h),
            int(c1.blue() + (c2.blue() - c1.blue()) * h),
            int(230 + 25 * h),
        )
        p.setBrush(QBrush(icon_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(icon_x, icon_y), icon_radius, icon_radius)

        # Icon color - interpolate from subtext1 to text
        ct1 = overlay_actions.COLORS["subtext1"]
        ct2 = overlay_actions.COLORS["text"]
        icon_color = QColor(
            int(ct1.red() + (ct2.red() - ct1.red()) * h),
            int(ct1.green() + (ct2.green() - ct1.green()) * h),
            int(ct1.blue() + (ct2.blue() - ct1.blue()) * h),
        )
        self._draw_icon(p, icon_x, icon_y, action[4], icon_radius * 0.65, icon_color)

    def _draw_icon(self, p, cx, cy, icon_type, size, color):
        # Thicker strokes for better visibility
        p.setPen(QPen(color, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if icon_type == "play_pause":
            if overlay_actions.MEDIA_PLAYING:
                # Pause icon - two vertical bars
                s = size * 0.55
                bar_w = s * 0.3
                gap = s * 0.25
                p.setBrush(QBrush(color))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(
                    QRectF(cx - gap - bar_w, cy - s, bar_w, s * 2), 1.5, 1.5
                )
                p.drawRoundedRect(
                    QRectF(cx + gap, cy - s, bar_w, s * 2), 1.5, 1.5
                )
            else:
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

        elif icon_type == "os_linux":
            # Tux penguin - simplified: round body, eyes, beak
            s = size * 0.45
            p.setPen(QPen(color, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Body (oval)
            p.drawEllipse(QPointF(cx, cy + s * 0.1), s * 0.65, s * 0.85)
            # Eyes
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx - s * 0.2, cy - s * 0.25), s * 0.1, s * 0.12)
            p.drawEllipse(QPointF(cx + s * 0.2, cy - s * 0.25), s * 0.1, s * 0.12)
            # Beak (small triangle)
            path = QPainterPath()
            path.moveTo(cx - s * 0.12, cy - s * 0.05)
            path.lineTo(cx + s * 0.12, cy - s * 0.05)
            path.lineTo(cx, cy + s * 0.1)
            path.closeSubpath()
            p.drawPath(path)

        elif icon_type == "os_windows":
            # Windows logo - 4-pane grid with perspective
            s = size * 0.38
            gap = s * 0.1
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            # Top-left
            p.drawRect(QRectF(cx - s, cy - s, s - gap / 2, s - gap / 2))
            # Top-right
            p.drawRect(QRectF(cx + gap / 2, cy - s, s - gap / 2, s - gap / 2))
            # Bottom-left
            p.drawRect(QRectF(cx - s, cy + gap / 2, s - gap / 2, s - gap / 2))
            # Bottom-right
            p.drawRect(QRectF(cx + gap / 2, cy + gap / 2, s - gap / 2, s - gap / 2))

        elif icon_type == "os_macos":
            # Apple silhouette - simplified apple with bite and leaf
            s = size * 0.45
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            # Apple body using arcs
            # Left side
            path.moveTo(cx, cy - s * 0.55)
            path.cubicTo(cx - s * 0.7, cy - s * 0.55, cx - s * 0.75, cy + s * 0.1, cx - s * 0.45, cy + s * 0.7)
            path.cubicTo(cx - s * 0.3, cy + s * 0.95, cx - s * 0.1, cy + s * 0.85, cx, cy + s * 0.6)
            # Right side
            path.cubicTo(cx + s * 0.1, cy + s * 0.85, cx + s * 0.3, cy + s * 0.95, cx + s * 0.45, cy + s * 0.7)
            path.cubicTo(cx + s * 0.75, cy + s * 0.1, cx + s * 0.7, cy - s * 0.55, cx, cy - s * 0.55)
            path.closeSubpath()
            # Bite (subtract a circle on the right)
            path.addEllipse(QPointF(cx + s * 0.55, cy - s * 0.15), s * 0.3, s * 0.35)
            p.drawPath(path)
            # Leaf/stem
            p.setPen(QPen(color, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            leaf = QPainterPath()
            leaf.moveTo(cx, cy - s * 0.55)
            leaf.cubicTo(cx + s * 0.1, cy - s * 0.9, cx + s * 0.35, cy - s * 0.85, cx + s * 0.3, cy - s * 0.65)
            p.drawPath(leaf)

        elif icon_type == "os_ios":
            # iOS - phone outline with small apple inside
            s = size * 0.45
            p.setPen(QPen(color, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Phone body (tall rounded rectangle)
            pw, ph = s * 0.7, s * 1.1
            p.drawRoundedRect(QRectF(cx - pw / 2, cy - ph / 2, pw, ph), 4, 4)
            # Small apple shape inside
            a = s * 0.3
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            ap = QPainterPath()
            ap.moveTo(cx, cy - a * 0.45)
            ap.cubicTo(cx - a * 0.6, cy - a * 0.45, cx - a * 0.65, cy + a * 0.05, cx - a * 0.4, cy + a * 0.55)
            ap.cubicTo(cx - a * 0.25, cy + a * 0.8, cx - a * 0.08, cy + a * 0.7, cx, cy + a * 0.5)
            ap.cubicTo(cx + a * 0.08, cy + a * 0.7, cx + a * 0.25, cy + a * 0.8, cx + a * 0.4, cy + a * 0.55)
            ap.cubicTo(cx + a * 0.65, cy + a * 0.05, cx + a * 0.6, cy - a * 0.45, cx, cy - a * 0.45)
            ap.closeSubpath()
            p.drawPath(ap)

        elif icon_type == "os_android":
            # Android robot head - half-circle with antennae and eyes
            s = size * 0.4
            p.setPen(QPen(color, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Head (half-circle / dome)
            head_rect = QRectF(cx - s * 0.8, cy - s * 0.8, s * 1.6, s * 1.6)
            p.drawArc(head_rect, 0, 180 * 16)
            # Flat bottom line
            p.drawLine(QPointF(cx - s * 0.8, cy), QPointF(cx + s * 0.8, cy))
            # Eyes
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx - s * 0.35, cy - s * 0.25), s * 0.1, s * 0.1)
            p.drawEllipse(QPointF(cx + s * 0.35, cy - s * 0.25), s * 0.1, s * 0.1)
            # Antennae
            p.setPen(QPen(color, 1.5))
            p.drawLine(QPointF(cx - s * 0.35, cy - s * 0.7), QPointF(cx - s * 0.55, cy - s * 1.05))
            p.drawLine(QPointF(cx + s * 0.35, cy - s * 0.7), QPointF(cx + s * 0.55, cy - s * 1.05))
            # Body rectangle below head
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(cx - s * 0.7, cy + s * 0.1, s * 1.4, s * 0.7), 3, 3)

        elif icon_type == "os_chromeos":
            # ChromeOS - simplified circle with inner circle (chrome-like)
            s = size * 0.4
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Outer circle
            p.drawEllipse(QPointF(cx, cy), s, s)
            # Inner circle
            p.drawEllipse(QPointF(cx, cy), s * 0.4, s * 0.4)
            # Three dividing lines from inner to outer (120 degrees apart)
            for angle_offset in [90, 210, 330]:
                a = math.radians(angle_offset)
                p.drawLine(
                    QPointF(cx + s * 0.4 * math.cos(a), cy - s * 0.4 * math.sin(a)),
                    QPointF(cx + s * math.cos(a), cy - s * math.sin(a)),
                )

        elif icon_type == "os_unknown":
            # Unknown OS - question mark in circle
            s = size * 0.4
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), s, s)
            # Question mark
            font = QFont("Sans", int(size * 0.45))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QPen(color))
            text_rect = QRectF(cx - s * 0.5, cy - s * 0.5, s, s)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "?")

    @staticmethod
    def _ease_out_back(t, overshoot=1.4):
        """OutBack easing - slight overshoot then settle, creates 'droplet' feel."""
        t = t - 1.0
        return t * t * ((overshoot + 1.0) * t + overshoot) + 1.0

    def _draw_submenu(self, p, cx, cy):
        """Draw submenu items with droplet pop-out animation."""
        submenu = overlay_actions.ACTIONS[self.submenu_slice][5]
        if not submenu:
            return

        progress = getattr(self, 'submenu_progress', 1.0)

        # Calculate parent slice angle
        parent_angle = self.submenu_slice * 45 - 90

        # Submenu items positioned in an arc beyond the main menu
        SUBMENU_RADIUS = MENU_RADIUS + 45
        SUBITEM_RADIUS = 24  # Size of each subitem circle

        num_items = len(submenu)
        spread = 18  # Degrees between items

        for i, item in enumerate(submenu):
            is_highlighted = i == self.highlighted_subitem

            # Per-item stagger - each item starts slightly after the previous
            stagger = 0.12
            item_t = max(0.0, min(1.0, (progress - i * stagger) / (1.0 - (num_items - 1) * stagger)))
            eased = self._ease_out_back(item_t)

            # Interpolate radius: start at ring edge, end at submenu position
            anim_radius = MENU_RADIUS + (SUBMENU_RADIUS - MENU_RADIUS) * eased

            # Interpolate scale: 0.5 -> 1.0
            item_scale = 0.5 + 0.5 * item_t

            # Opacity: fade in faster than movement
            item_opacity = min(1.0, item_t * 2.5)

            # Calculate position with animated radius
            offset = (i - (num_items - 1) / 2) * spread
            item_angle = math.radians(parent_angle + offset)
            item_x = cx + anim_radius * math.cos(item_angle)
            item_y = cy + anim_radius * math.sin(item_angle)

            # Apply scale and opacity via save/restore
            p.save()
            p.setOpacity(p.opacity() * item_opacity)

            # Scale around item center
            scaled_radius = SUBITEM_RADIUS * item_scale

            # Shadow for subitem
            shadow = QColor(0, 0, 0, 80)
            p.setBrush(QBrush(shadow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(
                QPointF(item_x + 2, item_y + 3), scaled_radius, scaled_radius
            )

            # Background
            if is_highlighted:
                bg = QColor(overlay_actions.COLORS["surface2"])
                bg.setAlpha(255)
                # Glow ring
                glow = QColor(255, 255, 255, 60)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(glow, 3))
                p.drawEllipse(
                    QPointF(item_x, item_y), scaled_radius + 3, scaled_radius + 3
                )
            else:
                bg = QColor(overlay_actions.COLORS["surface1"])
                bg.setAlpha(240)

            p.setBrush(QBrush(bg))
            border = (
                QColor(overlay_actions.COLORS["surface2"]) if not is_highlighted else QColor(255, 255, 255, 150)
            )
            p.setPen(QPen(border, 1.5))
            p.drawEllipse(QPointF(item_x, item_y), scaled_radius, scaled_radius)

            # Icon - use pre-rendered pixmap if available, fallback to drawn icon
            icon_name = item[3]  # e.g., "claude", "chatgpt", "os_linux", etc.
            all_icons = {**overlay_actions.AI_ICONS, **overlay_actions.OS_ICONS}
            if icon_name in all_icons:
                icon_size = scaled_radius * 1.4
                icon_rect = QRectF(
                    item_x - icon_size / 2, item_y - icon_size / 2, icon_size, icon_size
                )
                icon = all_icons[icon_name]
                p.drawPixmap(icon_rect.toRect(), icon)
            else:
                # Fallback to drawn icon
                icon_color = QColor(overlay_actions.COLORS["text"]) if is_highlighted else QColor(overlay_actions.COLORS["subtext1"])
                self._draw_icon(
                    p, item_x, item_y, icon_name, scaled_radius * 0.7, icon_color
                )

            p.restore()

    def _draw_center(self, p, cx, cy):
        params = overlay_actions.RADIAL_PARAMS or {}
        center_bg = params.get("center_bg")
        center_radius = self._get_center_radius()

        # Center zone pulse - elastic overshoot on menu open
        pulse = getattr(self, 'center_pulse', 1.0)
        if pulse < 1.0:
            if pulse == 0:
                eased = 0.0
            else:
                # Elastic out: overshoot then settle
                eased = (
                    math.pow(2, -10 * pulse)
                    * math.sin((pulse - 0.075) * (2 * math.pi) / 0.3)
                    + 1.0
                )
            scale = 0.85 + 0.15 * eased  # 0.85 -> overshoot ~1.01 -> 1.0
            p.save()
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.translate(-cx, -cy)

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

        # Restore center pulse transform
        if pulse < 1.0:
            p.restore()

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
