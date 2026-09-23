"""Backend bridge for the JuhRadial MX Qt/QML settings app.

Single source of truth between the QML front-end and the system:
  * reads/writes ~/.config/juhradial/config.json (atomic: temp + rename),
  * talks to the running daemon over D-Bus (org.kde.juhradialmx),
  * exposes live hardware state (battery, DPI, host, ratchet) via NOTIFY props.

The schema and D-Bus calls mirror the shipped GTK app exactly, so the running
daemon (v0.4.x) honours every change. Almost every write follows one pattern:
atomically persist config.json, then call ReloadConfig() - the daemon re-applies
button diverts, thumb-wheel divert and haptic patterns on reload. Only direct
hardware actions (DPI, SmartShift, host switch, haptic test, gaming) issue a
dedicated D-Bus method.
"""
import json
import os
import shutil
import subprocess
import sys
import pathlib
import copy
import tempfile
import threading
import time
import re

from PyQt6.QtCore import (
    QObject, pyqtSlot, pyqtProperty, pyqtSignal, QTimer, QCoreApplication,
    QAbstractListModel, QModelIndex, Qt, QByteArray, QUrl,
)

from PyQt6.QtCore import QMetaType, QSize
from PyQt6.QtGui import QIcon

try:
    from PyQt6.QtDBus import (QDBusArgument, QDBusConnection, QDBusInterface,
                              QDBusMessage, QDBusPendingCallWatcher,
                              QDBusPendingReply, QDBusServiceWatcher)
    _HAVE_DBUS = True
except Exception:  # pragma: no cover - QtDBus should be present
    _HAVE_DBUS = False

_XDG_CONFIG = pathlib.Path(os.environ.get("XDG_CONFIG_HOME",
                                          str(pathlib.Path.home() / ".config")))
CONFIG_DIR = _XDG_CONFIG / "juhradial"
CONFIG = CONFIG_DIR / "config.json"
PROFILES = CONFIG_DIR / "profiles.json"
AUTOSTART = _XDG_CONFIG / "autostart" / "juhradial-mx.desktop"

# Actions Ring geometry (Settings → Appearance): the overlay's defaults
# (overlay_constants MENU_RADIUS / CENTER_ZONE_RADIUS) and the clamps the GTK
# app applies in settings_config; tests/test_settings_qt_parity.py pins both.
RING_OUTER_DEFAULT, RING_INNER_DEFAULT = 150, 45
RING_OUTER_MIN, RING_OUTER_MAX = 80, 250
RING_INNER_MIN, RING_INNER_MARGIN = 20, 30

# Desktop Entry Exec field codes (%f %u %F %U ...) and the literal %%.
_FIELD_CODE_RE = re.compile(r"%%|%[fFuUdDnNickvm]")

BUS_NAME = "org.kde.juhradialmx"
OBJ_PATH = "/org/kde/juhradialmx/Daemon"
IFACE = "org.kde.juhradialmx.Daemon"

# ---------------------------------------------------------------------------
# Vocabulary (mirrors overlay/settings_constants.py + daemon config enums)
# ---------------------------------------------------------------------------

# Physical button -> default ButtonAction (daemon config.rs defaults).
BUTTON_SLOTS = [
    ("gesture", "Gesture Button", "virtual_desktops"),
    ("thumb", "Thumb Button", "radial_menu"),
    ("middle", "Middle Click", "middle_click"),
    ("shift_wheel", "Shift Wheel", "smartshift"),
    ("forward", "Forward", "forward"),
    ("back", "Back", "back"),
    ("horizontal_scroll", "Thumb Wheel Click", "scroll_left_right"),
]

# (id, label, freedesktop icon) for physical-button assignment (daemon ButtonAction).
BUTTON_ACTIONS = [
    ("radial_menu", "Radial Menu", "view-grid-symbolic"),
    ("virtual_desktops", "Virtual Desktops", "view-app-grid-symbolic"),
    ("middle_click", "Middle Click", "input-mouse-symbolic"),
    ("back", "Back", "go-previous-symbolic"), ("forward", "Forward", "go-next-symbolic"),
    ("copy", "Copy", "edit-copy-symbolic"), ("paste", "Paste", "edit-paste-symbolic"),
    ("undo", "Undo", "edit-undo-symbolic"), ("redo", "Redo", "edit-redo-symbolic"),
    ("screenshot", "Screenshot", "camera-photo-symbolic"),
    ("smartshift", "SmartShift", "emblem-synchronizing-symbolic"),
    ("scroll_left_right", "Scroll Left/Right", "object-flip-horizontal-symbolic"),
    ("volume_up", "Volume Up", "audio-volume-high-symbolic"),
    ("volume_down", "Volume Down", "audio-volume-low-symbolic"),
    ("play_pause", "Play/Pause", "media-playback-start-symbolic"),
    ("mute", "Mute", "audio-volume-muted-symbolic"),
    ("zoom_in", "Zoom In", "zoom-in-symbolic"), ("zoom_out", "Zoom Out", "zoom-out-symbolic"),
    ("show_desktop", "Show Desktop", "user-desktop-symbolic"),
    ("switch_desktop_left", "Desktop Left", "go-previous-symbolic"),
    ("switch_desktop_right", "Desktop Right", "go-next-symbolic"),
    ("task_switcher", "Task Switcher", "view-paged-symbolic"),
    ("close_window", "Close Window", "window-close-symbolic"),
    ("lock_screen", "Lock Screen", "system-lock-screen-symbolic"),
    ("calculator", "Calculator", "accessories-calculator-symbolic"),
    ("none", "Disabled", "action-unavailable-symbolic"),
]

# Radial-slice action presets: (action_id, label, icon, type, command, color)
RADIAL_ACTIONS = [
    ("play_pause", "Play/Pause", "media-playback-start-symbolic", "exec", "playerctl play-pause", "green"),
    ("screenshot", "Screenshot", "camera-photo-symbolic", "exec", "spectacle", "blue"),
    ("lock", "Lock Screen", "system-lock-screen-symbolic", "exec", "loginctl lock-session", "red"),
    ("settings", "Settings", "emblem-system-symbolic", "settings", "", "mauve"),
    ("files", "Files", "folder-symbolic", "exec", "dolphin", "sapphire"),
    ("emoji", "Emoji Picker", "face-smile-symbolic", "emoji", "", "pink"),
    ("new_note", "New Note", "document-new-symbolic", "exec", "kwrite", "yellow"),
    ("ai", "AI Assistant", "applications-science-symbolic", "submenu", "", "teal"),
    ("copy", "Copy", "edit-copy-symbolic", "shortcut", "ctrl+c", "blue"),
    ("paste", "Paste", "edit-paste-symbolic", "shortcut", "ctrl+v", "blue"),
    ("undo", "Undo", "edit-undo-symbolic", "shortcut", "ctrl+z", "blue"),
    ("redo", "Redo", "edit-redo-symbolic", "shortcut", "ctrl+shift+z", "blue"),
    ("cut", "Cut", "edit-cut-symbolic", "shortcut", "ctrl+x", "blue"),
    ("select_all", "Select All", "edit-select-all-symbolic", "shortcut", "ctrl+a", "blue"),
    ("close_window", "Close Window", "window-close-symbolic", "shortcut", "alt+F4", "red"),
    ("minimize", "Minimize", "window-minimize-symbolic", "shortcut", "super+h", "blue"),
    ("volume_up", "Volume Up", "audio-volume-high-symbolic", "exec", "pactl set-sink-volume @DEFAULT_SINK@ +5%", "green"),
    ("volume_down", "Volume Down", "audio-volume-low-symbolic", "exec", "pactl set-sink-volume @DEFAULT_SINK@ -5%", "green"),
    ("mute", "Mute", "audio-volume-muted-symbolic", "exec", "pactl set-sink-mute @DEFAULT_SINK@ toggle", "red"),
    ("next_track", "Next Track", "media-skip-forward-symbolic", "exec", "playerctl next", "green"),
    ("prev_track", "Previous Track", "media-skip-backward-symbolic", "exec", "playerctl previous", "green"),
    ("none", "Do Nothing", "action-unavailable-symbolic", "none", "", "gray"),
]

# Catppuccin-Mocha slice colours (name -> hex), used by the radial editor swatches.
SLICE_COLORS = {
    "green": "#A6E3A1", "yellow": "#F9E2AF", "red": "#F38BA8", "mauve": "#CBA6F7",
    "blue": "#89B4FA", "pink": "#F5C2E7", "sapphire": "#74C7EC", "teal": "#94E2D5",
    "peach": "#FAB387", "lavender": "#B4BEFE", "orange": "#FAB387", "purple": "#CBA6F7",
    "gray": "#9399B2",
}
SLICE_COLOR_ORDER = ["green", "yellow", "peach", "red", "pink", "mauve",
                     "blue", "sapphire", "teal"]

# 16 MX Master 4 haptic waveforms (id == display via title-case).
HAPTIC_PATTERNS = [
    "sharp_state_change", "damp_state_change", "sharp_collision", "damp_collision",
    "subtle_collision", "whisper_collision", "happy_alert", "angry_alert",
    "completed", "square", "wave", "firework", "mad", "knock", "jingle", "ringing",
]

THUMBWHEEL_MODES = [("off", "Off"), ("volume", "Volume"),
                    ("scroll", "Scroll"), ("zoom", "Zoom")]
SCROLL_MODES = [("ratchet", "Ratchet"), ("smartshift", "SmartShift"), ("freespin", "Free-spin")]
EASY_SWITCH_OS = [("linux", "Linux"), ("windows", "Windows"), ("macos", "macOS"),
                  ("ios", "iOS"), ("android", "Android"), ("chromeos", "ChromeOS"),
                  ("unknown", "Unknown")]
DESKTOP_ENVS = [("auto", "Auto-detect"), ("kde", "KDE Plasma"), ("gnome", "GNOME"),
                ("cosmic", "COSMIC"), ("generic", "Generic / Other")]
LANGUAGES = [("en", "English"), ("de", "Deutsch"), ("fr", "Francais"),
             ("es", "Espanol"), ("it", "Italiano"), ("pt_BR", "Portugues"),
             ("ru", "Russian"), ("ja", "Japanese"), ("ko", "Korean"), ("zh_CN", "Chinese")]

# ---------------------------------------------------------------------------
# Global search index. One entry per searchable setting across every tab.
# `label` MUST match the SettingRow `label:` verbatim where one exists, so the
# page can flash + scroll to the exact row when a result is chosen (rows that
# are not SettingRows still jump to the right tab). (tab_key, label, section,
# keywords). Tab labels are resolved from TAB_LABELS.
# ---------------------------------------------------------------------------
TAB_LABELS = {
    "dashboard": "Dashboard", "buttons": "Buttons", "scroll": "Point & Scroll",
    "haptics": "Haptics", "macros": "Macros", "apps": "App profiles",
    "easyswitch": "Easy-Switch", "devices": "Devices", "gaming": "Gaming",
    "flow": "Flow", "themes": "Themes", "settings": "Settings",
}

