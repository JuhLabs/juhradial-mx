#!/usr/bin/env python3
"""Generate custom circular radial-slice buttons via fal, TRANSPARENT.

fal has no native transparent text-to-image, so: FLUX-2-pro renders a glossy 3D
round button on a plain bg, then BiRefNet removes the bg (a bright convex circle
is an easy subject -> clean transparent edge). Output assets/slices/btn_<id>.png,
transparent so each button drops onto ANY wheel skin.

Run: settings-qt/.venv/bin/python settings-qt/tools/gen_slice_buttons.py
"""
import os
import re
import sys
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "settings-qt" / "assets" / "slices"


def _load_fal_key():
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        m = re.search(r"KEY\s*[:=]\s*(\S+)", line)
        if m and "FAL" in line.upper():
            return m.group(1).strip()
    sys.exit("FAL key not found in .env")


os.environ["FAL_KEY"] = _load_fal_key()
import fal_client  # noqa: E402


def _url(res):
    if res.get("images"):
        return res["images"][0]["url"]
    if isinstance(res.get("image"), dict):
        return res["image"]["url"]
    raise RuntimeError(str(res)[:160])


def gen(prompt):
    return _url(fal_client.subscribe("fal-ai/flux-2-pro", arguments={
        "prompt": prompt, "image_size": {"width": 1024, "height": 1024},
        "output_format": "png"}, with_logs=False))


def cutout(url):
    return _url(fal_client.subscribe("fal-ai/birefnet/v2", arguments={
        "image_url": url, "model": "General Use (Heavy)",
        "operating_resolution": "2048x2048", "output_format": "png",
        "refine_foreground": True}, with_logs=False))


# (action_id, colour words, symbol words)
BUTTONS = [
    ("play_pause", "vivid emerald green", "media play triangle"),
    ("pause", "vivid emerald green", "two vertical pause bars"),
    ("new_note", "warm golden amber", "pencil writing on a note page"),
    ("lock", "coral red", "closed padlock"),
    ("settings", "rich violet purple", "settings gear cog"),
    ("screenshot", "azure blue", "compact camera"),
    ("emoji", "rose pink", "round smiley face"),
    ("files", "sky blue", "open file folder"),
    ("ai", "vivid teal cyan", "four pointed sparkle star"),
    ("easy_switch", "azure blue", "two curved arrows forming a circular switch loop"),
    ("copy", "azure blue", "two overlapping document pages"),
    ("paste", "azure blue", "a clipboard with a document on it"),
    ("undo", "azure blue", "a curved arrow pointing left"),
    ("redo", "azure blue", "a curved arrow pointing right"),
    ("cut", "azure blue", "a pair of open scissors"),
    ("select_all", "azure blue", "a dashed selection rectangle"),
    ("close_window", "coral red", "a bold X close cross"),
    ("minimize", "sky blue", "a window minimize underscore line"),
    ("volume_up", "soft mint green", "a speaker emitting sound waves with a plus sign"),
    ("volume_down", "soft mint green", "a speaker with a minus sign"),
    ("mute", "coral red", "a muted speaker with an X"),
    ("next_track", "soft mint green", "skip to next track, double triangle with a bar"),
    ("prev_track", "soft mint green", "skip to previous track, double triangle with a bar"),
]

TEMPLATE = (
    "A single round glossy 3D app button, a solid opaque saturated {color} domed "
    "button with a soft bevelled rim and a bright glass-like top specular "
    "highlight, a crisp clean white {sym} icon centered and softly embossed on "
    "it, modern premium operating-system app icon, perfectly circular, centered "
    "and filling the frame with a small even margin, isolated on a plain flat "
    "medium grey studio background, soft even lighting, no drop shadow, no "
    "reflection, no text, one single button only, product render."
)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for aid, color, sym in BUTTONS:
        if only and aid not in only:
            continue
        try:
            raw = gen(TEMPLATE.format(color=color, sym=sym))
            cut = cutout(raw)
            dest = OUT / f"btn_{aid}.png"
            urllib.request.urlretrieve(cut, dest)
            print("saved:", dest.relative_to(ROOT))
        except Exception as e:
            print(f"{aid} failed:", e)
    print("DONE")


if __name__ == "__main__":
    main()
