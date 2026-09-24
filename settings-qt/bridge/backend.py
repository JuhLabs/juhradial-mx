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

from bridge.i18n import _


def _xdg_icon_file(name, roots=None):
    """An application icon file by name outside the Qt theme: the largest
    hicolor PNG, a scalable SVG, or /usr/share/pixmaps."""
    home = pathlib.Path.home()
    roots = roots or [home / ".local/share/icons/hicolor", home / ".local/share/flatpak/exports/share/icons/hicolor",
                      pathlib.Path("/var/lib/flatpak/exports/share/icons/hicolor"),
                      pathlib.Path("/usr/share/icons/hicolor"), pathlib.Path("/usr/share/pixmaps")]
    for root in roots:
        if root.name == "pixmaps":
            for ext in (".png", ".svg", ".xpm"):
                if (root / (name + ext)).is_file():
                    return str(root / (name + ext))
            continue
        svg = root / "scalable" / "apps" / (name + ".svg")
        if svg.is_file():
            return str(svg)
        for size in ("512x512", "256x256", "128x128", "96x96", "64x64", "48x48"):
            png = root / size / "apps" / (name + ".png")
            if png.is_file():
                return str(png)
    return ""


def QDesktopServicesOpen(url):
    """Open a URL or file in the user's default app."""
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))
from PyQt6.QtGui import QIcon

try:
    from PyQt6.QtDBus import (QDBus, QDBusArgument, QDBusConnection,
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

# Picker ids for plugin actions: "plugin:<folder>/<action id>" (ListPlugins).
PLUGIN_PREFIX = "plugin:"
PLUGINS_DIR = CONFIG_DIR / "plugins"

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

# Picker groups for physical-button actions, in display order.
BUTTON_GROUPS = [("ring", "Actions Ring and desktop"), ("mouse", "Mouse"),
                 ("pointer", "Pointer speed"), ("edit", "Editing"),
                 ("browse", "Tabs and pages"), ("media", "Media"), ("system", "System"),
                 ("switch", "Easy-Switch"), ("other", "Other")]

# (id, label, freedesktop icon, group) for physical-button assignment
# (daemon ButtonAction, config.rs).
BUTTON_ACTIONS = [
    ("radial_menu", "Actions Ring", "view-grid-symbolic", "ring"),
    ("virtual_desktops", "Virtual Desktops", "view-app-grid-symbolic", "ring"),
    ("show_desktop", "Show Desktop", "user-desktop-symbolic", "ring"),
    ("switch_desktop_left", "Desktop Left", "go-previous-symbolic", "ring"),
    ("switch_desktop_right", "Desktop Right", "go-next-symbolic", "ring"),
    ("task_switcher", "Task Switcher", "view-paged-symbolic", "ring"),
    ("close_window", "Close Window", "window-close-symbolic", "ring"),
    ("left_click", "Left Click", "input-mouse-symbolic", "mouse"),
    ("right_click", "Right Click", "input-mouse-symbolic", "mouse"),
    ("middle_click", "Middle Click", "input-mouse-symbolic", "mouse"),
    ("back", "Back", "go-previous-symbolic", "mouse"),
    ("forward", "Forward", "go-next-symbolic", "mouse"),
    ("scroll_left", "Scroll Left", "go-previous-symbolic", "mouse"),
    ("scroll_right", "Scroll Right", "go-next-symbolic", "mouse"),
    ("smartshift", "Switch Ratchet / Free-spin", "emblem-synchronizing-symbolic", "mouse"),
    ("scroll_left_right", "Scroll Left/Right", "object-flip-horizontal-symbolic", "mouse"),
    ("dpi_cycle", "Cycle DPI Presets", "utilities-system-monitor-symbolic", "pointer"),
    ("dpi_up", "DPI Up", "utilities-system-monitor-symbolic", "pointer"),
    ("dpi_down", "DPI Down", "utilities-system-monitor-symbolic", "pointer"),
    ("dpi_shift", "Precision DPI While Held", "system-search-symbolic", "pointer"),
    ("copy", "Copy", "edit-copy-symbolic", "edit"), ("paste", "Paste", "edit-paste-symbolic", "edit"),
    ("undo", "Undo", "edit-undo-symbolic", "edit"), ("redo", "Redo", "edit-redo-symbolic", "edit"),
    ("tab_next", "Next Tab", "view-paged-symbolic", "browse"),
    ("tab_prev", "Previous Tab", "view-paged-symbolic", "browse"),
    ("tab_close", "Close Tab", "window-close-symbolic", "browse"),
    ("tab_reopen", "Reopen Closed Tab", "edit-undo-symbolic", "browse"),
    ("page_up", "Page Up", "view-list-symbolic", "browse"),
    ("page_down", "Page Down", "view-list-symbolic", "browse"),
    ("home", "Home", "view-list-symbolic", "browse"), ("end", "End", "view-list-symbolic", "browse"),
    ("zoom_in", "Zoom In", "zoom-in-symbolic", "browse"),
    ("zoom_out", "Zoom Out", "zoom-out-symbolic", "browse"),
    ("play_pause", "Play/Pause", "media-playback-start-symbolic", "media"),
    ("volume_up", "Volume Up", "audio-volume-high-symbolic", "media"),
    ("volume_down", "Volume Down", "audio-volume-low-symbolic", "media"),
    ("mute", "Mute", "audio-volume-muted-symbolic", "media"),
    ("screenshot", "Screenshot", "camera-photo-symbolic", "system"),
    ("lock_screen", "Lock Screen", "system-lock-screen-symbolic", "system"),
    ("calculator", "Calculator", "accessories-calculator-symbolic", "system"),
    ("gaming_mode", "Gaming Mode On/Off", "gaming", "system"),
    ("host1", "Switch to Computer 1", "easy-switch", "switch"),
    ("host2", "Switch to Computer 2", "easy-switch", "switch"),
    ("host3", "Switch to Computer 3", "easy-switch", "switch"),
    ("host_next", "Next Computer", "easy-switch", "switch"),
    ("custom", "Custom Action…", "preferences-desktop-keyboard-shortcuts-symbolic", "other"),
    ("none", "Disabled", "action-unavailable-symbolic", "other"),
]
# Kept nameable for older configs, never offered: on a button the native
# thumb-wheel mode does nothing.
HIDDEN_BUTTON_ACTIONS = {"scroll_left_right"}
# Not offered for a directional drag or an extra control: the ring cannot
# open mid-drag, a drag has no hold for the precision DPI.
DIRECTIONAL_EXCLUDED = {"radial_menu", "dpi_shift", "custom"}

# Custom button actions (buttons.custom.<slot>, daemon CustomAction).
CUSTOM_KINDS = ("shortcut", "command", "url", "macro", "plugin")
SHORTCUT_RE = re.compile(r"^[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*$")
# Macro trigger values that belong to a named button slot.
MACRO_TRIGGER_SLOTS = {"mouse:8": "back", "mouse:9": "forward", "mouse:2": "middle"}
MACRO_PREFIX = "macro:"
MODIFIER_KEYS = ("ctrl", "alt", "shift", "super")


def new_macro(mid, name, actions):
    """A macro as the daemon's MacroConfig reads it. Record then Save sent no
    id (SaveMacro rejected it, audit P0 #1) and no use_standard_delay, whose
    default replaces every recorded delay with 50 ms."""
    return {"id": mid, "name": name, "description": "", "repeat_mode": "once",
            "repeat_count": 3, "actions": list(actions), "standard_delay_ms": 50,
            "use_standard_delay": False, "assigned_trigger": None}


def macro_id_for(name, existing):
    """A file-safe id from a name ([a-z0-9_]), unique among `existing`."""
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:40] or "macro"
    mid, n = base, 2
    while mid in existing:
        mid, n = f"{base}_{n}", n + 1
    return mid


def macro_rows(actions):
    """The daemon's flat action list as editor rows: a key press and release
    (with the modifiers held around it) becomes one "keys" row with its chord
    ("ctrl+c") and hold time; delays in a row merge."""
    acts = [a for a in (actions or []) if isinstance(a, dict)]
    rows, i = [], 0

    def delay_at(j):
        return int(acts[j].get("ms", 0)) if j < len(acts) and acts[j].get("type") == "delay" else None

    while i < len(acts):
        a = acts[i]
        t = a.get("type")
        if t == "key_down":
            # modifiers down, one key tapped, modifiers up (delays anywhere)
            j, mods, hold = i, [], 0
            while j < len(acts) and (acts[j].get("type") == "delay"
                                     or (acts[j].get("type") == "key_down"
                                         and acts[j].get("key") in MODIFIER_KEYS)):
                if acts[j].get("type") == "delay":
                    hold += int(acts[j].get("ms", 0))
                else:
                    mods.append(acts[j]["key"])
                j += 1
            key = None
            if j < len(acts) and acts[j].get("type") == "key_down" and acts[j].get("key") not in MODIFIER_KEYS:
                key, j = acts[j].get("key"), j + 1
                while delay_at(j) is not None:
                    hold += delay_at(j)
                    j += 1
                if j < len(acts) and acts[j].get("type") == "key_up" and acts[j].get("key") == key:
                    j += 1
                    left = list(mods)
                    while left and j < len(acts):
                        if acts[j].get("type") == "delay":
                            hold += int(acts[j].get("ms", 0))
                        elif acts[j].get("type") == "key_up" and acts[j].get("key") in left:
                            left.remove(acts[j]["key"])
                        else:
                            break
                        j += 1
                    if not left:
                        rows.append({"kind": "keys", "chord": "+".join(mods + [key]), "hold": hold})
                        i = j
                        continue
            rows.append({"kind": "raw", "action": dict(a)})
            i += 1
        elif t == "delay":
            ms = int(a.get("ms", 0))
            if rows and rows[-1]["kind"] == "delay":
                rows[-1]["ms"] += ms
            else:
                rows.append({"kind": "delay", "ms": ms})
            i += 1
        elif t == "text":
            rows.append({"kind": "text", "text": str(a.get("text", ""))})
            i += 1
        elif t == "mouse_click":
            rows.append({"kind": "click", "button": str(a.get("button", "left"))})
            i += 1
        elif (t == "mouse_down" and i + 1 < len(acts)
              and acts[i + 1].get("type") in ("mouse_up", "delay")):
            # a recorded click: press, (hold), release of the same button
            j = i + 1 if acts[i + 1].get("type") == "mouse_up" else i + 2
            if j < len(acts) and acts[j].get("type") == "mouse_up" and acts[j].get("button") == a.get("button"):
                rows.append({"kind": "click", "button": str(a.get("button", "left"))})
                i = j + 1
            else:
                rows.append({"kind": "raw", "action": dict(a)})
                i += 1
        elif t == "scroll":
            rows.append({"kind": "scroll", "direction": str(a.get("direction", "down")),
                         "amount": int(a.get("amount", 1))})
            i += 1
        else:
            rows.append({"kind": "raw", "action": dict(a)})
            i += 1
    return rows


