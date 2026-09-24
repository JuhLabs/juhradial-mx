#!/usr/bin/env python3
"""Safe round-trip test of the config read/write path (temp file, no real config)."""
import sys
import json
import pathlib
import tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from PyQt6.QtCore import QCoreApplication  # noqa: E402
import bridge.backend as bk                # noqa: E402

app = QCoreApplication(sys.argv)
tmp = pathlib.Path(tempfile.mkdtemp())
bk.CONFIG_DIR = tmp
bk.CONFIG = tmp / "config.json"

b = bk.Backend()
ok = True


def check(cond, msg):
    global ok
    print(("[ok] " if cond else "[FAIL] ") + msg)
    ok = ok and cond


# nested setLocal + get round-trip
b.setLocal("scroll.mode", "freespin")
check(b.get("scroll.mode") == "freespin", "scroll.mode round-trips in memory")
disk = json.loads(bk.CONFIG.read_text())
check(disk["scroll"]["mode"] == "freespin", "scroll.mode persisted to disk")

# deep value + default fallback
check(b.get("nope.missing", "dflt") == "dflt", "missing key returns default")

# buttons write
b.setLocal("buttons.forward", "copy")
check(json.loads(bk.CONFIG.read_text())["buttons"]["forward"] == "copy",
      "buttons.forward persisted")

# slice model setAction persists radial_menu.slices
b.slices.setAction(0, "screenshot")
disk = json.loads(bk.CONFIG.read_text())
check(disk["radial_menu"]["slices"][0]["action_id"] == "screenshot",
      "slice 0 action persisted")
check(disk["radial_menu"]["slices"][0]["icon"] == "camera-photo-symbolic",
      "slice 0 icon applied from preset")

# atomic write left no temp file behind
check(not (tmp / "config.json.tmp").exists(), "no leftover .tmp file")

# constants exposure
check(len(b.buttonActions()) > 10, "buttonActions populated")
check(len(b.hapticPatterns()) == 16, "16 haptic patterns")
check(b.slices.rowCount() == 8, "slice model has 8 rows")

print("\n" + ("ALL PASS" if ok else "FAILURES PRESENT"))
sys.exit(0 if ok else 1)
