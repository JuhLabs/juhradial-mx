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
import shlex
import subprocess
from PyQt6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PyQt6.QtCore import (
    Qt,
    pyqtSlot,
    QPropertyAnimation,
    QEasingCurve,
    QPointF,
    QRectF,
    QTimer,
)
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QFontMetrics,
    QPainterPath,
    QIcon,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtDBus import QDBusConnection, QDBusInterface

# =============================================================================
# GEOMETRY
# =============================================================================
MENU_RADIUS = 150
SHADOW_OFFSET = 12
CENTER_ZONE_RADIUS = 45
ICON_ZONE_RADIUS = 100
SUBMENU_EXTEND = 80  # Extra space for submenu items beyond main menu
WINDOW_SIZE = (MENU_RADIUS + SHADOW_OFFSET + SUBMENU_EXTEND) * 2

# =============================================================================
# THEME SYSTEM - Uses shared themes.py module
# =============================================================================
from themes import (
    get_colors,
    load_theme_name,
    get_radial_image,
    get_radial_params,
)
from i18n import _
import settings_constants

# =============================================================================
# CURSOR POSITION HELPERS (Hyprland/Wayland support)
# =============================================================================
IS_HYPRLAND = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") is not None

# Cache for Hyprland socket path
_hyprland_socket = None

# Cache for active monitor offset (refreshed when needed)
_monitor_offset_cache = None


def _get_hyprland_socket():
    """Get Hyprland socket path (cached)."""
    global _hyprland_socket
    if _hyprland_socket is None:
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
        _hyprland_socket = f"{xdg_runtime}/hypr/{sig}/.socket.sock"
    return _hyprland_socket


def _get_focused_monitor_offset():
    """Get the offset of the focused monitor from Hyprland.

    XWayland coordinates are relative to its virtual screen (usually 0,0),
    but Hyprland cursor coordinates are global (include monitor offset).
    We need to subtract the focused monitor's offset to convert.

    Returns:
        Tuple (x_offset, y_offset) or (0, 0) on failure.
    """
    global _monitor_offset_cache
    import socket
    import json

    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.1)
        sock.connect(_get_hyprland_socket())
        # Request JSON format with j/ prefix
        sock.send(b"j/monitors")

        # Read response in chunks
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            except socket.timeout:
                break

        response = b"".join(chunks).decode("utf-8").strip()
        monitors = json.loads(response)

        # Find the focused monitor
        for mon in monitors:
            if mon.get("focused", False):
                x_offset = mon.get("x", 0)
                y_offset = mon.get("y", 0)
                _monitor_offset_cache = (x_offset, y_offset)
                return _monitor_offset_cache

        # Fallback: use first monitor
        if monitors:
            x_offset = monitors[0].get("x", 0)
            y_offset = monitors[0].get("y", 0)
            _monitor_offset_cache = (x_offset, y_offset)
            return _monitor_offset_cache

    except Exception as e:
        print(f"[HYPRLAND] Failed to get monitor offset: {e}")
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass  # Socket already closed

    # Return cached value or default
    return _monitor_offset_cache if _monitor_offset_cache else (0, 0)


