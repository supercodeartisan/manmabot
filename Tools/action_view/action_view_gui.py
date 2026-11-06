"""Action window. Draws the live body action every 0.1s.

The picture is the memory read of ActionComponent+0xC0.
A small mark under the figure is ActorController+0x58.
Above the figure: HP/MP bars, Adena, and level with exp percent.
Start, Pause, and Stop count Adena and exp percent from the moment Start is clicked.
"""
import math
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app._05_action import body_pose as pose

W = 300
FIGURE_DY = 160
H = 448
_BAR_X = 46
_BAR_W = W - _BAR_X - 12
_BTN_Y = 96
_BTN_H = 24
_CLOCK_W = 64
_ADENA_Y = 54
_LEVEL_Y = 72
_ADENA_RATE_Y = 124
_EXP_RATE_Y = 140
_RATE_SEC = 1.0


def _btn_rects() -> list[QRectF]:
    gap = 4.0
    avail = W - 24 - _CLOCK_W - 6
    width = (avail - gap * 2) / 3
    x = 12.0
    return [
        QRectF(x + i * (width + gap), _BTN_Y, width, _BTN_H)
        for i in range(3)
    ]


def apply_counter(gain: int, last: int | None, current: int | None) -> tuple[int, int | None]:
    """Add the change in a counter. The first sample only sets the baseline."""
    if current is None:
        return gain, last
    if last is None:
        return gain, current
    return gain + (int(current) - int(last)), int(current)


def apply_exp(
    gain: float,
    last: tuple[int, float] | None,
    level: int | None,
    pct: float | None,
) -> tuple[float, tuple[int, float] | None]:
    """Add exp-percent change. A level-up keeps the rest of the previous bar."""
    if level is None or pct is None:
        return gain, last
    current = (int(level), float(pct))
    if last is None:
        return gain, current
    prev_level, prev_pct = last
    delta = (current[0] - int(prev_level)) * 100.0 + (current[1] - float(prev_pct))
    return gain + delta, current


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _rate(delta: float, elapsed: float, *, places: int = 0, unit: str = "/h") -> str:
    if elapsed < 15:
        return ""
    per_hour = delta / (elapsed / 3600.0)
    return f"{per_hour:+,.{places}f}{unit}"


