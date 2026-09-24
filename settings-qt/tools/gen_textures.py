#!/usr/bin/env python3
"""Procedural, perfectly-seamless, transparent UI textures (grain / grid / dots).

These tile cleanly and have real alpha, so they sit at low opacity over the
wallpaper/cards as quiet atmosphere. Run: .venv/bin/python tools/gen_textures.py
"""
import pathlib
import numpy as np
from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "textures"
OUT.mkdir(parents=True, exist_ok=True)
S = 512


def grain():
    rng = np.random.default_rng(11)
    n = rng.integers(0, 256, (S, S), dtype=np.uint8)          # monochrome noise
    a = (rng.random((S, S)) * 26).astype(np.uint8)            # very low alpha
    img = np.dstack([n, n, n, a])
    Image.fromarray(img, "RGBA").save(OUT / "grain.png")


def grid(step=32, alpha=16):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(0, S, step):
        d.line([(i, 0), (i, S)], fill=(255, 255, 255, alpha), width=1)
        d.line([(0, i), (S, i)], fill=(255, 255, 255, alpha), width=1)
    img.save(OUT / "grid.png")


def dots(step=24, r=1, alpha=22):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(0, S, step):
        for x in range(0, S, step):
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, alpha))
    img.save(OUT / "dots.png")


if __name__ == "__main__":
    grain(); grid(); dots()
    print("wrote grain.png, grid.png, dots.png to", OUT)