def get_cursor_position_hyprland():
    """Get cursor position using Hyprland IPC socket (faster than subprocess).

    Returns coordinates adjusted for XWayland by subtracting the focused
    monitor's offset. This is necessary because Hyprland returns global
    coordinates, but XWayland windows use coordinates relative to their
    virtual screen origin.
    """
    sock = None
    global_x, global_y = None, None

    try:
        import socket

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.05)  # 50ms timeout
        sock.connect(_get_hyprland_socket())
        sock.send(b"cursorpos")
        response = sock.recv(64).decode("utf-8").strip()

        # Parse "x, y" format
        parts = response.split(",")
        if len(parts) >= 2:
            global_x = int(parts[0].strip())
            global_y = int(parts[1].strip())
    except (OSError, ValueError):
        pass  # Socket error or parse failure, fall through to subprocess
    finally:
        # Always close socket to prevent resource leak (called 60x/sec in toggle mode)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass  # Socket already closed

    # Fallback to subprocess if socket fails
    if global_x is None:
        try:
            result = subprocess.run(
                ["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=0.1
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                if len(parts) >= 2:
                    global_x = int(parts[0].strip())
                    global_y = int(parts[1].strip())
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            pass  # hyprctl not available or returned unexpected output

    if global_x is None:
        return None

    # Convert from Hyprland global coordinates to XWayland local coordinates
    # by subtracting the focused monitor's offset
    mon_x, mon_y = _get_focused_monitor_offset()
    local_x = global_x - mon_x
    local_y = global_y - mon_y

    return (local_x, local_y)


def get_cursor_pos():
    """Get cursor position - uses hyprctl on Hyprland, QCursor otherwise."""
    if IS_HYPRLAND:
        pos = get_cursor_position_hyprland()
        if pos:
            return pos
    # Fallback to Qt (works on X11/KDE)
    qpos = QCursor.pos()
    return (qpos.x(), qpos.y())


def hex_to_qcolor(hex_color: str) -> QColor:
    """Convert hex color string to QColor"""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return QColor(r, g, b)


def load_theme() -> dict:
    """Load theme from config and convert to QColor objects"""
    theme_name = load_theme_name()
    hex_colors = get_colors(theme_name)

    # Convert hex colors to QColor objects
    qcolors = {}
    for key, value in hex_colors.items():
        if isinstance(value, str) and value.startswith("#"):
            qcolors[key] = hex_to_qcolor(value)
        elif isinstance(value, str) and value.startswith("rgba"):
            # Skip rgba strings, just use the accent color
            continue

    # Ensure 'lavender' exists (used for accent in ACTIONS)
    if "lavender" not in qcolors and "accent" in qcolors:
        qcolors["lavender"] = qcolors["accent"]

    print(f"Loaded theme: {theme_name}")
    return qcolors


# Load theme at startup
COLORS = load_theme()

# =============================================================================
# 3D RADIAL IMAGE (loaded if theme has radial_image set)
# =============================================================================
RADIAL_IMAGE = None  # QPixmap or None
RADIAL_PARAMS = None  # Per-theme rendering params or None


def load_radial_image():
    """Load the 3D radial wheel image for the current theme, if any."""
    global RADIAL_IMAGE, RADIAL_PARAMS
    image_name = get_radial_image()
    RADIAL_PARAMS = get_radial_params()
    if not image_name:
        RADIAL_IMAGE = None
        return

    # Search paths: development (../assets/radial-wheels/) and installed
    search_paths = [
        os.path.join(
            os.path.dirname(__file__), "..", "assets", "radial-wheels", image_name
        ),
        os.path.join("/usr/share/juhradial/assets/radial-wheels", image_name),
    ]

    for path in search_paths:
        if os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                target_size = (
                    RADIAL_PARAMS.get("image_size", MENU_RADIUS * 2 + 10)
                    if RADIAL_PARAMS
                    else MENU_RADIUS * 2 + 10
                )
                RADIAL_IMAGE = pixmap.scaled(
                    target_size,
                    target_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                print(
                    f"Loaded 3D radial image: {path} ({RADIAL_IMAGE.width()}x{RADIAL_IMAGE.height()})"
                )
                return

    print(f"Warning: 3D radial image '{image_name}' not found")
    RADIAL_IMAGE = None


# NOTE: load_radial_image() is deferred to after QApplication creation.
# QPixmap requires a QApplication instance to exist first.

# =============================================================================
# ACTIONS - 8 slices clockwise from top
# Format: (label, type, command, color, icon, [submenu])
# Submenu format: [(label, type, command, icon), ...]
# =============================================================================
AI_SUBMENU = [
    ("Claude", "url", "https://claude.ai", "claude"),
    ("ChatGPT", "url", "https://chat.openai.com", "chatgpt"),
    ("Gemini", "url", "https://gemini.google.com", "gemini"),
    ("Perplexity", "url", "https://perplexity.ai", "perplexity"),
]

# Easy-Switch submenu - switch between paired hosts
EASY_SWITCH_SUBMENU = [
    ("Host 1", "easy_switch", "0", "host1"),
    ("Host 2", "easy_switch", "1", "host2"),
    ("Host 3", "easy_switch", "2", "host3"),
]

# Default actions (fallback if config not found)
DEFAULT_ACTIONS = [
    ("Play/Pause", "exec", "playerctl play-pause", "green", "play_pause", None),
    ("New Note", "exec", "kwrite", "yellow", "note", None),
    ("Lock", "exec", "loginctl lock-session", "red", "lock", None),
    ("Settings", "settings", "", "mauve", "settings", None),
    ("Screenshot", "exec", "spectacle", "blue", "screenshot", None),
    ("Emoji", "emoji", "", "pink", "emoji", None),
    ("Files", "exec", "dolphin", "sapphire", "folder", None),
    ("AI", "submenu", "", "teal", "ai", AI_SUBMENU),
]

# Icon name mapping from GTK symbolic names to internal icon IDs
ICON_NAME_MAP = {
    "media-playback-start-symbolic": "play_pause",
    "media-skip-forward-symbolic": "next_track",
    "media-skip-backward-symbolic": "prev_track",
    "audio-volume-high-symbolic": "volume_up",
    "audio-volume-low-symbolic": "volume_down",
    "audio-volume-muted-symbolic": "mute",
    "camera-photo-symbolic": "screenshot",
    "system-lock-screen-symbolic": "lock",
    "folder-symbolic": "folder",
    "utilities-terminal-symbolic": "terminal",
    "web-browser-symbolic": "browser",
    "document-new-symbolic": "note",
    "accessories-calculator-symbolic": "calculator",
    "emblem-system-symbolic": "settings",
    "face-smile-symbolic": "emoji",
    "applications-science-symbolic": "ai",
}


def load_actions_from_config():
    """Load radial menu actions from config file"""
    import json
    from pathlib import Path

    config_path = Path.home() / ".config" / "juhradial" / "config.json"

    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            slices = config.get("radial_menu", {}).get("slices", [])
            easy_switch_enabled = config.get("radial_menu", {}).get(
                "easy_switch_shortcuts", False
            )

            if not slices:
                print("No radial_menu slices in config, using defaults")
                return DEFAULT_ACTIONS

            settings_constants._ = _
            settings_constants.refresh_translations()

            actions = []
            for i, slice_data in enumerate(slices):
                action_id = slice_data.get("action_id")
                label = slice_data.get("label", "Action")
                label = settings_constants.translate_radial_label(label, action_id)
                action_type = slice_data.get("type", "exec")
                command = slice_data.get("command", "")
                color = slice_data.get("color", "teal")
                gtk_icon = slice_data.get("icon", "application-x-executable-symbolic")

                # Map GTK icon name to internal icon ID
                icon = ICON_NAME_MAP.get(gtk_icon, "settings")

                # Handle submenu type (use AI_SUBMENU as default)
                submenu = AI_SUBMENU if action_type == "submenu" else None

                # Check if Easy-Switch shortcuts are enabled and this is the Emoji slot (index 5)
                if easy_switch_enabled and i == 5:
                    # Replace Emoji with Easy-Switch submenu
                    label = _("Easy-Switch")
                    action_type = "submenu"
                    icon = "easy_switch"
                    submenu = EASY_SWITCH_SUBMENU
                    print(
                        "Easy-Switch shortcuts enabled - replacing Emoji with Easy-Switch submenu"
                    )

                actions.append((label, action_type, command, color, icon, submenu))

            print(f"Loaded {len(actions)} actions from config")
            return actions

    except Exception as e:
        print(f"Error loading actions from config: {e}")

    return DEFAULT_ACTIONS


# Load actions at startup
ACTIONS = load_actions_from_config()

# =============================================================================
# AI SUBMENU ICONS (SVG)
# =============================================================================
AI_ICONS = {}


def load_ai_icons():
    """Load SVG icons for AI submenu items."""
    global AI_ICONS
    assets_dir = os.path.join(os.path.dirname(__file__), "..", "assets")

    icon_files = {
        "claude": "ai-claude.svg",
        "chatgpt": "ai-chatgpt.svg",
        "gemini": "ai-gemini.svg",
        "perplexity": "ai-perplexity.svg",
    }

    for name, filename in icon_files.items():
        path = os.path.join(assets_dir, filename)
        if os.path.exists(path):
            renderer = QSvgRenderer(path)
            if renderer.isValid():
                AI_ICONS[name] = renderer
                print(f"Loaded AI icon: {name}")
            else:
                print(f"Failed to load AI icon: {path}")
        else:
            print(f"AI icon not found: {path}")


def open_settings():
    """Launch the settings dashboard (GTK4 handles single-instance via D-Bus)"""
    # GTK4/Adwaita application handles single-instance automatically
    # If settings is already running, it will activate the existing window
    settings_script = os.path.join(os.path.dirname(__file__), "settings_dashboard.py")
    subprocess.Popen(
        ["python3", settings_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class RadialMenu(QWidget):
    # Tap threshold in milliseconds - below this is considered a "tap" (toggle mode)
    TAP_THRESHOLD_MS = 250

    def __init__(self):
        super().__init__()
        # Use Popup for menu-like behavior (receives mouse input)
        # ToolTip doesn't receive clicks on Hyprland/XWayland
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Popup  # Popup receives mouse input properly
            | Qt.WindowType.BypassWindowManagerHint  # Skip WM decorations
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)
        self.setMouseTracking(True)
        self.setWindowTitle("JuhRadial MX")  # For window rule matching (Hyprland, etc.)

        self.highlighted_slice = -1
        self.menu_center_x = 0
        self.menu_center_y = 0

        # Sub-menu state
        self.submenu_active = False  # True when showing a submenu
        self.submenu_slice = -1  # Which main slice has active submenu
        self.highlighted_subitem = -1  # Which sub-item is highlighted (-1 = none)

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
        for i, action in enumerate(ACTIONS):
            print(f"    {directions[i]:12} -> {action[0]}", flush=True)
        print("\n" + "=" * 60 + "\n", flush=True)

    @pyqtSlot(int, int)
    def on_show(self, x, y):
        import time

        # Reload translations for language changes
        global _
        from i18n import setup_i18n

        _ = setup_i18n()

        global ACTIONS

        # Reload actions, theme, and translations from config each time menu is shown
        # This ensures changes from settings are picked up immediately
        ACTIONS = load_actions_from_config()

        global COLORS, RADIAL_IMAGE, RADIAL_PARAMS
        COLORS = load_theme()
        load_radial_image()

        # If already in toggle mode and menu is visible, this is a second tap to close
        if self.toggle_mode and self.isVisible():
            print("OVERLAY: Second tap detected - closing menu")
            self._close_menu(execute=False)
            return

        # On Hyprland, re-query cursor position for freshness
        # The D-Bus signal coordinates may be stale due to async timing
        if IS_HYPRLAND:
            fresh_pos = get_cursor_position_hyprland()
            if fresh_pos:
                x, y = fresh_pos
                print(f"OVERLAY: Hyprland fresh cursor position: ({x}, {y})")

        # Use coordinates from D-Bus signal (daemon gets them via KWin scripting)
        # This works correctly on Plasma 6 Wayland with multiple monitors
        print(f"OVERLAY: MenuRequested at ({x}, {y})")

        self.menu_center_x = x
        self.menu_center_y = y
        self.toggle_mode = False  # Reset toggle mode on new show
        self.show_time = time.time()  # Track when menu was shown

        # Reset submenu state
        self.submenu_active = False
        self.submenu_slice = -1
        self.highlighted_subitem = -1

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
        params = RADIAL_PARAMS or {}
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
            self.update()

    def _close_menu(self, execute=True):
        self.cursor_timer.stop()
        self.toggle_mode = False  # Reset toggle mode

        print(
            f"_close_menu: execute={execute}, submenu_active={self.submenu_active}, subitem={self.highlighted_subitem}, slice={self.highlighted_slice}"
        )

        if execute:
            if self.submenu_active and self.highlighted_subitem >= 0:
                # Execute submenu item
                submenu = ACTIONS[self.submenu_slice][5]
                print(
                    f"_close_menu: Executing submenu item {self.highlighted_subitem} from slice {self.submenu_slice}"
                )
                if submenu and self.highlighted_subitem < len(submenu):
                    subitem = submenu[self.highlighted_subitem]
                    print(f"_close_menu: Subitem = {subitem}")
                    self._trigger_haptic("confirm")  # Haptic for selection confirm
                    self._execute_subaction(subitem)
            elif self.highlighted_slice >= 0:
                action = ACTIONS[self.highlighted_slice]
                if action[1] == "submenu":
                    # Don't execute, show submenu instead (handled in toggle mode)
                    pass
                else:
                    self._trigger_haptic("confirm")  # Haptic for selection confirm
                    self._execute_action(action)

        # Reset submenu state
        self.submenu_active = False
        self.submenu_slice = -1
        self.highlighted_subitem = -1
        self.hide()

    def _execute_action(self, action):
        label, cmd_type, cmd = action[0], action[1], action[2]
        print(f"Executing: {label}")

        try:
            if cmd_type == "exec":
                # Use shlex.split for safe command parsing (avoids shell injection)
                try:
                    cmd_args = shlex.split(cmd)
                    subprocess.Popen(
                        cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                except ValueError as e:
                    print(f"Invalid command syntax: {cmd} - {e}")
            elif cmd_type == "url":
                # Ensure cmd doesn't start with - to prevent option injection
                if cmd.startswith("-"):
                    print(f"Invalid URL (starts with -): {cmd}")
                else:
                    subprocess.Popen(
                        ["xdg-open", cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif cmd_type == "emoji":
                subprocess.Popen(
                    ["plasma-emojier"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif cmd_type == "settings":
                # Launch settings (uses singleton check defined at module level)
                open_settings()
            elif cmd_type == "submenu":
                # Submenu - activate it instead of executing
                self.submenu_active = True
                self.submenu_slice = self.highlighted_slice
                self.highlighted_subitem = -1
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
                # Use shlex.split for safe command parsing (avoids shell injection)
                try:
                    cmd_args = shlex.split(cmd)
                    subprocess.Popen(
                        cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                except ValueError as e:
                    print(f"Invalid command syntax: {cmd} - {e}")
            elif cmd_type == "url":
                # Ensure cmd doesn't start with - to prevent option injection
                if cmd.startswith("-"):
                    print(f"Invalid URL (starts with -): {cmd}")
                else:
                    subprocess.Popen(
                        ["xdg-open", cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif cmd_type == "easy_switch":
                # Switch to host via D-Bus call to daemon
                # Validate host_index (Easy-Switch supports 0-2 for 3 hosts)
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
                # Use gdbus for reliable D-Bus call with proper byte typing
                # PyQt6 QDBusMessage doesn't properly handle byte (y) signature
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
        # Use hyprctl on Hyprland (QCursor.pos() doesn't work on XWayland)
        pos_x, pos_y = get_cursor_pos()
        # Use stored center coordinates (reliable on multi-monitor)
        # self.geometry() returns wrong values on XWayland multi-monitor
        cx = self.menu_center_x
        cy = self.menu_center_y

        dx = pos_x - cx
        dy = pos_y - cy
        distance = math.hypot(dx, dy)
        center_radius = self._get_center_radius()

        # Calculate which slice we're over
        if (
            distance < center_radius or distance > MENU_RADIUS + 60
        ):  # Extended range for submenu
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        # Check submenu items if submenu is active
        if self.submenu_active:
            subitem = self._get_subitem_at_position(dx, dy)
            if subitem >= 0:
                # Hovering a subitem
                if subitem != self.highlighted_subitem:
                    self.highlighted_subitem = subitem
                    self.update()
                return
            # Not over a subitem - check if we're still near parent slice
            if new_slice == self.submenu_slice or distance > MENU_RADIUS:
                # Still in submenu area (over parent or in extended range)
                self.highlighted_subitem = -1
                self.update()
                return
            else:
                # Moved to different slice - deactivate submenu
                self.submenu_active = False
                self.submenu_slice = -1
                self.highlighted_subitem = -1

        # Check if hovering over a slice with submenu - activate it
        if new_slice >= 0 and new_slice != self.highlighted_slice:
            action = ACTIONS[new_slice]
            if action[1] == "submenu" and action[5]:
                self.submenu_active = True
                self.submenu_slice = new_slice
                self.highlighted_subitem = -1

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-TOGGLE] _poll_cursor: slice changed from {self.highlighted_slice} to {new_slice}"
            )
            # Trigger haptic for slice change (only when entering a valid slice)
            if new_slice >= 0:
                self._trigger_haptic("slice_change")
            self.highlighted_slice = new_slice
            self.update()
        elif self.submenu_active:
            self.update()

    def _get_subitem_at_position(self, dx, dy):
        """Check if cursor is over a submenu item. Returns item index or -1."""
        if not self.submenu_active or self.submenu_slice < 0:
            return -1

        submenu = ACTIONS[self.submenu_slice][5]
        if not submenu:
            return -1

        # Calculate parent slice angle
        parent_angle = self.submenu_slice * 45 - 90

        # Submenu items are positioned in an arc beyond the main menu
        SUBMENU_RADIUS = MENU_RADIUS + 45  # Distance from center to submenu items
        SUBITEM_SIZE = 32  # Size of each subitem circle

        num_items = len(submenu)
        spread = 15  # Degrees between items

        for i, item in enumerate(submenu):
            # Calculate position of this subitem
            offset = (i - (num_items - 1) / 2) * spread
            item_angle = math.radians(parent_angle + offset)
            item_x = SUBMENU_RADIUS * math.cos(item_angle)
            item_y = SUBMENU_RADIUS * math.sin(item_angle)

            # Check if cursor is within this item
            dist_to_item = math.hypot(dx - item_x, dy - item_y)
            if dist_to_item < SUBITEM_SIZE:
                return i

        return -1

    def mouseMoveEvent(self, event):
        print(f"[MOUSE] mouseMoveEvent called - toggle_mode={self.toggle_mode}")
        cx = WINDOW_SIZE / 2
        cy = WINDOW_SIZE / 2
        pos = event.position()
        dx = pos.x() - cx
        dy = pos.y() - cy
        distance = math.hypot(dx, dy)
        center_radius = self._get_center_radius()

        # Calculate which slice we're over
        if distance < center_radius or distance > MENU_RADIUS + 60:
            new_slice = -1
        else:
            angle = math.degrees(math.atan2(dx, -dy))
            if angle < 0:
                angle += 360
            new_slice = int((angle + 22.5) / 45) % 8

        # Check submenu items if submenu is active
        if self.submenu_active:
            subitem = self._get_subitem_at_position(dx, dy)
            if subitem >= 0:
                if subitem != self.highlighted_subitem:
                    self.highlighted_subitem = subitem
                    self.update()
                return
            # Not over a subitem - check if we're still near parent slice
            if new_slice == self.submenu_slice or distance > MENU_RADIUS:
                self.highlighted_subitem = -1
                self.update()
                return
            else:
                # Moved to different slice - deactivate submenu
                self.submenu_active = False
                self.submenu_slice = -1
                self.highlighted_subitem = -1

        # Check if hovering over a slice with submenu - activate it
        if new_slice >= 0 and new_slice != self.highlighted_slice:
            action = ACTIONS[new_slice]
            if action[1] == "submenu" and action[5]:
                self.submenu_active = True
                self.submenu_slice = new_slice
                self.highlighted_subitem = -1

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-MOUSE] mouseMoveEvent: slice changed from {self.highlighted_slice} to {new_slice}"
            )
            # Trigger haptic for slice change (only when entering a valid slice)
            if new_slice >= 0:
                self._trigger_haptic("slice_change")
            self.highlighted_slice = new_slice
            self.update()
        elif self.submenu_active:
            self.update()

    def mousePressEvent(self, event):
        """Handle mouse press - used in toggle mode for selection."""
        if self.toggle_mode:
            # In toggle mode, any click selects the current slice or closes
            if event.button() == Qt.MouseButton.LeftButton:
                print(
                    f"OVERLAY: Left click in toggle mode - slice={self.highlighted_slice}, submenu_active={self.submenu_active}, subitem={self.highlighted_subitem}"
                )
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

        if RADIAL_IMAGE is not None:
            # === 3D Image Mode ===
            # Draw the pre-rendered 3D radial wheel image centered
            img_x = cx - RADIAL_IMAGE.width() / 2
            img_y = cy - RADIAL_IMAGE.height() / 2
            p.drawPixmap(int(img_x), int(img_y), RADIAL_IMAGE)

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
            base_color = QColor(COLORS["base"])
            base_color.setAlpha(235)
            p.setBrush(QBrush(base_color))
            p.drawEllipse(QPointF(cx, cy), MENU_RADIUS, MENU_RADIUS)

            # Border
            border_color = QColor(COLORS["surface2"])
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
        params = RADIAL_PARAMS or {}
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
        params = RADIAL_PARAMS or {}
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
        action = ACTIONS[index]

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
        action = ACTIONS[index]

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
            fill = COLORS["surface0"]
            fill.setAlpha(80)
        p.setBrush(QBrush(fill))

        # Slice border - subtle, neutral
        if is_highlighted:
            stroke = QColor(255, 255, 255)
            stroke.setAlpha(120)
        else:
            stroke = COLORS["surface2"]
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
            icon_bg = COLORS["surface2"]
            icon_bg.setAlpha(255)
            # Add subtle glow ring
            glow = QColor(255, 255, 255)
            glow.setAlpha(40)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 3))
            p.drawEllipse(QPointF(icon_x, icon_y), icon_radius + 2, icon_radius + 2)
        else:
            icon_bg = COLORS["surface1"]
            icon_bg.setAlpha(230)
        p.setBrush(QBrush(icon_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(icon_x, icon_y), icon_radius, icon_radius)

        # Draw icon - brighter on hover
        if is_highlighted:
            icon_color = COLORS["text"]
        else:
            icon_color = COLORS["subtext1"]
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
        submenu = ACTIONS[self.submenu_slice][5]
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
                bg = COLORS["surface2"]
                bg.setAlpha(255)
                # Glow ring
                glow = QColor(255, 255, 255, 60)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(glow, 3))
                p.drawEllipse(
                    QPointF(item_x, item_y), SUBITEM_RADIUS + 3, SUBITEM_RADIUS + 3
                )
            else:
                bg = COLORS["surface1"]
                bg.setAlpha(240)

            p.setBrush(QBrush(bg))
            border = (
                COLORS["surface2"] if not is_highlighted else QColor(255, 255, 255, 150)
            )
            p.setPen(QPen(border, 1.5))
            p.drawEllipse(QPointF(item_x, item_y), SUBITEM_RADIUS, SUBITEM_RADIUS)

            # Icon - use SVG if available, fallback to drawn icon
            icon_name = item[3]  # e.g., "claude", "chatgpt", etc.
            if icon_name in AI_ICONS:
                # Render SVG icon
                icon_size = SUBITEM_RADIUS * 1.4  # Size of icon
                icon_rect = QRectF(
                    item_x - icon_size / 2, item_y - icon_size / 2, icon_size, icon_size
                )
                AI_ICONS[icon_name].render(p, icon_rect)
            else:
                # Fallback to drawn icon
                icon_color = COLORS["text"] if is_highlighted else COLORS["subtext1"]
                self._draw_icon(
                    p, item_x, item_y, icon_name, SUBITEM_RADIUS * 0.7, icon_color
                )

    def _draw_center(self, p, cx, cy):
        params = RADIAL_PARAMS or {}
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
            base = QColor(COLORS["base"])
            base.setAlpha(247)
            p.setBrush(QBrush(base))
            border = QColor(COLORS["surface2"])
            border.setAlpha(150)
            p.setPen(QPen(border, 2))
            p.drawEllipse(QPointF(cx, cy), center_radius, center_radius)
            text_color = QColor(COLORS["subtext1"])

        # Label text - show submenu item name if hovering one
        if self.submenu_active and self.highlighted_subitem >= 0:
            submenu = ACTIONS[self.submenu_slice][5]
            text = submenu[self.highlighted_subitem][0] if submenu else "AI"
        elif self.highlighted_slice >= 0:
            text = ACTIONS[self.highlighted_slice][0]
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


def create_tray_icon(app, radial_menu):
    """Create system tray icon with menu"""
    # Try to load SVG icon, fall back to creating one
    icon_path = os.path.join(
        os.path.dirname(__file__), "..", "assets", "juhradial-mx.svg"
    )
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
    else:
        # Create a simple colored circle icon as fallback
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(COLORS["lavender"]))
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
    settings_action = menu.addAction(_("Settings"))
    settings_action.triggered.connect(open_settings)

    menu.addSeparator()

    # Exit action - also closes settings dashboard if open
    def exit_application():
        import subprocess
        import os

        # Kill settings dashboard if running
        uid = str(os.getuid())
        subprocess.run(["pkill", "-u", uid, "-f", "settings_dashboard.py"], capture_output=True)
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
    app.setDesktopFileName("juhradial-overlay")  # For Wayland compositor identification

    # Load AI submenu icons and 3D radial image (requires QApplication)
    load_ai_icons()
    load_radial_image()

    w = RadialMenu()
    app.tray = create_tray_icon(app, w)  # Store reference on app to prevent GC

    print("Starting overlay event loop")
    print("System tray icon active - right-click for menu")
    sys.exit(app.exec())
