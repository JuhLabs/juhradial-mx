"""Flow edge indicator - shows a glowing marker on the screen edge
where cursor handoff is configured.

A semi-transparent pill with a strong glow, breathing pulse animation,
and peer OS icon. Only visible when a JuhFlow bridge peer is connected.
"""

import json
import logging
import math
import os
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, pyqtProperty,
)
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QRadialGradient, QPainterPath,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger("juhradial.flow.indicator")

# Indicator dimensions
PILL_LENGTH = 100      # along the edge
PILL_THICKNESS = 6     # perpendicular to edge
GLOW_SPREAD = 28       # glow radius beyond the pill
WINDOW_PAD = 4         # extra padding for glow rendering
ICON_SIZE = 32         # OS icon size
ICON_OFFSET = 14       # gap between pill and icon
ICON_CIRCLE_PAD = 8    # padding around icon inside circle
ICON_GLOW_SPREAD = 20  # glow radius around icon circle

# Platform -> SVG filename mapping
PLATFORM_ICON_MAP = {
    "macos": "os-macos.svg",
    "darwin": "os-macos.svg",
    "windows": "os-windows.svg",
    "win32": "os-windows.svg",
    "linux": "os-linux.svg",
    "ios": "os-ios.svg",
    "android": "os-android.svg",
    "chromeos": "os-chromeos.svg",
}


