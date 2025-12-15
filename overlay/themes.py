#!/usr/bin/env python3
"""
JuhRadial MX - Unified Theme System

Shared theme definitions for both the radial overlay and settings dashboard.
Themes affect both components when changed in settings.

SPDX-License-Identifier: GPL-3.0
"""

import json
from pathlib import Path

# =============================================================================
# THEME DEFINITIONS
# Each theme defines colors that work for both dark and light UIs
# =============================================================================
THEMES = {
    # =========================================================================
    # JUHRADIAL MX - Premium Default Theme (Vibrant Teal/Cyan)
    # This is the flagship theme matching the premium UI design
    # =========================================================================
    'juhradial-mx': {
        'name': 'JuhRadial MX',
        'description': 'Premium dark theme with vibrant cyan accents',
        'is_dark': True,
        'colors': {
            # Base colors - deep refined darks
            'crust':     '#0a0c10',   # Deepest background
            'mantle':    '#0f1117',   # Sidebar/panels
            'base':      '#121418',   # Main content
            'surface0':  '#1a1d24',   # Cards/elevated
            'surface1':  '#242832',   # Hover states
            'surface2':  '#2e3440',   # Active states
            'overlay0':  '#404654',   # Muted elements
            'overlay1':  '#525866',   # Placeholder text

            # Text colors
            'text':      '#f0f4f8',   # Primary text
            'subtext1':  '#c8d0dc',   # Secondary text
            'subtext0':  '#9aa5b5',   # Muted text

            # Accent colors
            'accent':    '#00d4ff',   # Primary accent - vibrant cyan
            'accent2':   '#0abdc6',   # Secondary accent - teal
            'accent_dim':'#0891a8',   # Dimmed accent

            # Semantic colors
            'green':     '#00e676',   # Success
            'yellow':    '#ffd54f',   # Warning
            'red':       '#ff5252',   # Error/danger
            'blue':      '#4a9eff',   # Info
            'mauve':     '#b388ff',   # Purple accent
            'pink':      '#ff80ab',   # Pink accent
            'peach':     '#ffab40',   # Orange accent
            'teal':      '#0abdc6',   # Teal (same as accent2)
            'sapphire':  '#00b4d8',   # Ocean blue
            'lavender':  '#00d4ff',   # Maps to accent for compatibility
        }
    },

    # =========================================================================
    # CATPPUCCIN MOCHA - Authentic Catppuccin colors (lavender accent)
    # =========================================================================
    'catppuccin-mocha': {
        'name': 'Catppuccin Mocha',
        'description': 'Soothing pastel theme with lavender accents',
        'is_dark': True,
        'colors': {
            'crust':     '#11111b',   # Authentic Catppuccin Mocha
            'mantle':    '#181825',
            'base':      '#1e1e2e',
            'surface0':  '#313244',
            'surface1':  '#45475a',
            'surface2':  '#585b70',
            'overlay0':  '#6c7086',
            'overlay1':  '#7f849c',
            'text':      '#cdd6f4',
            'subtext1':  '#bac2de',
            'subtext0':  '#a6adc8',
            'accent':    '#b4befe',   # Lavender - signature Catppuccin accent
            'accent2':   '#cba6f7',   # Mauve
            'accent_dim':'#9399b2',
            'green':     '#a6e3a1',
            'yellow':    '#f9e2af',
            'red':       '#f38ba8',
            'blue':      '#89b4fa',
            'mauve':     '#cba6f7',
            'pink':      '#f5c2e7',
            'peach':     '#fab387',
            'teal':      '#94e2d5',
            'sapphire':  '#74c7ec',
            'lavender':  '#b4befe',
        }
    },

    # =========================================================================
    # NORD - Arctic, bluish theme
    # =========================================================================
    'nord': {
        'name': 'Nord',
        'description': 'Arctic, north-bluish color palette',
        'is_dark': True,
        'colors': {
            'crust':     '#2e3440',
            'mantle':    '#3b4252',
            'base':      '#434c5e',
            'surface0':  '#4c566a',
            'surface1':  '#5e6779',
            'surface2':  '#6e7a8a',
            'overlay0':  '#7b88a1',
            'overlay1':  '#8892a8',
            'text':      '#eceff4',
            'subtext1':  '#e5e9f0',
            'subtext0':  '#d8dee9',
            'accent':    '#88c0d0',
            'accent2':   '#8fbcbb',
            'accent_dim':'#6a9fb5',
            'green':     '#a3be8c',
            'yellow':    '#ebcb8b',
            'red':       '#bf616a',
            'blue':      '#81a1c1',
            'mauve':     '#b48ead',
            'pink':      '#b48ead',
            'peach':     '#d08770',
            'teal':      '#8fbcbb',
            'sapphire':  '#88c0d0',
            'lavender':  '#88c0d0',
        }
    },

    # =========================================================================
    # DRACULA - Dark theme with purple accents
    # =========================================================================
    'dracula': {
        'name': 'Dracula',
        'description': 'Dark theme with vibrant colors',
        'is_dark': True,
        'colors': {
            'crust':     '#21222c',
            'mantle':    '#282a36',
            'base':      '#343746',
            'surface0':  '#414458',
            'surface1':  '#4e5268',
            'surface2':  '#5a5e78',
            'overlay0':  '#6c7093',
            'overlay1':  '#7e82a8',
            'text':      '#f8f8f2',
            'subtext1':  '#e2e2d8',
            'subtext0':  '#bfbfb4',
            'accent':    '#bd93f9',
            'accent2':   '#ff79c6',
            'accent_dim':'#9a6dd7',
            'green':     '#50fa7b',
            'yellow':    '#f1fa8c',
            'red':       '#ff5555',
            'blue':      '#8be9fd',
            'mauve':     '#bd93f9',
            'pink':      '#ff79c6',
            'peach':     '#ffb86c',
            'teal':      '#50fa7b',
            'sapphire':  '#8be9fd',
            'lavender':  '#bd93f9',
        }
    },

    # =========================================================================
    # CATPPUCCIN LATTE - Light theme
    # =========================================================================
    'catppuccin-latte': {
        'name': 'Catppuccin Latte',
        'description': 'Soothing pastel light theme',
        'is_dark': False,
        'colors': {
            'crust':     '#dce0e8',
            'mantle':    '#e6e9ef',
            'base':      '#eff1f5',
            'surface0':  '#ccd0da',
            'surface1':  '#bcc0cc',
            'surface2':  '#acb0be',
            'overlay0':  '#9ca0b0',
            'overlay1':  '#8c8fa1',
            'text':      '#4c4f69',
            'subtext1':  '#5c5f77',
            'subtext0':  '#6c6f85',
            'accent':    '#1e66f5',
            'accent2':   '#179299',
            'accent_dim':'#1558c4',
            'green':     '#40a02b',
            'yellow':    '#df8e1d',
            'red':       '#d20f39',
            'blue':      '#1e66f5',
            'mauve':     '#8839ef',
            'pink':      '#ea76cb',
            'peach':     '#fe640b',
            'teal':      '#179299',
            'sapphire':  '#209fb5',
            'lavender':  '#7287fd',
        }
    },

    # =========================================================================
    # GITHUB LIGHT
    # =========================================================================
    'github-light': {
        'name': 'GitHub Light',
        'description': 'Clean light theme inspired by GitHub',
        'is_dark': False,
        'colors': {
            'crust':     '#f0f0f0',
            'mantle':    '#f6f8fa',
            'base':      '#ffffff',
            'surface0':  '#f6f8fa',
            'surface1':  '#eaeef2',
            'surface2':  '#d8dee4',
            'overlay0':  '#c8cdd3',
            'overlay1':  '#afb8c1',
            'text':      '#24292f',
            'subtext1':  '#57606a',
            'subtext0':  '#6e7781',
            'accent':    '#0969da',
            'accent2':   '#0550ae',
            'accent_dim':'#0747a6',
            'green':     '#1a7f37',
            'yellow':    '#bf8700',
            'red':       '#cf222e',
            'blue':      '#0969da',
            'mauve':     '#8250df',
            'pink':      '#bf3989',
            'peach':     '#bf5700',
            'teal':      '#0d7d76',
            'sapphire':  '#00838b',
            'lavender':  '#8250df',
        }
    },

    # =========================================================================
    # SOLARIZED LIGHT
    # =========================================================================
    'solarized-light': {
        'name': 'Solarized Light',
        'description': 'Precision colors for machines and people',
        'is_dark': False,
        'colors': {
            'crust':     '#eee8d5',
            'mantle':    '#fdf6e3',
            'base':      '#fdf6e3',
            'surface0':  '#eee8d5',
            'surface1':  '#e0dcc8',
            'surface2':  '#d2cdb9',
            'overlay0':  '#93a1a1',
            'overlay1':  '#839496',
            'text':      '#657b83',
            'subtext1':  '#586e75',
            'subtext0':  '#839496',
            'accent':    '#268bd2',
            'accent2':   '#2aa198',
            'accent_dim':'#1a6ba0',
            'green':     '#859900',
            'yellow':    '#b58900',
            'red':       '#dc322f',
            'blue':      '#268bd2',
            'mauve':     '#6c71c4',
            'pink':      '#d33682',
            'peach':     '#cb4b16',
            'teal':      '#2aa198',
            'sapphire':  '#2aa198',
            'lavender':  '#6c71c4',
        }
    },
}

