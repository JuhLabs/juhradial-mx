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
import time as _time_mod

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
    QTimer,
)
from PyQt6.QtGui import QCursor, QPainter, QColor, QBrush, QPen, QIcon, QPixmap
from PyQt6.QtDBus import QDBusConnection, QDBusInterface

from overlay_constants import (
    MENU_RADIUS,
    CENTER_ZONE_RADIUS,
    WINDOW_SIZE,
    IS_HYPRLAND,
    IS_GNOME,
    IS_COSMIC,
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
    _init_xlib,
    _xquery_pointer,
    get_cursor_pos,
)
import overlay_actions
from overlay_painting import RadialMenuPaintingMixin
from i18n import _


class RadialMenu(RadialMenuPaintingMixin, QWidget):
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
        self._paint_suppressed = False  # Suppress painting during COSMIC sync

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
        for i, action in enumerate(overlay_actions.ACTIONS):
            print(f"    {directions[i]:12} -> {action[0]}", flush=True)
        print("\n" + "=" * 60 + "\n", flush=True)

    @pyqtSlot(int, int)
    def on_show(self, x, y):
        import time

        # Reload translations for language changes
        from i18n import setup_i18n

        global _
        _ = setup_i18n()

        # Reload actions, theme, and translations from config each time menu is shown
        # This ensures changes from settings are picked up immediately
        overlay_actions.ACTIONS = overlay_actions.load_actions_from_config()
        overlay_actions.COLORS = overlay_actions.load_theme()
        overlay_actions.load_radial_image()

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

        # On COSMIC, XWayland doesn't track the cursor unless it's over an
        # XWayland window.  Use a dedicated raw X11 sync window (truly
        # transparent ARGB, override-redirect) — no Qt overhead, no visual
        # artifacts.  The sync window is separate from the overlay.
        if IS_COSMIC and _HAS_XWAYLAND:
            fresh_pos = get_cursor_position_xwayland_synced()
            if fresh_pos:
                x, y = fresh_pos
                _log(f"COSMIC sync: using position ({x}, {y})")

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

        # Reset submenu state
        self.submenu_active = False
        self.submenu_slice = -1
        self.highlighted_subitem = -1

        # Position and show: set opacity to 0 and move BEFORE show to prevent
        # any visible frame at the wrong location on multi-monitor setups
        self.highlighted_slice = -1
        self.setWindowOpacity(0.0)
        self.move(x - half, y - half)

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

        if new_slice >= 0 and new_slice != self.highlighted_slice:
            action = overlay_actions.ACTIONS[new_slice]
            if action[1] == "submenu" and action[5]:
                self.submenu_active = True
                self.submenu_slice = new_slice
                self.highlighted_subitem = -1

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-TOGGLE] _poll_cursor: slice changed from {self.highlighted_slice} to {new_slice}"
            )
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
        print(f"[MOUSE] mouseMoveEvent called - toggle_mode={self.toggle_mode}")
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

        if new_slice >= 0 and new_slice != self.highlighted_slice:
            action = overlay_actions.ACTIONS[new_slice]
            if action[1] == "submenu" and action[5]:
                self.submenu_active = True
                self.submenu_slice = new_slice
                self.highlighted_subitem = -1

        if new_slice != self.highlighted_slice:
            print(
                f"[HOVER-MOUSE] mouseMoveEvent: slice changed from {self.highlighted_slice} to {new_slice}"
            )
            if new_slice >= 0:
                self._trigger_haptic("slice_change")
            self.highlighted_slice = new_slice
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
            else:
                print("OVERLAY: Non-left click in toggle mode - closing")
                self._close_menu(execute=False)

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

    # Load AI submenu icons and 3D radial image (requires QApplication)
    overlay_actions.load_ai_icons()
    overlay_actions.load_radial_image()

    w = RadialMenu()
    app.tray = create_tray_icon(app, w)

    print("Starting overlay event loop")
    print("System tray icon active - right-click for menu")
    sys.exit(app.exec())
