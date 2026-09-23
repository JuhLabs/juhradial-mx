#!/usr/bin/env python3
"""Compose a radial-menu wheel with EXACT 8-slice geometry aligned to the menu.

The menu draws icon i at angle (i*45 - 90) deg (icon 0 = top) and centers each
slice on its icon. So this renders 8 slices centered at i*45 (in the menu's
atan2(dx,-dy) frame: 0 = up, clockwise), dividers at the 22.5 offsets, a
transparent centre hole and transparent outside, at 1024x1024 to match the
existing wheels. AI provides the material; geometry + transparency are exact, so
buttons never move between themes.

    .venv/bin/python tools/wheel_compose.py proc out_name           # procedural fill
    .venv/bin/python tools/wheel_compose.py assets/materials/mat_azure.png azure
    add 'proof' as 3rd arg to overlay icon-position markers.
"""
import sys
import math
import pathlib
import numpy as np
from PIL import Image, ImageDraw

SIZE = 1024
CX = CY = SIZE / 2.0
INNER = 160.0          # transparent centre hole radius (matches existing wheels)
OUTER = 480.0          # outer radius
GAP_HALF = 2.0         # divider half-gap, degrees
FEATHER = 2.0          # px edge antialias
ICON_R = (INNER + OUTER) / 2.0
OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "wheels"
AZURE = np.array([92, 170, 255], dtype=np.float32)


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _grids():
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    dx = x - CX + 0.5
    dy = y - CY + 0.5
    r = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dx, -dy)) % 360.0   # 0 = up, clockwise (menu frame)
    return r, ang


def _slice_alpha(r, ang):
    annulus = _smooth(INNER - FEATHER, INNER + FEATHER, r) * (1 - _smooth(OUTER - FEATHER, OUTER + FEATHER, r))
    t = (ang - 22.5) % 45.0
    dist = np.minimum(t, 45.0 - t)                  # deg to nearest divider boundary
    divider = _smooth(GAP_HALF - 0.8, GAP_HALF + 0.8, dist)
    return annulus * divider


def _glow(r, ang):
    # thin azure light along each slice edge + subtle rim highlights (not beams)
    t = (ang - 22.5) % 45.0
    dist = np.minimum(t, 45.0 - t)
    edge = np.clip(1.0 - (dist - GAP_HALF) / 2.2, 0, 1) * (dist >= GAP_HALF)
    in_ring = (r >= INNER) & (r <= OUTER)
    inner = np.clip(1.0 - np.abs(r - INNER) / 7.0, 0, 1)
    outer = np.clip(1.0 - np.abs(r - OUTER) / 8.0, 0, 1)
    return np.clip(edge * 0.45 * in_ring + inner * 0.4 + outer * 0.45, 0, 1)


def _procedural():
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    dx = x - CX; dy = y - CY
    r = np.hypot(dx, dy); ang = np.arctan2(dy, dx)
    val = np.clip(0.12 + 0.16 * (1 - r / OUTER), 0, 1)
    val += 0.03 * np.sin(ang * 64)                  # fine brushed streaks
    rng = np.random.default_rng(7)
    val = np.clip(val + (rng.random((SIZE, SIZE)) - 0.5) * 0.05, 0, 1)  # grunge specks
    return (val[..., None] * (AZURE / 255.0)[None, None, :] * 255).astype(np.uint8)


def compose(mat_rgb, proof=False):
    r, ang = _grids()
    a = _slice_alpha(r, ang)
    g = _glow(r, ang)
    rgb = np.clip(mat_rgb.astype(np.float32) + g[..., None] * AZURE * 0.5, 0, 255)
    out = np.dstack([rgb.astype(np.uint8), (a * 255).astype(np.uint8)])
    img = Image.fromarray(out, "RGBA")
    if proof:
        d = ImageDraw.Draw(img)
        for i in range(8):
            t = math.radians(i * 45 - 90)
            ix = CX + ICON_R * math.cos(t); iy = CY + ICON_R * math.sin(t)
            d.ellipse([ix - 16, iy - 16, ix + 16, iy + 16], outline=(255, 80, 80, 255), width=5)
    return img


def main():
    src = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "wheel"
    proof = "proof" in sys.argv[3:]
    if src == "proc":
        mat = _procedural()
    else:
        mat = np.asarray(Image.open(src).convert("RGB").resize((SIZE, SIZE)))
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / (f"wheel_{name}.png")
    compose(mat, proof=proof).save(dest)
    print("wrote", dest.relative_to(OUT.parents[1]))


if __name__ == "__main__":
    main()