# Default theme
DEFAULT_THEME = 'juhradial-mx'


def load_theme_name() -> str:
    """Load theme name from config file"""
    config_path = Path.home() / ".config" / "juhradial" / "config.json"
    theme_name = DEFAULT_THEME

    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                theme_name = config.get('theme', DEFAULT_THEME)
    except Exception as e:
        print(f"Could not load theme from config: {e}")

    # Handle 'system' theme - default to juhradial-mx
    if theme_name == 'system':
        theme_name = DEFAULT_THEME

    if theme_name not in THEMES:
        print(f"Unknown theme '{theme_name}', using {DEFAULT_THEME}")
        theme_name = DEFAULT_THEME

    return theme_name


def get_theme(theme_name: str = None) -> dict:
    """Get theme definition by name"""
    if theme_name is None:
        theme_name = load_theme_name()
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def get_colors(theme_name: str = None) -> dict:
    """Get just the colors dict from a theme"""
    theme = get_theme(theme_name)
    return theme['colors']


def get_theme_list() -> list:
    """Get list of available themes with their display names"""
    return [(key, theme['name'], theme['description']) for key, theme in THEMES.items()]


def is_dark_theme(theme_name: str = None) -> bool:
    """Check if theme is dark or light"""
    theme = get_theme(theme_name)
    return theme.get('is_dark', True)
