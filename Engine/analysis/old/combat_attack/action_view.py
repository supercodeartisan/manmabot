"""300x300 window. Draws the live body action every 0.1s.

The picture is the memory read of ActionComponent+0xC0.
A small mark under the figure is ActorController+0x58.
"""
import math
import sys

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

import action_timeline as act

W = 300
H = 300


class ActionView(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setWindowTitle("action")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.body = 0
        self.cmd = 0
        self.phase = 0.0
        self.ready = False
        self.h = None
        self.pid = 0
        self.base = 0
        self.size = 0
        self.me = 0
        self._open()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)

    def _open(self):
        import ctypes

        self.pid = act.find_pid()
        self.h = act.k32.CreateFileW(
            "\\\\.\\WinNotify", 0x80000000 | 0x40000000, 0, None, 3, 0, None
        )
        bad = ctypes.c_void_p(-1).value
        if not self.pid or self.h in (bad, -1, None, 0):
            self.h = None
            return
        self.base, self.size = act.module_base(self.h, self.pid)
        self.me = act.find_my_player(self.h, self.pid, self.base, self.size)
        self.ready = bool(self.me)

    def _tick(self):
        self.phase += 0.55
        if self.h and self.me:
            if act.vrva(self.h, self.pid, self.base, self.size, self.me) != 0x11E12A8:
                self.me = act.find_my_player(self.h, self.pid, self.base, self.size)
            if self.me:
                cur = act.sample(self.h, self.pid, self.base, self.size, self.me)
                if cur:
                    self.body = cur["body"]
                    self.cmd = cur["cmd"]
                    self.ready = True
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#16181e"))
        name = act.label(act.BODY, self.body) if self.ready else "none"
        color = {
            "stand": "#d5dbe6",
            "walk": "#7dffb0",
            "attack": "#ff5b49",
            "actionbase": "#ffcc66",
            "turn": "#7ec8ff",
            "damaged": "#ff4d6d",
            "spell": "#c79bff",
            "death": "#8e96a3",
            "default": "#f2f2f2",
            "shop": "#ffe08a",
            "walkback": "#9dffce",
            "effect": "#d7b3ff",
            "fixedframe": "#c5c8d0",
            "npcstate": "#9ad7c8",
            "zapwand": "#b9f3ff",
            "none": "#3c4250",
        }.get(name, "#ffffff")
        pen = QPen(QColor(color))
        pen.setWidth(8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        draw = {
            "stand": self._stand,
            "walk": self._walk,
            "attack": self._attack,
            "actionbase": self._pickup,
            "turn": self._turn,
            "damaged": self._damaged,
            "spell": self._spell,
            "death": self._death,
            "walkback": self._walk,
        }.get(name, self._stand if self.ready else self._empty)
        draw(p)
        self._command(p)
        p.end()

    def _head(self, p, x, y, r=18):
        p.drawEllipse(QPointF(x, y), r, r)

    def _stand(self, p):
        self._head(p, 150, 78)
        p.drawLine(150, 96, 150, 168)
        p.drawLine(150, 118, 112, 150)
        p.drawLine(150, 118, 188, 150)
        p.drawLine(150, 168, 124, 228)
        p.drawLine(150, 168, 176, 228)

    def _walk(self, p):
        s = math.sin(self.phase)
        self._head(p, 150 + s * 4, 78)
        p.drawLine(150, 96, 150 + s * 6, 168)
        p.drawLine(150, 118, 116 - s * 18, 148)
        p.drawLine(150, 118, 184 + s * 18, 148)
        p.drawLine(150, 168, 122 - s * 26, 230)
        p.drawLine(150, 168, 178 + s * 26, 230)

    def _attack(self, p):
        swing = math.sin(self.phase * 1.6)
        self._head(p, 138, 80)
        p.drawLine(142, 98, 150, 170)
        p.drawLine(146, 122, 108, 156)
        x2 = 168 + 62 * math.cos(swing * 0.9)
        y2 = 118 + 62 * math.sin(swing * 0.9)
        p.drawLine(146, 120, int(x2), int(y2))
        p.drawLine(150, 170, 128, 228)
        p.drawLine(150, 170, 176, 228)

    def _pickup(self, p):
        bob = math.sin(self.phase) * 3
        self._head(p, 168, 118 + bob, 16)
        p.drawLine(156, 132, 132, 176)
        p.drawLine(148, 150, 196, 188)
        p.drawLine(140, 168, 118, 214)
        p.drawLine(138, 174, 168, 226)
        p.setBrush(QColor(p.pen().color()))
        p.drawEllipse(QPointF(208, 214), 8, 8)
        p.setBrush(Qt.NoBrush)

    def _turn(self, p):
        self._head(p, 156, 78, 16)
        p.drawLine(156, 94, 150, 170)
        p.drawLine(154, 120, 188, 146)
        p.drawLine(150, 170, 142, 228)
        p.drawLine(150, 170, 164, 228)
        p.drawArc(108, 96, 70, 70, 40 * 16, 140 * 16)

    def _damaged(self, p):
        self._head(p, 168, 86)
        p.drawLine(160, 104, 176, 168)
        p.drawLine(164, 122, 128, 100)
        p.drawLine(164, 128, 196, 108)
        p.drawLine(176, 168, 150, 226)
        p.drawLine(176, 168, 198, 220)

    def _spell(self, p):
        self._stand(p)
        p.setBrush(QColor(p.pen().color()))
        for i, x in enumerate((118, 150, 182)):
            r = 5 + (self.phase + i) % 3
            p.drawEllipse(QPointF(x, 42), r, r)
        p.setBrush(Qt.NoBrush)

    def _death(self, p):
        self._head(p, 78, 168, 16)
        p.drawLine(96, 168, 210, 168)
        p.drawLine(150, 168, 132, 140)
        p.drawLine(150, 168, 168, 196)

    def _empty(self, p):
        pen = QPen(QColor("#3c4250"))
        pen.setWidth(8)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(QPointF(150, 150), 36, 36)

    def _command(self, p):
        name = act.label(act.CMD, self.cmd)
        if name == "none":
            return
        pen = QPen(QColor("#f4f7fb"))
        pen.setWidth(6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if name == "move":
            p.drawLine(126, 262, 146, 248)
            p.drawLine(146, 248, 166, 262)
            p.drawLine(156, 262, 176, 248)
            p.drawLine(176, 248, 196, 262)
        elif name == "attack":
            p.drawLine(132, 268, 168, 244)
            p.drawLine(150, 270, 186, 246)
        elif name == "interact":
            p.drawLine(150, 242, 168, 258)
            p.drawLine(168, 258, 150, 274)
            p.drawLine(150, 274, 132, 258)
            p.drawLine(132, 258, 150, 242)


def main():
    app = QApplication(sys.argv)
    view = ActionView()
    view.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