def macro_actions(rows):
    """Editor rows back to the daemon's flat action list."""
    out = []
    for r in rows or []:
        kind = r.get("kind")
        if kind == "keys":
            keys = [k for k in str(r.get("chord", "")).split("+") if k]
            out += [{"type": "key_down", "key": k} for k in keys]
            if int(r.get("hold", 0)) > 0:
                out.append({"type": "delay", "ms": int(r["hold"])})
            out += [{"type": "key_up", "key": k} for k in reversed(keys)]
        elif kind == "delay":
            out.append({"type": "delay", "ms": max(0, int(r.get("ms", 0)))})
        elif kind == "text":
            out.append({"type": "text", "text": str(r.get("text", ""))})
        elif kind == "click":
            out.append({"type": "mouse_click", "button": str(r.get("button", "left"))})
        elif kind == "scroll":
            out.append({"type": "scroll", "direction": str(r.get("direction", "down")),
                        "amount": max(1, int(r.get("amount", 1)))})
        elif kind == "raw" and isinstance(r.get("action"), dict):
            out.append(dict(r["action"]))
    return out


# Starter macros (audit 4.8 #19): (id, name, description, rows)
MACRO_TEMPLATES = [
    ("duplicate_line", "Duplicate line", "Copies the current line below itself",
     [{"kind": "keys", "chord": "Home", "hold": 0}, {"kind": "keys", "chord": "shift+End", "hold": 0},
      {"kind": "keys", "chord": "ctrl+c", "hold": 0}, {"kind": "keys", "chord": "End", "hold": 0},
      {"kind": "keys", "chord": "Return", "hold": 0}, {"kind": "keys", "chord": "ctrl+v", "hold": 0}]),
    ("paste_plain", "Paste as plain text", "Ctrl + Shift + V, understood by most apps",
     [{"kind": "keys", "chord": "ctrl+shift+v", "hold": 0}]),
    ("signature", "Type a signature", "Types a greeting you can edit",
     [{"kind": "text", "text": "Best regards,"}, {"kind": "keys", "chord": "Return", "hold": 0},
      {"kind": "text", "text": "Your Name"}]),
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

# Ring surface palettes (config "theme", overlay/themes.py THEMES keys):
# (key, name, light, base, border, 3D image, icon). base, border and icon are
# the colours the overlay paints the classic ring and its glyphs with (THEMES
# colors "base"/"surface2"/"subtext1");
# a 3D palette draws its own bitmap instead while the skin is Classic.
RING_PALETTES = [
    ("phosphor", "Phosphor", False, "#0c1019", "#1e2733", "", "#a4b1c0"),
    ("juhradial-mx", "JuhRadial MX", False, "#121418", "#2e3440", "", "#c8d0dc"),
    ("catppuccin-mocha", "Catppuccin Mocha", False, "#1e1e2e", "#585b70", "", "#bac2de"),
    ("nord", "Nord", False, "#434c5e", "#6e7a8a", "", "#e5e9f0"),
    ("dracula", "Dracula", False, "#343746", "#5a5e78", "", "#e2e2d8"),
    ("catppuccin-latte", "Catppuccin Latte", True, "#eff1f5", "#acb0be", "", "#5c5f77"),
    ("github-light", "GitHub Light", True, "#ffffff", "#d8dee4", "", "#57606a"),
    ("solarized-light", "Solarized Light", True, "#fdf6e3", "#d2cdb9", "", "#586e75"),
    ("3d-blossom", "Pearl Blossom (3D)", True, "#1c1418", "#443440", "radialwheel2.png", "#dcc0d0"),
    ("3d-neon", "Neon Sci-Fi (3D)", False, "#0e1220", "#242e4a", "radialwheel3.png", "#b0c8e8"),
    ("3d-pastel", "Dark Ember (3D)", False, "#1a1814", "#3a3428", "radialwheel4.png", "#d0c8b0"),
    ("3d-crystal", "Golden Classic (3D)", False, "#181614", "#38322a", "radialwheel5.png", "#d0c8a8"),
]
# Where the overlay looks for the 3D images: the checkout / /usr/share/juhradial
# (settings-qt's parent), then the /opt app dir.
RADIAL_WHEEL_DIRS = [pathlib.Path(__file__).resolve().parents[2] / "assets" / "radial-wheels",
                     pathlib.Path("/opt/juhradial-mx/assets/radial-wheels")]


def _radial_wheel_uri(name):
    for d in RADIAL_WHEEL_DIRS if name else ():
        if (d / name).exists():
            return (d / name).as_uri()
    return ""

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

THUMBWHEEL_MODES = [("off", "Horizontal scroll (default)"), ("volume", "Volume"),
                    ("scroll", "Scroll"), ("zoom", "Zoom")]
SCROLL_MODES = [("ratchet", "Ratchet"), ("smartshift", "SmartShift"), ("freespin", "Free-spin")]
EASY_SWITCH_OS = [("linux", "Linux"), ("windows", "Windows"), ("macos", "macOS"),
                  ("ios", "iOS"), ("android", "Android"), ("chromeos", "ChromeOS"),
                  ("unknown", "Unknown")]
DESKTOP_ENVS = [("auto", "Auto-detect"), ("kde", "KDE Plasma"), ("gnome", "GNOME"),
                ("cosmic", "COSMIC"), ("generic", "Generic / Other")]
# Every locale shipped in overlay/locales, in its own language.
LANGUAGES = [("en", "English"), ("ar", "العربية"), ("de", "Deutsch"),
             ("es", "Español"), ("fr", "Français"), ("hi", "हिन्दी"),
             ("it", "Italiano"), ("ja", "日本語"), ("ko", "한국어"),
             ("nb", "Norsk bokmål"), ("nl", "Nederlands"), ("pl", "Polski"),
             ("pt_BR", "Português (Brasil)"), ("ru", "Русский"), ("sv", "Svenska"),
             ("th", "ไทย"), ("tr", "Türkçe"), ("uk", "Українська"), ("zh_CN", "简体中文")]

# Ring geometry mirrors of overlay_constants (tests/test_settings_page_backend.py
# pins them): the overlay scales the ring to each monitor by its height.
RING_SCALE_REFERENCE_HEIGHT = 1440
RING_SCALE_MIN, RING_SCALE_MAX = 0.8, 2.0
ICON_SCALE_MIN, ICON_SCALE_MAX = 0.6, 1.6

REPO_URL = "https://github.com/JuhLabs/juhradial-mx"
DOCS_URL = "https://juhlabs.github.io/juhradial-mx/"
RELEASES_API = "https://api.github.com/repos/JuhLabs/juhradial-mx/releases/latest"
UPDATE_CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME", str(pathlib.Path.home() / ".cache"))) \
    / "juhradial" / "update.json"
UPDATE_INTERVAL_S = 24 * 3600


def version_tuple(v):
    """'v0.4.5' / '0.4.5' -> (0, 4, 5); anything unparsable -> ()."""
    parts = re.findall(r"\d+", str(v or "").lstrip("vV").split("-")[0])
    return tuple(int(x) for x in parts[:3])


def resolve_auto_fit(radial):
    """Same rule as overlay_actions.resolve_auto_fit: unset = on unless the
    user already chose a ring or icon size."""
    auto = radial.get("auto_fit") if isinstance(radial, dict) else None
    if isinstance(auto, bool):
        return auto
    radial = radial if isinstance(radial, dict) else {}
    return all(radial.get(k) is None for k in ("outer_radius", "inner_radius", "icon_scale"))


def detect_desktop_key(env=None):
    """Desktop-defaults key for Auto-detect: kde, gnome, cosmic or generic."""
    desk = (env if env is not None else os.environ).get("XDG_CURRENT_DESKTOP", "").lower()
    for key in ("kde", "gnome", "cosmic"):
        if key in desk:
            return key
    return "generic"

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
    ("buttons", "Custom action", "Button mapping", "custom shortcut key recorder command url link macro plugin application app"),
    ("buttons", "Editing for", "Button mapping", "per app profile scope buttons application remap"),
    ("buttons", "Actions Ring", "Actions Ring", "radial menu slice action edit eight thumb wheel ring"),
    ("buttons", "Wheel skin", "Actions Ring", "wheel skin appearance icon style azure obsidian"),
    ("buttons", "Ring size", "Actions Ring", "ring size automatic scale radius preview show on screen"),
    ("buttons", "Quick links", "Quick links", "quick links submenu ai assistant urls websites apps"),
    ("buttons", "Directional gestures", "Directional gestures", "gesture drag direction up down left right swipe"),
    ("buttons", "Drag distance", "Directional gestures", "gesture threshold pixels drag distance click"),
    ("buttons", "Other controls", "Other controls", "extra controls buttons divert dpi switch side buttons"),
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
    ("macros", "Record a macro", "Record", "record macro capture keystrokes new keyboard sequence"),
    ("macros", "Your macros", "Library", "macro list library run edit rename duplicate delete export import"),
    ("macros", "Bind to a button", "Library", "bind trigger button assign macro back forward press"),
    ("macros", "Start from a template", "Library", "template starter example duplicate line signature"),
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
    ("themes", "Colour theme", "Colour theme", "theme color colour accent wallpaper appearance"),
    ("themes", "Match the desktop accent", "Colour theme", "automatic desktop accent kde gnome follow"),
    ("themes", "Radial menu look", "Radial menu look", "wheel skin ring colours colors palette light preview show on screen"),
    ("themes", "Icon style", "Radial menu look", "icons mono line classic monochrome"),
    # Settings
    ("settings", "Theme", "Window", "theme color accent appearance style"),
    ("settings", "Reduce transparency", "Window", "transparency glass solid cards contrast gpu"),
    ("settings", "Reduce motion", "Window", "motion animation fade reduce accessibility"),
    ("settings", "Automatic size", "Radial menu", "automatic fit monitor screen size ring auto"),
    ("settings", "Ring size", "Radial menu", "ring size radius bigger smaller outer"),
    ("settings", "Center zone", "Radial menu", "center centre zone dead zone inner radius"),
    ("settings", "Icon size", "Radial menu", "icon size bigger smaller slice icons scale"),
    ("settings", "Icon style", "Radial menu", "icon style line classic mono monochrome glyphs"),
    ("settings", "Menu background blur", "Radial menu", "blur background menu frost radial"),
    ("settings", "Simplified wheel", "Radial menu", "simplified wheel minimal mode icons only"),
    ("settings", "Click outside to close", "Radial menu", "click outside dismiss close menu ring tap away"),
    ("settings", "Check for updates", "Startup", "update new version release notify"),
    ("settings", "Troubleshooting", "Troubleshooting", "troubleshoot restart daemon overlay log diagnostics bug report"),
    ("settings", "Language", "Language & desktop", "language interface locale translation"),
    ("settings", "Desktop environment", "Language & desktop", "desktop environment kde gnome cosmic integration"),
    ("settings", "Apply desktop defaults", "Language & desktop", "desktop defaults kde gnome apply actions"),
    ("apps", "Suggest profiles for new apps", "App profiles", "suggest new app profile prompt first launch toast"),
    ("settings", "Start at login", "Startup", "autostart startup launch boot login"),
    ("settings", "Show tray icon", "Startup", "tray icon system tray notification area"),
    ("settings", "Export settings", "Backup", "export backup zip save copy transfer another machine"),
    ("settings", "Import settings", "Backup", "import restore backup zip transfer another machine"),
    ("settings", "Plugins", "Plugins", "plugins extensions manifest plugin.json actions third party"),
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
    # Values here are merged into every save, so each must equal what the
    # overlay/daemon assume when the key is absent (tests/test_config_defaults_parity.py).
    # Absent on purpose: language (absent = desktop locale; "en" pinned English
    # on the first unrelated save), pointer.dpi and the scroll device keys (the
    # daemon replays whatever is present, so a merged default would be forced
    # onto the mouse at every wake), radial.icon_style (readers default to mono).
    "radial_menu": {"slices": DEFAULT_SLICES,
                    "easy_switch_shortcuts": False,
                    "easy_switch_host_os": ["unknown", "unknown", "unknown"]},
    "blur_enabled": True,
    "desktop_environment": "auto",
    "device_mode": "auto",
    "haptics": {
        "enabled": True, "default_pattern": "subtle_collision",
        "per_event": {"menu_appear": "damp_state_change", "slice_change": "subtle_collision",
                      "confirm": "sharp_state_change", "invalid": "angry_alert"},
        "intensity": 70, "debounce_ms": 20, "slice_debounce_ms": 20, "reentry_debounce_ms": 50,
    },
    "pointer": {"speed": 5, "acceleration": True},
    "scroll": {"speed": 3},
    "thumbwheel": {"mode": "off", "invert": False, "speed": 1},
    "buttons": {k: d for (k, _l, d) in BUTTON_SLOTS},
    # Start at Login defaults on (the installer writes the autostart entry).
    "app": {"start_at_login": True, "show_tray_icon": True, "suggest_profiles": True,
            "check_updates": True},
    # wheel "" is the overlay no-op (falsy in _config_wheel_key), so a merged
    # default never overrides the theme-derived wheel for existing users.
    "radial": {"minimal_mode": False, "wheel": "", "click_outside_closes": True},
    "gaming": {"enabled": False, "suppress_overlay": True, "active_dpi_profile": 1,
               "dpi_profiles": [{"name": "Precision", "dpi": 400, "color": "blue"},
                                {"name": "Normal", "dpi": 1000, "color": "green"},
                                {"name": "Fast", "dpi": 3200, "color": "red"}]},
    "flow": {"enabled": False, "direction": "right", "edge_trigger": True,
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
    linkChanged = pyqtSignal(str, str)
    buttonPressed = pyqtSignal(int)
    macroPlayback = pyqtSignal(bool)
    activeProfileChanged = pyqtSignal(str)
    menuRequested = pyqtSignal()
    availabilityChanged = pyqtSignal()

    TIMEOUT_MS = 2000

    def __init__(self):
        super().__init__()
        self._available = False
        if not _HAVE_DBUS:
            return
        self._bus = QDBusConnection.sessionBus()
        # Raw messages, not QDBusInterface: its constructor introspects the
        # daemon synchronously on the GUI thread (at startup and after every
        # daemon restart). Availability comes from the bus daemon instead.
        self._available = self._registered()
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
        # Mouse reachability (connected/asleep/away/offline).
        self._bus.connect("", OBJ_PATH, IFACE, "DeviceConnectionChanged", self._on_link)
        # A physical button went down (the Buttons tab lights its pin).
        self._bus.connect("", OBJ_PATH, IFACE, "ButtonPressed", self._on_button)
        self._bus.connect("", OBJ_PATH, IFACE, "ActiveProfileChanged", self._on_profile)
        self._bus.connect("", OBJ_PATH, IFACE, "MenuRequested", self._on_menu)
        self._bus.connect("", OBJ_PATH, IFACE, "MacroPlaybackStarted", self._on_macro_started)
        self._bus.connect("", OBJ_PATH, IFACE, "MacroPlaybackStopped", self._on_macro_stopped)
        self._watcher = QDBusServiceWatcher(
            BUS_NAME, self._bus,
            QDBusServiceWatcher.WatchModeFlag.WatchForRegistration
            | QDBusServiceWatcher.WatchModeFlag.WatchForUnregistration, self)
        self._watcher.serviceRegistered.connect(self._on_service_up)
        self._watcher.serviceUnregistered.connect(self._on_service_down)

    def _registered(self):
        try:
            # A QDBusReply is always truthy; the answer is in value().
            return bool(self._bus.interface().isServiceRegistered(BUS_NAME).value())
        except Exception:
            return False

    def _on_service_up(self, name=""):
        self._available = True
        self.availabilityChanged.emit()

    def _on_service_down(self, name=""):
        self._available = False
        self.availabilityChanged.emit()

    @property
    def available(self):
        return self._available

    @staticmethod
    def _message(method, args, iface=IFACE):
        msg = QDBusMessage.createMethodCall(BUS_NAME, OBJ_PATH, iface, method)
        if args:
            msg.setArguments(list(args))
        return msg

    def call(self, method, *args):
        """Blocking daemon call (setters only); list of reply args, or None."""
        if not self._available:
            return None
        reply = self._bus.call(self._message(method, args), QDBus.CallMode.Block,
                               self.TIMEOUT_MS)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            return None
        return reply.arguments()

    def call_async(self, method, *args):
        """Fire-and-forget daemon call (no UI-thread round trip); reply dropped."""
        if not self._available:
            return
        self._bus.asyncCall(self._message(method, args), self.TIMEOUT_MS)

    def call_then(self, method, callback, *args):
        """Async daemon call; `callback(reply_args or None)` runs on the UI
        thread when the reply lands, so a slow method (a keyboard HID++ probe
        can take seconds) never stalls page changes."""
        if not self._available:
            callback(None)
            return
        self._watch(self._bus.asyncCall(self._message(method, args), self.TIMEOUT_MS),
                    method, callback)

    def prop_then(self, name, callback):
        """Async property read; `callback(value or None)` on the UI thread."""
        if not self._available:
            callback(None)
            return
        msg = self._message("Get", [IFACE, name], "org.freedesktop.DBus.Properties")

        def _unwrap(result):
            v = result[0] if result else None
            if hasattr(v, "variant"):
                v = v.variant()
            callback(v)
        self._watch(self._bus.asyncCall(msg, self.TIMEOUT_MS), name, _unwrap)

    def _watch(self, pending, method, callback):
        watcher = QDBusPendingCallWatcher(pending, self)
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
    def _on_link(self, msg):
        a = msg.arguments()
        if len(a) >= 2:
            self.linkChanged.emit(str(a[0]), str(a[1]))

    @pyqtSlot(QDBusMessage)
    def _on_profile(self, msg):
        a = msg.arguments()
        self.activeProfileChanged.emit(str(a[0]) if a else "")

    @pyqtSlot(QDBusMessage)
    def _on_menu(self, msg):
        self.menuRequested.emit()

    @pyqtSlot(QDBusMessage)
    def _on_macro_started(self, msg):
        self.macroPlayback.emit(True)

    @pyqtSlot(QDBusMessage)
    def _on_macro_stopped(self, msg):
        self.macroPlayback.emit(False)

    @pyqtSlot(QDBusMessage)
    def _on_button(self, msg):
        a = msg.arguments()
        if a:
            self.buttonPressed.emit(_to_int(a[0]))

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
        if action_id.startswith((PLUGIN_PREFIX, MACRO_PREFIX)):
            entries = (self._backend.pluginActions() if action_id.startswith(PLUGIN_PREFIX)
                       else self._backend.macroActions())
            entry = next((a for a in entries if a["id"] == action_id), None)
            if entry is None:
                return
            color = self._slices[row].get("color", "teal")
            self._slices[row] = {"label": entry["label"], "action_id": entry["type"], "type": entry["type"],
                                 "command": entry["command"], "color": color, "icon": entry["icon"]}
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])
            self._persist()
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
        # A preset action_id makes the overlay show the preset's name and
        # button ("Files") instead of the picked app (gcarmin #117 port).
        s["action_id"] = "custom_app"
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
    buttonPressed = pyqtSignal(str)          # slot name, or "0x00D7" for extra controls
    recordingStatusReady = pyqtSignal("QVariant")
    macroRunningChanged = pyqtSignal()
    macroBindingsReady = pyqtSignal("QVariant")
    pluginsReady = pyqtSignal("QVariant")
    navRequested = pyqtSignal(str)   # a page asks the shell to switch tabs
    # config.json was replaced wholesale (import, restore defaults): the shell
    # re-instantiates the visible page so its controls read the new values.
    configReloaded = pyqtSignal()
    # A newly focused application may deserve a profile; the shell asks for it
    # with takeProfileSuggestion() once its window is active.
    profileSuggested = pyqtSignal()
    searchTargetChanged = pyqtSignal()
    # False until the first prime round answered (or PRIME_TIMEOUT_MS passed);
    # pages show placeholders for live readouts until then. Never goes back.
    primedChanged = pyqtSignal()

    PRIME_TIMEOUT_MS = 3000

    @pyqtSlot(str)
    def goTo(self, key):
        self.navRequested.emit(key)

    # ---- global settings search ----
    @pyqtSlot(result="QVariant")
    def searchIndex(self):
        """Every searchable setting: {tab, tabKey, label, section, keywords}."""
        # Labels go through the same catalog as the pages' qsTr(), so the
        # result shows, and flashes, the row under its translated label;
        # English keywords keep matching in every language.
        return [{"tabKey": tk, "tab": _(TAB_LABELS.get(tk, tk)), "label": _(lbl),
                 "section": _(sec), "keywords": kw + " " + lbl.lower()}
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
        self._hosts_known = False
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
        self._primed = False
        self._prime_gen = 0
        # Values the user set during a prime round: a late getter answer must
        # not overwrite them.
        self._local_edits = set()
        # None = the daemon lacks the method (older build): fall back.
        self._caps_daemon = None
        self._link_daemon = None
        # Language the running UI was built with (a change needs a restart).
        from bridge import i18n as _i18n
        self._start_language = _i18n.configured_language(CONFIG) or "system"
        self._update = self._read_update_cache()
        self._net = None

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
        self.daemon.linkChanged.connect(self._set_link_live)
        self.daemon.macroPlayback.connect(self._set_macro_running)
        self._active_profile = ""
        self.daemon.activeProfileChanged.connect(self._set_active_profile)
        self.daemon.menuRequested.connect(self._on_menu_opened)
        self.daemon.buttonPressed.connect(
            lambda cid: self.buttonPressed.emit(self.SLOT_CIDS.get(cid, "0x%04X" % cid)))
        self.daemon.availabilityChanged.connect(self._on_daemon_availability)

        # prime device state shortly after start (daemon may be warming up)
        QTimer.singleShot(150, self._prime)
        # daily update check, off the startup path
        QTimer.singleShot(4000, lambda: self.checkForUpdates(False))
        if self._load_failed:
            # deferred so the QML shell exists before the toast fires
            QTimer.singleShot(800, lambda: self.toast.emit(
                _("Config was corrupt; using defaults (backup: config.json.bad)")))

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
            self.toast.emit(_("Save failed: {error}").format(error=e))

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
        def _done(ss):
            self._apply_smartshift(ss)
            self.liveChanged.emit()
        self.daemon.call_then("GetSmartShift", _done)

    def _apply_smartshift(self, ss):
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

    @pyqtProperty(bool, notify=primedChanged)
    def primed(self):
        return self._primed

    def _set_primed(self):
        if not self._primed:
            self._primed = True
            self.primedChanged.emit()

    @pyqtProperty("QVariantMap", notify=liveChanged)
    def caps(self):
        """What the mouse can do. Newer daemon: GetCapabilities; older: the
        three legacy getters plus the haptics heuristic; {} while unknown."""
        if self._caps_daemon:
            return dict(self._caps_daemon)
        if not self.daemon.available or not self._primed:
            return {}
        return {"dpi": self._dpi_supported, "smartshift": self._ss_supported,
                "thumbwheel": self._tw_supported,
                "haptics": not self.isGeneric}

    @pyqtProperty(bool, notify=liveChanged)
    def dpiSupported(self):
        return bool(self.caps.get("dpi", False))

    @pyqtProperty(bool, notify=liveChanged)
    def hapticsSupported(self):
        return bool(self.caps.get("haptics", False))

    @pyqtProperty(str, notify=liveChanged)
    def linkState(self):
        """connected | asleep | away | offline (see GetDeviceConnection)."""
        if not self.daemon.available:
            return "offline"
        if self.isGeneric or self._link_daemon is None:
            return "connected"
        return self._link_daemon[0]

    @pyqtProperty(str, notify=liveChanged)
    def transport(self):
        """bolt | unifying | bluetooth | usb | unknown."""
        if self._link_daemon and self._link_daemon[1] != "unknown":
            return self._link_daemon[1]
        c = (self._connection or "").lower()
        for key in ("bolt", "unifying", "bluetooth", "usb"):
            if key in c:
                return key
        return "unknown"

    @pyqtProperty(bool, notify=liveChanged)
    def hostsKnown(self):
        """False while the mouse has not reported its Easy-Switch slots."""
        return self._hosts_known

    @pyqtProperty(str, notify=liveChanged)
    def activeProfile(self):
        """The app whose profile is applied now ("" = global settings)."""
        return self._active_profile

    def _set_active_profile(self, app):
        self._active_profile = app
        self.liveChanged.emit()

    # ---- getting started (Dashboard checklist) ----
    def _on_menu_opened(self):
        if not self.get("app.onboarding.ring", False):
            self.setLocal("app.onboarding.ring", True)

    @pyqtSlot(result="QVariant")
    def onboarding(self):
        """The first-run checklist: [] once dismissed."""
        if self.get("app.onboarding_done", False):
            return []
        remapped = any(self.get(f"buttons.{k}", d) != d for (k, _n, d) in BUTTON_SLOTS
                       if k != "horizontal_scroll")
        return [{"id": "ring", "done": bool(self.get("app.onboarding.ring", False))},
                {"id": "button", "done": remapped},
                {"id": "skin", "done": bool(self.get("radial.wheel", ""))}]

    @pyqtSlot()
    def finishOnboarding(self):
        self.setLocal("app.onboarding_done", True)

    @pyqtSlot(result="QVariant")
    def healthIssues(self):
        """What needs a fix, with the fix: [{id, text}] (empty = healthy)."""
        out = []
        if not self.daemon.available:
            return [{"id": "daemon", "text": _("The background service is not running.")}]
        if not self._overlay_running():
            out.append({"id": "overlay", "text": _("The radial menu is not running.")})
        dv, av = version_tuple(self.daemonVersion), version_tuple(self.appVersion)
        if dv and av and dv != av:
            out.append({"id": "version", "text": _("The service is {daemon} and this app is {app}: reinstall so they match.")
                        .format(daemon=self.daemonVersion, app=self.appVersion)})
        if self._primed and self.linkState == "offline" and not self.isGeneric:
            out.append({"id": "access", "text": _("The service cannot reach the mouse. Check that your user is in the input group.")})
        auto = self.autostartStatus()
        if not auto.get("ok", True):
            out.append({"id": "autostart", "text": auto["text"]})
        return out

    def _set_link_live(self, state, transport):
        self._link_daemon = (state, transport)
        self.liveChanged.emit()
        if state == "connected":
            self._refresh_caps()

    def _refresh_caps(self):
        def _done(r):
            self._caps_daemon = dict(r[0]) if r and isinstance(r[0], dict) else None
            self.liveChanged.emit()
        self.daemon.call_then("GetCapabilities", _done)

    def _prime(self):
        """Read every live readout without blocking the UI thread.

        One call in flight at a time: the daemon runs HID++ requests serially,
        so parallel calls would only queue behind a slow one and time out.
        Cheap getters (no device I/O) go first so badges fill in at once.
        """
        d = self.daemon
        self._prime_gen += 1
        gen = self._prime_gen
        self._local_edits = set()
        if not d.available:
            self._device_name = ""
            self._device_mode = ""
            self._daemon_version = ""
            self._connection = ""
            self._caps_daemon = None
            self._link_daemon = None
            self.liveChanged.emit()
            self._set_primed()
            return

        def first(r, default=None):
            return r[0] if r else default

        def name(r):
            self._device_name = str(first(r, "") or "")
            # Dev override for device art and callout work on hardware you
            # do not own (JUH_DEVICE_NAME="MX Master 3S" on an MX Master 4).
            self._device_name = os.environ.get("JUH_DEVICE_NAME") or self._device_name

        def mode(r):
            self._device_mode = str(first(r, "") or "")
            self._connection = self._detect_connection(self._device_mode == "generic")

        def battery(r):
            if r and len(r) >= 2:
                self._battery, self._charging = _to_int(r[0]), bool(r[1])

        def dpi(r):
            v = first(r)
            if v and "dpi" not in self._local_edits:
                self._dpi = _to_int(v, self._dpi)

        def easy_switch(r):
            if r and len(r) >= 2:
                nh = _to_int(r[0])
                if nh > 0:  # receiver-connected mice report 0; keep 3 slots
                    self._num_hosts, self._cur_host = nh, _to_int(r[1])
                    self._hosts_known = True

        def host_names(r):
            v = first(r)
            if v:
                self._host_names = [str(x) for x in v]

        def link(r):
            self._link_daemon = (str(r[0]), str(r[1])) if r and len(r) >= 2 else None

        def caps(r):
            self._caps_daemon = dict(r[0]) if r and isinstance(r[0], dict) else None

        def flag(attr):
            def _set(r):
                setattr(self, attr, bool(first(r, False)))
            return _set

        steps = [
            ("GetDeviceName", name),
            ("GetUnitId", lambda r: setattr(self, "_unit_id", str(first(r, "") or ""))),
            ("GetDeviceMode", mode),
            ("DaemonVersion", lambda v: setattr(self, "_daemon_version", str(v or ""))),
            ("GetDeviceConnection", link),
            ("GetCapabilities", caps),
            ("GetBatteryStatus", battery),
            ("GetDpi", dpi),
            ("GetSmartShift",
             lambda r: None if "wheel" in self._local_edits else self._apply_smartshift(r)),
            ("SmartShiftSupported", flag("_ss_supported")),
            ("ThumbwheelSupported", flag("_tw_supported")),
            ("DpiSupported", flag("_dpi_supported")),
            ("GetEasySwitchInfo", easy_switch),
            ("GetHostNames", host_names),
        ]

        def run(i):
            if gen != self._prime_gen:
                return  # a newer round started (daemon restart)
            if i == len(steps):
                self._set_primed()
                return
            method, handler = steps[i]

            def done(result):
                if gen != self._prime_gen:
                    return
                try:
                    handler(result)
                except Exception as e:
                    print(f"prime {method} failed: {e}", file=sys.stderr)
                self.liveChanged.emit()
                run(i + 1)
            if method == "DaemonVersion":
                d.prop_then(method, done)
            else:
                d.call_then(method, done)
        run(0)
        QTimer.singleShot(self.PRIME_TIMEOUT_MS, self._set_primed)

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
                     "-u", "critical", _("Mouse battery low"),
                     _("{device} is at {percent}%. Time to recharge.").format(
                         device=self.deviceName, percent=pct)])
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
        self._local_edits.add("dpi")
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
        self._local_edits.add("wheel")
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
            self.toast.emit(_("Pointer acceleration needs GNOME gsettings"))
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
            self.toast.emit(_("Keyboard not reachable: press a key to wake it, then try again"))

    @pyqtSlot(str, float, float)
    def setPinPos(self, slot, nx, ny):
        """Persist a manually-placed callout pin (config.button_pins.<slot>)."""
        # "mx3.back" is the MX Master 3 photo's own pin: nested under
        # button_pins.mx3, which is where the page reads it back.
        self._set_path(["button_pins", *str(slot).split(".")], {"nx": round(nx, 4), "ny": round(ny, 4)})
        self._save()
        self.toast.emit(_("Pin saved: {slot} = {x}, {y}").format(slot=slot, x=f"{nx:.3f}", y=f"{ny:.3f}"))

    # ---- quick links (each submenu slice's own links, up to four) ----
    def _submenu_row(self):
        rows = self._submenu_rows()
        return rows[0] if rows else -1

    def _submenu_rows(self):
        return [i for i, sl in enumerate(self._slices.slices()) if sl.get("type") == "submenu"]

    @pyqtSlot(result="QVariant")
    def submenuRows(self):
        """Every slice that opens a submenu: [{row, label}] (the Quick links
        card edits each of them, not only the first)."""
        slices = self._slices.slices()
        return [{"row": i, "label": slices[i].get("label") or _("Slice {n}").format(n=i + 1)}
                for i in self._submenu_rows()]

    @pyqtSlot(result="QVariant")
    def aiLinks(self):
        return self.linksFor(self._submenu_row())

    @pyqtSlot(int, result="QVariant")
    def linksFor(self, row):
        """Rows for the quick-links editor of slice `row`: {name, url, icon, command}.

        Read from the slice's `submenu` list, which is what the overlay draws
        (0.4.3, `submenu_from_config`). A config that only has the older
        Qt-side radial_menu.ai_links key is shown from that once (first
        submenu slice) and moves into the slice on the next save. No links at
        all shows the AI defaults, exactly like an empty list on the wheel.
        """
        slices = self._slices.slices()
        items = slices[row].get("submenu") if 0 <= row < len(slices) else None
        if not items and row == self._submenu_row():
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

    @staticmethod
    def _clean_url(url):
        """A usable link, or "" (a bare "https://" used to be saved and drawn)."""
        from urllib.parse import urlparse
        url = str(url or "").strip()
        if not url:
            return ""
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        return url if parsed.scheme and parsed.netloc else ""

    @pyqtSlot("QVariant")
    def setAiLinks(self, links):
        self.setLinksFor(self._submenu_row(), links)

    @pyqtSlot(int, "QVariant")
    def setLinksFor(self, row, links):
        """Persist the quick links into submenu slice `row` (the overlay reads
        at most four). Link rows carry {name, url}; application rows carry
        {name, command, icon} and launch like an exec slice. Rows without a
        name or without a real address are dropped."""
        items = []
        for l in (links or []):
            if not isinstance(l, dict):
                continue
            name = str(l.get("name", "") or "").strip()
            command = str(l.get("command", "") or "").strip()
            url = self._clean_url(l.get("url", ""))
            if not name:
                continue
            if command:
                items.append({"label": name, "type": "exec", "command": command,
                              "icon": str(l.get("icon", "") or "")})
            elif url:
                items.append({"label": name, "url": url})
            if len(items) == 4:
                break
        if row not in self._submenu_rows():
            self.toast.emit(_("Give a slice a submenu first"))
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
            self.toast.emit(_("Profiles save failed: {error}").format(error=e))

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
            self.toast.emit(_("Added profile: {app}").format(app=app))

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
        old = (data.get("hardware") or {}).get(app) or {}
        for key in ("buttons", "custom"):  # edited on the Buttons tab
            if old.get(key):
                entry[key] = old[key]
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

    # ---- macros (the daemon stores them: ~/.config/juhradial/macros) ----
    def _macros(self):
        raw = self.daemon.call1("ListMacros", default="[]") or "[]"
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return sorted((m for m in data if isinstance(m, dict)),
                      key=lambda m: (str(m.get("name") or m.get("id") or "")).lower())

    @pyqtSlot(result="QVariant")
    def listMacros(self):
        return self._macros()

    def _find_macro(self, mid):
        return next((m for m in self._macros() if m.get("id") == mid), None)

    def _store_macro(self, m):
        """Save one macro and rebuild the trigger map; True when the daemon
        took it (a failed save used to pass silently)."""
        ok = self.daemon.call("SaveMacro", json.dumps(m)) is not None
        if not ok:
            self.notify(_("The macro could not be saved. Is the JuhRadial MX service running?"), "danger")
        self.daemon.call("ReloadMacroTriggers")
        self.macrosChanged.emit()
        return ok

    @pyqtSlot("QVariant", result="QVariant")
    def macroSummary(self, m):
        """{steps, ms}: steps as the editor shows them (a key press is one
        step), ms how long one run takes."""
        m = m if isinstance(m, dict) else {}
        acts = m.get("actions") or []
        fixed = bool(m.get("use_standard_delay", True))
        std = int(m.get("standard_delay_ms", 50) or 0)
        ms = sum(std if fixed else int(a.get("ms", 0))
                 for a in acts if isinstance(a, dict) and a.get("type") == "delay")
        return {"steps": len(macro_rows(acts)), "ms": ms}

    # recording: record, review the draft, then save or discard
    @pyqtSlot(result=bool)
    def startMacroRecording(self):
        if not self.daemon.available:
            self.notify(_("Start the JuhRadial MX service to record a macro."), "danger")
            return False
        if self.daemon.call("StartMacroRecording") is None:
            self.notify(_("No keyboard to record from. Your user needs to read /dev/input "
                          "(the input group)."), "danger")
            return False
        self._recording = True
        self._draft = []
        self.macrosChanged.emit()
        return True

    @pyqtSlot()
    def requestRecordingStatus(self):
        """Async: recordingStatusReady({recording, devices, count, recent})."""
        def done(args):
            if not args or len(args) < 3:
                return
            try:
                events = json.loads(args[2])
            except (TypeError, ValueError):
                events = []
            recent = [{"key": str(e.get("key", "")),
                       "down": e.get("event_type") in ("key_down", "mouse_down"),
                       "mouse": str(e.get("event_type", "")).startswith("mouse")}
                      for e in events[-8:] if isinstance(e, dict)]
            self.recordingStatusReady.emit({"recording": bool(args[0]),
                                            "devices": [str(d) for d in (args[1] or [])],
                                            "count": len(events), "recent": recent})
        self.daemon.call_then("GetRecordingStatus", done)

    @pyqtSlot(result="QVariant")
    def stopMacroRecording(self):
        """Stop and keep the capture as a draft to review; nothing is saved
        yet. Returns {steps, ms, rows} or {} when nothing was captured."""
        self._recording = False
        r = self.daemon.call("StopMacroRecording")
        self.macrosChanged.emit()
        try:
            data = json.loads(r[0]) if r else {}
        except (TypeError, ValueError):
            data = {}
        self._draft = list(data.get("actions") or [])
        if not self._draft:
            self.notify(_("Nothing was recorded. Press some keys while it records."), "info")
            return {}
        out = self.macroSummary({"actions": self._draft, "use_standard_delay": False})
        out["rows"] = macro_rows(self._draft)
        return out

    @pyqtSlot(str, result=bool)
    def saveDraft(self, name):
        if not self._draft:
            return False
        name = (name or "").strip() or _("New macro")
        m = new_macro(macro_id_for(name, {x.get("id") for x in self._macros()}), name, self._draft)
        if not self._store_macro(m):
            return False
        self._draft = []
        return True

    @pyqtSlot()
    def discardDraft(self):
        self._draft = []

    _recording = False
    _draft = []

    @pyqtProperty(bool, notify=macrosChanged)
    def recording(self):
        return self._recording

    # playback
    _macro_running = False

    @pyqtProperty(bool, notify=macroRunningChanged)
    def macroRunning(self):
        return self._macro_running

    def _set_macro_running(self, on):
        if on != self._macro_running:
            self._macro_running = on
            self.macroRunningChanged.emit()
        if on:
            # The daemon announces a start, not the end of a finished run.
            QTimer.singleShot(500, lambda: self.daemon.call_then(
                "IsMacroRunning", lambda a: self._set_macro_running(bool(a and a[0]))))

    @pyqtSlot(str)
    def runMacro(self, mid):
        if self.daemon.call("ExecuteMacro", mid) is not None:
            self._set_macro_running(True)

    @pyqtSlot()
    def stopMacro(self):
        self.daemon.call("StopMacro")
        self._set_macro_running(False)

    @pyqtSlot(str, "QVariant", bool, int)
    def testMacro(self, mid, rows, fixed, gap):
        """Play the editor's unsaved steps once."""
        m = new_macro(mid or "test", "test", macro_actions(rows))
        m["use_standard_delay"], m["standard_delay_ms"] = bool(fixed), max(0, int(gap))
        if self.daemon.call("ExecuteMacroInline", json.dumps(m)) is not None:
            self._set_macro_running(True)

    # library
    @pyqtSlot(str, result=str)
    def deleteMacro(self, mid):
        """Delete; returns the macro as JSON for Undo (restoreMacro)."""
        m = self._find_macro(mid)
        self.daemon.call("DeleteMacro", mid)
        self.daemon.call("ReloadMacroTriggers")  # drop the deleted macro's binding
        self.macrosChanged.emit()
        return json.dumps(m) if m else ""

    @pyqtSlot(str, result=bool)
    def restoreMacro(self, macro_json):
        try:
            m = json.loads(macro_json or "")
        except ValueError:
            return False
        return isinstance(m, dict) and bool(m.get("id")) and self._store_macro(m)

    @pyqtSlot(str, result=bool)
    def saveMacro(self, macro_json):
        """Persist a full macro (JSON string) and rebuild the trigger map."""
        try:
            m = json.loads(macro_json)
        except ValueError:
            return False
        return isinstance(m, dict) and self._store_macro(m)

    @pyqtSlot(str, str, str, result=bool)
    def setMacroMeta(self, mid, field, value):
        """Edit one top-level field (name/description) of a stored macro."""
        m = self._find_macro(mid)
        if not m or field not in ("name", "description"):
            return False
        m[field] = value
        return self._store_macro(m)

    @pyqtSlot(str, str, result=bool)
    def setMacroTrigger(self, mid, trigger):
        """Bind/clear a macro's trigger ('mouse:N', or '' to unbind). One
        button runs one macro: another macro on the same button is unbound."""
        macros = self._macros()
        m = next((x for x in macros if x.get("id") == mid), None)
        if not m:
            return False
        for other in macros:
            if trigger and other is not m and other.get("assigned_trigger") == trigger:
                other["assigned_trigger"] = None
                self.daemon.call("SaveMacro", json.dumps(other))
                self.notify(_("{name} is no longer bound to that button").format(
                    name=other.get("name") or other.get("id")), "info")
        m["assigned_trigger"] = trigger or None
        return self._store_macro(m)

    @pyqtSlot(str, result="QVariant")
    def getMacro(self, mid):
        """Full stored macro (id/name/actions/repeat_mode/...) or {} if absent."""
        return self._find_macro(mid) or {}

    @pyqtSlot(str, result="QVariant")
    def macroEditorRows(self, mid):
        m = self._find_macro(mid) or {}
        return macro_rows(m.get("actions") or [])

    @pyqtSlot(str, "QVariant", result=bool)
    def saveMacroRows(self, mid, rows):
        """Replace a macro's steps from the editor rows."""
        m = self._find_macro(mid)
        if not m:
            return False
        m["actions"] = macro_actions([dict(r) for r in (rows or []) if isinstance(r, dict)])
        return self._store_macro(m)

    @pyqtSlot(str, "QVariant", result=bool)
    def saveMacroSteps(self, mid, actions):
        """Replace a macro's ordered action list and resave (step editor)."""
        m = self._find_macro(mid)
        if not m:
            return False
        m["actions"] = [dict(a) for a in (actions or []) if isinstance(a, dict)]
        return self._store_macro(m)

    @pyqtSlot(str, str, int, result=bool)
    def setMacroRepeat(self, mid, mode, count):
        """Set repeat mode (once/while_holding/toggle/repeat_n) + count."""
        m = self._find_macro(mid)
        if not m:
            return False
        valid = {"once", "while_holding", "toggle", "repeat_n", "sequence"}
        m["repeat_mode"] = mode if mode in valid else "once"
        m["repeat_count"] = max(1, min(999, int(count)))
        return self._store_macro(m)

    @pyqtSlot(str, bool, int, result=bool)
    def setMacroTiming(self, mid, fixed, gap):
        """As recorded (fixed=False) or a fixed gap between steps."""
        m = self._find_macro(mid)
        if not m:
            return False
        m["use_standard_delay"] = bool(fixed)
        m["standard_delay_ms"] = max(0, min(10000, int(gap)))
        return self._store_macro(m)

    @pyqtSlot(str, result=str)
    def duplicateMacro(self, mid):
        """Clone a stored macro under a fresh id (trigger intentionally
        dropped); returns the new id ("" on failure)."""
        m = self._find_macro(mid)
        if not m:
            return ""
        clone = dict(m)
        clone["name"] = _("{name} copy").format(name=m.get("name") or _("Macro"))
        clone["id"] = macro_id_for(clone["name"], {x.get("id") for x in self._macros()})
        clone["assigned_trigger"] = None  # one button, one macro
        return clone["id"] if self._store_macro(clone) else ""

    @pyqtSlot(result="QVariant")
    def macroRepeatModes(self):
        return [{"id": "once", "name": _("Once"), "desc": _("Plays the steps one time.")},
                {"id": "repeat_n", "name": _("A number of times"), "desc": _("Plays the steps again and again, as often as you set.")},
                {"id": "while_holding", "name": _("While held"), "desc": _("Repeats while you hold the bound button.")},
                {"id": "toggle", "name": _("On / off"), "desc": _("The bound button starts it, the next press stops it.")}]

    @pyqtSlot(result="QVariant")
    def macroTriggerOptions(self):
        return [{"value": "", "name": _("No button")},
                {"value": "mouse:8", "name": _("Back button")},
                {"value": "mouse:9", "name": _("Forward button")},
                {"value": "mouse:2", "name": _("Wheel click")},
                {"value": "mouse:10", "name": _("Extra side button")}]

    @pyqtSlot(str, result=str)
    def triggerForSlot(self, slot):
        return next((t for t, s in MACRO_TRIGGER_SLOTS.items() if s == slot), "")

    @pyqtSlot(result="QVariant")
    def macroActions(self):
        """Saved macros as ring slice actions ("Run macro")."""
        return [{"id": MACRO_PREFIX + m["id"], "name": _("Macro: {name}").format(name=m.get("name") or m["id"]),
                 "label": m.get("name") or m["id"], "icon": "media-playback-start-symbolic",
                 "type": "macro", "command": m["id"], "color": "", "hex": ""}
                for m in self._macros() if m.get("id")]

    # import / export / templates
    @pyqtSlot(str, str, result=bool)
    def exportMacro(self, mid, url):
        m = self._find_macro(mid)
        path = self._local_path(url)
        if not m or not path:
            return False
        try:
            export = dict(m)
            export["assigned_trigger"] = None  # a button is this machine's choice
            pathlib.Path(path).write_text(json.dumps(export, indent=2))
        except OSError as e:
            self.notify(_("Export failed: {error}").format(error=e), "danger")
            return False
        self.notify(_("Macro exported"), "success")
        return True

    @pyqtSlot(str, result=bool)
    def importMacro(self, url):
        path = self._local_path(url)
        try:
            m = json.loads(pathlib.Path(path).read_text()) if path else None
        except (OSError, ValueError):
            m = None
        if not isinstance(m, dict) or not isinstance(m.get("actions"), list):
            self.notify(_("That file is not a JuhRadial MX macro."), "danger")
            return False
        name = str(m.get("name") or _("Imported macro"))
        clean = new_macro(macro_id_for(name, {x.get("id") for x in self._macros()}), name,
                          macro_actions(macro_rows(m["actions"])))
        for key in ("description", "repeat_mode", "repeat_count", "use_standard_delay", "standard_delay_ms"):
            if key in m:
                clean[key] = m[key]
        return self._store_macro(clean)

    @pyqtSlot(result="QVariant")
    def macroTemplates(self):
        return [{"id": t, "name": _(n), "desc": _(d)} for (t, n, d, _r) in MACRO_TEMPLATES]

    @pyqtSlot(str, result=str)
    def createMacroFromTemplate(self, tid):
        t = next((x for x in MACRO_TEMPLATES if x[0] == tid), None)
        if not t:
            return ""
        name = _(t[1])
        m = new_macro(macro_id_for(name, {x.get("id") for x in self._macros()}), name, macro_actions(t[3]))
        m["description"] = _(t[2])
        return m["id"] if self._store_macro(m) else ""

    # ---- restore defaults ----
    @pyqtSlot(result=bool)
    def restoreDefaults(self):
        """Reset config.json (macros and app profiles are kept). The previous
        file is copied to config.json.before-reset first, so Undo works."""
        try:
            if CONFIG.exists():
                shutil.copy2(CONFIG, CONFIG.with_name("config.json.before-reset"))
        except OSError as e:
            self.notify(_("Could not back up the settings, nothing was reset: {error}").format(error=e), "danger")
            return False
        self._cfg = copy.deepcopy(DEFAULT_CONFIG)
        self._save()
        self._after_config_replaced()
        return True

    @pyqtSlot(result=bool)
    def undoRestoreDefaults(self):
        return self._restore_file(CONFIG.with_name("config.json.before-reset"), CONFIG)

    def _restore_file(self, src, dst):
        try:
            if not src.exists():
                return False
            shutil.copy2(src, dst)
        except OSError as e:
            self.notify(_("Undo failed: {error}").format(error=e), "danger")
            return False
        self._load()
        self._after_config_replaced()
        return True

    def _after_config_replaced(self):
        self._slices.load(self.get("radial_menu.slices") or [])
        self.reloadConfig()
        self.configChanged.emit()
        self.macrosChanged.emit()
        self.configReloaded.emit()

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
        icon = self.get("radial.icon_scale")
        try:
            icon = max(ICON_SCALE_MIN, min(ICON_SCALE_MAX, float(icon)))
        except (TypeError, ValueError):
            icon = 1.0
        return {"outer": int(outer or RING_OUTER_DEFAULT),
                "inner": int(inner or RING_INNER_DEFAULT),
                "icon": icon, "iconMin": ICON_SCALE_MIN, "iconMax": ICON_SCALE_MAX,
                "auto": resolve_auto_fit(self.get("radial") or {}),
                "custom": outer is not None or inner is not None or self.get("radial.icon_scale") is not None,
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
        self._set_path(["radial", "icon_scale"], None)
        self._save()
        self.configChanged.emit()

    @pyqtSlot(float)
    def setIconScale(self, value):
        """Slice icon size, a multiplier on top of the ring size (owner ask)."""
        value = round(max(ICON_SCALE_MIN, min(ICON_SCALE_MAX, float(value))), 2)
        self._set_path(["radial", "icon_scale"], value)
        self._save()
        self.configChanged.emit()

    @pyqtSlot(bool)
    def setAutoFit(self, on):
        """Automatic: the ring, centre zone and icons fit the monitor. The
        manual values stay in the file for when it is turned off again."""
        self._set_path(["radial", "auto_fit"], bool(on))
        self._save()
        self.configChanged.emit()

    @pyqtSlot(int, result=float)
    def screenRingScale(self, screen_height):
        """The factor the overlay applies on a screen this tall
        (overlay_constants.compute_ring_scale)."""
        if screen_height <= 0:
            return 1.0
        return max(RING_SCALE_MIN, min(RING_SCALE_MAX, screen_height / RING_SCALE_REFERENCE_HEIGHT))

    @pyqtSlot()
    def showMenuPreview(self):
        """Open the real ring (the only faithful preview) where the pointer
        is; the daemon's ShowMenu takes the menu centre."""
        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        self.daemon.call_async("ShowMenu", pos.x(), pos.y())

    @pyqtProperty(bool, constant=True)
    def isKde(self):
        return "kde" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

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
                    # Not in the Qt icon theme: hicolor, pixmaps and Flatpak
                    # exports hold most application icons (XDG fallback).
                    found = _xdg_icon_file(name)
                    if found:
                        dest = dest_dir / (safe_id + os.path.splitext(found)[1])
                        shutil.copyfile(found, dest)
                        return str(dest)
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
            self.toast.emit(_("Autostart: {error}").format(error=e))

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
            self.notify(_("Backup saved as {name}").format(name=os.path.basename(path)), "success")
        else:
            self.notify(_("Export failed: {error}").format(error=msg), "danger")
        return ok

    @pyqtSlot(str, result="QVariant")
    def inspectBackup(self, url):
        """What a backup holds, read before anything is replaced."""
        import zipfile
        path = self._local_path(url)
        info = {"ok": False, "error": "", "created": "", "version": "",
                "config": False, "profiles": False, "macros": 0, "icons": 0, "themes": 0}
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "manifest.json" in names:
                    m = json.loads(z.read("manifest.json").decode("utf-8"))
                    info["created"] = str(m.get("created", m.get("created_at", "")))
                    info["version"] = str(m.get("version", m.get("app_version", "")))
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            info["error"] = str(e)
            return info
        info["config"] = "config.json" in names
        info["profiles"] = "profiles.json" in names
        for key, prefix in (("macros", "macros/"), ("icons", "icons/"), ("themes", "themes/")):
            info[key] = sum(1 for n in names if n.startswith(prefix) and not n.endswith("/"))
        info["ok"] = info["config"] or info["profiles"]
        if not info["ok"]:
            info["error"] = _("This is not a JuhRadial MX backup.")
        return info

    @pyqtSlot(result=bool)
    def undoImport(self):
        """Put back the config.json and profiles.json the import replaced
        (the daemon keeps them as .bak); macros and icons stay imported."""
        done = self._restore_file(CONFIG.with_name("config.json.bak"), CONFIG)
        prof_bak = PROFILES.with_name("profiles.json.bak")
        if prof_bak.exists():
            try:
                shutil.copy2(prof_bak, PROFILES)
                done = True
            except OSError:
                pass
        return done

    @pyqtSlot(str, result=bool)
    def importBackup(self, url):
        path = self._local_path(url)
        ok, msg = self._run_backup("--import", path)
        if not ok:
            self.notify(_("Import failed: {error}").format(error=msg), "danger")
            return False
        # The daemon has already reloaded its config and macro triggers; now
        # pick the new files up in this process and rebuild the visible page.
        self._load()
        self._slices.load(self.get("radial_menu.slices") or [])
        self.reloadConfig()
        self.configChanged.emit()
        self.macrosChanged.emit()
        self.configReloaded.emit()
        self.notify(_("Settings imported. The previous files are kept as .bak"), "success")
        return True

    # ---- desktop-environment defaults ----
    def _de_changes(self, de_key):
        """(key, [(label, old command, new command)]) for Apply desktop defaults."""
        if de_key in ("", "auto"):
            de_key = detect_desktop_key()
        cmds = self._de_commands(de_key)
        changes = []
        for s in self._slices.slices():
            aid = s.get("action_id", "")
            if aid in cmds and (s.get("type"), s.get("command", "")) != cmds[aid]:
                new = cmds[aid][1] or _("built-in emoji picker")
                changes.append((s.get("label", aid), s.get("command", ""), new))
        return de_key, changes

    @pyqtSlot(str, result="QVariant")
    def deDefaultsPreview(self, de_key):
        key, changes = self._de_changes(de_key)
        name = dict(DESKTOP_ENVS).get(key, key)
        return {"desktop": name, "changes": [{"label": l, "old": o, "to": n} for (l, o, n) in changes]}

    @staticmethod
    def _de_commands(de_key):
        return {
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

    @pyqtSlot(str)
    def applyDeDefaults(self, de_key):
        de_key, changes = self._de_changes(de_key)
        if not changes:
            self.notify(_("Already matches your desktop"), "info")
            return
        cmds = self._de_commands(de_key)
        slices = self._slices.slices()
        for s in slices:
            aid = s.get("action_id", "")
            if aid in cmds:
                s["type"], s["command"] = cmds[aid]
        self._slices.load(slices)
        self._set_path(["radial_menu", "slices"], slices)
        self._save()
        self.reloadConfig()
        self.notify(_("Applied desktop defaults to {count} actions").format(count=len(changes)), "success")

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
        """Every button action with its picker group. `hidden` ones only name
        old config values."""
        groups = dict(BUTTON_GROUPS)
        return [{"id": i, "name": _(n), "icon": ic, "group": g, "groupName": _(groups[g]),
                 "hidden": i in HIDDEN_BUTTON_ACTIONS}
                for (i, n, ic, g) in BUTTON_ACTIONS]

    @pyqtSlot(result="QVariant")
    def gestureActions(self):
        """Actions a directional drag or an extra control can run."""
        return [a for a in self.buttonActions()
                if a["id"] not in DIRECTIONAL_EXCLUDED and not a["hidden"]]

    # ---- button map, per scope ----
    #   ""       all apps: config.json buttons.<slot> / buttons.controls.<hex>
    #   "@mouse" this mouse only: the same keys under devices.<unit id>
    #   <class>  one app: profiles.json hardware.<class>.buttons / .custom
    MOUSE_SCOPE = "@mouse"

    @staticmethod
    def _button_key(slot):
        return f"buttons.controls.{slot}" if slot.lower().startswith("0x") else f"buttons.{slot}"

    def _mouse_prefix(self):
        return f"devices.{self._unit_id}." if self._unit_id else ""

    def _app_entry(self, app):
        return ((self._load_profiles().get("hardware") or {}).get(app) or {})

    def _own(self, scope, slot):
        """The scope's own action for a slot; None = it follows all apps."""
        if scope == self.MOUSE_SCOPE:
            prefix = self._mouse_prefix()
            return self.get(prefix + self._button_key(slot)) if prefix else None
        if scope:
            return (self._app_entry(scope).get("buttons") or {}).get(slot)
        return None

    @pyqtSlot(result="QVariant")
    def buttonScopes(self):
        """The mapping card's scope switcher: all apps, this mouse (when its
        unit id is known), then each app profile."""
        out = [{"id": "", "name": _("All apps")}]
        if self._unit_id:
            out.append({"id": self.MOUSE_SCOPE, "name": _("This mouse only")})
        apps = sorted((self._load_profiles().get("hardware") or {}).keys())
        return out + [{"id": a, "name": a} for a in apps]

    @pyqtSlot(str, str, str, result=str)
    def buttonAction(self, scope, slot, default):
        """A slot's action in a scope, falling back to all apps."""
        own = self._own(scope, slot)
        if own:
            return str(own)
        return str(self.get(self._button_key(slot), default))

    @pyqtSlot(str, str, result=bool)
    def hasOverride(self, scope, slot):
        return self._own(scope, slot) is not None

    def _edit_app(self, scope, fn):
        data = self._load_profiles()
        entry = data.setdefault("hardware", {}).setdefault(scope, {})
        fn(entry)
        for key in ("buttons", "custom"):
            if key in entry and not entry[key]:
                del entry[key]
        self._save_profiles(data)
        self.reloadConfig()

    def _drop_mouse_keys(self, slot):
        prefix = self._mouse_prefix()
        buttons = self.get(prefix + "buttons") if prefix else None
        if not isinstance(buttons, dict):
            return
        if slot.lower().startswith("0x"):
            (buttons.get("controls") or {}).pop(slot, None)
        else:
            buttons.pop(slot, None)
        (buttons.get("custom") or {}).pop(slot, None)
        self.set(prefix + "buttons", buttons)

    @pyqtSlot(str, str, str)
    def setButtonIn(self, scope, slot, action_id):
        if scope == self.MOUSE_SCOPE:
            if self._mouse_prefix():
                self.set(self._mouse_prefix() + self._button_key(slot), action_id)
            return
        if not scope:
            self.set(self._button_key(slot), action_id)
            return
        self._edit_app(scope, lambda e: e.setdefault("buttons", {}).__setitem__(slot, action_id))

    @pyqtSlot(str, str)
    def restoreButton(self, scope, slot):
        """A scoped button follows all apps again; a global one goes back to
        its default and forgets its custom action."""
        if scope == self.MOUSE_SCOPE:
            self._drop_mouse_keys(slot)
            return
        if scope:
            def drop(e):
                (e.get("buttons") or {}).pop(slot, None)
                (e.get("custom") or {}).pop(slot, None)
            self._edit_app(scope, drop)
            return
        default = next((d for (k, _n, d) in BUTTON_SLOTS if k == slot), "none")
        custom = self.get("buttons.custom") or {}
        if slot in custom:
            del custom[slot]
            self.setLocal("buttons.custom", custom)
        self.set(self._button_key(slot), default)

    @pyqtSlot(str, result=str)
    def resetButtonMap(self, scope):
        """Reset the mapping card; returns what Undo puts back (JSON)."""
        if scope == self.MOUSE_SCOPE:
            prefix = self._mouse_prefix()
            snap = {"buttons": copy.deepcopy(self.get(prefix + "buttons") or {})} if prefix else {}
            if prefix:
                self.set(prefix + "buttons", {})
            return json.dumps(snap)
        if scope:
            entry = self._app_entry(scope)
            snap = {"buttons": entry.get("buttons") or {}, "custom": entry.get("custom") or {}}
            self._edit_app(scope, lambda e: (e.pop("buttons", None), e.pop("custom", None)))
            return json.dumps(snap)
        snap = {"buttons": copy.deepcopy(self.get("buttons") or {}),
                "thumbwheel_mode": self.get("thumbwheel.mode", "off")}
        for (slot, _n, default) in BUTTON_SLOTS:
            if slot != "horizontal_scroll":
                self.setLocal(f"buttons.{slot}", default)
        # Extra controls are not on this card: keep their custom actions.
        self.setLocal("buttons.custom", {k: v for k, v in (self.get("buttons.custom") or {}).items()
                                         if k.lower().startswith("0x")})
        self.setLocal("thumbwheel.mode", "off")
        self.reloadConfig()
        return json.dumps(snap)

    @pyqtSlot(str, str)
    def undoResetButtonMap(self, scope, snapshot):
        try:
            snap = json.loads(snapshot or "{}")
        except ValueError:
            return
        if scope == self.MOUSE_SCOPE:
            if self._mouse_prefix() and "buttons" in snap:
                self.set(self._mouse_prefix() + "buttons", snap["buttons"])
            return
        if scope:
            def put(e):
                e["buttons"], e["custom"] = snap.get("buttons") or {}, snap.get("custom") or {}
            self._edit_app(scope, put)
            return
        self.setLocal("buttons", snap.get("buttons") or {})
        self.setLocal("thumbwheel.mode", snap.get("thumbwheel_mode", "off"))
        self.reloadConfig()

    @staticmethod
    def _clean_custom(obj):
        """A custom action as the daemon runs it, or None when it cannot run."""
        if not isinstance(obj, dict):
            return None
        kind = str(obj.get("kind", ""))
        value = str(obj.get("value", "")).strip()
        if kind not in CUSTOM_KINDS or not value:
            return None
        if kind == "shortcut" and not SHORTCUT_RE.match(value):
            return None
        if kind == "url":
            low = value.lower()
            scheme = next((p for p in ("https://", "http://", "mailto:") if low.startswith(p)), None)
            if scheme is None or len(value) == len(scheme):
                return None
        out = {"kind": kind, "value": value}
        for extra in ("label", "icon"):
            if isinstance(obj.get(extra), str) and obj[extra]:
                out[extra] = obj[extra]
        return out

    def _custom_map(self, scope):
        if scope == self.MOUSE_SCOPE:
            return self.get(self._mouse_prefix() + "buttons.custom") if self._mouse_prefix() else None
        if scope:
            return self._app_entry(scope).get("custom")
        return self.get("buttons.custom")

    @pyqtSlot(str, str, result="QVariant")
    def customAction(self, scope, slot):
        """A slot's custom action in a scope ({} = none), falling back to all
        apps like the daemon does."""
        own = (self._custom_map(scope) or {}).get(slot) if scope else None
        return dict(own or (self.get("buttons.custom") or {}).get(slot) or {})

    @pyqtSlot(str, str, "QVariant", result=bool)
    def setCustomAction(self, scope, slot, obj):
        """Save a button's custom action and set the button to it."""
        clean = self._clean_custom(obj)
        if clean is None:
            self.notify(_("That custom action cannot run: check the shortcut, link or command."), "danger")
            return False
        if scope and scope != self.MOUSE_SCOPE:
            def put(e):
                e.setdefault("custom", {})[slot] = clean
                e.setdefault("buttons", {})[slot] = "custom"
            self._edit_app(scope, put)
            return True
        prefix = self._mouse_prefix() if scope == self.MOUSE_SCOPE else ""
        if scope == self.MOUSE_SCOPE and not prefix:
            return False
        custom = self.get(prefix + "buttons.custom") or {}
        custom[slot] = clean
        self.setLocal(prefix + "buttons.custom", custom)
        self.set(prefix + self._button_key(slot), "custom")
        return True

    @pyqtSlot()
    def requestMacroBindings(self):
        """Async: macroBindingsReady({slot: {id, name}}) for macros bound to a
        named button (the Buttons tab shows them next to its remaps)."""
        def done(args):
            try:
                macros = json.loads(args[0] if args else "[]")
            except (TypeError, ValueError):
                macros = []
            out = {}
            for m in macros if isinstance(macros, list) else []:
                slot = MACRO_TRIGGER_SLOTS.get(str((m or {}).get("assigned_trigger") or ""))
                if slot:
                    out[slot] = {"id": m.get("id", ""), "name": m.get("name") or m.get("id", "")}
            self.macroBindingsReady.emit(out)
        self.daemon.call_then("ListMacros", done)

    # ---- plugins (~/.config/juhradial/plugins/<folder>/plugin.json) ----
    def _plugins(self):
        raw = self.daemon.call1("ListPlugins", default="[]") or "[]"
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _plugin_rows(data):
        """Installed plugins for the Settings card: folder, name, version,
        description, action count and the load error, if any."""
        try:
            data = json.loads(data or "[]")
        except Exception:
            data = []
        return [{"folder": p.get("folder", ""), "name": p.get("name", ""),
                 "version": p.get("version", ""), "description": p.get("description", ""),
                 "actions": len(p.get("actions") or []), "error": p.get("error") or ""}
                for p in (data if isinstance(data, list) else []) if isinstance(p, dict)]

    @pyqtSlot()
    def requestPlugins(self):
        """Async plugin list; pluginsReady carries the rows."""
        self.daemon.call_then("ListPlugins", lambda a: self.pluginsReady.emit(
            self._plugin_rows(a[0] if a else "[]")))

    @pyqtSlot(result="QVariant")
    def pluginActions(self):
        """Every valid plugin action as an ActionPicker entry. The label shown
        in the picker carries the plugin name; `label` is the slice label."""
        out = []
        for p in self._plugins():
            for a in p.get("actions") or []:
                ref = a.get("ref", "")
                if not ref:
                    continue
                out.append({"id": PLUGIN_PREFIX + ref, "name": f"{p.get('name', '')}: {a.get('label', ref)}",
                            "label": a.get("label", ref), "icon": a.get("icon", ""),
                            "type": "plugin", "command": ref, "color": "", "hex": ""})
        return out

    @pyqtSlot(result="QVariant")
    def sliceActions(self):
        """The slice editor's picker: built-in actions, saved macros, then
        plugin actions."""
        return self.radialActions() + self.macroActions() + self.pluginActions()

    @pyqtSlot()
    def openPluginsFolder(self):
        try:
            PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["xdg-open", str(PLUGINS_DIR)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.notify(_("Could not open the plugins folder: {error}").format(error=e), "danger")

    @pyqtSlot(result="QVariant")
    def radialActions(self):
        return [{"id": a, "name": n, "icon": ic, "type": t, "command": c, "color": col,
                 "hex": SLICE_COLORS.get(col, "#9399B2")}
                for (a, n, ic, t, c, col) in RADIAL_ACTIONS]

    @pyqtSlot(result="QVariant")
    def hapticPatterns(self):
        return [{"id": p, "name": p.replace("_", " ").title()} for p in HAPTIC_PATTERNS]

    @pyqtSlot(result="QVariant")
    def ringPalettes(self):
        return [{"id": k, "name": _(n), "light": light, "base": base, "border": border,
                 "image": _radial_wheel_uri(img), "icon": icon}
                for (k, n, light, base, border, img, icon) in RING_PALETTES]

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

    # ---- language: takes effect on the next start ----
    @pyqtProperty(bool, notify=configChanged)
    def languageNeedsRestart(self):
        lang = self.get("language") or "system"
        return lang != self._start_language

    @pyqtSlot()
    def restartApp(self):
        """Start a fresh settings window, then quit this one (the new process
        waits until this one released the single-instance name)."""
        main = pathlib.Path(__file__).resolve().parents[1] / "main.py"
        try:
            subprocess.Popen(["sh", "-c", 'sleep 0.8; exec "$0" "$1"', sys.executable, str(main)],
                             start_new_session=True)
        except OSError as e:
            self.notify(_("Could not restart: {error}").format(error=e), "danger")
            return
        QCoreApplication.quit()

    # ---- update check: GitHub's latest release, at most once a day ----
    updateChanged = pyqtSignal()

    def _read_update_cache(self):
        try:
            return json.loads(UPDATE_CACHE.read_text())
        except (OSError, ValueError):
            return {}

    def _write_update_cache(self):
        try:
            UPDATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            UPDATE_CACHE.write_text(json.dumps(self._update))
        except OSError:
            pass

    @pyqtProperty(bool, notify=updateChanged)
    def updateAvailable(self):
        latest = version_tuple(self._update.get("latest"))
        return bool(latest) and latest > version_tuple(self.appVersion)

    @pyqtProperty(str, notify=updateChanged)
    def latestVersion(self):
        return str(self._update.get("latest") or "").lstrip("vV")

    @pyqtProperty(str, notify=updateChanged)
    def latestReleaseUrl(self):
        return str(self._update.get("url") or (REPO_URL + "/releases"))

    @pyqtProperty(str, notify=updateChanged)
    def updateStatus(self):
        """Plain-language line for the Settings row."""
        if self._update.get("checking"):
            return _("Checking…")
        if self._update.get("error"):
            return _("Could not reach GitHub. Trying again tomorrow.")
        if self.updateAvailable:
            return _("Version {version} is available.").format(version=self.latestVersion)
        if self._update.get("checked"):
            return _("You have the latest version.")
        return _("Not checked yet.")

    @pyqtSlot(bool)
    def checkForUpdates(self, force):
        """Ask GitHub for the latest release. Only this one request is made,
        only when app.check_updates is on (or Check now was pressed), and at
        most once a day; nothing about this machine is sent."""
        if not force and not self.get("app.check_updates", True):
            return
        if not force and time.time() - float(self._update.get("checked") or 0) < UPDATE_INTERVAL_S:
            return
        try:
            from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
        except ImportError:
            return
        if self._net is None:
            self._net = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(RELEASES_API))
        req.setRawHeader(b"User-Agent", b"JuhRadialMX-settings")
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setTransferTimeout(10000)
        self._update["checking"] = True
        self.updateChanged.emit()
        reply = self._net.get(req)
        reply.finished.connect(lambda: self._on_update_reply(reply))

    def _on_update_reply(self, reply):
        try:
            self._update.pop("checking", None)
            self._update["checked"] = time.time()
            from PyQt6.QtNetwork import QNetworkReply
            err = reply.error()
            if err != QNetworkReply.NetworkError.NoError:
                # 404 = no release published yet: not an error for the user.
                self._update["error"] = err != QNetworkReply.NetworkError.ContentNotFoundError
            else:
                data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
                self._update["latest"] = str(data.get("tag_name") or "")
                self._update["url"] = str(data.get("html_url") or "")
                self._update["error"] = False
            self._write_update_cache()
        except Exception as e:
            print(f"update check failed: {e}", file=sys.stderr)
            self._update["error"] = True
        finally:
            reply.deleteLater()
            self.updateChanged.emit()

    # ---- troubleshooting ----
    @pyqtSlot(result="QVariant")
    def serviceStatus(self):
        return {"daemon": self.daemon.available, "overlay": self._overlay_running(),
                "app": self.appVersion, "daemonVersion": self.daemonVersion,
                "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "") or "unknown",
                "session": os.environ.get("XDG_SESSION_TYPE", "") or "unknown"}

    def _system_info(self):
        st = self.serviceStatus()
        caps = ", ".join(sorted(k for k, v in self.caps.items() if v)) or "unknown"
        return "\n".join([
            f"JuhRadial MX {st['app']} (daemon {st['daemonVersion']})",
            f"Desktop: {st['desktop']} ({st['session']})",
            f"Daemon running: {'yes' if st['daemon'] else 'no'}, overlay running: {'yes' if st['overlay'] else 'no'}",
            f"Device: {self.deviceName} ({self.deviceMode}), unit {self._unit_id or '-'}",
            f"Link: {self.linkState} via {self.transport}",
            f"Capabilities: {caps}",
            f"OS: {self._os_name()}",
        ])

    @staticmethod
    def _os_name():
        try:
            for line in pathlib.Path("/etc/os-release").read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip('"')
        except OSError:
            pass
        return sys.platform

    @pyqtSlot()
    def copySystemInfo(self):
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._system_info())
        self.notify(_("System information copied"), "success")

    @pyqtSlot()
    def reportBug(self):
        from urllib.parse import quote
        body = "**What happened**\n\n\n**Steps**\n\n\n**System**\n```\n" + self._system_info() + "\n```\n"
        QDesktopServicesOpen(REPO_URL + "/issues/new?labels=bug&body=" + quote(body))

    @pyqtSlot()
    def openLog(self):
        """One text file with the daemon journal and the overlay log."""
        runtime = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        out = runtime / "juhradial-diagnostics.txt"
        parts = [self._system_info(), ""]
        try:
            r = subprocess.run(["journalctl", "--user", "-u", "juhradialmx-daemon", "-n", "300",
                                "--no-pager"], capture_output=True, text=True, timeout=5)
            parts += ["== daemon (journalctl) ==", r.stdout or r.stderr]
        except (OSError, subprocess.SubprocessError) as e:
            parts += ["== daemon ==", str(e)]
        overlay_log = runtime / "juhradial-overlay.log"
        try:
            parts += ["== overlay ==", overlay_log.read_text(errors="replace")[-40000:]]
        except OSError:
            parts += ["== overlay ==", "no log"]
        try:
            out.write_text("\n".join(parts))
        except OSError as e:
            self.notify(_("Could not write the log: {error}").format(error=e), "danger")
            return
        QDesktopServicesOpen(QUrl.fromLocalFile(str(out)).toString())

    @pyqtSlot()
    def restartDaemon(self):
        try:
            subprocess.Popen(["systemctl", "--user", "restart", "juhradialmx-daemon.service"],
                             start_new_session=True)
            self.notify(_("Restarting the background service…"), "info")
        except OSError as e:
            self.notify(_("Could not restart the service: {error}").format(error=e), "danger")

    @pyqtSlot()
    def restartOverlay(self):
        """Stop the running overlay (by its bus name's owner) and start it
        again through the launcher, which starts whatever is not running."""
        pid = self._overlay_pid()
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        launcher = self._find_launcher()
        try:
            subprocess.Popen(["sh", "-c", 'sleep 1; exec "$0"', launcher], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.notify(_("Restarting the radial menu…"), "info")
        except OSError as e:
            self.notify(_("Could not start the radial menu: {error}").format(error=e), "danger")

    @staticmethod
    def _overlay_pid():
        if not _HAVE_DBUS:
            return 0
        try:
            reply = QDBusConnection.sessionBus().interface().servicePid("org.kde.juhradialmx.overlay")
            return int(reply.value() or 0)
        except Exception:
            return 0

    # ---- autostart health (the #129 / #32 failures were invisible) ----
    @pyqtSlot(result="QVariant")
    def autostartStatus(self):
        on = bool(self.get("app.start_at_login", True))
        if not on:
            return {"ok": True, "text": ""}
        if not AUTOSTART.exists():
            return {"ok": False, "text": _("The login entry is missing.")}
        exec_line = next((ln for ln in AUTOSTART.read_text(encoding="utf-8").splitlines()
                          if ln.startswith("Exec=")), "")
        cmd = exec_line[len("Exec="):].strip().split()
        if not cmd or not os.path.exists(cmd[0]):
            return {"ok": False, "text": _("The login entry points at a program that is gone.")}
        return {"ok": True, "text": _("Starts at login with {path}").format(path=cmd[0])}

    @pyqtSlot()
    def repairAutostart(self):
        try:
            self._write_autostart(self._find_launcher())
            self.notify(_("Login entry repaired"), "success")
        except OSError as e:
            self.notify(_("Autostart: {error}").format(error=e), "danger")
        self.configChanged.emit()

    @pyqtProperty("QVariantMap", constant=True)
    def links(self):
        return {"docs": DOCS_URL, "repo": REPO_URL, "changelog": REPO_URL + "/blob/master/CHANGELOG.md",
                "license": REPO_URL + "/blob/master/LICENSE", "plugins": DOCS_URL + "plugins/",
                "releases": REPO_URL + "/releases"}

    @pyqtSlot(result="QVariant")
    def languages(self):
        return ([{"id": "system", "name": _("System default")}]
                + [{"id": i, "name": n} for (i, n) in LANGUAGES])

    # expose the slice model as a property for QML context binding
    @pyqtProperty(QObject, constant=True)
    def slices(self):
        return self._slices
