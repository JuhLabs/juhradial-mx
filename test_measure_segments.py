#!/usr/bin/env python3
"""Measure segment positions: outer edge from alpha, use ring_inner as inner edge."""

import math
import numpy as np
from PIL import Image
from overlay.themes import THEMES

WHEELS = sorted(
    [
        key
        for key, theme in THEMES.items()
        if key.startswith("3d-") and theme.get("radial_image")
    ]
)
RESAMPLE = Image.Resampling.LANCZOS

for theme_key in WHEELS:
    theme = THEMES[theme_key]
    params = theme["radial_params"]
    img_path = f"assets/radial-wheels/{theme['radial_image']}"
    target = params["image_size"]

    img = Image.open(img_path).convert("RGBA")
    img = img.resize((target, target), RESAMPLE)
    pixels = np.array(img)

    cx, cy = target / 2, target / 2
    icon_radius = params["icon_radius"]
    ring_inner = params["ring_inner"]

    print(f"\n{'=' * 60}")
    print(f"{theme_key} (icon_radius={icon_radius}, ring_inner={ring_inner})")

    icon_angles = [i * 45 for i in range(8)]
    segment_centers = []

    for idx, ia in enumerate(icon_angles):
        rad = math.radians(ia - 90)

        # Find outermost pixel with alpha > 128 along this radial line
        outer_edge = ring_inner
        for r in range(target // 2 - 1, ring_inner, -1):
            x = int(cx + r * math.cos(rad))
            y = int(cy + r * math.sin(rad))
            if 0 <= x < target and 0 <= y < target:
                if int(pixels[y, x, 3]) > 128:
                    outer_edge = r
                    break

        seg_center = (ring_inner + outer_edge) / 2
        seg_width = outer_edge - ring_inner
        diff = seg_center - icon_radius
        segment_centers.append(seg_center)

        print(
            f"  icon {idx} ({ia:3d}°): inner={ring_inner} outer={outer_edge} "
            f"center={seg_center:.0f} width={seg_width}px  "
            f"diff={diff:+.0f}px"
        )

    avg = sum(segment_centers) / len(segment_centers)
    print(f"  AVERAGE center = {avg:.1f}px → SUGGESTED icon_radius = {round(avg)}")
    print(f"  Current icon_radius = {icon_radius}, delta = {avg - icon_radius:+.1f}px")
