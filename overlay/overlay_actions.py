"""
JuhRadial MX - Overlay Actions & Theme Bridge

Theme loading, action definitions, config loading, AI icon loading,
and settings launcher.

SPDX-License-Identifier: GPL-3.0
"""

import os
import subprocess

from PyQt6.QtGui import QColor, QPixmap, QPainter
from PyQt6.QtCore import Qt
from PyQt6.QtSvg import QSvgRenderer

from overlay_constants import (
    MENU_RADIUS,
    ICON_ZONE_RADIUS,
    SHADOW_OFFSET,
    SUBMENU_EXTEND,
)
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

    # Honour an explicit accent override from config.json: the Qt settings
    # app's theme picker writes radial.accent so the overlay's accent matches
    # the app without dragging in a second palette. Flows to every
    # COLORS["accent"] paint site (ripple, ping, slice highlight, glow).
    accent_override = _config_radial_accent()
    if accent_override:
        qcolors["accent"] = hex_to_qcolor(accent_override)
        qcolors["lavender"] = qcolors["accent"]

    # Ensure 'lavender' exists (used for accent in ACTIONS)
    if "lavender" not in qcolors and "accent" in qcolors:
        qcolors["lavender"] = qcolors["accent"]

    print(f"Loaded theme: {theme_name}")
    return qcolors


def _config_section(key, default=None):
    """A top-level config.json value (read fresh), or `default`."""
    import json
    from pathlib import Path

    try:
        cfg = json.loads((Path.home() / ".config" / "juhradial" / "config.json").read_text())
    except (OSError, ValueError):
        return default
    return cfg.get(key, default) if isinstance(cfg, dict) else default


def _config_radial_section():
    """The ``radial`` section of config.json, or an empty dict."""
    import json
    from pathlib import Path

    try:
        cfg = json.loads((Path.home() / ".config" / "juhradial" / "config.json").read_text())
    except (OSError, ValueError):
        return {}
    radial = cfg.get("radial") if isinstance(cfg, dict) else None
    return radial if isinstance(radial, dict) else {}


def _config_radial_accent():
    """Accent hex written by the Qt settings theme picker (radial.accent), or None."""
    accent = _config_radial_section().get("accent")
    return accent if isinstance(accent, str) and accent.startswith("#") else None


def _config_wheel_key():
    """Wheel skin key (radial.wheel) chosen in the Qt settings app, or None."""
    key = _config_radial_section().get("wheel")
    return key if isinstance(key, str) and key and key != "none" else None


ICON_SCALE_MIN, ICON_SCALE_MAX = 0.6, 1.6


def apply_ring_geometry(params, outer_radius, inner_radius, icon_scale=1.0):
    """Layer the user's ring geometry (Settings → Appearance) over theme params.

    A configured outer radius scales everything that is sized in pixels by the
    same ratio (outer_radius / MENU_RADIUS): the icon zone, shadow spread,
    submenu spacing, the 3D wheel image, and, via ``ui_scale``, ``icon_scale``
    and the centre font sizes, the icons, badges, submenu items and centre
    label themselves. Without that last group a bigger ring only spread the
    default-sized icons further apart (#134 follow-up).

    ``icon_scale`` (Settings > Icon size) multiplies the slice icons on top of
    that, so icons can grow or shrink without changing the ring.

    Returns the params unchanged (same object) when nothing is configured.
    """
    if outer_radius is None and inner_radius is None and icon_scale == 1.0:
        return params
    params = dict(params) if params else {}
    if outer_radius is not None:
        scale = outer_radius / MENU_RADIUS
        params["ring_outer"] = outer_radius
        params["icon_radius"] = ICON_ZONE_RADIUS * scale
        params["shadow_offset"] = SHADOW_OFFSET * scale
        params["submenu_extend"] = SUBMENU_EXTEND * scale
        # 3D-wheel themes draw a pre-rendered PNG as the ring/border
        # itself instead of a vector disc - scale it too, or it stays
        # the default size while the icons/hit-zone move past its edge.
        default_image_size = MENU_RADIUS * 2 + 10
        params["image_size"] = int(params.get("image_size", default_image_size) * scale)
        params["ui_scale"] = scale
        params["icon_scale"] = params.get("icon_scale", 1.0) * scale
        params["center_font_size"] = params.get("center_font_size", 11) * scale
        params["center_min_font_size"] = params.get("center_min_font_size", 7) * scale
    if inner_radius is not None:
        params["ring_inner"] = inner_radius
        params["center_radius"] = inner_radius
    if icon_scale != 1.0:
        params["icon_scale"] = params.get("icon_scale", 1.0) * icon_scale
    return params


