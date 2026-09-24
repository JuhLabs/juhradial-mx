#!/usr/bin/env python3
"""Offscreen QML smoke test: compile Main.qml + every page with real context.

Catches QML syntax errors, missing components, and bad property/signal names
across all pages at once (the running app only loads the visible page lazily).
Run: python3 settings-qt/tools/qml_check.py
"""
import os
import sys
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from PyQt6.QtGui import QGuiApplication            # noqa: E402
from PyQt6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PyQt6.QtCore import QUrl                      # noqa: E402
from bridge.theme import Theme                     # noqa: E402
from bridge.backend import Backend                 # noqa: E402

app = QGuiApplication(sys.argv)
engine = QQmlEngine()
theme, backend = Theme(), Backend()
ctx = engine.rootContext()
ctx.setContextProperty("Theme", theme)
ctx.setContextProperty("Backend", backend)
ctx.setContextProperty("Slices", backend.slices)
ctx.setContextProperty("assetsDir", (HERE / "assets").as_uri())

targets = [HERE / "qml" / "Main.qml"]
targets += sorted((HERE / "qml" / "pages").glob("*.qml"))

fail = 0
for t in targets:
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(t)))
    if comp.isError():
        fail += 1
        print(f"\n[ERROR] {t.name}")
        for e in comp.errors():
            print("   ", e.toString())
        continue
    obj = comp.create(ctx)
    if obj is None:
        fail += 1
        print(f"\n[CREATE-FAIL] {t.name}")
        for e in comp.errors():
            print("   ", e.toString())
    else:
        print(f"[ok] {t.name}")

print(f"\n{'FAILED' if fail else 'ALL OK'}: {fail} file(s) with errors")
sys.exit(1 if fail else 0)
