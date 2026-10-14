"""Character-centered field dots: self, monsters, items, and click rings."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

# etview marker colours. Dead is a light grey so a corpse is not another red dot.
_SELF = QColor(255, 255, 255)
_MONSTER = QColor(255, 40, 40)
_BAIT = QColor(120, 80, 40)
_DEAD = QColor(210, 210, 210)
_ITEM = QColor(40, 255, 40)
_CLICK = QColor(80, 220, 255)
_DOT_COLOURS = {
    "monster": _MONSTER,
    "bait": _BAIT,
    "dead": _DEAD,
    "item": _ITEM,
}

_RING_S = 0.6
_TILE = 14.0
_WALK = QColor(92, 94, 90)
_WALL = QColor(12, 12, 14)
_UNKNOWN = QColor(140, 48, 48)
_TERRAIN = {"walk": _WALK, "wall": _WALL, "unknown": _UNKNOWN}


def _to_screen(rx: float, ry: float, cx: float, cy: float) -> tuple[float, float]:
    """etview iso. Game +Y is down, so screen Y is centre minus (rx-ry)."""
    return (
        cx + (float(rx) + float(ry)) * _TILE,
        cy - (float(rx) - float(ry)) * _TILE * 0.5,
    )


class FieldView(QWidget):
    """Dots only. No other players and no attack lines."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setAutoFillBackground(False)
        self._dots: list[tuple[str, float, float]] = []
        self._terrain: list[tuple[int, int, str]] = []
        self._status = ""
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)

    def set_dots(self, dots: list[tuple[str, float, float]]) -> None:
        self._dots = list(dots)
        self.update()

    def set_terrain(self, cells: list[tuple[int, int, str]]) -> None:
        self._terrain = list(cells)
        self.update()

    def set_status(self, text: str) -> None:
        text = str(text or "")
        if text == self._status:
            return
        self._status = text
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(17, 17, 17))
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        half = _TILE * 0.5
        for rx, ry, kind in self._terrain:
            colour = _TERRAIN.get(kind)
            if colour is None:
                continue
            sx, sy = _to_screen(rx, ry, cx, cy)
            painter.setBrush(colour)
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(sx, sy - half),
                        QPointF(sx + _TILE, sy),
                        QPointF(sx, sy + half),
                        QPointF(sx - _TILE, sy),
                    ]
                )
            )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(55, 55, 55), 1))
        painter.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))
        painter.drawLine(int(cx), int(cy - 8), int(cx), int(cy + 8))

        for kind, rx, ry in self._dots:
            x, y = _to_screen(rx, ry, cx, cy)
            colour = _DOT_COLOURS.get(kind, _ITEM)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)

        from app._03_world.debug.field_clicks import recent_clicks

        now = time.time()
        clicks = recent_clicks()
        started = [row for row in clicks if row[0] <= now]
        latest = started[-1] if started else None
        if latest is not None:
            x, y = _to_screen(latest[1], latest[2], cx, cy)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_CLICK)
            painter.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
        for started, rx, ry in clicks:
            age = now - started
            if age < 0.0 or age > _RING_S:
                continue
            t = age / _RING_S
            x, y = _to_screen(rx, ry, cx, cy)
            radius = 6.0 + t * 52.0
            colour = QColor(_CLICK)
            colour.setAlpha(int(255 * (1.0 - t)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colour, 2))
            painter.drawEllipse(
                int(x - radius),
                int(y - radius),
                int(radius * 2),
                int(radius * 2),
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_SELF)
        painter.drawEllipse(int(cx) - 5, int(cy) - 5, 10, 10)
        if self._status:
            painter.setPen(QColor(209, 213, 219))
            painter.drawText(
                self.rect().adjusted(8, 10, -8, -8),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._status,
            )
        painter.end()
