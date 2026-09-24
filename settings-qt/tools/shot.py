#!/usr/bin/env python3
"""Capture one settings page on the GPU path, without needing window focus.

    python3 settings-qt/tools/shot.py --page 1 --out /tmp/buttons.png
        [--size 1400x920] [--delay 2500] [--device "MX Master 3S"] [--env K=V ...]

The offscreen QPA runs the software scene graph, where MultiEffect,
RectangularShadow, layers and masks are no-ops (frost, glows and rounded
tiles vanish), so this forces QT_QPA_PLATFORM=xcb and lets main.py grab its
own window with grabWindow(). Pages: 0 Dashboard, 1 Buttons, 2 Point & Scroll,
3 Haptics, 4 Macros, 5 App profiles, 6 Easy-Switch, 7 Devices, 8 Gaming,
9 Flow, 10 Themes, 11 Settings.
"""
import argparse
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1400x920")
    ap.add_argument("--delay", type=int, default=2600, help="ms before the grab")
    ap.add_argument("--device", default="", help="JUH_DEVICE_NAME override (device art work)")
    ap.add_argument("--env", action="append", default=[], help="extra KEY=VALUE for the app")
    args = ap.parse_args()

    env = dict(os.environ, QT_QPA_PLATFORM="xcb", JUH_PAGE=str(args.page),
               JUH_SHOT=os.path.abspath(args.out), JUH_SHOT_SIZE=args.size,
               JUH_SHOT_DELAY=str(args.delay))
    if args.device:
        env["JUH_DEVICE_NAME"] = args.device
    for kv in args.env:
        k, _, v = kv.partition("=")
        env[k] = v
    r = subprocess.run([sys.executable, str(HERE / "main.py")], env=env,
                       capture_output=True, text=True, timeout=60)
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    print("\n".join(tail))
    ok = r.returncode == 0 and os.path.exists(args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
