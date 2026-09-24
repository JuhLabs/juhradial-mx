"""Tray icon status for the overlay.

The tray tooltip names the mouse, its battery and charging state, the
Easy-Switch host (with the host's name when the mouse knows it) and the
per-app profile the daemon is applying. The icon carries a small badge: the
profile's initial while a per-app hardware profile is active, red while the
battery is low. A low battery also raises one desktop notification per
discharge, for the mouse and (with MX Keys S support on) the keyboard, at the
level set in Settings (`battery.alert_percent`, 15 by default) with a 5 point
hysteresis.

Everything is driven by the daemon's signals (BatteryChanged, HostChanged,
DeviceNameRefreshed, ActiveProfileChanged) after one asynchronous prime, so
the tooltip follows a change within the signal's own latency and the overlay
never blocks on the daemon's device lock.
"""

import json
import subprocess
from pathlib import Path

from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

try:
    from PyQt6.QtDBus import (
        QDBusConnection,
        QDBusInterface,
        QDBusMessage,
        QDBusPendingCallWatcher,
        QDBusPendingReply,
    )
    _HAVE_DBUS = True
except Exception:  # pragma: no cover - QtDBus ships with PyQt6 on Linux
    _HAVE_DBUS = False

BUS_NAME = "org.kde.juhradialmx"
OBJ_PATH = "/org/kde/juhradialmx/Daemon"
IFACE = "org.kde.juhradialmx.Daemon"

APP_NAME = "JuhRadial MX"
LOW_BATTERY = 15
CONFIG_PATH = Path.home() / ".config" / "juhradial" / "config.json"
BADGE_LOW = "#E5484D"
BADGE_PROFILE = "#3B82F6"


def _int(v):
    """A D-Bus scalar as int; PyQt6 hands a `y` byte over as bytes."""
    if isinstance(v, (bytes, bytearray)):
        return v[0] if v else 0
    return int(v)


def tooltip(device, percent, charging, host, num_hosts, host_names, profile):
    """The tray tooltip lines: app, device with battery, host, profile."""
    lines = [APP_NAME]
    if device:
        if percent is None:
            battery = "battery unknown"
        else:
            battery = f"{percent}%" + (", charging" if charging else "")
        lines.append(f"{device}: {battery}")
    if num_hosts:
        line = f"Host {host + 1} of {num_hosts}"
        name = host_names[host] if 0 <= host < len(host_names) else ""
        if name:
            line += f": {name}"
        lines.append(line)
    if profile:
        lines.append(f"Profile: {profile}")
    return "\n".join(lines)


def badge_letter(profile):
    """The glyph drawn on the icon for an active per-app profile."""
    return profile[:1].upper() if profile else ""


def render_icon(base, letter, low, size=64):
    """`base` with a badge in the bottom-right corner: `letter` (profile
    initial) on a blue disc, or on a red disc when `low`; a red dot when only
    `low`. Returns `base` untouched when neither applies."""
    if not letter and not low:
        return base
    source = base.pixmap(size, size)
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if not source.isNull():
        painter.drawPixmap((size - source.width()) // 2, (size - source.height()) // 2, source)
    diameter = size * (0.44 if letter else 0.34)
    rect = QRectF(size - diameter - 1, size - diameter - 1, diameter, diameter)
    painter.setPen(QPen(QColor(0, 0, 0, 170), max(1.0, size / 32)))
    painter.setBrush(QColor(BADGE_LOW if low else BADGE_PROFILE))
    painter.drawEllipse(rect)
    if letter:
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(diameter * 0.64))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return QIcon(canvas)


def battery_alerts(path=CONFIG_PATH):
    """The `battery` config: (alert percent, alert for the mouse, for the keyboard)."""
    try:
        cfg = json.loads(Path(path).read_text()).get("battery") or {}
        pct = int(cfg.get("alert_percent", LOW_BATTERY))
    except (OSError, ValueError, TypeError, AttributeError):
        cfg, pct = {}, LOW_BATTERY
    return (max(5, min(50, pct)), bool(cfg.get("alert_mouse", True)),
            bool(cfg.get("alert_keyboard", True)))


def notify_low_battery(device, percent, kind="mouse"):
    title = "Keyboard battery low" if kind == "keyboard" else "Mouse battery low"
    fallback = "The keyboard" if kind == "keyboard" else "The mouse"
    try:
        subprocess.Popen(
            ["notify-send", "-a", APP_NAME, "-i", "battery-low-symbolic", "-u", "critical",
             title, f"{device or fallback} is at {percent}%. Time to recharge."])
    except Exception:
        pass


def _low_step(owner, latch, percent, charging, level):
    """One low-battery latch: True once when a device on battery reaches
    `level`; re-arms after charging or above level + 5. 0 % = not read yet."""
    if charging or percent > level + 5:
        setattr(owner, latch, False)
        return False
    if percent <= 0 or percent > level or getattr(owner, latch):
        return False
    setattr(owner, latch, True)
    return True


