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

# Force XWayland platform - required for window positioning on Wayland
# (Native Wayland doesn't allow apps to position their own windows)
os.environ["QT_QPA_PLATFORM"] = "xcb"

import math
import subprocess
from PyQt6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, pyqtSlot, QPropertyAnimation, QEasingCurve, QPointF, QRectF, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import QPainter, QRadialGradient, QColor, QBrush, QPen, QFont, QPainterPath, QIcon, QPixmap
from PyQt6.QtDBus import QDBusConnection

# =============================================================================
# GEOMETRY
# =============================================================================
MENU_RADIUS = 150
SHADOW_OFFSET = 12
CENTER_ZONE_RADIUS = 45
ICON_ZONE_RADIUS = 100
WINDOW_SIZE = (MENU_RADIUS + SHADOW_OFFSET) * 2

# =============================================================================
# THEME PALETTES
# =============================================================================
THEMES = {
    'catppuccin-mocha': {
        'crust':    QColor(17, 17, 27),
        'base':     QColor(30, 30, 46),
        'surface0': QColor(49, 50, 68),
        'surface1': QColor(69, 71, 90),
        'surface2': QColor(88, 91, 112),
        'text':     QColor(205, 214, 244),
        'subtext1': QColor(186, 194, 222),
        'lavender': QColor(180, 190, 254),
        'blue':     QColor(137, 180, 250),
        'sapphire': QColor(116, 199, 236),
        'teal':     QColor(148, 226, 213),
        'green':    QColor(166, 227, 161),
        'yellow':   QColor(249, 226, 175),
        'peach':    QColor(250, 179, 135),
        'mauve':    QColor(203, 166, 247),
        'pink':     QColor(245, 194, 231),
        'red':      QColor(243, 139, 168),
    },
    'catppuccin-latte': {
        'crust':    QColor(220, 224, 232),
        'base':     QColor(239, 241, 245),
        'surface0': QColor(204, 208, 218),
        'surface1': QColor(188, 192, 204),
        'surface2': QColor(172, 176, 190),
        'text':     QColor(76, 79, 105),
        'subtext1': QColor(92, 95, 119),
        'lavender': QColor(114, 135, 253),
        'blue':     QColor(30, 102, 245),
        'sapphire': QColor(32, 159, 181),
        'teal':     QColor(23, 146, 153),
        'green':    QColor(64, 160, 43),
        'yellow':   QColor(223, 142, 29),
        'peach':    QColor(254, 100, 11),
        'mauve':    QColor(136, 57, 239),
        'pink':     QColor(234, 118, 203),
        'red':      QColor(210, 15, 57),
    },
    'nord': {
        'crust':    QColor(46, 52, 64),
        'base':     QColor(59, 66, 82),
        'surface0': QColor(67, 76, 94),
        'surface1': QColor(76, 86, 106),
        'surface2': QColor(94, 105, 117),
        'text':     QColor(236, 239, 244),
        'subtext1': QColor(229, 233, 240),
        'lavender': QColor(180, 142, 173),
        'blue':     QColor(129, 161, 193),
        'sapphire': QColor(136, 192, 208),
        'teal':     QColor(143, 188, 187),
        'green':    QColor(163, 190, 140),
        'yellow':   QColor(235, 203, 139),
        'peach':    QColor(208, 135, 112),
        'mauve':    QColor(180, 142, 173),
        'pink':     QColor(180, 142, 173),
        'red':      QColor(191, 97, 106),
    },
    'dracula': {
        'crust':    QColor(33, 34, 44),
        'base':     QColor(40, 42, 54),
        'surface0': QColor(52, 54, 68),
        'surface1': QColor(65, 67, 83),
        'surface2': QColor(78, 80, 98),
        'text':     QColor(248, 248, 242),
        'subtext1': QColor(226, 226, 216),
        'lavender': QColor(189, 147, 249),
        'blue':     QColor(139, 233, 253),
        'sapphire': QColor(139, 233, 253),
        'teal':     QColor(80, 250, 123),
        'green':    QColor(80, 250, 123),
        'yellow':   QColor(241, 250, 140),
        'peach':    QColor(255, 184, 108),
        'mauve':    QColor(189, 147, 249),
        'pink':     QColor(255, 121, 198),
        'red':      QColor(255, 85, 85),
    },
}

