#!/usr/bin/env python3
"""
JuhRadial MX - PyQt6 Radial Menu Overlay

Listens for MenuRequested signal and shows radial menu at cursor position.
Coordinates come from daemon via KWin scripting (accurate on multi-monitor Wayland).
Uses XWayland platform for window positioning (Wayland doesn't allow app-controlled positioning).

SPDX-License-Identifier: GPL-3.0
"""

import os
import sys
import ctypes
import ctypes.util

# Set process name to "juhradial-overlay" so it shows properly in system monitors
# instead of "python3". Uses prctl(PR_SET_NAME) on Linux.
try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    _libc.prctl(15, b"juhradial-overlay", 0, 0, 0)  # PR_SET_NAME = 15
except (OSError, AttributeError):
    _libc = None

# Force XWayland platform - required for window positioning on Wayland
# (Native Wayland doesn't allow apps to position their own windows)
os.environ["QT_QPA_PLATFORM"] = "xcb"

import math
import shlex
import subprocess

from PyQt6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PyQt6.QtCore import (
    Qt,
    pyqtSlot,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
    QRectF,
)
from PyQt6.QtGui import (
    QPainter,
    QBrush,
    QIcon,
    QPixmap,
    QRegion,
    QColor,
    QPen,
    QFont,
    QRadialGradient,
)
from PyQt6.QtDBus import QDBusConnection, QDBusInterface

from overlay_constants import (
    MENU_RADIUS,
    CENTER_ZONE_RADIUS,
    WINDOW_SIZE,
    IS_HYPRLAND,
    IS_GNOME,
    IS_COSMIC,
    IS_KDE,
    IS_X11,
    _HAS_XWAYLAND,
    _log,
)
from overlay_cursor import (
    _refresh_monitors,
    get_monitor_at_cursor,
    get_cursor_position_hyprland,
    get_cursor_position_gnome,
    get_cursor_position_xwayland,
    get_cursor_position_xwayland_synced,
    get_cursor_pos,
)
import overlay_actions
from overlay_painting import RadialMenuPaintingMixin
from i18n import _


