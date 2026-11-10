#!/usr/bin/env python3
"""Capture Qt Settings pages, GTK dashboard pages, and a tray-menu replica
in Hebrew and English, for manual RTL review (one-time, not a CI check).

    python3 scripts/rtl_screenshots.py --out-dir /path/to/dir
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
QT_PAGES = list(range(12))  # settings-qt/tools/shot.py's own 0-11 docstring
GTK_PAGES = ["buttons", "settings"]
LANGS = ["en", "he"]


def shoot_qt(out_dir):
    for page in QT_PAGES:
        for lang in LANGS:
            xdg = out_dir / "xdg" / lang
            (xdg / "juhradial").mkdir(parents=True, exist_ok=True)
            (xdg / "juhradial" / "config.json").write_text(json.dumps({"language": lang}))
            out = out_dir / f"qt_page{page}_{lang}.png"
            subprocess.run(
                [sys.executable, str(REPO / "settings-qt" / "tools" / "shot.py"),
                 "--page", str(page), "--out", str(out),
                 "--env", f"XDG_CONFIG_HOME={xdg}"],
                check=False, timeout=60)


def shoot_gtk(out_dir):
    config = pathlib.Path.home() / ".config" / "juhradial" / "config.json"
    backup = config.read_bytes() if config.exists() else None
    try:
        for page in GTK_PAGES:
            for lang in LANGS:
                cfg = json.loads(backup) if backup else {}
                cfg["language"] = lang
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps(cfg))
                out = out_dir / f"gtk_{page}_{lang}.png"
                env = dict(os.environ, JUH_SHOT=str(out), JUH_SHOT_PAGE=page)
                subprocess.run([sys.executable, str(REPO / "overlay" / "settings_dashboard.py")],
                               cwd=str(REPO / "overlay"), env=env, check=False, timeout=30)
    finally:
        if backup is not None:
            config.write_bytes(backup)
        elif config.exists():
            config.unlink()


def shoot_tray_menu(out_dir):
    """A representative QMenu, not the live tray (which needs a running
    daemon/D-Bus session) - enough to check RTL item order/alignment."""
    sys.path.insert(0, str(REPO / "overlay"))
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMenu
    import i18n

    app = QApplication.instance() or QApplication([])
    for lang in LANGS:
        i18n.get_configured_language = lambda lang=lang: lang
        _ = i18n.setup_i18n()  # also sets app's direction (apply_platform_direction)
        menu = QMenu()
        menu.addAction(_("Settings"))
        menu.addAction(_("Easy-Switch"))
        menu.addSeparator()
        menu.addAction(_("Exit"))
        menu.show()
        app.processEvents()
        menu.grab().save(str(out_dir / f"tray_menu_{lang}.png"))
        menu.close()
    app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shoot_qt(out_dir)
    shoot_gtk(out_dir)
    shoot_tray_menu(out_dir)
    print(f"screenshots in {out_dir}")


if __name__ == "__main__":
    main()
