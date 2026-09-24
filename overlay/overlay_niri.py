"""Reuse the Qt radial menu in an optional native niri layer-shell surface."""

import base64
import time

from PyQt6.QtCore import QBuffer, QEvent, QIODevice, QPointF, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QMouseEvent

import overlay_actions
from overlay_media import actions_use_media_state


def create_niri_menu(base, host):
    class NiriRadialMenu(base):
        def __init__(self):
            self._layer_visible = False
            self._pending_open = False
            self._pending_release = False
            self._frame_pending = False
            self._frame_dirty = False
            self._origin = (0, 0)
            self._serial = 0
            self._host = host
            super().__init__()
            host.attach(self)
            # All pointer coordinates come from the native surface.
            if hasattr(self, "_monitor_watch_timer"):
                self._monitor_watch_timer.stop()

        def _send(self, *message):
            if self._host is not None:
                try:
                    self._host.send(*message)
                except (BrokenPipeError, OSError):
                    self.host_closed()

        def host_closed(self):
            self._host = None
            self.hide()
            print("OVERLAY: niri layer-shell host stopped; restart the overlay", flush=True)

        def isVisible(self):
            return self._layer_visible

        def show(self):
            # Qt stays offscreen. Only the GTK host maps a native surface.
            self._layer_visible = True
            self.update()

        def hide(self):
            self._layer_visible = False
            self._pending_open = False
            self._pending_release = False
            self._anim_timer.stop()
            self.cursor_timer.stop()
            self._send("hide")

        @staticmethod
        def _click_outside_closes():
            # The native surface deliberately passes outside clicks through.
            return False

        def _poll_cursor(self):
            pass

        def _check_monitor_switch(self):
            pass

        @pyqtSlot(int, int)
        def on_cursor_moved(self, _dx, _dy):
            # Daemon deltas are physical pixels; GTK already supplies the
            # surface-local logical coordinates used for both paint and input.
            pass

        @pyqtSlot(int, int)
        def on_show(self, _x, _y):
            now = time.time()
            if now - self._menu_closed_at < 0.03:
                return
            if (self._pending_open or self.isVisible()) and self.show_time and now - self.show_time < 0.03:
                return
            if self.toggle_mode and self.isVisible():
                self._close_menu(execute=False)
                return
            self.show_time = now
            self._pending_open = True
            self._pending_release = False
            self._frame_pending = False
            self._serial += 1
            self._send("show", self._serial)

        @pyqtSlot()
        def on_hide(self):
            if self._pending_open:
                # A tap can finish before Wayland delivers pointer-enter.
                if (time.time() - self.show_time) * 1000 < self.TAP_THRESHOLD_MS:
                    self._pending_release = True
                else:
                    self.hide()
                return
            super().on_hide()
            self.cursor_timer.stop()

        def _open_at_pointer(self, x, y, width, height):
            from i18n import setup_i18n

            overlay_actions._ = setup_i18n()
            overlay_actions.ACTIONS = overlay_actions.load_actions_from_config()
            overlay_actions.COLORS = overlay_actions.load_theme()
            overlay_actions.load_radial_image()
            overlay_actions.MINIMAL_MODE = overlay_actions.load_minimal_mode()
            overlay_actions.ICON_STYLE = overlay_actions.load_icon_style()
            self._apply_ring_scale({"height": height})
            half = self.win_px // 2
            cx = max(half, min(x, width - half))
            cy = max(half, min(y, height - half))
            self._origin = (int(cx - half), int(cy - half))
            self.menu_center_x, self.menu_center_y = cx, cy
            self.toggle_mode = self._pending_release
            self._pending_open = False
            self.submenu_active = False
            self.submenu_slice = -1
            self.highlighted_subitem = -1
            self.highlighted_slice = -1
            self.slice_highlights = [0.0] * 8
            self.flash_slice = -1
            self.flash_progress = 0.0
            self.bloom_progress = 0.0
            self.center_pulse = 0.0
            self._hover_anchors = {}
            self._hover_armed = set()
            self.show()
            self._pointer_motion(x, y)
            self._anim_timer.start()
            if actions_use_media_state(overlay_actions.ACTIONS):
                QTimer.singleShot(0, self._refresh_media_glyph)
            if not self.daemon_iface.isValid():
                from PyQt6.QtDBus import QDBusConnection, QDBusInterface

                self.daemon_iface = QDBusInterface(
                    "org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon", QDBusConnection.sessionBus(),
                )
            self._trigger_haptic("menu_appear")

        def _pointer_motion(self, x, y):
            local = QPointF(x - self._origin[0], y - self._origin[1])
            event = QMouseEvent(QEvent.Type.MouseMove, local, local,
                                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier)
            # Reuse the menu's hit-testing in hold and toggle modes; native
            # events replace its XWayland polling in toggle mode.
            toggle = self.toggle_mode
            self.toggle_mode = False
            super().mouseMoveEvent(event)
            self.toggle_mode = toggle

        def layer_event(self, kind, serial, *args):
            if serial != self._serial:
                return
            if kind == "enter" and self._pending_open:
                self._open_at_pointer(*args)
            elif kind == "motion" and self.isVisible():
                self._pointer_motion(*args)
            elif kind == "leave" and self.isVisible():
                self.highlighted_slice = -1
                self.highlighted_subitem = -1
                self.update()
            elif kind == "click" and self.isVisible() and self.toggle_mode:
                if args[0] in (1, 3):
                    self._close_menu(execute=args[0] == 1)
            elif kind == "escape":
                self._close_menu(execute=False)
            elif kind == "painted":
                self._frame_pending = False
                if self._frame_dirty:
                    self.update()
            elif kind == "unavailable":
                self.hide()
                print(f"OVERLAY: niri menu cancelled: {args[0]}", flush=True)

        def update(self):
            super().update()
            self._frame_dirty = True
            if self.isVisible() and not self._frame_pending:
                self._frame_pending = True
                QTimer.singleShot(0, self._render_frame)

        def _render_frame(self):
            if not self.isVisible():
                self._frame_pending = False
                return
            self._frame_dirty = False
            data = QBuffer()
            data.open(QIODevice.OpenModeFlag.WriteOnly)
            # Offscreen Qt may inherit a desktop scale factor. The GTK host
            # expects logical surface pixels and applies output scaling itself.
            self.grab().toImage().scaled(self.win_px, self.win_px).save(data, "PNG")
            png = base64.b64encode(bytes(data.data())).decode("ascii")
            self._send("frame", self._serial, *self._origin, png)

    return NiriRadialMenu()
