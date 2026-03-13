"""
JuhRadial MX - Overlay Actions & Theme Bridge

Theme loading, action definitions, config loading, AI icon loading,
and settings launcher.

SPDX-License-Identifier: GPL-3.0
"""

import os
import subprocess

from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtCore import Qt
from PyQt6.QtSvg import QSvgRenderer

from overlay_constants import MENU_RADIUS
from themes import (
    get_colors,
    load_theme_name,
    get_radial_image,
    get_radial_params,
)
from i18n import _
import settings_constants


# =============================================================================
# THEME BRIDGE
# =============================================================================


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


# =============================================================================
# ACTION DEFINITIONS
# =============================================================================

AI_SUBMENU = [
    ("Claude", "url", "https://claude.ai", "claude"),
    ("ChatGPT", "url", "https://chat.openai.com", "chatgpt"),
    ("Gemini", "url", "https://gemini.google.com", "gemini"),
    ("Perplexity", "url", "https://perplexity.ai", "perplexity"),
]

# Easy-Switch submenu - built dynamically in load_actions_from_config()
EASY_SWITCH_SUBMENU = [
    ("Host 1", "easy_switch", "0", "os_unknown"),
    ("Host 2", "easy_switch", "1", "os_unknown"),
    ("Host 3", "easy_switch", "2", "os_unknown"),
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


# =============================================================================
# CONFIG LOADING
# =============================================================================


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

            # Build Easy-Switch submenu with OS-specific icons
            os_types = config.get("radial_menu", {}).get(
                "easy_switch_host_os", ["unknown", "unknown", "unknown"]
            )
            global EASY_SWITCH_SUBMENU
            EASY_SWITCH_SUBMENU = [
                (f"Host {i+1}", "easy_switch", str(i), f"os_{os_types[i] if i < len(os_types) else 'unknown'}")
                for i in range(3)
            ]

            if not slices:
                print("No radial_menu slices in config, using defaults")
                return DEFAULT_ACTIONS

            settings_constants._ = _
            settings_constants.refresh_translations(_)

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


# =============================================================================
# AI SUBMENU ICONS (SVG)
# =============================================================================

AI_ICONS = {}
OS_ICONS = {}


def _get_assets_dir():
    """Get the assets directory, searching dev and installed paths."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_dirs = [
        os.path.join(script_dir, "..", "assets"),  # dev: overlay/../assets
        os.path.join(script_dir, "assets"),  # installed: /usr/share/juhradial/assets
        "/usr/share/juhradial/assets",  # absolute fallback
    ]
    return next((d for d in search_dirs if os.path.isdir(d)), search_dirs[0])


def _svg_to_pixmap(path, size=64):
    """Pre-render SVG to QPixmap at fixed size (avoids huge buffer allocations)."""
    from PyQt6.QtGui import QPixmap, QPainter, QImage
    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        return None
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    renderer.render(p)
    p.end()
    return QPixmap.fromImage(img)


def load_ai_icons():
    """Load SVG icons for AI submenu items (pre-rendered to QPixmap)."""
    global AI_ICONS
    assets_dir = _get_assets_dir()

    icon_files = {
        "claude": "ai-claude.svg",
        "chatgpt": "ai-chatgpt.svg",
        "gemini": "ai-gemini.svg",
        "perplexity": "ai-perplexity.svg",
    }

    for name, filename in icon_files.items():
        path = os.path.join(assets_dir, filename)
        if os.path.exists(path):
            pixmap = _svg_to_pixmap(path)
            if pixmap:
                AI_ICONS[name] = pixmap
                print(f"Loaded AI icon: {name}")
            else:
                print(f"Failed to load AI icon: {path}")
        else:
            print(f"AI icon not found: {path}")


def load_os_icons():
    """Load SVG icons for OS Easy-Switch submenu items (pre-rendered to QPixmap)."""
    global OS_ICONS
    assets_dir = _get_assets_dir()

    icon_files = {
        "os_linux": "os-linux.svg",
        "os_windows": "os-windows.svg",
        "os_macos": "os-macos.svg",
        "os_ios": "os-ios.svg",
        "os_android": "os-android.svg",
        "os_chromeos": "os-chromeos.svg",
        "os_unknown": "os-unknown.svg",
    }

    for name, filename in icon_files.items():
        path = os.path.join(assets_dir, filename)
        if os.path.exists(path):
            pixmap = _svg_to_pixmap(path)
            if pixmap:
                OS_ICONS[name] = pixmap
                print(f"Loaded OS icon: {name}")
            else:
                print(f"Failed to load OS icon: {path}")
        else:
            print(f"OS icon not found: {path}")


# =============================================================================
# SETTINGS LAUNCHER
# =============================================================================


def open_settings():
    """Launch or refocus the settings dashboard.

    On GNOME Wayland, present() from a D-Bus Activate can't raise the window
    because the calling process (radial overlay) has already hidden itself.
    So we check if the settings app is running and if so, kill and relaunch
    to guarantee a focused window.
    """
    settings_script = os.path.join(os.path.dirname(__file__), "settings_dashboard.py")

    # Check if settings app is already running on D-Bus
    try:
        result = subprocess.run(
            ["busctl", "--user", "status", "org.kde.juhradialmx.settings"],
            capture_output=True, timeout=0.5,
        )
        if result.returncode == 0:
            # Already running - kill it so the fresh launch gets focus
            subprocess.run(
                ["pkill", "-f", "settings_dashboard.py"],
                capture_output=True, timeout=1,
            )
            import time
            time.sleep(0.15)
    except (subprocess.SubprocessError, OSError):
        pass  # Settings process may not be running

    subprocess.Popen(
        ["python3", settings_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# =============================================================================
# MEDIA STATE
# =============================================================================

MEDIA_PLAYING = False


def get_media_state():
    """Query playerctl for current playback state. Updates MEDIA_PLAYING global."""
    global MEDIA_PLAYING
    try:
        result = subprocess.run(
            ["playerctl", "status"],
            capture_output=True, text=True, timeout=0.2,
        )
        MEDIA_PLAYING = result.stdout.strip() == "Playing"
    except (subprocess.SubprocessError, OSError):
        MEDIA_PLAYING = False


# =============================================================================
# MUTABLE GLOBALS (reassigned by on_show in main overlay)
# =============================================================================

# Load theme at startup
COLORS = load_theme()

# 3D radial image (loaded after QApplication creation)
RADIAL_IMAGE = None
RADIAL_PARAMS = None

# Load actions at startup
ACTIONS = load_actions_from_config()

# Minimal mode flag - hides slice/wedge graphics, shows only floating icons
MINIMAL_MODE = False


def load_minimal_mode():
    """Read radial.minimal_mode from config.json. Returns bool."""
    import json
    from pathlib import Path

    config_path = Path.home() / ".config" / "juhradial" / "config.json"
    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return bool(cfg.get("radial", {}).get("minimal_mode", False))
    except (OSError, ValueError, KeyError):
        pass  # Config file missing or malformed
    return False
