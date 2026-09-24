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
    QAbstractListModel, QModelIndex, Qt, QByteArray, QUrl, QProcess,
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
                              QDBusPendingReply, QDBusServiceWatcher, QDBusVariant)
    _HAVE_DBUS = True
except Exception:  # pragma: no cover - QtDBus should be present
    _HAVE_DBUS = False

_XDG_CONFIG = pathlib.Path(os.environ.get("XDG_CONFIG_HOME",
                                          str(pathlib.Path.home() / ".config")))
CONFIG_DIR = _XDG_CONFIG / "juhradial"
CONFIG = CONFIG_DIR / "config.json"
PROFILES = CONFIG_DIR / "profiles.json"
AUTOSTART = _XDG_CONFIG / "autostart" / "juhradial-mx.desktop"

# Actions Ring geometry (Settings → Radial menu): the overlay's defaults
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
CUSTOM_KINDS = ("shortcut", "command", "url", "macro", "plugin", "text", "page")
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
# (settings-qt's parent), then the /opt app dir, then a user-mode install.
RADIAL_WHEEL_DIRS = [pathlib.Path(__file__).resolve().parents[2] / "assets" / "radial-wheels",
                     pathlib.Path("/opt/juhradial-mx/assets/radial-wheels"),
                     pathlib.Path(os.environ.get("XDG_DATA_HOME") or pathlib.Path.home() / ".local/share")
                     / "juhradial-mx" / "assets" / "radial-wheels"]


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
# (id, name, description, rhythm). The rhythm sketches the pulse for the
# picker glyph: one strength (0..1) per beat, 0 = a pause.
HAPTIC_PATTERNS = [
    ("sharp_state_change", "Sharp click", "One crisp click", [1.0]),
    ("damp_state_change", "Soft click", "One soft, rounded click", [0.6]),
    ("sharp_collision", "Sharp bump", "A firm knock", [0.9, 0.3]),
    ("damp_collision", "Soft bump", "A gentle knock", [0.55, 0.2]),
    ("subtle_collision", "Subtle", "A light tap", [0.4]),
    ("whisper_collision", "Whisper", "Barely there", [0.2]),
    ("happy_alert", "Happy", "Two rising taps", [0.4, 0.8]),
    ("angry_alert", "Alert", "Three hard taps", [0.9, 0.9, 0.9]),
    ("completed", "Complete", "A tap, then a longer one", [0.5, 0.0, 0.9]),
    ("square", "Square", "An even buzz", [0.7, 0.7, 0.7, 0.7]),
    ("wave", "Wave", "Swells and fades", [0.3, 0.7, 1.0, 0.7, 0.3]),
    ("firework", "Firework", "A quick burst", [1.0, 0.6, 0.8, 0.4, 0.6]),
    ("mad", "Strong alert", "A long, rough buzz", [1.0, 0.9, 1.0, 0.9, 1.0, 0.9]),
    ("knock", "Knock", "Two knocks", [0.8, 0.0, 0.8]),
    ("jingle", "Jingle", "A little tune", [0.5, 0.8, 0.5, 0.9]),
    ("ringing", "Ringing", "A phone-like ring", [0.7, 0.7, 0.7, 0.0, 0.7, 0.7, 0.7]),
]

# Every haptic event Settings lists: (config key, name, description, group,
# default pattern). Defaults mirror daemon config.rs (tests pin them).
HAPTIC_EVENTS = [
    ("menu_appear", "Menu opens", "The radial menu appears", "menu", "damp_state_change"),
    ("slice_change", "Slice change", "The pointer moves onto another slice or submenu item", "menu", "subtle_collision"),
    ("confirm", "Action runs", "You let go on a slice and its action runs", "menu", "sharp_state_change"),
    ("invalid", "Empty slice", "You let go on a slice with nothing on it", "menu", "angry_alert"),
    ("gesture_tick", "Gesture threshold", "A drag with the gesture button turns into a direction",
     "mouse", "sharp_collision"),
    ("dpi_change", "DPI change", "A DPI button changes the pointer speed", "mouse", "sharp_state_change"),
    ("host_arrive", "Mouse returns", "The mouse comes back from another computer", "mouse", "happy_alert"),
    ("low_battery", "Low battery", "The battery drops to the alert level set on Devices", "mouse", "angry_alert"),
    ("macro_start", "Macro starts", "A macro begins to play", "mouse", "damp_collision"),
    ("macro_finish", "Macro finishes", "A macro is done", "mouse", "completed"),
    ("window_switch", "App switch", "Alt+Tab, the taskbar, or clicking into another app",
     "desktop", "subtle_collision"),
    ("monitor_switch", "Monitor switch", "The pointer crosses onto another display", "desktop",
     "subtle_collision"),
]
HAPTIC_EVENTS_OFF = {"macro_start", "macro_finish"}  # off until switched on
# Style presets: a pattern per event. Balanced is the defaults.
HAPTIC_STYLES = {
    "quiet": {"menu_appear": "whisper_collision", "slice_change": "whisper_collision",
              "confirm": "subtle_collision", "invalid": "damp_collision",
              "gesture_tick": "whisper_collision", "dpi_change": "subtle_collision",
              "host_arrive": "subtle_collision", "low_battery": "damp_collision",
              "macro_start": "whisper_collision", "macro_finish": "subtle_collision",
              "window_switch": "whisper_collision", "monitor_switch": "whisper_collision"},
    "balanced": {k: d for (k, _n, _d, _g, d) in HAPTIC_EVENTS},
    "expressive": {"menu_appear": "sharp_state_change", "slice_change": "sharp_collision",
                   "confirm": "completed", "invalid": "angry_alert",
                   "gesture_tick": "sharp_collision", "dpi_change": "knock",
                   "host_arrive": "happy_alert", "low_battery": "mad",
                   "macro_start": "damp_collision", "macro_finish": "completed",
                   "window_switch": "damp_collision", "monitor_switch": "damp_collision"},
}
# Motor strength (0x19B0, device-wide) and Sense Panel force (0x19C0, % of
# the mouse's range), as Logitech Options+ names the steps.
HAPTIC_LEVELS = [("subtle", "Subtle", 25), ("low", "Low", 50), ("medium", "Medium", 75),
                 ("high", "High", 100)]
PANEL_FORCES = [("light", "Light", 0), ("medium", "Medium", 33), ("hard", "Hard", 66),
                ("firm", "Firm", 100)]
# Slice tick rate: the least time between two slice pulses (slice_debounce_ms).
SLICE_TICK_RATES = [("every", "Every slice", 0), ("balanced", "Balanced", 20), ("calm", "Calm", 80)]
TEST_REASONS = {
    "off": "Haptic feedback is off",
    "no_motor": "This mouse has no haptic motor",
    "unreachable": "The mouse is asleep or on another computer",
    "busy": "The mouse was busy. Try again",
}

THUMBWHEEL_MODES = [("off", "Horizontal scroll (default)"), ("volume", "Volume"),
                    ("scroll", "Scroll"), ("zoom", "Zoom")]
# "scroll" is horizontal scrolling too; the daemon inverts it in hardware
# (#127) while "off" leaves the wheel untouched. Pickers offer one
# "Horizontal scroll" and store "scroll" only while Invert is on.
THUMBWHEEL_PICKER = ("off", "volume", "zoom")

# The mouse's DPI range until the daemon answers GetDpiRange (MX Master 4,
# hardware-read: 200..8000 in steps of 50, factory 1000).
DPI_RANGE_FALLBACK = {"min": 200, "max": 8000, "step": 50, "default": 1000}
# What the DPI cycle button steps through when pointer.dpi_presets is unset
# (daemon main.rs dpi_step) and the precision DPI (pointer.dpi_shift).
DPI_PRESETS_DEFAULT = [800, 1600, 3200]
DPI_SHIFT_DEFAULT = 400

# Desktop pointer settings the mouse cannot hold itself: acceleration, scroll
# speed and the desktop's own natural scrolling, one knob per desktop. KDE
# Plasma on Wayland keeps them per device in KWin (kcminputrc
# [Libinput][vendor][product][name], live over D-Bus); the [Mouse]
# ScrollFactor key written up to 0.4.4 is never read there.
KWIN = "org.kde.KWin"
KWIN_INPUT = "/org/kde/KWin/InputDevice"
KWIN_DEVICE = "org.kde.KWin.InputDevice"
LOGITECH_VENDOR = 1133


def _is_x11(env):
    t = env.get("XDG_SESSION_TYPE", "").lower()
    return t == "x11" or (t != "wayland" and not env.get("WAYLAND_DISPLAY") and bool(env.get("DISPLAY")))


def pointer_desktop(env=None):
    """hyprland | sway | gnome | kde (Wayland) | x11 | "" (a Wayland desktop
    whose pointer settings JuhRadial cannot reach)."""
    env = os.environ if env is None else env
    desk = env.get("XDG_CURRENT_DESKTOP", "").lower()
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if "sway" in desk or env.get("SWAYSOCK"):
        return "sway"
    if any(d in desk for d in ("gnome", "unity", "budgie", "pantheon")):
        return "gnome"
    if ("kde" in desk or "plasma" in desk) and not _is_x11(env):
        return "kde"
    return "x11" if _is_x11(env) else ""


def scroll_speed_method(env=None, which=shutil.which):
    """(method, reason): how this session applies Scroll speed, or why not."""
    env = os.environ if env is None else env
    d = pointer_desktop(env)
    if d in ("kde", "hyprland", "sway"):
        return d, ""
    if _is_x11(env):
        if which("imwheel"):
            return "imwheel", ""
        return "", _("Install imwheel to change the scroll speed")
    if d == "gnome":
        return "", _("GNOME on Wayland has no scroll speed setting")
    return "", _("Your desktop has no scroll speed setting JuhRadial can change")


def accel_method(env=None, which=shutil.which):
    """(method, reason): how this session switches pointer acceleration."""
    env = os.environ if env is None else env
    d = pointer_desktop(env)
    if d == "gnome":
        return ("gsettings", "") if which("gsettings") else ("", _("Needs gsettings"))
    if d in ("kde", "hyprland", "sway"):
        return d, ""
    if d == "x11":
        return ("xinput", "") if which("xinput") else ("", _("Install xinput to change pointer acceleration"))
    return "", _("Your desktop has no acceleration setting JuhRadial can change")


def scroll_factor(speed):
    """Scroll speed 1..10 -> desktop scroll factor 0.5x .. 2x (1.0x at 4)."""
    return 0.5 + (max(1, min(10, int(speed))) - 1) * 0.167


def speed_for_factor(factor):
    """The Scroll speed step (1..10) nearest a desktop scroll factor."""
    return max(1, min(10, int(round((float(factor) - 0.5) / 0.167)) + 1))


def scroll_lines(method, speed):
    """Lines one wheel notch scrolls at this speed (most apps: 3 at 1.0x).
    imwheel repeats the whole notch instead of scaling it."""
    speed = max(1, min(10, int(speed)))
    n = 3 * speed if method == "imwheel" else 3 * scroll_factor(speed)
    return round(n, 1)


def xinput_ids(names_out, ids_out):
    """Pointer ids whose name looks like a Logitech mouse, from
    `xinput list --name-only` and `xinput list --id-only` (same order)."""
    names = (names_out or "").splitlines()
    ids = (ids_out or "").split()
    return [i for n, i in zip(names, ids) if "logitech" in n.lower() or n.strip().startswith("MX ")]


def xinput_prop(props_out, name):
    """Values of one property in `xinput list-props` output, or None."""
    for line in (props_out or "").splitlines():
        line = line.strip()
        if line.startswith(name + " ("):
            return [v.strip() for v in line.split(":", 1)[1].split(",")]
    return None
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


def is_newer_version(latest, current):
    """True when release `latest` supersedes `current`. A pre-release
    ('0.4.5-beta.1') sorts below its final release ('0.4.5'), as in SemVer."""
    lt, ct = version_tuple(latest), version_tuple(current)
    if not lt:
        return False
    if lt != ct:
        return lt > ct
    return "-" in str(current).strip() and "-" not in str(latest).strip()


def resolve_auto_fit(radial):
    """Same rule as overlay_actions.resolve_auto_fit: unset = on unless the
    user already chose a ring or icon size."""
    auto = radial.get("auto_fit") if isinstance(radial, dict) else None
    if isinstance(auto, bool):
        return auto
    radial = radial if isinstance(radial, dict) else {}
    return all(radial.get(k) is None for k in ("outer_radius", "inner_radius", "icon_scale"))


def focus_sees_xwayland_only(env=None):
    """True where the daemon's window tracker falls back to xprop on Wayland
    (every desktop but KDE Plasma and Hyprland, window_tracker.rs), which sees
    focus moving between XWayland windows only."""
    env = env if env is not None else os.environ
    wayland = env.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    desk = env.get("XDG_CURRENT_DESKTOP", "").upper()
    return wayland and not any(k in desk for k in ("KDE", "PLASMA", "HYPRLAND"))


def monitor_sees_xwayland_only(env=None):
    """True where the monitor-switch poll has no live pointer on Wayland (not
    KDE Plasma's KWin script, Hyprland IPC or the GNOME Shell helper)."""
    env = env if env is not None else os.environ
    desk = env.get("XDG_CURRENT_DESKTOP", "").upper()
    return focus_sees_xwayland_only(env) and "GNOME" not in desk


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
    "keypad": "MX Keypad",
    "dashboard": "Dashboard", "buttons": "Buttons", "scroll": "Point & Scroll",
    "haptics": "Haptics", "macros": "Macros", "apps": "App profiles",
    "easyswitch": "Easy-Switch", "devices": "Devices", "gaming": "Gaming",
    "flow": "Flow", "themes": "Themes", "settings": "Settings",
}