SEARCH_INDEX = [
    # Dashboard
    ("dashboard", "Battery", "", "battery charge level power percent remaining"),
    ("dashboard", "Device status", "", "connected daemon status overview offline"),
    # Buttons - physical button map
    ("buttons", "Gesture button", "Button mapping", "gesture thumb gestures virtual desktops remap assign"),
    ("buttons", "Thumb button", "Button mapping", "thumb radial menu remap assign"),
    ("buttons", "Wheel click", "Button mapping", "middle click wheel button remap assign"),
    ("buttons", "Mode shift", "Button mapping", "shift wheel smartshift mode remap assign"),
    ("buttons", "Forward", "Button mapping", "forward navigation button remap assign"),
    ("buttons", "Back", "Button mapping", "back navigation button remap assign"),
    ("buttons", "Thumb wheel", "Button mapping", "horizontal scroll thumb wheel click remap"),
    ("buttons", "Radial menu actions", "Radial menu", "radial slice action edit eight thumb wheel"),
    ("buttons", "Wheel skin", "Radial menu", "wheel skin appearance icon style azure obsidian"),
    # Point & Scroll
    ("scroll", "Sensitivity", "Pointer", "dpi pointer tracking speed sensitivity cursor"),
    ("scroll", "Pointer acceleration", "Pointer", "acceleration speed fast slow motion"),
    ("scroll", "Wheel mode", "Scroll wheel", "ratchet free-spin smartshift click glide"),
    ("scroll", "SmartShift sensitivity", "Scroll wheel", "smartshift threshold flick auto-switch"),
    ("scroll", "Natural scrolling", "Scroll wheel", "natural scrolling direction content follows reverse"),
    ("scroll", "Smooth (high-res) scrolling", "Scroll wheel", "smooth high-res scrolling fine precision hires"),
    ("scroll", "Scroll speed", "Scroll wheel", "scroll speed lines notch velocity"),
    ("scroll", "Action", "Thumb wheel", "thumb wheel action mode purpose volume zoom"),
    ("scroll", "Invert direction", "Thumb wheel", "invert direction reverse scroll rotation thumb wheel"),
    ("scroll", "Speed", "Thumb wheel", "thumb wheel speed repeats rotation tick velocity"),
    # Haptics
    ("haptics", "Intensity", "Haptic feedback", "intensity strength vibration motor haptic"),
    ("haptics", "Menu opens", "Feedback patterns", "haptic pattern menu appear open vibrate"),
    ("haptics", "Slice change", "Feedback patterns", "haptic pattern slice change rotate select"),
    ("haptics", "Confirm", "Feedback patterns", "haptic pattern confirm accept action success"),
    ("haptics", "Invalid", "Feedback patterns", "haptic pattern invalid error action"),
    ("haptics", "Default pattern", "Default pattern", "default haptic pattern fallback vibration"),
    # Macros
    ("macros", "Macro name", "Macros", "macro name label record replay automation"),
    ("macros", "Record macro", "Macros", "record macro capture keystrokes new"),
    ("macros", "Trigger", "Macros", "bind trigger button assign macro invoke hotkey"),
    # App profiles
    ("apps", "App profiles", "", "per-app application profile dpi smartshift focus window class"),
    ("apps", "Add application", "", "add app profile window class per-app override"),
    # Easy-Switch
    ("easyswitch", "Easy-Switch shortcuts in radial menu", "Easy-Switch", "easy-switch radial menu slices host-switch"),
    ("easyswitch", "Operating system", "Paired computers", "easy-switch host os operating system computer"),
    ("easyswitch", "Switch host", "Paired computers", "switch host computer change device channel"),
    # Devices
    ("devices", "Paired devices", "", "devices paired connected list hardware mouse"),
    ("devices", "Force generic mode", "Device mode", "generic mode standard hid override detection logitech"),
    ("devices", "MX Keys S support", "Keyboard", "keyboard mx keys battery backlight enable beta"),
    # Gaming
    ("gaming", "Gaming mode", "Gaming mode", "gaming mode enable game performance"),
    ("gaming", "Show overlay in games", "Gaming mode", "overlay radial menu game fullscreen suppress"),
    ("gaming", "Active profile", "DPI profiles", "active profile dpi selection current"),
    # Flow
    ("flow", "Switch edge", "Behaviour", "switch edge direction screen handoff cursor"),
    ("flow", "Move cursor to edge to switch", "Behaviour", "cursor edge trigger switch handoff pointer"),
    ("flow", "Share clipboard", "Behaviour", "clipboard share copy paste sync computer"),
    ("flow", "Edge sensitivity", "Behaviour", "edge sensitivity threshold force pressure"),
    ("flow", "Monitor", "Behaviour", "monitor display screen handoff selection"),
    # Themes
    ("themes", "Color theme", "Color theme", "theme color accent wallpaper appearance"),
    # Settings
    ("settings", "Theme", "Appearance", "theme color accent appearance style"),
    ("settings", "Menu background blur", "Appearance", "blur background menu frost radial"),
    ("settings", "Simplified wheel", "Radial menu", "simplified wheel minimal mode icons only"),
    ("settings", "Monochrome icons", "Radial menu", "monochrome icons flat single-colour glyphs"),
    ("settings", "Click outside to close", "Radial menu", "click outside dismiss close menu ring tap away"),
    ("settings", "Language", "Language & desktop", "language interface locale translation"),
    ("settings", "Desktop environment", "Language & desktop", "desktop environment kde gnome cosmic integration"),
    ("settings", "Apply desktop defaults", "Language & desktop", "desktop defaults kde gnome apply actions"),
    ("apps", "Suggest profiles for new apps", "App profiles", "suggest new app profile prompt first launch toast"),
    ("settings", "Start at login", "Startup", "autostart startup launch boot login"),
    ("settings", "Show tray icon", "Startup", "tray icon system tray notification area"),
    ("settings", "Export settings", "Backup", "export backup zip save copy transfer another machine"),
    ("settings", "Import settings", "Backup", "import restore backup zip transfer another machine"),
    ("settings", "Restore defaults", "About", "reset restore defaults factory"),
]

# AI-assistant submenu quick-links (the "AI" radial slice opens these). The
# four defaults render their brand glyph; user-added links get a generic globe.
DEFAULT_AI_LINKS = [
    {"name": "Claude", "url": "https://claude.ai", "icon": "claude"},
    {"name": "ChatGPT", "url": "https://chat.openai.com", "icon": "chatgpt"},
    {"name": "Gemini", "url": "https://gemini.google.com", "icon": "gemini"},
    {"name": "Perplexity", "url": "https://perplexity.ai", "icon": "perplexity"},
]

DEFAULT_SLICES = [
    {"label": "Play/Pause", "action_id": "play_pause", "type": "exec",
     "command": "playerctl play-pause", "color": "green", "icon": "media-playback-start-symbolic"},
    {"label": "New Note", "action_id": "new_note", "type": "exec",
     "command": "kwrite", "color": "yellow", "icon": "document-new-symbolic"},
    {"label": "Lock", "action_id": "lock", "type": "exec",
     "command": "loginctl lock-session", "color": "red", "icon": "system-lock-screen-symbolic"},
    {"label": "Settings", "action_id": "settings", "type": "settings",
     "command": "", "color": "mauve", "icon": "emblem-system-symbolic"},
    {"label": "Screenshot", "action_id": "screenshot", "type": "exec",
     "command": "spectacle", "color": "blue", "icon": "camera-photo-symbolic"},
    {"label": "Emoji", "action_id": "emoji", "type": "emoji",
     "command": "", "color": "pink", "icon": "face-smile-symbolic"},
    {"label": "Files", "action_id": "files", "type": "exec",
     "command": "dolphin", "color": "sapphire", "icon": "folder-symbolic"},
    {"label": "AI", "action_id": "ai", "type": "submenu",
     "command": "", "color": "teal", "icon": "applications-science-symbolic"},
]

DEFAULT_CONFIG = {
    "theme": "phosphor",
    "radial_menu": {"slices": DEFAULT_SLICES,
                    "easy_switch_shortcuts": True,
                    "easy_switch_host_os": ["linux", "windows", "macos"]},
    "blur_enabled": True,
    "language": "en",
    "desktop_environment": "auto",
    "device_mode": "auto",
    "haptics": {
        "enabled": True, "default_pattern": "subtle_collision",
        "per_event": {"menu_appear": "damp_state_change", "slice_change": "subtle_collision",
                      "confirm": "sharp_state_change", "invalid": "angry_alert"},
        "intensity": 70, "debounce_ms": 20, "slice_debounce_ms": 20, "reentry_debounce_ms": 50,
    },
    "pointer": {"speed": 5, "dpi": 1600, "acceleration": True},
    "scroll": {"mode": "smartshift", "smartshift_threshold": 50, "speed": 3,
               "natural": False, "smooth": True},
    "thumbwheel": {"mode": "off", "invert": False, "speed": 1},
    "buttons": {k: d for (k, _l, d) in BUTTON_SLOTS},
    # Start at Login defaults on (the installer writes the autostart entry).
    "app": {"start_at_login": True, "show_tray_icon": True, "suggest_profiles": True},
    # wheel "" is the overlay no-op (falsy in _config_wheel_key), so a merged
    # default never overrides the theme-derived wheel for existing users.
    "radial": {"minimal_mode": False, "wheel": "", "click_outside_closes": True},
    "gaming": {"enabled": False, "suppress_overlay": False, "active_dpi_profile": 1,
               "dpi_profiles": [{"name": "Precision", "dpi": 400, "color": "blue"},
                                {"name": "Normal", "dpi": 1000, "color": "green"},
                                {"name": "Fast", "dpi": 3200, "color": "red"}]},
    "flow": {"enabled": False, "direction": "left", "edge_trigger": True,
             "share_clipboard": True, "edge_sensitivity": 50, "monitor": ""},
}


def _u8(v):
    """A D-Bus byte (`y`). PyQt6 sends a plain Python int as int32 (`i`), and
    the daemon (zbus) rejects a call whose signature differs from the declared
    one before the handler runs, so every byte argument must be typed."""
    return QDBusArgument(max(0, min(255, int(v))), QMetaType.Type.UChar.value)


def _u16(v):
    """A D-Bus uint16 (`q`); see _u8."""
    return QDBusArgument(max(0, min(65535, int(v))), QMetaType.Type.UShort.value)


def _to_int(v, default=0):
    """Coerce a D-Bus scalar to int. The 'y' byte type arrives as bytes."""
    if isinstance(v, (bytes, bytearray)):
        return v[0] if len(v) else default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ---------------------------------------------------------------------------
