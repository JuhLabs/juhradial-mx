#!/usr/bin/env python3
"""
Generate promotional radial menu image for README/screenshots.
Uses Cairo for high-quality vector rendering.
"""

import cairo
import math
import os

# Output settings
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "../assets/screenshots/radial-menu.png")
IMAGE_SIZE = 600
MENU_RADIUS = 200
CENTER_ZONE_RADIUS = 60
ICON_ZONE_RADIUS = 135
SHADOW_BLUR = 20

# Catppuccin Mocha colors (RGB tuples)
COLORS = {
    'crust':    (17/255, 17/255, 27/255),
    'base':     (30/255, 30/255, 46/255),
    'surface0': (49/255, 50/255, 68/255),
    'surface1': (69/255, 71/255, 90/255),
    'surface2': (88/255, 91/255, 112/255),
    'text':     (205/255, 214/255, 244/255),
    'subtext1': (186/255, 194/255, 222/255),
    'lavender': (180/255, 190/255, 254/255),
    'blue':     (137/255, 180/255, 250/255),
    'sapphire': (116/255, 199/255, 236/255),
    'teal':     (148/255, 226/255, 213/255),
    'green':    (166/255, 227/255, 161/255),
    'yellow':   (249/255, 226/255, 175/255),
    'peach':    (250/255, 179/255, 135/255),
    'mauve':    (203/255, 166/255, 247/255),
    'pink':     (245/255, 194/255, 231/255),
    'red':      (243/255, 139/255, 168/255),
}

# Actions with colors and icons
ACTIONS = [
    ("Play/Pause", "green",    "play_pause"),
    ("New Note",   "yellow",   "note"),
    ("Lock",       "red",      "lock"),
    ("Settings",   "mauve",    "settings"),
    ("Screenshot", "blue",     "screenshot"),
    ("Emoji",      "pink",     "emoji"),
    ("Files",      "sapphire", "folder"),
    ("AI",         "teal",     "ai"),
]

def draw_icon(cr, cx, cy, icon_type, size, color):
    """Draw an icon at the specified position."""
    cr.set_source_rgba(*color, 1.0)
    cr.set_line_width(3)

    if icon_type == "play_pause":
        # Play triangle
        s = size * 0.5
        cr.move_to(cx - s * 0.35, cy - s)
        cr.line_to(cx + s * 0.7, cy)
        cr.line_to(cx - s * 0.35, cy + s)
        cr.close_path()
        cr.fill()

    elif icon_type == "note":
        # Notepad
        w, h = size * 0.6, size * 0.8
        cr.rectangle(cx - w/2, cy - h/2, w, h)
        cr.stroke()
        for i in range(3):
            y = cy - h/4 + i * size * 0.2
            cr.move_to(cx - w/3, y)
            cr.line_to(cx + w/3, y)
            cr.stroke()

    elif icon_type == "lock":
        # Padlock body
        w, h = size * 0.55, size * 0.45
        cr.rectangle(cx - w/2, cy, w, h)
        cr.stroke()
        # Shackle
        cr.arc(cx, cy, w * 0.35, math.pi, 0)
        cr.stroke()

    elif icon_type == "settings":
        # Gear
        cr.arc(cx, cy, size * 0.15, 0, 2 * math.pi)
        cr.stroke()
        for i in range(6):
            angle = i * math.pi / 3
            inner, outer = size * 0.25, size * 0.45
            x1 = cx + inner * math.cos(angle)
            y1 = cy + inner * math.sin(angle)
            x2 = cx + outer * math.cos(angle)
            y2 = cy + outer * math.sin(angle)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

    elif icon_type == "screenshot":
        # Camera/screen capture
        w, h = size * 0.7, size * 0.5
        cr.rectangle(cx - w/2, cy - h/2, w, h)
        cr.stroke()
        # Viewfinder
        cr.arc(cx, cy, size * 0.15, 0, 2 * math.pi)
        cr.stroke()

    elif icon_type == "emoji":
        # Smiley face
        cr.arc(cx, cy, size * 0.4, 0, 2 * math.pi)
        cr.stroke()
        # Eyes
        cr.arc(cx - size * 0.15, cy - size * 0.1, size * 0.05, 0, 2 * math.pi)
        cr.fill()
        cr.arc(cx + size * 0.15, cy - size * 0.1, size * 0.05, 0, 2 * math.pi)
        cr.fill()
        # Smile
        cr.arc(cx, cy + size * 0.05, size * 0.2, 0.2, math.pi - 0.2)
        cr.stroke()

    elif icon_type == "folder":
        # Folder icon
        w, h = size * 0.7, size * 0.55
        # Folder tab
        cr.move_to(cx - w/2, cy - h/2)
        cr.line_to(cx - w/2, cy - h/2 - size * 0.1)
        cr.line_to(cx - w/4, cy - h/2 - size * 0.1)
        cr.line_to(cx - w/6, cy - h/2)
        cr.stroke()
        # Folder body
        cr.rectangle(cx - w/2, cy - h/2, w, h)
        cr.stroke()

    elif icon_type == "ai":
        # Brain/AI sparkle
        cr.arc(cx, cy, size * 0.3, 0, 2 * math.pi)
        cr.stroke()
        # Sparkles
        for i in range(4):
            angle = i * math.pi / 2 + math.pi / 4
            x1 = cx + size * 0.35 * math.cos(angle)
            y1 = cy + size * 0.35 * math.sin(angle)
            x2 = cx + size * 0.5 * math.cos(angle)
            y2 = cy + size * 0.5 * math.sin(angle)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

