#!/usr/bin/env python3
"""
JuhRadial MX - Settings CSS

Design system: "PHOSPHOR" — an obsidian instrument lit by a single charged
trace of light. (Reversible test skin for the GTK4/Adwaita settings app.)

  - Machined obsidian surfaces; depth from layered ambient shadow + a top
    sheen + a corner radial glow + a hairline border — never from loud fills.
  - ONE accent: phosphor mint-aqua (#4FEFC9) -> cyan (#36C9FF).
  - "Light is state": the accent + its glow appear ONLY on things that are
    active / checked / selected / connected / focused. Resting controls are quiet.
  - Editorial display headers; mono means numbers: every DPI / Hz / ms / % /
    key-combo is JetBrains Mono.
  - Hairline 1px borders; generous radii; a real elevation ladder.

GTK4/Adwaita CSS notes: this is a strict subset of web CSS. There is NO
backdrop-filter/blur, NO `filter`, NO `transform`, NO `::before/::after`
generated content, NO web `var()`. So "glass" is approximated with dark
translucent gradients + an inset top-edge highlight + a hairline border;
accent rails are drawn with inset `box-shadow` (a left bar) instead of a
pseudo-element; depth is layered real `box-shadow`. rgba()/gradients are
GTK-native and used throughout.

SPDX-License-Identifier: GPL-3.0
"""


