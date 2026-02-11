#!/usr/bin/env python3
"""
JuhRadial MX - Unified Theme System

Shared theme definitions for both the radial overlay and settings dashboard.
Themes affect both components when changed in settings.

SPDX-License-Identifier: GPL-3.0
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# =============================================================================
# THEME DEFINITIONS
# Each theme defines colors that work for both dark and light UIs
# =============================================================================
THEMES = {
    # =========================================================================
    # JUHRADIAL MX - Premium Default Theme (Vibrant Teal/Cyan)
    # This is the flagship theme matching the premium UI design
    # =========================================================================
    "juhradial-mx": {
        "name": "JuhRadial MX",
        "description": "Premium dark theme with vibrant cyan accents",
        "is_dark": True,
        "radial_image": None,
        "colors": {
            # Base colors - deep refined darks
            "crust": "#0a0c10",  # Deepest background
            "mantle": "#0f1117",  # Sidebar/panels
            "base": "#121418",  # Main content
            "surface0": "#1a1d24",  # Cards/elevated
            "surface1": "#242832",  # Hover states
            "surface2": "#2e3440",  # Active states
            "overlay0": "#404654",  # Muted elements
            "overlay1": "#525866",  # Placeholder text
            # Text colors
            "text": "#f0f4f8",  # Primary text
            "subtext1": "#c8d0dc",  # Secondary text
            "subtext0": "#9aa5b5",  # Muted text
            # Accent colors
            "accent": "#00d4ff",  # Primary accent - vibrant cyan
            "accent2": "#0abdc6",  # Secondary accent - teal
            "accent_dim": "#0891a8",  # Dimmed accent
            # Semantic colors
            "green": "#00e676",  # Success
            "yellow": "#ffd54f",  # Warning
            "red": "#ff5252",  # Error/danger
            "blue": "#4a9eff",  # Info
            "mauve": "#b388ff",  # Purple accent
            "pink": "#ff80ab",  # Pink accent
            "peach": "#ffab40",  # Orange accent
            "teal": "#0abdc6",  # Teal (same as accent2)
            "sapphire": "#00b4d8",  # Ocean blue
            "lavender": "#00d4ff",  # Maps to accent for compatibility
        },
    },
    # =========================================================================
    # CATPPUCCIN MOCHA - Authentic Catppuccin colors (lavender accent)
    # =========================================================================
    "catppuccin-mocha": {
        "name": "Catppuccin Mocha",
        "description": "Soothing pastel theme with lavender accents",
        "is_dark": True,
        "radial_image": None,
        "colors": {
            "crust": "#11111b",  # Authentic Catppuccin Mocha
            "mantle": "#181825",
            "base": "#1e1e2e",
            "surface0": "#313244",
            "surface1": "#45475a",
            "surface2": "#585b70",
            "overlay0": "#6c7086",
            "overlay1": "#7f849c",
            "text": "#cdd6f4",
            "subtext1": "#bac2de",
            "subtext0": "#a6adc8",
            "accent": "#b4befe",  # Lavender - signature Catppuccin accent
            "accent2": "#cba6f7",  # Mauve
            "accent_dim": "#9399b2",
            "green": "#a6e3a1",
            "yellow": "#f9e2af",
            "red": "#f38ba8",
            "blue": "#89b4fa",
            "mauve": "#cba6f7",
            "pink": "#f5c2e7",
            "peach": "#fab387",
            "teal": "#94e2d5",
            "sapphire": "#74c7ec",
            "lavender": "#b4befe",
        },
    },
    # =========================================================================
    # NORD - Arctic, bluish theme
    # =========================================================================
    "nord": {
        "name": "Nord",
        "description": "Arctic, north-bluish color palette",
        "is_dark": True,
        "radial_image": None,
        "colors": {
            "crust": "#2e3440",
            "mantle": "#3b4252",
            "base": "#434c5e",
            "surface0": "#4c566a",
            "surface1": "#5e6779",
            "surface2": "#6e7a8a",
            "overlay0": "#7b88a1",
            "overlay1": "#8892a8",
            "text": "#eceff4",
            "subtext1": "#e5e9f0",
            "subtext0": "#d8dee9",
            "accent": "#88c0d0",
            "accent2": "#8fbcbb",
            "accent_dim": "#6a9fb5",
            "green": "#a3be8c",
            "yellow": "#ebcb8b",
            "red": "#bf616a",
            "blue": "#81a1c1",
            "mauve": "#b48ead",
            "pink": "#b48ead",
            "peach": "#d08770",
            "teal": "#8fbcbb",
            "sapphire": "#88c0d0",
            "lavender": "#88c0d0",
        },
    },
    # =========================================================================
    # DRACULA - Dark theme with purple accents
    # =========================================================================
    "dracula": {
        "name": "Dracula",
        "description": "Dark theme with vibrant colors",
        "is_dark": True,
        "radial_image": None,
        "colors": {
            "crust": "#21222c",
            "mantle": "#282a36",
            "base": "#343746",
            "surface0": "#414458",
            "surface1": "#4e5268",
            "surface2": "#5a5e78",
            "overlay0": "#6c7093",
            "overlay1": "#7e82a8",
            "text": "#f8f8f2",
            "subtext1": "#e2e2d8",
            "subtext0": "#bfbfb4",
            "accent": "#bd93f9",
            "accent2": "#ff79c6",
            "accent_dim": "#9a6dd7",
            "green": "#50fa7b",
            "yellow": "#f1fa8c",
            "red": "#ff5555",
            "blue": "#8be9fd",
            "mauve": "#bd93f9",
            "pink": "#ff79c6",
            "peach": "#ffb86c",
            "teal": "#50fa7b",
            "sapphire": "#8be9fd",
            "lavender": "#bd93f9",
        },
    },
    # =========================================================================
    # CATPPUCCIN LATTE - Light theme
    # =========================================================================
    "catppuccin-latte": {
        "name": "Catppuccin Latte",
        "description": "Soothing pastel light theme",
        "is_dark": False,
        "radial_image": None,
        "colors": {
            "crust": "#dce0e8",
            "mantle": "#e6e9ef",
            "base": "#eff1f5",
            "surface0": "#ccd0da",
            "surface1": "#bcc0cc",
            "surface2": "#acb0be",
            "overlay0": "#9ca0b0",
            "overlay1": "#8c8fa1",
            "text": "#4c4f69",
            "subtext1": "#5c5f77",
            "subtext0": "#6c6f85",
            "accent": "#1e66f5",
            "accent2": "#179299",
            "accent_dim": "#1558c4",
            "green": "#40a02b",
            "yellow": "#df8e1d",
            "red": "#d20f39",
            "blue": "#1e66f5",
            "mauve": "#8839ef",
            "pink": "#ea76cb",
            "peach": "#fe640b",
            "teal": "#179299",
            "sapphire": "#209fb5",
            "lavender": "#7287fd",
        },
    },
    # =========================================================================
    # GITHUB LIGHT
    # =========================================================================
    "github-light": {
        "name": "GitHub Light",
        "description": "Clean light theme inspired by GitHub",
        "is_dark": False,
        "radial_image": None,
        "colors": {
            "crust": "#f0f0f0",
            "mantle": "#f6f8fa",
            "base": "#ffffff",
            "surface0": "#f6f8fa",
            "surface1": "#eaeef2",
            "surface2": "#d8dee4",
            "overlay0": "#c8cdd3",
            "overlay1": "#afb8c1",
            "text": "#24292f",
            "subtext1": "#57606a",
            "subtext0": "#6e7781",
            "accent": "#0969da",
            "accent2": "#0550ae",
            "accent_dim": "#0747a6",
            "green": "#1a7f37",
            "yellow": "#bf8700",
            "red": "#cf222e",
            "blue": "#0969da",
            "mauve": "#8250df",
            "pink": "#bf3989",
            "peach": "#bf5700",
            "teal": "#0d7d76",
            "sapphire": "#00838b",
            "lavender": "#8250df",
        },
    },
    # =========================================================================
    # SOLARIZED LIGHT
    # =========================================================================
    "solarized-light": {
        "name": "Solarized Light",
        "description": "Precision colors for machines and people",
        "is_dark": False,
        "radial_image": None,
        "colors": {
            "crust": "#eee8d5",
            "mantle": "#fdf6e3",
            "base": "#fdf6e3",
            "surface0": "#eee8d5",
            "surface1": "#e0dcc8",
            "surface2": "#d2cdb9",
            "overlay0": "#93a1a1",
            "overlay1": "#839496",
            "text": "#657b83",
            "subtext1": "#586e75",
            "subtext0": "#839496",
            "accent": "#268bd2",
            "accent2": "#2aa198",
            "accent_dim": "#1a6ba0",
            "green": "#859900",
            "yellow": "#b58900",
            "red": "#dc322f",
            "blue": "#268bd2",
            "mauve": "#6c71c4",
            "pink": "#d33682",
            "peach": "#cb4b16",
            "teal": "#2aa198",
            "sapphire": "#2aa198",
            "lavender": "#6c71c4",
        },
    },
    # =========================================================================
    # 3D THEMES - Use pre-rendered radial wheel images
    # Pearl Blossom (3D) - Soft rose-gold with warm pearl tones
    "3d-blossom": {
        "name": "Pearl Blossom (3D)",
        "description": "Elegant pearl radial wheel with blossom pink tones",
        "is_dark": True,
        "radial_image": "radialwheel2.png",
        "radial_params": {
            "image_size": 310,
            "icon_radius": 101,
            "ring_inner": 58,
            "ring_outer": 144,
            "icon_scale": 1.0,
            "icon_color": (255, 255, 255),
            "icon_shadow_alpha": 90,
            "highlight_fill": (232, 160, 184, 40),
            "highlight_border": (240, 200, 220, 80),
            "hover_glow": (232, 180, 200, 50),
            # Center zone styling
            "center_bg": (30, 20, 28, 220),
            "center_border": (200, 160, 180, 140),
            "center_border_width": 2.0,
            "center_text_color": (220, 200, 210),
            "icon_bold": 1.4,
        },
        "colors": {
            "crust": "#0e0a0c",
            "mantle": "#161014",
            "base": "#1c1418",
            "surface0": "#2a1e24",
            "surface1": "#362832",
            "surface2": "#443440",
            "overlay0": "#5e4858",
            "overlay1": "#785e70",
            "text": "#f4e8ee",
            "subtext1": "#dcc0d0",
            "subtext0": "#a88898",
            "accent": "#e8a0b8",
            "accent2": "#d088a0",
            "accent_dim": "#b06880",
            "green": "#a0c890",
            "yellow": "#d8c888",
            "red": "#e07070",
            "blue": "#88a8d0",
            "mauve": "#c090d0",
            "pink": "#e8a0b8",
            "peach": "#d8a888",
            "teal": "#80b8b0",
            "sapphire": "#88a8d0",
            "lavender": "#c090d0",
        },
    },
    # Neon Sci-Fi (3D) - Electric cyan/magenta cyberpunk glow
    "3d-neon": {
        "name": "Neon Sci-Fi (3D)",
        "description": "Cyberpunk neon radial wheel with electric glow",
        "is_dark": True,
        "radial_image": "radialwheel3.png",
        "radial_params": {
            "image_size": 310,
            "icon_radius": 101,
            "ring_inner": 58,
            "ring_outer": 144,
            "icon_scale": 1.0,
            "icon_color": (200, 240, 255),
            "icon_shadow_alpha": 0,
            "highlight_fill": (0, 232, 255, 35),
            "highlight_border": (0, 232, 255, 100),
            "hover_glow": (0, 232, 255, 70),
            # Center zone styling
            "center_bg": (8, 12, 22, 235),
            "center_border": (0, 232, 255, 200),
            "center_border_width": 2.0,
            "center_text_color": (0, 210, 240),
            "icon_bold": 1.4,
        },
        "colors": {
            "crust": "#06080e",
            "mantle": "#0a0e18",
            "base": "#0e1220",
            "surface0": "#141a2e",
            "surface1": "#1c243c",
            "surface2": "#242e4a",
            "overlay0": "#364068",
            "overlay1": "#485580",
            "text": "#e0f0ff",
            "subtext1": "#b0c8e8",
            "subtext0": "#7090b8",
            "accent": "#00e8ff",
            "accent2": "#e040ff",
            "accent_dim": "#0098b0",
            "green": "#00ff88",
            "yellow": "#ffdd00",
            "red": "#ff3060",
            "blue": "#00b8ff",
            "mauve": "#e040ff",
            "pink": "#ff60c0",
            "peach": "#ff8840",
            "teal": "#00e8d0",
            "sapphire": "#00b8ff",
            "lavender": "#b080ff",
        },
    },
    # Dark Ember (3D) - Dark elegance with golden accents
    "3d-pastel": {
        "name": "Dark Ember (3D)",
        "description": "Dark elegant radial wheel with golden accents",
        "is_dark": True,
        "radial_image": "radialwheel4.png",
        "radial_params": {
            "image_size": 310,
            "icon_radius": 101,
            "ring_inner": 58,
            "ring_outer": 144,
            "icon_scale": 1.0,
            "icon_color": (255, 215, 160),
            "icon_shadow_alpha": 90,
            "highlight_fill": (255, 130, 60, 45),
            "highlight_border": (255, 170, 90, 95),
            "hover_glow": (255, 140, 70, 70),
            # Center zone styling
            "center_bg": (26, 16, 12, 235),
            "center_border": (220, 140, 70, 170),
            "center_border_width": 2.0,
            "center_text_color": (240, 200, 140),
            "icon_bold": 1.4,
        },
        "colors": {
            "crust": "#0a0a08",
            "mantle": "#121210",
            "base": "#1a1814",
            "surface0": "#242018",
            "surface1": "#2e2a20",
            "surface2": "#3a3428",
            "overlay0": "#504838",
            "overlay1": "#686050",
            "text": "#f0e8d8",
            "subtext1": "#d0c8b0",
            "subtext0": "#988e78",
            "accent": "#d4a840",
            "accent2": "#c09030",
            "accent_dim": "#a07828",
            "green": "#80b860",
            "yellow": "#d4a840",
            "red": "#c86050",
            "blue": "#6898c0",
            "mauve": "#a080b0",
            "pink": "#c88890",
            "peach": "#d8a060",
            "teal": "#60a898",
            "sapphire": "#6898c0",
            "lavender": "#a080b0",
        },
    },
    # Golden Classic (3D) - Ornamental with golden filigree
    "3d-crystal": {
        "name": "Golden Classic (3D)",
        "description": "Ornamental radial wheel with golden filigree",
        "is_dark": True,
        "radial_image": "radialwheel5.png",
        "radial_params": {
            "image_size": 310,
            "icon_radius": 101,
            "ring_inner": 58,
            "ring_outer": 144,
            "icon_scale": 1.0,
            "icon_color": (255, 235, 190),
            "icon_shadow_alpha": 85,
            "highlight_fill": (230, 190, 110, 45),
            "highlight_border": (255, 220, 150, 100),
            "hover_glow": (255, 210, 130, 70),
            # Center zone styling
            "center_bg": (22, 18, 12, 235),
            "center_border": (230, 190, 110, 180),
            "center_border_width": 2.0,
            "center_text_color": (245, 215, 160),
            "icon_bold": 1.4,
        },
        "colors": {
            "crust": "#0a0808",
            "mantle": "#121010",
            "base": "#181614",
            "surface0": "#221e1a",
            "surface1": "#2c2820",
            "surface2": "#38322a",
            "overlay0": "#4e4638",
            "overlay1": "#665e50",
            "text": "#f0e8d0",
            "subtext1": "#d0c8a8",
            "subtext0": "#988e70",
            "accent": "#d4a840",
            "accent2": "#c09030",
            "accent_dim": "#a07828",
            "green": "#78b858",
            "yellow": "#d4a840",
            "red": "#c85848",
            "blue": "#6090b8",
            "mauve": "#a07898",
            "pink": "#c08080",
            "peach": "#d89850",
            "teal": "#58a090",
            "sapphire": "#6090b8",
            "lavender": "#a07898",
        },
    },
}

# Default theme
DEFAULT_THEME = "juhradial-mx"


def load_theme_name() -> str:
    """Load theme name from config file"""
    config_path = Path.home() / ".config" / "juhradial" / "config.json"
    theme_name = DEFAULT_THEME

    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                theme_name = config.get("theme", DEFAULT_THEME)
    except Exception as e:
        print(f"Could not load theme from config: {e}")

    # Handle 'system' theme - default to juhradial-mx
    if theme_name == "system":
        theme_name = DEFAULT_THEME

    if theme_name not in THEMES:
        print(f"Unknown theme '{theme_name}', using {DEFAULT_THEME}")
        theme_name = DEFAULT_THEME

    return theme_name


def get_theme(theme_name: Optional[str] = None) -> Dict[str, Any]:
    """Get theme definition by name"""
    if theme_name is None:
        theme_name = load_theme_name()
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def get_colors(theme_name: Optional[str] = None) -> Dict[str, Any]:
    """Get just the colors dict from a theme"""
    theme = get_theme(theme_name)
    return theme["colors"]


def get_theme_list() -> List[Tuple[str, str, str]]:
    """Get list of available themes with their display names"""
    return [(key, theme["name"], theme["description"]) for key, theme in THEMES.items()]


def get_radial_image(theme_name: Optional[str] = None) -> Optional[str]:
    """Get radial image filename for a theme (None if vector theme)"""
    theme = get_theme(theme_name)
    return theme.get("radial_image", None)


def get_radial_params(theme_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get per-theme radial rendering parameters (None if vector theme)"""
    theme = get_theme(theme_name)
    return theme.get("radial_params", None)


def is_dark_theme(theme_name: Optional[str] = None) -> bool:
    """Check if theme is dark or light"""
    theme = get_theme(theme_name)
    return theme.get("is_dark", True)
