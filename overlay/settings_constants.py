"""
JuhRadial MX - Settings Constants

Data constants for mouse buttons, navigation, and radial menu actions.

SPDX-License-Identifier: GPL-3.0
"""

from i18n import _


# =============================================================================
# MX MASTER 4 BUTTON DEFINITIONS
# Positions for 3/4 angle view (front-top-left perspective)
# Coordinates are normalized (0-1) relative to the drawing area
# line_from: 'top' = line comes from above, 'left' = line comes from left
# =============================================================================
_BASE_MOUSE_BUTTONS = {
    "middle": {
        "name": "Middle Button",
        "action": "Middle Click",
        "pos": (0.58, 0.19),  # Top of MagSpeed scroll wheel
        "line_from": "top",
    },
    "shift_wheel": {
        "name": "Shift Wheel Mode",
        "action": "SmartShift",
        "pos": (0.58, 0.36),  # Square button below scroll wheel
        "line_from": "top",
    },
    "forward": {
        "name": "Forward",
        "action": "Forward",
        "pos": (0.23, 0.40),  # Upper thumb button
        "line_from": "left",
    },
    "horizontal_scroll": {
        "name": "Horizontal Scroll",
        "action": "Scroll Left/Right",
        "pos": (0.24, 0.47),  # Grey thumb wheel
        "line_from": "left",
    },
    "back": {
        "name": "Back",
        "action": "Back",
        "pos": (0.27, 0.54),  # Lower thumb button
        "line_from": "left",
    },
    "gesture": {
        "name": "Gestures",
        "action": "Virtual desktops",
        "pos": (0.26, 0.36),  # Dot on upper thumb area
        "line_from": "l_up",
        "label_y": 0.34,  # Label Y position (above Forward)
    },
    "thumb": {
        "name": "Show Actions Ring",
        "action": "Radial Menu",
        "pos": (0.28, 0.42),  # Dot on lower thumb area
        "line_from": "l_up",
        "label_y": 0.26,  # Label Y position (above Gestures)
    },
}

# =============================================================================
# SIDEBAR NAVIGATION ITEMS
# =============================================================================
_BASE_NAV_ITEMS = [
    ("buttons", "BUTTONS", "input-mouse-symbolic"),
    ("scroll", "SENSITIVITY", "input-touchpad-symbolic"),
    ("haptics", "HAPTIC FEEDBACK", "audio-speakers-symbolic"),
    ("devices", "DEVICES", "computer-symbolic"),
    ("easy_switch", "EASY-SWITCH", "network-wireless-symbolic"),
    ("flow", "FLOW", "view-dual-symbolic"),
    ("settings", "SETTINGS", "emblem-system-symbolic"),
]

# Default actions for each button (used for restore)
_BASE_DEFAULT_BUTTON_ACTIONS = {
    "middle": "Middle Click",
    "shift_wheel": "SmartShift",
    "forward": "Forward",
    "horizontal_scroll": "Scroll Left/Right",
    "back": "Back",
    "gesture": "Virtual Desktops",
    "thumb": "Radial Menu",
}

# Available actions for button assignment
_BASE_BUTTON_ACTIONS = [
    ("middle_click", "Middle Click"),
    ("back", "Back"),
    ("forward", "Forward"),
    ("copy", "Copy"),
    ("paste", "Paste"),
    ("undo", "Undo"),
    ("redo", "Redo"),
    ("screenshot", "Screenshot"),
    ("smartshift", "SmartShift"),
    ("scroll_left_right", "Scroll Left/Right"),
    ("volume_up", "Volume Up"),
    ("volume_down", "Volume Down"),
    ("play_pause", "Play/Pause"),
    ("mute", "Mute"),
    ("radial_menu", "Radial Menu"),
    ("virtual_desktops", "Virtual Desktops"),
    ("zoom_in", "Zoom In"),
    ("zoom_out", "Zoom Out"),
    ("none", "Do Nothing"),
    ("custom", "Custom Action..."),
]