def load_radial_image():
    """Load the radial wheel image.

    A wheel skin chosen in the Qt settings app (``radial.wheel``, independent
    of the colour theme) takes precedence; otherwise the colour theme's own 3D
    image, if any. Either way the user's ring geometry is layered on top.
    """
    global RADIAL_IMAGE, RADIAL_PARAMS, WHEEL_MATERIAL
    WHEEL_MATERIAL = None
    user_geometry = load_ring_geometry()
    outer_radius = user_geometry.get("outer_radius")
    inner_radius = user_geometry.get("inner_radius")
    icon_scale = user_geometry.get("icon_scale", 1.0)

    wheel_key = _config_wheel_key()
    if wheel_key:
        here = os.path.dirname(__file__)
        fname = f"wheel_{wheel_key}.png"
        for path in (
            os.path.join(here, "..", "settings-qt", "assets", "wheels", fname),
            os.path.join(here, "..", "assets", "wheels", fname),
            os.path.join(here, "assets", "wheels", fname),  # flat install (--user too)
            os.path.join("/usr/share/juhradial/assets/wheels", fname),
        ):
            if not os.path.exists(path):
                continue
            pixmap = QPixmap(path)
            if pixmap.isNull():
                continue
            # A wheel skin is only a material disc (radius 495 of 1024): the
            # Classic ring's own wedges, hover fill, icons and centre are
            # painted over it, so every skin has Classic's exact geometry.
            RADIAL_PARAMS = apply_ring_geometry(None, outer_radius, inner_radius, icon_scale)
            target = (RADIAL_PARAMS or {}).get("image_size", MENU_RADIUS * 2 + 10)
            RADIAL_IMAGE = None
            WHEEL_MATERIAL = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            print(f"Loaded wheel skin: {path}")
            return

    image_name = get_radial_image()
    RADIAL_PARAMS = get_radial_params()

    # Layer the user's configured ring geometry on top of the theme's own
    # radial_params (user config wins). A configured outer radius also scales
    # the icon zone, shadow spread, and submenu spacing by the same ratio, so
    # the whole ring resizes as one proportional set rather than piecemeal.
    RADIAL_PARAMS = apply_ring_geometry(RADIAL_PARAMS, outer_radius, inner_radius, icon_scale)

    if not image_name:
        RADIAL_IMAGE = None
        return

    # Search paths: development (../assets/radial-wheels/) and installed
    search_paths = [
        os.path.join(
            os.path.dirname(__file__), "..", "assets", "radial-wheels", image_name
        ),
        os.path.join(os.path.dirname(__file__), "assets", "radial-wheels", image_name),
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

# Domain fragments mapped to the bundled brand icons; anything else falls back
# to the painter's generic browser glyph.
_LINK_ICON_DOMAINS = [
    ("claude", "claude"),
    ("chatgpt", "chatgpt"),
    ("openai", "chatgpt"),
    ("gemini", "gemini"),
    ("perplexity", "perplexity"),
]


def _link_icon_for_url(url):
    """Pick a submenu icon id for a quick-link URL."""
    lowered = url.lower()
    for fragment, icon in _LINK_ICON_DOMAINS:
        if fragment in lowered:
            return icon
    return "browser"


def submenu_from_config(items):
    """Build a submenu from configured quick links, or None if unusable.

    ``items`` is the slice's ``submenu`` config list of dicts, each either
    a link (``{label, url}``) or an app (``{label, type: "exec", command,
    icon}``, "icon" holding an absolute path to a user-imported app icon).
    Invalid entries are skipped; an empty result returns None so the caller
    falls back to the default AI links.
    """
    if not isinstance(items, list):
        return None
    submenu = []
    for item in items:
        if len(submenu) == 4:
            break
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        if item.get("type") == "exec":
            command = str(item.get("command", "")).strip()
            if not command:
                continue
            icon_path = str(item.get("icon", ""))
            icon = icon_path if _is_user_icon_path(icon_path) else "browser"
            submenu.append((label, "exec", command, icon))
            continue
        url = str(item.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            continue
        submenu.append((label, "url", url, _link_icon_for_url(url)))
    return submenu or None

# Easy-Switch submenu labels: the mouse's own names for its computers, and this
# computer's local alias (Settings > Easy-Switch) for its slot. The tray learns
# them from the daemon and calls set_host_labels().
HOST_LABELS = {}


def easy_switch_label(i):
    return HOST_LABELS.get(i) or f"Host {i+1}"


def set_host_labels(names, current, alias=""):
    """Name the Easy-Switch submenu items after the computers (live)."""
    HOST_LABELS.clear()
    for i, name in enumerate(names or []):
        if name:
            HOST_LABELS[i] = name
    if alias and 0 <= current < 3:
        HOST_LABELS[current] = alias
    for i, item in enumerate(EASY_SWITCH_SUBMENU):
        EASY_SWITCH_SUBMENU[i] = (easy_switch_label(i),) + tuple(item[1:])


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

# =============================================================================
# ICON STYLE (Settings → Appearance → Icon style)
# =============================================================================
# "line" draws the 0.4.5 composed slice buttons and line glyphs, "classic" the
# 0.4.4 glossy buttons and PNG glyphs, "mono" flat single-colour glyphs only,
# "mono2" (Monochrome 2) the same with the filled PNG glyph set. The assets
# are the settings app's own (settings-qt/assets next to overlay/ in a
# checkout, /usr/share/juhradial/settings-qt/assets when installed), so the
# live wheel and the settings previews always agree.
ICON_STYLES = ("line", "classic", "mono", "mono2")
# ICON_STYLE itself is set by load_icon_style() further down, next to the
# other config readers, and refreshed every time the menu opens.

# Per-slice action ids and freedesktop icon names, kept in lockstep with
# ACTIONS by index: the button image is keyed by action id, the glyph by name.
DEFAULT_ACTION_IDS = ["play_pause", "new_note", "lock", "settings",
                      "screenshot", "emoji", "files", "ai"]
DEFAULT_ACTION_ICON_NAMES = [
    "media-playback-start-symbolic", "document-new-symbolic",
    "system-lock-screen-symbolic", "emblem-system-symbolic",
    "camera-photo-symbolic", "face-smile-symbolic",
    "folder-symbolic", "applications-science-symbolic",
]
ACTION_IDS = list(DEFAULT_ACTION_IDS)
ACTION_ICON_NAMES = list(DEFAULT_ACTION_ICON_NAMES)
_SLICE_BTN_CACHE = {}   # (style, action_id, size) -> scaled QPixmap or None
_GLYPH_CACHE = {}       # (style, name, size) -> white QPixmap or None


def _settings_assets_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (
        os.path.join(here, "..", "settings-qt", "assets"),  # dev checkout
        os.path.join(here, "settings-qt", "assets"),  # /usr/share/juhradial
    ):
        if os.path.isdir(d):
            return d
    return None


def _slice_keeps_own_icon(index):
    """True when the slice shows a user-picked app icon (an absolute path),
    which wins over any family button or glyph."""
    return index < len(ACTIONS) and _is_user_icon_path(ACTIONS[index][4])


def _slice_button_path(action_id, style):
    """Path of the slice button image for `action_id` in `style`, or None.

    Mirrors Theme.sliceButton in the settings app: "classic" prefers the
    0.4.4 orbs and falls back to the current set, "mono" and "mono2" have
    no buttons.
    """
    if style in ("mono", "mono2"):
        return None
    assets = _settings_assets_dir()
    if not assets:
        return None
    fname = f"btn_{action_id}.png"
    candidates = [os.path.join(assets, "slices", fname)]
    if style == "classic":
        candidates.insert(0, os.path.join(assets, "slices", "classic", fname))
    return next((c for c in candidates if os.path.exists(c)), None)


def get_slice_button(index, size):
    """QPixmap of the slice button for slice `index` at `size` px, or None."""
    if not 0 <= index < len(ACTION_IDS) or _slice_keeps_own_icon(index):
        return None
    action_id = ACTION_IDS[index]
    if not action_id:
        return None
    # play/pause shows the pause button while media is playing
    if action_id == "play_pause" and MEDIA_PLAYING:
        action_id = "pause"
    key = (ICON_STYLE, action_id, size)
    if key not in _SLICE_BTN_CACHE:
        path = _slice_button_path(action_id, ICON_STYLE)
        raw = QPixmap(path) if path else QPixmap()
        _SLICE_BTN_CACHE[key] = None if raw.isNull() else raw.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    return _SLICE_BTN_CACHE[key]


def _glyph_path(name, style):
    """Path of the family glyph `name` for `style`: the line SVG masters for
    "line" and "mono", the 0.4.4 PNG masters first for "classic", the
    Monochrome 2 PNGs first for "mono2". None when
    the family has no glyph of that name (the painter draws its own then)."""
    assets = _settings_assets_dir()
    if not assets or not name:
        return None
    icons = os.path.join(assets, "icons")
    candidates = [os.path.join(icons, "mono", f"{name}.svg"),
                  os.path.join(icons, "nav", f"{name}.svg")]
    if style == "classic":
        candidates.insert(0, os.path.join(icons, "classic", "mono", f"{name}.png"))
    elif style == "mono2":
        candidates.insert(0, os.path.join(icons, "mono2", f"{name}.png"))
    return next((c for c in candidates if os.path.exists(c)), None)


def get_style_glyph(index, size, color):
    """Tinted QPixmap of the family glyph for slice `index`, or None.

    White masters are cached per (style, name, size); each call tints a copy
    to `color`, so the hover brightness still applies.
    """
    if not 0 <= index < len(ACTION_ICON_NAMES) or _slice_keeps_own_icon(index):
        return None
    name = ACTION_ICON_NAMES[index]
    size = max(8, int(size))
    key = (ICON_STYLE, name, size)
    if key not in _GLYPH_CACHE:
        path = _glyph_path(name, ICON_STYLE)
        base = None
        if path and path.endswith(".svg"):
            base = _svg_to_pixmap(path, size)
        elif path:
            raw = QPixmap(path)
            if not raw.isNull():
                base = raw.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        _GLYPH_CACHE[key] = base
    base = _GLYPH_CACHE[key]
    if base is None:
        return None
    tinted = QPixmap(base.size())
    tinted.fill(Qt.GlobalColor.transparent)
    qp = QPainter(tinted)
    qp.drawPixmap(0, 0, base)
    qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    qp.fillRect(tinted.rect(), color)
    qp.end()
    return tinted


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

# Interactive screenshot via org.freedesktop.portal.Screenshot. Desktop-agnostic
# and the only reliable path on GNOME 42+, where the private Shell screenshot API
# is not exposed to third-party callers. The portal Screenshot call is async: it
# returns a Request handle and the result arrives on that Request's Response
# signal, and xdg-desktop-portal cancels the pending Request the moment the
# caller's bus connection drops. A one-shot `gdbus call` therefore dismisses the
# interactive picker as soon as gdbus exits, so route through portal_screenshot.py,
# which holds its bus connection open on a GLib main loop until Response arrives.
# Stored as an exec string so the overlay's existing shlex.split + Popen dispatch
# runs it unchanged; the helper path is resolved next to this module so it works
# from both a dev checkout and /usr/share/juhradial.
_PORTAL_SCREENSHOT_CMD = (
    "python3 " + os.path.join(os.path.dirname(__file__), "portal_screenshot.py")
)


def resolve_screenshot_command(configured_cmd: str) -> str:
    """Return a screenshot exec command suited to the current desktop.

    KDE keeps its configured command (spectacle). Elsewhere a command whose
    binary is not installed is replaced, and spectacle is additionally replaced
    on Wayland sessions (it can capture there only through KDE's own portal
    backend, so an installed spectacle still works on X11 and is kept there):
    COSMIC keeps cosmic-screenshot; every other portal desktop (GNOME included)
    uses the freedesktop Screenshot portal via portal_screenshot.py, with
    flameshot as a last resort. Any other configured command whose binary
    exists is left untouched so a user's own choice is preserved.
    """
    import importlib.util
    import shutil

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in desktop or "plasma" in desktop:
        return configured_cmd

    wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    parts = configured_cmd.split()
    base = parts[0] if parts else ""
    mismatched = (base == "spectacle" and wayland) or (
        base and shutil.which(base) is None
    )
    if not mismatched:
        return configured_cmd

    if "cosmic" in desktop and shutil.which("cosmic-screenshot"):
        return "cosmic-screenshot"
    # The helper needs PyGObject, not gdbus; gate on what it actually imports.
    if importlib.util.find_spec("gi") is not None:
        return _PORTAL_SCREENSHOT_CMD
    if shutil.which("flameshot"):
        return "flameshot gui"
    return configured_cmd


# The app whose profile is active (ActiveProfileChanged); its own slices,
# when profiles.json gives it some, replace the global ring.
ACTIVE_APP = ""


def app_slices(app, profiles_path=None):
    """The 8 slices of `app`'s own radial menu, or None."""
    import json
    from pathlib import Path

    if not app:
        return None
    path = profiles_path or Path.home() / ".config" / "juhradial" / "profiles.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            hw = (json.load(f).get("hardware") or {}).get(app) or {}
    except (OSError, ValueError, AttributeError):
        return None
    slices = hw.get("slices")
    return slices if isinstance(slices, list) and len(slices) == 8 else None


def load_actions_from_config():
    """Load radial menu actions from config file"""
    import json
    from pathlib import Path

    global ACTION_IDS, ACTION_ICON_NAMES
    ACTION_IDS = list(DEFAULT_ACTION_IDS)
    ACTION_ICON_NAMES = list(DEFAULT_ACTION_ICON_NAMES)
    config_path = Path.home() / ".config" / "juhradial" / "config.json"

    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            slices = app_slices(ACTIVE_APP) or config.get("radial_menu", {}).get("slices", [])
            easy_switch_enabled = config.get("radial_menu", {}).get(
                "easy_switch_shortcuts", False
            )

            # Build Easy-Switch submenu with OS-specific icons
            os_types = config.get("radial_menu", {}).get(
                "easy_switch_host_os", ["unknown", "unknown", "unknown"]
            )
            global EASY_SWITCH_SUBMENU
            EASY_SWITCH_SUBMENU = [
                (easy_switch_label(i), "easy_switch", str(i), f"os_{os_types[i] if i < len(os_types) else 'unknown'}")
                for i in range(3)
            ]

            if not slices:
                print("No radial_menu slices in config, using defaults")
                return DEFAULT_ACTIONS

            settings_constants._ = _
            settings_constants.refresh_translations(_)

            actions = []
            action_ids = []
            action_icon_names = []
            for i, slice_data in enumerate(slices):
                action_id = slice_data.get("action_id")
                label = slice_data.get("label", "Action")
                label = settings_constants.translate_radial_label(label, action_id)
                action_type = slice_data.get("type", "exec")
                command = slice_data.get("command", "")
                if action_id == "screenshot" and action_type == "exec":
                    command = resolve_screenshot_command(command)
                color = slice_data.get("color", "teal")
                gtk_icon = slice_data.get("icon", "application-x-executable-symbolic")

                # A user-imported app icon is stored as an absolute file path;
                # anything else is a symbolic icon name mapped to an internal ID.
                # The actual pixmap is rendered lazily at paint time (see
                # overlay_painting._draw_action_icon) - this runs at import
                # time, before QApplication exists, and QPixmap/QSvgRenderer
                # abort the process if constructed that early.
                if _is_user_icon_path(gtk_icon):
                    icon = gtk_icon
                else:
                    icon = ICON_NAME_MAP.get(gtk_icon, "settings")

                # Handle submenu type: configured quick links win, with the
                # default AI links as fallback for older configs.
                submenu = None
                if action_type == "submenu":
                    submenu = (
                        submenu_from_config(slice_data.get("submenu")) or AI_SUBMENU
                    )

                # Check if Easy-Switch shortcuts are enabled and this is the Emoji slot (index 5)
                if easy_switch_enabled and i == 5:
                    # Replace Emoji with Easy-Switch submenu
                    label = _("Easy-Switch")
                    action_type = "submenu"
                    icon = "easy_switch"
                    action_id = "easy_switch"
                    gtk_icon = "easy-switch"
                    submenu = EASY_SWITCH_SUBMENU
                    print(
                        "Easy-Switch shortcuts enabled - replacing Emoji with Easy-Switch submenu"
                    )

                actions.append((label, action_type, command, color, icon, submenu))
                action_ids.append(action_id)
                action_icon_names.append(gtk_icon)

            ACTION_IDS = action_ids
            ACTION_ICON_NAMES = action_icon_names
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
USER_ICONS = {}


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
    """Pre-render SVG to QPixmap at fixed size (avoids huge buffer allocations),
    centred with its aspect ratio kept (the Apple glyph is 814 x 1000)."""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QPixmap, QPainter, QImage
    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        return None
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    box = renderer.viewBoxF()
    scale = size / max(box.width(), box.height(), 1e-6)
    w, h = box.width() * scale, box.height() * scale
    renderer.render(p, QRectF((size - w) / 2, (size - h) / 2, w, h))
    p.end()
    return QPixmap.fromImage(img)


# Single-colour OS glyphs: painted in the ring's icon colour (white on dark
# rings, dark on the light ones) instead of the SVG's black.
MONO_OS_ICONS = {"os_macos", "os_ios", "os_unknown"}
# Icons that are a full disc of their own and fill the whole submenu circle.
DISC_OS_ICONS = {"os_linux"}
_TINTED = {}


def tinted_icon(name, pixmap, color):
    """`pixmap` in `color` (alpha kept), cached per icon and colour."""
    from PyQt6.QtGui import QPainter
    key = (name, color.rgba())
    if key not in _TINTED:
        out = pixmap.copy()
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(out.rect(), color)
        p.end()
        _TINTED[key] = out
    return _TINTED[key]


def _is_user_icon_path(path):
    """Plain filesystem check - safe to call at import time, unlike
    load_user_icon() which constructs Qt objects (see its docstring)."""
    return bool(path) and os.path.isabs(path) and os.path.exists(path)


def load_user_icon(path):
    """Load a user-imported app icon (absolute .svg/.png/... path) into
    USER_ICONS, keyed by its own path. Returns True if the icon is cached
    (already loaded or loaded now), False if it can't be read/rendered.

    Constructs QPixmap/QSvgRenderer, which abort the process if called
    before a QApplication exists - only call this after one is constructed
    (e.g. lazily at paint time), never from load_actions_from_config()."""
    if path in USER_ICONS:
        return True
    if not _is_user_icon_path(path):
        return False
    if path.lower().endswith(".svg"):
        pixmap = _svg_to_pixmap(path)
    else:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            pixmap = None
        else:
            pixmap = pixmap.scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
    if not pixmap:
        return False
    USER_ICONS[path] = pixmap
    return True


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
            pixmap = _svg_to_pixmap(path, 128)
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


def _requires_settings_relaunch():
    """Keep the legacy relaunch only outside KDE Plasma.

    KDE Plasma reliably presents an existing Gtk.Application through its
    single-instance D-Bus activation. Other desktops retain the established
    kill-and-relaunch behavior until they are verified separately.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return "kde" not in desktop and "plasma" not in desktop


def _settings_qt_script():
    """Path of the Qt/QML settings app when it is present and runnable, else None.

    The Qt app needs PyQt6's QML module and Qt 6.9 or newer at runtime
    (RectangularShadow, VectorImage); otherwise the GTK settings app stays the
    target, as in the launcher script. JUHRADIAL_SETTINGS=gtk forces the GTK app.
    """
    if os.environ.get("JUHRADIAL_SETTINGS") == "gtk":
        return None
    try:
        import PyQt6.QtQml  # noqa: F401
        from PyQt6.QtCore import qVersion
    except ImportError:
        return None
    if tuple(int(x) for x in qVersion().split(".")[:2]) < (6, 9):
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "..", "settings-qt", "main.py"),
        os.path.join(here, "settings-qt", "main.py"),  # flat install (--user too)
        "/usr/share/juhradial/settings-qt/main.py",
    ):
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
    return None


def open_settings():
    """Launch or refocus the settings app.

    Prefers the Qt/QML settings app, which owns its own single-instance gate
    (a second launch raises the existing window). The GTK dashboard is the
    fallback: KDE's single-instance activation raises an existing window
    immediately, other desktops retain the kill-and-relaunch behaviour, which
    works around focus restrictions observed on GNOME Wayland.
    """
    qt_script = _settings_qt_script()
    if qt_script:
        subprocess.Popen(
            ["python3", qt_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    settings_script = os.path.join(os.path.dirname(__file__), "settings_dashboard.py")

    if _requires_settings_relaunch():
        try:
            result = subprocess.run(
                ["busctl", "--user", "status", "org.kde.juhradialmx.settings"],
                capture_output=True, timeout=0.5,
            )
            if result.returncode == 0:
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


# =============================================================================
# MUTABLE GLOBALS (reassigned by on_show in main overlay)
# =============================================================================

# Load theme at startup
COLORS = load_theme()

# 3D radial image (loaded after QApplication creation)
RADIAL_IMAGE = None
RADIAL_PARAMS = None
# Wheel skin material drawn as the Classic ring's disc (None = palette colour)
WHEEL_MATERIAL = None

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


def load_icon_style():
    """Icon style from config.json: radial.icon_style, written by the settings
    app; older configs carry only radial.monochrome_icons (kept: true = mono,
    false = line). Neither key: mono2 (Monochrome 2), the default since 0.4.5."""
    radial = _config_radial_section()
    style = radial.get("icon_style")
    if style in ICON_STYLES:
        return style
    if "monochrome_icons" in radial:
        return "mono" if radial.get("monochrome_icons") else "line"
    return "mono2"


ICON_STYLE = load_icon_style()


def resolve_auto_fit(radial):
    """Settings > Radial menu > Automatic. Unset: on unless the user already
    chose a size (so an existing manual ring looks the same after upgrade)."""
    auto = radial.get("auto_fit")
    if isinstance(auto, bool):
        return auto
    return all(radial.get(k) is None for k in ("outer_radius", "inner_radius", "icon_scale"))


def load_ring_geometry():
    """Ring geometry from config.json radial.*.

    Returns {"outer_radius": int|None, "inner_radius": int|None,
    "icon_scale": float}. None means "use the theme/default radius". With
    Automatic on (radial.auto_fit) the manual values stay in the file but are
    ignored: the ring uses its defaults, which the overlay already scales to
    the monitor it opens on (compute_ring_scale). Mirrors
    settings_config.get_ring_geometry for the outer/inner keys (that module
    pulls in GTK4 and cannot be imported here).
    """
    radial = _config_radial_section()
    if resolve_auto_fit(radial):
        return {"outer_radius": None, "inner_radius": None, "icon_scale": 1.0}
    icon = radial.get("icon_scale")
    try:
        icon = max(ICON_SCALE_MIN, min(ICON_SCALE_MAX, float(icon)))
    except (TypeError, ValueError):
        icon = 1.0
    return {"outer_radius": radial.get("outer_radius"),
            "inner_radius": radial.get("inner_radius"),
            "icon_scale": icon}
