#!/usr/bin/env python3
"""Visualize icon placement on each 3D radial wheel - large output for detail."""

import math
from PIL import Image, ImageDraw

from overlay.themes import THEMES

WHEELS = sorted(
    [
        key
        for key, theme in THEMES.items()
        if key.startswith("3d-") and theme.get("radial_image")
    ]
)
RESAMPLE = Image.Resampling.LANCZOS
OUT_SIZE = 800  # large output for clear visibility

for theme_key in WHEELS:
    theme = THEMES[theme_key]
    params = theme["radial_params"]
    img_name = theme["radial_image"]
    img_path = f"assets/radial-wheels/{img_name}"

    img = Image.open(img_path).convert("RGBA")
    target = params["image_size"]
    # Scale to output size
    s = OUT_SIZE / target
    img = img.resize((OUT_SIZE, OUT_SIZE), RESAMPLE)

    draw = ImageDraw.Draw(img)
    cx = OUT_SIZE / 2
    cy = OUT_SIZE / 2

    icon_radius = params["icon_radius"] * s
    ring_inner = params["ring_inner"] * s
    ring_outer = params["ring_outer"] * s

    shape = params.get("icon_bg_shape", "circle")
    bg_radius = params.get("icon_bg_radius", 20)
    bg_width = params.get("icon_bg_width", bg_radius * 2)
    bg_height = params.get("icon_bg_height", bg_radius * 2)
    scale = params.get("icon_scale", 1.0)

    # Draw ring inner/outer boundaries in green
    for r in [ring_inner, ring_outer]:
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r], outline=(0, 255, 0, 120), width=2
        )

    # Icon radius circle in red
    draw.ellipse(
        [cx - icon_radius, cy - icon_radius, cx + icon_radius, cy + icon_radius],
        outline=(255, 0, 0, 180),
        width=2,
    )

    for i in range(8):
        angle_deg = i * 45 - 90
        angle_rad = math.radians(angle_deg)
        ix = cx + icon_radius * math.cos(angle_rad)
        iy = cy + icon_radius * math.sin(angle_rad)

        # Large bright crosshair
        draw.line([(ix - 15, iy), (ix + 15, iy)], fill=(255, 50, 50), width=3)
        draw.line([(ix, iy - 15), (ix, iy + 15)], fill=(255, 50, 50), width=3)

        # Badge outline in bright yellow
        sw = s * scale
        if shape == "circle":
            r = bg_radius * sw
            draw.ellipse(
                [ix - r, iy - r, ix + r, iy + r], outline=(255, 255, 0), width=3
            )
        elif shape == "rounded_rect":
            w = bg_width * sw
            h = bg_height * sw
            cos_a = math.cos(math.radians(angle_deg + 90))
            sin_a = math.sin(math.radians(angle_deg + 90))
            corners = [
                (-w / 2, -h / 2),
                (w / 2, -h / 2),
                (w / 2, h / 2),
                (-w / 2, h / 2),
            ]
            pts = [
                (lx * cos_a - ly * sin_a + ix, lx * sin_a + ly * cos_a + iy)
                for lx, ly in corners
            ]
            draw.polygon(pts, outline=(255, 255, 0), width=3)
        elif shape == "diamond":
            w = bg_width * sw
            h = bg_height * sw
            cos_a = math.cos(math.radians(angle_deg + 90))
            sin_a = math.sin(math.radians(angle_deg + 90))
            pts_local = [(0, -h / 2), (w / 2, 0), (0, h / 2), (-w / 2, 0)]
            pts = [
                (lx * cos_a - ly * sin_a + ix, lx * sin_a + ly * cos_a + iy)
                for lx, ly in pts_local
            ]
            draw.polygon(pts, outline=(255, 255, 0), width=3)
        elif shape == "hexagon":
            r = bg_radius * sw
            cos_a = math.cos(math.radians(angle_deg + 90))
            sin_a = math.sin(math.radians(angle_deg + 90))
            pts = []
            for j in range(6):
                a = math.radians(j * 60 - 90)
                lx = r * math.cos(a)
                ly = r * math.sin(a)
                pts.append((lx * cos_a - ly * sin_a + ix, lx * sin_a + ly * cos_a + iy))
            draw.polygon(pts, outline=(255, 255, 0), width=3)

    out = f"GeneratedImages/place_{theme_key}.png"
    img.save(out)
    print(
        f"{theme_key}: radius={params['icon_radius']}, ring={params['ring_inner']}-{params['ring_outer']}, shape={shape}"
    )