class TrayStatus(QObject):
    """Keeps a QSystemTrayIcon's tooltip and badge in step with the daemon."""

    def __init__(self, tray, base_icon, bus=None, notify=notify_low_battery, parent=None,
                 on_profile=None, alerts=battery_alerts):
        super().__init__(parent)
        self.on_profile = on_profile
        self.tray = tray
        self.base_icon = base_icon
        self.notify = notify
        self.alerts = alerts
        self.device = ""
        self.percent = None
        self.charging = False
        self.host = 0
        self.num_hosts = 0
        self.host_names = []
        self.profile = ""
        self.gaming = False
        self.gaming_action = None
        self._low_notified = False
        self._kb_low_notified = False
        self._alert_level = LOW_BATTERY
        self._watchers = set()
        self._bus = None
        self._iface = None
        if bus is None and _HAVE_DBUS:
            bus = QDBusConnection.sessionBus()
        # bus=False: no D-Bus at all (tests); None: the session bus.
        if bus and bus.isConnected():
            self._bus = bus
            self._iface = QDBusInterface(BUS_NAME, OBJ_PATH, IFACE, bus)
            # Empty service name: survive a daemon restart.
            bus.connect("", OBJ_PATH, IFACE, "BatteryChanged", self._on_battery)
            bus.connect("", OBJ_PATH, IFACE, "HostChanged", self._on_host)
            bus.connect("", OBJ_PATH, IFACE, "DeviceNameRefreshed", self._on_device_name)
            bus.connect("", OBJ_PATH, IFACE, "ActiveProfileChanged", self._on_profile)
            bus.connect("", OBJ_PATH, IFACE, "GamingModeChanged", self._on_gaming)
            # Sent when a key press re-links the MX Keys S (support on).
            bus.connect("", OBJ_PATH, IFACE, "KeyboardBatteryChanged", self._on_kb_battery)
        self.refresh()
        self.prime()

    # ---- state ----
    def set_battery(self, percent, status):
        self.percent = percent
        # Same rule as the daemon's GetBatteryStatus bool: "full" and
        # "not_charging" arrive with a cable in but are not charging.
        self.charging = status == "charging"
        level, on, _kb = self.alerts()
        self._alert_level = level
        if _low_step(self, "_low_notified", percent, self.charging, level) and on:
            self.notify(self.device, percent)
        self.refresh()

    def set_keyboard_battery(self, percent, charging):
        level, _mouse, on = self.alerts()
        if _low_step(self, "_kb_low_notified", percent, charging, level) and on:
            self.notify("", percent, "keyboard")

    def set_host(self, host):
        self.host = host
        self.refresh()

    def set_device(self, name):
        if name:
            self.device = name
        self.refresh()

    def set_profile(self, profile):
        self.profile = profile
        if self.on_profile is not None:
            self.on_profile(profile)
        self.refresh()

    def set_gaming(self, on):
        self.gaming = bool(on)
        if self.gaming_action is not None:
            self.gaming_action.setChecked(self.gaming)

    def bind_gaming_action(self, action):
        """A checkable tray entry that switches gaming mode and follows it
        (Settings, a button, automatic mode)."""
        self.gaming_action = action
        action.setCheckable(True)
        action.setChecked(self.gaming)
        # triggered, not toggled: only a click sends, never our own setChecked.
        action.triggered.connect(self._toggle_gaming)

    def _toggle_gaming(self, checked):
        if self._iface is not None:
            self._iface.asyncCall("SetGamingMode", bool(checked))

    @property
    def low(self):
        return self.percent is not None and self.percent <= self._alert_level and not self.charging

    def refresh(self):
        self.tray.setToolTip(tooltip(self.device, self.percent, self.charging, self.host,
                                     self.num_hosts, self.host_names, self.profile))
        self.tray.setIcon(render_icon(self.base_icon, badge_letter(self.profile), self.low))

    # ---- daemon signals (the full QDBusMessage is delivered) ----
    @pyqtSlot(QDBusMessage)
    def _on_battery(self, msg):
        try:
            a = msg.arguments()
            self.set_battery(_int(a[0]), str(a[1]))
        except Exception:
            pass

    @pyqtSlot(QDBusMessage)
    def _on_kb_battery(self, msg):
        try:
            a = msg.arguments()
            self.set_keyboard_battery(_int(a[0]), bool(a[1]))
        except Exception:
            pass

    @pyqtSlot(QDBusMessage)
    def _on_host(self, msg):
        try:
            self.set_host(_int(msg.arguments()[0]))
        except Exception:
            pass

    @pyqtSlot(QDBusMessage)
    def _on_device_name(self, msg):
        try:
            self.set_device(str(msg.arguments()[0]))
        except Exception:
            pass
        # The mouse just came online: its hosts and battery may be new too.
        self.prime()

    @pyqtSlot(QDBusMessage)
    def _on_gaming(self, msg):
        try:
            self.set_gaming(bool(msg.arguments()[0]))
        except Exception:
            pass

    @pyqtSlot(QDBusMessage)
    def _on_profile(self, msg):
        try:
            self.set_profile(str(msg.arguments()[0]))
        except Exception:
            pass

    # ---- priming (async, never blocks the overlay) ----
    def prime(self):
        if self._iface is None:
            return
        self._call_then("GetDeviceName", lambda a: self.set_device(str(a[0])))
        self._call_then("GetBatteryStatus", lambda a: self.set_battery(_int(a[0]), "charging" if a[1] else ""))
        self._call_then("GetEasySwitchInfo", self._set_easy_switch)
        self._call_then("GetHostNames", self._set_host_names)
        self._call_then("GetGamingMode", lambda a: self.set_gaming(bool(a[0])))

    def _set_easy_switch(self, a):
        self.num_hosts, self.host = _int(a[0]), _int(a[1])
        self.refresh()

    def _set_host_names(self, a):
        self.host_names = [str(n) for n in (a[0] or [])]
        self.refresh()

    def _call_then(self, method, callback):
        watcher = QDBusPendingCallWatcher(self._iface.asyncCall(method), self)
        self._watchers.add(watcher)

        def finished(w):
            # PyQt6 binds no reply() on the watcher; QDBusPendingReply wraps
            # it. A Python exception inside a Qt slot aborts the process.
            self._watchers.discard(w)
            try:
                reply = QDBusPendingReply(w)
                args = None if reply.isError() else list(reply.reply().arguments())
            except Exception:
                args = None
            finally:
                w.deleteLater()
            if not args:
                return
            try:
                callback(args)
            except Exception:
                pass
        watcher.finished.connect(finished)