# Radial menu action definitions: (action_id, display_name, icon, type, command, color)
_BASE_RADIAL_ACTIONS = [
    (
        "play_pause",
        "Play/Pause",
        "media-playback-start-symbolic",
        "exec",
        "playerctl play-pause",
        "green",
    ),
    (
        "screenshot",
        "Screenshot",
        "camera-photo-symbolic",
        "exec",
        "flameshot gui",
        "purple",
    ),
    (
        "lock",
        "Lock Screen",
        "system-lock-screen-symbolic",
        "exec",
        "loginctl lock-session",
        "red",
    ),
    ("settings", "Settings", "preferences-system-symbolic", "settings", "", "blue"),
    ("files", "Files", "system-file-manager-symbolic", "exec", "dolphin", "orange"),
    ("emoji", "Emoji Picker", "face-smile-symbolic", "exec", "ibus emoji", "yellow"),
    ("new_note", "New Note", "document-new-symbolic", "exec", "kwrite", "yellow"),
    ("ai", "AI Assistant", "dialog-information-symbolic", "submenu", "", "teal"),
    ("copy", "Copy", "edit-copy-symbolic", "shortcut", "ctrl+c", "blue"),
    ("paste", "Paste", "edit-paste-symbolic", "shortcut", "ctrl+v", "blue"),
    ("undo", "Undo", "edit-undo-symbolic", "shortcut", "ctrl+z", "blue"),
    ("redo", "Redo", "edit-redo-symbolic", "shortcut", "ctrl+shift+z", "blue"),
    ("cut", "Cut", "edit-cut-symbolic", "shortcut", "ctrl+x", "blue"),
    (
        "select_all",
        "Select All",
        "edit-select-all-symbolic",
        "shortcut",
        "ctrl+a",
        "blue",
    ),
    (
        "close_window",
        "Close Window",
        "window-close-symbolic",
        "shortcut",
        "alt+F4",
        "red",
    ),
    ("minimize", "Minimize", "window-minimize-symbolic", "shortcut", "super+d", "blue"),
    (
        "volume_up",
        "Volume Up",
        "audio-volume-high-symbolic",
        "exec",
        "pactl set-sink-volume @DEFAULT_SINK@ +5%",
        "green",
    ),
    (
        "volume_down",
        "Volume Down",
        "audio-volume-low-symbolic",
        "exec",
        "pactl set-sink-volume @DEFAULT_SINK@ -5%",
        "green",
    ),
    (
        "mute",
        "Mute",
        "audio-volume-muted-symbolic",
        "exec",
        "pactl set-sink-mute @DEFAULT_SINK@ toggle",
        "red",
    ),
    (
        "next_track",
        "Next Track",
        "media-skip-forward-symbolic",
        "exec",
        "playerctl next",
        "green",
    ),
    (
        "prev_track",
        "Previous Track",
        "media-skip-backward-symbolic",
        "exec",
        "playerctl previous",
        "green",
    ),
    ("none", "Do Nothing", "action-unavailable-symbolic", "none", "", "gray"),
]


MOUSE_BUTTONS = {}
NAV_ITEMS = []
DEFAULT_BUTTON_ACTIONS = {}
BUTTON_ACTIONS = []
RADIAL_ACTIONS = []
_RADIAL_LABEL_ALIAS_TO_ID = {
    "Play/Pause": "play_pause",
    "New Note": "new_note",
    "Lock": "lock",
    "Settings": "settings",
    "Screenshot": "screenshot",
    "Emoji": "emoji",
    "Files": "files",
    "AI": "ai",
}


def refresh_translations():
    base_action_labels = {label for _, label in _BASE_BUTTON_ACTIONS}
    existing_actions = {key: info.get("action") for key, info in MOUSE_BUTTONS.items()}

    MOUSE_BUTTONS.clear()
    for key, info in _BASE_MOUSE_BUTTONS.items():
        action_label = existing_actions.get(key, info["action"])
        if action_label in base_action_labels:
            action_label = _(action_label)
        MOUSE_BUTTONS[key] = {
            **info,
            "name": _(info["name"]),
            "action": action_label,
        }

    NAV_ITEMS[:] = [
        (item_id, _(label), icon) for item_id, label, icon in _BASE_NAV_ITEMS
    ]

    DEFAULT_BUTTON_ACTIONS.clear()
    for key, label in _BASE_DEFAULT_BUTTON_ACTIONS.items():
        DEFAULT_BUTTON_ACTIONS[key] = _(label)

    BUTTON_ACTIONS[:] = [
        (action_id, _(label)) for action_id, label in _BASE_BUTTON_ACTIONS
    ]

    RADIAL_ACTIONS[:] = [
        (action_id, _(label), icon, action_type, command, color)
        for action_id, label, icon, action_type, command, color in _BASE_RADIAL_ACTIONS
    ]


def find_radial_action_index(label):
    alias_action_id = _RADIAL_LABEL_ALIAS_TO_ID.get(label)
    if alias_action_id:
        for idx, (action_id, _, _, _, _, _) in enumerate(RADIAL_ACTIONS):
            if action_id == alias_action_id:
                return idx
    for idx, (_, name, _, _, _, _) in enumerate(RADIAL_ACTIONS):
        if name == label:
            return idx
    for idx, (_, name, _, _, _, _) in enumerate(_BASE_RADIAL_ACTIONS):
        if name == label:
            return idx
    return -1


def translate_radial_label(label, action_id=None):
    if action_id:
        for rid, name, _, _, _, _ in RADIAL_ACTIONS:
            if rid == action_id:
                return name

    alias_action_id = _RADIAL_LABEL_ALIAS_TO_ID.get(label)
    if alias_action_id:
        for rid, name, _, _, _, _ in RADIAL_ACTIONS:
            if rid == alias_action_id:
                return name

    for idx, (_, base_name, _, _, _, _) in enumerate(_BASE_RADIAL_ACTIONS):
        if base_name == label:
            return RADIAL_ACTIONS[idx][1]

    for _, name, _, _, _, _ in RADIAL_ACTIONS:
        if name == label:
            return name

    return label


refresh_translations()