SEARCH_INDEX = [
    # MX Keypad
    ("keypad", "Key plates", "MX Keypad", "keypad lcd keys icon label shortcut app"),
    ("keypad", "Pages", "MX Keypad", "keypad page add rename reorder delete"),
    ("keypad", "Templates", "MX Keypad", "keypad everyday media developer meetings profiles"),
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
    ("scroll", "Pointer speed (DPI)", "Pointer", "dpi pointer tracking speed sensitivity cursor presets cycle stops"),
    ("scroll", "Precision DPI", "Pointer", "precision dpi shift sniper hold slow"),
    ("scroll", "Pointer acceleration", "Pointer", "acceleration speed fast slow motion"),
    ("scroll", "Wheel mode", "Scroll wheel", "ratchet free-spin smartshift click glide"),
    ("scroll", "SmartShift threshold", "Scroll wheel", "smartshift sensitivity threshold flick auto-switch"),
    ("scroll", "Scroll force", "Scroll wheel", "ratchet torque firmness resistance click notch force"),
    ("scroll", "Natural scrolling", "Scroll wheel", "natural scrolling direction content follows reverse"),
    ("scroll", "Smooth scrolling", "Scroll wheel", "smooth high-res scrolling fine precision hires"),
    ("scroll", "Scroll speed", "Scroll wheel", "scroll speed lines notch velocity"),
    ("scroll", "Action", "Thumb wheel", "thumb wheel action mode purpose volume zoom"),
    ("scroll", "Invert direction", "Thumb wheel", "invert direction reverse scroll rotation thumb wheel"),
    ("scroll", "Speed", "Thumb wheel", "thumb wheel speed repeats rotation tick velocity"),
    # Haptics
    ("haptics", "Strength", "Haptic feedback", "intensity strength vibration motor haptic level subtle low medium high"),
    ("haptics", "Style", "Haptic feedback", "haptic style preset quiet balanced expressive default pattern"),
    ("haptics", "Menu opens", "Events", "haptic pattern menu appear open vibrate"),
    ("haptics", "Slice change", "Events", "haptic pattern slice change rotate select"),
    ("haptics", "Action runs", "Events", "haptic pattern confirm accept action success"),
    ("haptics", "Empty slice", "Events", "haptic pattern invalid empty error action"),
    ("haptics", "Gesture threshold", "Events", "haptic gesture directional drag tick threshold"),
    ("haptics", "DPI change", "Events", "haptic dpi change button speed"),
    ("haptics", "Mouse returns", "Events", "haptic easy-switch host return arrive computer"),
    ("haptics", "Low battery", "Events", "haptic low battery charge warning"),
    ("haptics", "Macro starts", "Events", "haptic macro start play"),
    ("haptics", "Macro finishes", "Events", "haptic macro finish done complete"),
    ("haptics", "App switch", "Events", "haptic app window switch focus alt tab"),
    ("haptics", "Monitor switch", "Events", "haptic monitor display screen switch cross"),
    ("haptics", "Press force", "Haptic Sense Panel", "sense panel force pressure press sensitivity light firm"),
    ("haptics", "Slice tick rate", "Advanced", "haptic slice tick rate debounce sweep"),
    ("haptics", "Prevent duplicate pulses", "Advanced", "haptic duplicate reentry debounce wobble"),
    ("haptics", "Quiet in games", "Advanced", "haptic mute quiet games gaming"),
    ("haptics", "Quiet in these apps", "Advanced", "haptic mute quiet apps per-app"),
    # Macros
    ("macros", "Record a macro", "Record", "record macro capture keystrokes new keyboard sequence"),
    ("macros", "Your macros", "Library", "macro list library run edit rename duplicate delete export import"),
    ("macros", "Bind to a button", "Library", "bind trigger button assign macro back forward press"),
    ("macros", "Start from a template", "Library", "template starter example duplicate line signature"),
    # App profiles
    ("apps", "App profiles", "", "per-app application profile dpi smartshift focus window class"),
    ("apps", "Add by window class", "App profiles", "add app profile window class per-app override"),
    ("apps", "Recently used", "App profiles", "recent apps add profile one click"),
    # Easy-Switch
    ("easyswitch", "Easy-Switch in the radial menu", "Computers", "easy-switch radial menu slices host-switch submenu"),
    ("easyswitch", "This computer's name", "Computers", "easy-switch host name alias this computer"),
    ("easyswitch", "Mouse and keyboard move together", "Computers", "easy-switch keyboard follows mouse mx keys together mouse follows keyboard"),
    ("easyswitch", "Computers", "Easy-Switch", "switch host computer change device channel os icon paired"),
    # Devices
    ("devices", "Connected devices", "", "devices paired connected list hardware mouse keyboard battery asleep"),
    ("devices", "MX Keys S support", "Keyboard", "keyboard mx keys battery backlight enable beta"),
    ("devices", "Backlight", "Keyboard", "keyboard backlight automatic manual light sensor brightness"),
    ("devices", "Stay on for", "Keyboard", "keyboard backlight timeout duration stay on fade"),
    ("devices", "Warn me at", "Battery alerts", "battery low alert notification warning percent threshold"),
    ("devices", "About this mouse", "", "unit id firmware version features capabilities model diagnostics bug report"),
    ("devices", "Settings only for this mouse", "About this mouse", "per-device override unit reset this mouse only"),
    ("devices", "Force generic mode", "Advanced", "generic mode standard hid override detection logitech"),
    ("devices", "Radial menu button", "Advanced", "generic trigger button side extra forward back middle"),
    # Gaming
    ("gaming", "Gaming mode", "Gaming mode", "gaming mode enable game performance"),
    ("gaming", "When Feral GameMode runs a game", "Turn on automatically", "gamemode feral automatic auto game"),
    ("gaming", "When these apps are in front", "Turn on automatically", "automatic apps games focus"),
    ("gaming", "Show the radial menu", "In games", "overlay radial menu ring game fullscreen suppress show hide"),
    ("gaming", "Ring button", "In games", "ring button actions precision dpi cycle preset"),
    ("gaming", "Scroll wheel", "In games", "wheel lock ratchet free-spin games"),
    ("gaming", "Pulse on preset change", "In games", "haptic pulse dpi preset stage"),
    ("gaming", "Game macros", "In games", "macros games"),
    # Flow
    ("flow", "Flow", "", "flow cross computer cursor mac companion juhflow kvm"),
    ("flow", "Computers", "Flow", "flow computers approve pair trust connected mac forget"),
    ("flow", "Where is the other computer", "Flow", "arrange side edge direction left right top bottom screen"),
    ("flow", "Screen", "Flow", "monitor display screen handoff edge"),
    ("flow", "This computer's channel", "Flow", "easy-switch channel host mouse follows cursor"),
    ("flow", "Move the cursor across the edge", "Behaviour", "cursor edge trigger switch handoff pointer"),
    ("flow", "How firmly to push", "Behaviour", "edge sensitivity dwell threshold push"),
    ("flow", "Share clipboard", "Behaviour", "clipboard share copy paste sync text"),
    ("flow", "Show the edge glow", "Behaviour", "indicator glow edge hide"),
    ("flow", "Use the whole edge", "Behaviour", "extend edge zone full length"),
    ("flow", "Hold Ctrl to cross", "Behaviour", "ctrl modifier hold key accident switch edge"),
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
    # onto the mouse at every wake), radial.icon_style (readers default to mono2).
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


def _u32(v):
    """A D-Bus uint32 (`u`); see _u8."""
    return QDBusArgument(max(0, min(4294967295, int(v))), QMetaType.Type.UInt.value)


def _js(value):
    """A JS array or object reaches a "QVariant" slot as a QJSValue (Qt 6,
    PyQt 6.11): its plain Python list or dict. Anything else is unchanged."""
    return value.toVariant() if hasattr(value, "toVariant") else value


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
    keyboardBacklightChanged = pyqtSignal(int, int, int)
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
        # The keyboard's backlight keys changed its level.
        self._bus.connect("", OBJ_PATH, IFACE, "KeyboardBacklightChanged", self._on_kb_backlight)
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
    def _on_kb_backlight(self, msg):
        a = msg.arguments()
        if len(a) >= 3:
            self.keyboardBacklightChanged.emit(_to_int(a[0]), _to_int(a[1]), _to_int(a[2]))

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


class AppSliceModel(SliceModel):
    """One app's own radial menu (profiles.json hardware.<app>.slices); the
    overlay shows it while that app's profile is active."""

    app = ""

    def _persist(self):
        if not self.app:
            return
        data = self._backend._load_profiles()
        hw = data.setdefault("hardware", {}).setdefault(self.app, {})
        hw["slices"] = self.slices()
        self._backend._save_profiles(data)
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
    hwErrorsChanged = pyqtSignal()
    desktopPointerChanged = pyqtSignal()
    hapticDeviceChanged = pyqtSignal()
    hapticTested = pyqtSignal(str, bool, str)   # pattern, played, reason

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
        self._app_slices = AppSliceModel(self)

        # live hardware state
        self._battery = 0
        self._charging = False
        self._dpi = int(self.get("pointer.dpi", 1600))
        self._cur_host = 0
        self._num_hosts = 3
        self._hosts_known = False
        self._ratchet = True
        self._ratchet_seen = False
        self._wheel_mode = ""
        self._dpi_range = dict(DPI_RANGE_FALLBACK)
        self._scroll_force = {"supported": False, "value": 0, "default": 75}
        # Hardware writes the mouse refused or deferred: {key: {text, error}}.
        self._hw_errors = {}
        # Desktop pointer state read back (1 on, 0 off, -1 unknown).
        self._desk = {"accel": -1, "natural": -1, "speed": -1}
        self._procs = set()
        # What the mouse reports about its motor and Sense Panel (async).
        self._hap_dev = {"levelSupported": False, "levelPct": 0, "forceSupported": False,
                         "tracking": True}
        self._last_preview = 0.0
        self._host_names = []
        self._host_slots = []
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

        # The daemon owns gaming mode (a button, the tray or automatic mode
        # can switch it); primed from GetGamingStatus, then GamingModeChanged.
        self._gaming_mode = False
        self._gaming = {"auto": False, "stage": 0, "dpi": 0, "gamemodeInstalled": False,
                        "gamemodeActive": False}
        self._low_batt_notified = False
        self._kb_low_notified = False
        self._firmware = []
        self._refreshed_at = 0.0
        self._repair_autostart_if_stale()

        self.daemon.batteryChanged.connect(self._set_battery)
        self.daemon.deviceNameRefreshed.connect(self._set_device_name_live)
        self.daemon.dpiChanged.connect(self._set_dpi_live)
        self.daemon.hostChanged.connect(self._set_host_live)
        self.daemon.ratchetChanged.connect(self._set_ratchet_live)
        self.daemon.gamingModeChanged.connect(self._set_gaming_live)
        self._pending_app = ""
        self._recent_apps = []
        self.daemon.newAppSeen.connect(self._on_new_app)
        self._kb_info = None
        self._kb_last_battery = 0
        self.daemon.keyboardBatteryChanged.connect(self._on_keyboard_battery)
        self.daemon.keyboardBacklightChanged.connect(self._on_keyboard_backlight)
        self.daemon.linkChanged.connect(self._set_link_live)
        self.daemon.macroPlayback.connect(self._set_macro_running)
        self._active_profile = ""
        self.daemon.activeProfileChanged.connect(self._set_active_profile)
        self.daemon.menuRequested.connect(self._on_menu_opened)
        self.daemon.buttonPressed.connect(
            lambda cid: self.buttonPressed.emit(self.SLOT_CIDS.get(cid, "0x%04X" % cid)))
        self.daemon.availabilityChanged.connect(self._on_daemon_availability)
        self._init_keypad()

        # prime device state shortly after start (daemon may be warming up)
        QTimer.singleShot(150, self._prime)
        # daily update check, off the startup path
        QTimer.singleShot(4000, lambda: self.checkForUpdates(False))
        if self._load_failed:
            # deferred so the QML shell exists before the toast fires
            QTimer.singleShot(800, lambda: self.toast.emit(
                _("Config was corrupt; using defaults (backup: config.json.bad)")))

    # ---- MX Keypad ----
    keypadChanged = pyqtSignal()
    keypadKeyPressed = pyqtSignal(int, int)

    def _init_keypad(self):
        self._keypad_status = {"connected": False, "name": "", "active_page": 0, "page_count": 0}
        self._keypad_revision = 0
        self._keypad_edit_serial = 0
        self._keypad_query_pending = False
        if _HAVE_DBUS:
            self.daemon._bus.connect("", OBJ_PATH, IFACE, "KeypadKeyPressed", self._keypad_pressed)
            self.daemon._bus.connect("", OBJ_PATH, IFACE, "KeypadStatusChanged", self._keypad_connection)
        self.configChanged.connect(self.keypadChanged.emit)
        self.daemon.availabilityChanged.connect(self.refreshKeypadStatus)
        self._keypad_timer = QTimer(self)
        self._keypad_timer.setInterval(2500)
        self._keypad_timer.timeout.connect(self.refreshKeypadStatus)
        self._keypad_timer.start()
        QTimer.singleShot(0, self.refreshKeypadStatus)

    @pyqtProperty("QVariant", notify=keypadChanged)
    def keypadStatus(self):
        return dict(self._keypad_status)

    @pyqtProperty("QVariant", notify=keypadChanged)
    def keypadPages(self):
        return copy.deepcopy(self.get("keypad.pages", []))

    @pyqtProperty(bool, notify=keypadChanged)
    def keypadVisible(self):
        return self._keypad_status["connected"] or bool(self.get("keypad.pages", []))

    @pyqtProperty(int, notify=keypadChanged)
    def keypadRevision(self):
        return self._keypad_revision

    @pyqtSlot()
    def refreshKeypadStatus(self):
        if self._keypad_query_pending:
            return
        self._keypad_query_pending = True
        serial = self._keypad_edit_serial
        def done(args):
            self._keypad_query_pending = False
            if serial != self._keypad_edit_serial:
                return
            status = {"connected": False, "name": "", "active_page": int(self.get("keypad.active_page", 0)),
                      "page_count": len(self.keypadPages)}
            if args and len(args) >= 4:
                status.update(connected=bool(args[0]), name=str(args[1]),
                              active_page=_to_int(args[2]), page_count=_to_int(args[3]))
                page = status["active_page"]
                if (status["page_count"] == len(self.keypadPages) and 0 <= page < len(self.keypadPages)
                        and page != self.get("keypad.active_page", 0)):
                    self.setLocal("keypad.active_page", page)
            if status != self._keypad_status:
                self._keypad_status = status
                self.keypadChanged.emit()
        self.daemon.call_then("GetKeypadStatus", done)

    @pyqtSlot(QDBusMessage)
    def _keypad_pressed(self, message):
        args = message.arguments()
        if len(args) >= 2:
            self.keypadKeyPressed.emit(_to_int(args[0]), _to_int(args[1]))
            self.refreshKeypadStatus()

    @pyqtSlot(QDBusMessage)
    def _keypad_connection(self, message):
        args = message.arguments()
        if args:
            self._keypad_status["connected"] = bool(args[0])
            self.keypadChanged.emit()
        self.refreshKeypadStatus()

    @pyqtSlot(int)
    def setKeypadPage(self, page):
        if not 0 <= page < len(self.keypadPages):
            return
        self._keypad_edit_serial += 1
        self.setLocal("keypad.active_page", page)
        self._keypad_status["active_page"] = page
        self.keypadChanged.emit()
        def done(args):
            if args is None and self.daemon.available:
                self.notify(_("Could not switch the keypad page"), "danger")
            self.refreshKeypadStatus()
        self.daemon.call_then("SetKeypadPage", done, _u8(page))

    @pyqtSlot(int, int, result=str)
    def keypadPlate(self, page, key):
        path = CONFIG_DIR / "keypad" / "plates" / f"p{page}-k{key}.jpg"
        return path.as_uri() + f"?v={self._keypad_revision}" if path.is_file() else ""

    @pyqtSlot(int, int, result="QVariant")
    def keypadKey(self, page, key):
        pages = self.keypadPages
        if 0 <= page < len(pages) and 1 <= key <= 9:
            return pages[page]["keys"][key - 1]
        from bridge.keypad import empty_key
        return empty_key()

    def _save_keypad(self, pages, active=None):
        from bridge.keypad import render_plate
        if len(pages) > 255 or any(len(p.get("keys", [])) != 9 for p in pages):
            return False
        active = int(self.get("keypad.active_page", 0)) if active is None else active
        active = max(0, min(active, len(pages) - 1))
        dest = CONFIG_DIR / "keypad" / "plates"
        try:
            dest.mkdir(parents=True, exist_ok=True)
            # Complete every render before replacing the plates currently in use.
            with tempfile.TemporaryDirectory(dir=dest) as staging:
                for p, page in enumerate(pages):
                    for k, key in enumerate(page["keys"], 1):
                        render_plate(key, pathlib.Path(staging) / f"p{p}-k{k}.jpg", self.cacheAppIcon)
                        for n, state in enumerate(key.get("states") or [], 1):
                            render_plate(state, pathlib.Path(staging) / f"p{p}-k{k}-s{n}.jpg", self.cacheAppIcon)
                fresh = {f.name for f in pathlib.Path(staging).iterdir()}
                for plate in pathlib.Path(staging).iterdir():
                    os.replace(plate, dest / plate.name)
            # Frames of a key that is no longer animated (or gone), and the plate
            # of a state a key no longer has, must go.
            for old in [*dest.glob("*.anim"), *dest.glob("*-a[0-9][0-9][0-9].jpg"), *dest.glob("*-s[0-9]*.jpg")]:
                if old.name not in fresh:
                    old.unlink(missing_ok=True)
            # Merge: other keypad settings (brightness, ...) survive a page save.
            section = dict(self.get("keypad", {}) or {})
            section.update(enabled=bool(self.get("keypad.enabled", True)), active_page=active, pages=pages)
            self.setLocal("keypad", section)
            if json.loads(CONFIG.read_text()).get("keypad") != section:
                raise OSError(_("The keypad configuration was not saved"))
        except (OSError, ValueError) as error:
            self.notify(_("Could not save keypad: {error}").format(error=error), "danger")
            return False
        self._keypad_revision += 1
        self._keypad_edit_serial += 1
        self._keypad_status.update(active_page=active, page_count=len(pages))
        self.keypadChanged.emit()
        def reloaded(args):
            if args is None:
                if self.daemon.available:
                    self.notify(_("Keypad saved; the service could not reload it"), "danger")
                return
            self.daemon.call_then("RefreshKeypadPlates", refreshed)
        def refreshed(args):
            if args is None:
                self.notify(_("Keypad saved; reconnect the device to refresh its keys"), "info")
            self.refreshKeypadStatus()
        self.daemon.call_then("ReloadConfig", reloaded)
        return True

    def _clean_keypad_key(self, obj):
        """A keypad key as stored, or None when its action cannot run."""
        from bridge.keypad import art_path
        if not isinstance(obj, dict):
            return None
        action = obj.get("action", "none")
        if not isinstance(action, str) or action not in {a[0] for a in BUTTON_ACTIONS} - HIDDEN_BUTTON_ACTIONS:
            return None
        custom = self._clean_custom(obj.get("custom")) if action == "custom" else {}
        if custom is None:
            return None
        key = {"action": action, "label": str(obj.get("label", ""))[:40],
               "icon": str(obj.get("icon", "")), "custom": custom}
        plate = str(obj.get("plate", "") or "")
        if plate and pathlib.Path(plate).is_absolute() and pathlib.Path(plate).is_file():
            key["plate"] = plate
        if art_path(obj.get("art")) is not None:
            key["art"] = obj["art"]
        style = obj.get("style") if isinstance(obj.get("style"), dict) else {}
        style = {**({"background": style["background"].lower()} if isinstance(style.get("background"), str)
                    and re.fullmatch(r"#[0-9a-fA-F]{6}", style["background"]) else {}),
                 **({"hide_label": True} if style.get("hide_label") is True else {})}
        if style:
            key["style"] = style
        # A two-state key: the second state is a key of its own (no nesting).
        states = obj.get("states")
        if isinstance(states, list) and states:
            second = states[0] if isinstance(states[0], dict) else None
            second = self._clean_keypad_key({k: v for k, v in second.items() if k != "states"}) if second else None
            if second is None:
                return None
            key["states"] = [second]
        return key

    @pyqtSlot(int, int, "QVariant", result=bool)
    def saveKeypadKey(self, page, key, obj):
        if hasattr(obj, "toVariant"):
            obj = obj.toVariant()
        pages = self.keypadPages
        if not (0 <= page < len(pages) and 1 <= key <= 9 and isinstance(obj, dict)):
            return False
        clean = self._clean_keypad_key(obj)
        if clean is None:
            if obj.get("action") == "custom":
                self.notify(_("Check the custom action before saving this key"), "danger")
            return False
        pages[page]["keys"][key - 1] = clean
        return self._save_keypad(pages)

    @pyqtSlot(str, result=bool)
    def addKeypadPage(self, name):
        return self.addKeypadGroupPage(name, [], "")

    @pyqtSlot(str, "QVariant", str, result=bool)
    def addKeypadGroupPage(self, name, apps, profile):
        """A new empty page that comes up with these apps ([] = all apps), in
        the group of built-in `profile` when given."""
        from bridge.keypad import empty_key
        if hasattr(apps, "toVariant"):
            apps = apps.toVariant()
        pages = self.keypadPages
        entry = {"name": name.strip()[:60] or _("New page"), "keys": [empty_key() for _ in range(9)]}
        clean = sorted({str(a).strip().lower() for a in (apps or []) if str(a).strip()})
        if clean:
            entry["apps"] = clean
            if profile:
                entry["profile"] = str(profile)
        pages.append(entry)
        return self._save_keypad(pages, len(pages) - 1)

    @pyqtSlot(str, result=bool)
    def addKeypadAppProfile(self, desktop_id):
        """Start an own profile: a page named after the app that comes up
        while it is in front."""
        cls = self.appClassFor(desktop_id)
        if not cls:
            return False
        app = next((a for a in self.listApplications() if a.get("id") == desktop_id), {})
        return self.addKeypadGroupPage(app.get("name") or cls, [cls], "")

    @pyqtSlot(str, result=str)
    def importKeypadImage(self, url):
        """Copy a picture the user chose into the config (keypad/images) so the
        key keeps it when the original moves; returns the copy's path or ""."""
        import hashlib
        src = pathlib.Path(QUrl(url).toLocalFile() if url.startswith("file:") else url)
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg") or not src.is_file():
            return ""
        try:
            data = src.read_bytes()
            dest = CONFIG_DIR / "keypad" / "images" / (hashlib.sha1(data).hexdigest()[:16] + src.suffix.lower())
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except OSError as error:
            self.notify(_("Could not copy the picture: {error}").format(error=error), "danger")
            return ""
        return str(dest)

    @pyqtSlot(int, "QVariant")
    def setKeypadPageApps(self, page, apps):
        """Show a page only while one of these apps is in front ([] = General)."""
        if hasattr(apps, "toVariant"):
            apps = apps.toVariant()
        pages = self.keypadPages
        if not 0 <= page < len(pages):
            return
        clean = sorted({str(a).strip().lower() for a in (apps or []) if str(a).strip()})
        if clean:
            pages[page]["apps"] = clean
        else:
            # A general page belongs to no built-in profile's group any more.
            pages[page].pop("apps", None)
            pages[page].pop("profile", None)
        self._save_keypad(pages)

    @pyqtSlot(int, bool)
    def setKeypadPageFolder(self, page, on):
        """A folder opens only from a "page" key; while it is up either page
        button goes back to the page it was opened from."""
        pages = self.keypadPages
        if not 0 <= page < len(pages):
            return
        if on:
            pages[page]["folder"] = True
        else:
            pages[page].pop("folder", None)
        self._save_keypad(pages)

    @pyqtSlot(int, str)
    def renameKeypadPage(self, page, name):
        pages = self.keypadPages
        if 0 <= page < len(pages) and name.strip():
            old = str(pages[page].get("name", "")).strip()
            new = name.strip()[:60]
            # "page" keys go by name: the daemon takes "next"/"previous" as
            # steps, else the FIRST page of that name (ignoring case), so only
            # keys that reach this very page follow the rename.
            first = next((i for i, p in enumerate(pages) if str(p.get("name", "")).strip().lower() == old.lower()), None)
            follows = bool(old) and old.lower() not in ("next", "previous") and first == page
            pages[page]["name"] = new
            for key in (k for pg in pages for k in pg.get("keys", []) if isinstance(k, dict) and follows):
                custom = key.get("custom") or {}
                if custom.get("kind") == "page" and str(custom.get("value", "")).strip().lower() == old.lower():
                    custom["value"] = new
                    for holder in (key, custom):
                        if holder.get("label") == old:
                            holder["label"] = new
            self._save_keypad(pages)

    @pyqtSlot(int, int)
    def moveKeypadPage(self, source, target):
        pages = self.keypadPages
        if not (0 <= source < len(pages) and 0 <= target < len(pages)):
            return
        order = list(range(len(pages)))
        order.insert(target, order.pop(source))
        active = int(self.get("keypad.active_page", 0))
        self._save_keypad([pages[i] for i in order], order.index(active) if active in order else 0)

    @pyqtSlot(int, result=str)
    def deleteKeypadPage(self, page):
        pages = self.keypadPages
        if not 0 <= page < len(pages):
            return ""
        active = int(self.get("keypad.active_page", 0))
        snapshot = json.dumps({"pages": pages, "active_page": active})
        del pages[page]
        return snapshot if self._save_keypad(pages, active - (page < active)) else ""

    @pyqtSlot(str)
    def restoreKeypadPages(self, snapshot):
        try:
            saved = json.loads(snapshot)
            self._save_keypad(saved["pages"], saved["active_page"])
        except (ValueError, KeyError, TypeError):
            self.notify(_("Could not restore the keypad page"), "danger")

    @pyqtSlot(result="QVariant")
    def keypadTemplates(self):
        return [{"id": "everyday", "name": _("Everyday"), "description": _("Apps and daily essentials")},
                {"id": "media", "name": _("Media"), "description": _("Playback, volume and microphone")},
                {"id": "developer", "name": _("Developer"), "description": _("Editor, terminal and editing shortcuts")},
                {"id": "meetings", "name": _("Meetings"), "description": _("Sound controls; choose your app's camera, share and leave shortcuts") }]

    @pyqtSlot(str, result=bool)
    def applyKeypadTemplate(self, template):
        from bridge.keypad import template_keys
        keys = template_keys(template, self.listApplications(), BUTTON_ACTIONS)
        if keys is None:
            return False
        # Store app keys the way the App picker does (name + cached icon), so
        # the custom action editor opens them on its App tab.
        for key in keys:
            if key["icon"].startswith("desktop:") and key["custom"].get("kind") == "command":
                key["custom"]["label"] = key["label"]
                key["custom"]["icon"] = self.cacheAppIcon(key["icon"][8:]) or "application-x-executable-symbolic"
        name = next(t["name"] for t in self.keypadTemplates() if t["id"] == template)
        pages = self.keypadPages
        pages.append({"name": name, "keys": keys})
        if not self._save_keypad(pages, len(pages) - 1):
            return False
        self.notify(_("Template added. Keys for missing apps stay unassigned."), "info")
        return True

    # ---- MX Keypad pack import (portable.json + ready key images) ----
    # Options+ profile names in a pack -> Linux window classes. Safari's pages
    # are browser shortcuts, so they follow every browser.
    PACK_PROFILE_APPS = {
        "vscode": ["code", "code-oss", "vscodium"], "ghostty": ["com.mitchellh.ghostty"],
        "chrome": ["google-chrome", "chromium"], "firefox": ["firefox"],
        "safari": ["firefox", "google-chrome", "chromium", "brave-browser", "vivaldi-stable", "microsoft-edge"],
        "spotify": ["spotify"], "discord": ["discord"], "slack": ["slack"], "zoom": ["zoom"], "obs": ["obs"],
    }

    def _pack_key(self, raw, image, apps):
        """One pack key as a keypad key: its ready image and label always; the
        action only where Linux has a sure equivalent (else left for the user)."""
        from bridge.keypad import empty_key
        key = empty_key()
        key["label"] = str(raw.get("label", ""))[:40]
        if image:
            key["plate"] = image
        act = raw.get("action")
        act = act if isinstance(act, dict) else {}
        kind = act.get("kind")
        if kind == "launch":
            name = str(act.get("name", "")).strip().lower()
            found = next((a for a in apps if a.get("name", "").lower() == name
                          or name.replace(" ", "") in a.get("id", "").lower()), None) if name else None
            if found:
                key.update(action="custom", custom={"kind": "command", "value": found["command"],
                                                    "label": found["name"],
                                                    "icon": self.cacheAppIcon(found["id"]) or "application-x-executable-symbolic"})
        elif kind == "keys" and "primary" not in str(act.get("combo", "")):
            names = {"return": "Return", "escape": "Escape", "tab": "Tab"}
            combo = "+".join(names.get(t, t) for t in str(act.get("combo", "")).split("+"))
            custom = self._clean_custom({"kind": "shortcut", "value": combo})
            if custom:
                key.update(action="custom", custom=custom)
        elif kind in ("type", "paste") and act.get("text"):
            custom = {"kind": "text", "value": str(act["text"]), "enter": bool(act.get("enter"))}
            if "terminal" in str(act.get("target", "")):
                custom["paste_with"] = "ctrl+shift+v"
            custom = self._clean_custom(custom)
            if custom:
                key.update(action="custom", custom=custom)
        elif kind == "spotify" and act.get("action") in ("previous", "play-pause", "next"):
            key.update(action="custom", custom={"kind": "command", "value": f"playerctl -p spotify {act['action']}"})
        return key

    def _own_pack_key(self, raw, image, apps, pack):
        """A key from a JuhRadial MX export, restored exactly (None for other
        packs). Its image stands in for a picture or an icon this computer
        does not have; an exported picture file (a GIF too) is used as is."""
        if not isinstance(raw, dict) or not isinstance(raw.get("juhradial"), dict):
            return None
        picture = pack / "pictures" / pathlib.Path(str(raw.get("picture_file") or "none")).name
        if raw.get("picture") and picture.is_file():
            image = str(picture)
        # A pack never points a key at a file on this computer: pictures come
        # from the pack's own pictures/ folder only.
        own = {k: v for k, v in raw["juhradial"].items() if k != "plate"}
        if isinstance(own.get("states"), list):
            own["states"] = [{k: v for k, v in st.items() if k != "plate"} if isinstance(st, dict) else st
                             for st in own["states"]]
        key = self._clean_keypad_key(own)
        if key is None:
            return None
        if key["custom"].get("kind") == "command" and key["custom"].get("value") not in {a.get("command") for a in apps}:
            # A shared pack must not bind a shell command to a harmless-looking
            # key: only launches of apps installed here come along.
            key.update(action="none", custom={})
        icon = key.get("icon", "")
        missing_icon = icon.startswith("/") and not pathlib.Path(icon).is_file()
        if image and (raw.get("picture") or missing_icon):
            key["plate"] = image
        return key

    @pyqtSlot(str, result=bool)
    def importKeypadPack(self, url):
        """Import a keypad pack: a folder or .zip holding portable.json and
        keys-118/<set>/<id>.jpg images. Pages keep their images and labels;
        per-app pages follow their apps. Every art set is copied; the first of
        artsy, minimal, then any other, is used."""
        import shutil
        import zipfile
        import zlib
        src = pathlib.Path(QUrl(url).toLocalFile() if url.startswith("file:") else url)
        label = src.stem if src.suffix.lower() == ".zip" else ""  # before src becomes the temp dir
        work = None
        try:
            if src.suffix.lower() == ".zip":
                work = pathlib.Path(tempfile.mkdtemp())
                with zipfile.ZipFile(src) as zf:
                    for member in zf.infolist():
                        target = (work / member.filename).resolve()
                        if not str(target).startswith(str(work.resolve())):
                            raise ValueError(_("The pack contains an unsafe path"))
                    zf.extractall(work)
                src = work
            root = src.parent if src.name == "portable.json" else src
            spec = next(iter(sorted(root.rglob("portable.json"), key=lambda p: len(p.parts))), None)
            if spec is None:
                raise ValueError(_("No portable.json in this pack"))
            data = json.loads(spec.read_text(encoding="utf-8"))
            page_list = data.get("pages") if isinstance(data, dict) else None
            if not isinstance(page_list, list):
                raise ValueError(_("The pack has no pages to add"))
            base = spec.parent.parent if spec.parent.name == "profiles" else spec.parent
            art = next(iter(base.rglob("keys-118")), None)
            sets = sorted(d.name for d in art.iterdir() if d.is_dir()) if art else []
            chosen = next((s for s in ("artsy", "minimal") if s in sets), sets[0] if sets else "")
            # Own folder per import: two packs (or two versions) never share pictures.
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or base.name))[:50]
            packs = CONFIG_DIR / "keypad" / "packs"
            packs.mkdir(parents=True, exist_ok=True)
            pack = pathlib.Path(tempfile.mkdtemp(prefix=f"{safe}-", dir=packs))
            for name in sets:
                shutil.copytree(art / name, pack / name, dirs_exist_ok=True)
            if (spec.parent / "pictures").is_dir():
                shutil.copytree(spec.parent / "pictures", pack / "pictures", dirs_exist_ok=True)
            apps = self.listApplications()
            builtin = {p["id"] for p in self._keypad_catalogue()}
            pages = self.keypadPages
            first = len(pages)
            for page in page_list:
                if not isinstance(page, dict):
                    continue
                keys = [None] * 9
                for raw in page.get("keys") if isinstance(page.get("keys"), list) else []:
                    slot = raw.get("slot") if isinstance(raw, dict) else None
                    if isinstance(slot, int) and 0 <= slot < 9:
                        # The id names a file in the pack, never a path out of it.
                        img = pack / chosen / (pathlib.Path(str(raw.get("id", ""))).name + ".jpg")
                        inside = img.resolve().is_relative_to(pack.resolve())
                        img = str(img) if chosen and inside and img.is_file() else ""
                        keys[slot] = self._own_pack_key(raw, img, apps, pack) or self._pack_key(raw, img, apps)
                from bridge.keypad import empty_key
                profiles = page.get("mac_profiles")
                profiles = profiles if isinstance(profiles, dict) else {}
                if isinstance(page.get("apps"), list):  # a JuhRadial MX export
                    classes = sorted({str(a).strip().lower() for a in page["apps"] if str(a).strip()})
                elif "general" in profiles or not profiles:
                    classes = []
                else:
                    classes = sorted({c for prof in profiles for c in self.PACK_PROFILE_APPS.get(prof, [])})
                entry = {"name": str(page.get("title") or page.get("id") or _("Page"))[:60],
                         "keys": [k or empty_key() for k in keys]}
                if page.get("folder") is True:
                    entry["folder"] = True
                if classes:
                    entry["apps"] = classes
                    # The page joins its built-in profile's group (unknown ids are dropped).
                    if isinstance(page.get("profile"), str) and page["profile"] in builtin:
                        entry["profile"] = page["profile"]
                pages.append(entry)
            if len(pages) == first or len(pages) > 255 or not self._save_keypad(pages, first):
                raise ValueError(_("The pack has no pages to add"))
        except RuntimeError:  # an encrypted zip
            self.notify(_("Could not import the pack: {error}").format(error=_("it is password protected")), "danger")
            return False
        except (OSError, ValueError, KeyError, EOFError, zlib.error, zipfile.BadZipFile) as error:
            self.notify(_("Could not import the pack: {error}").format(error=error), "danger")
            return False
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        self.notify(_("Pack imported: {n} pages. Keys without a Linux action keep their picture for you to assign.")
                    .format(n=len(pages) - first), "success")
        return True

    # ---- MX Keypad app profiles (built-in catalogue, ranked by use) ----
    def _keypad_catalogue(self):
        path = pathlib.Path(__file__).resolve().parents[1] / "assets" / "keypad" / "profiles.json"
        try:
            profiles = json.loads(path.read_text(encoding="utf-8")).get("profiles", [])
        except (OSError, ValueError, AttributeError):
            return []
        return [p for p in profiles if isinstance(p, dict) and p.get("id") and p.get("pages")]

    @staticmethod
    def _app_usage():
        try:
            data = json.loads((CONFIG_DIR / "app_usage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k).lower(): int(v) for k, v in data.items() if isinstance(v, (int, float))} if isinstance(data, dict) else {}

    @pyqtSlot(result="QVariant")
    def keypadProfiles(self):
        """Every built-in app profile: installed apps first, then by the time
        those apps spent in front (app_usage.json, written by the service)."""
        app_icons = {str(a.get("id", "")).lower(): a.get("icon", "") for a in self.listApplications()}
        installed = set(app_icons)
        usage = self._app_usage()
        pages = self.keypadPages
        out = []
        for prof in self._keypad_catalogue():
            apps = [str(a).lower() for a in prof.get("apps", [])]
            ids = {str(d).lower() for d in prof.get("desktop_ids", [])}
            used = sum(usage.get(a, 0) for a in apps)
            added = any(pg.get("profile") == prof["id"] for pg in pages) or (bool(apps) and any(
                "profile" not in pg and sorted(pg.get("apps", [])) == sorted(apps) for pg in pages))
            # A CLI's profile follows terminals: it counts as installed only
            # when the command is (terminal use alone says nothing about it).
            commands = [str(c) for c in prof.get("commands", [])]
            present = (any(self._has_command(c) for c in commands) or bool(ids & installed)) if commands \
                else (not apps or bool(ids & installed) or used > 0)
            own = next((app_icons[str(d).lower()] for d in prof.get("desktop_ids", [])
                        if app_icons.get(str(d).lower())), "")
            icon, icon_kind = self._row_icon(own, prof.get("icon", ""))
            out.append({"id": prof["id"], "name": _(prof.get("name", prof["id"])),
                        "icon": icon, "iconKind": icon_kind,
                        "description": _(prof.get("description", "")),
                        "installed": present,
                        "minutes": used // 60, "added": added,
                        "general": not apps, "requires": list(prof.get("requires", []))})
        out.sort(key=lambda p: (not p["installed"], -p["minutes"], p["name"].lower()))
        return out

    @staticmethod
    def _has_command(name):
        """Whether a command-line tool is installed (PATH, or the user-level
        folders its installers use, which a desktop session's PATH may lack)."""
        home = pathlib.Path.home()
        dirs = [home / d for d in (".local/bin", ".npm-global/bin", ".bun/bin", ".volta/bin", ".claude/local")]
        dirs += (home / ".nvm/versions/node").glob("*/bin")
        return bool(shutil.which(name)) or any((d / name).is_file() for d in dirs)

    @pyqtSlot(str, result=bool)
    def applyKeypadProfile(self, profile_id):
        """Add a built-in profile's pages; they come up while its apps are in front."""
        prof = next((p for p in self._keypad_catalogue() if p["id"] == profile_id), None)
        if prof is None:
            return False
        from bridge.keypad import art_path, empty_key
        known = {a[0] for a in BUTTON_ACTIONS} - HIDDEN_BUTTON_ACTIONS
        apps = sorted({str(a).lower() for a in prof.get("apps", [])})
        pages = self.keypadPages
        first = len(pages)
        for page in prof["pages"][:2]:
            keys = []
            for raw in (page.get("keys") or [])[:9]:
                key = empty_key()
                action = raw.get("action", "none")
                custom = self._clean_custom(raw.get("custom")) if action == "custom" else {}
                if action in known and custom is not None:
                    key.update(action=action, custom=custom or {},
                               label=_(str(raw.get("label", "")))[:40], icon=str(raw.get("icon", "")))
                    if art_path(raw.get("art")) is not None:
                        key["art"] = raw["art"]
                keys.append(key)
            keys += [empty_key() for _unused in range(9 - len(keys))]
            entry = {"name": _(str(page.get("name", prof.get("name", "")))), "keys": keys, "profile": prof["id"]}
            if apps:
                entry["apps"] = apps
            pages.append(entry)
        if len(pages) > 255 or not self._save_keypad(pages, first):
            return False
        self.notify(_("Profile added: {name}").format(name=_(prof.get("name", ""))), "success")
        return True

    @staticmethod
    def _row_icon(app_icon, fallback):
        """(icon, kind) for a profile row: the catalogue's own art or tool mark
        first, then the installed app's icon ("file" for a path, "app" for a
        theme name), then the catalogue glyph."""
        from bridge.keypad import art_path, brand_path
        art = art_path(fallback) or brand_path(fallback)
        if art is not None:
            return str(art), "file"
        if app_icon:
            return app_icon, ("file" if app_icon.startswith("/") else "app")
        return fallback or "input-keyboard-symbolic", "glyph"

    def _class_apps(self):
        """Installed apps by the window class their windows carry (cached)."""
        if getattr(self, "_class_app_cache", None) is None:
            found = {}
            for app in self.listApplications():
                found.setdefault(self.appClassFor(app.get("id", "")), app)
            self._class_app_cache = found
        return self._class_app_cache

    @pyqtSlot(result="QVariant")
    def keypadGroups(self):
        """The pages as they come up: the all-apps pages first, then one group
        per app set (a built-in profile's or the user's own), in page order."""
        pages = self.keypadPages
        # One group per built-in profile added (two can share apps, like
        # Claude Code and Codex CLI in terminals), else per app set.
        grouped = {}
        for i, page in enumerate(pages):
            apps = tuple(sorted(page.get("apps", [])))
            key = (page.get("profile", "") if apps else "", apps)
            grouped.setdefault(key, []).append(i)
        by_id = {p["id"]: p for p in self._keypad_catalogue()}
        by_apps = {tuple(sorted(str(a).lower() for a in p.get("apps", []))): p
                   for p in self._keypad_catalogue() if p.get("apps")}
        installed = self._class_apps()
        out = []
        for (profile_id, apps), indexes in sorted(grouped.items(), key=lambda kv: (bool(kv[0][1]), kv[1][0])):
            if not apps:
                out.append({"name": _("All apps"), "desc": _("Shown while no app below is in front"),
                            "icon": "input-keyboard-symbolic", "iconKind": "glyph", "apps": [], "pages": indexes,
                            "profile": ""})
                continue
            prof = by_id.get(profile_id) or (by_apps.get(apps) if not profile_id else None) or {}
            names = [installed[c]["name"] if c in installed else c for c in apps]
            app = next((installed[c] for c in apps if c in installed), {})
            icon, icon_kind = self._row_icon(app.get("icon", ""), prof.get("icon", "application-x-executable-symbolic"))
            out.append({"name": _(prof["name"]) if prof else names[0],
                        "desc": ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else ""),
                        "icon": icon, "iconKind": icon_kind, "apps": list(apps), "pages": indexes,
                        "profile": profile_id})
        return out

    @pyqtSlot(result="QVariant")
    def keypadArt(self):
        """The bundled key art for the picker: [{id "<set>/<name>", name, set, path}]."""
        from bridge.keypad import art_catalogue, art_path
        catalogue = art_catalogue()
        out = []
        for art_set in catalogue.get("sets", []):
            for art in catalogue.get("art", []):
                ref = f"{art_set.get('id')}/{art.get('id')}"
                path = art_path(ref) if art_set.get("id") in art.get("sets", []) else None
                if path is not None:
                    out.append({"id": ref, "name": _(art.get("name", "")), "set": art_set["id"], "path": str(path)})
        return out

    @pyqtSlot(result="QVariant")
    def keypadArtSets(self):
        from bridge.keypad import art_catalogue
        return [{"id": s.get("id", ""), "name": _(s.get("name", ""))} for s in art_catalogue().get("sets", [])]

    @pyqtSlot(str, result=str)
    def keypadArtPath(self, ref):
        from bridge.keypad import art_path
        path = art_path(ref)
        return str(path) if path is not None else ""

    @pyqtSlot(str, "QVariant", result=bool)
    def exportKeypadPack(self, url, indexes):
        """Save pages as a keypad pack (.zip: portable.json + key images) that
        Import pack reads back with the same actions, art, pictures and apps."""
        import zipfile
        if hasattr(indexes, "toVariant"):
            indexes = indexes.toVariant()
        dest = pathlib.Path(QUrl(url).toLocalFile() if url.startswith("file:") else url)
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        pages = self.keypadPages
        chosen = [int(i) for i in (indexes or []) if isinstance(i, (int, float)) and 0 <= int(i) < len(pages)]
        if not chosen:
            return False
        plates = CONFIG_DIR / "keypad" / "plates"
        spec = []
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                for n, index in enumerate(chosen):
                    keys = []
                    for slot, key in enumerate(pages[index]["keys"]):
                        ident = f"p{n + 1}-k{slot + 1}"
                        plate = plates / f"p{index}-k{slot + 1}.jpg"
                        if plate.is_file():
                            zf.write(plate, f"keys-118/juhradial/{ident}.jpg")
                        entry = {"slot": slot, "id": ident, "label": key.get("label", ""),
                                 "juhradial": {k: v for k, v in key.items() if k != "plate"},
                                 "picture": bool(key.get("plate"))}
                        # The picture itself travels too: a GIF keeps playing.
                        picture = pathlib.Path(key.get("plate", "") or "")
                        if key.get("plate") and picture.is_file():
                            entry["picture_file"] = f"pictures/{ident}{picture.suffix.lower()}"
                            zf.write(picture, entry["picture_file"])
                        keys.append(entry)
                    entry = {"id": f"page-{n + 1}", "title": pages[index].get("name", ""),
                             "apps": list(pages[index].get("apps", [])), "keys": keys}
                    if pages[index].get("profile"):
                        entry["profile"] = pages[index]["profile"]
                    if pages[index].get("folder"):
                        entry["folder"] = True
                    spec.append(entry)
                zf.writestr("portable.json", json.dumps({"generator": "JuhRadial MX", "version": 1, "pages": spec},
                                                        indent=1, ensure_ascii=False))
        except OSError as error:
            self.notify(_("Could not save the pack: {error}").format(error=error), "danger")
            return False
        self.notify(_("Pack saved: {path}").format(path=dest.name), "success")
        return True

    @pyqtSlot(result="QVariant")
    def keypadGlyphs(self):
        return [{"id": row[2], "name": _(row[1]), "icon": row[2]}
                for row in BUTTON_ACTIONS if row[0] not in HIDDEN_BUTTON_ACTIONS]
    # ---- End MX Keypad ----

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
        value = _js(value)
        self._set_path(path.split("."), value)
        self._save()
        self.reloadConfig()
        self.configChanged.emit()

    @pyqtSlot(str, "QVariant")
    def setLocal(self, path, value):
        """Persist a config value WITHOUT a daemon reload (UI-only keys)."""
        value = _js(value)
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
        """The daemon's name for the mouse; "" until it answers (never a guess:
        an MX Master 3S owner must not see "MX Master 4" while it is down)."""
        return self._device_name

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

    # ---- Flow: asks the ring process (org.kde.juhradialmx.overlay) ----
    def _overlay_call(self, method, *args, done=None):
        msg = QDBusMessage.createMethodCall("org.kde.juhradialmx.overlay", "/Overlay",
                                            "org.kde.juhradialmx.Overlay", method)
        msg.setArguments(list(args))
        watcher = QDBusPendingCallWatcher(QDBusConnection.sessionBus().asyncCall(msg, 3000), self)
        watchers = self.__dict__.setdefault("_overlay_watchers", set())
        watchers.add(watcher)  # alive until it answers

        def finished(w):
            watchers.discard(w)
            try:
                reply = QDBusPendingReply(w)
                args = None if reply.isError() else list(reply.reply().arguments())
                if done is not None:
                    done(None if args is None else (args[0] if args else True))
            except Exception as e:  # a slot must never raise under PyQt6
                print(f"overlay {method} failed: {e}", file=sys.stderr)
            finally:
                w.deleteLater()
        watcher.finished.connect(finished)

    @pyqtSlot()
    def sendFlowCursor(self):
        """Send the cursor to the other computer now, as if it crossed the edge."""
        self._overlay_call("SendCursor", done=lambda ok: None if ok else self.notify(
            _("The ring is not running, or Flow is off. Start JuhRadial MX and turn Flow on."), "warning"))

    @pyqtSlot(str)
    def identifyScreens(self, flow_label):
        """A card with each monitor's number and name for a few seconds."""
        self._overlay_call("IdentifyScreens", str(self.get("flow.monitor", "") or ""), flow_label,
                           done=lambda ok: None if ok else self.notify(
                               _("The ring is not running. Start JuhRadial MX to identify screens.") if ok is None
                               else _("Identify screens needs X11 windows, which the ring does not use on this desktop."),
                               "warning"))

    # ---- USB receivers (Devices tab) ----
    receiversChanged = pyqtSignal()
    RECEIVER_KINDS = {1: "keyboard", 2: "mouse", 3: "numpad", 4: "presenter", 8: "trackball", 9: "touchpad"}

    @pyqtProperty("QVariant", notify=receiversChanged)
    def receivers(self):
        """[{kind, devices: [{slot, kind, wpid, name, role}]}] from ListReceivers
        (None until the first read answers)."""
        return getattr(self, "_receivers", None)

    @pyqtSlot()
    def refreshReceivers(self):
        def done(r):
            rows = []
            for path, kind, slots in (r[0] if r else []) or []:
                devices = [{"slot": _to_int(s[0]), "kind": self.RECEIVER_KINDS.get(_to_int(s[1]), "device"),
                            "wpid": f"{_to_int(s[2]):04X}", "name": str(s[3]), "role": str(s[4])}
                           for s in slots]
                rows.append({"path": str(path), "kind": str(kind), "devices": devices})
            self._receivers = rows
            self.receiversChanged.emit()
        self.daemon.call_then("ListReceivers", done)

    # ---- App profiles "Try now" ----
    TRIAL_SECONDS = 60

    @pyqtProperty(str, notify=liveChanged)
    def trialApp(self):
        """The app whose profile is being tried right now ("" = none)."""
        return getattr(self, "_trial_app", "")

    @pyqtSlot(str)
    def tryAppProfile(self, app):
        """Act as if `app` were in front for a minute, so its buttons, ring
        and pointer settings can be tried from here."""
        def done(r):
            if not (r and bool(r[0])):
                self.notify(_("Could not try the profile. Is the JuhRadial service running?"), "danger")
                return
            self._trial_app = app
            if getattr(self, "_trial_timer", None) is None:
                self._trial_timer = QTimer(self)
                self._trial_timer.setSingleShot(True)
                self._trial_timer.timeout.connect(self._end_trial)
            self._trial_timer.start(self.TRIAL_SECONDS * 1000)
            self.liveChanged.emit()
            self.notify(_("Trying this profile for a minute: use the mouse and the ring now."), "info")
        self.daemon.call_then("TryAppProfile", done, app, _u32(self.TRIAL_SECONDS))

    @pyqtSlot()
    def stopAppProfileTrial(self):
        self.daemon.call_then("StopAppProfileTrial", lambda _r: None)
        self._end_trial()

    def _end_trial(self):
        if getattr(self, "_trial_timer", None) is not None:
            self._trial_timer.stop()
        self._trial_app = ""
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
            ("GetDpiRange", self._apply_dpi_range),
            ("GetScrollForce", self._apply_scroll_force),
            ("GetSmartShift",
             lambda r: None if "wheel" in self._local_edits else self._apply_smartshift(r)),
            ("SmartShiftSupported", flag("_ss_supported")),
            ("ThumbwheelSupported", flag("_tw_supported")),
            ("DpiSupported", flag("_dpi_supported")),
            ("GetGamingStatus", self._apply_gaming_status),
            ("GetEasySwitchInfo", easy_switch),
            ("GetHostNames", host_names),
            ("GetFirmware", lambda r: setattr(self, "_firmware", [str(x) for x in (first(r) or [])])),
        ]

        def run(i):
            if gen != self._prime_gen:
                return  # a newer round started (daemon restart)
            if i == len(steps):
                self._refreshed_at = time.time()
                self._set_primed()
                self.liveChanged.emit()
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
        # Daemon labels: discharging, charging, full, not_charging, unknown.
        # Only "charging" charges (the GetBatteryStatus bool uses the same rule).
        self._charging = status.lower() == "charging"
        self._maybe_low_battery_notify(pct)
        self.liveChanged.emit()

    def _battery_alerts(self):
        """The `battery` config the tray reads too: (alert percent, alert for
        the mouse, alert for the keyboard); absent = 15 %, both on."""
        level = _to_int(self.get("battery.alert_percent", 15), 15)
        return (max(5, min(50, level)), bool(self.get("battery.alert_mouse", True)),
                bool(self.get("battery.alert_keyboard", True)))

    def _maybe_low_battery_notify(self, pct):
        """Desktop-notify once when the mouse drops to the alert level on
        battery; re-arm above level + 5 or while charging. The overlay raises
        it itself while it runs (tray badge + notify-send)."""
        level, on, _kb = self._battery_alerts()
        if self._charging or pct > level + 5:
            self._low_batt_notified = False
            return
        if on and 0 < pct <= level and not self._low_batt_notified and not self._overlay_running():
            self._low_batt_notified = True
            self._send_low_battery(_("Mouse battery low"), self.deviceName, pct)

    def _maybe_kb_low_notify(self, pct, charging):
        level, _mouse, on = self._battery_alerts()
        if charging or pct > level + 5:
            self._kb_low_notified = False
            return
        if on and 0 < pct <= level and not self._kb_low_notified and not self._overlay_running():
            self._kb_low_notified = True
            self._send_low_battery(_("Keyboard battery low"), _("The keyboard"), pct)

    @staticmethod
    def _send_low_battery(title, device, pct):
        try:
            subprocess.Popen(
                ["notify-send", "-a", "JuhRadial MX", "-i", "battery-low-symbolic",
                 "-u", "critical", title,
                 _("{device} is at {percent}%. Time to recharge.").format(device=device, percent=pct)])
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
        # the preset, DPI and automatic flag moved with it
        self.daemon.call_then("GetGamingStatus", self._apply_gaming_status)

    def _apply_gaming_status(self, r):
        if not r or len(r) < 6:
            return
        self._gaming_mode = bool(r[0])
        self._gaming = {"auto": bool(r[1]), "stage": _to_int(r[2]), "dpi": _to_int(r[3]),
                        "gamemodeInstalled": bool(r[4]), "gamemodeActive": bool(r[5])}
        self.liveChanged.emit()

    def _set_dpi_live(self, dpi):
        self._dpi = dpi
        self.liveChanged.emit()

    def _set_host_live(self, host):
        self._cur_host = host
        self.liveChanged.emit()

    def _set_ratchet_live(self, r):
        self._ratchet = r
        self._ratchet_seen = True
        # The hardware button toggles engagement without touching the stored
        # wheel mode; re-read so wheelMode stays truthful either way.
        self._refresh_wheel_mode()
        self.liveChanged.emit()

    # ---- pointer / scroll / thumbwheel actions ----
    def _restore_local(self, path, value):
        """Put a config key back as it was (None = it was absent)."""
        parts = path.split(".")
        if value is None:
            parent = self._get_path(parts[:-1], None)
            if isinstance(parent, dict):
                parent.pop(parts[-1], None)
            self._save()
            self.configChanged.emit()
        else:
            self.setLocal(path, value)

    @pyqtProperty("QVariantMap", notify=hwErrorsChanged)
    def hwErrors(self):
        """Hardware writes the mouse refused or deferred, by setting:
        {key: {"text": message, "error": bool}}."""
        return dict(self._hw_errors)

    def _set_hw_error(self, key, text="", error=True):
        if text:
            self._hw_errors[key] = {"text": text, "error": error}
        elif key not in self._hw_errors:
            return
        else:
            self._hw_errors.pop(key)
        self.hwErrorsChanged.emit()

    def _hw_then(self, key, method, revert, *args):
        """Send a hardware setter and report its fate under `key`. The value
        stays saved while the mouse sleeps, sits on another computer or the
        service is down (the daemon replays it); a refusal from a connected
        mouse is undone with `revert()`."""
        def done(r):
            if r is not None:
                self._set_hw_error(key)
            elif not self.daemon.available:
                self._set_hw_error(key, _("Saved. JuhRadial applies it when its service starts."), False)
            elif self.linkState in ("asleep", "away", "offline"):
                self._set_hw_error(key, _("Saved. The mouse gets it when it wakes up or comes back."), False)
            else:
                revert()
                self._set_hw_error(key, _("The mouse did not accept this change."))
        self.daemon.call_then(method, done, *args)

    @pyqtProperty("QVariantMap", notify=liveChanged)
    def scrollForce(self):
        """{supported, value, default}: the wheel's ratchet force in % (0x2111)."""
        return dict(self._scroll_force)

    def _apply_scroll_force(self, r):
        if not r or len(r) < 3 or "force" in self._local_edits:
            return
        supported, value, default = bool(r[0]), _to_int(r[1]), _to_int(r[2])
        self._scroll_force = {"supported": supported, "value": value if 1 <= value <= 100 else 0,
                              "default": default if 1 <= default <= 100 else 75}

    @pyqtSlot(int)
    def setScrollForce(self, percent):
        """Save the ratchet force and send it; a connected mouse that refuses
        it gets the old value back."""
        percent = max(1, min(100, int(percent)))
        before = self.get("scroll.force", None)
        shown = self._scroll_force.get("value", 0)
        self._local_edits.add("force")
        self.setLocal("scroll.force", percent)
        self._scroll_force["value"] = percent
        self.liveChanged.emit()

        def done(r):
            if r and bool(r[0]):
                self._set_hw_error("force")
            elif not self.daemon.available:
                self._set_hw_error("force", _("Saved. JuhRadial applies it when its service starts."), False)
            elif self.linkState in ("asleep", "away", "offline"):
                self._set_hw_error("force", _("Saved. The mouse gets it when it wakes up or comes back."), False)
            else:
                self._restore_local("scroll.force", before)
                self._scroll_force["value"] = shown
                self.liveChanged.emit()
                self._set_hw_error("force", _("The mouse did not accept this change."))
        self.daemon.call_then("SetScrollForce", done, _u8(percent))

    @pyqtProperty("QVariantMap", notify=liveChanged)
    def dpiRange(self):
        """{min, max, step, default}: what the sensor accepts (GetDpiRange)."""
        return dict(self._dpi_range)

    def _apply_dpi_range(self, r):
        if not r or len(r) < 3:
            return
        lo, hi, step = _to_int(r[0]), _to_int(r[1]), _to_int(r[2])
        if lo <= 0 or hi < lo:
            return
        default = _to_int(r[3]) if len(r) >= 4 else 0
        self._dpi_range = {"min": lo, "max": hi, "step": step,
                           "default": default if lo <= default <= hi else max(lo, min(hi, 1000))}

    @pyqtSlot(int, result=int)
    def snapDpi(self, dpi):
        """The settable DPI nearest to `dpi` (the daemon snaps the same way)."""
        r = self._dpi_range
        lo, hi, step = r["min"], r["max"], r["step"]
        dpi = max(lo, min(hi, int(dpi)))
        if step <= 0:
            return dpi
        on_grid = min(hi, lo + int((dpi - lo) / step + 0.5) * step)
        return hi if hi - dpi < abs(dpi - on_grid) else on_grid

    @pyqtSlot(int)
    def setDpi(self, dpi):
        dpi = self.snapDpi(dpi)
        before, before_cfg = self._dpi, self.get("pointer.dpi", None)
        self._local_edits.add("dpi")
        self._dpi = dpi
        self.setLocal("pointer.dpi", dpi)
        self.liveChanged.emit()

        def revert():
            self._dpi = before
            self._restore_local("pointer.dpi", before_cfg)
            self.liveChanged.emit()
        self._hw_then("dpi", "SetDpi", revert, _u16(dpi))

    @pyqtSlot(result="QVariant")
    def dpiPresets(self):
        """The DPI cycle button's stops (pointer.dpi_presets), ascending."""
        raw = self.get("pointer.dpi_presets", None)
        vals = raw if isinstance(raw, list) and raw else DPI_PRESETS_DEFAULT
        return sorted({self.snapDpi(_to_int(v)) for v in vals if _to_int(v) > 0})

    @pyqtSlot("QVariant")
    def setDpiPresets(self, values):
        values = _js(values)
        vals = sorted({self.snapDpi(_to_int(v)) for v in (values or []) if _to_int(v) > 0})
        self.set("pointer.dpi_presets", vals[:6])

    @pyqtProperty(int, notify=configChanged)
    def dpiShift(self):
        """Precision DPI while a Precision DPI button is held."""
        return self.snapDpi(_to_int(self.get("pointer.dpi_shift", DPI_SHIFT_DEFAULT), DPI_SHIFT_DEFAULT))

    @pyqtSlot(int)
    def setDpiShift(self, dpi):
        self.set("pointer.dpi_shift", self.snapDpi(dpi))

    @pyqtProperty(str, notify=liveChanged)
    def scrollMode(self):
        """The wheel mode the selector shows: the hardware's once read,
        else the saved one (#108: the selector follows the mouse)."""
        return self._wheel_mode or str(self.get("scroll.mode", "smartshift"))

    @pyqtProperty(bool, notify=liveChanged)
    def wheelClicking(self):
        """Whether the wheel is clicking right now: the live RatchetChanged
        state, else what the mode implies at rest."""
        if self._ratchet_seen:
            return self._ratchet
        return self.scrollMode != "freespin"

    @pyqtSlot(str)
    def setScrollMode(self, mode):
        thr = int(self.get("scroll.smartshift_threshold", 50))
        # (True, 1..49) = SmartShift, (False, _) = permanently ratcheted
        # (autoDisengage 255), (True, 0) = free-spin.
        wire = {"smartshift": (True, self._dev_threshold(thr)),
                "ratchet": (False, 0), "freespin": (True, 0)}.get(mode)
        if wire is None:
            return
        before_cfg, before_live = self.get("scroll.mode", None), self._wheel_mode
        self.setLocal("scroll.mode", mode)
        self._wheel_mode = mode
        self._local_edits.add("wheel")
        self.liveChanged.emit()

        def revert():
            self._restore_local("scroll.mode", before_cfg)
            self._wheel_mode = before_live
            self._refresh_wheel_mode()
        self._hw_then("wheel", "SetSmartShift", revert, wire[0], _u8(wire[1]))

    @pyqtSlot(int)
    def setSmartShiftThreshold(self, ui_value):
        before = self.get("scroll.smartshift_threshold", None)
        self.setLocal("scroll.smartshift_threshold", int(ui_value))
        # Only SmartShift uses the threshold: sending it in Ratchet or
        # Free-spin would switch the wheel to SmartShift (#108).
        if self.scrollMode != "smartshift":
            return
        self._hw_then("smartshift", "SetSmartShift",
                      lambda: self._restore_local("scroll.smartshift_threshold", before),
                      True, _u8(self._dev_threshold(ui_value)))

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
        before = self.get("scroll.natural", None)
        self.setLocal("scroll.natural", bool(on))
        self._hw_then("natural", "SetHiresscrollMode",
                      lambda: self._restore_local("scroll.natural", before),
                      bool(self.get("scroll.smooth", True)), bool(on), False)

    @pyqtSlot(bool)
    def setSmoothScroll(self, on):
        before = self.get("scroll.smooth", None)
        self.setLocal("scroll.smooth", bool(on))
        self._hw_then("smooth", "SetHiresscrollMode",
                      lambda: self._restore_local("scroll.smooth", before),
                      bool(on), bool(self.get("scroll.natural", False)), False)

    # ---- desktop pointer settings (acceleration, scroll speed) ----
    def _run_then(self, cmd, callback, timeout_ms=3000):
        """Run a desktop helper without blocking the UI thread;
        `callback(stdout or None)` runs on the UI thread."""
        if shutil.which(cmd[0]) is None:
            callback(None)
            return
        proc = QProcess(self)
        self._procs.add(proc)

        def done(*_a):
            if proc not in self._procs:
                return
            self._procs.discard(proc)
            ok = (proc.exitStatus() == QProcess.ExitStatus.NormalExit and proc.exitCode() == 0)
            out = proc.readAllStandardOutput().data().decode(errors="replace") if ok else None
            proc.deleteLater()
            try:
                callback(out)
            except Exception as e:
                print(f"{cmd[0]} callback failed: {e}", file=sys.stderr)
        proc.finished.connect(done)
        proc.errorOccurred.connect(
            lambda _e: done() if proc.state() == QProcess.ProcessState.NotRunning else None)
        proc.start(cmd[0], cmd[1:])
        QTimer.singleShot(timeout_ms, lambda: proc.kill() if proc in self._procs else None)

    def _kwin_then(self, path, iface, method, args, callback):
        if not _HAVE_DBUS:
            callback(None)
            return
        msg = QDBusMessage.createMethodCall(KWIN, path, iface, method)
        if args:
            msg.setArguments(list(args))
        self.daemon._watch(QDBusConnection.sessionBus().asyncCall(msg, 2000), method, callback)

    def _kwin_prop_then(self, path, prop, callback):
        def unwrap(r):
            v = r[0] if r else None
            callback(v.variant() if hasattr(v, "variant") else v)
        self._kwin_then(path, "org.freedesktop.DBus.Properties", "Get", [KWIN_DEVICE, prop], unwrap)

    def _kwin_mice(self, callback):
        """KWin's Logitech pointer devices (object paths) -> `callback(paths)`."""
        def listed(r):
            names = [str(n) for n in (r[0] if r else [])]
            if not names:
                callback([])
                return
            found, left = [], [len(names)]
            for n in names:
                def got(v, path=f"{KWIN_INPUT}/{n}"):
                    if _to_int(v) == LOGITECH_VENDOR:
                        found.append(path)
                    left[0] -= 1
                    if left[0] == 0:
                        callback(sorted(found))
                self._kwin_prop_then(f"{KWIN_INPUT}/{n}", "vendor", got)
        self._kwin_then(KWIN_INPUT, "org.kde.KWin.InputDeviceManager", "ListPointers", [], listed)

    def _kwin_set(self, prop, value):
        """Write a KWin device property on every Logitech pointer: applies
        live and KWin saves it in kcminputrc."""
        def each(paths):
            for path in paths:
                self._kwin_then(path, "org.freedesktop.DBus.Properties", "Set",
                                [KWIN_DEVICE, prop, QDBusVariant(value)], lambda _r: None)
        self._kwin_mice(each)

    def _xinput_mice(self, callback):
        def names(out_n):
            self._run_then(["xinput", "list", "--id-only"],
                           lambda out_i: callback(xinput_ids(out_n, out_i)))
        self._run_then(["xinput", "list", "--name-only"], names)

    @pyqtProperty("QVariantMap", notify=desktopPointerChanged)
    def desktopPointer(self):
        """How this desktop takes Scroll speed and acceleration (method "" =
        it cannot, with the reason) and what it reports: accel / natural
        1 on, 0 off, -1 unknown; speed the step of its scroll factor, -1
        unknown."""
        sm, sr = scroll_speed_method()
        am, ar = accel_method()
        return {"speedMethod": sm, "speedReason": sr, "accelMethod": am, "accelReason": ar,
                "accel": self._desk["accel"], "natural": self._desk["natural"],
                "speed": self._desk["speed"]}

    def _put_desk(self, key, val):
        if key == "speed":
            v = -1 if val is None else speed_for_factor(val)
        else:
            v = -1 if val is None else (1 if val else 0)
        if self._desk.get(key) != v:
            self._desk[key] = v
            self.desktopPointerChanged.emit()

    @pyqtSlot()
    def readDesktopPointer(self):
        """Read the desktop's own acceleration and natural scrolling (async)."""
        d = pointer_desktop()
        if d == "kde":
            def each(paths):
                seen = {"pointerAccelerationProfileFlat": [], "naturalScroll": [], "scrollFactor": []}
                left = [len(paths) * len(seen)]

                def got(v, prop):
                    if v is not None:
                        seen[prop].append(v)
                    left[0] -= 1
                    if left[0] == 0:
                        flat, nat = seen["pointerAccelerationProfileFlat"], seen["naturalScroll"]
                        # the device we set last differs from 1.0 when anything does
                        factors = [float(f) for f in seen["scrollFactor"]]
                        moved = [f for f in factors if abs(f - 1.0) > 0.01]
                        self._put_desk("accel", (not any(flat)) if flat else None)
                        self._put_desk("natural", any(nat) if nat else None)
                        self._put_desk("speed", (moved or factors or [None])[0])
                for path in paths:
                    for prop in seen:
                        self._kwin_prop_then(path, prop, lambda v, prop=prop: got(v, prop))
            self._kwin_mice(each)
        elif d == "gnome":
            schema = "org.gnome.desktop.peripherals.mouse"
            self._run_then(["gsettings", "get", schema, "accel-profile"],
                           lambda o: self._put_desk("accel", None if o is None else "flat" not in o))
            self._run_then(["gsettings", "get", schema, "natural-scroll"],
                           lambda o: self._put_desk("natural", None if o is None else o.strip() == "true"))
        elif d == "hyprland":
            def opt(o, key):
                try:
                    j = json.loads(o or "")
                except ValueError:
                    return None
                return j.get(key)
            self._run_then(["hyprctl", "getoption", "input:accel_profile", "-j"],
                           lambda o: self._put_desk("accel", None if opt(o, "str") is None
                                                    else "flat" not in opt(o, "str")))
            self._run_then(["hyprctl", "getoption", "input:natural_scroll", "-j"],
                           lambda o: self._put_desk("natural", None if opt(o, "int") is None
                                                    else bool(opt(o, "int"))))
            self._run_then(["hyprctl", "getoption", "input:scroll_factor", "-j"],
                           lambda o: self._put_desk("speed", opt(o, "float")))
        elif d == "sway":
            def inputs(o):
                try:
                    ptrs = [i for i in json.loads(o or "[]") if i.get("type") == "pointer"]
                except ValueError:
                    ptrs = []
                ptrs.sort(key=lambda i: "logitech" not in i.get("name", "").lower())
                li = ptrs[0].get("libinput", {}) if ptrs else {}
                self._put_desk("accel", None if "accel_profile" not in li else li["accel_profile"] != "flat")
                self._put_desk("natural", None if "natural_scroll" not in li
                               else li["natural_scroll"] == "enabled")
            self._run_then(["swaymsg", "-t", "get_inputs"], inputs)
        elif d == "x11":
            def first(ids):
                if not ids:
                    return

                def props(o):
                    acc = xinput_prop(o, "libinput Accel Profile Enabled")
                    nat = xinput_prop(o, "libinput Natural Scrolling Enabled")
                    self._put_desk("accel", None if not acc else acc[0] == "1")
                    self._put_desk("natural", None if not nat else nat[0] == "1")
                self._run_then(["xinput", "list-props", ids[0]], props)
            self._xinput_mice(first)

    @pyqtSlot(bool)
    def setPointerAccel(self, on):
        """Pointer acceleration on (adaptive) or off (flat), in the desktop."""
        self.setLocal("pointer.acceleration", bool(on))
        method, reason = accel_method()
        profile = "adaptive" if on else "flat"
        noop = lambda _o: None  # noqa: E731
        if method == "":
            self.toast.emit(reason)
            return
        if method == "gsettings":
            self._run_then(["gsettings", "set", "org.gnome.desktop.peripherals.mouse",
                            "accel-profile", profile], noop)
        elif method == "kde":
            self._kwin_set("pointerAccelerationProfileAdaptive" if on else "pointerAccelerationProfileFlat", True)
        elif method == "hyprland":
            self._run_then(["hyprctl", "keyword", "input:accel_profile", profile], noop)
        elif method == "sway":
            self._run_then(["swaymsg", "input", "type:pointer", "accel_profile", profile], noop)
        elif method == "xinput":
            def each(ids):
                for i in ids:
                    def props(o, i=i):
                        vals = xinput_prop(o, "libinput Accel Profile Enabled")
                        if vals and len(vals) >= 2:
                            new = ["1" if on else "0", "0" if on else "1"] + ["0"] * (len(vals) - 2)
                            self._run_then(["xinput", "set-prop", i, "libinput Accel Profile Enabled", *new], noop)
                    self._run_then(["xinput", "list-props", i], props)
            self._xinput_mice(each)
        self._put_desk("accel", on)

    @pyqtSlot(int, result=str)
    def scrollLinesText(self, speed):
        """Lines per notch at this Scroll speed, as text ("2.5")."""
        return "%g" % scroll_lines(scroll_speed_method()[0], speed)

    @pyqtSlot(int)
    def setScrollSpeed(self, lines):
        """Persist + apply the wheel scroll-speed multiplier per desktop."""
        lines = max(1, min(10, int(lines)))
        self.setLocal("scroll.speed", lines)
        self._apply_scroll_speed(lines)

    def _apply_scroll_speed(self, lines):
        """Apply Scroll speed through this desktop's knob (fail-soft; never
        blocks: it fires from a slider on the UI thread)."""
        method, _reason = scroll_speed_method()
        factor = round(scroll_factor(lines), 3)
        noop = lambda _o: None  # noqa: E731
        if method in ("kde", "hyprland"):
            self._put_desk("speed", factor)
        if method == "kde":
            self._kwin_set("scrollFactor", float(factor))
        elif method == "hyprland":
            self._run_then(["hyprctl", "keyword", "input:scroll_factor", str(factor)], noop)
        elif method == "sway":
            self._run_then(["swaymsg", "input", "type:pointer", "scroll_factor", str(factor)], noop)
        elif method == "imwheel":
            def _spawn(cmd):
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                except Exception:
                    pass

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

    @pyqtProperty(str, notify=configChanged)
    def thumbwheelMode(self):
        """The picker's choice ("scroll", inverted horizontal scrolling,
        shows as the one "off" = Horizontal scroll)."""
        m = str(self.get("thumbwheel.mode", "off"))
        return "off" if m == "scroll" else m

    @staticmethod
    def _tw_store(mode, invert):
        """What thumbwheel.mode stores for a picker choice: horizontal
        scrolling is "scroll" while Invert is on, since only that mode
        inverts in hardware (#127)."""
        if mode in ("off", "scroll"):
            return "scroll" if invert else "off"
        return mode

    @pyqtSlot(str)
    def setThumbwheelMode(self, mode):
        self.setLocal("thumbwheel.mode", self._tw_store(mode, bool(self.get("thumbwheel.invert", False))))
        self.reloadConfig()  # daemon re-applies divert from config

    @pyqtSlot(bool)
    def setThumbwheelInvert(self, inv):
        self.setLocal("thumbwheel.invert", bool(inv))
        self.setLocal("thumbwheel.mode", self._tw_store(str(self.get("thumbwheel.mode", "off")), bool(inv)))
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
        return [{"id": "275", "name": _("Side button")},
                {"id": "276", "name": _("Extra side button")},
                {"id": "277", "name": _("Forward button")},
                {"id": "278", "name": _("Back button")},
                {"id": "274", "name": _("Middle click")}]

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
        return self._keyboard_info(battery, paired, keys, self.daemon.call("GetKeyboardBacklight"))

    @staticmethod
    def _backlight_info(r):
        """GetKeyboardBacklight as a dict; {"ok": False} when unreadable (support
        off, asleep, or an older daemon without the method)."""
        if not r or len(r) < 10 or not bool(r[0]):
            return {"ok": False}
        levels = max(2, _to_int(r[4], 8))
        level = _to_int(r[3])
        return {"ok": True, "enabled": bool(r[1]), "mode": _to_int(r[2]), "level": level,
                "levels": levels, "percent": round(level * 100 / (levels - 1)),
                "status": _to_int(r[5], 255), "autoSupported": bool(r[6]),
                "away": _to_int(r[7]), "near": _to_int(r[8]), "powered": _to_int(r[9])}

    def _keyboard_info(self, battery, paired, keys, backlight=None):
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
                "lastBattery": self._kb_last_battery,
                "backlight": self._backlight_info(backlight)}

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
        self._maybe_kb_low_notify(pct, bool(charging))
        self.keyboardInfoReady.emit(info)

    def _on_keyboard_backlight(self, level, levels, status):
        """KeyboardBacklightChanged: the F-row backlight keys (or the light
        sensor) changed the level; the Devices card follows without a read."""
        info = dict(self._kb_info or {})
        backlight = dict(info.get("backlight") or {})
        if not backlight.get("ok") or levels < 2:
            return  # nothing shown yet; the next full read brings it
        backlight.update(level=level, levels=levels, status=status,
                         percent=round(level * 100 / (levels - 1)))
        info.update(backlight=backlight, present=True, sleeping=False)
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
        order = ("GetKeyboardBattery", "GetKeyboardPaired", "ListKeyboardKeys", "GetKeyboardBacklight")

        def step(i):
            if i == len(order):
                self._kb_info = self._keyboard_info(
                    state["GetKeyboardBattery"], state["GetKeyboardPaired"],
                    state["ListKeyboardKeys"], state["GetKeyboardBacklight"])
                self.keyboardInfoReady.emit(self._kb_info)
                return
            name = order[i]

            def _cb(args):
                state[name] = args
                step(i + 1)
            self.daemon.call_then(name, _cb)
        step(0)

    def _kb_write_then(self, method, *args):
        """A backlight write, then a fresh read so the card shows what the
        keyboard applied. A sleeping keyboard ignores HID++ until a key press."""
        def done(r):
            if not (r and r[0]):
                self.notify(_("The keyboard did not answer. Press a key to wake it, then try again."), "warning")
            self.requestKeyboardInfo()
        self.daemon.call_then(method, done, *args)

    @pyqtSlot(int)
    def setKeyboardBacklight(self, level):
        """Set MX Keys S backlight 0..100% (Manual mode, mapped to its levels)."""
        self._kb_write_then("SetKeyboardBacklight", _u8(max(0, min(100, int(level)))))

    @pyqtSlot(bool)
    def setKeyboardBacklightAuto(self, automatic):
        """Automatic (the light sensor sets the level) or Manual."""
        self._kb_write_then("SetKeyboardBacklightMode", bool(automatic))

    @pyqtSlot(int, int)
    def setKeyboardBacklightDuration(self, seconds, powered_seconds):
        """How long the backlight stays on after the hands leave (the same for
        hands away and hands near) and on a cable; 0 keeps a value."""
        s, pw = max(0, int(seconds)), max(0, int(powered_seconds))
        self._kb_write_then("SetKeyboardBacklightDurations", _u16(s), _u16(s), _u16(pw))

    @pyqtSlot(int, result="QVariant")
    def backlightDurations(self, current=0):
        """Stay-on choices (the keyboard takes 5 s to 2 h), plus the keyboard's
        current value when it is not one of them."""
        choices = [(5, _("5 seconds")), (10, _("10 seconds")), (30, _("30 seconds")),
                   (60, _("1 minute")), (120, _("2 minutes")), (300, _("5 minutes")),
                   (600, _("10 minutes")), (1800, _("30 minutes")), (3600, _("1 hour")),
                   (7200, _("2 hours"))]
        if current > 0 and current not in dict(choices):
            label = (_("{n} seconds").format(n=current) if current < 120
                     else _("{n} minutes").format(n=round(current / 60)))
            choices = sorted(choices + [(current, label)])
        return [{"id": str(v), "name": n} for v, n in choices]

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
        submenu slice) and moves into the slice on the next save. A submenu
        without links starts empty (#118): the card says the wheel shows the
        AI defaults meanwhile (defaultQuickLinks) instead of pre-filling them.
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
        return out[:4]

    @pyqtSlot(result="QVariant")
    def defaultQuickLinks(self):
        """The AI assistant links the wheel shows under a submenu without links."""
        return [{"name": l["name"], "url": l["url"], "icon": l["icon"], "command": ""} for l in DEFAULT_AI_LINKS]

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
        links = _js(links)
        self.setLinksFor(self._submenu_row(), links)

    @pyqtSlot(int, "QVariant")
    def setLinksFor(self, row, links):
        """Persist the quick links into submenu slice `row` (the overlay reads
        at most four). Link rows carry {name, url}; application rows carry
        {name, command, icon} and launch like an exec slice. Rows without a
        name or without a real address are dropped."""
        links = _js(links)
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

    def _profile_globals(self):
        """What a profile falls back to where it overrides nothing."""
        mode = self.scrollMode
        return {"dpi": self._dpi, "smartshiftEnabled": mode == "smartshift",
                "smartshiftThreshold": _to_int(self.get("scroll.smartshift_threshold", 50), 50),
                "hires": bool(self.get("scroll.smooth", True)), "thumbwheel": self.thumbwheelMode}

    @pyqtSlot(result="QVariant")
    def appProfiles(self):
        """Every profile: which settings it overrides (the rest follow the
        global ones), their values, its own ring and buttons."""
        hw_all = (self._load_profiles().get("hardware") or {})
        g = self._profile_globals()
        out = []
        for app, h in hw_all.items():
            h = h if isinstance(h, dict) else {}
            ss = h.get("smartshift") if isinstance(h.get("smartshift"), dict) else None
            # profiles.json stores the device threshold the daemon sends to the
            # mouse; the slider speaks sensitivity % through the PR #123
            # mapping, the same one saveAppProfile writes with.
            ui_thr = (self._ui_threshold(_to_int(ss.get("threshold"), self._dev_threshold(50)))
                      if ss else g["smartshiftThreshold"])
            tw = h.get("thumbwheel")
            out.append({"app": app, "name": self._app_display_name(app), "icon": self._app_icon_name(app),
                        "overrides": {"dpi": "dpi" in h, "smartshift": ss is not None,
                                      "hires": "hires" in h, "thumbwheel": tw is not None},
                        "dpi": _to_int(h.get("dpi"), g["dpi"]) if "dpi" in h else g["dpi"],
                        "smartshiftEnabled": bool(ss.get("enabled", True)) if ss else g["smartshiftEnabled"],
                        "smartshiftThreshold": ui_thr,
                        "hires": bool(h["hires"]) if "hires" in h else g["hires"],
                        "thumbwheel": ("off" if tw == "scroll" else str(tw)) if tw is not None else g["thumbwheel"],
                        "ownRing": isinstance(h.get("slices"), list) and len(h["slices"]) == 8,
                        "buttons": len(h.get("buttons") or {})})
        out.sort(key=lambda x: x["name"].lower())
        return out

    @staticmethod
    def _app_icon_name(app):
        """The desktop entry's icon name for a window class, or ""."""
        try:
            from gi.repository import Gio
            for candidate in (app, app.lower()):
                try:
                    info = Gio.DesktopAppInfo.new(candidate + ".desktop")
                except Exception:
                    info = None
                if info is not None and isinstance(info.get_icon(), Gio.ThemedIcon):
                    names = info.get_icon().get_names() or []
                    return names[0] if names else ""
        except Exception:
            pass
        return ""

    @pyqtSlot(result="QVariant")
    def recentApps(self):
        """Apps seen in front this session without a profile (newest first),
        for one-click profiles."""
        have = set((self._load_profiles().get("hardware") or {}).keys())
        return [{"app": a, "name": self._app_display_name(a)}
                for a in self._recent_apps if a not in have][:6]

    @pyqtProperty(QObject, constant=True)
    def appSlices(self):
        """The slices of the app picked with editAppSlices()."""
        return self._app_slices

    @pyqtSlot(str, result=bool)
    def appHasOwnRing(self, app):
        hw = (self._load_profiles().get("hardware") or {}).get(app) or {}
        return isinstance(hw.get("slices"), list) and len(hw["slices"]) == 8

    @pyqtSlot(str, bool)
    def setAppOwnRing(self, app, on):
        """Give an app its own radial menu (a copy of the global one to start
        from), or send it back to the global one."""
        data = self._load_profiles()
        hw = data.setdefault("hardware", {}).setdefault(app, {})
        if on:
            hw["slices"] = copy.deepcopy(self._slices.slices())
        else:
            hw.pop("slices", None)
        self._save_profiles(data)
        self.editAppSlices(app)

    @pyqtSlot(str)
    def editAppSlices(self, app):
        hw = (self._load_profiles().get("hardware") or {}).get(app) or {}
        self._app_slices.app = app
        self._app_slices.load(hw.get("slices") if self.appHasOwnRing(app) else self._slices.slices())

    @pyqtSlot(str, result=str)
    def appProfileError(self, app):
        """Why a window class cannot be added ("" = it can)."""
        app = (app or "").strip().lower()
        if not app:
            return ""
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", app):
            return _("Letters, digits, dots, dashes and underscores only")
        if app in (self._load_profiles().get("hardware") or {}):
            return _("There is already a profile for {app}").format(app=app)
        return ""

    @pyqtSlot(str)
    def addAppProfile(self, app):
        """A new profile overrides nothing until you choose what it changes,
        so adding one never changes how the app behaves (audit 4.9 #3)."""
        app = (app or "").strip().lower()
        if not app or self.appProfileError(app):
            return
        data = self._load_profiles()
        data.setdefault("hardware", {})[app] = {}
        self._save_profiles(data)
        self.reloadConfig()
        self.toast.emit(_("Added profile: {app}").format(app=self._app_display_name(app)))

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
        cls = (app or "").strip().lower()
        if cls and cls not in self._recent_apps and self._should_suggest(cls):
            self._recent_apps.insert(0, cls)
            del self._recent_apps[12:]
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

    @pyqtSlot(str, result="QVariant")
    def removeAppProfile(self, app):
        """Delete a profile; returns it for restoreAppProfile (Undo)."""
        data = self._load_profiles()
        hw = data.get("hardware") or {}
        old = hw.pop(app, None)
        if old is not None:
            self._save_profiles(data)
            self.reloadConfig()
        return old

    @pyqtSlot(str, str)
    def copyAppProfile(self, src, dst):
        """Give `dst` the same profile as `src` (settings, buttons, ring)."""
        dst = (dst or "").strip().lower()
        data = self._load_profiles()
        hw = data.setdefault("hardware", {})
        if src in hw and dst and dst != src:
            hw[dst] = copy.deepcopy(hw[src])
            self._save_profiles(data)
            self.reloadConfig()
            self.toast.emit(_("Copied to {app}").format(app=self._app_display_name(dst)))

    @pyqtSlot(str, "QVariant")
    def restoreAppProfile(self, app, entry):
        entry = _js(entry)
        if not app or not isinstance(entry, dict):
            return
        data = self._load_profiles()
        data.setdefault("hardware", {})[app] = entry
        self._save_profiles(data)
        self.reloadConfig()

    @pyqtSlot(str, "QVariant")
    def saveAppProfile(self, app, obj):
        """Write the settings the profile overrides (obj.overrides); the rest
        are left out so they follow the global settings. Buttons, custom
        actions and the app's own ring are kept (edited elsewhere)."""
        obj = _js(obj)
        app = (app or "").strip().lower()
        if not app or not isinstance(obj, dict):
            return
        over = obj.get("overrides") or {}
        data = self._load_profiles()
        old = (data.get("hardware") or {}).get(app) or {}
        entry = {k: old[k] for k in ("buttons", "custom", "slices") if old.get(k)}
        if over.get("dpi"):
            entry["dpi"] = self.snapDpi(_to_int(obj.get("dpi", 1000), 1000))
        if over.get("smartshift"):
            entry["smartshift"] = {"enabled": bool(obj.get("smartshiftEnabled", True)),
                                   # UI sensitivity % -> device threshold 1..49,
                                   # same conversion as the global scroll slider.
                                   "threshold": self._dev_threshold(
                                       max(1, min(100, _to_int(obj.get("smartshiftThreshold", 50), 50))))}
        if over.get("hires"):
            entry["hires"] = bool(obj.get("hires", True))
        if over.get("thumbwheel"):
            entry["thumbwheel"] = self._tw_store(str(obj.get("thumbwheel", "off")),
                                                 bool(self.get("thumbwheel.invert", False)))
        data.setdefault("hardware", {})[app] = entry
        self._save_profiles(data)
        self.reloadConfig()

    # ---- haptics ----
    @pyqtSlot(str)
    def testHaptic(self, pattern):
        """Play a waveform; say why when the mouse stays silent."""
        def done(r):
            if r is None:  # no service, or it failed
                played, reason = False, "service"
            else:  # (played, reason); an older daemon answers nothing
                played = bool(r[0]) if r else True
                reason = str(r[1]) if len(r) > 1 else ""
            self.hapticTested.emit(pattern, played, reason)
            if not played:
                text = TEST_REASONS.get(reason) or _("The JuhRadial service is not running")
                self.notify(_(text), "info")
        self.daemon.call_then("TriggerHapticPattern", done, pattern)

    @pyqtSlot(str)
    def previewHaptic(self, pattern):
        """Hover preview in the pattern picker: at most one pulse per 250 ms."""
        now = time.monotonic()
        if now - self._last_preview < 0.25:
            return
        self._last_preview = now
        self.daemon.call_async("TriggerHapticPattern", pattern)

    @pyqtSlot(result="QVariant")
    def hapticEvents(self):
        """Every event with its pattern, switch and whether it can fire here."""
        tracking = self._hap_dev.get("tracking", True)
        out = []
        for (key, name, desc, group, default) in HAPTIC_EVENTS:
            if key in ("window_switch", "monitor_switch"):
                on = bool(self.get(f"haptics.{key}_enabled", True))
            else:
                on = bool(self.get(f"haptics.per_event_enabled.{key}", key not in HAPTIC_EVENTS_OFF))
            available, reason, note = True, "", ""
            if key == "window_switch" and not tracking:
                available, reason = False, _("Your desktop does not tell JuhRadial which window is in front")
            elif key == "window_switch" and focus_sees_xwayland_only():
                note = _("On this desktop only apps that run through XWayland are seen.")
            elif key == "monitor_switch" and monitor_sees_xwayland_only():
                note = _("On this desktop a crossing is noticed only while the pointer is over an XWayland window.")
            out.append({"key": key, "name": _(name), "desc": _(desc), "group": group,
                        "pattern": str(self.get(f"haptics.per_event.{key}", default)),
                        "enabled": on, "available": available, "reason": reason, "note": note})
        return out

    @pyqtSlot(str, str)
    def setHapticEventPattern(self, key, pattern):
        self.set(f"haptics.per_event.{key}", pattern)

    @pyqtSlot(str, bool)
    def setHapticEventEnabled(self, key, on):
        if key in ("window_switch", "monitor_switch"):
            self.set(f"haptics.{key}_enabled", bool(on))
        else:
            self.set(f"haptics.per_event_enabled.{key}", bool(on))

    @pyqtProperty(str, notify=configChanged)
    def hapticStyle(self):
        """quiet | balanced | expressive, or custom when the patterns match none."""
        cur = {k: str(self.get(f"haptics.per_event.{k}", d)) for (k, _n, _d, _g, d) in HAPTIC_EVENTS}
        for name, patterns in HAPTIC_STYLES.items():
            if cur == patterns:
                return name
        return "custom"

    @pyqtSlot(result="QVariant")
    def hapticPatternSnapshot(self):
        return {k: str(self.get(f"haptics.per_event.{k}", d)) for (k, _n, _d, _g, d) in HAPTIC_EVENTS}

    @pyqtSlot("QVariant")
    def setHapticPatterns(self, patterns):
        """Write every event's pattern in one save (styles, restore, undo)."""
        patterns = _js(patterns)
        for k, v in dict(patterns or {}).items():
            if any(k == e[0] for e in HAPTIC_EVENTS):
                self._set_path(["haptics", "per_event", k], str(v))
        self._save()
        self.reloadConfig()
        self.configChanged.emit()

    @pyqtSlot(str)
    def applyHapticStyle(self, name):
        if name in HAPTIC_STYLES:
            self.setHapticPatterns(HAPTIC_STYLES[name])

    @pyqtProperty("QVariantMap", notify=hapticDeviceChanged)
    def hapticDevice(self):
        """What the mouse reports: levelSupported, levelPct, forceSupported,
        forceMin/Max/Default/Current, tracking (the focused-window tracker)."""
        return dict(self._hap_dev)

    @pyqtSlot()
    def readHapticDevice(self):
        def level(r):
            if r and len(r) >= 3:
                self._hap_dev.update(levelSupported=bool(r[0]), levelPct=_to_int(r[2]))
            self.hapticDeviceChanged.emit()

        def force(r):
            if r and len(r) >= 5:
                self._hap_dev.update(forceSupported=bool(r[0]), forceMin=_to_int(r[1]),
                                     forceMax=_to_int(r[2]), forceDefault=_to_int(r[3]),
                                     forceCurrent=_to_int(r[4]))
            self.hapticDeviceChanged.emit()

        def tracking(r):
            if r:
                self._hap_dev["tracking"] = bool(r[0])
            self.hapticDeviceChanged.emit()
        self.daemon.call_then("GetHapticLevel", level)
        self.daemon.call_then("GetForceSense", force)
        self.daemon.call_then("WindowTrackingActive", tracking)

    @pyqtSlot(result="QVariant")
    def hapticLevels(self):
        return [{"id": i, "name": _(n), "pct": p} for (i, n, p) in HAPTIC_LEVELS]

    @pyqtProperty(str, notify=hapticDeviceChanged)
    def hapticLevel(self):
        """The strength step to show: the saved one, else the mouse's own."""
        pct = self.get("haptics.level", None)
        pct = _to_int(pct) if pct is not None else self._hap_dev.get("levelPct", 0)
        if not pct:
            return ""
        return min(HAPTIC_LEVELS, key=lambda lv: abs(lv[2] - pct))[0]

    @pyqtSlot(str)
    def setHapticLevel(self, level_id):
        pct = dict((i, p) for (i, _n, p) in HAPTIC_LEVELS).get(level_id)
        if pct is None:
            return
        self.set("haptics.level", pct)
        self._hap_dev["levelPct"] = pct
        self.hapticDeviceChanged.emit()

    @pyqtSlot(result="QVariant")
    def panelForces(self):
        return [{"id": i, "name": _(n), "pct": p} for (i, n, p) in PANEL_FORCES]

    def _force_pct(self, raw):
        lo, hi = self._hap_dev.get("forceMin", 0), self._hap_dev.get("forceMax", 0)
        return round((raw - lo) * 100 / (hi - lo)) if hi > lo else 0

    @pyqtProperty(str, notify=hapticDeviceChanged)
    def panelForce(self):
        """The Sense Panel force step to show: saved, else the mouse's own."""
        pct = self.get("haptics.panel_force", None)
        if pct is None:
            if not self._hap_dev.get("forceSupported"):
                return ""
            pct = self._force_pct(self._hap_dev.get("forceCurrent", 0))
        return min(PANEL_FORCES, key=lambda f: abs(f[2] - _to_int(pct)))[0]

    @pyqtProperty(int, notify=hapticDeviceChanged)
    def panelForceDefaultPct(self):
        """Where Logitech's default force sits on the Light..Firm scale."""
        return self._force_pct(self._hap_dev.get("forceDefault", 0)) if self._hap_dev.get("forceSupported") else -1

    @pyqtSlot(str)
    def setPanelForce(self, force_id):
        pct = dict((i, p) for (i, _n, p) in PANEL_FORCES).get(force_id)
        if pct is None:
            return
        self.set("haptics.panel_force", pct)
        lo, hi = self._hap_dev.get("forceMin", 0), self._hap_dev.get("forceMax", 0)
        if hi > lo:
            self._hap_dev["forceCurrent"] = lo + (hi - lo) * pct // 100
        self.hapticDeviceChanged.emit()

    @pyqtSlot(result="QVariant")
    def sliceTickRates(self):
        return [{"id": i, "name": _(n), "ms": ms} for (i, n, ms) in SLICE_TICK_RATES]

    @pyqtProperty(str, notify=configChanged)
    def sliceTickRate(self):
        ms = _to_int(self.get("haptics.slice_debounce_ms", 20), 20)
        return min(SLICE_TICK_RATES, key=lambda r: abs(r[2] - ms))[0]

    @pyqtSlot(str)
    def setSliceTickRate(self, rate_id):
        ms = dict((i, m) for (i, _n, m) in SLICE_TICK_RATES).get(rate_id)
        if ms is not None:
            self.set("haptics.slice_debounce_ms", ms)

    @pyqtSlot(result="QVariant")
    def hapticMutedApps(self):
        return [str(a) for a in (self.get("haptics.muted_apps") or [])]

    @pyqtSlot(str)
    def addHapticMutedApp(self, cls):
        cls = (cls or "").strip().lower()
        apps = self.hapticMutedApps()
        if cls and cls not in apps:
            self.set("haptics.muted_apps", apps + [cls])

    @pyqtSlot(str)
    def removeHapticMutedApp(self, cls):
        self.set("haptics.muted_apps", [a for a in self.hapticMutedApps() if a != cls])

    @pyqtSlot(str, result=str)
    def appClassFor(self, desktop_id):
        """The window class an installed app's windows carry: its
        StartupWMClass, else the desktop id's last part (org.gnome.Nautilus
        -> nautilus), lowercase like the focus tracker reports it."""
        try:
            from gi.repository import Gio
            app = Gio.DesktopAppInfo.new(desktop_id) if desktop_id else None
            wm = app.get_startup_wm_class() if app else None
        except Exception:
            wm = None
        if wm:
            return wm.lower()
        base = re.sub(r"\.desktop$", "", desktop_id or "")
        return base.rsplit(".", 1)[-1].lower()

    # ---- easy-switch ----
    @pyqtSlot(int)
    def switchHost(self, host):
        """Send the mouse to another computer. The row moves only when the
        daemon says the mouse went; a refusal says why."""
        before = self._cur_host

        def done(r):
            if r and bool(r[0]):
                self._cur_host = host
            else:
                self._cur_host = before
                self.notify(_("The mouse did not switch. Is it awake, and is that computer paired?"), "info")
            self.liveChanged.emit()
        self.daemon.call_then("SetHost", done, _u8(host))

    hostSlotsChanged = pyqtSignal()

    @pyqtProperty("QVariant", notify=hostSlotsChanged)
    def hostSlots(self):
        """[{index, paired, bus ("receiver" | "bluetooth" | ""), name}] for
        each Easy-Switch slot; [] until read (readHostSlots)."""
        return list(self._host_slots)

    @pyqtSlot()
    def readHostSlots(self):
        buses = {1: "receiver", 2: "bluetooth", 3: "bluetooth", 4: "bluetooth"}

        def done(r):
            rows = r[0] if r and isinstance(r[0], list) else []
            self._host_slots = [{"index": i, "paired": _to_int(row[0]) == 1,
                                 "bus": buses.get(_to_int(row[1]), ""), "name": str(row[2])}
                                for i, row in enumerate(rows) if isinstance(row, (list, tuple)) and len(row) >= 3]
            self.hostSlotsChanged.emit()
        self.daemon.call_then("GetHostSlots", done)

    @pyqtProperty(str, notify=configChanged)
    def localHostAlias(self):
        """What this computer is called in Settings, the tray and the ring."""
        return str(self.get("radial_menu.easy_switch_local_alias", "") or "")

    @pyqtSlot(str)
    def setLocalHostAlias(self, name):
        self.setLocal("radial_menu.easy_switch_local_alias", name.strip()[:24])

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
        """Ask the daemon; the switch moves when GamingModeChanged says so."""
        self.setLocal("gaming.enabled", bool(on))

        def done(r):
            if r is None:
                self.notify(_("Gaming mode needs the JuhRadial service"), "info")
            self.liveChanged.emit()  # a refused change snaps the switch back
        self.daemon.call_then("SetGamingMode", done, bool(on))

    @pyqtProperty("QVariantMap", notify=liveChanged)
    def gamingStatus(self):
        """{auto, stage (1-based), dpi, gamemodeInstalled, gamemodeActive}."""
        return dict(self._gaming)

    GAMING_NAME_MAX = 12
    GAMING_PRESETS_MAX = 5
    GAMING_COLORS = ["blue", "green", "red", "yellow", "mauve", "peach", "teal", "pink"]

    @pyqtSlot(result="QVariant")
    def gamingPresets(self):
        out = []
        for p in (self.get("gaming.dpi_profiles") or []):
            if isinstance(p, dict):
                color = str(p.get("color") or "blue")
                out.append({"name": str(p.get("name") or ""), "dpi": _to_int(p.get("dpi"), 1000),
                            "color": color, "hex": SLICE_COLORS.get(color, "#89B4FA")})
        return out

    def _save_presets(self, presets, active=None):
        presets = presets[:self.GAMING_PRESETS_MAX]
        if active is None:
            active = _to_int(self.get("gaming.active_dpi_profile", 1), 1)
        self._set_path(["gaming", "dpi_profiles"], [
            {"name": p["name"][:self.GAMING_NAME_MAX], "dpi": self.snapDpi(p["dpi"]), "color": p["color"]}
            for p in presets])
        self._set_path(["gaming", "active_dpi_profile"], max(0, min(len(presets) - 1, active)))
        self._save()
        self.reloadConfig()
        self.configChanged.emit()

    @pyqtSlot(int, str, "QVariant")
    def setGamingPreset(self, idx, field, value):
        value = _js(value)
        presets = self.gamingPresets()
        if not (0 <= idx < len(presets)) or field not in ("name", "dpi", "color"):
            return
        if field == "name":
            value = str(value).strip()[:self.GAMING_NAME_MAX] or presets[idx]["name"]
        presets[idx][field] = _to_int(value) if field == "dpi" else str(value)
        self._save_presets(presets)

    @pyqtSlot(int)
    def setActiveGamingPreset(self, idx):
        """Takes effect at once while gaming mode is on (the daemon applies it)."""
        self._save_presets(self.gamingPresets(), idx)

    @pyqtSlot()
    def addGamingPreset(self):
        presets = self.gamingPresets()
        if len(presets) >= self.GAMING_PRESETS_MAX:
            return
        used = {p["color"] for p in presets}
        color = next((c for c in self.GAMING_COLORS if c not in used), "blue")
        dpi = min(self.dpiRange["max"], (presets[-1]["dpi"] * 2) if presets else 1000)
        presets.append({"name": _("Preset %d") % (len(presets) + 1), "dpi": dpi, "color": color})
        self._save_presets(presets)

    @pyqtSlot(int)
    def removeGamingPreset(self, idx):
        presets = self.gamingPresets()
        if len(presets) <= 1 or not (0 <= idx < len(presets)):
            return
        active = _to_int(self.get("gaming.active_dpi_profile", 1), 1)
        presets.pop(idx)
        self._save_presets(presets, active - 1 if idx < active else active)

    @pyqtSlot(int, int)
    def moveGamingPreset(self, idx, delta):
        presets = self.gamingPresets()
        j = idx + delta
        if not (0 <= idx < len(presets) and 0 <= j < len(presets)):
            return
        active = _to_int(self.get("gaming.active_dpi_profile", 1), 1)
        presets[idx], presets[j] = presets[j], presets[idx]
        active = j if active == idx else (idx if active == j else active)
        self._save_presets(presets, active)

    @pyqtSlot(result="QVariant")
    def gamingAutoApps(self):
        return [str(a) for a in (self.get("gaming.auto_apps") or [])]

    @pyqtSlot(str)
    def addGamingAutoApp(self, cls):
        cls = (cls or "").strip().lower()
        apps = self.gamingAutoApps()
        if cls and cls not in apps:
            self.set("gaming.auto_apps", apps + [cls])

    @pyqtSlot(str)
    def removeGamingAutoApp(self, cls):
        self.set("gaming.auto_apps", [a for a in self.gamingAutoApps() if a != cls])

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
        m = _js(m)
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
        rows = _js(rows)
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
        rows = _js(rows)
        m = self._find_macro(mid)
        if not m:
            return False
        m["actions"] = macro_actions([dict(r) for r in (rows or []) if isinstance(r, dict)])
        return self._store_macro(m)

    @pyqtSlot(str, "QVariant", result=bool)
    def saveMacroSteps(self, mid, actions):
        """Replace a macro's ordered action list and resave (step editor)."""
        actions = _js(actions)
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

    @pyqtProperty("QStringList", notify=liveChanged)
    def firmware(self):
        """Main firmware versions the mouse reports ("RBM 27.00.B0015")."""
        return list(self._firmware)

    @pyqtProperty(float, notify=liveChanged)
    def refreshedAt(self):
        """When the last full read of the mouse finished (epoch s, 0 = never)."""
        return self._refreshed_at

    @pyqtSlot(result="QVariant")
    def deviceOverrides(self):
        """Settings kept only for this mouse (config `devices.<unit id>`), as
        dotted paths ("buttons.back")."""
        own = self.get(f"devices.{self._unit_id}") if self._unit_id else None
        out = []

        def walk(node, path):
            if isinstance(node, dict) and node:
                for k, v in node.items():
                    walk(v, f"{path}.{k}" if path else str(k))
            elif path:
                out.append(path)
        walk(own if isinstance(own, dict) else {}, "")
        return sorted(out)

    @pyqtSlot()
    def resetDeviceOverrides(self):
        """Drop this mouse's own settings: it follows the global ones again."""
        devices = self.get("devices")
        if not self._unit_id or not isinstance(devices, dict) or self._unit_id not in devices:
            return
        devices = dict(devices)
        devices.pop(self._unit_id)
        self.set("devices", devices)
        self.reloadConfig()
        self.configChanged.emit()
        self.notify(_("This mouse follows your global settings again"), "success")

    @pyqtSlot(str, str)
    def copyText(self, text, what=""):
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
        self.notify(_("{what} copied").format(what=what) if what else _("Copied"), "success")

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

    # ---- Actions Ring geometry (Settings → Radial menu) ----
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
                  "/usr/bin/juhradial-mx", str(pathlib.Path.home() / ".local/bin/juhradial-mx")):
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
                  "/usr/bin/juhradiald", str(pathlib.Path.home() / ".local/bin/juhradiald"), str(dev)):
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
        # A text keeps its own spacing and line breaks (it is pasted as is).
        out = {"kind": kind, "value": str(obj.get("value", "")) if kind == "text" else value}
        for extra in ("label", "icon"):
            if isinstance(obj.get(extra), str) and obj[extra]:
                out[extra] = obj[extra]
        if kind == "shortcut" and obj.get("hold"):
            out["hold"] = True
        if kind == "text":
            if obj.get("enter"):
                out["enter"] = True
            if obj.get("paste_with") in ("auto", "ctrl+v", "ctrl+shift+v"):
                out["paste_with"] = obj["paste_with"]
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
        obj = _js(obj)
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
        return [{"id": i, "name": _(n), "desc": _(d), "beats": b} for (i, n, d, b) in HAPTIC_PATTERNS]

    # "Classic Light" (Themes, Buttons): the Classic ring on the white GitHub
    # Light surface, the light classic ring 0.4.4 offered.
    LIGHT_CLASSIC = "github-light"

    @pyqtProperty(str, notify=configChanged)
    def wheelSkin(self):
        """The skin a picker shows as chosen: a wheel key, "none" or "classic-light"."""
        k = self.get("radial.wheel", "") or "none"
        if k != "none":
            return k
        return "classic-light" if self.get("theme", "phosphor") == self.LIGHT_CLASSIC else "none"

    @pyqtSlot(str)
    def setWheelSkin(self, key):
        if key == "classic-light":
            self.set("radial.wheel", "none")
            self.set("theme", self.LIGHT_CLASSIC)
            return
        if key == "none" and self.get("theme", "phosphor") == self.LIGHT_CLASSIC:
            self.set("theme", "phosphor")  # back to the dark Classic surface
        self.set("radial.wheel", key)

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
        names = dict(THUMBWHEEL_MODES)
        return [{"id": i, "name": _(names[i])} for i in THUMBWHEEL_PICKER]

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
        return is_newer_version(self._update.get("latest"), self.appVersion)

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

    # ---- Flow ----
    # The Flow server lives in the overlay process, which follows config.json
    # live (juhradial-overlay.py follow_flow_setting). It publishes connected
    # computers in flow_status.json; which ones may use Flow is the trust file
    # the bridge re-reads (overlay/flow/trust.py, same format).
    FLOW_TCP_PORT = 59872
    FLOW_UDP_PORT = 59873

    @staticmethod
    def _flow_trust_path():
        return CONFIG_DIR / "flow_trusted.json"

    def _flow_trust(self):
        try:
            data = json.loads(self._flow_trust_path().read_text())
        except (OSError, ValueError):
            data = {}
        return {"trusted": dict(data.get("trusted") or {}), "denied": dict(data.get("denied") or {})}

    def _set_flow_trust(self, fp, state, hostname="", platform=""):
        data = self._flow_trust()
        for key in ("trusted", "denied"):
            data[key].pop(fp, None)
        if state in ("trusted", "denied"):
            data[state][fp] = {"hostname": hostname, "platform": platform, "at": int(time.time())}
        path = self._flow_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    @classmethod
    def _flow_listening(cls, proc="/proc/net"):
        """True while something listens on the Flow bridge port (the overlay's
        Flow server is up)."""
        port = "%04X" % cls.FLOW_TCP_PORT
        for name in ("tcp", "tcp6"):
            try:
                lines = pathlib.Path(proc, name).read_text().splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                cols = line.split()
                if len(cols) > 3 and cols[1].endswith(":" + port) and cols[3] == "0A":
                    return True
        return False

    @pyqtSlot(result="QVariant")
    def flowStatus(self):
        """{running, peers: [{hostname, platform, ip, fingerprint, state}],
        trusted: [{fingerprint, hostname, platform, connected}], clipboardTool}."""
        peers = []
        try:
            status = json.loads((CONFIG_DIR / "flow_status.json").read_text())
            if time.time() - float(status.get("updated_at", 0)) < 15:
                peers = [dict(p) for p in status.get("peers") or [] if isinstance(p, dict)]
        except (OSError, ValueError, TypeError):
            pass
        for p in peers:
            p.setdefault("state", "trusted")
            p.setdefault("fingerprint", "")
        online = {p["fingerprint"] for p in peers}
        trust = self._flow_trust()
        trusted = [{"fingerprint": fp, "hostname": str(v.get("hostname") or ""),
                    "platform": str(v.get("platform") or ""), "connected": fp in online}
                   for fp, v in sorted(trust["trusted"].items(), key=lambda kv: str(kv[1].get("hostname")))]
        wayland = os.environ.get("XDG_SESSION_TYPE", "") == "wayland"
        tool = shutil.which("wl-copy") if wayland else None
        tool = tool or shutil.which("xclip")
        return {"running": self._flow_listening(), "peers": peers, "trusted": trusted,
                "clipboardTool": os.path.basename(tool) if tool else "",
                "clipboardHint": "wl-clipboard" if wayland else "xclip"}

    @pyqtSlot(str, str, str)
    def approveFlowPeer(self, fp, hostname, platform):
        self._set_flow_trust(fp, "trusted", hostname, platform)
        self.notify(_("{name} can now use Flow with this computer").format(name=hostname or fp), "success")

    @pyqtSlot(str, str, str)
    def denyFlowPeer(self, fp, hostname, platform):
        self._set_flow_trust(fp, "denied", hostname, platform)
        self.notify(_("{name} was turned away").format(name=hostname or fp), "info")

    @pyqtSlot(str)
    def forgetFlowPeer(self, fp):
        self._set_flow_trust(fp, "")
        self.notify(_("Forgotten. It has to be approved again to use Flow"), "info")

    @pyqtSlot(result="QVariant")
    def flowScreens(self):
        """The Flow edge monitor choices: Automatic, then each screen by its
        connector name (what the runtime matches on)."""
        from PyQt6.QtGui import QGuiApplication
        out = [{"id": "", "name": _("Automatic")}]
        for scr in QGuiApplication.screens():
            g = scr.geometry()
            out.append({"id": scr.name(), "name": f"{scr.name()} ({g.width()} x {g.height()})"})
        return out

    @pyqtSlot()
    def openJuhFlow(self):
        """The JuhFlow companion app (Mac) in the repository."""
        QDesktopServicesOpen(REPO_URL + "/tree/master/juhflow")

    @pyqtSlot(result="QVariant")
    def flowFirewall(self):
        """Whether a firewall may block Flow, with the command that opens it."""
        def active(unit):
            try:
                return subprocess.run(["systemctl", "is-active", "--quiet", unit],
                                      timeout=3).returncode == 0
            except (OSError, subprocess.SubprocessError):
                return False
        tcp, udp = self.FLOW_TCP_PORT, self.FLOW_UDP_PORT
        if active("firewalld"):
            try:
                open_ = all(subprocess.run(["firewall-cmd", f"--query-port={port}"],
                                           capture_output=True, text=True, timeout=4).stdout.strip() == "yes"
                            for port in (f"{tcp}/tcp", f"{udp}/udp"))
            except (OSError, subprocess.SubprocessError):
                open_ = False
            return {"firewall": "firewalld", "open": open_,
                    "command": f"sudo firewall-cmd --permanent --add-port={tcp}/tcp --add-port={udp}/udp && sudo firewall-cmd --reload"}
        if active("ufw"):
            return {"firewall": "ufw", "open": None,
                    "command": f"sudo ufw allow {tcp}/tcp && sudo ufw allow {udp}/udp"}
        return {"firewall": "", "open": True, "command": ""}

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

    def _diagnostics(self):
        """System info plus firmware, keyboard state and the daemon's last 50
        journal lines: what a bug report needs (#13, #52 reporters pasted it by hand)."""
        kb = self._kb_info or {}
        lines = [self._system_info(),
                 f"Firmware: {', '.join(self._firmware) or 'unknown'}",
                 f"Connection: {self.connection}",
                 f"Keyboard: {'on' if kb.get('enabled') else 'off'}, "
                 f"{'present' if kb.get('present') else 'not detected'}"
                 + (", asleep" if kb.get("sleeping") else "")]
        try:
            r = subprocess.run(["journalctl", "--user", "-u", "juhradialmx-daemon", "-n", "50",
                                "--no-pager", "-o", "short-iso"], capture_output=True, text=True, timeout=5)
            lines += ["", "== daemon (last 50 lines) ==", (r.stdout or r.stderr).strip()]
        except (OSError, subprocess.SubprocessError) as e:
            lines += ["", f"journal: {e}"]
        return "\n".join(lines)

    @pyqtSlot()
    def copyDiagnostics(self):
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._diagnostics())
        self.notify(_("Diagnostics copied. Paste them into your bug report."), "success")

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
