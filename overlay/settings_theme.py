#!/usr/bin/env python3
"""
JuhRadial MX - Theme System

Theme loading and CSS generation for the settings dashboard.
Supports dark and light themes with dynamic accent colors.

SPDX-License-Identifier: GPL-3.0
"""

from themes import get_colors, is_dark_theme


# =============================================================================
# THEME LOADING
# =============================================================================
def load_colors():
    """Load colors from the current theme with glow color computed"""
    colors = get_colors().copy()
    # Add computed glow color based on accent
    accent = colors.get('accent', '#00d4ff')
    # Parse hex to RGB for glow
    r = int(accent[1:3], 16)
    g = int(accent[3:5], 16)
    b = int(accent[5:7], 16)
    colors['accent_glow'] = f'rgba({r}, {g}, {b}, 0.4)'
    colors['accent_glow_light'] = f'rgba({r}, {g}, {b}, 0.15)'
    # Add missing legacy colors if needed
    colors.setdefault('maroon', '#ff8a80')
    colors.setdefault('flamingo', '#f8bbd9')
    colors.setdefault('rosewater', '#fce4ec')
    # Add is_dark flag for CSS generation
    colors['is_dark'] = is_dark_theme()
    return colors

# Load initial colors
COLORS = load_colors()
IS_DARK_THEME = COLORS.get('is_dark', True)

# =============================================================================
# WINDOW CONFIGURATION
# =============================================================================
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
WINDOW_MIN_WIDTH = 400  # Can be narrow - content scrolls horizontally
WINDOW_MIN_HEIGHT = 300