class SplashScreen(QWidget):
    """Premium loading splash for JuhRadial MX startup."""

    # Theme colors (Catppuccin Mocha)
    BG = QColor(30, 30, 46)          # #1e1e2e base
    SURFACE = QColor(69, 71, 90)     # #45475a surface1
    TEXT = QColor(205, 214, 244)     # #cdd6f4 text
    ACCENT = QColor(180, 190, 254)   # #b4befe lavender
    ACCENT_DIM = QColor(137, 180, 250)  # #89b2fa blue
    SUBTEXT = QColor(166, 173, 200)  # #a6adc8 subtext0

    SPLASH_SIZE = 320
    ARC_RADIUS = 80
    WHEEL_SIZE = 140  # radial wheel rendered inside the spinning arc

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.SPLASH_SIZE, self.SPLASH_SIZE)

        # Center on primary screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.move(
                geo.x() + (geo.width() - self.SPLASH_SIZE) // 2,
                geo.y() + (geo.height() - self.SPLASH_SIZE) // 2,
            )

        # Load radial wheel image from user's theme (or fallback)
        self._wheel_pixmap = None
        wheel_name = None
        try:
            from themes import get_radial_image
            wheel_name = get_radial_image()
        except (ImportError, AttributeError, ValueError):
            wheel_name = None

        # Search: theme wheel -> fallback to radialwheel3 (neon, looks great on dark)
        wheel_candidates = []
        if wheel_name:
            wheel_candidates.append(wheel_name)
        wheel_candidates.append("radialwheel3.png")  # neon fallback
        wheel_candidates.append("radialwheel1.png")  # metallic fallback

        for wname in wheel_candidates:
            for base in [
                os.path.join(os.path.dirname(__file__), "..", "assets", "radial-wheels"),
                "/usr/share/juhradial/assets/radial-wheels",
            ]:
                wpath = os.path.join(base, wname)
                if os.path.exists(wpath):
                    pm = QPixmap(wpath)
                    if not pm.isNull():
                        self._wheel_pixmap = pm.scaled(
                            self.WHEEL_SIZE, self.WHEEL_SIZE,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    break
            if self._wheel_pixmap:
                break

        # Animation state
        self._angle = 0.0        # spinning arc angle
        self._fade = 1.0         # fade-out progress (1.0 = visible)
        self._pulse = 0.0        # glow pulse phase
        self._closing = False
        self._ready = False      # set True when app loading is done
        self._show_time = None   # when splash was first shown
        self._status_text = _("Loading...")
        self._daemon_iface = None  # set externally to check daemon readiness

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(16)  # ~60fps
        self._timer.start()

    MIN_DISPLAY_MS = 2000  # show splash for at least 2 seconds

    def _tick(self):
        import time

        if self._show_time is None:
            self._show_time = time.time()

        self._angle = (self._angle + 4.0) % 360.0
        self._pulse = (self._pulse + 0.04) % (2 * math.pi)

        if self._closing:
            self._fade -= 0.05
            if self._fade <= 0:
                self._fade = 0
                self._timer.stop()
                self.hide()
                self.deleteLater()
                return
        elif self._ready:
            # App loading done - wait for minimum display time + daemon ready
            elapsed_ms = (time.time() - self._show_time) * 1000
            daemon_ok = (
                self._daemon_iface is None
                or self._daemon_iface.isValid()
            )
            if elapsed_ms >= self.MIN_DISPLAY_MS and daemon_ok:
                self._closing = True
            elif elapsed_ms >= self.MIN_DISPLAY_MS and not daemon_ok:
                self._status_text = _("Waiting for daemon...")
            elif daemon_ok:
                self._status_text = _("Ready")

        self.update()

    def mark_ready(self, daemon_iface=None):
        """Mark app loading as done. Splash stays until min time + daemon ready."""
        self._ready = True
        self._daemon_iface = daemon_iface

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.SPLASH_SIZE / 2
        cy = self.SPLASH_SIZE / 2
        opacity = self._fade

        # -- Background: rounded rect with radial glow --
        p.setOpacity(opacity * 0.95)
        bg_rect = QRectF(20, 20, self.SPLASH_SIZE - 40, self.SPLASH_SIZE - 40)

        # Subtle radial glow behind the panel
        glow = QRadialGradient(cx, cy, self.SPLASH_SIZE * 0.5)
        glow_alpha = int(30 + 10 * math.sin(self._pulse))
        glow.setColorAt(0.0, QColor(self.ACCENT.red(), self.ACCENT.green(), self.ACCENT.blue(), glow_alpha))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(0, 0, self.SPLASH_SIZE, self.SPLASH_SIZE))

        # Main panel
        p.setOpacity(opacity)
        p.setBrush(QBrush(self.BG))
        border_pen = QPen(self.SURFACE)
        border_pen.setWidth(2)
        p.setPen(border_pen)
        p.drawRoundedRect(bg_rect, 24, 24)

        # -- Spinning arc --
        arc_rect = QRectF(
            cx - self.ARC_RADIUS, cy - self.ARC_RADIUS - 10,
            self.ARC_RADIUS * 2, self.ARC_RADIUS * 2,
        )

        # Arc trail (dim)
        trail_pen = QPen(self.SURFACE)
        trail_pen.setWidth(3)
        trail_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(trail_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(arc_rect)

        # Arc sweep with gradient
        sweep_pen = QPen()
        sweep_pen.setWidth(3)
        sweep_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # Draw two arcs for a polished look
        # Primary arc
        sweep_pen.setColor(self.ACCENT)
        p.setPen(sweep_pen)
        start_angle = int(self._angle * 16)
        p.drawArc(arc_rect, start_angle, 90 * 16)

        # Secondary arc (opposite side, dimmer)
        dim_accent = QColor(self.ACCENT_DIM)
        dim_accent.setAlpha(120)
        sweep_pen.setColor(dim_accent)
        p.setPen(sweep_pen)
        p.drawArc(arc_rect, start_angle + 180 * 16, 60 * 16)

        # -- Radial wheel in center of arc --
        wheel_cy = cy - 10  # same vertical offset as arc center
        if self._wheel_pixmap:
            ww = self._wheel_pixmap.width()
            wh = self._wheel_pixmap.height()
            # Glow behind wheel (pulsing)
            wheel_glow = QRadialGradient(cx, wheel_cy, self.WHEEL_SIZE * 0.55)
            wg_alpha = int(50 + 30 * math.sin(self._pulse))
            wheel_glow.setColorAt(0.0, QColor(self.ACCENT.red(), self.ACCENT.green(), self.ACCENT.blue(), wg_alpha))
            wheel_glow.setColorAt(0.7, QColor(self.ACCENT_DIM.red(), self.ACCENT_DIM.green(), self.ACCENT_DIM.blue(), wg_alpha // 3))
            wheel_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(wheel_glow))
            p.setPen(Qt.PenStyle.NoPen)
            glow_r = self.WHEEL_SIZE * 0.6
            p.drawEllipse(QRectF(cx - glow_r, wheel_cy - glow_r, glow_r * 2, glow_r * 2))
            # Wheel image
            p.drawPixmap(int(cx - ww / 2), int(wheel_cy - wh / 2), self._wheel_pixmap)

        # -- "JuhRadial MX" text with multi-layer glow --
        text_y = cy + self.ARC_RADIUS + 10
        title_font = QFont("Sans", 16, QFont.Weight.Bold)
        p.setFont(title_font)

        pulse_val = math.sin(self._pulse)

        # Layer 1: Wide soft glow (large offsets, low alpha)
        wide_alpha = int(25 + 15 * pulse_val)
        wide_color = QColor(self.ACCENT.red(), self.ACCENT.green(), self.ACCENT.blue(), wide_alpha)
        p.setPen(wide_color)
        for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)]:
            p.drawText(
                QRectF(dx, text_y + dy, self.SPLASH_SIZE, 30),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "JuhRadial MX",
            )

        # Layer 2: Medium glow
        med_alpha = int(50 + 30 * pulse_val)
        med_color = QColor(self.ACCENT.red(), self.ACCENT.green(), self.ACCENT.blue(), med_alpha)
        p.setPen(med_color)
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
            p.drawText(
                QRectF(dx, text_y + dy, self.SPLASH_SIZE, 30),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "JuhRadial MX",
            )

        # Layer 3: Tight bright glow
        tight_alpha = int(80 + 40 * pulse_val)
        tight_color = QColor(self.ACCENT.red(), self.ACCENT.green(), self.ACCENT.blue(), tight_alpha)
        p.setPen(tight_color)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            p.drawText(
                QRectF(dx, text_y + dy, self.SPLASH_SIZE, 30),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "JuhRadial MX",
            )

        # Main text (bright white on top)
        p.setPen(self.TEXT)
        p.drawText(
            QRectF(0, text_y, self.SPLASH_SIZE, 30),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "JuhRadial MX",
        )

        # -- Subtitle (dynamic status) --
        sub_font = QFont("Sans", 9)
        p.setFont(sub_font)
        p.setPen(self.SUBTEXT)
        p.drawText(
            QRectF(0, text_y + 28, self.SPLASH_SIZE, 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self._status_text,
        )

        p.end()


class RadialMenu(RadialMenuPaintingMixin, QWidget):
    # Tap threshold in milliseconds - below this is considered a "tap" (toggle mode)
    TAP_THRESHOLD_MS = 250

    def __init__(self):
        super().__init__()
        # Window flags depend on compositor:
        # - GNOME: Popup gets auto-dismissed when focus shifts. Use Tool instead.
        # - KDE/Hyprland/others: Popup works fine and receives mouse input.
        if IS_GNOME:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.BypassWindowManagerHint
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Popup
                | Qt.WindowType.BypassWindowManagerHint
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)
        self.setMouseTracking(True)

        # Pre-set circular mask on KDE so the very first frame is shaped
        if IS_KDE:
            half_win = WINDOW_SIZE // 2
            r = half_win
            self.setMask(QRegion(
                half_win - r, half_win - r, r * 2, r * 2,
                QRegion.RegionType.Ellipse,
            ))
        self.setWindowTitle("JuhRadial MX")  # For window rule matching (Hyprland, etc.)

        self.highlighted_slice = -1
        self.menu_center_x = 0
        self.menu_center_y = 0
        self._paint_suppressed = False  # Suppress painting during COSMIC sync

        # Sub-menu state
        self.submenu_active = False  # True when showing a submenu
        self.submenu_slice = -1  # Which main slice has active submenu
        self.highlighted_subitem = -1  # Which sub-item is highlighted (-1 = none)

        # Animation state - per-slice highlight progress (0.0 = off, 1.0 = full)
        self.slice_highlights = [0.0] * 8
        # Submenu pop-out animation progress (0.0 = hidden, 1.0 = fully shown)
        self.submenu_progress = 0.0
        # Selection flash (slice index to flash, -1 = none)
        self.flash_slice = -1
        self.flash_progress = 0.0  # 1.0 = bright, fades to 0.0
        # Menu open bloom scale (0.0 = start, 1.0 = settled)
        self.bloom_progress = 0.0
        # Center zone pulse (0.0 = start, 1.0 = settled)
        self.center_pulse = 0.0

        # Toggle mode: True when menu was opened with a quick tap and stays open
        self.toggle_mode = False
        # Track when menu was shown (for tap detection)
        self.show_time = None

        # D-Bus setup
        bus = QDBusConnection.sessionBus()
        bus.connect(
            "org.kde.juhradialmx",
            "/org/kde/juhradialmx/Daemon",
            "org.kde.juhradialmx.Daemon",
            "MenuRequested",
            "ii",
            self.on_show,
        )
        # Listen for HideMenu without parameters - we track duration ourselves
        bus.connect(
            "org.kde.juhradialmx",
            "/org/kde/juhradialmx/Daemon",
            "org.kde.juhradialmx.Daemon",
            "HideMenu",
            "",
            self.on_hide,
        )
        bus.connect(
            "org.kde.juhradialmx",
            "/org/kde/juhradialmx/Daemon",
            "org.kde.juhradialmx.Daemon",
            "CursorMoved",
            "ii",
            self.on_cursor_moved,
        )

        # Listen for language changes from settings process
        bus.connect(
            "",  # any sender
            "/org/kde/juhradialmx/Settings",
            "org.kde.juhradialmx.Settings",
            "LanguageChanged",
            "s",
            self._on_language_changed,
        )

        # D-Bus interface for calling daemon methods (haptic feedback)
        self.daemon_iface = QDBusInterface(
            "org.kde.juhradialmx",
            "/org/kde/juhradialmx/Daemon",
            "org.kde.juhradialmx.Daemon",
            bus,
        )
        print(
            f"[DBUS] D-Bus interface created - isValid: {self.daemon_iface.isValid()}"
        )

        # Fade animation
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Cursor polling timer for toggle mode (tracks cursor position when menu stays open)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.timeout.connect(self._poll_cursor)
        self.cursor_timer.setInterval(16)  # ~60fps

        # Animation timer - runs while menu is visible for smooth transitions
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_animations)
        self._anim_timer.setInterval(16)  # ~60fps

        print("=" * 60, flush=True)
        print("  JuhRadial MX - PyQt6 Overlay", flush=True)
        print("=" * 60, flush=True)
        print("\n  Modes:", flush=True)
        print(f"    Hold + release: Execute action on release", flush=True)
        print(
            f"    Quick tap (<{self.TAP_THRESHOLD_MS}ms): Menu stays open, click to select",
            flush=True,
        )
        print("\n  Actions (clockwise from top):", flush=True)
        directions = [
            "Top",
            "Top-Right",
            "Right",
            "Bottom-Right",
            "Bottom",
            "Bottom-Left",
            "Left",
            "Top-Left",
        ]
        for i, action in enumerate(overlay_actions.ACTIONS):
            print(f"    {directions[i]:12} -> {action[0]}", flush=True)
        print("\n" + "=" * 60 + "\n", flush=True)

    @pyqtSlot(str)
    def _on_language_changed(self, lang):
        """Reload translations immediately when settings changes language."""
        print(f"OVERLAY: Language changed to '{lang}' - reloading translations")
        from i18n import setup_i18n

        global _
        _ = setup_i18n()
        overlay_actions._ = _
        overlay_actions.ACTIONS = overlay_actions.load_actions_from_config()

    @pyqtSlot(int, int)
    def on_show(self, x, y):
        import time

        # Reload translations for language changes
        from i18n import setup_i18n

        global _
        _ = setup_i18n()
        overlay_actions._ = _

        # Reload actions, theme, and translations from config each time menu is shown
        # This ensures changes from settings are picked up immediately
        overlay_actions.ACTIONS = overlay_actions.load_actions_from_config()
        overlay_actions.COLORS = overlay_actions.load_theme()
        overlay_actions.load_radial_image()
        overlay_actions.MINIMAL_MODE = overlay_actions.load_minimal_mode()

        # If already in toggle mode and menu is visible, this is a second tap to close
        if self.toggle_mode and self.isVisible():
            print("OVERLAY: Second tap detected - closing menu")
            self._close_menu(execute=False)
            return

        # On Hyprland, re-query cursor position and monitor info for freshness
        # The D-Bus signal coordinates may be stale due to async timing
        if IS_HYPRLAND:
            _refresh_monitors()
            fresh_pos = get_cursor_position_hyprland()
            if fresh_pos:
                x, y = fresh_pos
                print(f"OVERLAY: Hyprland fresh cursor position: ({x}, {y})")

        # On GNOME Wayland, re-query cursor position for freshness
        # The daemon coordinates may be stale due to async timing
        if IS_GNOME:
            fresh_pos = get_cursor_position_gnome()
            if fresh_pos:
                x, y = fresh_pos
                print(f"OVERLAY: GNOME fresh cursor position: ({x}, {y})")

        # On KDE X11, use QCursor.pos() directly - most reliable because it
        # returns coordinates in Qt's own space (matching QWidget.move()).
        # The daemon's xdotool/XQueryPointer coords may be in physical pixels
        # while Qt uses logical pixels with KDE display scaling, causing the
        # menu to appear offset from the cursor.
        if IS_KDE and IS_X11:
            from PyQt6.QtGui import QCursor
            qpos = QCursor.pos()
            x, y = qpos.x(), qpos.y()
            _log(f"KDE X11: QCursor position ({x}, {y})")

        # On KDE Wayland, the daemon's KWin script provides accurate
        # workspace.cursorPos coordinates via D-Bus (ShowMenuAtCursor).
        # Trust those instead of re-querying via XWayland, which can
        # return slightly offset positions (e.g., cursor hotspot shift
        # when hovering browser links).
        elif IS_KDE and _HAS_XWAYLAND:
            _log(f"KDE Wayland: trusting KWin position ({x}, {y})")

        # On COSMIC, XWayland doesn't track the cursor unless it's over an
        # XWayland window.  Use a dedicated raw X11 sync window (truly
        # transparent ARGB, override-redirect) - no Qt overhead, no visual
        # artifacts.  The sync window is separate from the overlay.
        elif IS_COSMIC and _HAS_XWAYLAND:
            fresh_pos = get_cursor_position_xwayland_synced()
            if fresh_pos:
                x, y = fresh_pos
                _log(f"COSMIC sync: using position ({x}, {y})")

        # On other Wayland compositors with XWayland (non-Hyprland,
        # non-GNOME, non-KDE, non-COSMIC): re-query cursor position via
        # XWayland to ensure coordinates are in XWayland's pixel space.
        elif not IS_HYPRLAND and not IS_GNOME and _HAS_XWAYLAND:
            fresh_pos = get_cursor_position_xwayland()
            if fresh_pos:
                x, y = fresh_pos
                _log(f"XWayland cursor position: ({x}, {y})")

        # Detect which monitor the cursor is on and clamp menu to it
        if IS_HYPRLAND:
            mon = get_monitor_at_cursor(x, y)
            print(
                f"OVERLAY: Monitor: {mon['name']} ({mon['width']}x{mon['height']} at {mon['x']},{mon['y']})"
            )
        else:
            mon = None

        print(f"OVERLAY: MenuRequested at ({x}, {y})")
        _log(f"MenuRequested final pos: ({x}, {y})")

        # Clamp menu position to stay within the active monitor
        half = WINDOW_SIZE // 2
        if mon:
            x = max(mon["x"] + half, min(x, mon["x"] + mon["width"] - half))
            y = max(mon["y"] + half, min(y, mon["y"] + mon["height"] - half))

        self.menu_center_x = x
        self.menu_center_y = y
        self.toggle_mode = False  # Reset toggle mode on new show
        self.show_time = time.time()  # Track when menu was shown

        # Reset submenu and animation state
        self.submenu_active = False
        self.submenu_slice = -1
        self.highlighted_subitem = -1
        self.slice_highlights = [0.0] * 8
        self.flash_slice = -1
        self.flash_progress = 0.0
        self.bloom_progress = 0.0
        self.center_pulse = 0.0

        # Query media playback state for play/pause icon
        overlay_actions.get_media_state()

        # Position and show: set opacity to 0 and move BEFORE show to prevent
        # any visible frame at the wrong location on multi-monitor setups
        self.highlighted_slice = -1
        self.setWindowOpacity(0.0)
        self.move(x - half, y - half)

        # On KDE Plasma, XWayland windows show a frozen wallpaper rectangle
        # behind transparent areas (KWin caches the wallpaper). Two fixes:
        # 1) Circular mask - removes rectangular corners from the window
        # 2) Position micro-oscillation in _tick_animations forces KWin to
        #    re-composite the wallpaper behind this window every frame
        # Set mask BEFORE show() so the first frame is already shaped.
        if IS_KDE:
            self._kde_base_x = x - half
            self._kde_base_y = y - half
            self._kde_frame = 0
            self._update_kde_mask()

        self.show()
        self.raise_()
        self.activateWindow()

        # Note: Cursor polling via QCursor.pos() doesn't work on Wayland while button is held
        # Instead, we use CursorMoved D-Bus signals from daemon which tracks evdev REL events
        # (cursor_timer is started in toggle mode after quick tap)

        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        # Start animation timer for bloom + center pulse
        self._anim_timer.start()

        # Verify D-Bus interface is still valid (in case daemon restarted)
        if not self.daemon_iface.isValid():
            print("[DBUS] D-Bus interface invalid, recreating...")
            bus = QDBusConnection.sessionBus()
            self.daemon_iface = QDBusInterface(
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                bus,
            )
            print(
                f"[DBUS] D-Bus interface recreated - isValid: {self.daemon_iface.isValid()}"
            )

        # Trigger haptic feedback for menu appearance
        self._trigger_haptic("menu_appear")

    def _get_center_radius(self):
        params = overlay_actions.RADIAL_PARAMS or {}
        return params.get("center_radius", params.get("ring_inner", CENTER_ZONE_RADIUS))

    def _trigger_haptic(self, event):
        """Trigger haptic feedback via D-Bus call to daemon.

        Args:
            event: One of "menu_appear", "slice_change", "confirm", "invalid"
        """
        print(
            f"[HAPTIC] _trigger_haptic called: event={event}, iface_valid={self.daemon_iface.isValid()}"
        )
        if self.daemon_iface.isValid():
            reply = self.daemon_iface.call("TriggerHaptic", event)
            if reply.type() == reply.MessageType.ErrorMessage:
                print(
                    f"[HAPTIC] D-Bus call failed: {reply.errorName()} - {reply.errorMessage()}"
                )
            else:
                print(f"[HAPTIC] D-Bus call succeeded for {event}")
        else:
            print(
                f"[HAPTIC] ERROR: daemon_iface is INVALID - cannot send haptic signal"
            )

    def _update_kde_mask(self):
        """Set circular window mask on KDE to eliminate rectangular artifact."""
        if not IS_KDE:
            return
        half_win = WINDOW_SIZE // 2
        # Use the full inscribed circle of the window. This clips the
        # rectangular corners (prevents KWin wallpaper cache artifact)
        # while being large enough to contain all rendered content
        # including hover glow, shadows, and submenu items.
        r = half_win
        self.setMask(QRegion(
            half_win - r, half_win - r, r * 2, r * 2,
            QRegion.RegionType.Ellipse,
        ))

    def _tick_animations(self):
        """Update animation state for smooth hover transitions."""
        dirty = False
        for i in range(8):
            target = 1.0 if i == self.highlighted_slice else 0.0
            current = self.slice_highlights[i]
            if current < target:
                self.slice_highlights[i] = min(1.0, current + 0.15)  # ~112ms in
                dirty = True
            elif current > target:
                self.slice_highlights[i] = max(0.0, current - 0.20)  # ~80ms out
                dirty = True

        # Submenu pop-out animation
        if self.submenu_active and self.submenu_progress < 1.0:
            self.submenu_progress = min(1.0, self.submenu_progress + 0.08)  # ~200ms
            dirty = True

        # Selection flash decay
        if self.flash_progress > 0:
            self.flash_progress = max(0.0, self.flash_progress - 0.12)  # ~130ms decay
            dirty = True
            if self.flash_progress <= 0:
                self.flash_slice = -1

        # Menu open bloom (0 -> 1 over ~220ms)
        if self.bloom_progress < 1.0:
            self.bloom_progress = min(1.0, self.bloom_progress + 0.075)
            dirty = True

        # Center zone pulse (0 -> 1 over ~350ms)
        if self.center_pulse < 1.0:
            self.center_pulse = min(1.0, self.center_pulse + 0.05)
            dirty = True

        if dirty:
            self.update()
        elif self._anim_timer.isActive():
            if IS_KDE:
                # Keep timer alive on KDE for position oscillation below
                self.update()
            else:
                # All animations settled - stop timer to save CPU
                self._anim_timer.stop()

        # On KDE Plasma, micro-oscillate window position by 1px each frame.
        # This forces KWin to re-composite the wallpaper behind the window,
        # preventing the frozen/cached rectangle on animated shader wallpapers.
        if IS_KDE and hasattr(self, '_kde_base_x'):
            self._kde_frame += 1
            offset = self._kde_frame % 2
            self.move(self._kde_base_x + offset, self._kde_base_y)

    @pyqtSlot()
    def on_hide(self):
        """Handle HideMenu signal - determine tap vs hold based on time elapsed."""
        import time

        # Guard: if menu was already closed (e.g., by toggle-close in on_show),
        # don't process another HideMenu - it would use stale show_time and
        # might execute an action on the already-hidden menu.
        if not self.isVisible():
            print("OVERLAY: HideMenu received but menu already hidden - ignoring")
            return

        # Calculate how long the menu was shown
        if self.show_time:
            duration_ms = (time.time() - self.show_time) * 1000
        else:
            duration_ms = 1000  # Default to hold mode if no time recorded

        print(f"OVERLAY: HideMenu received (duration={duration_ms:.0f}ms)")

        if duration_ms < self.TAP_THRESHOLD_MS:
            # Quick tap - enter toggle mode
            print(f"OVERLAY: Quick tap detected - entering toggle mode")
            self.toggle_mode = True
            # Start cursor polling for hover detection in toggle mode
            self.cursor_timer.start()
            # Menu stays open - user will click to select or tap again to close
        else:
            # Normal hold-and-release - close and execute
            self._close_menu(execute=True)

    @pyqtSlot(int, int)
    def on_cursor_moved(self, dx, dy):
        """Handle cursor movement from daemon (relative to menu center)."""
        # dx, dy are relative offsets from menu center (button press point)
        distance = math.hypot(dx, dy)
        center_radius = self._get_center_radius()

        if distance < center_radius or distance > MENU_RADIUS:
            new_slice = -1
        else:
            # Calculate angle from relative position
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-HOLD] on_cursor_moved: slice changed from {self.highlighted_slice} to {new_slice}"
            )
            # Trigger haptic for slice change (only when entering a valid slice)
            if new_slice >= 0:
                self._trigger_haptic("slice_change")
            self.highlighted_slice = new_slice
            # Start animation timer for smooth highlight transition
            if not self._anim_timer.isActive():
                self._anim_timer.start()
            self.update()

    def _reposition_cosmic(self):
        """Reposition overlay after XWayland syncs cursor position on COSMIC."""
        fresh_pos = get_cursor_position_xwayland()
        if fresh_pos:
            x, y = fresh_pos
            half = WINDOW_SIZE // 2
            self.menu_center_x = x
            self.menu_center_y = y
            self.move(x - half, y - half)
            print(f"OVERLAY: COSMIC reposition to ({x}, {y})")

    def _close_menu(self, execute=True):
        self.cursor_timer.stop()
        self.toggle_mode = False  # Reset toggle mode

        print(
            f"_close_menu: execute={execute}, submenu_active={self.submenu_active}, subitem={self.highlighted_subitem}, slice={self.highlighted_slice}"
        )

        if execute:
            if self.submenu_active and self.highlighted_subitem >= 0:
                # Execute submenu item
                submenu = overlay_actions.ACTIONS[self.submenu_slice][5]
                print(
                    f"_close_menu: Executing submenu item {self.highlighted_subitem} from slice {self.submenu_slice}"
                )
                if submenu and self.highlighted_subitem < len(submenu):
                    subitem = submenu[self.highlighted_subitem]
                    print(f"_close_menu: Subitem = {subitem}")
                    self._trigger_haptic("confirm")  # Haptic for selection confirm
                    self._execute_subaction(subitem)
            elif self.highlighted_slice >= 0:
                action = overlay_actions.ACTIONS[self.highlighted_slice]
                if action[1] == "submenu":
                    # Don't execute, show submenu instead (handled in toggle mode)
                    pass
                else:
                    # Trigger selection flash before closing
                    self.flash_slice = self.highlighted_slice
                    self.flash_progress = 1.0
                    self._anim_timer.start()
                    self.update()
                    self._trigger_haptic("confirm")  # Haptic for selection confirm
                    # Delay hide briefly so flash is visible
                    QTimer.singleShot(80, lambda: self._finish_close(action))
                    return  # Don't hide yet

        # Reset submenu state and hide immediately (no flash)
        self._finish_hide()

    def _finish_close(self, action):
        """Complete the close after selection flash - execute action and hide."""
        self._execute_action(action)
        self._finish_hide()

    def _finish_hide(self):
        """Reset state and hide the menu."""
        # On KDE, make window invisible BEFORE stopping the oscillation timer.
        # Otherwise KWin gets one frame to show the cached wallpaper rectangle.
        if IS_KDE:
            self.setWindowOpacity(0.0)
        self._anim_timer.stop()
        self.submenu_active = False
        self.submenu_slice = -1
        self.highlighted_subitem = -1
        self.flash_slice = -1
        self.flash_progress = 0.0
        self.show_time = None  # Prevent stale duration in on_hide
        self.hide()
        if IS_KDE:
            self.clearMask()

    def _execute_action(self, action):
        label, cmd_type, cmd = action[0], action[1], action[2]
        print(f"Executing: {label}")

        try:
            if cmd_type == "exec":
                try:
                    cmd_args = shlex.split(cmd)
                    subprocess.Popen(
                        cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                except ValueError as e:
                    print(f"Invalid command syntax: {cmd} - {e}")
            elif cmd_type == "url":
                if cmd.startswith("-"):
                    print(f"Invalid URL (starts with -): {cmd}")
                else:
                    subprocess.Popen(
                        ["xdg-open", cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif cmd_type == "emoji":
                import shutil
                if shutil.which("plasma-emojier"):
                    emoji_cmd = ["plasma-emojier"]
                elif shutil.which("gnome-characters"):
                    emoji_cmd = ["gnome-characters"]
                elif shutil.which("ibus"):
                    emoji_cmd = ["ibus", "emoji"]
                else:
                    emoji_cmd = ["xdg-open", "https://emojipedia.org"]
                subprocess.Popen(
                    emoji_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif cmd_type == "settings":
                overlay_actions.open_settings()
            elif cmd_type == "submenu":
                self.submenu_active = True
                self.submenu_slice = self.highlighted_slice
                self.highlighted_subitem = -1
                self.submenu_progress = 0.0
                self._update_kde_mask()
                if not self._anim_timer.isActive():
                    self._anim_timer.start()
                self.update()
                return  # Don't close menu
        except Exception as e:
            print(f"Error executing action: {e}")

    def _execute_subaction(self, subitem):
        """Execute a submenu item action."""
        label, cmd_type, cmd = subitem[0], subitem[1], subitem[2]
        print(f"Executing submenu: {label}")

        try:
            if cmd_type == "exec":
                try:
                    cmd_args = shlex.split(cmd)
                    subprocess.Popen(
                        cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                except ValueError as e:
                    print(f"Invalid command syntax: {cmd} - {e}")
            elif cmd_type == "url":
                if cmd.startswith("-"):
                    print(f"Invalid URL (starts with -): {cmd}")
                else:
                    subprocess.Popen(
                        ["xdg-open", cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif cmd_type == "easy_switch":
                try:
                    host_index = int(cmd)
                    if not 0 <= host_index <= 2:
                        print(
                            f"Easy-Switch: Invalid host index {host_index}, must be 0-2"
                        )
                        self._trigger_haptic("invalid")
                        return
                except ValueError:
                    print(f"Easy-Switch: Invalid host index format: {cmd}")
                    self._trigger_haptic("invalid")
                    return

                print(f"Easy-Switch: Switching to host {host_index}")
                try:
                    result = subprocess.run(
                        [
                            "gdbus",
                            "call",
                            "--session",
                            "--dest",
                            "org.kde.juhradialmx",
                            "--object-path",
                            "/org/kde/juhradialmx/Daemon",
                            "--method",
                            "org.kde.juhradialmx.Daemon.SetHost",
                            str(host_index),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        print(
                            f"Easy-Switch: Successfully requested switch to host {host_index}"
                        )
                    else:
                        print(f"Easy-Switch D-Bus error: {result.stderr.strip()}")
                        self._trigger_haptic("invalid")
                except subprocess.TimeoutExpired:
                    print("Easy-Switch: D-Bus call timed out")
                    self._trigger_haptic("invalid")
                except Exception as e:
                    print(f"Easy-Switch D-Bus error: {e}")
                    self._trigger_haptic("invalid")
        except Exception as e:
            print(f"Error executing subaction: {e}")

    def _poll_cursor(self):
        """Poll cursor position for hover detection."""
        pos_x, pos_y = get_cursor_pos()
        cx = self.menu_center_x
        cy = self.menu_center_y

        dx = pos_x - cx
        dy = pos_y - cy
        distance = math.hypot(dx, dy)
        center_radius = self._get_center_radius()

        if (
            distance < center_radius or distance > MENU_RADIUS + 60
        ):
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        if self.submenu_active:
            subitem = self._get_subitem_at_position(dx, dy)
            if subitem >= 0:
                if subitem != self.highlighted_subitem:
                    self.highlighted_subitem = subitem
                    self.update()
                return
            if new_slice == self.submenu_slice or distance > MENU_RADIUS:
                self.highlighted_subitem = -1
                self.update()
                return
            else:
                self.submenu_active = False
                self.submenu_slice = -1
                self.highlighted_subitem = -1
                self._update_kde_mask()

        if new_slice >= 0 and new_slice != self.highlighted_slice:
            action = overlay_actions.ACTIONS[new_slice]
            if action[1] == "submenu" and action[5]:
                self.submenu_active = True
                self.submenu_slice = new_slice
                self.highlighted_subitem = -1
                self.submenu_progress = 0.0
                self._update_kde_mask()
                if not self._anim_timer.isActive():
                    self._anim_timer.start()

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-TOGGLE] _poll_cursor: slice changed from {self.highlighted_slice} to {new_slice}"
            )
            if new_slice >= 0:
                self._trigger_haptic("slice_change")
            self.highlighted_slice = new_slice
            if not self._anim_timer.isActive():
                self._anim_timer.start()
            self.update()
        elif self.submenu_active:
            self.update()

    def _get_subitem_at_position(self, dx, dy):
        """Check if cursor is over a submenu item. Returns item index or -1."""
        if not self.submenu_active or self.submenu_slice < 0:
            return -1

        submenu = overlay_actions.ACTIONS[self.submenu_slice][5]
        if not submenu:
            return -1

        parent_angle = self.submenu_slice * 45 - 90
        SUBMENU_RADIUS = MENU_RADIUS + 45
        SUBITEM_SIZE = 32

        num_items = len(submenu)
        spread = 15

        for i, item in enumerate(submenu):
            offset = (i - (num_items - 1) / 2) * spread
            item_angle = math.radians(parent_angle + offset)
            item_x = SUBMENU_RADIUS * math.cos(item_angle)
            item_y = SUBMENU_RADIUS * math.sin(item_angle)

            dist_to_item = math.hypot(dx - item_x, dy - item_y)
            if dist_to_item < SUBITEM_SIZE:
                return i

        return -1

    def mouseMoveEvent(self, event):
        _log(f"mouseMoveEvent: toggle_mode={self.toggle_mode}")
        cx = WINDOW_SIZE / 2
        cy = WINDOW_SIZE / 2
        pos = event.position()
        dx = pos.x() - cx
        dy = pos.y() - cy
        distance = math.hypot(dx, dy)
        center_radius = self._get_center_radius()

        if distance < center_radius or distance > MENU_RADIUS + 60:
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        if self.submenu_active:
            subitem = self._get_subitem_at_position(dx, dy)
            if subitem >= 0:
                if subitem != self.highlighted_subitem:
                    self.highlighted_subitem = subitem
                    self.update()
                return
            if new_slice == self.submenu_slice or distance > MENU_RADIUS:
                self.highlighted_subitem = -1
                self.update()
                return
            else:
                self.submenu_active = False
                self.submenu_slice = -1
                self.highlighted_subitem = -1
                self._update_kde_mask()

        if new_slice >= 0 and new_slice != self.highlighted_slice:
            action = overlay_actions.ACTIONS[new_slice]
            if action[1] == "submenu" and action[5]:
                self.submenu_active = True
                self.submenu_slice = new_slice
                self.highlighted_subitem = -1
                self.submenu_progress = 0.0
                self._update_kde_mask()
                if not self._anim_timer.isActive():
                    self._anim_timer.start()

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-MOUSE] mouseMoveEvent: slice changed from {self.highlighted_slice} to {new_slice}"
            )
            if new_slice >= 0:
                self._trigger_haptic("slice_change")
            self.highlighted_slice = new_slice
            if not self._anim_timer.isActive():
                self._anim_timer.start()
            self.update()
        elif self.submenu_active:
            self.update()

    def mousePressEvent(self, event):
        """Handle mouse press - used in toggle mode for selection."""
        if self.toggle_mode:
            if event.button() == Qt.MouseButton.LeftButton:
                print(
                    f"OVERLAY: Left click in toggle mode - slice={self.highlighted_slice}, submenu_active={self.submenu_active}, subitem={self.highlighted_subitem}"
                )
                self._close_menu(execute=True)
            elif event.button() == Qt.MouseButton.RightButton:
                print("OVERLAY: Right click in toggle mode - closing")
                self._close_menu(execute=False)
            # Ignore BackButton/ForwardButton (gesture button) - handled via D-Bus
            # Prevents race: Qt mouse event arrives before D-Bus ShowMenu signal,
            # which would close the menu then immediately reopen it.

    def mouseReleaseEvent(self, event):
        """Handle mouse release - only used in non-toggle mode."""
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._close_menu(execute=False)


def create_tray_icon(app, radial_menu):
    """Create system tray icon with menu"""
    icon = QIcon.fromTheme("juhradial-mx")

    icon_paths = [
        os.path.join(os.path.dirname(__file__), "..", "assets", "juhradial-mx.svg"),
        os.path.join("/usr/share/juhradial/assets", "juhradial-mx.svg"),
        os.path.join("/usr/share/icons/hicolor/scalable/apps", "juhradial-mx.svg"),
    ]

    if icon.isNull():
        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                candidate = QIcon(icon_path)
                if not candidate.isNull():
                    icon = candidate
                    break

    if icon.isNull():
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(overlay_actions.COLORS["lavender"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        icon = QIcon(pixmap)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("JuhRadial MX")

    menu = QMenu()
    menu.setStyleSheet("""
        QMenu {
            background-color: #1e1e2e;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 8px;
            padding: 4px;
        }
        QMenu::item {
            padding: 8px 24px;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #45475a;
        }
    """)

    settings_action = menu.addAction(_("Settings"))
    settings_action.triggered.connect(overlay_actions.open_settings)

    menu.addSeparator()

    def exit_application():
        uid = str(os.getuid())
        subprocess.run(
            ["pkill", "-u", uid, "-f", "settings_dashboard.py"], capture_output=True
        )
        app.quit()

    exit_action = menu.addAction(_("Exit"))
    exit_action.triggered.connect(exit_application)

    tray.setContextMenu(menu)
    tray.show()

    return tray


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("JuhRadial MX")
    app.setDesktopFileName("juhradial-mx")

    # Show splash screen immediately (before heavy loading)
    splash = SplashScreen()
    splash.show()
    app.processEvents()

    # Load submenu icons and 3D radial image (requires QApplication)
    overlay_actions.load_ai_icons()
    app.processEvents()
    overlay_actions.load_os_icons()
    app.processEvents()
    overlay_actions.load_radial_image()
    app.processEvents()

    w = RadialMenu()
    app.processEvents()
    app.tray = create_tray_icon(app, w)

    # Start Flow server if enabled in config
    # NOTE: Cannot import settings_config here - it imports GTK4 (gi)
    # which deadlocks inside a PyQt6 process. Read JSON directly.
    try:
        import json as _json
        _cfg_path = os.path.join(
            os.path.expanduser("~"), ".config", "juhradial", "config.json"
        )
        with open(_cfg_path) as _f:
            _cfg = _json.load(_f)
        if _cfg.get("flow", {}).get("enabled", False):
            from flow import start_flow_server
            start_flow_server()
            _log("[Flow] Auto-started from config")
    except Exception as e:
        _log(f"[Flow] Auto-start failed: {e}")
        import traceback
        _log(traceback.format_exc())

    # Mark loading done - splash waits for min display time + daemon D-Bus ready
    splash.mark_ready(daemon_iface=w.daemon_iface)

    print("System tray icon active - right-click for menu", flush=True)
    ret = app.exec()
    sys.exit(ret)
