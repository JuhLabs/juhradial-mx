#!/usr/bin/env python3
"""Bake the GlassCard drop shadow into a 9-patch PNG.

GlassCard used a per-card layer + MultiEffect drop shadow: any animated child
re-rendered the whole card into an offscreen FBO every frame. Instead we
pre-render one blurred rounded-rect shadow and let a BorderImage stretch it
behind every card.

Canvas is 128x128 with 32px margins (not 96: the inner rect must be wider than
2 * radius so the 18px corner radius is not clamped). The BorderImage in
GlassCard.qml keeps 32px border slices to match the margin.

Run: python3 settings-qt/tools/gen_card_shadow.py
Writes: settings-qt/assets/fx/card_shadow.png
"""
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (QApplication, QGraphicsBlurEffect,
                             QGraphicsPixmapItem, QGraphicsScene)

SIZE = 128
MARGIN = 32
RADIUS = 18      # Theme.radiusCard
BLUR = 24
OPACITY = 0.55


def main():
    app = QApplication(sys.argv)  # noqa: F841 (QGraphicsScene needs QApplication)

    silhouette = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    silhouette.fill(Qt.GlobalColor.transparent)
    p = QPainter(silhouette)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(MARGIN, MARGIN, SIZE - 2 * MARGIN, SIZE - 2 * MARGIN), RADIUS, RADIUS)
    p.fillPath(path, QColor(0, 0, 0, round(OPACITY * 255)))
    p.end()

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(silhouette))
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(BLUR)
    item.setGraphicsEffect(blur)
    scene.addItem(item)

    out = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(0, 0, SIZE, SIZE), QRectF(0, 0, SIZE, SIZE))
    p.end()

    dest = pathlib.Path(__file__).resolve().parents[1] / "assets" / "fx" / "card_shadow.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not out.save(str(dest)):
        sys.exit(f"failed to write {dest}")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