# =============================================================================
# CSS STYLESHEET - ADAPTIVE THEME SYSTEM
# Supports both dark and light themes with proper color handling
# =============================================================================
def generate_css():
    """Generate CSS with current theme colors - call when theme changes"""
    is_dark = COLORS.get('is_dark', True)

    # Parse accent colors to RGB for dynamic opacity values
    accent = COLORS.get('accent', '#00d4ff')
    accent2 = COLORS.get('accent2', '#0abdc6')
    ar, ag, ab = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    a2r, a2g, a2b = int(accent2[1:3], 16), int(accent2[3:5], 16), int(accent2[5:7], 16)

    # Dynamic accent opacity variants
    accent_08 = f'rgba({ar}, {ag}, {ab}, 0.08)'
    accent_10 = f'rgba({ar}, {ag}, {ab}, 0.1)'
    accent_12 = f'rgba({ar}, {ag}, {ab}, 0.12)'
    accent_15 = f'rgba({ar}, {ag}, {ab}, 0.15)'
    accent_20 = f'rgba({ar}, {ag}, {ab}, 0.2)'
    accent_25 = f'rgba({ar}, {ag}, {ab}, 0.25)'
    accent_30 = f'rgba({ar}, {ag}, {ab}, 0.3)'
    accent_35 = f'rgba({ar}, {ag}, {ab}, 0.35)'
    accent_40 = f'rgba({ar}, {ag}, {ab}, 0.4)'
    accent_50 = f'rgba({ar}, {ag}, {ab}, 0.5)'

    # Dynamic accent2 opacity variants
    accent2_05 = f'rgba({a2r}, {a2g}, {a2b}, 0.05)'
    accent2_08 = f'rgba({a2r}, {a2g}, {a2b}, 0.08)'
    accent2_10 = f'rgba({a2r}, {a2g}, {a2b}, 0.1)'
    accent2_15 = f'rgba({a2r}, {a2g}, {a2b}, 0.15)'

    # Theme-aware color adjustments
    if is_dark:
        # Dark theme: use dark backgrounds with light accents
        shadow_color = 'rgba(0, 0, 0, 0.4)'
        shadow_color_strong = 'rgba(0, 0, 0, 0.5)'
        hover_bg = f"linear-gradient(135deg, {COLORS['surface1']} 0%, {COLORS['surface0']} 100%)"
        card_bg = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['base']} 100%)"
        border_subtle = 'rgba(255, 255, 255, 0.1)'
        border_very_subtle = 'rgba(255, 255, 255, 0.05)'
        border_faint = 'rgba(255, 255, 255, 0.03)'
        text_on_accent = COLORS['crust']
        elevated_bg = f"linear-gradient(135deg, rgba(26, 29, 36, 0.95) 0%, rgba(18, 20, 24, 0.9) 100%)"
        elevated_bg_hover = f"linear-gradient(135deg, rgba(36, 40, 50, 0.5) 0%, rgba(26, 29, 36, 0.3) 100%)"
        tooltip_bg = 'linear-gradient(135deg, rgba(26, 29, 36, 0.98) 0%, rgba(18, 20, 24, 0.95) 100%)'
    else:
        # Light theme: use light backgrounds with darker accents
        shadow_color = 'rgba(0, 0, 0, 0.1)'
        shadow_color_strong = 'rgba(0, 0, 0, 0.15)'
        hover_bg = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['surface1']} 100%)"
        card_bg = f"linear-gradient(135deg, {COLORS['base']} 0%, {COLORS['mantle']} 100%)"
        border_subtle = 'rgba(0, 0, 0, 0.1)'
        border_very_subtle = 'rgba(0, 0, 0, 0.06)'
        border_faint = 'rgba(0, 0, 0, 0.04)'
        text_on_accent = '#ffffff'
        elevated_bg = f"linear-gradient(135deg, {COLORS['base']} 0%, {COLORS['surface0']} 100%)"
        elevated_bg_hover = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['surface1']} 100%)"
        tooltip_bg = f"linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['mantle']} 100%)"

    return f"""
/* ============================================
   GLOBAL TRANSITIONS & ANIMATIONS
   ============================================ */
@keyframes pulse-glow {{
    0%, 100% {{ box-shadow: 0 0 20px {COLORS['accent_glow']}; }}
    50% {{ box-shadow: 0 0 35px {COLORS['accent_glow']}; }}
}}

@keyframes subtle-pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.85; }}
}}

@keyframes slide-in {{
    from {{ opacity: 0; transform: translateX(20px); }}
    to {{ opacity: 1; transform: translateX(0); }}
}}

/* ============================================
   MAIN WINDOW
   ============================================ */
window.settings-window {{
    background: linear-gradient(180deg, {COLORS['crust']} 0%, {COLORS['mantle']} 100%);
}}

/* ============================================
   HEADER BAR - Premium Glass Effect
   ============================================ */
.header-area {{
    background: {COLORS['mantle']};
    padding: 18px 28px;
    border-bottom: 1px solid {border_subtle};
    box-shadow: 0 4px 24px {shadow_color};
}}

.device-title {{
    font-size: 26px;
    font-weight: 700;
    color: {COLORS['text']};
    letter-spacing: 0.5px;
}}

.add-app-btn {{
    background: {COLORS['surface0']};
    color: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    border-radius: 10px;
    padding: 10px 20px;
    font-weight: 600;
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.add-app-btn:hover {{
    background: {COLORS['accent']};
    color: {text_on_accent};
    box-shadow: 0 4px 20px {COLORS['accent_glow']};
    transform: translateY(-1px);
}}

/* ============================================
   SIDEBAR NAVIGATION - Sleek & Modern
   ============================================ */
.sidebar {{
    background: {COLORS['mantle']};
    padding: 16px 10px 12px 10px;
    min-width: 230px;
    border-right: 1px solid {border_subtle};
    border-radius: 14px;
    box-shadow: 4px 0 24px {shadow_color};
}}

.nav-item {{
    padding: 16px 18px;
    border-radius: 12px;
    margin: 4px 0;
    color: {COLORS['subtext0']};
    font-weight: 500;
    font-size: 13px;
    letter-spacing: 0.3px;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid transparent;
}}

.nav-item:hover {{
    background: {hover_bg};
    color: {COLORS['text']};
    border-color: {COLORS['accent_glow_light']};
    transform: translateX(4px);
    box-shadow: 0 4px 16px {shadow_color};
}}

.nav-item.active {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    font-weight: 600;
    box-shadow: 0 4px 20px {COLORS['accent_glow']};
    border-color: transparent;
}}

.nav-item.active:hover {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    transform: translateX(4px);
    box-shadow: 0 6px 28px {COLORS['accent_glow']};
}}

/* ============================================
   MAIN CONTENT AREA
   ============================================ */
.content-area {{
    background: {COLORS['base']};
}}

/* ============================================
   MOUSE VISUALIZATION AREA
   ============================================ */
.mouse-area {{
    background: radial-gradient(ellipse at center, {COLORS['surface0']} 0%, {COLORS['base']} 70%);
    padding: 40px;
}}

/* ============================================
   BUTTON LABELS ON MOUSE - Premium Floating Tags
   ============================================ */
.button-label {{
    background: {card_bg};
    color: {COLORS['text']};
    padding: 10px 16px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    box-shadow: 0 4px 20px {shadow_color_strong};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid {border_subtle};
}}

.button-label:hover {{
    background: {COLORS['surface1']};
    border-color: {COLORS['accent']};
    box-shadow: 0 6px 28px {COLORS['accent_glow']};
    color: {COLORS['accent']};
}}

.button-label.highlighted {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    box-shadow: 0 6px 28px {COLORS['accent_glow']};
    border-color: transparent;
}}

/* ============================================
   SETTINGS CARDS - Glassmorphism Effect
   ============================================ */
.settings-card {{
    background: {card_bg};
    border-radius: 16px;
    padding: 24px;
    margin: 14px;
    border: 1px solid {border_subtle};
    box-shadow: 0 8px 32px {shadow_color};
    transition: all 300ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.settings-card:hover {{
    border-color: {COLORS['accent_glow_light']};
    box-shadow: 0 12px 40px {shadow_color_strong};
    transform: translateY(-2px);
}}

.card-title {{
    font-size: 17px;
    font-weight: 700;
    color: {COLORS['text']};
    margin-bottom: 18px;
    letter-spacing: 0.5px;
    padding-bottom: 12px;
    border-bottom: 1px solid {border_subtle};
}}

/* ============================================
   SETTINGS ROWS - Interactive List Items
   ============================================ */
.setting-row {{
    padding: 14px 12px;
    border-radius: 10px;
    margin: 4px 0;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid transparent;
}}

.setting-row:hover {{
    background: {hover_bg};
    border-color: {border_subtle};
    transform: translateX(4px);
}}

.setting-label {{
    color: {COLORS['text']};
    font-size: 14px;
    font-weight: 500;
}}

.setting-value {{
    color: {COLORS['subtext0']};
    font-size: 13px;
}}

/* ============================================
   STATUS BAR - Premium Bottom Bar
   ============================================ */
.status-bar {{
    background: {COLORS['crust']};
    padding: 14px 28px;
    border-top: 1px solid {border_subtle};
    box-shadow: 0 -4px 24px {shadow_color};
}}

.battery-icon {{
    color: {COLORS['green']};
    opacity: 0.9;
}}

.battery-indicator {{
    color: {COLORS['green']};
    font-weight: 600;
}}

.connection-icon {{
    color: {COLORS['accent']};
    opacity: 0.8;
}}

.connection-status {{
    color: {COLORS['subtext1']};
    font-size: 13px;
    font-weight: 500;
}}

/* ============================================
   SWITCHES - Modern Toggle Design
   ============================================ */
switch {{
    background: linear-gradient(135deg, {COLORS['surface1']} 0%, {COLORS['surface2']} 100%);
    border-radius: 16px;
    min-width: 52px;
    min-height: 28px;
    border: 1px solid {border_very_subtle};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

switch:hover {{
    border-color: {accent_30};
}}

switch:checked {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    box-shadow: 0 2px 12px {accent_40};
    border-color: transparent;
}}

switch slider {{
    background: linear-gradient(135deg, {COLORS['text']} 0%, {COLORS['subtext1']} 100%);
    border-radius: 14px;
    min-width: 24px;
    min-height: 24px;
    margin: 2px;
    box-shadow: 0 2px 8px {shadow_color};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

switch:checked slider {{
    background: {COLORS['text']};
    box-shadow: 0 2px 8px {shadow_color_strong};
}}

/* ============================================
   SCALES/SLIDERS - Premium Slider Design
   ============================================ */
scale trough {{
    background: linear-gradient(90deg, {COLORS['surface1']} 0%, {COLORS['surface2']} 100%);
    border-radius: 6px;
    min-height: 8px;
    border: 1px solid {border_faint};
}}

scale highlight {{
    background: linear-gradient(90deg, {COLORS['accent2']} 0%, {COLORS['accent']} 100%);
    border-radius: 6px;
    box-shadow: 0 0 12px {accent_30};
}}

scale slider {{
    background: linear-gradient(135deg, {COLORS['text']} 0%, {COLORS['subtext1']} 100%);
    border-radius: 50%;
    min-width: 22px;
    min-height: 22px;
    box-shadow: 0 2px 8px {shadow_color_strong};
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: none;
}}

scale slider:hover {{
    box-shadow: 0 4px 16px {accent_30}, 0 2px 8px {shadow_color_strong};
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
}}

/* ============================================
   SCROLLBAR - Minimal Modern Design
   ============================================ */
scrollbar {{
    background: transparent;
}}

scrollbar slider {{
    background: linear-gradient(180deg, {COLORS['surface2']} 0%, {COLORS['overlay0']} 100%);
    border-radius: 6px;
    min-width: 8px;
    transition: all 200ms ease;
    border: 1px solid {border_faint};
}}

scrollbar slider:hover {{
    background: linear-gradient(180deg, {COLORS['overlay0']} 0%, {COLORS['overlay1']} 100%);
    min-width: 10px;
}}

/* ============================================
   PRIMARY BUTTONS - Accent Gradient
   ============================================ */
.primary-btn {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    border: none;
    border-radius: 12px;
    padding: 12px 24px;
    font-weight: 700;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 16px {accent_30};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.primary-btn:hover {{
    background: linear-gradient(135deg, {COLORS['accent2']} 0%, {COLORS['accent']} 100%);
    box-shadow: 0 6px 24px {accent_50};
    transform: translateY(-2px);
}}

.primary-btn:active {{
    transform: translateY(0);
    box-shadow: 0 2px 8px {accent_30};
}}

/* ============================================
   DANGER BUTTONS - Warning Style
   ============================================ */
.danger-btn {{
    background: transparent;
    color: {COLORS['red']};
    border: 2px solid rgba(255, 82, 82, 0.5);
    border-radius: 12px;
    padding: 12px 24px;
    font-weight: 600;
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.danger-btn:hover {{
    background: rgba(255, 82, 82, 0.15);
    border-color: {COLORS['red']};
    box-shadow: 0 4px 20px rgba(255, 82, 82, 0.25);
    transform: translateY(-2px);
}}

/* ============================================
   SECONDARY/GHOST BUTTONS
   ============================================ */
.secondary-btn {{
    background: transparent;
    color: {COLORS['accent']};
    border: 1px solid {accent_30};
    border-radius: 10px;
    padding: 10px 20px;
    font-weight: 600;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.secondary-btn:hover {{
    background: {accent_10};
    border-color: {COLORS['accent']};
    box-shadow: 0 4px 16px {accent_20};
}}

/* ============================================
   DROPDOWN/COMBOBOX STYLING
   ============================================ */
dropdown {{
    background: linear-gradient(135deg, {COLORS['surface0']} 0%, {COLORS['surface1']} 100%);
    border: 1px solid {accent_15};
    border-radius: 10px;
    padding: 8px 16px;
    color: {COLORS['text']};
    transition: all 200ms ease;
}}

dropdown:hover {{
    border-color: {accent_40};
    box-shadow: 0 4px 16px {accent_15};
}}

dropdown popover {{
    background: {COLORS['surface0']};
    border: 1px solid {accent_20};
    border-radius: 12px;
    box-shadow: 0 8px 32px {shadow_color_strong};
}}

/* ============================================
   ENTRY/INPUT FIELDS
   ============================================ */
entry {{
    background: {COLORS['surface0']};
    border: 1px solid {COLORS['surface1']};
    border-radius: 10px;
    padding: 10px 14px;
    color: {COLORS['text']};
    transition: all 200ms ease;
}}

entry:focus {{
    border-color: {COLORS['accent']};
    box-shadow: 0 0 0 3px {accent_15}, 0 4px 16px {accent_10};
}}

/* ============================================
   TOOLTIPS
   ============================================ */
tooltip {{
    background: {tooltip_bg};
    border: 1px solid {accent_20};
    border-radius: 10px;
    padding: 10px 14px;
    box-shadow: 0 8px 32px {shadow_color_strong};
    color: {COLORS['text']};
}}

/* ============================================
   SPECIAL EFFECTS - Glow Classes
   ============================================ */
.glow-accent {{
    box-shadow: 0 0 20px {COLORS['accent_glow']};
}}

.glow-pulse {{
    animation: pulse-glow 2s ease-in-out infinite;
}}

.animate-slide-in {{
    animation: slide-in 300ms cubic-bezier(0.4, 0, 0.2, 1);
}}

/* ============================================
   HAPTIC PATTERN LIST ITEMS
   ============================================ */
.haptic-pattern-item {{
    padding: 14px 16px;
    border-radius: 10px;
    margin: 4px 0;
    background: transparent;
    border: 1px solid transparent;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.haptic-pattern-item:hover {{
    background: {accent_08};
    border-color: {accent_15};
}}

.haptic-pattern-item.selected {{
    background: linear-gradient(135deg, {accent_15} 0%, {accent2_10} 100%);
    border-color: {COLORS['accent']};
    box-shadow: 0 4px 16px {accent_20};
}}

/* ============================================
   SECTION DIVIDERS
   ============================================ */
.section-divider {{
    background: linear-gradient(90deg, transparent 0%, {accent_30} 50%, transparent 100%);
    min-height: 1px;
    margin: 20px 0;
}}

/* ============================================
   EASY-SWITCH SHORTCUTS CARD
   ============================================ */
.easyswitch-shortcuts-card {{
    background: {elevated_bg};
    border-radius: 12px;
    padding: 16px 20px;
    margin: 12px 0;
    border: 1px solid {accent_08};
    box-shadow: 0 4px 16px {shadow_color};
}}

.easyswitch-row {{
    padding: 4px 0;
}}

.easyswitch-icon-box {{
    background: linear-gradient(135deg, {accent_20} 0%, {accent2_15} 100%);
    border-radius: 10px;
    padding: 10px;
    min-width: 42px;
    min-height: 42px;
    border: 1px solid {accent_20};
}}

.easyswitch-icon {{
    color: {COLORS['accent']};
}}

.easyswitch-title {{
    font-size: 14px;
    font-weight: 600;
    color: {COLORS['text']};
    letter-spacing: 0.3px;
}}

.easyswitch-desc {{
    font-size: 12px;
    color: {COLORS['subtext0']};
    opacity: 0.85;
}}

/* ============================================
   BUTTON ASSIGNMENT UI - Premium Design
   ============================================ */
.button-assignment-card {{
    background: {elevated_bg};
    border-radius: 16px;
    padding: 20px;
    margin: 12px 0;
    border: 1px solid {accent_08};
    box-shadow: 0 8px 32px {shadow_color_strong};
}}

.button-assignment-header {{
    font-size: 15px;
    font-weight: 700;
    color: {COLORS['accent']};
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid {accent_15};
}}

.button-row {{
    background: {elevated_bg_hover};
    border-radius: 12px;
    padding: 14px 16px;
    margin: 6px 0;
    border: 1px solid {border_faint};
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.button-row:hover {{
    background: linear-gradient(135deg, {accent_12} 0%, {accent2_08} 100%);
    border-color: {accent_25};
    transform: translateX(4px);
    box-shadow: 0 4px 16px {accent_15};
}}

.button-icon-box {{
    background: linear-gradient(135deg, {accent_20} 0%, {accent2_15} 100%);
    border-radius: 10px;
    padding: 10px;
    min-width: 42px;
    min-height: 42px;
    border: 1px solid {accent_20};
}}

.button-icon {{
    color: {COLORS['accent']};
}}

.button-name {{
    font-size: 15px;
    font-weight: 600;
    color: {COLORS['text']};
    letter-spacing: 0.3px;
}}

.button-action {{
    font-size: 13px;
    font-weight: 500;
    color: {COLORS['accent']};
    padding: 4px 10px;
    background: {accent_10};
    border-radius: 6px;
    border: 1px solid {accent_20};
}}

.button-arrow {{
    color: {COLORS['subtext0']};
    padding: 8px;
    border-radius: 8px;
    transition: all 200ms ease;
}}

.button-arrow:hover {{
    background: {accent_15};
    color: {COLORS['accent']};
}}

/* Radial Menu Card - Featured Style */
.radial-menu-card {{
    background: linear-gradient(135deg, {accent_08} 0%, {accent2_05} 100%);
    border-radius: 16px;
    padding: 24px;
    margin: 20px 0 12px 0;
    border: 1px solid {accent_20};
    box-shadow: 0 8px 32px {accent_10}, 0 4px 16px {shadow_color};
}}

.radial-menu-card:hover {{
    border-color: {accent_35};
    box-shadow: 0 12px 40px {accent_15}, 0 6px 20px {shadow_color_strong};
}}

.radial-icon-large {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    border-radius: 14px;
    padding: 16px;
    min-width: 56px;
    min-height: 56px;
    box-shadow: 0 4px 16px {accent_35};
}}

.radial-icon-large image {{
    color: {text_on_accent};
}}

.radial-title {{
    font-size: 18px;
    font-weight: 700;
    color: {COLORS['text']};
    letter-spacing: 0.5px;
}}

.radial-subtitle {{
    font-size: 13px;
    color: {COLORS['subtext1']};
    margin-top: 4px;
}}

.configure-radial-btn {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 16px {accent_35};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.configure-radial-btn:hover {{
    box-shadow: 0 6px 24px {accent_50};
    transform: translateY(-2px);
}}

/* Slice Row Styling */
.slice-row {{
    background: {COLORS['surface0']};
    border-radius: 8px;
    padding: 10px 12px;
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid transparent;
}}

.slice-row:hover {{
    background: {COLORS['surface1']};
    border-color: {accent_20};
}}

.slice-icon {{
    color: {COLORS['subtext1']};
    opacity: 0.8;
}}

.slice-label {{
    font-size: 13px;
    font-weight: 500;
    color: {COLORS['text']};
}}

.slice-edit-btn {{
    opacity: 0.5;
    transition: opacity 200ms;
}}

.slice-row:hover .slice-edit-btn {{
    opacity: 1;
}}

/* Color Picker Buttons */
.color-btn-green {{ background: #00e676; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-green:checked {{ border-color: white; box-shadow: 0 0 8px #00e676; }}
.color-btn-yellow {{ background: #ffd54f; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-yellow:checked {{ border-color: white; box-shadow: 0 0 8px #ffd54f; }}
.color-btn-red {{ background: #ff5252; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-red:checked {{ border-color: white; box-shadow: 0 0 8px #ff5252; }}
.color-btn-mauve {{ background: #b388ff; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-mauve:checked {{ border-color: white; box-shadow: 0 0 8px #b388ff; }}
.color-btn-blue {{ background: #4a9eff; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-blue:checked {{ border-color: white; box-shadow: 0 0 8px #4a9eff; }}
.color-btn-pink {{ background: #ff80ab; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-pink:checked {{ border-color: white; box-shadow: 0 0 8px #ff80ab; }}
.color-btn-sapphire {{ background: #00b4d8; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-sapphire:checked {{ border-color: white; box-shadow: 0 0 8px #00b4d8; }}
.color-btn-teal {{ background: #0abdc6; border-radius: 8px; border: 2px solid transparent; }}
.color-btn-teal:checked {{ border-color: white; box-shadow: 0 0 8px #0abdc6; }}

/* Preset Action Buttons */
.preset-btn {{
    background: {COLORS['surface0']};
    border: 1px solid {COLORS['surface2']};
    border-radius: 8px;
    padding: 8px 12px;
    transition: all 200ms;
}}

.preset-btn:hover {{
    background: {COLORS['surface1']};
    border-color: {COLORS['accent']};
}}

/* Section Header */
.section-header {{
    font-size: 12px;
    font-weight: 600;
    color: {COLORS['subtext0']};
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 12px;
    margin-top: 8px;
}}

/* ============================================
   PREMIUM HEADER STYLING
   ============================================ */
.app-title {{
    font-size: 22px;
    font-weight: 800;
    color: {COLORS['text']};
    letter-spacing: 0.5px;
}}

.app-title-accent {{
    color: {COLORS['accent']};
}}

.app-subtitle {{
    font-size: 11px;
    font-weight: 500;
    color: {COLORS['subtext0']};
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 2px;
}}

.logo-container {{
    background: linear-gradient(135deg, {accent_15} 0%, {accent2_10} 100%);
    border-radius: 12px;
    padding: 8px;
    border: 1px solid {accent_20};
    box-shadow: 0 4px 16px {accent_15};
}}

.device-badge {{
    background: linear-gradient(135deg, rgba(0, 230, 118, 0.15) 0%, rgba(0, 200, 100, 0.1) 100%);
    border: 1px solid rgba(0, 230, 118, 0.3);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    color: {COLORS['green']};
    letter-spacing: 0.5px;
}}

.header-divider {{
    background: linear-gradient(90deg, {accent_40} 0%, {accent_10} 100%);
    min-width: 2px;
    min-height: 36px;
    border-radius: 1px;
    margin: 0 16px;
}}

/* ============================================
   DONATE BUTTON - Theme-Colored
   ============================================ */
.donate-btn {{
    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent2']} 100%);
    color: {text_on_accent};
    border-radius: 10px;
    padding: 10px 16px;
    font-weight: 600;
    font-size: 13px;
    border: none;
    box-shadow: 0 4px 16px {COLORS['accent_glow']};
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}}

.donate-btn:hover {{
    box-shadow: 0 6px 24px {COLORS['accent_glow']};
    transform: translateY(-1px);
}}
"""

# Generate CSS at module load time
CSS = generate_css()