class FlowEdgeIndicator(QWidget):
    """Glowing pill indicator on the configured flow edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowTitle("JuhFlow Indicator")

        self._direction = "right"
        self._breath = 0.0  # 0.0 to 1.0 breathing cycle
        self._visible_target = False
        self._peer_platform = ""  # "macos", "windows", etc.
        self._icon_renderer = None  # QSvgRenderer for peer OS icon
        self._last_peer_seen = 0.0  # timestamp of last peer check with peers
        self._grace_period = 8.0    # seconds to keep showing after peers disappear

        # Breathing animation
        self._breath_anim = QPropertyAnimation(self, b"breath")
        self._breath_anim.setDuration(2400)
        self._breath_anim.setStartValue(0.0)
        self._breath_anim.setEndValue(1.0)
        self._breath_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breath_anim.setLoopCount(-1)  # infinite

        # Fade animation
        self._opacity = 0.0
        self._fade_anim = QPropertyAnimation(self, b"indicator_opacity")
        self._fade_anim.setDuration(400)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Poll for peer connections
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_peers)
        self._poll_timer.start(2000)

    def _get_breath(self):
        return self._breath

    def _set_breath(self, val):
        self._breath = val
        self.update()

    breath = pyqtProperty(float, _get_breath, _set_breath)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.setWindowOpacity(val)
        if val <= 0.01 and not self._visible_target:
            self.hide()

    indicator_opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def configure(self, direction="right"):
        """Set which edge to show the indicator on and position it."""
        self._direction = direction
        self._position_on_edge()

    def _load_icon(self, platform):
        """Load the OS icon SVG for the given platform."""
        filename = PLATFORM_ICON_MAP.get(platform, "os-unknown.svg")
        # Try install path first, then relative
        for base in ["/usr/share/juhradial/assets", "assets"]:
            path = os.path.join(base, filename)
            if os.path.exists(path):
                renderer = QSvgRenderer(path)
                if renderer.isValid():
                    return renderer
        return None

    def _get_window_size(self):
        """Calculate window size based on direction, including space for icon."""
        pad = GLOW_SPREAD + WINDOW_PAD
        circle_diameter = ICON_SIZE + ICON_CIRCLE_PAD * 2
        icon_space = ICON_OFFSET + circle_diameter + ICON_GLOW_SPREAD

        d = self._direction
        if d in ("left", "right"):
            win_w = PILL_THICKNESS + pad * 2 + icon_space
            win_h = PILL_LENGTH + pad * 2
        else:
            win_w = PILL_LENGTH + pad * 2
            win_h = PILL_THICKNESS + pad * 2 + icon_space
        return int(win_w), int(win_h)

    def _position_on_edge(self):
        """Position the widget on the configured screen edge."""
        try:
            from overlay.overlay_cursor import get_screen_geometry
        except ImportError:
            try:
                from overlay_cursor import get_screen_geometry
            except ImportError:
                return

        screen = get_screen_geometry()
        sx, sy = screen["x"], screen["y"]
        sw, sh = screen["width"], screen["height"]

        d = self._direction
        win_w, win_h = self._get_window_size()
        pad = GLOW_SPREAD + WINDOW_PAD

        if d == "right":
            cx = sx + sw - win_w + pad
            cy = sy + sh // 2 - win_h // 2
        elif d == "left":
            cx = sx - pad
            cy = sy + sh // 2 - win_h // 2
        elif d == "bottom":
            cx = sx + sw // 2 - win_w // 2
            cy = sy + sh - win_h + pad
        else:  # top
            cx = sx + sw // 2 - win_w // 2
            cy = sy - pad

        self.setFixedSize(win_w, win_h)
        self.move(int(cx), int(cy))

    def show_indicator(self):
        """Fade in the indicator."""
        if self._visible_target:
            return
        self._visible_target = True
        self._position_on_edge()
        self.setWindowOpacity(0.0)
        self.show()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        self._breath_anim.start()
        logger.info("Flow indicator shown on %s edge (%s)", self._direction, self._peer_platform)

    def hide_indicator(self):
        """Fade out the indicator."""
        if not self._visible_target:
            return
        self._visible_target = False
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()
        self._breath_anim.stop()

    def _check_peers(self):
        """Poll bridge for connected peers."""
        try:
            from . import get_juhflow_bridge
            bridge = get_juhflow_bridge()
            if bridge and bridge.get_peers():
                import time
                self._last_peer_seen = time.time()
                peers = bridge.get_peers()
                platform = peers[0].get("platform", "") if peers else ""
                if platform != self._peer_platform:
                    self._peer_platform = platform
                    self._icon_renderer = self._load_icon(platform)
                    if self._visible_target:
                        self._position_on_edge()
                        self.update()
                if not self._visible_target:
                    self._read_direction()
                    self.show_indicator()
            else:
                # Grace period - don't hide during handoff
                import time
                if time.time() - self._last_peer_seen > self._grace_period:
                    self.hide_indicator()
        except Exception:
            pass

    def _read_direction(self):
        """Read flow direction from config."""
        try:
            cfg_path = Path.home() / ".config" / "juhradial" / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text())
                d = cfg.get("flow", {}).get("direction", "right")
                if d != self._direction:
                    self._direction = d
                    self._position_on_edge()
        except Exception:
            pass

    def paintEvent(self, event):
        """Draw the glowing pill indicator with OS icon."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        pad = GLOW_SPREAD + WINDOW_PAD

        # Breathing factor: oscillates 0 -> 1 -> 0
        t = (math.sin(self._breath * math.pi * 2 - math.pi / 2) + 1) / 2

        d = self._direction

        # Pill rect position
        if d == "right":
            px = w - pad - PILL_THICKNESS
            py = pad
            pw, ph = PILL_THICKNESS, PILL_LENGTH
        elif d == "left":
            px = pad
            py = pad
            pw, ph = PILL_THICKNESS, PILL_LENGTH
        elif d == "top":
            px = pad
            py = pad
            pw, ph = PILL_LENGTH, PILL_THICKNESS
        else:  # bottom
            px = pad
            py = h - pad - PILL_THICKNESS
            pw, ph = PILL_LENGTH, PILL_THICKNESS

        pill_cx = px + pw / 2
        pill_cy = py + ph / 2

        # --- Outer glow (large, soft) ---
        outer_r = GLOW_SPREAD + t * 8
        outer_alpha = int(50 + t * 60)
        outer_grad = QRadialGradient(pill_cx, pill_cy, outer_r)
        outer_grad.setColorAt(0.0, QColor(70, 150, 255, outer_alpha))
        outer_grad.setColorAt(0.4, QColor(70, 150, 255, int(outer_alpha * 0.5)))
        outer_grad.setColorAt(1.0, QColor(70, 150, 255, 0))

        p.setBrush(outer_grad)
        p.setPen(Qt.PenStyle.NoPen)
        if d in ("left", "right"):
            glow_rect = QRectF(
                pill_cx - outer_r,
                pill_cy - PILL_LENGTH / 2 - outer_r * 0.3,
                outer_r * 2,
                PILL_LENGTH + outer_r * 0.6,
            )
        else:
            glow_rect = QRectF(
                pill_cx - PILL_LENGTH / 2 - outer_r * 0.3,
                pill_cy - outer_r,
                PILL_LENGTH + outer_r * 0.6,
                outer_r * 2,
            )
        p.drawEllipse(glow_rect)

        # --- Inner glow (tight, brighter) ---
        inner_r = GLOW_SPREAD * 0.5 + t * 4
        inner_alpha = int(80 + t * 80)
        inner_grad = QRadialGradient(pill_cx, pill_cy, inner_r)
        inner_grad.setColorAt(0.0, QColor(120, 190, 255, inner_alpha))
        inner_grad.setColorAt(0.6, QColor(100, 170, 255, int(inner_alpha * 0.4)))
        inner_grad.setColorAt(1.0, QColor(80, 150, 255, 0))

        p.setBrush(inner_grad)
        if d in ("left", "right"):
            inner_rect = QRectF(
                pill_cx - inner_r, pill_cy - PILL_LENGTH / 2,
                inner_r * 2, PILL_LENGTH,
            )
        else:
            inner_rect = QRectF(
                pill_cx - PILL_LENGTH / 2, pill_cy - inner_r,
                PILL_LENGTH, inner_r * 2,
            )
        p.drawEllipse(inner_rect)

        # --- Pill body ---
        pill_rect = QRectF(px, py, pw, ph)
        pill_alpha = int(200 + t * 55)
        if d in ("left", "right"):
            pill_grad = QLinearGradient(px, py, px, py + ph)
        else:
            pill_grad = QLinearGradient(px, py, px + pw, py)
        pill_grad.setColorAt(0.0, QColor(90, 170, 255, int(pill_alpha * 0.5)))
        pill_grad.setColorAt(0.5, QColor(140, 210, 255, pill_alpha))
        pill_grad.setColorAt(1.0, QColor(90, 170, 255, int(pill_alpha * 0.5)))

        p.setBrush(pill_grad)
        pill_path = QPainterPath()
        radius = min(pw, ph) / 2
        pill_path.addRoundedRect(pill_rect, radius, radius)
        p.drawPath(pill_path)

        # --- Bright core line ---
        core_alpha = int(220 + t * 35)
        p.setPen(QColor(200, 230, 255, core_alpha))
        if d in ("left", "right"):
            lx = px + pw / 2
            p.drawLine(int(lx), int(py + ph * 0.1), int(lx), int(py + ph * 0.9))
        else:
            ly = py + ph / 2
            p.drawLine(int(px + pw * 0.1), int(ly), int(px + pw * 0.9), int(ly))

        # --- Icon with glowing circle ---
        if self._icon_renderer:
            circle_r = (ICON_SIZE + ICON_CIRCLE_PAD * 2) / 2

            # Icon center position
            if d == "right":
                icx = px - ICON_OFFSET - circle_r
                icy = pill_cy
            elif d == "left":
                icx = px + pw + ICON_OFFSET + circle_r
                icy = pill_cy
            elif d == "top":
                icx = pill_cx
                icy = py + ph + ICON_OFFSET + circle_r
            else:  # bottom
                icx = pill_cx
                icy = py - ICON_OFFSET - circle_r

            # Icon circle glow
            glow_r = circle_r + ICON_GLOW_SPREAD + t * 6
            glow_a = int(70 + t * 80)
            icon_glow = QRadialGradient(icx, icy, glow_r)
            icon_glow.setColorAt(0.0, QColor(80, 170, 255, glow_a))
            icon_glow.setColorAt(0.4, QColor(70, 150, 255, int(glow_a * 0.5)))
            icon_glow.setColorAt(1.0, QColor(60, 140, 255, 0))
            p.setBrush(icon_glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(icx - glow_r, icy - glow_r, glow_r * 2, glow_r * 2))

            # Circle background
            bg_alpha = int(40 + t * 30)
            p.setBrush(QColor(30, 60, 120, bg_alpha))
            circle_pen_alpha = int(120 + t * 80)
            from PyQt6.QtGui import QPen
            p.setPen(QPen(QColor(100, 180, 255, circle_pen_alpha), 1.5))
            p.drawEllipse(QRectF(icx - circle_r, icy - circle_r, circle_r * 2, circle_r * 2))

            # Icon
            p.setPen(Qt.PenStyle.NoPen)
            icon_alpha = int(200 + t * 55)
            p.setOpacity(icon_alpha / 255.0)
            icon_rect = QRectF(icx - ICON_SIZE / 2, icy - ICON_SIZE / 2, ICON_SIZE, ICON_SIZE)
            self._icon_renderer.render(p, icon_rect)
            p.setOpacity(1.0)

        p.end()