class ActionView(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setWindowTitle("Action View")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMouseTracking(True)
        self.body = 0
        self.cmd = 0
        self.phase = 0.0
        self.ready = False
        self.hp = None
        self.max_hp = None
        self.mp = None
        self.max_mp = None
        self.adena = None
        self.adena_ok = False
        self.level = None
        self.exp_percent = None
        self._rate_at = 0.0
        self._income_cache = ("Adena  —", "", "#8e96a3", "Exp  —", "", "#8e96a3")
        self._rec = None
        self._hover = None
        self._font = QFont("Segoe UI", 9)
        self._font_sm = QFont("Segoe UI", 8)
        self._adena_stop = threading.Event()
        self._adena_thread = threading.Thread(
            target=self._adena_worker, name="action-view-adena", daemon=True
        )
        self._adena_thread.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)

    def _adena_worker(self):
        try:
            from app._01_perception.inventory_listen_reader import InventoryListenReader
            from app._03_world.merge.memory_inventory import (
                ADENA_IDS,
                ADENA_NAMES,
                count_matching,
            )

            reader = InventoryListenReader()
        except Exception:
            return
        try:
            while not self._adena_stop.is_set():
                try:
                    snap = reader.snapshot()
                except Exception:
                    snap = None
                items = snap.get("items") if isinstance(snap, dict) else None
                if isinstance(items, list):
                    self.adena = count_matching(items, ids=ADENA_IDS, names=ADENA_NAMES)
                    self.adena_ok = True
                if self._adena_stop.wait(1.0):
                    break
        finally:
            try:
                reader.close()
            except Exception:
                pass

    def closeEvent(self, event):
        self._adena_stop.set()
        super().closeEvent(event)

    def _tick(self):
        self.phase += 0.55
        body, cmd = pose.read_action()
        if body is not None:
            self.body = body
            self.cmd = cmd or 0
            self.ready = True
        vitals = pose.read_vitals()
        if vitals:
            self.hp = vitals["hp"]
            self.max_hp = vitals["max_hp"]
            self.mp = vitals["mp"]
            self.max_mp = vitals["max_mp"]
        now = time.monotonic()
        if now - self._rate_at >= _RATE_SEC:
            self._rate_at = now
            self._sample_rates()
        self.update()

    def _sample_rates(self):
        """Read exp and fold adena/exp into the hourly figures once a second."""
        progress = pose.read_progress()
        if progress:
            self.level = progress["level"]
            self.exp_percent = progress["exp_percent"]
        self._advance_record()
        self._income_cache = self._income_snapshot()

    def _elapsed(self, rec: dict) -> float:
        extra = 0.0
        if rec["state"] == "run":
            extra = time.monotonic() - float(rec["t_mark"])
        return float(rec["t_run"]) + extra

    def _advance_record(self):
        rec = self._rec
        if rec is None or rec["state"] != "run":
            return
        adena = int(self.adena) if self.adena_ok and self.adena is not None else None
        rec["adena_gain"], rec["last_adena"] = apply_counter(
            rec["adena_gain"], rec["last_adena"], adena
        )
        level = int(self.level) if self.level is not None else None
        pct = float(self.exp_percent) if self.exp_percent is not None else None
        rec["exp_gain"], rec["last_exp"] = apply_exp(
            rec["exp_gain"], rec["last_exp"], level, pct
        )

    def _start_record(self):
        rec = self._rec
        if rec is not None and rec["state"] == "pause":
            rec["t_mark"] = time.monotonic()
            rec["state"] = "run"
            return
        self._rec = {
            "state": "run",
            "t_run": 0.0,
            "t_mark": time.monotonic(),
            "adena_gain": 0,
            "last_adena": int(self.adena) if self.adena_ok and self.adena is not None else None,
            "exp_gain": 0.0,
            "last_exp": (
                (int(self.level), float(self.exp_percent))
                if self.level is not None and self.exp_percent is not None
                else None
            ),
        }

    def _pause_record(self):
        rec = self._rec
        if rec is None or rec["state"] != "run":
            return
        self._advance_record()
        rec["t_run"] = self._elapsed(rec)
        rec["state"] = "pause"

    def _stop_record(self):
        rec = self._rec
        if rec is None or rec["state"] not in ("run", "pause"):
            return
        if rec["state"] == "run":
            self._advance_record()
            rec["t_run"] = self._elapsed(rec)
        rec["state"] = "stop"

    def _hit_button(self, pos) -> int | None:
        state = None if self._rec is None else self._rec["state"]
        enabled = (
            state in (None, "pause", "stop"),
            state == "run",
            state in ("run", "pause"),
        )
        for index, rect in enumerate(_btn_rects()):
            if enabled[index] and rect.contains(pos):
                return index
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._hit_button(event.position())
            if hit == 0:
                self._start_record()
                self._income_cache = self._income_snapshot()
                self.update()
                return
            if hit == 1:
                self._pause_record()
                self._income_cache = self._income_snapshot()
                self.update()
                return
            if hit == 2:
                self._stop_record()
                self._income_cache = self._income_snapshot()
                self.update()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        hover = self._hit_button(event.position())
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.PointingHandCursor if hover is not None else Qt.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#16181e"))
        self._paint_hud(p)
        p.save()
        p.translate(0, FIGURE_DY)
        self._paint_figure(p)
        p.restore()
        p.end()

    def _paint_figure(self, p):
        name = pose.label(pose.BODY, self.body) if self.ready else "none"
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

    def _paint_hud(self, p):
        p.setFont(self._font)
        self._stat_bar(
            p, 8, "HP", self.hp, self.max_hp, "#e5484d", "#3a2226"
        )
        self._stat_bar(
            p, 32, "MP", self.mp, self.max_mp, "#3b82f6", "#1c2c44"
        )
        p.setPen(QColor("#ffe08a"))
        adena = f"{int(self.adena):,}" if self.adena_ok and self.adena is not None else "—"
        p.setFont(self._font)
        p.drawText(QRectF(12, _ADENA_Y, 70, 18), Qt.AlignVCenter | Qt.AlignLeft, "Adena")
        p.drawText(QRectF(82, _ADENA_Y, W - 94, 18), Qt.AlignVCenter | Qt.AlignRight, adena)
        self._level_line(p)
        self._record_buttons(p)
        self._income(p)

    def _stat_bar(self, p, y, label, cur, maximum, fill, track):
        p.setFont(self._font)
        p.setPen(QColor(fill))
        p.drawText(QRectF(10, y, 32, 18), Qt.AlignVCenter | Qt.AlignLeft, label)
        if cur is None:
            text = "—"
            ratio = 0.0
        elif maximum:
            text = f"{int(cur):,} / {int(maximum):,}"
            ratio = max(0.0, min(1.0, float(cur) / float(maximum)))
        else:
            text = f"{int(cur):,}"
            ratio = 0.0
        self._fill_bar(p, QRectF(_BAR_X, y, _BAR_W, 18), ratio, fill, track, text)

    def _fill_bar(self, p, rect, ratio, fill, track, text):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(track))
        p.drawRoundedRect(rect, 4, 4)
        if ratio > 0:
            filled = QRectF(rect)
            filled.setWidth(max(6.0, rect.width() * ratio))
            p.setBrush(QColor(fill))
            p.drawRoundedRect(filled, 4, 4)
        if text:
            p.setPen(QColor("#f7f8fb"))
            p.setFont(self._font)
            p.drawText(rect, Qt.AlignCenter, text)

    def _record_buttons(self, p):
        state = None if self._rec is None else self._rec["state"]
        labels = ("Resume" if state == "pause" else "Start", "Pause", "Stop")
        enabled = (
            state in (None, "pause", "stop"),
            state == "run",
            state in ("run", "pause"),
        )
        p.setFont(self._font_sm)
        for index, rect in enumerate(_btn_rects()):
            hot = self._hover == index
            on = enabled[index]
            p.setPen(QPen(QColor("#d7deea" if hot else ("#8ea0bd" if on else "#3c4250"))))
            p.setBrush(QColor("#343c4c" if hot else ("#2a3140" if on else "#1c2028")))
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor("#f4f7fb" if on else "#5c6573"))
            p.drawText(rect, Qt.AlignCenter, labels[index])
        if self._rec is not None:
            p.setPen(QColor("#f4f7fb" if state == "run" else "#8e96a3"))
            p.setFont(self._font_sm)
            p.drawText(
                QRectF(W - 12 - _CLOCK_W, _BTN_Y, _CLOCK_W, _BTN_H),
                Qt.AlignVCenter | Qt.AlignRight,
                _clock(self._elapsed(self._rec)),
            )

    def _level_line(self, p):
        p.setFont(self._font)
        p.setPen(QColor("#9ad7ff"))
        if self.level is None:
            label = "Lv  —"
        else:
            label = f"Lv {int(self.level)}"
        if self.exp_percent is None:
            pct = "—"
        else:
            pct = f"{float(self.exp_percent):.2f}%"
        p.drawText(QRectF(12, _LEVEL_Y, 70, 18), Qt.AlignVCenter | Qt.AlignLeft, label)
        p.drawText(QRectF(82, _LEVEL_Y, W - 94, 18), Qt.AlignVCenter | Qt.AlignRight, pct)

    def _income_snapshot(self):
        adena_text, adena_rate, adena_color = "Adena  —", "", "#8e96a3"
        exp_text, exp_rate, exp_color = "Exp  —", "", "#8e96a3"
        rec = self._rec
        if rec is not None:
            elapsed = self._elapsed(rec)
            if rec["last_adena"] is None and rec["state"] == "run":
                adena_text = "Adena  …"
            else:
                gained = int(rec["adena_gain"])
                adena_text = f"Adena  {gained:+,}"
                adena_rate = _rate(gained, elapsed)
                adena_color = "#7dffb0" if gained >= 0 else "#ff8a7a"
            if rec["last_exp"] is None and rec["state"] == "run":
                exp_text = "Exp  …"
            else:
                gained_pct = float(rec["exp_gain"])
                exp_text = f"Exp  {gained_pct:+.2f}%"
                exp_rate = _rate(gained_pct, elapsed, places=2, unit="%/h")
                exp_color = "#7dffb0" if gained_pct >= 0 else "#ff8a7a"
        return (adena_text, adena_rate, adena_color, exp_text, exp_rate, exp_color)

    def _income(self, p):
        p.setFont(self._font_sm)
        adena_text, adena_rate, adena_color, exp_text, exp_rate, exp_color = self._income_cache
        p.setPen(QColor(adena_color))
        p.drawText(QRectF(12, _ADENA_RATE_Y, 176, 16), Qt.AlignVCenter | Qt.AlignLeft, adena_text)
        p.drawText(QRectF(176, _ADENA_RATE_Y, W - 188, 16), Qt.AlignVCenter | Qt.AlignRight, adena_rate)
        p.setPen(QColor(exp_color))
        p.drawText(QRectF(12, _EXP_RATE_Y, 176, 16), Qt.AlignVCenter | Qt.AlignLeft, exp_text)
        p.drawText(QRectF(176, _EXP_RATE_Y, W - 188, 16), Qt.AlignVCenter | Qt.AlignRight, exp_rate)

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
        name = pose.label(pose.CMD, self.cmd)
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


def run_action_view() -> int:
    app = QApplication(sys.argv)
    view = ActionView()
    view.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(run_action_view())
