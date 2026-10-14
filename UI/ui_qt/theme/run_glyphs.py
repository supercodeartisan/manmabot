"""16×16 run control glyphs — parity with classic ``_run_glyph``."""

from __future__ import annotations

from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtCore import Qt

from ui_qt.theme import tokens

_CACHE: dict[str, QIcon] = {}


def run_glyph(kind: str) -> QIcon:
    key = str(kind or "start")
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    color = QColor(tokens.ACCENT)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)

    def triangle(x0: int) -> None:
        for y in range(3, 13):
            reach = 5 - abs(y - 7)
            if reach > 0:
                painter.drawRect(x0, y, reach, 1)

    if key == "pause":
        painter.drawRect(3, 3, 3, 10)
        painter.drawRect(10, 3, 3, 10)
    elif key == "resume":
        painter.drawRect(2, 3, 3, 10)
        triangle(7)
    elif key == "stop":
        painter.drawRect(3, 3, 10, 10)
    else:
        triangle(5)
    painter.end()
    icon = QIcon(QPixmap.fromImage(image))
    _CACHE[key] = icon
    return icon
