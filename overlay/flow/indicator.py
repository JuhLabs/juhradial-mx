"""Flow edge indicator - shows a glowing bar on the screen edge
where cursor handoff is configured.

Uses a pre-rendered PNG image (flow-indicator.png) with breathing
opacity animation. Only visible when a JuhFlow bridge peer is connected.
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
    QPainter, QPixmap, QTransform, QColor, QRadialGradient,
)
from PyQt6.QtWidgets import QWidget, QApplication

logger = logging.getLogger("juhradial.flow.indicator")

# Target height for the indicator image (pixels).
# The image is scaled to this height; width scales proportionally.
INDICATOR_HEIGHT = 500

# Soft glow padding around the image (extra window space for the glow to render)
GLOW_PAD = 18


class FlowEdgeIndicator(QWidget):
    """Glowing bar indicator on the configured flow edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Desktop-aware window flags:
        # - KDE Wayland: BypassWindowManagerHint works correctly
        # - GNOME/Mutter: BypassWindowManagerHint is ignored on XWayland;
        #   use Tool + WindowStaysOnTopHint which Mutter respects
        try:
            from overlay_constants import IS_GNOME
        except ImportError:
            IS_GNOME = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

        if IS_GNOME:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.BypassWindowManagerHint
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("JuhFlow Indicator")

        self._direction = "right"
        self._breath = 0.0  # 0.0 to 1.0 breathing cycle
        self._visible_target = False
        self._hovered = False  # mouse hovering over indicator
        self._peer_platform = ""  # "macos", "windows", etc.
        self._last_peer_seen = 0.0  # timestamp of last peer check with peers
        self._grace_period = 8.0    # seconds to keep showing after peers disappear
        self._hidden_by_config = False  # user chose to hide indicator
        self._monitor_name = ""  # "" = auto (cursor-based), "DP-1" etc = specific

        # KDE screen edge action suppression
        self._kde_saved_edge_action = None  # original value to restore
        self._kde_edge_suppressed = False

        # Load indicator image
        self._pixmap = None
        self._pixmap_rotated_cw = None   # 90 CW for top edge
        self._pixmap_rotated_ccw = None  # 90 CCW for bottom edge
        self._load_indicator_image()

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

    def _load_indicator_image(self):
        """Load the flow indicator PNG from assets."""
        for base in ["/usr/share/juhradial/assets", "assets"]:
            path = os.path.join(base, "flow-indicator.png")
            if os.path.exists(path):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    # Scale to target height, preserve aspect ratio
                    self._pixmap = pixmap.scaledToHeight(
                        INDICATOR_HEIGHT,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    # Pre-compute rotated versions for top/bottom edges.
                    # CW (90) for top, CCW (-90) for bottom keeps text readable.
                    transform_cw = QTransform().rotate(90)
                    self._pixmap_rotated_cw = self._pixmap.transformed(
                        transform_cw,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    transform_ccw = QTransform().rotate(-90)
                    self._pixmap_rotated_ccw = self._pixmap.transformed(
                        transform_ccw,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    logger.info("Flow indicator image loaded from %s (%dx%d)",
                                path, self._pixmap.width(), self._pixmap.height())
                    return
        logger.warning("Flow indicator image not found")

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

    def _get_active_pixmap(self):
        """Return the correct pixmap for the current direction."""
        if self._direction in ("top", "bottom"):
            return self._pixmap_rotated_ccw
        return self._pixmap

    def _get_monitor_geometry(self):
        """Get geometry of the configured monitor.

        "" (auto/default) = original cursor-based detection.
        "DP-1" etc = match by connector name (stable across reboots).
        """
        if self._monitor_name:
            app = QApplication.instance()
            if app:
                for screen in app.screens():
                    if screen.name() == self._monitor_name:
                        geom = screen.geometry()
                        return {
                            "x": geom.x(), "y": geom.y(),
                            "width": geom.width(), "height": geom.height(),
                        }
                # Connector not found (unplugged?) - fall through to auto
                logger.debug("Monitor %s not found, falling back to auto",
                             self._monitor_name)

        # Auto mode: use cursor-based screen detection (original behavior)
        try:
            from overlay.overlay_cursor import get_screen_geometry
        except ImportError:
            try:
                from overlay_cursor import get_screen_geometry
            except ImportError:
                return {"x": 0, "y": 0, "width": 1920, "height": 1080}
        return get_screen_geometry()

    def _position_on_edge(self):
        """Position the widget on the configured screen edge."""
        pm = self._get_active_pixmap()
        if not pm:
            return

        screen = self._get_monitor_geometry()
        if not screen:
            return
        sx = screen.get("x") or 0
        sy = screen.get("y") or 0
        sw = screen.get("width") or 1920
        sh = screen.get("height") or 1080

        # Window is image size + glow padding on all sides
        img_w, img_h = pm.width(), pm.height()
        win_w = img_w + GLOW_PAD * 2
        win_h = img_h + GLOW_PAD * 2
        d = self._direction

        if d == "right":
            cx = sx + sw - img_w - GLOW_PAD
            cy = sy + sh // 2 - win_h // 2
        elif d == "left":
            cx = sx - GLOW_PAD
            cy = sy + sh // 2 - win_h // 2
        elif d == "bottom":
            cx = sx + sw // 2 - win_w // 2
            cy = sy + sh - img_h - GLOW_PAD
        else:  # top
            cx = sx + sw // 2 - win_w // 2
            cy = sy - GLOW_PAD

        self.setFixedSize(win_w, win_h)
        self.move(int(cx), int(cy))

    # -- KDE screen edge suppression --
    # KDE ElectricBorder enum: Top=0, TopRight=1, Right=2, BottomRight=3,
    # Bottom=4, BottomLeft=5, Left=6, TopLeft=7, None=8
    _DIRECTION_TO_KDE_BORDER_ID = {
        "right": "2",
        "left": "6",
        "top": "0",
        "bottom": "4",
    }
    _DIRECTION_TO_KDE_EDGE_KEY = {
        "right": "Right",
        "left": "Left",
        "top": "Top",
        "bottom": "Bottom",
    }

    def _suppress_kde_edge(self):
        """Disable KDE's screen edge actions for the flow edge.

        KDE effects (cube, overview, etc.) use [Effect-*] BorderActivate
        keys with numeric border IDs. We scan all effect groups, save any
        that use our edge's border ID, and remove that ID temporarily.
        Also handles [ElectricBorders] for simple edge actions.
        """
        if self._kde_edge_suppressed:
            return
        border_id = self._DIRECTION_TO_KDE_BORDER_ID.get(self._direction)
        edge_key = self._DIRECTION_TO_KDE_EDGE_KEY.get(self._direction)
        if not border_id:
            return
        try:
            import configparser
            import subprocess
            kwinrc = Path.home() / ".config" / "kwinrc"
            if not kwinrc.exists():
                return

            cfg = configparser.ConfigParser(strict=False)
            cfg.read(str(kwinrc))

            saved = []  # [(group, key, original_value)]
            changed = False

            # Scan all [Effect-*] groups for BorderActivate containing our border ID
            for section in cfg.sections():
                if not section.startswith("Effect-"):
                    continue
                for key in ("BorderActivate", "BorderActivate2", "BorderActivate3"):
                    if cfg.has_option(section, key):
                        val = cfg.get(section, key)
                        ids = [x.strip() for x in val.split(",")]
                        if border_id in ids:
                            saved.append((section, key, val))
                            new_ids = [x for x in ids if x != border_id]
                            new_val = ",".join(new_ids) if new_ids else ""
                            subprocess.run(
                                ["kwriteconfig6", "--file", "kwinrc",
                                 "--group", section, "--key", key, new_val],
                                timeout=3,
                            )
                            changed = True
                            logger.info("Suppressed KDE %s %s: %s -> %s",
                                        section, key, val, new_val)

            # Also check [ElectricBorders] for simple edge actions
            if edge_key and cfg.has_option("ElectricBorders", edge_key):
                val = cfg.get("ElectricBorders", edge_key)
                if val and val != "None":
                    saved.append(("ElectricBorders", edge_key, val))
                    subprocess.run(
                        ["kwriteconfig6", "--file", "kwinrc",
                         "--group", "ElectricBorders", "--key", edge_key, "None"],
                        timeout=3,
                    )
                    changed = True

            if changed:
                subprocess.Popen(
                    ["dbus-send", "--session", "--type=method_call",
                     "--dest=org.kde.KWin", "/KWin",
                     "org.kde.KWin.reconfigure"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

            self._kde_saved_edge_action = saved if saved else None
            self._kde_edge_suppressed = bool(saved)
        except Exception as e:
            logger.debug("KDE edge suppression failed: %s", e)

    def _restore_kde_edge(self):
        """Restore all KDE screen edge actions that were suppressed."""
        if not self._kde_edge_suppressed or not self._kde_saved_edge_action:
            self._kde_edge_suppressed = False
            return
        try:
            import subprocess
            for group, key, original_val in self._kde_saved_edge_action:
                subprocess.run(
                    ["kwriteconfig6", "--file", "kwinrc",
                     "--group", group, "--key", key, original_val],
                    timeout=3,
                )
                logger.info("Restored KDE %s %s: %s", group, key, original_val)
            subprocess.Popen(
                ["dbus-send", "--session", "--type=method_call",
                 "--dest=org.kde.KWin", "/KWin",
                 "org.kde.KWin.reconfigure"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug("KDE edge restore failed: %s", e)
        self._kde_edge_suppressed = False
        self._kde_saved_edge_action = None

    def show_indicator(self):
        """Fade in the indicator."""
        if self._visible_target:
            return
        if self._hidden_by_config:
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
        self._suppress_kde_edge()
        logger.info("Flow indicator shown on %s edge", self._direction)

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
        self._restore_kde_edge()

    def _check_peers(self):
        """Poll bridge for connected peers."""
        try:
            from . import get_juhflow_bridge
            bridge = get_juhflow_bridge()
            if bridge is None:
                logger.debug("_check_peers: bridge is None (not initialized)")
                return
            peers = bridge.get_peers()
            if peers:
                import time
                self._last_peer_seen = time.time()
                platform = peers[0].get("platform", "") if peers else ""
                self._peer_platform = platform
                self._read_direction()
                if not self._visible_target:
                    logger.info("Peer detected (%s), showing on %s edge",
                                platform, self._direction)
                    self.show_indicator()
                    logger.debug("Indicator visible=%s, opacity=%.2f, "
                                 "pos=(%d,%d), size=%dx%d",
                                 self.isVisible(), self._opacity,
                                 self.x(), self.y(),
                                 self.width(), self.height())
            else:
                logger.debug("_check_peers: bridge active but no peers connected")
                # Grace period - don't hide during handoff
                import time
                if time.time() - self._last_peer_seen > self._grace_period:
                    self.hide_indicator()
        except Exception as e:
            logger.debug("_check_peers error: %s", e)

    def _read_direction(self):
        """Read flow config: direction, hide_indicator, monitor."""
        try:
            cfg_path = Path.home() / ".config" / "juhradial" / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text())
                flow = cfg.get("flow", {})
                d = flow.get("direction", "right")
                hidden = flow.get("hide_indicator", False)
                monitor = flow.get("monitor", "")

                self._hidden_by_config = hidden
                if hidden and self._visible_target:
                    self.hide_indicator()
                    return

                reposition = False
                if d != self._direction:
                    # Direction changed - restore old edge, suppress new one
                    if self._kde_edge_suppressed:
                        self._restore_kde_edge()
                    self._direction = d
                    if self._visible_target:
                        self._suppress_kde_edge()
                    reposition = True
                if monitor != self._monitor_name:
                    self._monitor_name = monitor
                    reposition = True
                if reposition:
                    self._position_on_edge()
        except Exception:
            pass

    def enterEvent(self, event):
        """Mouse entered - brighten the glow."""
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        """Mouse left - return to normal glow."""
        self._hovered = False
        self.update()

    def paintEvent(self, event):
        """Draw subtle glow + indicator image with breathing opacity."""
        pm = self._get_active_pixmap()
        if not pm:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # Breathing factor: oscillates 0 -> 1 -> 0
        t = (math.sin(self._breath * math.pi * 2 - math.pi / 2) + 1) / 2

        # --- Soft ambient glow hugging the image ---
        hover = 1.8 if self._hovered else 1.0
        p.setPen(Qt.PenStyle.NoPen)

        # Image dimensions inside the window
        pm_w, pm_h = pm.width(), pm.height()

        # Outer glow - snug around the image
        outer_alpha = int((15 + t * 18) * hover)
        glow_rx = (pm_w / 2 + GLOW_PAD) * (1.0 + (0.08 if self._hovered else 0))
        glow_ry = (pm_h / 2 + GLOW_PAD) * (1.0 + (0.04 if self._hovered else 0))
        outer_grad = QRadialGradient(cx, cy, max(glow_rx, glow_ry))
        outer_grad.setColorAt(0.0, QColor(60, 160, 255, min(outer_alpha, 255)))
        outer_grad.setColorAt(0.6, QColor(50, 130, 255, min(int(outer_alpha * 0.35), 255)))
        outer_grad.setColorAt(1.0, QColor(40, 100, 255, 0))
        p.setBrush(outer_grad)
        p.drawEllipse(QRectF(cx - glow_rx, cy - glow_ry, glow_rx * 2, glow_ry * 2))

        # Inner glow - tight, slightly brighter
        inner_alpha = int((22 + t * 25) * hover)
        inner_rx = (pm_w / 2) * (0.6 + (0.08 if self._hovered else 0))
        inner_ry = (pm_h / 2) * (0.85 + (0.04 if self._hovered else 0))
        inner_grad = QRadialGradient(cx, cy, max(inner_rx, inner_ry))
        inner_grad.setColorAt(0.0, QColor(90, 180, 255, min(inner_alpha, 255)))
        inner_grad.setColorAt(0.65, QColor(70, 150, 255, min(int(inner_alpha * 0.25), 255)))
        inner_grad.setColorAt(1.0, QColor(50, 130, 255, 0))
        p.setBrush(inner_grad)
        p.drawEllipse(QRectF(cx - inner_rx, cy - inner_ry, inner_rx * 2, inner_ry * 2))

        # --- Indicator image ---
        breath_opacity = (0.8 + t * 0.2) if self._hovered else (0.7 + t * 0.3)
        p.setOpacity(breath_opacity)
        p.drawPixmap(GLOW_PAD, GLOW_PAD, pm)

        p.end()