def generate_css(COLORS):
    # ---------------------------------------------------------------------
    # PHOSPHOR tokens, now driven by the active theme palette (COLORS).
    # The obsidian structure (glows, radii, sheen, type) is preserved; every
    # hue is pulled from the selected theme so switching themes recolors the
    # whole UI. The PHOSPHOR mint values remain the fallback.
    # ---------------------------------------------------------------------
    c = COLORS or {}
    is_dark = c.get('is_dark', True)

    def _rgba(hex_color, alpha):
        h = (hex_color or '#000000').lstrip('#')
        if len(h) == 3:
            h = ''.join(ch * 2 for ch in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'rgba({r}, {g}, {b}, {alpha})'

    # Surfaces — depth ramp (deepest -> raised), from the theme
    void         = c.get('crust', '#04060A')
    surface_900  = c.get('mantle', '#080B11')
    surface_800  = c.get('base', '#0C1019')
    surface_700  = c.get('surface0', '#11161F')
    surface_600  = c.get('surface1', '#161D28')
    surface_500  = c.get('surface2', '#1E2733')

    # Hairlines — white alpha on dark themes, ink alpha on light ones
    _ln = '255, 255, 255' if is_dark else '8, 12, 20'
    line_faint   = f'rgba({_ln}, 0.045)'
    line         = f'rgba({_ln}, 0.085)'
    line_strong  = f'rgba({_ln}, 0.135)'
    line_bright  = f'rgba({_ln}, 0.22)'

    # Ink ramp
    text_0       = c.get('text', '#F3F8FB')
    text_1       = c.get('text', '#DCE5EE')
    text_2       = c.get('subtext1', '#A4B1C0')
    text_3       = c.get('subtext0', '#6C7A8A')
    text_4       = c.get('overlay1', c.get('overlay0', '#47535F'))

    # Accent — the one charged trace, from the theme
    accent        = c.get('accent', '#4FEFC9')
    accent_2      = c.get('accent2', '#36C9FF')
    accent_bright = c.get('accent', '#76FFDD')
    on_accent     = '#04201A' if is_dark else '#04140F'

    accent_a06 = _rgba(accent, 0.06)
    accent_a10 = _rgba(accent, 0.10)
    accent_a16 = _rgba(accent, 0.16)
    accent_a24 = _rgba(accent, 0.24)
    accent_a40 = _rgba(accent, 0.40)
    accent_a60 = _rgba(accent, 0.60)

    # The dual-tone live gradient — ONLY on powered elements
    grad_live      = f'linear-gradient(135deg, {accent} 0%, {accent_2} 100%)'
    grad_live_soft = f'linear-gradient(135deg, {_rgba(accent, 0.20)}, {_rgba(accent_2, 0.13)})'

    # Semantic (status only)
    success = c.get('green', '#3FE08A')
    warning = c.get('yellow', '#FFC75A')
    danger  = c.get('red', '#FF5C6E')

    # Glow — accent bloom (live only)
    glow_xs  = f'0 0 8px {_rgba(accent, 0.40)}'
    glow_sm  = f'0 0 14px {_rgba(accent, 0.36)}'

    # Elevation ladder — machined ambient shadows + insets
    shadow_sm  = '0 1px 2px rgba(0,0,0,0.45)'
    shadow_md  = '0 10px 28px -10px rgba(0,0,0,0.58)'
    shadow_lg  = '0 22px 52px -18px rgba(0,0,0,0.66)'
    inset_top  = 'inset 0 1px 0 rgba(255,255,255,0.06)'
    inset_edge = 'inset 0 0 0 1px rgba(255,255,255,0.028)'
    focus_glow = f'0 0 0 2px {accent_a40}, 0 0 16px {_rgba(accent, 0.28)}'

    # Composed card recipes (machined obsidian: corner glow + top sheen + edge)
    card_bg_image = ('radial-gradient(125% 90% at 0% 0%, rgba(30,40,55,0.32), transparent 58%), '
                     'linear-gradient(180deg, rgba(255,255,255,0.030), transparent 44%)')
    card_shadow       = f'{shadow_md}, {inset_top}, {inset_edge}'
    card_shadow_hover = f'{shadow_lg}, {inset_top}, {inset_edge}'

    # The accent rail — a 3px left bar drawn with an inset shadow (no pseudo-els)
    rail = f'inset 3px 0 0 0 {accent}'

    # Row state fills
    row_bg        = 'transparent'
    row_bg_hover  = surface_600
    row_bg_active = surface_500

    chip_bg     = surface_700
    chip_border = line

    # Type stacks. GTK falls through gracefully if a family is missing.
    sans = ('"Hanken Grotesk", "Inter", "SF Pro Text", -apple-system, '
            '"Segoe UI", system-ui, sans-serif')
    disp = ('"Bricolage Grotesque", "Archivo", "Hanken Grotesk", '
            'system-ui, sans-serif')
    mono = ('"JetBrains Mono", "Geist Mono", "SF Mono", "Fira Code", '
            '"Cascadia Code", monospace')

    return f"""
/* =========================================================================
   ADWAITA NAMED COLORS — re-tint libadwaita's built-ins to PHOSPHOR obsidian.
   These flow into the header bar, dialogs, popovers, default switches, links.
   ========================================================================= */
@define-color window_bg_color {surface_800};
@define-color window_fg_color {text_1};
@define-color view_bg_color {surface_800};
@define-color view_fg_color {text_1};
@define-color headerbar_bg_color {surface_900};
@define-color headerbar_fg_color {text_1};
@define-color headerbar_border_color {line};
@define-color headerbar_backdrop_color {surface_900};
@define-color sidebar_bg_color {surface_900};
@define-color sidebar_fg_color {text_2};
@define-color card_bg_color {surface_700};
@define-color card_fg_color {text_1};
@define-color popover_bg_color {surface_700};
@define-color popover_fg_color {text_1};
@define-color dialog_bg_color {surface_700};
@define-color dialog_fg_color {text_1};
@define-color accent_color {accent};
@define-color accent_bg_color {accent};
@define-color accent_fg_color {on_accent};
@define-color destructive_color {danger};
@define-color destructive_bg_color {danger};
@define-color destructive_fg_color {on_accent};
@define-color success_color {success};
@define-color warning_color {warning};
@define-color error_color {danger};

/* =========================================================================
   ROOT — global typography defaults + obsidian atmosphere
   ========================================================================= */
window {{
    font-family: {sans};
    color: {text_1};
    background-color: {void};
}}

window.settings-window {{
    background-color: {void};
    background-image:
        radial-gradient(58% 46% at 14% 4%, {accent_a10}, transparent 56%),
        radial-gradient(54% 44% at 100% 100%, {_rgba(accent_2, 0.07)}, transparent 58%),
        linear-gradient(180deg, #0B121C 0%, {void} 64%);
}}

label {{
    color: {text_1};
}}

.dim-label, label.dim-label {{
    color: {text_2};
}}

/* Header bar — recessed obsidian tray, top sheen, hairline foot, soft drop */
headerbar {{
    background-color: {surface_900};
    background-image: linear-gradient(180deg, rgba(22,29,40,0.34), transparent 72%);
    color: {text_1};
    border-bottom: 1px solid {line};
    box-shadow: {inset_top}, 0 1px 0 rgba(0,0,0,0.35);
}}

headerbar:backdrop {{
    background-image: none;
}}

/* Sidebar / content divider */
separator {{
    background-color: {line};
    min-width: 1px;
    min-height: 1px;
}}

/* Built-in Adwaita typography classes — editorial headers, quiet captions */
.title-1 {{ font-family: {disp}; font-size: 27px; font-weight: 800; letter-spacing: -0.8px; color: {text_0}; }}
.title-2 {{ font-family: {disp}; font-size: 20px; font-weight: 700; letter-spacing: -0.4px; color: {text_0}; }}
.title-3 {{ font-size: 15px; font-weight: 600; color: {text_0}; letter-spacing: -0.1px; }}
.heading {{ font-size: 14px; font-weight: 700; color: {text_1}; letter-spacing: 0.1px; }}
.caption {{ font-family: {mono}; font-size: 11px; color: {text_3}; letter-spacing: 0.4px; }}

/* =========================================================================
   HEADER — product mark, device status, primary action. Quiet.
   ========================================================================= */
.app-title {{
    font-family: {disp};
    font-size: 16px;
    font-weight: 800;
    color: {text_0};
    letter-spacing: -0.4px;
}}

.app-title-accent {{
    font-family: {disp};
    font-weight: 800;
    color: {accent};
}}

.app-subtitle {{
    font-family: {mono};
    font-size: 10px;
    font-weight: 500;
    color: {text_3};
    letter-spacing: 1.6px;
    text-transform: uppercase;
}}

.logo-container {{
    background: transparent;
    border-radius: 8px;
    padding: 2px;
    border: none;
    box-shadow: none;
}}

.header-divider {{
    background: {line};
    min-width: 1px;
    min-height: 20px;
    margin: 0 14px;
    border-radius: 0;
}}

/* Device badge — mono pill, quiet until it matters */
.device-badge {{
    background: {surface_800};
    border: 1px solid {line};
    border-radius: 999px;
    padding: 4px 11px;
    font-family: {mono};
    font-size: 10px;
    font-weight: 500;
    color: {text_2};
    letter-spacing: 1.2px;
    text-transform: uppercase;
}}

/* =========================================================================
   SIDEBAR — recessed tray. Active item = accent pill + rail + glow.
   ========================================================================= */
.sidebar {{
    background-color: {surface_900};
    background-image:
        linear-gradient(180deg, rgba(30,40,55,0.18), transparent 22%),
        radial-gradient(120% 28% at 50% 0%, {accent_a06}, transparent 60%);
    padding: 18px 10px 12px 10px;
    min-width: 232px;
    border-right: 1px solid {line};
    border-radius: 0;
    box-shadow: none;
}}

.nav-item {{
    padding: 10px 14px 10px 14px;
    margin: 2px 4px;
    border-radius: 10px;
    color: {text_2};
    font-family: {sans};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.1px;
    border: 1px solid transparent;
    background: transparent;
    box-shadow: none;
    transition: background 180ms cubic-bezier(0.16,1,0.3,1),
                color 180ms cubic-bezier(0.16,1,0.3,1),
                border-color 180ms cubic-bezier(0.16,1,0.3,1),
                box-shadow 180ms cubic-bezier(0.16,1,0.3,1);
}}

.nav-item:hover {{
    background: {surface_600};
    color: {text_0};
    border-color: {line_faint};
}}

.nav-item.active {{
    color: {accent_bright};
    background-color: {surface_600};
    background-image: {grad_live_soft};
    border-color: {accent_a24};
    box-shadow: {rail}, inset 0 0 0 1px {accent_a24}, 0 0 18px {accent_a16};
}}

.nav-item.active:hover {{
    color: {accent_bright};
    background-image: {grad_live_soft};
    border-color: {accent_a40};
    box-shadow: {rail}, inset 0 0 0 1px {accent_a40}, 0 0 22px {_rgba(accent, 0.20)};
}}

/* PNG nav icons — desaturate slightly so color doesn't carry meaning */
.nav-icon-img {{
    opacity: 0.74;
    transition: opacity 180ms ease;
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
    color: {text_3};
    transition: color 180ms ease;
}}

.nav-item:hover .nav-icon {{
    color: {text_1};
}}

.nav-item.active .nav-icon {{
    color: {accent};
}}

/* Page header icon (top of each page) — quiet, machined */
.page-header-icon {{
    color: {text_2};
    opacity: 0.9;
}}

/* Generated transparent assets — a lit stage: the artwork floats on a soft
   phosphor floor-glow inside a machined frame. */
.generated-asset-hero {{
    background-color: {surface_800};
    background-image:
        radial-gradient(80% 70% at 50% 116%, {accent_a16}, transparent 60%),
        linear-gradient(180deg, rgba(255,255,255,0.03), transparent 38%);
    border: 1px solid {line};
    border-radius: 16px;
    padding: 12px 14px;
    margin: 0 10px 6px 10px;
    box-shadow: {shadow_md}, {inset_top};
}}

.generated-asset-image {{
    opacity: 0.99;
}}

.radial-menu-card .generated-asset-hero {{
    background-color: {surface_700};
    border-color: {line_faint};
    padding: 8px;
    margin: -2px 0 14px 0;
    box-shadow: {inset_top};
}}

/* =========================================================================
   PANELS — machined obsidian surface: corner glow + top sheen + hairline +
   a real ambient drop shadow. This is the single biggest lift from "recolor"
   to "designed page".
   ========================================================================= */
.settings-card {{
    background-color: {surface_700};
    background-image: {card_bg_image};
    border: 1px solid {line};
    border-radius: 18px;
    padding: 20px 22px;
    margin: 10px;
    box-shadow: {card_shadow};
    transition: border-color 180ms ease, box-shadow 220ms ease;
}}

.settings-card:hover {{
    border-color: {line_strong};
    box-shadow: {card_shadow_hover};
}}

.info-card {{
    background-color: {surface_800};
    background-image: linear-gradient(180deg, rgba(255,255,255,0.018), transparent 40%);
    border: 1px solid {line_faint};
    border-radius: 18px;
    padding: 16px 18px;
    margin: 10px;
    box-shadow: {shadow_sm}, {inset_top};
}}

.info-card:hover {{
    border-color: {line};
}}

.info-card .card-title {{
    font-family: {mono};
    font-size: 11px;
    font-weight: 600;
    color: {text_3};
    letter-spacing: 1.4px;
    text-transform: uppercase;
    border-bottom: none;
    padding-bottom: 8px;
    margin-bottom: 12px;
}}

.card-title {{
    font-family: {disp};
    font-size: 17px;
    font-weight: 700;
    color: {text_0};
    letter-spacing: -0.4px;
    padding-bottom: 14px;
    margin-bottom: 16px;
    border-bottom: 1px solid {line};
}}

/* Section header — mono small-caps, groups rows inside a panel */
.section-header {{
    font-family: {mono};
    font-size: 10px;
    font-weight: 600;
    color: {text_4};
    letter-spacing: 1.8px;
    text-transform: uppercase;
    margin: 14px 0 8px 0;
}}

/* =========================================================================
   ROWS — high-density list items. Resting transparent, hover lifts.
   ========================================================================= */
.setting-row {{
    padding: 11px 12px;
    margin: 0;
    border-radius: 12px;
    background: {row_bg};
    border: 1px solid transparent;
    transition: background 180ms ease, border-color 180ms ease;
}}

.setting-row:hover {{
    background: {row_bg_hover};
    border-color: {line_faint};
}}

.setting-label {{
    color: {text_1};
    font-family: {sans};
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0;
}}

.setting-value {{
    color: {text_2};
    font-family: {mono};
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0;
}}

/* Boxed list (Adwaita) — same machined surface as our panels */
.boxed-list {{
    background-color: {surface_700};
    background-image: {card_bg_image};
    border: 1px solid {line};
    border-radius: 18px;
    box-shadow: {card_shadow};
}}

.boxed-list > row {{
    background: transparent;
    border-bottom: 1px solid {line_faint};
    transition: background 180ms ease;
}}

.boxed-list > row:last-child {{
    border-bottom: none;
}}

.boxed-list > row:hover {{
    background: {row_bg_hover};
}}

.boxed-list > row:selected {{
    background-color: {accent_a10};
    box-shadow: {rail};
}}

/* =========================================================================
   STATUS BAR — minimal foot. Battery, connection, version.
   ========================================================================= */
.status-bar {{
    background-color: {surface_900};
    background-image: linear-gradient(180deg, rgba(22,29,40,0.30), transparent 80%);
    padding: 10px 22px;
    border-top: 1px solid {line};
    box-shadow: {inset_top};
}}

.battery-icon {{
    color: {accent};
    opacity: 1.0;
    text-shadow: 0 0 8px {accent_a40};
}}

.battery-indicator {{
    color: {accent};
    font-family: {mono};
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.3px;
    text-shadow: 0 0 10px {accent_a60};
}}

.battery-pill {{
    background: {accent_a10};
    border: 1px solid {accent_a24};
    border-radius: 999px;
    padding: 4px 13px;
    box-shadow: 0 0 16px {accent_a24};
}}

.connection-icon {{
    color: {text_2};
    opacity: 0.85;
}}

.connection-status {{
    color: {text_2};
    font-family: {sans};
    font-size: 12px;
    font-weight: 500;
}}

.connection-dot {{
    min-width: 9px;
    min-height: 9px;
    border-radius: 50%;
    background: {text_4};
}}

/* connected = the live state -> success glow */
.connection-dot.connected {{
    background: {success};
    box-shadow: 0 0 8px {_rgba(success, 0.65)};
}}

/* inactive slot -> quiet grey dot, never an alarm red */
.connection-dot.disconnected {{
    background: {text_3};
}}

/* =========================================================================
   SWITCH — OFF quiet machined pill; ON = live gradient + halo glow.
   ========================================================================= */
switch {{
    background-color: {surface_500};
    background-image: none;
    border: 1px solid {line};
    border-radius: 999px;
    min-width: 48px;
    min-height: 26px;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.45);
    transition: background 240ms cubic-bezier(0.2,0.8,0.2,1), border-color 240ms ease, box-shadow 240ms ease;
}}

switch:hover {{
    border-color: {line_strong};
}}

switch:checked {{
    background-color: {accent};
    background-image: {grad_live};
    border-color: transparent;
    box-shadow: {glow_xs}, {inset_top};
}}

switch slider {{
    background-image: radial-gradient(circle at 50% 35%, #EAF1F6, {text_2});
    border-radius: 50%;
    min-width: 20px;
    min-height: 20px;
    margin: 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.5);
    transition: background 240ms ease;
}}

switch:checked slider {{
    background-image: radial-gradient(circle at 50% 35%, #0A2C24, {on_accent});
    box-shadow: 0 0 8px rgba(4,32,26,0.5);
}}

/* =========================================================================
   SCALES / SLIDERS — quiet machined track; the energy fill + thumb light up.
   margins are forced to 0 so no inherited (negative) Adwaita slider margin
   can shrink a gizmo below zero. (See scrollbar note below.)
   ========================================================================= */
scale {{
    padding: 6px 0;
    min-height: 26px;
}}

scale trough {{
    background-color: {surface_500};
    border: 1px solid {line_faint};
    border-radius: 999px;
    min-height: 8px;
    margin: 0;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.5);
}}

scale highlight {{
    background-color: {accent};
    background-image: {grad_live};
    border-radius: 999px;
    margin: 0;
    box-shadow: {glow_xs}, inset 0 1px 0 rgba(255,255,255,0.30);
}}

scale slider {{
    background-image: radial-gradient(circle at 50% 35%, #FFFFFF, {text_1});
    border-radius: 50%;
    min-width: 18px;
    min-height: 18px;
    margin: 0;
    box-shadow: 0 0 0 4px rgba(4,6,10,0.7), {shadow_sm};
    transition: box-shadow 180ms ease;
}}

scale slider:hover {{
    box-shadow: 0 0 0 4px rgba(4,6,10,0.7), {glow_sm};
}}

scale:focus slider {{
    box-shadow: 0 0 0 4px rgba(4,6,10,0.7), {glow_sm};
}}

/* scale tick marks + value, when present */
scale marks,
scale value {{
    color: {text_3};
    font-family: {mono};
    font-size: 10px;
}}

scale indicator {{
    background-color: {line_strong};
    min-width: 1px;
    min-height: 5px;
}}

/* =========================================================================
   SCROLLBAR — invisible until needed.
   NOTE: Adwaita's default scrollbar `slider` carries a NEGATIVE margin (it
   overhangs a wider trough). Combined with a small min-size that produced a
   negative gizmo min ("slider reported min height -10"). We pin margin: 0 so
   the slider's min size stays exactly its min-width/height — never negative.
   ========================================================================= */
scrollbar {{
    background: transparent;
    border: none;
}}

scrollbar slider {{
    background: {line_strong};
    border: none;
    border-radius: 999px;
    min-width: 8px;
    min-height: 8px;
    margin: 0;
    transition: background 180ms ease, min-width 180ms ease, min-height 180ms ease;
}}

scrollbar slider:hover {{
    background: {line_bright};
    min-width: 10px;
    min-height: 10px;
}}

/* =========================================================================
   BUTTONS — primary glows (live), the rest stay quiet hairline controls.
   ========================================================================= */
.primary-btn, button.suggested-action {{
    background-color: {accent};
    background-image: {grad_live};
    color: {on_accent};
    border: none;
    border-radius: 10px;
    padding: 9px 16px;
    font-family: {sans};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0;
    box-shadow: {glow_xs}, {inset_top};
    transition: box-shadow 180ms ease, background 180ms ease;
}}

.primary-btn:hover, button.suggested-action:hover {{
    background-image: {grad_live};
    box-shadow: {glow_sm}, {inset_top};
}}

.primary-btn:active, button.suggested-action:active {{
    box-shadow: {inset_top};
}}

.secondary-btn {{
    background: transparent;
    color: {text_1};
    border: 1px solid {line_strong};
    border-radius: 10px;
    padding: 8px 14px;
    font-family: {sans};
    font-weight: 600;
    font-size: 13px;
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
}}

.secondary-btn:hover {{
    background: {row_bg_hover};
    border-color: {accent_a40};
    color: {text_0};
}}

.danger-btn, button.destructive-action {{
    background: transparent;
    color: {danger};
    border: 1px solid {line_strong};
    border-radius: 10px;
    padding: 8px 14px;
    font-family: {sans};
    font-weight: 600;
    font-size: 13px;
    transition: background 180ms ease, border-color 180ms ease;
}}

.danger-btn:hover, button.destructive-action:hover {{
    background: {_rgba(danger, 0.10)};
    border-color: {danger};
    color: {danger};
}}

/* "Add" affordance — dashed hairline, arms to phosphor on hover */
.add-app-btn {{
    background: transparent;
    color: {text_2};
    border: 1px dashed {line_strong};
    border-radius: 12px;
    padding: 8px 14px;
    font-family: {sans};
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.2px;
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
}}

.add-app-btn:hover {{
    background: {accent_a06};
    border-color: {accent_a40};
    color: {accent_bright};
}}

button.flat {{
    background: transparent;
    border: none;
    color: {text_1};
    border-radius: 8px;
    padding: 6px 10px;
    transition: background 180ms ease, color 180ms ease;
}}

button.flat:hover {{
    background: {row_bg_hover};
    color: {text_0};
}}

button.circular {{
    background: transparent;
    border: 1px solid {line};
    border-radius: 999px;
    color: {text_2};
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
}}

button.circular:hover {{
    background: {row_bg_hover};
    border-color: {line_strong};
    color: {text_0};
}}

/* =========================================================================
   SEGMENTED / LINKED — the wheel-mode selector. Cells are quiet; the
   checked cell becomes the one live gradient segment (light is state).
   ========================================================================= */
.linked {{
    border-radius: 12px;
    background-color: {surface_700};
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.40), {inset_edge};
    padding: 3px;
}}

.linked > button {{
    background: transparent;
    background-image: none;
    color: {text_2};
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 8px 14px;
    font-family: {sans};
    font-size: 13px;
    font-weight: 600;
    box-shadow: none;
    transition: background 180ms ease, color 180ms ease, box-shadow 180ms ease;
}}

.linked > button:hover {{
    background: {surface_600};
    color: {text_0};
}}

.linked > button:checked {{
    color: {on_accent};
    background-color: {accent};
    background-image: {grad_live};
    border-color: transparent;
    box-shadow: {glow_xs}, {inset_top};
}}

.linked > button:checked:hover {{
    background-image: {grad_live};
    box-shadow: {glow_sm}, {inset_top};
}}

/* keep the rounded ends of the group */
.linked > *:first-child {{ border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}
.linked > *:last-child {{ border-top-right-radius: 9px; border-bottom-right-radius: 9px; }}

/* =========================================================================
   DROPDOWN, ENTRY, SPINBUTTON, TOOLTIP — focused control glows phosphor.
   ========================================================================= */
dropdown {{
    background-color: {surface_700};
    border: 1px solid {line_strong};
    border-radius: 10px;
    padding: 6px 12px;
    color: {text_1};
    font-family: {sans};
    font-size: 13px;
    box-shadow: {inset_top};
    transition: border-color 180ms ease, background 180ms ease;
}}

dropdown:hover {{
    border-color: {accent_a40};
}}

dropdown popover {{
    background-color: {surface_700};
    border: 1px solid {line_strong};
    border-radius: 12px;
    box-shadow: {shadow_lg}, {inset_top};
    padding: 4px;
}}

dropdown popover listview row {{
    padding: 8px 12px;
    border-radius: 8px;
    color: {text_1};
    font-size: 13px;
}}

dropdown popover listview row:hover {{
    background: {row_bg_hover};
}}

dropdown popover listview row:selected {{
    background-color: {accent_a16};
    color: {accent_bright};
}}

entry {{
    background-color: {surface_800};
    border: 1px solid {line_strong};
    border-radius: 10px;
    padding: 8px 12px;
    color: {text_1};
    font-family: {sans};
    font-size: 13px;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.35);
    transition: border-color 180ms ease, box-shadow 180ms ease;
}}

entry:focus, entry:focus-within {{
    border-color: {accent};
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.35), {focus_glow};
}}

entry > text > selection {{
    background-color: {accent_a40};
    color: {text_0};
}}

/* SpinButton — numeric stepper (gaming DPI, manual DPI). Mono digits. */
spinbutton {{
    background-color: {surface_800};
    border: 1px solid {line_strong};
    border-radius: 10px;
    color: {text_0};
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.35);
    transition: border-color 180ms ease, box-shadow 180ms ease;
}}

spinbutton:focus-within {{
    border-color: {accent};
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.35), {focus_glow};
}}

spinbutton > text {{
    color: {text_0};
    font-family: {mono};
    font-size: 13px;
    font-weight: 500;
}}

spinbutton button {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {text_2};
    min-width: 26px;
    box-shadow: none;
    transition: background 180ms ease, color 180ms ease;
}}

spinbutton button:hover {{
    background: {accent_a06};
    color: {accent_bright};
}}

tooltip {{
    background-color: {surface_700};
    border: 1px solid {line_strong};
    border-radius: 10px;
    padding: 6px 10px;
    box-shadow: {shadow_md};
    color: {text_1};
    font-size: 12px;
}}

/* =========================================================================
   BUTTON ASSIGNMENTS — the table users live in. Mono values, hairline rows.
   ========================================================================= */
.button-assignment-card {{
    background-color: {surface_700};
    background-image: {card_bg_image};
    border: 1px solid {line};
    border-radius: 18px;
    padding: 8px;
    margin: 6px 0;
    box-shadow: {card_shadow};
}}

.button-assignment-header {{
    font-family: {mono};
    font-size: 10px;
    font-weight: 600;
    color: {text_4};
    letter-spacing: 1.8px;
    text-transform: uppercase;
    padding: 12px 12px 8px 12px;
    margin: 0;
    border-bottom: 1px solid {line_faint};
}}

.button-row {{
    background: transparent;
    border-radius: 12px;
    padding: 10px 12px;
    margin: 1px 0;
    border: 1px solid transparent;
    transition: background 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}}

.button-row:hover {{
    background: {row_bg_hover};
    border-color: {line_faint};
}}

.button-icon-box {{
    background: {surface_600};
    border-radius: 10px;
    padding: 6px;
    min-width: 28px;
    min-height: 28px;
    border: 1px solid {line_faint};
    box-shadow: {inset_top};
    transition: border-color 180ms ease, background 180ms ease;
}}

.button-icon {{
    color: {text_2};
}}

.button-row:hover .button-icon {{
    color: {text_0};
}}

.button-row:hover .button-icon-box {{
    border-color: {line};
}}

.button-name {{
    font-family: {sans};
    font-size: 14px;
    font-weight: 600;
    color: {text_1};
    letter-spacing: 0;
}}

.button-action {{
    font-family: {mono};
    font-size: 11px;
    font-weight: 500;
    color: {text_2};
    padding: 3px 8px;
    background: {chip_bg};
    border-radius: 6px;
    border: 1px solid {chip_border};
    letter-spacing: 0;
}}

.button-arrow {{
    color: {text_4};
    padding: 4px;
    border-radius: 6px;
    transition: color 180ms ease, background 180ms ease;
}}

.button-row:hover .button-arrow {{
    color: {text_1};
}}

.button-arrow:hover {{
    background: {row_bg_active};
    color: {text_0};
}}

/* =========================================================================
   RADIAL MENU CARD — the "Actions Ring" preview. The one featured live object.
   ========================================================================= */
.radial-menu-card {{
    background-color: {surface_800};
    background-image:
        radial-gradient(90% 70% at 50% 0%, rgba(30,40,55,0.36), transparent 62%),
        radial-gradient(60% 60% at 50% 120%, {accent_a10}, transparent 66%);
    border: 1px solid {line};
    border-radius: 18px;
    padding: 16px 18px;
    margin: 6px 0;
    box-shadow: {card_shadow};
    transition: border-color 180ms ease, box-shadow 220ms ease;
}}

.radial-menu-card:hover {{
    border-color: {accent_a24};
    box-shadow: {card_shadow_hover};
}}

.radial-icon-large {{
    background-color: {surface_700};
    background-image: radial-gradient(circle at 50% 36%, {accent_a16}, transparent 62%);
    border: 1px solid {accent_a40};
    border-radius: 12px;
    padding: 10px;
    min-width: 40px;
    min-height: 40px;
    box-shadow: {glow_xs}, {inset_top};
}}

.radial-icon-large image {{
    color: {accent};
}}

.radial-title {{
    font-family: {disp};
    font-size: 15px;
    font-weight: 700;
    color: {text_0};
    letter-spacing: -0.2px;
}}

.radial-subtitle {{
    font-family: {sans};
    font-size: 12px;
    color: {text_3};
    margin-top: 2px;
}}

/* Slice rows inside the radial action editor */
.slice-row {{
    background: transparent;
    border-radius: 10px;
    padding: 8px 10px;
    border: 1px solid transparent;
    transition: background 180ms ease, border-color 180ms ease;
}}

.slice-row:hover {{
    background: {row_bg_hover};
    border-color: {line_faint};
}}

.slice-icon {{
    color: {text_2};
    opacity: 0.9;
}}

.slice-label {{
    font-family: {sans};
    font-size: 13px;
    font-weight: 600;
    color: {text_1};
}}

.slice-edit-btn {{
    opacity: 0;
    transition: opacity 180ms ease;
}}

.slice-row:hover .slice-edit-btn {{
    opacity: 1;
}}

/* Color picker swatches for slice colors (per-slice identity hues) */
.color-btn-green   {{ background: #46E0A0; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-yellow  {{ background: #FFB454; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-red     {{ background: #FF6B7A; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-mauve   {{ background: #B98BFF; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-blue    {{ background: #5BA8FF; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-pink    {{ background: #FF86C2; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-sapphire{{ background: #46D6FF; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}
.color-btn-teal    {{ background: #3FE0D0; border-radius: 8px; border: 2px solid transparent; min-width: 22px; min-height: 22px; }}

.color-btn-green:checked,
.color-btn-yellow:checked,
.color-btn-red:checked,
.color-btn-mauve:checked,
.color-btn-blue:checked,
.color-btn-pink:checked,
.color-btn-sapphire:checked,
.color-btn-teal:checked {{
    border-color: {text_0};
    box-shadow: 0 0 0 2px {void} inset, 0 0 12px rgba(255,255,255,0.22);
}}

/* Preset / palette action buttons */
.preset-btn, .palette-action-btn {{
    background: transparent;
    border: 1px solid {line};
    border-radius: 10px;
    padding: 6px 10px;
    color: {text_1};
    font-family: {sans};
    font-size: 12px;
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
}}

.preset-btn:hover, .palette-action-btn:hover {{
    background: {row_bg_hover};
    border-color: {accent_a40};
    color: {text_0};
}}

.preset-btn.selected, .palette-action-btn.selected {{
    color: {accent};
    background: {accent_a10};
    border-color: {accent_a40};
    box-shadow: inset 0 0 0 1px {accent_a40}, 0 0 14px {accent_a16};
}}

/* =========================================================================
   HAPTICS — actuator-trace panel, readouts, eyebrows, live badge.
   ========================================================================= */
.section-eyebrow {{
    font-family: {mono};
    font-size: 11px;
    letter-spacing: 1.6px;
    color: {text_3};
}}
.page-display-title {{
    font-family: {disp};
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.5px;
    color: {text_0};
}}
.live-badge {{
    font-family: {mono};
    font-size: 10px;
    letter-spacing: 1.2px;
    color: {accent};
    background: {accent_a10};
    border: 1px solid {accent_a24};
    border-radius: 999px;
    padding: 2px 10px;
}}
.waveform-trace {{
    background-color: {surface_900};
    background-image: linear-gradient(180deg, {accent_a06}, transparent 62%);
    border: 1px solid {line};
    border-radius: 14px;
}}
.haptic-readout-label {{
    font-family: {mono};
    font-size: 10px;
    letter-spacing: 1.2px;
    color: {text_3};
}}
.haptic-readout-num {{
    font-family: {disp};
    font-size: 22px;
    font-weight: 600;
    color: {text_0};
}}

/* =========================================================================
   EASY-SWITCH — keyboard shortcut hints. Mono so the keys read like keys.
   ========================================================================= */
.easyswitch-shortcuts-card {{
    background-color: {surface_800};
    background-image: linear-gradient(180deg, rgba(255,255,255,0.02), transparent 40%);
    border: 1px solid {line};
    border-radius: 18px;
    padding: 14px 16px;
    margin: 6px 0;
    box-shadow: {shadow_sm}, {inset_top};
}}

.easyswitch-row {{
    padding: 6px 0;
    border-bottom: 1px solid {line_faint};
}}

.easyswitch-row:last-child {{
    border-bottom: none;
}}

.easyswitch-icon-box {{
    background: {surface_700};
    border: 1px solid {line_faint};
    border-radius: 10px;
    padding: 6px;
    min-width: 32px;
    min-height: 32px;
    box-shadow: {inset_top};
}}

.easyswitch-icon {{
    color: {text_2};
}}

.easyswitch-title {{
    font-family: {sans};
    font-size: 13px;
    font-weight: 600;
    color: {text_1};
    letter-spacing: 0;
}}

.easyswitch-desc {{
    font-size: 11px;
    color: {text_3};
    font-family: {mono};
}}

/* =========================================================================
   HAPTIC PATTERN ROWS — selected row gets the accent rail + faint glow.
   ========================================================================= */
.haptic-pattern-item {{
    padding: 10px 12px;
    margin: 1px 0;
    border-radius: 12px;
    background: transparent;
    border: 1px solid transparent;
    transition: background 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}}

.haptic-pattern-item:hover {{
    background: {row_bg_hover};
    border-color: {line_faint};
}}

.haptic-pattern-item.selected {{
    background-color: {accent_a10};
    border: 1px solid {accent_a24};
    box-shadow: {rail}, inset 0 0 0 1px {accent_a24}, 0 0 18px {_rgba(accent, 0.12)};
}}

/* =========================================================================
   MACRO TIMELINE — frames in a strip. Selection: accent tint + rail.
   ========================================================================= */
.timeline-row {{
    padding: 8px 12px;
    border-radius: 12px;
    background: transparent;
    border: 1px solid transparent;
    transition: background 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}}

.timeline-row:hover {{
    background: {row_bg_hover};
    border-color: {line_faint};
}}

.timeline-row-selected {{
    background-color: {accent_a10};
    border: 1px solid {accent_a24};
    box-shadow: {rail}, inset 0 0 0 1px {accent_a24}, 0 0 18px {_rgba(accent, 0.12)};
}}

/* =========================================================================
   DONATE — sidebar bottom card. Quiet, but humanly warm.
   ========================================================================= */
.donate-card {{
    background-color: {surface_800};
    background-image: linear-gradient(180deg, rgba(255,255,255,0.02), transparent 40%);
    border: 1px solid {line};
    border-radius: 16px;
    padding: 12px;
    box-shadow: {shadow_sm}, {inset_top};
}}

.donate-btn {{
    background: transparent;
    color: {text_1};
    border: 1px solid {line_strong};
    border-radius: 10px;
    padding: 8px 14px;
    font-family: {sans};
    font-weight: 600;
    font-size: 12px;
    box-shadow: none;
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
}}

.donate-btn:hover {{
    background: {row_bg_hover};
    border-color: {accent_a40};
    color: {text_0};
}}

.donate-heart {{
    min-width: 32px;
    min-height: 32px;
}}

/* =========================================================================
   STATUS / SEMANTIC TINTS — muted; a green/red label is info, not an alarm.
   ========================================================================= */
.success {{
    color: {success};
}}

.warning {{
    color: {warning};
}}

.accent, .accent-color {{
    color: {accent};
}}

/* Generic badge — small uppercase mono pill */
.badge {{
    background: {chip_bg};
    border: 1px solid {chip_border};
    border-radius: 999px;
    padding: 2px 9px;
    font-family: {mono};
    font-size: 10px;
    font-weight: 600;
    color: {text_2};
    letter-spacing: 1.2px;
    text-transform: uppercase;
}}

/* a badge that signals a live / connected state */
.badge.success {{
    color: {accent_bright};
    background: {accent_a10};
    border-color: {accent_a24};
    box-shadow: {glow_xs};
}}

/* Generic catch-all card class (libadwaita .card) */
.card {{
    background-color: {surface_700};
    background-image: {card_bg_image};
    border: 1px solid {line};
    border-radius: 18px;
    box-shadow: {card_shadow};
}}

/* Generic background helper */
.background {{
    background-color: {surface_800};
}}

/* =========================================================================
   FOCUS — phosphor focus ring on every interactive widget (light is state).
   ========================================================================= */
button:focus-visible,
.nav-item:focus-visible,
.button-row:focus-visible,
.setting-row:focus-visible,
.haptic-pattern-item:focus-visible,
.timeline-row:focus-visible,
.preset-btn:focus-visible,
.add-app-btn:focus-visible,
.linked > button:focus-visible,
dropdown:focus-visible,
switch:focus-visible {{
    outline: none;
    box-shadow: {focus_glow};
}}
"""