def load_theme():
    """Load theme from config file"""
    import json
    from pathlib import Path

    config_path = Path.home() / ".config" / "juhradial" / "config.json"
    theme_name = "catppuccin-mocha"  # Default

    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                theme_name = config.get('theme', 'catppuccin-mocha')
    except Exception as e:
        print(f"Could not load theme from config: {e}")

    # Handle 'system' theme - default to mocha for now
    if theme_name == 'system':
        theme_name = 'catppuccin-mocha'

    if theme_name not in THEMES:
        print(f"Unknown theme '{theme_name}', using catppuccin-mocha")
        theme_name = 'catppuccin-mocha'

    print(f"Loaded theme: {theme_name}")
    return THEMES[theme_name]

# Load theme at startup
COLORS = load_theme()

# =============================================================================
# ACTIONS - 8 slices clockwise from top
# =============================================================================
ACTIONS = [
    ("Play/Pause",   "exec",    "playerctl play-pause",  "green",    "play_pause"),
    ("New Note",     "exec",    "kwrite",                "yellow",   "note"),
    ("Lock",         "exec",    "loginctl lock-session", "red",      "lock"),
    ("Settings",     "settings", "",                     "mauve",    "settings"),
    ("Screenshot",   "exec",    "spectacle",             "blue",     "screenshot"),
    ("Emoji",        "emoji",   "",                      "pink",     "emoji"),
    ("Files",        "exec",    "dolphin",               "sapphire", "folder"),
    ("AI",           "url",     "https://claude.ai",     "teal",     "ai"),
]


