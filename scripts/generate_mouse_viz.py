#!/usr/bin/env python3
"""
Generate mouse visualization image for README/screenshots.
Shows MX Master 4 with labeled interactive buttons.
"""
import cairo
import math
import os

# Output path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "..", "assets", "screenshots", "mouse-viz.png")

# Canvas size
WIDTH = 800
HEIGHT = 600

# Colors
BG_COLOR = (0.08, 0.08, 0.12)  # Dark background
MOUSE_BODY = (0.22, 0.22, 0.28)
MOUSE_DARK = (0.15, 0.15, 0.20)
MOUSE_LIGHT = (0.30, 0.30, 0.38)
ACCENT = (0.4, 0.6, 1.0)  # Blue accent
ACCENT_GLOW = (0.4, 0.6, 1.0, 0.3)
TEXT_COLOR = (0.9, 0.9, 0.95)
LABEL_BG = (0.15, 0.15, 0.22, 0.9)


def draw_mouse(ctx, cx, cy, scale=1.0):
    """Draw MX Master 4 mouse."""
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(scale, scale)

    # Shadow
    ctx.set_source_rgba(0, 0, 0, 0.4)
    ctx.arc(10, 20, 130, 0, 2 * math.pi)
    ctx.fill()

    # Main body
    gradient = cairo.LinearGradient(-100, -150, 100, 150)
    gradient.add_color_stop_rgb(0, *MOUSE_LIGHT)
    gradient.add_color_stop_rgb(0.5, *MOUSE_BODY)
    gradient.add_color_stop_rgb(1, *MOUSE_DARK)
    ctx.set_source(gradient)
    ctx.arc(0, 0, 120, 0, 2 * math.pi)
    ctx.fill()

    # Top highlight
    gradient = cairo.LinearGradient(0, -120, 0, 0)
    gradient.add_color_stop_rgba(0, 1, 1, 1, 0.15)
    gradient.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(gradient)
    ctx.arc(0, -20, 100, 0, 2 * math.pi)
    ctx.fill()

    # Scroll wheel area
    ctx.set_source_rgb(*MOUSE_DARK)
    ctx.rectangle(-20, -110, 40, 60)
    ctx.fill()

    # Scroll wheel
    ctx.set_source_rgb(*MOUSE_LIGHT)
    ctx.rectangle(-12, -100, 24, 40)
    ctx.fill()

    # Scroll wheel grooves
    ctx.set_source_rgb(*MOUSE_DARK)
    ctx.set_line_width(2)
    for y in range(-95, -55, 10):
        ctx.move_to(-8, y)
        ctx.line_to(8, y)
        ctx.stroke()

    # Thumb rest
    ctx.set_source_rgb(*MOUSE_DARK)
    ctx.save()
    ctx.translate(-90, 20)
    ctx.scale(0.5, 1.0)
    ctx.arc(0, 0, 80, 0, 2 * math.pi)
    ctx.restore()
    ctx.fill()

    # Thumb buttons (back/forward)
    ctx.set_source_rgb(*MOUSE_BODY)
    ctx.rectangle(-75, -50, 35, 18)
    ctx.fill()
    ctx.rectangle(-75, -25, 35, 18)
    ctx.fill()

    # Gesture button (highlighted)
    ctx.set_source_rgba(*ACCENT_GLOW)
    ctx.arc(-80, 35, 25, 0, 2 * math.pi)
    ctx.fill()
    ctx.set_source_rgb(*ACCENT)
    ctx.arc(-80, 35, 18, 0, 2 * math.pi)
    ctx.fill()

    # Horizontal scroll
    ctx.set_source_rgb(*MOUSE_LIGHT)
    ctx.rectangle(-100, 70, 40, 10)
    ctx.fill()

    # Mode shift button
    ctx.set_source_rgb(*MOUSE_BODY)
    ctx.arc(20, -45, 10, 0, 2 * math.pi)
    ctx.fill()

    # Logo
    ctx.set_source_rgba(0.5, 0.5, 0.6, 0.5)
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(12)
    ctx.move_to(-12, 70)
    ctx.show_text("logi")

    ctx.restore()


