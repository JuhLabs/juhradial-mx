#!/usr/bin/env python3
"""Settings > Menu background blur was a dead toggle since 0.4.4: nothing read
blur_enabled. On KDE the overlay now asks KWin to blur behind the ring disc
(_KDE_NET_WM_BLUR_BEHIND_REGION). The region must be the disc, not the square
window, or a frosted square shows around the round ring.

Run: python3 -m pytest tests/test_overlay_blur.py -q
"""
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "overlay"))

import overlay_blur  # noqa: E402


def test_strips_cover_the_disc_and_stay_inside_it():
    cx = cy = 150
    r = 120
    rects = overlay_blur.circle_strips(cx, cy, r)
    assert rects
    covered = sum(w * h for (_x, _y, w, h) in rects)
    assert 0.9 * math.pi * r * r < covered < 1.02 * math.pi * r * r
    for x, y, w, h in rects:
        assert x >= cx - r and x + w <= cx + r
        assert y >= cy - r and y + h <= cy + r


def test_empty_radius_means_no_region():
    assert overlay_blur.circle_strips(10, 10, 0) == []


def test_overlay_applies_it_on_kde_opens_only():
    src = (REPO / "overlay" / "juhradial-overlay.py").read_text(encoding="utf-8")
    show = src[src.index("        if IS_KDE:\n            self._update_kde_mask()\n            self._apply_blur()"):]
    assert show  # applied in the KDE branch before show()
    assert '_config_section("blur_enabled", True)' in src
