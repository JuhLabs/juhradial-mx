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

from PyQt6.QtCore import (
    QObject, pyqtSlot, pyqtProperty, pyqtSignal, QTimer, QCoreApplication,
    QAbstractListModel, QModelIndex, Qt, QByteArray,
)

try:
    from PyQt6.QtDBus import (QDBusConnection, QDBusInterface, QDBusMessage,
                              QDBusServiceWatcher)
    _HAVE_DBUS = True
except Exception:  # pragma: no cover - QtDBus should be present
    _HAVE_DBUS = False

_XDG_CONFIG = pathlib.Path(os.environ.get("XDG_CONFIG_HOME",
                                          str(pathlib.Path.home() / ".config")))
CONFIG_DIR = _XDG_CONFIG / "juhradial"
CONFIG = CONFIG_DIR / "config.json"
PROFILES = CONFIG_DIR / "profiles.json"
AUTOSTART = _XDG_CONFIG / "autostart" / "juhradial-mx.desktop"

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
    ("settings", "Start at login", "Startup", "autostart startup launch boot login"),
    ("settings", "Show tray icon", "Startup", "tray icon system tray notification area"),
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
                    "easy_switch_host_os": ["linux", "windows", "macos"],
                    "ai_links": DEFAULT_AI_LINKS},
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
    "app": {"start_at_login": False, "show_tray_icon": True},
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
    gamingModeChanged = pyqtSignal(bool)
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
        self._bus.connect("", OBJ_PATH, IFACE, "BatteryChanged",
                          self._on_battery)
        self._bus.connect("", OBJ_PATH, IFACE, "DpiChanged", self._on_dpi)
        self._bus.connect("", OBJ_PATH, IFACE, "HostChanged", self._on_host)
        self._bus.connect("", OBJ_PATH, IFACE, "RatchetChanged", self._on_ratchet)
        self._bus.connect("", OBJ_PATH, IFACE, "GamingModeChanged", self._on_gaming)
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
    navRequested = pyqtSignal(str)   # a page asks the shell to switch tabs
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

        self._gaming_mode = bool(self.get("gaming.enabled", False))
        self._low_batt_notified = False

        self.daemon.batteryChanged.connect(self._set_battery)
        self.daemon.dpiChanged.connect(self._set_dpi_live)
        self.daemon.hostChanged.connect(self._set_host_live)
        self.daemon.ratchetChanged.connect(self._set_ratchet_live)
        self.daemon.gamingModeChanged.connect(self._set_gaming_live)
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
            self._wheel_mode = self._derive_wheel_mode(bool(ss[0]), _to_int(ss[1]))

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
            self.liveChanged.emit()
            return
        self._device_name = d.call1("GetDeviceName", default="") or ""
        self._device_mode = d.call1("GetDeviceMode", default="") or ""
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
        if pct <= 15 and not self._low_batt_notified:
            self._low_batt_notified = True
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "JuhRadial MX", "-i", "battery-low-symbolic",
                     "-u", "critical", "Mouse battery low",
                     f"MX Master 4 is at {pct}%. Time to recharge."])
            except Exception:
                pass

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
        self.daemon.call_async("SetDpi", dpi)
        self.liveChanged.emit()

    @pyqtSlot(str)
    def setScrollMode(self, mode):
        self.setLocal("scroll.mode", mode)
        thr = int(self.get("scroll.smartshift_threshold", 50))
        if mode == "smartshift":
            self.daemon.call("SetSmartShift", True, self._dev_threshold(thr))
        elif mode == "ratchet":
            # (False, _) = permanently ratcheted (autoDisengage 255).
            self.daemon.call("SetSmartShift", False, 0)
        elif mode == "freespin":
            # (True, 0) = freespin.
            self.daemon.call("SetSmartShift", True, 0)
        self._wheel_mode = mode
        self.liveChanged.emit()

    @pyqtSlot(int)
    def setSmartShiftThreshold(self, ui_value):
        self.setLocal("scroll.smartshift_threshold", int(ui_value))
        self.daemon.call("SetSmartShift", True, self._dev_threshold(ui_value))

    @staticmethod
    def _dev_threshold(ui_value):
        # UI 1..100 -> device 1..254 (higher = more ratchet-like). 0 and 255
        # are excluded: 0 means freespin and 255 permanent ratchet in the
        # daemon's SetSmartShift mapping.
        return max(1, min(254, int(round((100 - ui_value) * 2.55))))

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
        enabled = bool(self.get("keyboard.mx_keys.enabled", False))
        r = self.daemon.call("GetKeyboardBattery")
        pct, charging = 0, False
        if r and len(r) >= 2:
            pct, charging = _to_int(r[0]), bool(r[1])
        # Paired = receiver pairing table; true even while the keyboard's radio
        # sleeps (battery reads 0 then). Distinguishes "asleep" from "absent".
        paired = bool(self.daemon.call1("GetKeyboardPaired", default=False))
        present = paired or pct > 0 or charging
        keys = self.daemon.call1("ListKeyboardKeys", default=None) or []
        return {"present": present, "enabled": enabled, "battery": pct,
                "charging": charging, "sleeping": present and pct == 0,
                "keyCount": len(keys)}

    @pyqtSlot(int)
    def setKeyboardBacklight(self, level):
        """Set MX Keys S backlight 0..100% (mapped to the device's levels)."""
        r = self.daemon.call("SetKeyboardBacklight", max(0, min(100, int(level))))
        if not (r and len(r) >= 1 and r[0]):
            # A sleeping keyboard ignores HID++ until a key press wakes it.
            self.toast.emit("Keyboard not reachable - press a key to wake it, then try again")

    @pyqtSlot(str, float, float)
    def setPinPos(self, slot, nx, ny):
        """Persist a manually-placed callout pin (config.button_pins.<slot>)."""
        self._set_path(["button_pins", slot], {"nx": round(nx, 4), "ny": round(ny, 4)})
        self._save()
        self.toast.emit(f"Pin saved: {slot} = {nx:.3f}, {ny:.3f}")

    # ---- AI submenu quick-links ----
    @pyqtSlot(result="QVariant")
    def aiLinks(self):
        v = self.get("radial_menu.ai_links")
        return v if v else [dict(x) for x in DEFAULT_AI_LINKS]

    @pyqtSlot("QVariant")
    def setAiLinks(self, links):
        """Persist the editable AI-assistant quick-links (name+url, max 6)."""
        out = []
        for l in (links or []):
            if not isinstance(l, dict):
                continue
            name = str(l.get("name", "")).strip()
            url = str(l.get("url", "")).strip()
            if not name or not url:
                continue
            if "://" not in url:
                url = "https://" + url
            out.append({"name": name, "url": url,
                        "icon": str(l.get("icon", "") or "browser")})
        self._set_path(["radial_menu", "ai_links"], out[:6])
        self._save()
        self.reloadConfig()
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
            # profiles.json stores the device threshold (1-254, what the daemon
            # sends to the mouse); the UI slider speaks sensitivity % (1-100).
            dev_thr = int(ss.get("threshold", 128))
            ui_thr = max(1, min(100, 100 - int(round(dev_thr / 2.55))))
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
            hw[app] = {"dpi": 1600, "smartshift": {"enabled": True, "threshold": 128},
                       "hires": True, "thumbwheel": "off"}
            self._save_profiles(data)
            self.reloadConfig()
            self.toast.emit(f"Added profile: {app}")

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
                                # UI sensitivity % -> device threshold 1-254,
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
        self.daemon.call_async("SetHost", host)
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
        self.toast.emit("Settings restored to defaults")

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
                AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                launcher = self._find_launcher()
                AUTOSTART.write_text(
                    "[Desktop Entry]\nType=Application\nName=JuhRadial MX\n"
                    f"Exec={launcher}\nX-GNOME-Autostart-enabled=true\nTerminal=false\n")
            elif AUTOSTART.exists():
                AUTOSTART.unlink()
        except Exception as e:
            self.toast.emit(f"Autostart: {e}")

    @staticmethod
    def _find_launcher():
        # juhradial-mx starts daemon + overlay; the bare daemon is a fallback.
        for name in ("juhradial-mx", "juhradiald"):
            p = shutil.which(name)
            if p:
                return p
        for c in ("/usr/local/bin/juhradiald", "/usr/bin/juhradiald"):
            if os.path.exists(c):
                return c
        return "juhradiald"

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
