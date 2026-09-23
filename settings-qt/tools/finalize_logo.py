#!/usr/bin/env python3
"""Export the approved orb logo to app-icon sizes + a horizontal README lockup."""
import glob
import pathlib
from PIL import Image, ImageDraw, ImageFont

LOGO = pathlib.Path("assets/logo")
FINAL = LOGO / "logo_final.png"      # orb + centred wordmark (app icon master)
ORB = LOGO / "orb_a.png"             # orb mark, no text (for the lockup)
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]


def font(*names, size=64):
    for n in names:
        hits = glob.glob(f"/usr/share/fonts/**/{n}", recursive=True)
        if hits:
            return ImageFont.truetype(hits[0], size)
    raise SystemExit(f"font not found: {names}")


def main():
    master = Image.open(FINAL).convert("RGBA")
    # alpha sanity: corner must be transparent
    a = master.getpixel((4, 4))[3]
    print(f"corner alpha = {a} ({'transparent OK' if a == 0 else 'NOT transparent'})")

    icons = LOGO / "icons"
    icons.mkdir(exist_ok=True)
    for s in SIZES:
        master.resize((s, s), Image.LANCZOS).save(icons / f"juhradial-mx-{s}.png")
    master.resize((256, 256), Image.LANCZOS).save(LOGO / "juhradial-mx.png")
    print(f"icons: {', '.join(str(s) for s in SIZES)}")

    # horizontal lockup: orb mark (no text) + wordmark
    orb = Image.open(ORB).convert("RGBA")
    H = 360
    orb_sz = 320
    orb_r = orb.resize((orb_sz, orb_sz), Image.LANCZOS)
    pad = 40
    f_main = font("InterDisplay-SemiBold.ttf", "Inter-SemiBold.ttf", size=132)
    f_sub = font("InterDisplay-Medium.ttf", "Inter-Medium.ttf", size=92)
    tw = max(int(f_main.getlength("JuhRadial")), int(f_sub.getlength("MX")) + 16)
    W = pad + orb_sz + 28 + tw + pad
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(orb_r, (pad, (H - orb_sz) // 2))
    d = ImageDraw.Draw(canvas)
    tx = pad + orb_sz + 28
    d.text((tx, H // 2 - 6), "JuhRadial", font=f_main, fill=(255, 255, 255, 255), anchor="lm")
    d.text((tx + int(f_main.getlength("JuhRadial")) + 18, H // 2 - 6), "MX",
           font=f_sub, fill=(76, 154, 255, 255), anchor="lm")
    canvas.save(LOGO / "lockup.png")
    print(f"lockup: {W}x{H}")


if __name__ == "__main__":
    main()