# D-Bus client (thin wrapper, fail-soft when the daemon is down)
# ---------------------------------------------------------------------------
class Daemon(QObject):
    batteryChanged = pyqtSignal(int, str)
    dpiChanged = pyqtSignal(int)
    hostChanged = pyqtSignal(int)
    ratchetChanged = pyqtSignal(bool)
    deviceNameRefreshed = pyqtSignal(str)
    gamingModeChanged = pyqtSignal(bool)
    newAppSeen = pyqtSignal(str)
    keyboardBatteryChanged = pyqtSignal(int, bool)
    availabilityChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._iface = None
        self._available = False
        if not _HAVE_DBUS:
            return
        self._bus = QDBusConnection.sessionBus()
        self._iface = QDBusInterface(BUS_NAME, OBJ_PATH, IFACE, self._bus)
        self._iface.setTimeout(2000)
        self._available = self._iface.isValid()
        # Empty service name: survive a daemon restart.
        # Subscribe even while the daemon is down so a later start is heard.
        self._watchers = set()  # pending async calls (keeps the watchers alive)
        self._bus.connect("", OBJ_PATH, IFACE, "BatteryChanged",
                          self._on_battery)
        self._bus.connect("", OBJ_PATH, IFACE, "DpiChanged", self._on_dpi)
        self._bus.connect("", OBJ_PATH, IFACE, "HostChanged", self._on_host)
        self._bus.connect("", OBJ_PATH, IFACE, "RatchetChanged", self._on_ratchet)
        self._bus.connect("", OBJ_PATH, IFACE, "GamingModeChanged", self._on_gaming)
        # Bolt reports a generic receiver name until the mouse answers; the
        # daemon re-probes and announces the real model (GTK app parity).
        self._bus.connect("", OBJ_PATH, IFACE, "DeviceNameRefreshed", self._on_device_name)
        # First focus of an application since the daemon started.
        self._bus.connect("", OBJ_PATH, IFACE, "NewAppSeen", self._on_new_app)
        # The keyboard linked up (a key press) and the daemon read its battery.
        self._bus.connect("", OBJ_PATH, IFACE, "KeyboardBatteryChanged", self._on_kb_battery)
        self._watcher = QDBusServiceWatcher(
            BUS_NAME, self._bus,
            QDBusServiceWatcher.WatchModeFlag.WatchForRegistration
            | QDBusServiceWatcher.WatchModeFlag.WatchForUnregistration, self)
        self._watcher.serviceRegistered.connect(self._on_service_up)
        self._watcher.serviceUnregistered.connect(self._on_service_down)

    def _on_service_up(self, name=""):
        # QDBusInterface introspects at construction, so one built while the
        # daemon was down stays call-dead forever; rebuild it on register.
        self._iface = QDBusInterface(BUS_NAME, OBJ_PATH, IFACE, self._bus)
        self._iface.setTimeout(2000)
        self._available = self._iface.isValid()
        self.availabilityChanged.emit()

    def _on_service_down(self, name=""):
        self._available = False
        self.availabilityChanged.emit()

    @property
    def available(self):
        return self._available

    def call(self, method, *args):
        """Call a daemon method; returns list of reply args, or None on error."""
        if not self._available:
            return None
        reply = self._iface.call(method, *args)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            return None
        return reply.arguments()

    def call_async(self, method, *args):
        """Fire-and-forget daemon call (no UI-thread round trip); reply dropped."""
        if not self._available:
            return
        self._iface.asyncCall(method, *args)

    def call_then(self, method, callback, *args):
        """Async daemon call; `callback(reply_args or None)` runs on the UI
        thread when the reply lands, so a slow method (a keyboard HID++ probe
        can take seconds) never stalls page changes."""
        if not self._available:
            callback(None)
            return
        watcher = QDBusPendingCallWatcher(self._iface.asyncCall(method, *args), self)
        self._watchers.add(watcher)

        def _finished(w):
            # PyQt6 binds no reply() on the watcher; QDBusPendingReply wraps
            # it. Everything runs inside a Qt slot, where an unhandled Python
            # exception is fatal (PyQt6 aborts the process), so guard it.
            self._watchers.discard(w)
            try:
                reply = QDBusPendingReply(w)
                result = None if reply.isError() else list(reply.reply().arguments())
            except Exception as e:  # pragma: no cover - defensive
                print(f"async {method} reply failed: {e}", file=sys.stderr)
                result = None
            finally:
                w.deleteLater()
            try:
                callback(result)
            except Exception as e:
                print(f"async {method} callback failed: {e}", file=sys.stderr)
        watcher.finished.connect(_finished)

    def call1(self, method, *args, default=None):
        r = self.call(method, *args)
        if r is None or len(r) == 0:
            return default
        return r[0]

    def prop(self, name, default=None):
        """Read a D-Bus property via org.freedesktop.DBus.Properties.Get."""
        if not self._available:
            return default
        m = QDBusMessage.createMethodCall(
            BUS_NAME, OBJ_PATH, "org.freedesktop.DBus.Properties", "Get")
        m.setArguments([IFACE, name])
        r = self._bus.call(m)
        if r.type() == QDBusMessage.MessageType.ErrorMessage:
            return default
        a = r.arguments()
        if not a:
            return default
        v = a[0]
        if hasattr(v, "variant"):
            v = v.variant()
        return default if v is None else v

    # --- signal handlers (the full QDBusMessage is delivered) ---
    @pyqtSlot(QDBusMessage)
    def _on_kb_battery(self, msg):
        a = msg.arguments()
        if len(a) >= 2:
            self.keyboardBatteryChanged.emit(_to_int(a[0]), bool(a[1]))

    @pyqtSlot(QDBusMessage)
    def _on_new_app(self, msg):
        a = msg.arguments()
        if a:
            self.newAppSeen.emit(str(a[0]))

    @pyqtSlot(QDBusMessage)
    def _on_battery(self, msg):
        a = msg.arguments()
        if len(a) >= 2:
            self.batteryChanged.emit(_to_int(a[0]), str(a[1]))

    @pyqtSlot(QDBusMessage)
    def _on_dpi(self, msg):
        a = msg.arguments()
        if a:
            self.dpiChanged.emit(_to_int(a[0]))

    @pyqtSlot(QDBusMessage)
    def _on_host(self, msg):
        a = msg.arguments()
        if a:
            self.hostChanged.emit(_to_int(a[0]))

    @pyqtSlot(QDBusMessage)
    def _on_ratchet(self, msg):
        a = msg.arguments()
        if a:
            self.ratchetChanged.emit(bool(a[0]))

    @pyqtSlot(QDBusMessage)
    def _on_device_name(self, msg):
        a = msg.arguments()
        if a:
            self.deviceNameRefreshed.emit(str(a[0]))

    @pyqtSlot(QDBusMessage)
    def _on_gaming(self, msg):
        a = msg.arguments()
        if a:
            self.gamingModeChanged.emit(bool(a[0]))


