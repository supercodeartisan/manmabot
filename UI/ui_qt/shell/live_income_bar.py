"""Dashboard cards: level, exp, adena, and hourly rates.

Holdings update every second from memory. Hourly rates count only while the
project is running. Pause and stop keep the elapsed time and the gains so far,
and the next start continues from those numbers. Closing the program drops
them. A shop purchase is left out of the Adena gain; a shop sale is kept.
Time to level uses that running-only exp rate.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

_RATE_WAIT = 15.0
_BAR_H = 88
_ICON_DIR = Path(__file__).resolve().parent / "icons"
_ICONS: dict[str, QPixmap] = {}


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


def per_hour(delta: float, elapsed: float) -> float | None:
    if elapsed < _RATE_WAIT:
        return None
    return float(delta) / (elapsed / 3600.0)


_COPY = {
    "ko": {
        "exp": "경험치",
        "eta_label": "레벨업까지 남은 시간",
        "eta_reserve": "약 100시간 59분",
        "per_hour": "시간당",
        "adena_label": "아데나 보유량",
        "adena_rate_label": "시간당 획득량",
        "gained_label": "획득한 아데나",
        "runtime_label": "가동시간",
        "about": "약",
        "under_minute": "약 1분 미만",
        "runtime_under_minute": "1분 미만",
        "hour": "시간",
        "minute": "분",
    },
    "zh": {
        "exp": "经验值",
        "eta_label": "距离升级剩余时间",
        "eta_reserve": "约100小时59分",
        "per_hour": "每小时",
        "adena_label": "金币持有量",
        "adena_rate_label": "每小时获得",
        "gained_label": "获得金币",
        "runtime_label": "运行时间",
        "about": "约",
        "under_minute": "约1分钟以内",
        "runtime_under_minute": "1分钟以内",
        "hour": "小时",
        "minute": "分",
    },
}


def _copy(language: str) -> dict[str, str]:
    if str(language or "").lower().startswith("zh"):
        return _COPY["zh"]
    return _COPY["ko"]


_RUNTIME_GAP = 12.0
_RUNTIME_VALUE_SIZE = 12


def runtime_phrase(elapsed: float | None, language: str = "ko") -> str:
    """``1시간 10분``. ``elapsed`` is the same running-only clock the Adena rate uses."""
    text = _copy(language)
    if elapsed is None:
        return "—"
    total_min = int(float(elapsed) // 60.0)
    if total_min <= 0:
        return text["runtime_under_minute"]
    whole, minutes = divmod(total_min, 60)
    if str(language or "").lower().startswith("zh"):
        if whole and minutes:
            return f"{whole}{text['hour']}{minutes}{text['minute']}"
        if whole:
            return f"{whole}{text['hour']}"
        return f"{minutes}{text['minute']}"
    if whole and minutes:
        return f"{whole}{text['hour']} {minutes}{text['minute']}"
    if whole:
        return f"{whole}{text['hour']}"
    return f"{minutes}{text['minute']}"


def eta_phrase(
    exp_percent: float | None,
    exp_per_hour: float | None,
    language: str = "ko",
) -> str:
    """``약 2시간 14분``. Empty rate or a falling bar has no arrival time."""
    text = _copy(language)
    if exp_percent is None or exp_per_hour is None or exp_per_hour <= 1e-9:
        return "—"
    hours = (100.0 - float(exp_percent)) / float(exp_per_hour)
    if hours < 0:
        return "—"
    total_min = int(round(hours * 60.0))
    if total_min <= 0:
        return text["under_minute"]
    whole, minutes = divmod(total_min, 60)
    about = text["about"]
    if str(language or "").lower().startswith("zh"):
        if whole and minutes:
            return f"{about}{whole}{text['hour']}{minutes}{text['minute']}"
        if whole:
            return f"{about}{whole}{text['hour']}"
        return f"{about}{minutes}{text['minute']}"
    if whole and minutes:
        return f"{about} {whole}{text['hour']} {minutes}{text['minute']}"
    if whole:
        return f"{about} {whole}{text['hour']}"
    return f"{about} {minutes}{text['minute']}"


class _Meter:
    """Gains and elapsed time for the current process only.

    The clock runs while ``running`` is true. Pause or stop folds the open
    segment into the saved totals and forgets the baseline, so manual play
    in the gap is not part of the next delta. A negative Adena change during
    a shop buy is ignored. Sales and other gains are kept.
    """

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.segment_start: float | None = None
        self.started = False
        self.adena_gain = 0
        self.exp_gain = 0.0
        self.last_adena: int | None = None
        self.last_exp: tuple[int, float] | None = None
        self.level: int | None = None
        self.exp: float | None = None
        self.hold_adena: int | None = None

    def push(
        self,
        *,
        running: bool,
        buying: bool,
        adena: int | None,
        level: int | None,
        exp_percent: float | None,
        now: float | None = None,
    ) -> dict:
        if level is not None:
            self.level = int(level)
        if exp_percent is not None:
            self.exp = float(exp_percent)
        if adena is not None:
            self.hold_adena = int(adena)
        moment = time.monotonic() if now is None else float(now)
        if running:
            if self.segment_start is None:
                self.segment_start = moment
                self.started = True
                self.last_adena = int(adena) if adena is not None else None
                if level is not None and exp_percent is not None:
                    self.last_exp = (int(level), float(exp_percent))
                else:
                    self.last_exp = None
            else:
                if adena is not None and self.last_adena is not None:
                    delta = int(adena) - int(self.last_adena)
                    if not (delta < 0 and buying):
                        self.adena_gain += delta
                if adena is not None:
                    self.last_adena = int(adena)
                self.exp_gain, self.last_exp = apply_exp(
                    self.exp_gain, self.last_exp, level, exp_percent
                )
            elapsed = self.elapsed + max(0.0, moment - self.segment_start)
        else:
            if self.segment_start is not None:
                self.elapsed += max(0.0, moment - self.segment_start)
                self.segment_start = None
            self.last_adena = None
            self.last_exp = None
            elapsed = self.elapsed
        show_rate = self.started
        return {
            "level": self.level,
            "exp": self.exp,
            "exp_rate": per_hour(self.exp_gain, elapsed) if show_rate else None,
            "adena": self.hold_adena,
            "adena_rate": per_hour(self.adena_gain, elapsed) if show_rate else None,
            "adena_gained": self.adena_gain if show_rate else None,
            "elapsed": elapsed if show_rate else None,
        }


def _read_sample() -> tuple[int | None, int | None, float | None]:
    adena = level = None
    exp_percent = None
    try:
        from app._01_perception.inventory_listen_reader import shared_inventory
        from app._03_world.merge.memory_inventory import (
            ADENA_IDS,
            ADENA_NAMES,
            count_matching,
        )

        snap = shared_inventory().snapshot()
        items = snap.get("items") if isinstance(snap, dict) else None
        if isinstance(items, list):
            adena = int(count_matching(items, ids=ADENA_IDS, names=ADENA_NAMES))
    except Exception:
        adena = None
    try:
        from app._05_action import body_pose as pose

        progress = pose.read_progress()
        if progress:
            level = progress.get("level")
            exp_percent = progress.get("exp_percent")
            if level is not None:
                level = int(level)
            if exp_percent is not None:
                exp_percent = float(exp_percent)
    except Exception:
        level = None
        exp_percent = None
    return adena, level, exp_percent


class _IncomeSession:
    """One sampler for this process. A new process starts the totals at zero."""

    def __init__(self) -> None:
        self.meter = _Meter()
        self._lock = threading.Lock()
        self._running = lambda: False
        self._buying = lambda: False
        self._listeners: list = []
        self._thread = threading.Thread(
            target=self._loop, name="live-income", daemon=True
        )
        self._thread.start()

    def bind(self, running, buying) -> None:
        with self._lock:
            self._running = running
            self._buying = buying

    def listen(self, fn) -> None:
        with self._lock:
            self._listeners.append(fn)

    def unlisten(self, fn) -> None:
        with self._lock:
            self._listeners = [item for item in self._listeners if item is not fn]

    def _loop(self) -> None:
        while True:
            adena, level, exp_percent = _read_sample()
            with self._lock:
                try:
                    running = bool(self._running())
                except Exception:
                    running = False
                try:
                    buying = bool(self._buying())
                except Exception:
                    buying = False
                listeners = list(self._listeners)
                view = self.meter.push(
                    running=running,
                    buying=buying,
                    adena=adena,
                    level=level,
                    exp_percent=exp_percent,
                )
            for fn in listeners:
                try:
                    fn(view)
                except Exception:
                    pass
            time.sleep(1.0)


_SESSION: _IncomeSession | None = None
_SESSION_LOCK = threading.Lock()


def _session() -> _IncomeSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = _IncomeSession()
        return _SESSION


class LiveIncomeBar(QWidget):
    """Two cards above the account editor. Repaint follows the 1s sample."""

    sampleReady = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        language: str = "ko",
        running=None,
        buying=None,
    ) -> None:
        super().__init__(parent)
        self._language = language or "ko"
        self.setFixedHeight(_BAR_H)
        self._view: dict = {
            "level": None,
            "exp": None,
            "exp_rate": None,
            "adena": None,
            "adena_rate": None,
            "adena_gained": None,
            "elapsed": None,
        }
        self._session = _session()
        self._session.bind(running or (lambda: False), buying or (lambda: False))
        self.sampleReady.connect(self._apply_sample)
        self._session.listen(self._on_session)

    def shutdown(self) -> None:
        self._session.unlisten(self._on_session)
        try:
            self.sampleReady.disconnect(self._apply_sample)
        except (RuntimeError, TypeError):
            pass

    def _on_session(self, view: object) -> None:
        self.sampleReady.emit(view)

    def _apply_sample(self, view: object) -> None:
        if isinstance(view, dict):
            self._view = view
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gap = 10.0
        left = 3.0
        usable = max(0.0, self.width() - left - gap - 1.0)
        adena_w = self._adena_width(painter)
        # The level card keeps most of a narrow bar. Adena takes its content
        # width only when the level card still has room for its columns.
        if usable >= adena_w + 360.0:
            level_w = usable - adena_w
        else:
            level_w = usable * 0.62
            adena_w = usable - level_w
        height = self.height() - 2.0
        self._paint_progress(painter, QRectF(left, 0, level_w, height))
        self._paint_adena(painter, QRectF(left + level_w + gap, 0, adena_w, height))
        painter.end()

    def _paint_progress(self, painter: QPainter, rect: QRectF) -> None:
        text = _copy(self._language)
        painter.save()
        painter.setClipRect(rect.adjusted(-1, -1, 1, 1))
        self._card(painter, rect, QColor("#ffffff"), QColor("#e3e8ef"))
        avatar = QRectF(rect.left() + 12, rect.top() + 16, 52, 52)
        if not self._blit_icon(painter, avatar, "exp"):
            self._avatar(painter, avatar)
        level = self._view.get("level")
        exp = self._view.get("exp")
        rate = self._view.get("exp_rate")
        eta = eta_phrase(
            exp if isinstance(exp, (int, float)) else None,
            rate if isinstance(rate, (int, float)) else None,
            self._language,
        )
        rate_text = self._exp_rate_value(rate)
        gutter = 18.0
        level_need = self._block_width(
            painter,
            (("Lv. 999", 15, True), (f"{text['exp']} 100.0%", 11, False)),
        )
        eta_w = self._block_width(
            painter,
            ((text["eta_label"], 11, False), (text["eta_reserve"], 15, True)),
        )
        rate_w = self._block_width(
            painter,
            ((text["per_hour"], 11, False), ("100.0%", 15, True)),
        )
        body_left = avatar.right() + 12.0
        body_right = rect.right() - 12.0
        available = max(0.0, body_right - body_left)
        side = eta_w + rate_w + gutter * 2.0
        if level_need + side <= available:
            level_w = available - side
        else:
            gutter = 8.0
            level_w = min(level_need, available)
            room = max(0.0, available - level_w - gutter * 2.0)
            pair = eta_w + rate_w
            if pair > room and pair > 0:
                scale = room / pair
                eta_w *= scale
                rate_w *= scale
        level_rect = QRectF(body_left, rect.top() + 8, level_w, rect.height() - 16)
        eta_x = body_left + level_w + gutter
        rate_x = eta_x + eta_w + gutter
        self._rule(painter, eta_x - gutter / 2.0, rect)
        self._rule(painter, rate_x - gutter / 2.0, rect)
        level_text = "Lv. —" if level is None else f"Lv. {int(level)}"
        exp_text = f"{text['exp']} —" if exp is None else f"{text['exp']} {float(exp):.1f}%"
        self._text(painter, level_rect, 2, level_text, 15, "#1f2937", bold=True)
        self._text(painter, level_rect.adjusted(0, 22, 0, 0), 0, exp_text, 11, "#6b7280", bold=False)
        self._exp_bar(
            painter,
            QRectF(level_rect.left(), level_rect.top() + 42, level_rect.width(), 7),
            exp,
        )
        eta_rect = QRectF(eta_x, rect.top() + 8, eta_w, rect.height() - 16)
        self._text(painter, eta_rect, 6, text["eta_label"], 11, "#6b7280", bold=False)
        self._text(painter, eta_rect.adjusted(0, 24, 0, 0), 0, eta, 15, "#1f2937", bold=True)
        rate_rect = QRectF(rate_x, rect.top() + 8, max(rate_w, body_right - rate_x), rect.height() - 16)
        rate_color = "#e11d48" if isinstance(rate, (int, float)) and float(rate) < 0 else "#3b82f6"
        self._text(painter, rate_rect, 6, text["per_hour"], 11, "#6b7280", bold=False)
        self._text(painter, rate_rect.adjusted(0, 24, 0, 0), 0, rate_text, 15, rate_color, bold=True)
        painter.restore()

    def _paint_adena(self, painter: QPainter, rect: QRectF) -> None:
        text = _copy(self._language)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        painter.save()
        painter.setClipRect(rect.adjusted(-1, -1, 1, 1))
        gradient.setColorAt(0.0, QColor("#fff8ea"))
        gradient.setColorAt(1.0, QColor("#ffe6b0"))
        painter.setPen(QPen(QColor("#f0d7a2")))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 12, 12)
        icon = QRectF(rect.left() + 14, rect.top() + 18, 46, 46)
        if not self._blit_icon(painter, icon, "adena"):
            self._coins(painter, icon)
        adena = self._view.get("adena")
        rate = self._view.get("adena_rate")
        amount = "—" if adena is None else f"{int(adena):,}"
        gutter = 18.0
        hold_w = self._hold_column_width(painter, text)
        rate_w = self._block_width(
            painter,
            ((text["adena_rate_label"], 11, False), (f"{text['about']} 999,999", 15, True)),
        )
        hold_x = icon.right() + 12.0
        rate_x = hold_x + hold_w + gutter
        self._rule(painter, rate_x - gutter / 2.0, rect, QColor("#f0d7a2"))
        hold_rect = QRectF(hold_x, rect.top() + 8, hold_w, rect.height() - 12)
        rate_rect = QRectF(rate_x, rect.top() + 10, max(rate_w, rect.right() - 12.0 - rate_x), rect.height() - 20)
        self._text(painter, hold_rect, 2, text["adena_label"], 11, "#8a6a32", bold=False)
        self._text(painter, hold_rect.adjusted(0, 18, 0, 0), 0, amount, 18, "#1f2937", bold=True)
        gained_dy = 52.0
        label = text["gained_label"]
        gained_number = self._gained_number()
        label_w = self._advance(painter, label + " ", 11, False)
        number_w = self._advance(painter, gained_number, 14, True)
        runtime_x = label_w + number_w + _RUNTIME_GAP
        runtime_label = text["runtime_label"]
        runtime_label_w = self._advance(painter, runtime_label + " ", 11, False)
        self._text(painter, hold_rect, gained_dy + 3, label, 11, "#8a6a32", bold=False)
        self._text(
            painter,
            hold_rect.adjusted(label_w, 0, 0, 0),
            gained_dy,
            gained_number,
            14,
            "#1f2937",
            bold=True,
        )
        self._text(
            painter,
            hold_rect.adjusted(runtime_x, 0, 0, 0),
            gained_dy + 3,
            runtime_label,
            11,
            "#8a6a32",
            bold=False,
        )
        self._text(
            painter,
            hold_rect.adjusted(runtime_x + runtime_label_w, 0, 0, 0),
            gained_dy + 2,
            self._runtime_text(),
            _RUNTIME_VALUE_SIZE,
            "#1f2937",
            bold=True,
        )
        self._text(painter, rate_rect, 4, text["adena_rate_label"], 11, "#8a6a32", bold=False)
        self._text(
            painter,
            rate_rect.adjusted(0, 22, 0, 0),
            0,
            self._adena_rate_value(rate),
            15,
            "#1f2937",
            bold=True,
        )
        painter.restore()

    def _card(self, painter: QPainter, rect: QRectF, fill: QColor, border: QColor) -> None:
        painter.setPen(QPen(border))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 12, 12)

    def _adena_width(self, painter: QPainter) -> float:
        """Content width of the gold card, without the empty stretch."""
        text = _copy(self._language)
        hold_w = self._hold_column_width(painter, text)
        rate_w = self._block_width(
            painter,
            ((text["adena_rate_label"], 11, False), (f"{text['about']} 999,999", 15, True)),
        )
        return 14.0 + 46.0 + 12.0 + hold_w + 18.0 + rate_w + 16.0

    def _hold_column_width(self, painter: QPainter, text: dict[str, str]) -> float:
        """Holdings column. Runtime sits on the gained line and must not push the rate off."""
        base = max(
            self._advance(painter, text["adena_label"], 11, False),
            self._advance(painter, "999,999,999", 18, True),
            self._advance(painter, text["gained_label"] + " ", 11, False)
            + self._advance(painter, "999,999,999", 14, True),
        )
        bottom = (
            self._advance(painter, text["gained_label"] + " ", 11, False)
            + self._advance(painter, self._gained_number(), 14, True)
            + _RUNTIME_GAP
            + self._advance(painter, text["runtime_label"] + " ", 11, False)
            + self._advance(painter, self._runtime_text(), _RUNTIME_VALUE_SIZE, True)
        )
        return max(base, bottom) + 4.0

    def _block_width(
        self,
        painter: QPainter,
        lines: tuple[tuple[str, int, bool], ...],
    ) -> float:
        return max(self._advance(painter, line, size, bold) for line, size, bold in lines) + 4.0

    def _advance(self, painter: QPainter, text: str, size: int, bold: bool) -> float:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        return float(painter.fontMetrics().horizontalAdvance(text))

    def _rule(
        self,
        painter: QPainter,
        x: float,
        rect: QRectF,
        color: QColor | None = None,
    ) -> None:
        painter.setPen(QPen(color or QColor("#e6ebf2")))
        painter.drawLine(QPointF(x, rect.top() + 16), QPointF(x, rect.bottom() - 16))

    def _text(
        self,
        painter: QPainter,
        rect: QRectF,
        dy: float,
        text: str,
        size: int,
        color: str,
        *,
        bold: bool,
    ) -> None:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(rect.adjusted(0, dy, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)

    def _exp_bar(self, painter: QPainter, rect: QRectF, exp: object) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e7eef8"))
        painter.drawRoundedRect(rect, 3, 3)
        if not isinstance(exp, (int, float)):
            return
        ratio = max(0.0, min(1.0, float(exp) / 100.0))
        if ratio <= 0:
            return
        filled = QRectF(rect)
        filled.setWidth(max(6.0, rect.width() * ratio))
        painter.setBrush(QColor("#3b82f6"))
        painter.drawRoundedRect(filled, 3, 3)

    def _icon(self, name: str) -> QPixmap:
        pix = _ICONS.get(name)
        if pix is None:
            pix = QPixmap(str(_ICON_DIR / f"{name}.png"))
            _ICONS[name] = pix
        return pix

    def _blit_icon(self, painter: QPainter, rect: QRectF, name: str) -> bool:
        """Draw a transparent icon so the card fill shows through unchanged."""
        pix = self._icon(name)
        if pix.isNull():
            return False
        device = painter.device()
        dpr = float(device.devicePixelRatioF()) if device is not None else 1.0
        scaled = pix.scaled(
            max(1, int(round(rect.width() * dpr))),
            max(1, int(round(rect.height() * dpr))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        drawn_w = scaled.width() / dpr
        drawn_h = scaled.height() / dpr
        origin = QPointF(
            rect.center().x() - drawn_w / 2.0,
            rect.center().y() - drawn_h / 2.0,
        )
        painter.drawPixmap(origin, scaled)
        return True

    def _avatar(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8eef6"))
        painter.drawEllipse(rect)
        painter.setBrush(QColor("#9aa8bc"))
        head = QRectF(rect.center().x() - 8, rect.top() + 12, 16, 16)
        painter.drawEllipse(head)
        painter.setBrush(QColor("#7d8da3"))
        body = QRectF(rect.center().x() - 14, rect.top() + 30, 28, 16)
        painter.drawRoundedRect(body, 8, 8)

    def _coins(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#c48a12")))
        for index, dy in enumerate((18, 10, 2)):
            coin = QRectF(rect.left() + 6, rect.top() + dy, 34, 16)
            painter.setBrush(QColor("#f6c453" if index < 2 else "#ffd56a"))
            painter.drawEllipse(coin)

    def _exp_rate_value(self, rate: object) -> str:
        if not isinstance(rate, (int, float)):
            return "—"
        value = float(rate)
        if value < 0:
            return f"-{abs(value):.1f}%"
        return f"{value:.1f}%"

    def _runtime_text(self) -> str:
        elapsed = self._view.get("elapsed")
        if not isinstance(elapsed, (int, float)):
            return "—"
        return runtime_phrase(float(elapsed), self._language)

    def _gained_number(self) -> str:
        gained = self._view.get("adena_gained")
        if not isinstance(gained, (int, float)):
            return "—"
        value = int(gained)
        if value < 0:
            return f"-{abs(value):,}"
        return f"{value:,}"

    def _adena_rate_value(self, rate: object) -> str:
        about = _copy(self._language)["about"]
        if not isinstance(rate, (int, float)):
            return "—"
        value = int(round(float(rate)))
        if value < 0:
            return f"{about} -{abs(value):,}"
        return f"{about} {value:,}"