def draw_label(ctx, x, y, text, anchor="left", highlight=False):
    """Draw a label with background."""
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(14)

    extents = ctx.text_extents(text)
    padding = 8

    # Calculate position based on anchor
    if anchor == "right":
        text_x = x - extents.width - padding
    elif anchor == "center":
        text_x = x - extents.width / 2
    else:
        text_x = x + padding

    text_y = y + extents.height / 2

    # Background
    bg_x = text_x - padding
    bg_y = y - extents.height / 2 - padding / 2
    bg_w = extents.width + padding * 2
    bg_h = extents.height + padding

    if highlight:
        ctx.set_source_rgba(*ACCENT, 0.2)
    else:
        ctx.set_source_rgba(*LABEL_BG)

    # Rounded rectangle
    radius = 4
    ctx.new_path()
    ctx.arc(bg_x + radius, bg_y + radius, radius, math.pi, 1.5 * math.pi)
    ctx.arc(bg_x + bg_w - radius, bg_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
    ctx.arc(bg_x + bg_w - radius, bg_y + bg_h - radius, radius, 0, 0.5 * math.pi)
    ctx.arc(bg_x + radius, bg_y + bg_h - radius, radius, 0.5 * math.pi, math.pi)
    ctx.close_path()
    ctx.fill()

    # Border for highlighted
    if highlight:
        ctx.set_source_rgba(*ACCENT, 0.5)
        ctx.set_line_width(1)
        ctx.new_path()
        ctx.arc(bg_x + radius, bg_y + radius, radius, math.pi, 1.5 * math.pi)
        ctx.arc(bg_x + bg_w - radius, bg_y + radius, radius, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(bg_x + bg_w - radius, bg_y + bg_h - radius, radius, 0, 0.5 * math.pi)
        ctx.arc(bg_x + radius, bg_y + bg_h - radius, radius, 0.5 * math.pi, math.pi)
        ctx.close_path()
        ctx.stroke()

    # Text
    if highlight:
        ctx.set_source_rgb(*ACCENT)
    else:
        ctx.set_source_rgb(*TEXT_COLOR)
    ctx.move_to(text_x, text_y)
    ctx.show_text(text)


def draw_connector(ctx, x1, y1, x2, y2, highlight=False):
    """Draw a connector line from label to button."""
    if highlight:
        ctx.set_source_rgba(*ACCENT, 0.6)
    else:
        ctx.set_source_rgba(0.5, 0.5, 0.6, 0.4)
    ctx.set_line_width(1.5)

    # Draw dotted line
    ctx.set_dash([4, 4])
    ctx.move_to(x1, y1)
    ctx.line_to(x2, y2)
    ctx.stroke()
    ctx.set_dash([])

    # End dot
    ctx.arc(x2, y2, 3, 0, 2 * math.pi)
    ctx.fill()


def main():
    # Create surface
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    ctx = cairo.Context(surface)

    # Background
    ctx.set_source_rgb(*BG_COLOR)
    ctx.paint()

    # Title
    ctx.set_source_rgb(*TEXT_COLOR)
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(24)
    ctx.move_to(30, 45)
    ctx.show_text("MX Master 4 - Button Configuration")

    # Subtitle
    ctx.set_source_rgba(*TEXT_COLOR, 0.6)
    ctx.set_font_size(14)
    ctx.move_to(30, 70)
    ctx.show_text("Click any button to configure its action")

    # Draw mouse
    mouse_x, mouse_y = 450, 320
    draw_mouse(ctx, mouse_x, mouse_y, scale=1.3)

    # Labels and connectors
    labels = [
        ("Gesture Button", 120, 380, mouse_x - 104, mouse_y + 45, True),  # Highlighted
        ("Back Button", 120, 240, mouse_x - 98, mouse_y - 65, False),
        ("Forward Button", 120, 280, mouse_x - 98, mouse_y - 33, False),
        ("Horizontal Scroll", 120, 450, mouse_x - 130, mouse_y + 91, False),
        ("Scroll Wheel", 620, 180, mouse_x, mouse_y - 130, False),
        ("Mode Shift", 620, 240, mouse_x + 26, mouse_y - 58, False),
        ("Left Click", 620, 300, mouse_x - 40, mouse_y - 100, False),
        ("Right Click", 620, 340, mouse_x + 40, mouse_y - 100, False),
    ]

    for label_text, lx, ly, bx, by, highlight in labels:
        anchor = "right" if lx > 400 else "left"
        draw_connector(ctx, lx if anchor == "left" else lx, ly, bx, by, highlight)
        draw_label(ctx, lx, ly, label_text, anchor, highlight)

    # Info box at bottom
    ctx.set_source_rgba(*LABEL_BG)
    ctx.rectangle(30, HEIGHT - 70, WIDTH - 60, 40)
    ctx.fill()

    ctx.set_source_rgb(*ACCENT)
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(13)
    ctx.move_to(50, HEIGHT - 45)
    ctx.show_text("Gesture Button")

    ctx.set_source_rgb(*TEXT_COLOR)
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.move_to(170, HEIGHT - 45)
    ctx.show_text("triggers the radial menu overlay with 8 customizable directions")

    # Save
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    surface.write_to_png(OUTPUT_PATH)
    print(f"Generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