def draw_slice(cr, cx, cy, index, highlighted=False):
    """Draw a radial menu slice."""
    action = ACTIONS[index]
    accent_color = COLORS[action[1]]

    start_angle = math.radians(index * 45 - 22.5 - 90)
    end_angle = start_angle + math.radians(45)
    outer_r = MENU_RADIUS - 8
    inner_r = CENTER_ZONE_RADIUS + 8

    # Draw slice path
    cr.new_path()
    cr.arc(cx, cy, outer_r, start_angle, end_angle)
    cr.arc_negative(cx, cy, inner_r, end_angle, start_angle)
    cr.close_path()

    # Fill slice
    if highlighted:
        cr.set_source_rgba(1, 1, 1, 0.15)
    else:
        cr.set_source_rgba(*COLORS['surface0'], 0.4)
    cr.fill_preserve()

    # Stroke slice
    if highlighted:
        cr.set_source_rgba(1, 1, 1, 0.5)
        cr.set_line_width(2)
    else:
        cr.set_source_rgba(*COLORS['surface2'], 0.3)
        cr.set_line_width(1)
    cr.stroke()

    # Icon position
    icon_angle = math.radians(index * 45 - 90)
    icon_x = cx + ICON_ZONE_RADIUS * math.cos(icon_angle)
    icon_y = cy + ICON_ZONE_RADIUS * math.sin(icon_angle)
    icon_radius = 35

    # Icon circle glow for highlighted
    if highlighted:
        cr.arc(icon_x, icon_y, icon_radius + 4, 0, 2 * math.pi)
        cr.set_source_rgba(*accent_color, 0.4)
        cr.fill()

    # Icon circle background
    cr.arc(icon_x, icon_y, icon_radius, 0, 2 * math.pi)
    if highlighted:
        cr.set_source_rgba(*COLORS['surface2'], 1.0)
    else:
        cr.set_source_rgba(*COLORS['surface1'], 0.9)
    cr.fill()

    # Draw the icon
    icon_color = COLORS['text'] if highlighted else COLORS['subtext1']
    draw_icon(cr, icon_x, icon_y, action[2], icon_radius * 0.65, icon_color)

def generate_radial_menu():
    """Generate the promotional radial menu image."""
    # Create surface with transparency
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, IMAGE_SIZE, IMAGE_SIZE)
    cr = cairo.Context(surface)

    cx, cy = IMAGE_SIZE / 2, IMAGE_SIZE / 2

    # Transparent background
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()

    # Shadow
    cr.arc(cx + 6, cy + 8, MENU_RADIUS, 0, 2 * math.pi)
    cr.set_source_rgba(0, 0, 0, 0.4)
    cr.fill()

    # Main background circle
    cr.arc(cx, cy, MENU_RADIUS, 0, 2 * math.pi)
    cr.set_source_rgba(*COLORS['base'], 0.95)
    cr.fill()

    # Outer border
    cr.arc(cx, cy, MENU_RADIUS, 0, 2 * math.pi)
    cr.set_source_rgba(*COLORS['surface2'], 0.6)
    cr.set_line_width(2)
    cr.stroke()

    # Draw slices (highlight slice 7 = AI for the promo shot)
    for i in range(8):
        draw_slice(cr, cx, cy, i, highlighted=(i == 7))

    # Center circle - background
    cr.arc(cx, cy, CENTER_ZONE_RADIUS, 0, 2 * math.pi)
    cr.set_source_rgba(*COLORS['crust'], 0.9)
    cr.fill()

    # Center circle - border
    cr.arc(cx, cy, CENTER_ZONE_RADIUS, 0, 2 * math.pi)
    cr.set_source_rgba(*COLORS['surface2'], 0.5)
    cr.set_line_width(2)
    cr.stroke()

    # Center logo/text
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(18)
    cr.set_source_rgba(*COLORS['text'], 1.0)
    text = "MX"
    extents = cr.text_extents(text)
    cr.move_to(cx - extents.width/2, cy + extents.height/3)
    cr.show_text(text)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    # Save
    surface.write_to_png(OUTPUT_PATH)
    print(f"Generated: {OUTPUT_PATH}")

    # Also generate a version with dark background for better visibility
    surface_bg = cairo.ImageSurface(cairo.FORMAT_ARGB32, IMAGE_SIZE, IMAGE_SIZE)
    cr_bg = cairo.Context(surface_bg)

    # Dark gradient background
    gradient = cairo.RadialGradient(cx, cy, 0, cx, cy, IMAGE_SIZE * 0.7)
    gradient.add_color_stop_rgba(0, *COLORS['base'], 1.0)
    gradient.add_color_stop_rgba(1, *COLORS['crust'], 1.0)
    cr_bg.set_source(gradient)
    cr_bg.paint()

    # Draw the menu on top
    cr_bg.set_source_surface(surface, 0, 0)
    cr_bg.paint()

    output_bg = OUTPUT_PATH.replace('.png', '-dark.png')
    surface_bg.write_to_png(output_bg)
    print(f"Generated: {output_bg}")

if __name__ == "__main__":
    generate_radial_menu()
