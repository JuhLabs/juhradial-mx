"""Text legibility helpers for rich backgrounds (pure Python, no Qt).

WCAG-based contrast utilities used to pick readable text colors and the
minimum black scrim needed over a busy background. Channels are 0..255.
"""


def srgb_to_linear(c):
    """Linearize a single 0..255 sRGB channel to 0..1."""
    cs = c / 255.0
    if cs <= 0.04045:
        return cs / 12.92
    return ((cs + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    """WCAG relative luminance (0..1) for an (r, g, b) 0..255 tuple."""
    r, g, b = rgb
    return (
        0.2126 * srgb_to_linear(r)
        + 0.7152 * srgb_to_linear(g)
        + 0.0722 * srgb_to_linear(b)
    )


def contrast_ratio(rgb_a, rgb_b):
    """WCAG contrast ratio between two colors: (Llight+0.05)/(Ldark+0.05)."""
    la = relative_luminance(rgb_a)
    lb = relative_luminance(rgb_b)
    light, dark = (la, lb) if la >= lb else (lb, la)
    return (light + 0.05) / (dark + 0.05)


def best_text_color(bg_rgb, light=(243, 235, 214), dark=(11, 11, 13)):
    """Return whichever of light/dark contrasts most strongly with bg_rgb."""
    if contrast_ratio(light, bg_rgb) >= contrast_ratio(dark, bg_rgb):
        return light
    return dark


def _hex_to_rgb(hex_color):
    h = (hex_color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in rgb))


def ensure_contrast(fg_hex, bg_hex, target):
    """Return fg_hex nudged toward black/white until it reaches the target
    WCAG ratio against bg_hex; unchanged when it already passes.

    The nudge is a linear mix toward whichever pole lies away from the
    background, so hue is preserved and the adjustment is the minimum
    needed. Used as a legibility floor over theme palettes whose ink or
    status colors fall short (e.g. Solarized Light body text at 4.1:1).
    """
    fg = _hex_to_rgb(fg_hex)
    bg = _hex_to_rgb(bg_hex)
    if contrast_ratio(fg, bg) >= target:
        return fg_hex
    pole = (0, 0, 0) if relative_luminance(bg) > 0.5 else (255, 255, 255)
    steps = 50
    for i in range(1, steps + 1):
        t = i / steps
        mixed = tuple(f + (p - f) * t for f, p in zip(fg, pole))
        if contrast_ratio(mixed, bg) >= target:
            return _rgb_to_hex(mixed)
    return _rgb_to_hex(pole)


def scrim_alpha_for(bg_rgb, text_rgb, target=4.5, max_alpha=0.6):
    """Smallest black-scrim alpha (0..max_alpha) so text hits target contrast.

    Black is composited over bg per channel as c' = c*(1-alpha). Returns 0.0 if
    the target is already met, otherwise the smallest alpha reaching it, capped
    at max_alpha (returned when target is unreachable within the cap).
    """
    if contrast_ratio(text_rgb, bg_rgb) >= target:
        return 0.0

    r, g, b = bg_rgb
    steps = 600
    for i in range(1, steps + 1):
        alpha = max_alpha * i / steps
        scrimmed = (r * (1 - alpha), g * (1 - alpha), b * (1 - alpha))
        if contrast_ratio(text_rgb, scrimmed) >= target:
            return alpha
    return max_alpha
