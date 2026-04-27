#!/usr/bin/env python3
"""
JuhRadial MX - Settings CSS

Design system: "Workbench" — settings as a precision instrument.
- One accent, used only for state (never decoration).
- Solid surfaces, hairline 1px borders.
- No gradients, no transforms, no glow halos.
- Monospace for numeric values.
- 120-150ms transitions, color/border/opacity only.
- Light and dark themes designed independently.

SPDX-License-Identifier: GPL-3.0
"""


def generate_css(COLORS):
    is_dark = COLORS.get('is_dark', True)

    accent = COLORS.get('accent', '#00d4ff')
    ar, ag, ab = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    accent_06 = f'rgba({ar}, {ag}, {ab}, 0.06)'
    accent_10 = f'rgba({ar}, {ag}, {ab}, 0.10)'
    accent_15 = f'rgba({ar}, {ag}, {ab}, 0.15)'
    accent_25 = f'rgba({ar}, {ag}, {ab}, 0.25)'
    accent_40 = f'rgba({ar}, {ag}, {ab}, 0.40)'

    # Theme-specific tokens.
    if is_dark:
        # Dark — graphite/obsidian. The mouse render is the only luminous thing.
        win_bg            = COLORS['crust']
        rail_bg           = COLORS['mantle']
        panel_bg          = COLORS['mantle']
        panel_bg_quiet    = COLORS['crust']
        panel_bg_hover    = COLORS['surface0']
        row_bg            = 'transparent'
        row_bg_hover      = 'rgba(255, 255, 255, 0.03)'
        row_bg_active     = 'rgba(255, 255, 255, 0.05)'
        hairline          = 'rgba(255, 255, 255, 0.07)'
        hairline_strong   = 'rgba(255, 255, 255, 0.12)'
        hairline_faint    = 'rgba(255, 255, 255, 0.04)'
        text_strong       = COLORS['text']
        text_dim          = COLORS['subtext0']
        text_faint        = COLORS['overlay0']
        text_on_accent    = COLORS['crust']
        focus_ring        = accent_40
        scrollbar_track   = 'transparent'
        scrollbar_thumb   = 'rgba(255, 255, 255, 0.12)'
        scrollbar_thumb_h = 'rgba(255, 255, 255, 0.22)'
        chip_bg           = 'rgba(255, 255, 255, 0.04)'
        chip_border       = 'rgba(255, 255, 255, 0.08)'
        success           = COLORS['green']
        danger            = COLORS['red']
    else:
        # Light — warm off-white, graphite text. Not a flipped dark.
        win_bg            = '#FAFAF7'
        rail_bg           = '#F2F1EC'
        panel_bg          = '#FFFFFF'
        panel_bg_quiet    = '#F7F6F2'
        panel_bg_hover    = '#F2F1EC'
        row_bg            = 'transparent'
        row_bg_hover      = 'rgba(0, 0, 0, 0.03)'
        row_bg_active     = 'rgba(0, 0, 0, 0.05)'
        hairline          = 'rgba(0, 0, 0, 0.10)'
        hairline_strong   = 'rgba(0, 0, 0, 0.18)'
        hairline_faint    = 'rgba(0, 0, 0, 0.05)'
        text_strong       = '#16181C'
        text_dim          = '#54585F'
        text_faint        = '#8B8F97'
        text_on_accent    = '#FFFFFF'
        focus_ring        = accent_40
        scrollbar_track   = 'transparent'
        scrollbar_thumb   = 'rgba(0, 0, 0, 0.18)'
        scrollbar_thumb_h = 'rgba(0, 0, 0, 0.30)'
        chip_bg           = 'rgba(0, 0, 0, 0.04)'
        chip_border       = 'rgba(0, 0, 0, 0.08)'
        success           = '#1F9D55'
        danger            = '#C33A3A'

    # Type stacks. GTK falls through gracefully if a family is missing.
    sans = '"Inter", "Geist", "SF Pro Text", -apple-system, "Segoe UI", system-ui, sans-serif'
    mono = '"Geist Mono", "JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code", monospace'

    return f"""
/* =========================================================================
   ROOT — global typography defaults
   ========================================================================= */
window {{
    font-family: {sans};
    color: {text_strong};
}}

window.settings-window {{
    background: {win_bg};
}}

label {{
    color: {text_strong};
}}

.dim-label, label.dim-label {{
    color: {text_dim};
}}

/* Built-in Adwaita typography classes — keep readable but neutral */
.title-1 {{ font-size: 22px; font-weight: 600; letter-spacing: -0.2px; color: {text_strong}; }}
.title-2 {{ font-size: 18px; font-weight: 600; letter-spacing: -0.1px; color: {text_strong}; }}
.title-3 {{ font-size: 15px; font-weight: 600; color: {text_strong}; }}
.heading {{ font-size: 14px; font-weight: 600; color: {text_strong}; letter-spacing: 0.2px; }}
.caption {{ font-size: 11px; color: {text_dim}; letter-spacing: 0.4px; }}

/* =========================================================================
   HEADER — product mark, device status, primary action
   Quiet. The header should not compete with the workbench below it.
   ========================================================================= */
.app-title {{
    font-size: 16px;
    font-weight: 600;
    color: {text_strong};
    letter-spacing: -0.1px;
}}

.app-title-accent {{
    color: {COLORS['accent']};
}}

.app-subtitle {{
    font-size: 10px;
    font-weight: 500;
    color: {text_faint};
    letter-spacing: 1.4px;
    text-transform: uppercase;
}}

.logo-container {{
    background: transparent;
    border-radius: 6px;
    padding: 2px;
    border: none;
    box-shadow: none;
}}

.header-divider {{
    background: {hairline};
    min-width: 1px;
    min-height: 20px;
    margin: 0 14px;
    border-radius: 0;
}}

/* Device badge — compact pill, success color reserved for "actually connected" */
.device-badge {{
    background: transparent;
    border: 1px solid {hairline_strong};
    border-radius: 4px;
    padding: 4px 10px;
    font-family: {mono};
    font-size: 10px;
    font-weight: 600;
    color: {text_dim};
    letter-spacing: 1.2px;
    text-transform: uppercase;
}}

/* =========================================================================
   SIDEBAR — left rail. Text + icon. Active state is a 2px accent rail.
   No card-y badges. No gradients. Typography carries hierarchy.
   ========================================================================= */
.sidebar {{
    background: {rail_bg};
    padding: 18px 8px 12px 8px;
    min-width: 220px;
    border-right: 1px solid {hairline};
    border-radius: 0;
    box-shadow: none;
}}

.nav-item {{
    padding: 10px 14px 10px 16px;
    margin: 1px 4px;
    border-radius: 6px;
    color: {text_dim};
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.1px;
    border: none;
    background: transparent;
    box-shadow: none;
    transition: background 120ms ease, color 120ms ease;
}}

.nav-item:hover {{
    background: {row_bg_hover};
    color: {text_strong};
}}

.nav-item.active {{
    background: {row_bg_active};
    color: {text_strong};
    /* 2px accent indicator on left edge */
    border-left: 2px solid {COLORS['accent']};
    padding-left: 14px;
}}

.nav-item.active:hover {{
    background: {row_bg_active};
    color: {text_strong};
}}

/* PNG nav icons — desaturate slightly so color doesn't carry meaning */
.nav-icon-img {{
    opacity: 0.78;
    transition: opacity 120ms ease;
}}

.nav-item:hover .nav-icon-img {{ opacity: 1; }}
.nav-item.active .nav-icon-img {{ opacity: 1; }}

/* Symbolic icon fallback — no badge, just the glyph */
.nav-icon-badge {{
    background: transparent;
    border: none;
    padding: 4px;
    min-width: 24px;
    min-height: 24px;
    box-shadow: none;
}}

.nav-icon {{
    color: {text_dim};
    transition: color 120ms ease;
}}

.nav-item:hover .nav-icon,
.nav-item.active .nav-icon {{
    color: {text_strong};
}}

/* Page header icon (top of each page) */
.page-header-icon {{
    color: {text_dim};
    opacity: 0.85;
}}

/* Generated transparent assets — visual depth lives in the artwork, not chrome. */
.generated-asset-hero {{
    background: {panel_bg_quiet};
    border: 1px solid {hairline};
    border-radius: 10px;
    padding: 10px 12px;
    margin: 0 10px 4px 10px;
    box-shadow: none;
}}

.generated-asset-image {{
    opacity: 0.96;
}}

.radial-menu-card .generated-asset-hero {{
    background: {panel_bg};
    border-color: {hairline_faint};
    padding: 8px;
    margin: -2px 0 14px 0;
}}

/* =========================================================================
   PANELS — settings-card and info-card.
   Solid surfaces, 1px hairlines, generous padding, no shadow.
   ========================================================================= */
.settings-card {{
    background: {panel_bg};
    border: 1px solid {hairline};
    border-radius: 10px;
    padding: 20px 22px;
    margin: 10px;
    box-shadow: none;
    transition: border-color 120ms ease, background 120ms ease;
}}

.settings-card:hover {{
    border-color: {hairline_strong};
    box-shadow: none;
}}

.info-card {{
    background: {panel_bg_quiet};
    border: 1px solid {hairline_faint};
    border-radius: 10px;
    padding: 16px 18px;
    margin: 10px;
    box-shadow: none;
}}

.info-card:hover {{
    border-color: {hairline};
    background: {panel_bg_quiet};
}}

.info-card .card-title {{
    font-size: 11px;
    font-weight: 600;
    color: {text_dim};
    letter-spacing: 1.2px;
    text-transform: uppercase;
    border-bottom: none;
    padding-bottom: 8px;
    margin-bottom: 12px;
}}

.card-title {{
    font-size: 15px;
    font-weight: 600;
    color: {text_strong};
    letter-spacing: -0.1px;
    padding-bottom: 14px;
    margin-bottom: 16px;
    border-bottom: 1px solid {hairline};
}}

/* Section header — small caps tracking, used to group rows inside a panel */
.section-header {{
    font-size: 10px;
    font-weight: 600;
    color: {text_faint};
    letter-spacing: 1.6px;
    text-transform: uppercase;
    margin: 14px 0 8px 0;
}}

/* =========================================================================
   ROWS — high-density list items. Replace boxy cards.
   Label · value · chevron pattern.
   ========================================================================= */
.setting-row {{
    padding: 10px 12px;
    margin: 0;
    border-radius: 6px;
    background: {row_bg};
    border: 1px solid transparent;
    transition: background 120ms ease, border-color 120ms ease;
}}

.setting-row:hover {{
    background: {row_bg_hover};
    border-color: {hairline};
}}

.setting-label {{
    color: {text_strong};
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0;
}}

.setting-value {{
    color: {text_dim};
    font-family: {mono};
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0;
}}

/* Boxed list (Adwaita) — keep visual rhythm with our panels */
.boxed-list {{
    background: {panel_bg};
    border: 1px solid {hairline};
    border-radius: 10px;
}}

/* =========================================================================
   STATUS BAR — minimal foot. Battery, connection, version.
   ========================================================================= */
.status-bar {{
    background: {win_bg};
    padding: 10px 22px;
    border-top: 1px solid {hairline};
    box-shadow: none;
}}

.battery-icon {{
    color: {text_dim};
    opacity: 0.9;
}}

.battery-indicator {{
    color: {text_strong};
    font-family: {mono};
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0;
}}

.connection-icon {{
    color: {text_dim};
    opacity: 0.85;
}}

.connection-status {{
    color: {text_dim};
    font-size: 12px;
    font-weight: 500;
}}

.connection-dot {{
    min-width: 6px;
    min-height: 6px;
    border-radius: 50%;
    background: {text_faint};
}}

.connection-dot.connected {{
    background: {success};
    box-shadow: none;
}}

.connection-dot.disconnected {{
    background: {danger};
}}

/* =========================================================================
   SWITCH — sharp pill. State carried by accent fill.
   ========================================================================= */
switch {{
    background: {chip_bg};
    border: 1px solid {chip_border};
    border-radius: 14px;
    min-width: 48px;
    min-height: 26px;
    transition: background 120ms ease, border-color 120ms ease;
}}

switch:hover {{
    border-color: {hairline_strong};
}}

switch:checked {{
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
    box-shadow: none;
}}

switch slider {{
    background: {text_strong};
    border-radius: 11px;
    min-width: 20px;
    min-height: 20px;
    box-shadow: none;
    transition: none;
}}

switch:checked slider {{
    background: {text_on_accent};
    box-shadow: none;
}}

/* =========================================================================
   SCALES / SLIDERS — thin track, simple thumb.
   ========================================================================= */
scale {{
    padding: 4px 0;
    min-height: 22px;
}}

scale trough {{
    background: {chip_bg};
    border: 1px solid {chip_border};
    border-radius: 3px;
    min-height: 6px;
}}

scale highlight {{
    background: {COLORS['accent']};
    border-radius: 3px;
    box-shadow: none;
}}

scale slider {{
    background: {text_strong};
    border-radius: 50%;
    min-width: 20px;
    min-height: 20px;
    box-shadow: none;
    transition: background 120ms ease;
}}

scale slider:hover {{
    background: {COLORS['accent']};
}}

/* =========================================================================
   SCROLLBAR — invisible until needed.
   ========================================================================= */
scrollbar {{
    background: {scrollbar_track};
    border: none;
}}

scrollbar slider {{
    background: {scrollbar_thumb};
    border: none;
    border-radius: 4px;
    min-width: 6px;
    min-height: 6px;
    transition: background 120ms ease, min-width 120ms ease;
}}

scrollbar slider:hover {{
    background: {scrollbar_thumb_h};
    min-width: 8px;
}}

/* =========================================================================
   BUTTONS — primary, secondary, danger, add-app, donate.
   No gradient. Accent is the primary fill. Hover: subtle tone shift.
   ========================================================================= */
.primary-btn, button.suggested-action {{
    background: {COLORS['accent']};
    color: {text_on_accent};
    border: 1px solid {COLORS['accent']};
    border-radius: 6px;
    padding: 9px 16px;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0;
    box-shadow: none;
    transition: background 120ms ease, border-color 120ms ease;
}}

.primary-btn:hover, button.suggested-action:hover {{
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
    box-shadow: 0 0 0 3px {accent_15};
}}

.primary-btn:active, button.suggested-action:active {{
    box-shadow: none;
    opacity: 0.9;
}}

.secondary-btn {{
    background: transparent;
    color: {text_strong};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 500;
    font-size: 13px;
    transition: background 120ms ease, border-color 120ms ease;
}}

.secondary-btn:hover {{
    background: {row_bg_hover};
    border-color: {COLORS['accent']};
    color: {text_strong};
    box-shadow: none;
}}

.danger-btn, button.destructive-action {{
    background: transparent;
    color: {danger};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 500;
    font-size: 13px;
    transition: background 120ms ease, border-color 120ms ease;
}}

.danger-btn:hover, button.destructive-action:hover {{
    background: rgba(195, 58, 58, 0.08);
    border-color: {danger};
    color: {danger};
    box-shadow: none;
}}

.add-app-btn {{
    background: transparent;
    color: {text_strong};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 500;
    font-size: 13px;
    transition: background 120ms ease, border-color 120ms ease;
}}

.add-app-btn:hover {{
    background: {row_bg_hover};
    border-color: {COLORS['accent']};
    color: {text_strong};
    box-shadow: none;
}}

button.flat {{
    background: transparent;
    border: none;
    color: {text_strong};
    border-radius: 6px;
    padding: 6px 10px;
    transition: background 120ms ease;
}}

button.flat:hover {{
    background: {row_bg_hover};
}}

button.circular {{
    background: transparent;
    border: 1px solid {hairline};
    border-radius: 999px;
    color: {text_dim};
    transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}}

button.circular:hover {{
    background: {row_bg_hover};
    border-color: {hairline_strong};
    color: {text_strong};
}}

/* =========================================================================
   DROPDOWN, ENTRY, TOOLTIP
   ========================================================================= */
dropdown {{
    background: {panel_bg};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 6px 12px;
    color: {text_strong};
    font-size: 13px;
    transition: border-color 120ms ease, background 120ms ease;
}}

dropdown:hover {{
    border-color: {COLORS['accent']};
    box-shadow: none;
}}

dropdown popover {{
    background: {panel_bg};
    border: 1px solid {hairline_strong};
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
    padding: 4px;
}}

dropdown popover listview row {{
    padding: 8px 12px;
    border-radius: 4px;
    color: {text_strong};
    font-size: 13px;
}}

dropdown popover listview row:hover {{
    background: {row_bg_hover};
}}

dropdown popover listview row:selected {{
    background: {accent_15};
    color: {text_strong};
}}

entry {{
    background: {panel_bg};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 8px 12px;
    color: {text_strong};
    font-size: 13px;
    transition: border-color 120ms ease, box-shadow 120ms ease;
}}

entry:focus {{
    border-color: {COLORS['accent']};
    box-shadow: 0 0 0 3px {accent_15};
}}

tooltip {{
    background: {panel_bg};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 6px 10px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
    color: {text_strong};
    font-size: 12px;
}}

/* Linked button group (e.g. segmented controls) */
.linked > * {{
    border-radius: 0;
}}

.linked > *:first-child {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
.linked > *:last-child {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}

/* =========================================================================
   BUTTON ASSIGNMENTS — the primary content of the BUTTONS tab.
   This is the table users live in. Make it feel like a real table:
   tight, scannable, mono values, subtle dividers.
   ========================================================================= */
.button-assignment-card {{
    background: {panel_bg};
    border: 1px solid {hairline};
    border-radius: 10px;
    padding: 8px;
    margin: 6px 0;
    box-shadow: none;
}}

.button-assignment-header {{
    font-size: 10px;
    font-weight: 600;
    color: {text_faint};
    letter-spacing: 1.6px;
    text-transform: uppercase;
    padding: 12px 12px 8px 12px;
    margin: 0;
    border-bottom: 1px solid {hairline_faint};
}}

.button-row {{
    background: transparent;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 1px 0;
    border: 1px solid transparent;
    transition: background 120ms ease, border-color 120ms ease;
}}

.button-row:hover {{
    background: {row_bg_hover};
    border-color: {hairline};
    box-shadow: none;
}}

.button-icon-box {{
    background: transparent;
    border-radius: 6px;
    padding: 6px;
    min-width: 28px;
    min-height: 28px;
    border: 1px solid {hairline};
}}

.button-icon {{
    color: {text_dim};
}}

.button-row:hover .button-icon {{
    color: {text_strong};
}}

.button-name {{
    font-size: 13px;
    font-weight: 500;
    color: {text_strong};
    letter-spacing: 0;
}}

.button-action {{
    font-family: {mono};
    font-size: 11px;
    font-weight: 500;
    color: {text_dim};
    padding: 3px 8px;
    background: {chip_bg};
    border-radius: 4px;
    border: 1px solid {chip_border};
    letter-spacing: 0;
}}

.button-arrow {{
    color: {text_faint};
    padding: 4px;
    border-radius: 4px;
    transition: color 120ms ease, background 120ms ease;
}}

.button-row:hover .button-arrow {{
    color: {text_strong};
}}

.button-arrow:hover {{
    background: {row_bg_active};
    color: {text_strong};
}}

/* =========================================================================
   RADIAL MENU CARD — the "Actions Ring" preview at the top of BUTTONS.
   Quieter than before. Featured but not a billboard.
   ========================================================================= */
.radial-menu-card {{
    background: {panel_bg_quiet};
    border: 1px solid {hairline};
    border-radius: 10px;
    padding: 16px 18px;
    margin: 6px 0;
    box-shadow: none;
    transition: border-color 120ms ease;
}}

.radial-menu-card:hover {{
    border-color: {hairline_strong};
    box-shadow: none;
}}

.radial-icon-large {{
    background: transparent;
    border: 1px solid {COLORS['accent']};
    border-radius: 8px;
    padding: 10px;
    min-width: 40px;
    min-height: 40px;
    box-shadow: none;
}}

.radial-icon-large image {{
    color: {COLORS['accent']};
}}

.radial-title {{
    font-size: 14px;
    font-weight: 600;
    color: {text_strong};
    letter-spacing: -0.1px;
}}

.radial-subtitle {{
    font-size: 12px;
    color: {text_dim};
    margin-top: 2px;
}}

/* Slice rows inside the radial action editor */
.slice-row {{
    background: transparent;
    border-radius: 6px;
    padding: 8px 10px;
    border: 1px solid transparent;
    transition: background 120ms ease, border-color 120ms ease;
}}

.slice-row:hover {{
    background: {row_bg_hover};
    border-color: {hairline};
}}

.slice-icon {{
    color: {text_dim};
    opacity: 0.9;
}}

.slice-label {{
    font-size: 13px;
    font-weight: 500;
    color: {text_strong};
}}

.slice-edit-btn {{
    opacity: 0;
    transition: opacity 120ms ease;
}}

.slice-row:hover .slice-edit-btn {{
    opacity: 1;
}}

/* Color picker swatches for slice colors */
.color-btn-green   {{ background: #1F9D55; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-yellow  {{ background: #E0A800; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-red     {{ background: #C33A3A; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-mauve   {{ background: #8E6BD1; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-blue    {{ background: #3D80D6; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-pink    {{ background: #D86891; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-sapphire{{ background: #2D8FB3; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-teal    {{ background: #2A9D9A; border-radius: 6px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}

.color-btn-green:checked,
.color-btn-yellow:checked,
.color-btn-red:checked,
.color-btn-mauve:checked,
.color-btn-blue:checked,
.color-btn-pink:checked,
.color-btn-sapphire:checked,
.color-btn-teal:checked {{
    border-color: {text_strong};
    box-shadow: 0 0 0 2px {win_bg} inset;
}}

/* Preset / palette action buttons */
.preset-btn, .palette-action-btn {{
    background: transparent;
    border: 1px solid {hairline};
    border-radius: 6px;
    padding: 6px 10px;
    color: {text_strong};
    font-size: 12px;
    transition: background 120ms ease, border-color 120ms ease;
}}

.preset-btn:hover, .palette-action-btn:hover {{
    background: {row_bg_hover};
    border-color: {COLORS['accent']};
}}

/* =========================================================================
   EASY-SWITCH — keyboard shortcut hints. Mono so the keys read like keys.
   ========================================================================= */
.easyswitch-shortcuts-card {{
    background: {panel_bg_quiet};
    border: 1px solid {hairline};
    border-radius: 10px;
    padding: 14px 16px;
    margin: 6px 0;
    box-shadow: none;
}}

.easyswitch-row {{
    padding: 6px 0;
    border-bottom: 1px solid {hairline_faint};
}}

.easyswitch-row:last-child {{
    border-bottom: none;
}}

.easyswitch-icon-box {{
    background: transparent;
    border: 1px solid {hairline};
    border-radius: 6px;
    padding: 6px;
    min-width: 32px;
    min-height: 32px;
}}

.easyswitch-icon {{
    color: {text_dim};
}}

.easyswitch-title {{
    font-size: 13px;
    font-weight: 500;
    color: {text_strong};
    letter-spacing: 0;
}}

.easyswitch-desc {{
    font-size: 11px;
    color: {text_dim};
    font-family: {mono};
}}

/* =========================================================================
   HAPTIC PATTERN ROWS — a list. The selected row gets the accent rail.
   ========================================================================= */
.haptic-pattern-item {{
    padding: 10px 12px;
    margin: 1px 0;
    border-radius: 6px;
    background: transparent;
    border: 1px solid transparent;
    transition: background 120ms ease, border-color 120ms ease;
}}

.haptic-pattern-item:hover {{
    background: {row_bg_hover};
    border-color: {hairline};
}}

.haptic-pattern-item.selected {{
    background: {accent_06};
    border-left: 2px solid {COLORS['accent']};
    border-top: 1px solid {hairline};
    border-right: 1px solid {hairline};
    border-bottom: 1px solid {hairline};
    padding-left: 10px;
}}

/* =========================================================================
   MACRO TIMELINE — frames in a strip. Selection: accent rail.
   ========================================================================= */
.timeline-row {{
    padding: 8px 12px;
    border-radius: 6px;
    background: transparent;
    border: 1px solid transparent;
    transition: background 120ms ease, border-color 120ms ease;
}}

.timeline-row:hover {{
    background: {row_bg_hover};
    border-color: {hairline};
}}

.timeline-row-selected {{
    background: {accent_06};
    border-left: 2px solid {COLORS['accent']};
    border-top: 1px solid {hairline};
    border-right: 1px solid {hairline};
    border-bottom: 1px solid {hairline};
    padding-left: 10px;
}}

/* =========================================================================
   DONATE — sidebar bottom card. Quiet, but humanly warm.
   ========================================================================= */
.donate-card {{
    background: {panel_bg_quiet};
    border: 1px solid {hairline};
    border-radius: 10px;
    padding: 12px;
    box-shadow: none;
}}

.donate-btn {{
    background: transparent;
    color: {text_strong};
    border: 1px solid {hairline_strong};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 500;
    font-size: 12px;
    box-shadow: none;
    transition: background 120ms ease, border-color 120ms ease;
}}

.donate-btn:hover {{
    background: {row_bg_hover};
    border-color: {COLORS['accent']};
    color: {text_strong};
    box-shadow: none;
}}

.donate-heart {{
    min-width: 32px;
    min-height: 32px;
}}

/* =========================================================================
   STATUS / SEMANTIC TINTS — keep Adwaita's success/warning/accent muted,
   so a green or red label is information, not an alarm.
   ========================================================================= */
.success {{
    color: {success};
}}

.warning {{
    color: #C9851B;
}}

.accent, .accent-color {{
    color: {COLORS['accent']};
}}

/* Generic badge — small uppercase pill */
.badge {{
    background: {chip_bg};
    border: 1px solid {chip_border};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 600;
    color: {text_dim};
    letter-spacing: 1.2px;
    text-transform: uppercase;
}}

/* Generic catch-all card class (libadwaita .card) */
.card {{
    background: {panel_bg};
    border: 1px solid {hairline};
    border-radius: 10px;
}}

/* Generic background helper */
.background {{
    background: {win_bg};
}}

/* =========================================================================
   FOCUS — visible on every interactive widget when keyboard-navigated.
   Power users keyboard-navigate settings.
   ========================================================================= */
button:focus-visible,
.nav-item:focus-visible,
.button-row:focus-visible,
.setting-row:focus-visible,
.haptic-pattern-item:focus-visible,
.timeline-row:focus-visible,
.preset-btn:focus-visible,
.add-app-btn:focus-visible,
dropdown:focus-visible {{
    outline: none;
    box-shadow: 0 0 0 2px {focus_ring};
}}
"""
