#!/usr/bin/env python3
"""Generate the bespoke monochrome icon set for JuhRadial MX.

For a cohesive line of glyphs we reuse the SAME family the nav tabs already
use: Phosphor "regular". Each freedesktop "-symbolic" name the
app references is mapped to a Phosphor glyph, downloaded, recoloured white and
rasterised to a transparent PNG. The QML IconProvider then prefers these over
the freedesktop theme, so monochrome mode, the action pickers and every card
header pick them up with no QML changes (the provider re-tints by alpha).

Run with SYSTEM python3 (needs PyQt6 QtSvg):
    python3 settings-qt/tools/gen_mono_icons.py
"""
import pathlib
import sys
import urllib.request
import urllib.error

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import QByteArray

HERE = pathlib.Path(__file__).resolve().parents[1]
OUT = HERE / "assets" / "icons" / "mono"
CDN = "https://raw.githubusercontent.com/phosphor-icons/core/main/assets/regular/{}.svg"
SIZE = 256

# freedesktop "-symbolic" name -> Phosphor regular glyph candidates (first hit
# wins; alternates self-heal a renamed/absent glyph). Kept cohesive: one family.
MAP = {
    # physical buttons / radial actions
    "view-grid-symbolic": ["squares-four"],
    "view-app-grid-symbolic": ["grid-four", "squares-four"],
    "input-mouse-symbolic": ["mouse"],
    "go-previous-symbolic": ["arrow-left"],
    "go-next-symbolic": ["arrow-right"],
    "edit-copy-symbolic": ["copy"],
    "edit-paste-symbolic": ["clipboard"],
    "edit-undo-symbolic": ["arrow-counter-clockwise"],
    "edit-redo-symbolic": ["arrow-clockwise"],
    "edit-cut-symbolic": ["scissors"],
    "edit-select-all-symbolic": ["selection", "selection-all"],
    "camera-photo-symbolic": ["camera"],
    "emblem-synchronizing-symbolic": ["arrows-clockwise"],
    "object-flip-horizontal-symbolic": ["arrows-left-right", "arrows-horizontal"],
    "audio-volume-high-symbolic": ["speaker-high"],
    "audio-volume-low-symbolic": ["speaker-low"],
    "audio-volume-medium-symbolic": ["vibrate"],
    "audio-volume-muted-symbolic": ["speaker-x", "speaker-simple-x"],
    "media-playback-start-symbolic": ["play"],
    "media-playback-stop-symbolic": ["stop"],
    "media-seek-forward-symbolic": ["fast-forward"],
    "media-skip-forward-symbolic": ["skip-forward"],
    "media-skip-backward-symbolic": ["skip-back"],
    "zoom-in-symbolic": ["magnifying-glass-plus"],
    "zoom-out-symbolic": ["magnifying-glass-minus"],
    "user-desktop-symbolic": ["monitor"],
    "view-paged-symbolic": ["cards"],
    "window-close-symbolic": ["x"],
    "window-minimize-symbolic": ["minus"],
    "system-lock-screen-symbolic": ["lock"],
    "accessories-calculator-symbolic": ["calculator"],
    "action-unavailable-symbolic": ["prohibit"],
    "emblem-system-symbolic": ["gear"],
    "folder-symbolic": ["folder"],
    "face-smile-symbolic": ["smiley"],
    "document-new-symbolic": ["note-pencil", "note"],
    "applications-science-symbolic": ["sparkle"],
    # card headers / stat tiles / status across pages
    "view-list-symbolic": ["list"],
    "preferences-desktop-theme-symbolic": ["palette"],
    "preferences-desktop-locale-symbolic": ["globe"],
    "preferences-system-symbolic": ["sliders-horizontal", "sliders"],
    "system-run-symbolic": ["rocket-launch"],
    "help-about-symbolic": ["info"],
    "dialog-information-symbolic": ["info"],
    "applications-development-symbolic": ["code"],
    "applications-system-symbolic": ["stack"],
    "battery-full-charging-symbolic": ["battery-charging"],
    "battery-good-symbolic": ["battery-high"],
    "computer-symbolic": ["desktop-tower", "monitor"],
    "network-wireless-symbolic": ["wifi-high"],
    "network-wireless-disconnected-symbolic": ["wifi-slash", "wifi-x"],
    "starred-symbolic": ["star"],
    "user-trash-symbolic": ["trash"],
    "utilities-system-monitor-symbolic": ["gauge", "chart-line"],
    "view-dual-symbolic": ["columns", "square-split-horizontal"],
    "list-add-symbolic": ["plus"],
    # global search bar
    "system-search-symbolic": ["magnifying-glass"],
    "edit-find-symbolic": ["magnifying-glass"],
    "edit-clear-symbolic": ["x-circle"],
    # overlay-only auto-injected radial slice (switch between paired computers)
    "easy-switch": ["swap", "arrows-left-right"],
}


def fetch(glyphs):
    for g in glyphs:
        try:
            with urllib.request.urlopen(CDN.format(g), timeout=20) as r:
                if r.status == 200:
                    return g, r.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return None, None


def rasterise(svg_text, dest):
    # Phosphor svgs use fill="currentColor"; force white so the base PNG is a
    # visible white-on-transparent alpha master (IconProvider re-tints by alpha).
    svg_text = svg_text.replace("currentColor", "#FFFFFF")
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    if not renderer.isValid():
        return False
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    renderer.render(p)
    p.end()
    return img.save(str(dest), "PNG")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    force = "--force" in sys.argv
    ok, miss = [], []
    for fd_name, glyphs in MAP.items():
        dest = OUT / f"{fd_name}.png"
        if dest.exists() and not force:
            ok.append(f"{fd_name} (cached)")
            continue
        used, svg = fetch(glyphs)
        if svg is None:
            miss.append(f"{fd_name} -> {glyphs} (download failed)")
            continue
        if rasterise(svg, dest):
            ok.append(f"{fd_name} -> {used}")
        else:
            miss.append(f"{fd_name} -> {used} (render failed)")
    print(f"generated {len(ok)}/{len(MAP)} mono icons in {OUT}")
    for m in miss:
        print("  MISS:", m)


if __name__ == "__main__":
    main()
