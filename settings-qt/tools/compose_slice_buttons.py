#!/usr/bin/env python3
"""Compose the radial-slice buttons: one machined disc per action + its line
glyph, identical geometry for every button so nothing ever looks skewed.

Disc: the action's slice colour (bridge.backend SLICE_COLORS) pushed to a
saturated mid tone, lit from the top left, with a lit rim and a darker base.
Glyph: the same 24-grid SVG the pickers use (assets/icons/mono), white, at 46
percent of the disc. Output: assets/slices/btn_<action_id>.png, 256 px RGBA PNG,
transparent background (circular asset rule).

Run: python3 settings-qt/tools/compose_slice_buttons.py
Needs Pillow and CairoSVG (dev tools only, not runtime dependencies).
"""
import colorsys
import io
import pathlib
import sys

import cairosvg
from PIL import Image, ImageDraw, ImageFilter

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from bridge.backend import RADIAL_ACTIONS, SLICE_COLORS  # noqa: E402

MONO = HERE / "assets" / "icons" / "mono"
OUT = HERE / "assets" / "slices"
SIZE = 256
DISC = 236          # disc diameter inside the 256 canvas
GLYPH = 0.46        # glyph size as a fraction of the disc

# Buttons that exist outside RADIAL_ACTIONS (legacy ids still referenced).
EXTRA = [
    ("easy_switch", "easy-switch", "teal"),
    ("pause", "media-playback-pause-symbolic", "green"),
]


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _tone(rgb, s, v):
    hh, _s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hh, s, v))


def disc(colour):
    """Radial-lit disc: lighter at the top left, darker toward the base."""
    base = _hex_to_rgb(colour)
    hi, mid, lo = _tone(base, 0.55, 0.92), _tone(base, 0.66, 0.70), _tone(base, 0.74, 0.42)
    ss = 4  # supersample for clean edges
    big = SIZE * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    grad = Image.new("RGB", (big, big), mid)
    px = grad.load()
    cx, cy, r = big * 0.40, big * 0.36, big * 0.62
    for y in range(big):
        for x in range(0, big, 2):
            d = min(1.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / r)
            t = d * d
            c = tuple(round(hi[i] * (1 - t) + lo[i] * t) for i in range(3))
            px[x, y] = c
            px[x + 1, y] = c
    mask = Image.new("L", (big, big), 0)
    off = (SIZE - DISC) / 2 * ss
    ImageDraw.Draw(mask).ellipse((off, off, big - off, big - off), fill=255)
    img.paste(grad, (0, 0), mask)
    # lit rim (top) and darker edge (bottom) drawn as thin arcs
    rim = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(rim)
    w = 3 * ss
    d.arc((off + w / 2, off + w / 2, big - off - w / 2, big - off - w / 2), 200, 340,
          fill=(255, 255, 255, 110), width=w)
    d.arc((off + w / 2, off + w / 2, big - off - w / 2, big - off - w / 2), 20, 160,
          fill=(0, 0, 0, 90), width=w)
    rim = rim.filter(ImageFilter.GaussianBlur(2 * ss))
    img.alpha_composite(rim)
    # soft top-left sheen: the disc is lit like the glass above it
    sheen = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse((off + big * 0.10, off + big * 0.06, big - off - big * 0.22, off + big * 0.42),
                                  fill=(255, 255, 255, 46))
    sheen = sheen.filter(ImageFilter.GaussianBlur(9 * ss))
    img.alpha_composite(sheen)
    # hairline edge
    edge = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(edge).ellipse((off, off, big - off, big - off), outline=(0, 0, 0, 70), width=ss)
    img.alpha_composite(edge)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def glyph(icon_name):
    svg = MONO / f"{icon_name}.svg"
    if not svg.exists():
        raise FileNotFoundError(svg)
    size = round(DISC * GLYPH)
    png = cairosvg.svg2png(url=str(svg), output_width=size * 2, output_height=size * 2)
    g = Image.open(io.BytesIO(png)).convert("RGBA").resize((size, size), Image.LANCZOS)
    # soft dark drop under the glyph for depth
    shadow = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
    alpha = g.split()[3]
    shadow.paste((0, 0, 0, 110), (4, 6), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(2.2))
    return g, shadow


def compose(action_id, icon_name, colour_name):
    colour = SLICE_COLORS.get(colour_name, SLICE_COLORS["blue"])
    img = disc(colour)
    g, shadow = glyph(icon_name)
    x = (SIZE - g.width) // 2
    y = (SIZE - g.height) // 2
    img.alpha_composite(shadow, (x - 4, y - 4))
    img.alpha_composite(g, (x, y))
    out = OUT / f"btn_{action_id}.png"
    img.save(out, optimize=True)   # RGBA: a quantised palette bands the gradient
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(aid, icon, colour) for (aid, _label, icon, _t, _cmd, colour) in RADIAL_ACTIONS] + EXTRA
    for aid, icon, colour in jobs:
        out = compose(aid, icon, colour)
        print("saved:", out.relative_to(HERE), out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