def open_settings():
    """Launch the settings dashboard (singleton - only one instance allowed)"""
    # Check if settings is already running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "settings_dashboard.py"],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            print("Settings already running, focusing existing window")
            # Try to focus the existing window using wmctrl
            subprocess.run(
                ["wmctrl", "-a", "JuhRadial"],
                capture_output=True
            )
            return
    except Exception:
        pass

    settings_script = os.path.join(os.path.dirname(__file__), "settings_dashboard.py")
    subprocess.Popen(["python3", settings_script],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class RadialMenu(QWidget):
    # Tap threshold in milliseconds - below this is considered a "tap" (toggle mode)
    TAP_THRESHOLD_MS = 250

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.ToolTip  # ToolTip windows don't appear in taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)
        self.setMouseTracking(True)

        self.highlighted_slice = -1
        self.menu_center_x = 0
        self.menu_center_y = 0

        # Toggle mode: True when menu was opened with a quick tap and stays open
        self.toggle_mode = False
        # Track when menu was shown (for tap detection)
        self.show_time = None

        # D-Bus setup
        bus = QDBusConnection.sessionBus()
        bus.connect("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon", "MenuRequested", "ii", self.on_show)
        # Listen for HideMenu without parameters - we track duration ourselves
        bus.connect("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon", "HideMenu", "", self.on_hide)
        bus.connect("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon", "CursorMoved", "ii", self.on_cursor_moved)

        # Fade animation
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Cursor polling timer for toggle mode (tracks cursor position when menu stays open)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.timeout.connect(self._poll_cursor)
        self.cursor_timer.setInterval(16)  # ~60fps

        print("=" * 60, flush=True)
        print("  JuhRadial MX - PyQt6 Overlay", flush=True)
        print("=" * 60, flush=True)
        print("\n  Modes:", flush=True)
        print(f"    Hold + release: Execute action on release", flush=True)
        print(f"    Quick tap (<{self.TAP_THRESHOLD_MS}ms): Menu stays open, click to select", flush=True)
        print("\n  Actions (clockwise from top):", flush=True)
        directions = ["Top", "Top-Right", "Right", "Bottom-Right",
                     "Bottom", "Bottom-Left", "Left", "Top-Left"]
        for i, action in enumerate(ACTIONS):
            print(f"    {directions[i]:12} -> {action[0]}", flush=True)
        print("\n" + "=" * 60 + "\n", flush=True)

    @pyqtSlot(int, int)
    def on_show(self, x, y):
        import time

        # If already in toggle mode and menu is visible, this is a second tap to close
        if self.toggle_mode and self.isVisible():
            print("OVERLAY: Second tap detected - closing menu")
            self._close_menu(execute=False)
            return

        # Use coordinates from D-Bus signal (daemon gets them via KWin scripting)
        # This works correctly on Plasma 6 Wayland with multiple monitors
        print(f"OVERLAY: MenuRequested at ({x}, {y})")

        self.menu_center_x = x
        self.menu_center_y = y
        self.toggle_mode = False  # Reset toggle mode on new show
        self.show_time = time.time()  # Track when menu was shown

        # Move window so menu is centered at x, y
        self.move(x - WINDOW_SIZE // 2, y - WINDOW_SIZE // 2)
        self.highlighted_slice = -1

        self.show()
        self.raise_()
        self.activateWindow()

        # Note: Cursor polling via QCursor.pos() doesn't work on Wayland while button is held
        # Instead, we use CursorMoved D-Bus signals from daemon which tracks evdev REL events
        # (cursor_timer is started in toggle mode after quick tap)

        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    @pyqtSlot()
    def on_hide(self):
        """Handle HideMenu signal - determine tap vs hold based on time elapsed."""
        import time

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
        distance = math.sqrt(dx * dx + dy * dy)

        if distance < CENTER_ZONE_RADIUS or distance > MENU_RADIUS:
            new_slice = -1
        else:
            # Calculate angle from relative position
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        if new_slice != self.highlighted_slice:
            self.highlighted_slice = new_slice
            self.update()

    def _close_menu(self, execute=True):
        self.cursor_timer.stop()
        self.toggle_mode = False  # Reset toggle mode
        if execute and self.highlighted_slice >= 0:
            self._execute_action(ACTIONS[self.highlighted_slice])
        self.hide()

    def _execute_action(self, action):
        label, cmd_type, cmd = action[0], action[1], action[2]
        print(f"Executing: {label}")

        try:
            if cmd_type == "exec":
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif cmd_type == "url":
                subprocess.Popen(["xdg-open", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif cmd_type == "emoji":
                subprocess.Popen(["plasma-emojier"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif cmd_type == "settings":
                # Launch settings (uses singleton check defined at module level)
                open_settings()
        except Exception as e:
            print(f"Error executing action: {e}")

    def _poll_cursor(self):
        """Poll cursor position for hover detection."""
        pos = QCursor.pos()
        # Use stored center coordinates (reliable on multi-monitor)
        # self.geometry() returns wrong values on XWayland multi-monitor
        cx = self.menu_center_x
        cy = self.menu_center_y

        dx = pos.x() - cx
        dy = pos.y() - cy
        distance = math.sqrt(dx * dx + dy * dy)

        if distance < CENTER_ZONE_RADIUS or distance > MENU_RADIUS:
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        print(f"POLL: slice={new_slice} dist={distance:.0f}", flush=True)
        self.highlighted_slice = new_slice
        self.update()

    def mouseMoveEvent(self, event):
        cx = WINDOW_SIZE / 2
        cy = WINDOW_SIZE / 2
        pos = event.position()
        dx = pos.x() - cx
        dy = pos.y() - cy
        distance = math.sqrt(dx * dx + dy * dy)

        if distance < CENTER_ZONE_RADIUS or distance > MENU_RADIUS:
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        print(f"MOUSE: pos=({pos.x():.0f},{pos.y():.0f}) dist={distance:.0f} slice={new_slice}")
        if new_slice != self.highlighted_slice:
            self.highlighted_slice = new_slice
            self.update()

    def mousePressEvent(self, event):
        """Handle mouse press - used in toggle mode for selection."""
        if self.toggle_mode:
            # In toggle mode, any click selects the current slice or closes
            if event.button() == Qt.MouseButton.LeftButton:
                print(f"OVERLAY: Left click in toggle mode - executing slice {self.highlighted_slice}")
                self._close_menu(execute=True)
            else:
                # Right-click or other button - close without executing
                print("OVERLAY: Non-left click in toggle mode - closing")
                self._close_menu(execute=False)

    def mouseReleaseEvent(self, event):
        """Handle mouse release - only used in non-toggle mode."""
        # In toggle mode, we handle clicks in mousePressEvent
        # This is called for the initial gesture button release via Qt events
        # but the actual logic is in on_hide_with_duration via D-Bus
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._close_menu(execute=False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = WINDOW_SIZE / 2
        cy = WINDOW_SIZE / 2

        # Shadow
        shadow_color = QColor(0, 0, 0, 100)
        p.setBrush(QBrush(shadow_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx + 4, cy + 6), MENU_RADIUS, MENU_RADIUS)

        # Main background
        base_color = COLORS['base']
        base_color.setAlpha(235)
        p.setBrush(QBrush(base_color))
        p.drawEllipse(QPointF(cx, cy), MENU_RADIUS, MENU_RADIUS)

        # Border
        border_color = COLORS['surface2']
        border_color.setAlpha(150)
        p.setPen(QPen(border_color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), MENU_RADIUS, MENU_RADIUS)

        # Draw slices
        for i in range(8):
            self._draw_slice(p, cx, cy, i)

        # Center zone
        self._draw_center(p, cx, cy)

        p.end()

    def _draw_slice(self, p, cx, cy, index):
        is_highlighted = (index == self.highlighted_slice)
        action = ACTIONS[index]
        accent = COLORS[action[3]]

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
            fill = COLORS['surface0']
            fill.setAlpha(80)
        p.setBrush(QBrush(fill))

        # Slice border - subtle, neutral
        if is_highlighted:
            stroke = QColor(255, 255, 255)
            stroke.setAlpha(120)
        else:
            stroke = COLORS['surface2']
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
            icon_bg = COLORS['surface2']
            icon_bg.setAlpha(255)
            # Add subtle glow ring
            glow = QColor(255, 255, 255)
            glow.setAlpha(40)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 3))
            p.drawEllipse(QPointF(icon_x, icon_y), icon_radius + 2, icon_radius + 2)
        else:
            icon_bg = COLORS['surface1']
            icon_bg.setAlpha(230)
        p.setBrush(QBrush(icon_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(icon_x, icon_y), icon_radius, icon_radius)

        # Draw icon - brighter on hover
        if is_highlighted:
            icon_color = COLORS['text']
        else:
            icon_color = COLORS['subtext1']
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
            p.drawRoundedRect(QRectF(cx - w/2, cy - h/2, w, h), 2, 2)
            for i in range(3):
                y = cy - h/4 + i * size * 0.22
                p.drawLine(QPointF(cx - w/3, y), QPointF(cx + w/3, y))

        elif icon_type == "lock":
            # Padlock
            w, h = size * 0.55, size * 0.45
            p.setPen(QPen(color, 2.5))
            p.drawRoundedRect(QRectF(cx - w/2, cy, w, h), 3, 3)
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
                p.drawLine(QPointF(cx + dx * s, cy + dy * (s - corner)),
                          QPointF(cx + dx * s, cy + dy * s))
                p.drawLine(QPointF(cx + dx * s, cy + dy * s),
                          QPointF(cx + dx * (s - corner), cy + dy * s))
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
            p.drawEllipse(QPointF(cx - size * 0.16, cy - size * 0.12), size * 0.055, size * 0.055)
            p.drawEllipse(QPointF(cx + size * 0.16, cy - size * 0.12), size * 0.055, size * 0.055)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Smile arc - smaller and centered
            p.setPen(QPen(color, 1.8))
            path = QPainterPath()
            path.arcMoveTo(QRectF(cx - size * 0.15, cy - size * 0.02, size * 0.30, size * 0.22), 210)
            path.arcTo(QRectF(cx - size * 0.15, cy - size * 0.02, size * 0.30, size * 0.22), 210, 120)
            p.drawPath(path)

        elif icon_type == "folder":
            # Folder icon - cleaner
            w, h = size * 0.65, size * 0.5
            tab_w = w * 0.35
            p.setPen(QPen(color, 2))
            path = QPainterPath()
            path.moveTo(cx - w/2, cy - h/2 + h * 0.25)
            path.lineTo(cx - w/2, cy + h/2)
            path.lineTo(cx + w/2, cy + h/2)
            path.lineTo(cx + w/2, cy - h/2 + h * 0.25)
            path.lineTo(cx - w/2 + tab_w + h * 0.1, cy - h/2 + h * 0.25)
            path.lineTo(cx - w/2 + tab_w, cy - h/2)
            path.lineTo(cx - w/2, cy - h/2)
            path.closeSubpath()
            p.drawPath(path)

        elif icon_type == "ai":
            # Sparkle
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            s = size * 0.35
            path = QPainterPath()
            path.moveTo(cx, cy - s)
            path.cubicTo(cx + s * 0.1, cy - s * 0.1, cx + s * 0.1, cy - s * 0.1, cx + s, cy)
            path.cubicTo(cx + s * 0.1, cy + s * 0.1, cx + s * 0.1, cy + s * 0.1, cx, cy + s)
            path.cubicTo(cx - s * 0.1, cy + s * 0.1, cx - s * 0.1, cy + s * 0.1, cx - s, cy)
            path.cubicTo(cx - s * 0.1, cy - s * 0.1, cx - s * 0.1, cy - s * 0.1, cx, cy - s)
            p.drawPath(path)
            # Small sparkle
            s2 = size * 0.12
            sx, sy = cx + size * 0.3, cy - size * 0.25
            path2 = QPainterPath()
            path2.moveTo(sx, sy - s2)
            path2.cubicTo(sx + s2 * 0.1, sy - s2 * 0.1, sx + s2 * 0.1, sy - s2 * 0.1, sx + s2, sy)
            path2.cubicTo(sx + s2 * 0.1, sy + s2 * 0.1, sx + s2 * 0.1, sy + s2 * 0.1, sx, sy + s2)
            path2.cubicTo(sx - s2 * 0.1, sy + s2 * 0.1, sx - s2 * 0.1, sy + s2 * 0.1, sx - s2, sy)
            path2.cubicTo(sx - s2 * 0.1, sy - s2 * 0.1, sx - s2 * 0.1, sy - s2 * 0.1, sx, sy - s2)
            p.drawPath(path2)

    def _draw_center(self, p, cx, cy):
        # Center background
        base = QColor(COLORS['base'])
        base.setAlpha(247)
        p.setBrush(QBrush(base))
        border = COLORS['surface2']
        border.setAlpha(150)
        p.setPen(QPen(border, 2))
        p.drawEllipse(QPointF(cx, cy), CENTER_ZONE_RADIUS, CENTER_ZONE_RADIUS)

        # Label text
        text = ACTIONS[self.highlighted_slice][0] if self.highlighted_slice >= 0 else "Drag"
        font = QFont("Sans", 11)
        p.setFont(font)
        p.setPen(QPen(COLORS['subtext1']))
        text_rect = QRectF(cx - CENTER_ZONE_RADIUS, cy - 10, CENTER_ZONE_RADIUS * 2, 20)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)


def create_tray_icon(app, radial_menu):
    """Create system tray icon with menu"""
    # Try to load SVG icon, fall back to creating one
    icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "juhradial-mx.svg")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
    else:
        # Create a simple colored circle icon as fallback
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(COLORS['lavender']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        icon = QIcon(pixmap)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("JuhRadial MX")

    # Create context menu
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

    # Settings action
    settings_action = menu.addAction("Settings")
    settings_action.triggered.connect(lambda: open_settings())

    menu.addSeparator()

    # Exit action - also closes settings dashboard if open
    def exit_application():
        import subprocess
        # Kill settings dashboard if running
        subprocess.run(['pkill', '-f', 'settings_dashboard.py'], capture_output=True)
        app.quit()

    exit_action = menu.addAction("Exit")
    exit_action.triggered.connect(exit_application)

    tray.setContextMenu(menu)
    tray.show()

    return tray


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("JuhRadial MX")

    w = RadialMenu()
    tray = create_tray_icon(app, w)

    print("Starting overlay event loop")
    print("System tray icon active - right-click for menu")
    sys.exit(app.exec())