# ---------------------------------------------------------------------------
# Radial-slice list model (8 entries) - shared by the editor + persistence
# ---------------------------------------------------------------------------
class SliceModel(QAbstractListModel):
    LabelRole = Qt.ItemDataRole.UserRole + 1
    ActionIdRole = Qt.ItemDataRole.UserRole + 2
    TypeRole = Qt.ItemDataRole.UserRole + 3
    CommandRole = Qt.ItemDataRole.UserRole + 4
    ColorRole = Qt.ItemDataRole.UserRole + 5
    IconRole = Qt.ItemDataRole.UserRole + 6
    HexRole = Qt.ItemDataRole.UserRole + 7
    changed = pyqtSignal()

    def __init__(self, backend):
        super().__init__()
        self._backend = backend
        self._slices = []

    def load(self, slices):
        self.beginResetModel()
        self._slices = [dict(s) for s in slices][:8]
        # pad to 8 with "none"
        while len(self._slices) < 8:
            self._slices.append({"label": "Do Nothing", "action_id": "none",
                                 "type": "none", "command": "", "color": "gray",
                                 "icon": "action-unavailable-symbolic"})
        self.endResetModel()

    def roleNames(self):
        return {
            self.LabelRole: QByteArray(b"label"),
            self.ActionIdRole: QByteArray(b"actionId"),
            self.TypeRole: QByteArray(b"type"),
            self.CommandRole: QByteArray(b"command"),
            self.ColorRole: QByteArray(b"color"),
            self.IconRole: QByteArray(b"icon"),
            self.HexRole: QByteArray(b"hex"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._slices)

    def data(self, index, role):
        if not index.isValid():
            return None
        s = self._slices[index.row()]
        if role == self.LabelRole:
            return s.get("label", "")
        if role == self.ActionIdRole:
            return s.get("action_id", "none")
        if role == self.TypeRole:
            return s.get("type", "none")
        if role == self.CommandRole:
            return s.get("command", "")
        if role == self.ColorRole:
            return s.get("color", "gray")
        if role == self.IconRole:
            return s.get("icon", "")
        if role == self.HexRole:
            return SLICE_COLORS.get(s.get("color", "gray"), "#9399B2")
        return None

    def slices(self):
        return [dict(s) for s in self._slices]

    @pyqtSlot(int, result="QVariant")
    def sliceAt(self, row):
        """Full data for one slice (for the slice editor)."""
        if 0 <= row < len(self._slices):
            s = self._slices[row]
            d = dict(s)
            d["hex"] = SLICE_COLORS.get(s.get("color", "gray"), "#9399B2")
            return d
        return {}

    @pyqtSlot(int, str)
    def setAction(self, row, action_id):
        """Apply a RADIAL_ACTIONS preset to a slice (keeps the slice colour)."""
        if not (0 <= row < len(self._slices)):
            return
        for aid, label, icon, atype, command, color in RADIAL_ACTIONS:
            if aid == action_id:
                self._slices[row] = {"label": label, "action_id": aid, "type": atype,
                                     "command": command, "color": color, "icon": icon}
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [])
                self._persist()
                return

    @pyqtSlot(int, str)
    def setColor(self, row, color):
        if 0 <= row < len(self._slices):
            self._slices[row]["color"] = color
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])
            self._persist()

    @pyqtSlot(int, str)
    def setLabel(self, row, label):
        if 0 <= row < len(self._slices):
            self._slices[row]["label"] = label
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])
            self._persist()

    @pyqtSlot(int, str)
    def setCommand(self, row, command):
        if 0 <= row < len(self._slices):
            self._slices[row]["command"] = command
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])
            self._persist()

    @pyqtSlot(int, str, str, str)
    def setApp(self, row, command, label, icon):
        """Point a slice at a picked application: exec type, its command and
        cached icon (an absolute path the overlay draws as-is). The label is
        replaced only while it is still the preset's own text or empty."""
        if not (0 <= row < len(self._slices)):
            return
        s = self._slices[row]
        preset = next((lbl for (aid, lbl, *_r) in RADIAL_ACTIONS if aid == s.get("action_id")), None)
        s["type"] = "exec"
        s["command"] = command
        if icon:
            s["icon"] = icon
        if label and (not (s.get("label") or "").strip() or s.get("label") == preset):
            s["label"] = label
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [])
        self._persist()

    def set_submenu(self, row, items):
        """Replace the quick links carried by a submenu slice (what the overlay reads)."""
        if 0 <= row < len(self._slices):
            self._slices[row]["submenu"] = [dict(i) for i in items]
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])
            self._persist()

    @pyqtSlot(int, int)
    def swap(self, a, b):
        n = len(self._slices)
        if 0 <= a < n and 0 <= b < n and a != b:
            self._slices[a], self._slices[b] = self._slices[b], self._slices[a]
            self.beginResetModel()
            self.endResetModel()
            self._persist()

    def _persist(self):
        self._backend._set_path(["radial_menu", "slices"], self.slices())
        self._backend._save()
        self._backend.reloadConfig()
        self.changed.emit()


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------
class Backend(QObject):
    configChanged = pyqtSignal()
    liveChanged = pyqtSignal()
    # UI toast requests (text, kind). Pages call notify(); Main.qml shows it.
    toastRequested = pyqtSignal(str, str)
    availabilityChanged = pyqtSignal()
    macrosChanged = pyqtSignal()
    toast = pyqtSignal(str)
    keyboardInfoReady = pyqtSignal("QVariant")
    controlsReady = pyqtSignal("QVariant")
    navRequested = pyqtSignal(str)   # a page asks the shell to switch tabs
    # config.json was replaced wholesale (import, restore defaults): the shell
    # re-instantiates the visible page so its controls read the new values.
    configReloaded = pyqtSignal()
    # A newly focused application may deserve a profile; the shell asks for it
    # with takeProfileSuggestion() once its window is active.
    profileSuggested = pyqtSignal()
    searchTargetChanged = pyqtSignal()

    @pyqtSlot(str)
    def goTo(self, key):
        self.navRequested.emit(key)

    # ---- global settings search ----
    @pyqtSlot(result="QVariant")
    def searchIndex(self):
        """Every searchable setting: {tab, tabKey, label, section, keywords}."""
        return [{"tabKey": tk, "tab": TAB_LABELS.get(tk, tk), "label": lbl,
                 "section": sec, "keywords": kw}
                for (tk, lbl, sec, kw) in SEARCH_INDEX]

    @pyqtProperty(str, notify=searchTargetChanged)
    def searchTarget(self):
        """SettingRow label the active page should flash + scroll to ("" = none)."""
        return self._search_target

    @pyqtSlot(str, str)
    def openSearchResult(self, tab_key, label):
        """Jump to the result's tab, then flag its row to highlight itself."""
        self.navRequested.emit(tab_key)
        self._search_target = label
        self.searchTargetChanged.emit()
        # auto-clear so a later visit to the same tab does not re-flash; guard on
        # the label so a stale timer cannot wipe a newer search target.
        QTimer.singleShot(2800, lambda lbl=label: self._clear_if(lbl))

    def _clear_if(self, label):
        if self._search_target == label:
            self._search_target = ""
            self.searchTargetChanged.emit()

    @pyqtSlot()
    def clearSearchTarget(self):
        if self._search_target:
            self._search_target = ""
            self.searchTargetChanged.emit()

    def __init__(self):
        super().__init__()
        self._cfg = {}
        self._search_target = ""
        self._load()
        self.daemon = Daemon()
        self._slices = SliceModel(self)
        self._slices.load(self.get("radial_menu.slices") or [])

        # live hardware state
        self._battery = 0
        self._charging = False
        self._dpi = int(self.get("pointer.dpi", 1600))
        self._cur_host = 0
        self._num_hosts = 3
        self._ratchet = True
        self._wheel_mode = ""
        self._host_names = []
        self._ss_supported = False
        self._tw_supported = False
        self._dpi_supported = False
        self._device_name = ""
        self._device_mode = ""
        self._daemon_version = ""
        self._connection = ""
        self._unit_id = ""

        self._gaming_mode = bool(self.get("gaming.enabled", False))
        self._low_batt_notified = False
        self._repair_autostart_if_stale()

        self.daemon.batteryChanged.connect(self._set_battery)
        self.daemon.deviceNameRefreshed.connect(self._set_device_name_live)
        self.daemon.dpiChanged.connect(self._set_dpi_live)
        self.daemon.hostChanged.connect(self._set_host_live)
        self.daemon.ratchetChanged.connect(self._set_ratchet_live)
        self.daemon.gamingModeChanged.connect(self._set_gaming_live)
        self._pending_app = ""
        self.daemon.newAppSeen.connect(self._on_new_app)
        self._kb_info = None
        self._kb_last_battery = 0
        self.daemon.keyboardBatteryChanged.connect(self._on_keyboard_battery)
        self.daemon.availabilityChanged.connect(self._on_daemon_availability)

        # prime device state shortly after start (daemon may be warming up)
        QTimer.singleShot(150, self._prime)
        if self._load_failed:
            # deferred so the QML shell exists before the toast fires
            QTimer.singleShot(800, lambda: self.toast.emit(
                "Config was corrupt; using defaults (backup: config.json.bad)"))

    def _on_daemon_availability(self):
        self._prime()
        self.availabilityChanged.emit()

    # ---- config file ----
    def _load(self):
        self._load_failed = False
        user = {}
        try:
            user = json.loads(CONFIG.read_text())
            if not isinstance(user, dict):
                raise ValueError("config root is not an object")
        except FileNotFoundError:
            pass
        except Exception as e:
            # Keep the broken file so the next _save() cannot destroy it.
            try:
                shutil.copy2(CONFIG, CONFIG.with_suffix(".json.bad"))
            except Exception:
                pass
            print(f"config load failed ({e}); backup at config.json.bad",
                  file=sys.stderr)
            self._load_failed = True
            user = {}
        self._cfg = _deep_merge(DEFAULT_CONFIG, user)

    @staticmethod
    def _normalize_numbers(o):
        """Collapse integral floats (QML sliders emit doubles: 100.0) to ints.

        The daemon's serde config uses strict integer fields (u8 intensity,
        u32 debounce); a single `100.0` fails the WHOLE parse and silently
        reverts the daemon to defaults. Non-integral floats are preserved.
        """
        if isinstance(o, dict):
            return {k: Backend._normalize_numbers(v) for k, v in o.items()}
        if isinstance(o, list):
            return [Backend._normalize_numbers(v) for v in o]
        if isinstance(o, float) and o.is_integer():
            return int(o)
        return o

    def _save(self):
        try:
            self._cfg = self._normalize_numbers(self._cfg)
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    "w", dir=CONFIG_DIR, prefix="config.", suffix=".tmp",
                    delete=False) as f:
                f.write(json.dumps(self._cfg, indent=2))
                f.flush()
                os.fsync(f.fileno())
            os.replace(f.name, CONFIG)
        except Exception as e:
            self.toast.emit(f"Save failed: {e}")

    def _get_path(self, parts, default=None):
        cur = self._cfg
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
        return cur

    def _set_path(self, parts, value):
        cur = self._cfg
        for p in parts[:-1]:
            if not isinstance(cur.get(p), dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = value

    # ---- generic config access for QML ----
    @pyqtSlot(str, result="QVariant")
    @pyqtSlot(str, "QVariant", result="QVariant")
    def get(self, path, default=None):
        v = self._get_path(path.split("."), None)
        return default if v is None else v

    @pyqtSlot(str, "QVariant")
    def set(self, path, value):
        """Persist a config value and tell the daemon to reload."""
        self._set_path(path.split("."), value)
        self._save()
        self.reloadConfig()
        self.configChanged.emit()

    @pyqtSlot(str, "QVariant")
    def setLocal(self, path, value):
        """Persist a config value WITHOUT a daemon reload (UI-only keys)."""
        self._set_path(path.split("."), value)
        self._save()
        self.configChanged.emit()

    # ---- daemon basic ----
    @pyqtSlot()
    def reloadPage(self):
        """Rebuild the visible page so it re-reads config and profiles."""
        self.configReloaded.emit()

    @pyqtSlot()
    def reloadConfig(self):
        self.daemon.call_async("ReloadConfig")

    @pyqtProperty(bool, notify=availabilityChanged)
    def daemonAvailable(self):
        return self.daemon.available

    # deviceName/deviceMode/daemonVersion are bound app-wide (every nav
    # delegate), so they must read the _prime() cache, never D-Bus directly.
    @pyqtProperty(str, notify=liveChanged)
    def deviceName(self):
        return self._device_name or "MX Master 4"

    @pyqtProperty(str, notify=liveChanged)
    def deviceMode(self):
        return self._device_mode or self.get("device_mode", "auto")

    @pyqtProperty(bool, notify=liveChanged)
    def isGeneric(self):
        return self.deviceMode == "generic"

    @pyqtProperty(str, constant=True)
    def appVersion(self):
        # settings-qt/VERSION is one of the sites scripts/bump-version.sh keeps
        # in step with daemon/Cargo.toml (tests/test_version_consistency.py).
        try:
            return (pathlib.Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
        except OSError:
            return "dev"

    @pyqtProperty(str, notify=liveChanged)
    def daemonVersion(self):
        return self._daemon_version or "-"

    # ---- live hardware props ----
    @pyqtProperty(int, notify=liveChanged)
    def battery(self):
        return self._battery

    @pyqtProperty(bool, notify=liveChanged)
    def charging(self):
        return self._charging

    @pyqtProperty(int, notify=liveChanged)
    def dpi(self):
        return self._dpi

    @pyqtProperty(int, notify=liveChanged)
    def currentHost(self):
        return self._cur_host

    @pyqtProperty(int, notify=liveChanged)
    def numHosts(self):
        return self._num_hosts

    @pyqtProperty(bool, notify=liveChanged)
    def ratchet(self):
        return self._ratchet

    @pyqtProperty(str, notify=liveChanged)
    def wheelMode(self):
        """Configured wheel mode: 'smartshift', 'ratchet', 'freespin', or ''.

        Derived from GetSmartShift, unlike `ratchet`, which mirrors the
        instantaneous RatchetChanged bool from the hardware button.
        """
        return self._wheel_mode

    @staticmethod
    def _derive_wheel_mode(enabled, threshold):
        # Daemon mapping: (True, 1-254) = smartshift auto-disengage,
        # (True, 0) = freespin, (False, _) = permanent ratchet.
        if not enabled:
            return "ratchet"
        return "freespin" if threshold == 0 else "smartshift"

    def _refresh_wheel_mode(self):
        ss = self.daemon.call("GetSmartShift")
        if ss and len(ss) >= 2:
            enabled, threshold = bool(ss[0]), _to_int(ss[1])
            self._wheel_mode = self._derive_wheel_mode(enabled, threshold)
            # The sensitivity slider follows the hardware when it was set from
            # elsewhere (another host, the GTK app): device 1..49 maps back to
            # the percent scale exactly (PR #123). Untouched when the device
            # already holds what the config maps to, so the slider never nudges.
            if enabled and 1 <= threshold <= 49:
                cur = int(self.get("scroll.smartshift_threshold", 50))
                if self._dev_threshold(cur) != threshold:
                    self._set_path(["scroll", "smartshift_threshold"], self._ui_threshold(threshold))
                    self._save()
                    self.configChanged.emit()

    @pyqtProperty("QStringList", notify=liveChanged)
    def hostNames(self):
        return self._host_names

    @pyqtProperty(bool, notify=liveChanged)
    def smartShiftSupported(self):
        return self._ss_supported

    @pyqtProperty(bool, notify=liveChanged)
    def thumbwheelSupported(self):
        return self._tw_supported

    @pyqtProperty(bool, notify=configChanged)
    def hapticsEnabled(self):
        return bool(self.get("haptics.enabled", True))

    def _prime(self):
        d = self.daemon
        if not d.available:
            self._device_name = ""
            self._device_mode = ""
            self._daemon_version = ""
            self._connection = ""
            self.liveChanged.emit()
            return
        self._device_name = d.call1("GetDeviceName", default="") or ""
        # Dev override for device art and callout work on hardware you do not
        # own (for example JUH_DEVICE_NAME="MX Master 3S" on an MX Master 4).
        self._device_name = os.environ.get("JUH_DEVICE_NAME") or self._device_name
        self._unit_id = str(d.call1("GetUnitId", default="") or "")
        self._device_mode = d.call1("GetDeviceMode", default="") or ""
        self._connection = self._detect_connection(self._device_mode == "generic")
        self._daemon_version = str(d.prop("DaemonVersion", "") or "")
        r = d.call("GetBatteryStatus")
        if r and len(r) >= 2:
            self._battery, self._charging = _to_int(r[0]), bool(r[1])
        dpi = d.call1("GetDpi", default=None)
        if dpi:
            self._dpi = _to_int(dpi, self._dpi)
        es = d.call("GetEasySwitchInfo")
        if es and len(es) >= 2:
            nh = _to_int(es[0])
            if nh > 0:  # receiver-connected mice report 0; keep 3 slots default
                self._num_hosts, self._cur_host = nh, _to_int(es[1])
        hn = d.call1("GetHostNames", default=None)
        if hn:
            self._host_names = [str(x) for x in hn]
        self._refresh_wheel_mode()
        self._ss_supported = bool(d.call1("SmartShiftSupported", default=False))
        self._tw_supported = bool(d.call1("ThumbwheelSupported", default=False))
        self._dpi_supported = bool(d.call1("DpiSupported", default=False))
        self.liveChanged.emit()

    def _set_battery(self, pct, status):
        self._battery = pct
        # "discharging" contains "charg" AND "charging", so test for the
        # discharge case first or the mouse always reads as charging.
        s = status.lower()
        self._charging = ("charg" in s) and ("dischar" not in s)
        self._maybe_low_battery_notify(pct)
        self.liveChanged.emit()

    def _maybe_low_battery_notify(self, pct):
        """Desktop-notify once when the mouse drops to <=15% on battery; reset
        the latch above 20% (hysteresis) or while charging, so it can re-fire."""
        if self._charging or pct > 20:
            self._low_batt_notified = False
            return
        if pct <= 15 and not self._low_batt_notified and not self._overlay_running():
            self._low_batt_notified = True
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "JuhRadial MX", "-i", "battery-low-symbolic",
                     "-u", "critical", "Mouse battery low",
                     f"MX Master 4 is at {pct}%. Time to recharge."])
            except Exception:
                pass

    @staticmethod
    def _overlay_running():
        """True while the overlay owns its bus name: it raises the low-battery
        notification itself then (tray badge + notify-send), so the settings
        app stays quiet instead of sending a second one."""
        if not _HAVE_DBUS:
            return False
        try:
            # A QDBusReply is always truthy; the answer is in value().
            reply = QDBusConnection.sessionBus().interface().isServiceRegistered(
                "org.kde.juhradialmx.overlay")
            return bool(reply.value())
        except Exception:
            return False

    def _set_gaming_live(self, on):
        self._gaming_mode = bool(on)
        self.liveChanged.emit()

    def _set_dpi_live(self, dpi):
        self._dpi = dpi
        self.liveChanged.emit()

    def _set_host_live(self, host):
        self._cur_host = host
        self.liveChanged.emit()

    def _set_ratchet_live(self, r):
        self._ratchet = r
        # The hardware button toggles engagement without touching the stored
        # wheel mode; re-read so wheelMode stays truthful either way.
        self._refresh_wheel_mode()
        self.liveChanged.emit()

    # ---- pointer / scroll / thumbwheel actions ----
    @pyqtSlot(int)
    def setDpi(self, dpi):
        dpi = max(400, min(8000, int(dpi)))
        self._dpi = dpi
        self.setLocal("pointer.dpi", dpi)
        self.daemon.call_async("SetDpi", _u16(dpi))
        self.liveChanged.emit()

    @pyqtSlot(str)
    def setScrollMode(self, mode):
        self.setLocal("scroll.mode", mode)
        thr = int(self.get("scroll.smartshift_threshold", 50))
        if mode == "smartshift":
            self.daemon.call("SetSmartShift", True, _u8(self._dev_threshold(thr)))
        elif mode == "ratchet":
            # (False, _) = permanently ratcheted (autoDisengage 255).
            self.daemon.call("SetSmartShift", False, _u8(0))
        elif mode == "freespin":
            # (True, 0) = freespin.
            self.daemon.call("SetSmartShift", True, _u8(0))
        self._wheel_mode = mode
        self.liveChanged.emit()

    @pyqtSlot(int)
    def setSmartShiftThreshold(self, ui_value):
        self.setLocal("scroll.smartshift_threshold", int(ui_value))
        self.daemon.call("SetSmartShift", True, _u8(self._dev_threshold(ui_value)))

    @staticmethod
    def _dev_threshold(ui_value):
        """Easy 1% .. Hard 100% -> HID++ automatic disengage threshold 1..49.

        Same mapping as the GTK app since PR #123 (hardware-verified on an
        MX Master 4): monotonic, higher slider = harder flick before the wheel
        auto-releases. 0 (free-spin) and 255 (permanent ratchet) stay reserved
        for the wheel-mode setter, and 50 is Logitech's ratchet-only endpoint.
        """
        ui_value = max(1, min(100, int(ui_value)))
        return 1 + (((ui_value - 1) * 48 + 49) // 99)

    @staticmethod
    def _ui_threshold(device_threshold):
        """Inverse of _dev_threshold: device 1..49 -> Easy/Hard percent."""
        threshold = max(1, min(49, int(device_threshold)))
        return 1 + (((threshold - 1) * 99) // 48)

    @pyqtSlot(bool)
    def setNaturalScroll(self, on):
        self.setLocal("scroll.natural", bool(on))
        self.daemon.call("SetHiresscrollMode", bool(self.get("scroll.smooth", True)),
                         bool(on), False)

    @pyqtSlot(bool)
    def setSmoothScroll(self, on):
        self.setLocal("scroll.smooth", bool(on))
        self.daemon.call("SetHiresscrollMode", bool(on),
                         bool(self.get("scroll.natural", False)), False)

    @pyqtSlot(bool)
    def setPointerAccel(self, on):
        """Pointer acceleration on/off -> libinput accel-profile via gsettings
        (adaptive when on, flat when off)."""
        self.setLocal("pointer.acceleration", bool(on))
        if shutil.which("gsettings") is None:
            self.toast.emit("Pointer acceleration needs GNOME gsettings")
            return
        try:
            subprocess.Popen(["gsettings", "set",
                              "org.gnome.desktop.peripherals.mouse",
                              "accel-profile", "adaptive" if on else "flat"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @pyqtSlot(int)
    def setScrollSpeed(self, lines):
        """Persist + apply the wheel scroll-speed multiplier per desktop."""
        lines = max(1, min(10, int(lines)))
        self.setLocal("scroll.speed", lines)
        self._apply_scroll_speed(lines)

    def _apply_scroll_speed(self, lines):
        """Apply the scroll multiplier across desktops (best-effort, fail-soft).
        Ported from the shipped GTK app: KDE ScrollFactor, Hyprland/sway IPC,
        X11 imwheel. 1 line -> 0.5x .. ramps up by ~0.167 per step.
        All external commands run detached or on worker threads: this fires
        from a slider on the UI thread, so it must never block."""
        factor = 0.5 + (lines - 1) * 0.167
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()

        def _spawn(cmd):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except Exception:
                pass

        if "kde" in desktop or "plasma" in desktop:
            # Plasma 6 ships kwriteconfig6; fall back to the Plasma 5 name.
            for tool in ("kwriteconfig6", "kwriteconfig5"):
                if shutil.which(tool):
                    _spawn([tool, "--file", "kcminputrc", "--group", "Mouse",
                            "--key", "ScrollFactor", str(factor)])
                    break

        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            _spawn(["hyprctl", "keyword", "input:scroll_factor", str(factor)])

        if "sway" in desktop:
            def _sway():
                try:
                    r = subprocess.run(["swaymsg", "-t", "get_inputs"],
                                       capture_output=True, text=True, timeout=2)
                    if r.returncode == 0:
                        for inp in json.loads(r.stdout):
                            if "pointer" in inp.get("type", ""):
                                subprocess.run(
                                    ["swaymsg", "input", inp.get("identifier", ""),
                                     "scroll_factor", str(factor)],
                                    capture_output=True, timeout=2)
                except Exception:
                    pass
            threading.Thread(target=_sway, daemon=True).start()

        if session == "x11":
            def _imwheel():
                try:
                    rc = pathlib.Path.home() / ".imwheelrc"
                    rc.write_text(f'".*"\nNone,      Up,   Button4, {lines}\n'
                                  f'None,      Down, Button5, {lines}\n')
                    # kill must complete before the relaunch, hence the thread
                    subprocess.run(["pkill", "-u", str(os.getuid()), "imwheel"],
                                   capture_output=True, timeout=2)
                    _spawn(["imwheel", "-b", "45"])
                except Exception:
                    pass
            threading.Thread(target=_imwheel, daemon=True).start()

    @pyqtSlot(str)
    def setThumbwheelMode(self, mode):
        self.setLocal("thumbwheel.mode", mode)
        self.reloadConfig()  # daemon re-applies divert from config

    @pyqtSlot(bool)
    def setThumbwheelInvert(self, inv):
        self.setLocal("thumbwheel.invert", bool(inv))
        self.reloadConfig()

    @pyqtSlot(int)
    def setThumbwheelSpeed(self, sp):
        self.setLocal("thumbwheel.speed", max(1, min(8, int(sp))))
        self.reloadConfig()

    # ---- buttons ----
    @pyqtSlot(str, str)
    def setButton(self, slot, action_id):
        self.set(f"buttons.{slot}", action_id)

    @pyqtSlot(str)
    def setDeviceMode(self, mode):
        """Force device mode (auto/generic); daemon re-evaluates on reload."""
        self.set("device_mode", mode)
        self._device_mode = ""  # cache is stale until next prime; fall to config
        self.liveChanged.emit()

    # Generic-mouse radial trigger: which evdev button opens the menu when the
    # device is driven in generic mode (daemon reads `generic_trigger_button`,
    # default 0x113 BTN_SIDE). Only meaningful while device_mode == generic.
    # currentId is a string in the shared ComboBox; ids are the decimal evdev
    # code as text ("275"), while config.json stores the int the daemon reads.
    @pyqtProperty(str, notify=liveChanged)
    def genericTrigger(self):
        return str(int(self.get("generic_trigger_button", 0x113)))

    @pyqtSlot(str)
    def setGenericTrigger(self, code):
        try:
            self.set("generic_trigger_button", int(code))
        except (TypeError, ValueError):
            return
        self.liveChanged.emit()

    @pyqtSlot(result="QVariant")
    def genericTriggerOptions(self):
        # evdev BTN_* codes for the buttons a generic mouse realistically exposes.
        return [{"id": "275", "name": "Side button (BTN_SIDE)"},
                {"id": "276", "name": "Extra button (BTN_EXTRA)"},
                {"id": "277", "name": "Forward (BTN_FORWARD)"},
                {"id": "278", "name": "Back (BTN_BACK)"},
                {"id": "274", "name": "Middle click (BTN_MIDDLE)"}]

    # ---- keyboard (MX Keys S / generic, BETA) ----
    # Fail-soft against the running daemon: pre-keyboard daemons lack these
    # methods, so the card just reports "not detected" until the daemon that
    # ships keyboard support is installed.
    @pyqtSlot(result="QVariant")
    def keyboardInfo(self):
        """Blocking variant (tests, scripts). Pages use requestKeyboardInfo()."""
        battery = self.daemon.call("GetKeyboardBattery")
        paired = self.daemon.call("GetKeyboardPaired")
        keys = self.daemon.call("ListKeyboardKeys")
        return self._keyboard_info(battery, paired, keys)

    def _keyboard_info(self, battery, paired, keys):
        enabled = bool(self.get("keyboard.mx_keys.enabled", False))
        pct, charging = 0, False
        if battery and len(battery) >= 2:
            pct, charging = _to_int(battery[0]), bool(battery[1])
        # Paired = receiver pairing table; true even while the keyboard's radio
        # sleeps (battery reads 0 then). Distinguishes "asleep" from "absent".
        is_paired = bool(paired[0]) if paired else False
        present = is_paired or pct > 0 or charging
        key_list = keys[0] if keys and keys[0] else []
        if pct > 0:
            self._kb_last_battery = pct
        return {"present": present, "enabled": enabled, "battery": pct,
                "charging": charging, "sleeping": present and pct == 0,
                "keyCount": len(key_list), "pending": False,
                "lastBattery": self._kb_last_battery}

    def _on_keyboard_battery(self, pct, charging):
        """KeyboardBatteryChanged: the keyboard is awake right now."""
        if pct <= 0:
            return
        self._kb_last_battery = pct
        info = dict(self._kb_info or {
            "enabled": bool(self.get("keyboard.mx_keys.enabled", False)), "keyCount": 0})
        info.update({"present": True, "battery": pct, "charging": bool(charging),
                     "sleeping": False, "pending": False, "lastBattery": pct})
        self._kb_info = info
        self.keyboardInfoReady.emit(info)

    @pyqtSlot()
    def requestKeyboardInfo(self):
        """Non-blocking keyboardInfo(): the three keyboard calls can each take
        seconds while the daemon probes the receiver, and running them inline
        froze the Devices page on open. keyboardInfoReady carries the dict."""
        # One call at a time, in the order the blocking version used: the
        # daemon's pairing-table probe listens on the receiver for 500 ms and
        # misses its answer when its own battery scan runs at the same time
        # (three concurrent calls read "not detected" for a paired keyboard).
        state = {}
        order = ("GetKeyboardBattery", "GetKeyboardPaired", "ListKeyboardKeys")

        def step(i):
            if i == len(order):
                self._kb_info = self._keyboard_info(
                    state["GetKeyboardBattery"], state["GetKeyboardPaired"],
                    state["ListKeyboardKeys"])
                self.keyboardInfoReady.emit(self._kb_info)
                return
            name = order[i]

            def _cb(args):
                state[name] = args
                step(i + 1)
            self.daemon.call_then(name, _cb)
        step(0)

    @pyqtSlot(int)
    def setKeyboardBacklight(self, level):
        """Set MX Keys S backlight 0..100% (mapped to the device's levels)."""
        r = self.daemon.call("SetKeyboardBacklight", _u8(max(0, min(100, int(level)))))
        if not (r and len(r) >= 1 and r[0]):
            # A sleeping keyboard ignores HID++ until a key press wakes it.
            self.toast.emit("Keyboard not reachable - press a key to wake it, then try again")

    @pyqtSlot(str, float, float)
    def setPinPos(self, slot, nx, ny):
        """Persist a manually-placed callout pin (config.button_pins.<slot>)."""
        self._set_path(["button_pins", slot], {"nx": round(nx, 4), "ny": round(ny, 4)})
        self._save()
        self.toast.emit(f"Pin saved: {slot} = {nx:.3f}, {ny:.3f}")

    # ---- quick links (the submenu slice's own links, up to four) ----
    def _submenu_row(self):
        for i, sl in enumerate(self._slices.slices()):
            if sl.get("type") == "submenu":
                return i
        return -1

    @pyqtSlot(result="QVariant")
    def aiLinks(self):
        """Rows for the quick-links editor: {name, url, icon, command}.

        Read from the submenu slice's `submenu` list, which is what the
        overlay draws (0.4.3, `submenu_from_config`). A config that only has
        the older Qt-side radial_menu.ai_links key is shown from that once and
        moves into the slice on the next save. No links at all shows the AI
        defaults, exactly like an empty list does on the wheel.
        """
        row = self._submenu_row()
        items = self._slices.slices()[row].get("submenu") if row >= 0 else None
        if not items:
            legacy = self.get("radial_menu.ai_links")
            if isinstance(legacy, list):
                items = [{"label": l.get("name", ""), "url": l.get("url", "")}
                         for l in legacy if isinstance(l, dict)]
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            if it.get("type") == "exec":
                out.append({"name": it.get("label", ""), "url": "",
                            "icon": it.get("icon", ""), "command": it.get("command", "")})
            else:
                out.append({"name": it.get("label", ""), "url": it.get("url", ""),
                            "icon": "browser", "command": ""})
        return out[:4] or [{"name": l["name"], "url": l["url"], "icon": l["icon"], "command": ""}
                           for l in DEFAULT_AI_LINKS]

    @pyqtSlot("QVariant")
    def setAiLinks(self, links):
        """Persist the quick links into the submenu slice (the overlay reads at
        most four). Link rows carry {name, url}; application rows carry
        {name, command, icon} and launch like an exec slice."""
        items = []
        for l in (links or []):
            if not isinstance(l, dict):
                continue
            name = str(l.get("name", "") or "").strip()
            command = str(l.get("command", "") or "").strip()
            url = str(l.get("url", "") or "").strip()
            if not name:
                continue
            if command:
                items.append({"label": name, "type": "exec", "command": command,
                              "icon": str(l.get("icon", "") or "")})
            elif url:
                if "://" not in url:
                    url = "https://" + url
                items.append({"label": name, "url": url})
            if len(items) == 4:
                break
        row = self._submenu_row()
        if row < 0:
            self.toast.emit("Give a slice the AI Assistant action first")
            return
        radial_menu = self._cfg.get("radial_menu")
        if isinstance(radial_menu, dict):
            radial_menu.pop("ai_links", None)
        self._slices.set_submenu(row, items)
        self.configChanged.emit()

    # ---- per-app hardware profiles (profiles.json -> hardware{}) ----
    # NOTE: the daemon consumes ONLY the `hardware` overrides (dpi/smartshift/
    # hires/thumbwheel), applied volatile on focus change via ReportActiveWindow.
    # Per-app radial SLICES are not wired in the daemon, so we don't expose them.
    def _load_profiles(self):
        try:
            return json.loads(PROFILES.read_text())
        except Exception:
            return {}

    def _save_profiles(self, data):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    "w", dir=CONFIG_DIR, prefix="profiles.", suffix=".tmp",
                    delete=False) as f:
                f.write(json.dumps(data, indent=2))
                f.flush()
                os.fsync(f.fileno())
            os.replace(f.name, PROFILES)
        except Exception as e:
            self.toast.emit(f"Profiles save failed: {e}")

    @pyqtSlot(result="QVariant")
    def appProfiles(self):
        hw = (self._load_profiles().get("hardware") or {})
        out = []
        for app, h in hw.items():
            ss = h.get("smartshift") or {}
            # profiles.json stores the device threshold the daemon sends to the
            # mouse; the slider speaks sensitivity % through the PR #123
            # mapping, the same one saveAppProfile writes with.
            dev_thr = _to_int(ss.get("threshold"), self._dev_threshold(50))
            ui_thr = self._ui_threshold(dev_thr)
            out.append({"app": app,
                        "dpi": int(h.get("dpi", 1600)),
                        "smartshiftEnabled": bool(ss.get("enabled", True)),
                        "smartshiftThreshold": ui_thr,
                        "hires": bool(h.get("hires", True)),
                        "thumbwheel": str(h.get("thumbwheel", "off"))})
        out.sort(key=lambda x: x["app"])
        return out

    @pyqtSlot(str)
    def addAppProfile(self, app):
        app = (app or "").strip().lower()
        if not app:
            return
        data = self._load_profiles()
        hw = data.setdefault("hardware", {})
        if app not in hw:
            hw[app] = {"dpi": 1600,
                       "smartshift": {"enabled": True, "threshold": self._dev_threshold(50)},
                       "hires": True, "thumbwheel": "off"}
            self._save_profiles(data)
            self.reloadConfig()
            self.toast.emit(f"Added profile: {app}")

    # ---- profile suggestions for newly focused apps (NewAppSeen) ----
    # Our own windows and the desktop shell are never worth a profile.
    IGNORED_APPS = frozenset({
        "org.kde.juhradialmx.settings", "juhradial-mx", "juhradial mx", "python3",
        "main.py", "plasmashell", "org.kde.plasmashell", "kwin_wayland", "kwin_x11",
        "krunner", "org.kde.krunner", "gnome-shell", "org.gnome.shell",
        "xdg-desktop-portal-kde", "xdg-desktop-portal-gnome", "cosmic-panel",
        "cosmic-launcher", "cosmic-app-library", "ksmserver-logout-greeter",
        "org.kde.polkit-kde-authentication-agent-1"})
    PROMPTED_MAX = 200

    def _should_suggest(self, app):
        app = (app or "").strip().lower()
        if not app or app in self.IGNORED_APPS:
            return False
        if not self.get("app.suggest_profiles", True):
            return False
        if app in (self.get("app.profile_prompted") or []):
            return False
        return app not in (self._load_profiles().get("hardware") or {})

    def _on_new_app(self, app):
        if self._should_suggest(app):
            self._pending_app = app.strip().lower()
            self.profileSuggested.emit()

    @staticmethod
    def _app_display_name(app):
        """The desktop entry's name for a window class, else the class."""
        try:
            from gi.repository import Gio
            info = None
            for candidate in (app, app.lower()):
                try:
                    info = Gio.DesktopAppInfo.new(candidate + ".desktop")
                except Exception:
                    info = None
                if info is not None:
                    break
            if info is None:
                hits = Gio.DesktopAppInfo.search(app) or []
                if hits and hits[0]:
                    info = Gio.DesktopAppInfo.new(hits[0][0])
            if info is not None and info.get_display_name():
                return info.get_display_name()
        except Exception:
            pass
        return app

    @pyqtSlot(result="QVariant")
    def takeProfileSuggestion(self):
        """The pending suggestion as {app, name}, or None. Taking it records
        the app so it is offered once, ever."""
        app, self._pending_app = self._pending_app, ""
        if not self._should_suggest(app):
            return None
        prompted = [a for a in (self.get("app.profile_prompted") or []) if a != app]
        self.setLocal("app.profile_prompted", (prompted + [app])[-self.PROMPTED_MAX:])
        return {"app": app, "name": self._app_display_name(app)}

    @pyqtSlot(str)
    def removeAppProfile(self, app):
        data = self._load_profiles()
        hw = data.get("hardware") or {}
        if app in hw:
            del hw[app]
            self._save_profiles(data)
            self.reloadConfig()

    @pyqtSlot(str, "QVariant")
    def saveAppProfile(self, app, obj):
        app = (app or "").strip().lower()
        if not app or not isinstance(obj, dict):
            return
        entry = {"dpi": max(400, min(8000, int(obj.get("dpi", 1600)))),
                 "smartshift": {"enabled": bool(obj.get("smartshiftEnabled", True)),
                                # UI sensitivity % -> device threshold 1..49,
                                # same conversion as the global scroll slider.
                                "threshold": self._dev_threshold(
                                    max(1, min(100, int(obj.get("smartshiftThreshold", 50)))))},
                 "hires": bool(obj.get("hires", True)),
                 "thumbwheel": str(obj.get("thumbwheel", "off"))}
        data = self._load_profiles()
        data.setdefault("hardware", {})[app] = entry
        self._save_profiles(data)
        self.reloadConfig()

    # ---- haptics ----
    @pyqtSlot(str)
    def testHaptic(self, pattern):
        self.daemon.call_async("TriggerHapticPattern", pattern)

    # ---- easy-switch ----
    @pyqtSlot(int)
    def switchHost(self, host):
        self.daemon.call_async("SetHost", _u8(host))
        self._cur_host = host
        self.liveChanged.emit()

    @pyqtSlot(int, str)
    def setHostOs(self, slot, os_key):
        arr = list(self.get("radial_menu.easy_switch_host_os") or [])
        while len(arr) <= slot:
            arr.append("unknown")
        arr[slot] = os_key
        self.setLocal("radial_menu.easy_switch_host_os", arr)

    # ---- gaming ----
    @pyqtProperty(bool, notify=liveChanged)
    def gamingMode(self):
        """Live gaming-mode state (kept in sync with the daemon signal)."""
        return self._gaming_mode

    @pyqtSlot(bool)
    def setGamingMode(self, on):
        self._gaming_mode = bool(on)
        self.setLocal("gaming.enabled", bool(on))
        self.daemon.call_async("SetGamingMode", bool(on))
        self.liveChanged.emit()

    @pyqtSlot(int, str, "QVariant")
    def setGamingProfile(self, idx, field, value):
        profiles = list(self.get("gaming.dpi_profiles") or [])
        if 0 <= idx < len(profiles):
            profiles[idx][field] = value
            self.setLocal("gaming.dpi_profiles", profiles)

    # ---- macros ----
    @pyqtSlot(result="QVariant")
    def listMacros(self):
        raw = self.daemon.call1("ListMacros", default="[]") or "[]"
        try:
            return json.loads(raw)
        except Exception:
            return []

    @pyqtSlot(str)
    def runMacro(self, mid):
        self.daemon.call("ExecuteMacro", mid)

    @pyqtSlot()
    def stopMacro(self):
        self.daemon.call("StopMacro")

    @pyqtSlot(str)
    def deleteMacro(self, mid):
        self.daemon.call("DeleteMacro", mid)
        self.daemon.call("ReloadMacroTriggers")  # drop the deleted macro's binding
        self.macrosChanged.emit()

    @pyqtSlot(str, result=bool)
    def saveMacro(self, macro_json):
        """Persist a full macro (JSON string) and rebuild the trigger map.
        The daemon's SaveMacro does NOT reload triggers itself, so we must."""
        r = self.daemon.call("SaveMacro", macro_json)
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return r is not None

    @pyqtSlot(str, str, result=bool)
    def setMacroMeta(self, mid, field, value):
        """Edit one top-level field (name/description) of a stored macro."""
        m = next((x for x in self.listMacros() if x.get("id") == mid), None)
        if not m:
            return False
        m[field] = value
        self.daemon.call("SaveMacro", json.dumps(m))
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return True

    @pyqtSlot(str, str, result=bool)
    def setMacroTrigger(self, mid, trigger):
        """Bind/clear a macro's trigger ('mouse:N', or '' to unbind)."""
        m = next((x for x in self.listMacros() if x.get("id") == mid), None)
        if not m:
            return False
        m["assigned_trigger"] = trigger or None
        self.daemon.call("SaveMacro", json.dumps(m))
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return True

    @pyqtSlot(str, result="QVariant")
    def getMacro(self, mid):
        """Full stored macro (id/name/actions/repeat_mode/...) or {} if absent."""
        return next((x for x in self.listMacros() if x.get("id") == mid), {})

    @pyqtSlot(str, "QVariant", result=bool)
    def saveMacroSteps(self, mid, actions):
        """Replace a macro's ordered action list and resave (step editor)."""
        m = next((x for x in self.listMacros() if x.get("id") == mid), None)
        if not m:
            return False
        m["actions"] = [dict(a) for a in (actions or []) if isinstance(a, dict)]
        self.daemon.call("SaveMacro", json.dumps(m))
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return True

    @pyqtSlot(str, str, int, result=bool)
    def setMacroRepeat(self, mid, mode, count):
        """Set repeat mode (once/while_holding/toggle/repeat_n) + count."""
        m = next((x for x in self.listMacros() if x.get("id") == mid), None)
        if not m:
            return False
        valid = {"once", "while_holding", "toggle", "repeat_n", "sequence"}
        m["repeat_mode"] = mode if mode in valid else "once"
        m["repeat_count"] = max(1, min(999, int(count)))
        self.daemon.call("SaveMacro", json.dumps(m))
        self.macrosChanged.emit()
        return True

    @pyqtSlot(str, result=bool)
    def duplicateMacro(self, mid):
        """Clone a stored macro under a fresh id (trigger intentionally dropped)."""
        m = next((x for x in self.listMacros() if x.get("id") == mid), None)
        if not m:
            return False
        existing = {x.get("id") for x in self.listMacros()}
        base = (m.get("id") or "macro") + "_copy"
        new_id, n = base, 2
        while new_id in existing:
            new_id, n = f"{base}{n}", n + 1
        clone = dict(m)
        clone["id"] = new_id
        clone["name"] = (m.get("name") or "Macro") + " copy"
        clone["assigned_trigger"] = None  # never inherit a binding (one button, one macro)
        self.daemon.call("SaveMacro", json.dumps(clone))
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return True

    @pyqtSlot(result="QVariant")
    def macroRepeatModes(self):
        return [{"id": "once", "name": "Once"},
                {"id": "while_holding", "name": "While held"},
                {"id": "toggle", "name": "Toggle on/off"},
                {"id": "repeat_n", "name": "Repeat N times"}]

    @pyqtSlot(result="QVariant")
    def macroTriggerOptions(self):
        # mouse:N -> evdev in the daemon; back/forward/side are the realistically
        # bindable ones (must be a divertable button to actually fire).
        return [{"value": "", "name": "Not bound"},
                {"value": "mouse:8", "name": "Back button"},
                {"value": "mouse:9", "name": "Forward button"},
                {"value": "mouse:2", "name": "Middle click"},
                {"value": "mouse:10", "name": "Side / extra button"}]

    _recording = False

    @pyqtProperty(bool, notify=macrosChanged)
    def recording(self):
        return self._recording

    @pyqtSlot()
    def startMacroRecording(self):
        if self.daemon.available:
            self.daemon.call("StartMacroRecording")
            self._recording = True
            self.macrosChanged.emit()

    @pyqtSlot(str, result=bool)
    def stopMacroRecording(self, name):
        """Stop recording, name + persist the captured macro. Returns success."""
        self._recording = False
        r = self.daemon.call("StopMacroRecording")
        self.macrosChanged.emit()
        if not r:
            return False
        try:
            data = json.loads(r[0]) if isinstance(r[0], str) else {}
        except Exception:
            data = {}
        if not data.get("actions"):
            # unparseable reply or nothing captured: don't save an empty macro
            self.toast.emit("Recording failed")
            return False
        data["name"] = name or "New macro"
        self.daemon.call("SaveMacro", json.dumps(data))
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return True

    # ---- restore defaults ----
    @pyqtSlot()
    def restoreDefaults(self):
        self._cfg = copy.deepcopy(DEFAULT_CONFIG)
        self._save()
        self._slices.load(self.get("radial_menu.slices") or [])
        self.reloadConfig()
        self.configChanged.emit()
        self.configReloaded.emit()
        self.toast.emit("Settings restored to defaults")

    # ---- live device name + link ----
    def _set_device_name_live(self, name):
        if name:
            self._device_name = name
        self._connection = self._detect_connection(self.isGeneric)
        self.liveChanged.emit()

    @pyqtProperty(str, notify=liveChanged)
    def unitId(self):
        """The mouse's unit id as the config `devices` key ("0x1234ABCD"), or ""."""
        return self._unit_id

    @pyqtProperty(str, notify=liveChanged)
    def connection(self):
        """How the mouse is linked: Bolt receiver, Unifying receiver, USB
        receiver, Bluetooth, or a receiver plus Bluetooth (0.4.4 Devices row)."""
        return self._connection or ("USB" if self.isGeneric else "USB receiver")

    @staticmethod
    def _detect_connection(generic=False, hid_root="/sys/bus/hid/devices"):
        """Read the HID bus from sysfs like the GTK Devices page: entries are
        BBBB:VVVV:PPPP.NNNN, bus 0005 = Bluetooth and 0003 = USB, Logitech is
        046D, the Bolt receiver C548, Unifying C52B / C534. Generic mice only
        tell Bluetooth from USB."""
        try:
            names = [n.upper() for n in os.listdir(hid_root)]
        except OSError:
            names = []
        if generic:
            return "Bluetooth" if any(n.startswith("0005:") for n in names) else "USB"
        bluetooth, receiver = False, None
        for name in names:
            if ":046D:" not in name:
                continue
            if name.startswith("0005:"):
                bluetooth = True
            elif name.startswith("0003:"):
                pid = name.split(".")[0].rsplit(":", 1)[-1]
                if pid == "C548":
                    receiver = "Bolt receiver"
                elif pid in ("C52B", "C534"):
                    receiver = "Unifying receiver"
                elif receiver is None:
                    receiver = "USB receiver"
        if receiver and bluetooth:
            return receiver + " + Bluetooth"
        if bluetooth:
            return "Bluetooth"
        return receiver or "USB receiver"

    # ---- Actions Ring geometry (Settings → Appearance) ----
    @pyqtSlot(result="QVariant")
    def ringGeometry(self):
        outer = self.get("radial.outer_radius")
        inner = self.get("radial.inner_radius")
        return {"outer": int(outer or RING_OUTER_DEFAULT),
                "inner": int(inner or RING_INNER_DEFAULT),
                "custom": outer is not None or inner is not None,
                "outerMin": RING_OUTER_MIN, "outerMax": RING_OUTER_MAX,
                "innerMin": RING_INNER_MIN, "margin": RING_INNER_MARGIN,
                "outerDefault": RING_OUTER_DEFAULT, "innerDefault": RING_INNER_DEFAULT}

    @pyqtSlot(int)
    def setRingOuter(self, value):
        """Outer radius in px. A too-large centre zone is pulled in with it
        (same clamps as the GTK app). The overlay re-reads radial.* every
        time the menu opens, so no daemon reload is involved."""
        value = int(max(RING_OUTER_MIN, min(RING_OUTER_MAX, int(value))))
        inner = self.get("radial.inner_radius")
        if inner is not None and int(inner) > value - RING_INNER_MARGIN:
            self._set_path(["radial", "inner_radius"],
                           max(RING_INNER_MIN, value - RING_INNER_MARGIN))
        self._set_path(["radial", "outer_radius"], value)
        self._save()
        self.configChanged.emit()

    @pyqtSlot(int)
    def setRingInner(self, value):
        outer = int(self.get("radial.outer_radius") or RING_OUTER_DEFAULT)
        value = int(max(RING_INNER_MIN, min(int(value), outer - RING_INNER_MARGIN)))
        self._set_path(["radial", "inner_radius"], value)
        self._save()
        self.configChanged.emit()

    @pyqtSlot()
    def resetRingGeometry(self):
        """Back to the theme default: null clears the override (what the GTK
        app writes and what the overlay treats as unset)."""
        self._set_path(["radial", "outer_radius"], None)
        self._set_path(["radial", "inner_radius"], None)
        self._save()
        self.configChanged.emit()

    # ---- installed applications ("Pick application" for slices and links) ----
    @staticmethod
    def _command_for_exec(exec_line):
        """Plain shell command from a Desktop Entry Exec line: field codes
        dropped, %% collapsed to one percent (the GTK picker's rule)."""
        return _FIELD_CODE_RE.sub(lambda m: "%" if m.group(0) == "%%" else "",
                                  exec_line or "").strip()

    @pyqtSlot(result="QVariant")
    def listApplications(self):
        """Installed applications as the desktop menu lists them (Gio), without
        hidden entries and without Terminal=true ones, which open no window
        when launched from a slice. Sorted by name."""
        try:
            from gi.repository import Gio
        except Exception:
            return []
        out = []
        for app in Gio.AppInfo.get_all():
            try:
                if not app.should_show():
                    continue
                desktop = isinstance(app, Gio.DesktopAppInfo)
                if desktop and app.get_boolean("Terminal"):
                    continue
                command = self._command_for_exec(
                    app.get_string("Exec") if desktop else app.get_commandline())
                if not command:
                    continue
                icon, icon_name = app.get_icon(), ""
                if isinstance(icon, Gio.ThemedIcon):
                    names = icon.get_names() or []
                    icon_name = names[0] if names else ""
                elif isinstance(icon, Gio.FileIcon):
                    icon_name = icon.get_file().get_path() or ""
                out.append({"id": app.get_id() or "",
                            "name": app.get_display_name() or app.get_name() or "",
                            "command": command, "icon": icon_name,
                            "description": app.get_description() or ""})
            except Exception:
                continue
        out.sort(key=lambda a: a["name"].lower())
        return out

    @pyqtSlot(str, result=str)
    def cacheAppIcon(self, app_id):
        """Copy or render an application's icon into ~/.config/juhradial/icons/
        (the cache the GTK picker uses, which the overlay draws from) and
        return the absolute path, or "" when the icon cannot be resolved."""
        try:
            from gi.repository import Gio
            app = Gio.DesktopAppInfo.new(app_id) if app_id else None
        except Exception:
            return ""
        icon = app.get_icon() if app is not None else None
        if icon is None:
            return ""
        safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in app_id)
        dest_dir = CONFIG_DIR / "icons"
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(icon, Gio.FileIcon):
                src = icon.get_file().get_path()
                if not src or not os.path.isfile(src):
                    return ""
                dest = dest_dir / (safe_id + (os.path.splitext(src)[1] or ".png"))
                shutil.copyfile(src, dest)
                return str(dest)
            names = icon.get_names() if isinstance(icon, Gio.ThemedIcon) else []
            for name in names or []:
                qicon = QIcon.fromTheme(name)
                if qicon.isNull():
                    continue
                pm = qicon.pixmap(QSize(64, 64))
                dest = dest_dir / (safe_id + ".png")
                if not pm.isNull() and pm.save(str(dest), "PNG"):
                    return str(dest)
        except Exception:
            return ""
        return ""

    # ---- app / autostart ----
    @pyqtSlot()
    def refreshDevices(self):
        """Re-query the daemon for battery / DPI / easy-switch host state."""
        self._prime()

    @pyqtSlot()
    def quitApp(self):
        """Close the settings window (the app has no tray of its own)."""
        QCoreApplication.quit()

    @pyqtSlot(bool)
    def setStartAtLogin(self, on):
        self.setLocal("app.start_at_login", bool(on))
        try:
            if on:
                self._write_autostart(self._find_launcher())
            elif AUTOSTART.exists():
                AUTOSTART.unlink()
        except Exception as e:
            self.toast.emit(f"Autostart: {e}")

    @staticmethod
    def _installed_launcher():
        for c in (shutil.which("juhradial-mx"), "/usr/local/bin/juhradial-mx",
                  "/usr/bin/juhradial-mx"):
            if c and os.path.exists(c):
                return c
        return None

    @classmethod
    def _find_launcher(cls):
        """The juhradial-mx launcher (daemon + overlay), or this checkout's
        script. Never the bare daemon: the systemd unit owns that, and a login
        entry pointing at it would leave the overlay unstarted (#129)."""
        installed = cls._installed_launcher()
        if installed:
            return installed
        dev = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "juhradial-mx.sh"
        return str(dev) if dev.exists() else "juhradial-mx"

    @staticmethod
    def _write_autostart(exec_path):
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(
            "[Desktop Entry]\nType=Application\nName=JuhRadial MX\n"
            "Comment=Radial menu for Logitech MX Master\n"
            f"Exec={exec_path}\nIcon=juhradial-mx\nTerminal=false\n"
            "Categories=Utility;\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8")

    def _repair_autostart_if_stale(self):
        """Keep the login entry working without a re-toggle (GTK app parity).

        Creates a missing entry when Start at Login is on and an installed
        launcher exists (a bare checkout never makes itself the autostart), and
        rewrites an Exec whose binary is gone: older builds hardcoded
        /usr/bin/juhradial-mx, which fails with status=127 on curl installs
        (#32, #129). A valid entry is left alone.
        """
        if not self.get("app.start_at_login", True):
            return
        try:
            if not AUTOSTART.exists():
                installed = self._installed_launcher()
                if installed:
                    self._write_autostart(installed)
                return
            exec_line = next((ln for ln in AUTOSTART.read_text(encoding="utf-8").splitlines()
                              if ln.startswith("Exec=")), "")
            current = exec_line[len("Exec="):].strip().split()
            if current and os.path.exists(current[0]):
                return
            self._write_autostart(self._find_launcher())
        except OSError:
            pass

    # ---- backup: one implementation, in the daemon binary ----
    # `juhradiald --export FILE` / `--import FILE` (daemon/src/backup.rs) own
    # the archive format and the validation; the app only runs them.
    @staticmethod
    def _daemon_binary():
        """The installed daemon, or this checkout's release build."""
        dev = (pathlib.Path(__file__).resolve().parents[2]
               / "daemon" / "target" / "release" / "juhradiald")
        for c in (shutil.which("juhradiald"), "/usr/local/bin/juhradiald",
                  "/usr/bin/juhradiald", str(dev)):
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    @staticmethod
    def _local_path(url):
        """A QML file url (or a plain path) as a filesystem path."""
        return QUrl(url).toLocalFile() if url.startswith("file:") else url

    @pyqtSlot(result=str)
    def suggestedBackupUrl(self):
        """Pre-filled target for the export dialog: a dated name in
        ~/Downloads when that exists, else in the home directory."""
        folder = pathlib.Path.home() / "Downloads"
        if not folder.is_dir():
            folder = pathlib.Path.home()
        name = time.strftime("juhradial-backup-%Y%m%d-%H%M.zip")
        return QUrl.fromLocalFile(str(folder / name)).toString()

    def _run_backup(self, flag, path):
        """Run `juhradiald <flag> <path>`; returns (ok, message)."""
        binary = self._daemon_binary()
        if not binary:
            return False, "juhradiald not found"
        try:
            r = subprocess.run([binary, flag, path], capture_output=True,
                               text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
        if r.returncode != 0:
            lines = r.stderr.strip().splitlines() or r.stdout.strip().splitlines()
            return False, lines[-1] if lines else f"exit status {r.returncode}"
        return True, r.stdout.strip()

    @pyqtSlot(str, result=bool)
    def exportBackup(self, url):
        path = self._local_path(url)
        ok, msg = self._run_backup("--export", path)
        if ok:
            self.notify(f"Backup saved as {os.path.basename(path)}", "success")
        else:
            self.notify(f"Export failed: {msg}", "danger")
        return ok

    @pyqtSlot(str, result=bool)
    def importBackup(self, url):
        path = self._local_path(url)
        ok, msg = self._run_backup("--import", path)
        if not ok:
            self.notify(f"Import failed: {msg}", "danger")
            return False
        # The daemon has already reloaded its config and macro triggers; now
        # pick the new files up in this process and rebuild the visible page.
        self._load()
        self._slices.load(self.get("radial_menu.slices") or [])
        self.reloadConfig()
        self.configChanged.emit()
        self.macrosChanged.emit()
        self.configReloaded.emit()
        self.notify("Settings imported. The previous files are kept as .bak", "success")
        return True

    # ---- desktop-environment defaults ----
    @pyqtSlot(str)
    def applyDeDefaults(self, de_key):
        cmds = {
            "kde": {"screenshot": ("exec", "spectacle"), "files": ("exec", "dolphin"),
                    "new_note": ("exec", "kwrite"), "emoji": ("emoji", ""),
                    "lock": ("exec", "loginctl lock-session")},
            "gnome": {"screenshot": ("exec", "gnome-screenshot --interactive"),
                      "files": ("exec", "nautilus"), "new_note": ("exec", "gnome-text-editor"),
                      "emoji": ("exec", "gnome-characters"), "lock": ("exec", "loginctl lock-session")},
            "cosmic": {"screenshot": ("exec", "cosmic-screenshot"), "files": ("exec", "cosmic-files"),
                       "new_note": ("exec", "cosmic-edit"), "emoji": ("exec", "gnome-characters"),
                       "lock": ("exec", "loginctl lock-session")},
            "generic": {"screenshot": ("exec", "flameshot gui"), "files": ("exec", "xdg-open ~"),
                        "new_note": ("exec", "xdg-open"), "emoji": ("exec", "ibus emoji"),
                        "lock": ("exec", "loginctl lock-session")},
        }.get(de_key, {})
        slices = self._slices.slices()
        for s in slices:
            aid = s.get("action_id", "")
            if aid in cmds:
                s["type"], s["command"] = cmds[aid]
        self._slices.load(slices)
        self._set_path(["radial_menu", "slices"], slices)
        self._save()
        self.reloadConfig()
        self.toast.emit("Applied desktop defaults")

    # ---- constants for QML ----
    @pyqtSlot(result="QVariant")
    def buttonSlots(self):
        return [{"slot": k, "name": n, "default": d} for (k, n, d) in BUTTON_SLOTS]

    @pyqtSlot(str, str)
    def notify(self, text, kind="info"):
        self.toastRequested.emit(text, kind)

    # ---- dynamic control inventory (REPROG_CONTROLS_V4 via ListControls) ----
    # CIDs the named button slots already cover; anything else divertable is
    # offered in the "Other controls" card and stored under buttons.controls.
    SLOT_CIDS = {0x0052: "middle", 0x0053: "back", 0x0056: "forward",
                 0x00C3: "gesture", 0x00C4: "shift_wheel", 0x01A0: "thumb"}

    @pyqtSlot(result="QVariant")
    def listControls(self):
        """Every control the connected mouse reports, decoded by the daemon
        (see ListControls). Empty when the daemon is down or the mouse has no
        REPROG_CONTROLS_V4 feature. Blocking: the daemon scans the mouse under
        its device lock, so pages use requestControls() instead."""
        return self._parse_controls(self.daemon.call1("ListControls", default="[]"))

    @pyqtSlot()
    def requestControls(self):
        """Async listControls(): controlsReady fires with the assignable
        extras (see extraControls) once the daemon has answered."""
        self.daemon.call_then(
            "ListControls",
            lambda args: self.controlsReady.emit(
                self._extra_of(self._parse_controls(args[0] if args else "[]"))))

    def _parse_controls(self, raw):
        try:
            items = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        out = []
        for c in items if isinstance(items, list) else []:
            if not isinstance(c, dict):
                continue
            cid = int(c.get("cid", 0))
            c = dict(c)
            c["slot"] = self.SLOT_CIDS.get(cid, "")
            c["key"] = "buttons.controls." + c.get("hex", "0x%04X" % cid)
            out.append(c)
        return out

    @pyqtSlot(result="QVariant")
    def extraControls(self):
        """Divertable, non-virtual controls without a named slot (and never the
        primary clicks): the ones a user can assign under Other controls."""
        return self._extra_of(self.listControls())

    @staticmethod
    def _extra_of(controls):
        return [c for c in controls
                if c.get("divertable") and not c.get("virtual") and not c["slot"]
                and int(c.get("cid", 0)) not in (0x0050, 0x0051)]

    @pyqtSlot(result="QVariant")
    def buttonActions(self):
        return [{"id": i, "name": n, "icon": ic} for (i, n, ic) in BUTTON_ACTIONS]

    @pyqtSlot(result="QVariant")
    def radialActions(self):
        return [{"id": a, "name": n, "icon": ic, "type": t, "command": c, "color": col,
                 "hex": SLICE_COLORS.get(col, "#9399B2")}
                for (a, n, ic, t, c, col) in RADIAL_ACTIONS]

    @pyqtSlot(result="QVariant")
    def hapticPatterns(self):
        return [{"id": p, "name": p.replace("_", " ").title()} for p in HAPTIC_PATTERNS]

    @pyqtSlot(result="QVariant")
    def sliceColors(self):
        return [{"name": c, "hex": SLICE_COLORS[c]} for c in SLICE_COLOR_ORDER]

    @pyqtSlot(result="QVariant")
    def thumbwheelModes(self):
        return [{"id": i, "name": n} for (i, n) in THUMBWHEEL_MODES]

    @pyqtSlot(result="QVariant")
    def scrollModes(self):
        return [{"id": i, "name": n} for (i, n) in SCROLL_MODES]

    @pyqtSlot(result="QVariant")
    def easySwitchOs(self):
        return [{"id": i, "name": n} for (i, n) in EASY_SWITCH_OS]

    @pyqtSlot(result="QVariant")
    def desktopEnvs(self):
        return [{"id": i, "name": n} for (i, n) in DESKTOP_ENVS]

    @pyqtSlot(result="QVariant")
    def languages(self):
        return [{"id": i, "name": n} for (i, n) in LANGUAGES]

    # expose the slice model as a property for QML context binding
    @pyqtProperty(QObject, constant=True)
    def slices(self):
        return self._slices
