"""Party-bot role picker. View only — writes no settings by itself."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui_qt.i18n_overlay import tx

_BLUE = "#3478F6"
_BLUE_SOFT = "#EAF2FF"
_CARD = "#FFFFFF"
_BORDER = "#D9E1EC"
_TEXT = "#202B3C"
_MUTED = "#64748B"
_BADGE_BG = "#F1F5F9"


def _mix(start: str, end: str, amount: float) -> str:
    origin = QColor(start)
    target = QColor(end)
    blend = max(0.0, min(1.0, float(amount)))
    return QColor(
        int(origin.red() + (target.red() - origin.red()) * blend),
        int(origin.green() + (target.green() - origin.green()) * blend),
        int(origin.blue() + (target.blue() - origin.blue()) * blend),
    ).name()


def _icon(kind: str, color: str, size: int = 20) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size / 14.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = size / 24.0

    def p(x: float, y: float) -> QPointF:
        return QPointF(x * s, y * s)

    def line(*pts: tuple[float, float]) -> None:
        for index in range(len(pts) - 1):
            painter.drawLine(p(*pts[index]), p(*pts[index + 1]))

    if kind == "crown":
        line((4, 17), (4, 9), (8.5, 13), (12, 6), (15.5, 13), (20, 9), (20, 17))
        painter.drawLine(p(4, 17), p(20, 17))
    elif kind == "user":
        painter.drawEllipse(p(12, 8), 3.3 * s, 3.3 * s)
        painter.drawArc(QRectF(5 * s, 13 * s, 14 * s, 10 * s), 0, 180 * 16)
    elif kind == "users":
        painter.drawEllipse(p(9, 9), 2.4 * s, 2.4 * s)
        painter.drawEllipse(p(15, 8), 2.1 * s, 2.1 * s)
        painter.drawArc(QRectF(4 * s, 13 * s, 10 * s, 8 * s), 0, 180 * 16)
        painter.drawArc(QRectF(12 * s, 13 * s, 8 * s, 7 * s), 20 * 16, 140 * 16)
    elif kind == "map":
        painter.drawRoundedRect(QRectF(4 * s, 5 * s, 16 * s, 14 * s), 1.5 * s, 1.5 * s)
        line((4, 9), (9, 7), (15, 11), (20, 8))
    elif kind == "crosshair":
        painter.drawEllipse(p(12, 12), 5 * s, 5 * s)
        painter.drawLine(p(12, 4), p(12, 8))
        painter.drawLine(p(12, 16), p(12, 20))
        painter.drawLine(p(4, 12), p(8, 12))
        painter.drawLine(p(16, 12), p(20, 12))
    elif kind == "shield":
        line((12, 4), (19, 7), (19, 12), (12, 20), (5, 12), (5, 7), (12, 4))
        line((9.5, 12), (11.2, 14), (15, 9.5))
    elif kind == "package":
        line((4, 8), (12, 4), (20, 8), (20, 16), (12, 20), (4, 16), (4, 8))
        painter.drawLine(p(12, 4), p(12, 20))
        painter.drawLine(p(4, 8), p(20, 8))
    elif kind == "server":
        painter.drawRoundedRect(QRectF(5 * s, 4 * s, 14 * s, 5 * s), 1.2 * s, 1.2 * s)
        painter.drawRoundedRect(QRectF(5 * s, 11 * s, 14 * s, 5 * s), 1.2 * s, 1.2 * s)
        painter.drawEllipse(p(8, 6.5), 0.7 * s, 0.7 * s)
        painter.drawEllipse(p(8, 13.5), 0.7 * s, 0.7 * s)
    elif kind == "activity":
        line((3, 12), (8, 12), (10.5, 6), (13.5, 18), (16, 12), (21, 12))
    elif kind == "navigation":
        line((12, 20), (12, 5), (18, 11))
        painter.drawLine(p(12, 5), p(6, 11))
    elif kind == "target":
        painter.drawEllipse(p(12, 12), 7 * s, 7 * s)
        painter.drawEllipse(p(12, 12), 3 * s, 3 * s)
        painter.drawEllipse(p(12, 12), 0.8 * s, 0.8 * s)
    elif kind == "check":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))
        mark = QPen(QColor("#FFFFFF"))
        mark.setWidthF(max(1.6, size / 10.0))
        mark.setCapStyle(Qt.PenCapStyle.RoundCap)
        mark.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(mark)
        line((7, 12.5), (10.5, 16), (17, 8))
    elif kind == "lock":
        painter.drawRoundedRect(QRectF(6 * s, 11 * s, 12 * s, 8 * s), 1.4 * s, 1.4 * s)
        painter.drawArc(QRectF(8 * s, 5 * s, 8 * s, 8 * s), 0, 180 * 16)
    painter.end()
    return pix


class RoleCard(QFrame):
    chosen = Signal(str)

    def __init__(
        self,
        role: str,
        title: str,
        description: str,
        points: list[tuple[str, str]],
        *,
        accent: str,
        selected_fill: str,
        icon_kind: str,
        saved_text: str = "마지막 선택",
        lock_text: str = "역할 변경이 잠겨 있습니다",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        self._accent = accent
        self._selected_fill = selected_fill
        self._selected = False
        self._saved_role = False
        self._locked = False
        self._hover = False
        self._hover_t = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_tick)
        self.setObjectName("roleCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(310, 320)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        plate = QLabel()
        plate.setPixmap(_icon(icon_kind, accent, 32))
        plate.setFixedSize(32, 32)
        plate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._check = QLabel()
        self._check.setPixmap(_icon("check", accent, 18))
        self._check.setFixedSize(18, 18)
        self._check.hide()
        top.addWidget(plate, alignment=Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        top.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(top)
        lay.addSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-weight: 700; font-size: 16px; background: transparent;"
        )
        self._saved = QLabel(saved_text)
        self._saved.setStyleSheet(
            f"color: {_MUTED}; background: {_BADGE_BG}; border: 1px solid {_BORDER}; "
            "border-radius: 8px; padding: 1px 7px; font-size: 11px; font-weight: 600;"
        )
        self._saved.hide()
        title_row.addWidget(title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self._saved, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        lay.addLayout(title_row)
        lay.addSpacing(8)

        body = QLabel(description)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {_MUTED}; font-size: 13px; background: transparent;"
        )
        lay.addWidget(body)
        lay.addSpacing(14)

        for icon_name, text in points:
            host = QWidget()
            host.setFixedHeight(26)
            host.setStyleSheet("background: transparent;")
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            mark = QLabel()
            mark.setPixmap(_icon(icon_name, _MUTED, 16))
            mark.setFixedSize(16, 16)
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label = QLabel(text)
            label.setFixedHeight(26)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            label.setStyleSheet(
                f"color: {_TEXT}; font-size: 13px; background: transparent; "
                "padding: 0px; margin: 0px;"
            )
            row.addWidget(mark, alignment=Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(label, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(host)

        lay.addSpacing(8)
        lock_row = QHBoxLayout()
        lock_row.setContentsMargins(0, 0, 0, 0)
        lock_row.setSpacing(6)
        self._lock_icon = QLabel()
        self._lock_icon.setPixmap(_icon("lock", _MUTED, 14))
        self._lock_icon.setFixedSize(14, 14)
        self._lock_text = QLabel(lock_text)
        self._lock_text.setWordWrap(True)
        self._lock_text.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; background: transparent;"
        )
        lock_row.addWidget(self._lock_icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        lock_row.addWidget(self._lock_text, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._lock_host = QWidget()
        self._lock_host.setLayout(lock_row)
        self._lock_host.hide()
        lay.addWidget(self._lock_host)
        lay.addStretch(1)
        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._check.setVisible(self._selected)
        self._apply_style()

    def set_saved(self, saved: bool) -> None:
        """Neutral badge for the stored role. Separate from the selection mark."""
        self._saved_role = bool(saved)
        self._saved.setVisible(self._saved_role)

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self._hover = False
        self._hover_t = 0.0
        self._hover_anim.stop()
        self._lock_host.setVisible(self._locked)
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if locked
            else Qt.CursorShape.PointingHandCursor
        )
        self._apply_style()

    def _on_hover_tick(self, value: object) -> None:
        try:
            self._hover_t = float(value)
        except (TypeError, ValueError):
            self._hover_t = 0.0
        self._apply_style()

    def _move_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event) -> None:
        if not self._locked and not self._selected:
            self._hover = True
            self._move_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._move_hover(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.role)
        super().mousePressEvent(event)

    def _apply_style(self) -> None:
        if self._selected:
            fill = self._selected_fill
            border = self._accent
            width = 2
        else:
            rest_border = _BLUE
            amount = 0.0 if self._locked else self._hover_t
            fill = _mix(_CARD, self._selected_fill, amount * 0.55)
            border = _mix(rest_border, self._accent, amount)
            width = 1
        self.setStyleSheet(
            "QFrame#roleCard {"
            f"background: {fill};"
            f"border: {width}px solid {border};"
            "border-radius: 12px;"
            "}"
            "QFrame#roleCard QLabel { border: none; }"
        )


class PartyRolePicker(QWidget):
    roleChosen = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        strings: dict | None = None,
    ) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 12, 8, 12)
        root.setSpacing(8)

        title = QLabel(tx(strings, "party_ui_picker_title", "파티봇 역할 선택"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {_TEXT}; font-weight: 700; font-size: 16px; background: transparent;"
        )
        root.addWidget(title)
        subtitle = QLabel(
            tx(strings, "party_ui_picker_sub", "파티봇을 어떤 역할로 실행할지 선택하세요.")
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; background: transparent;"
        )
        root.addWidget(subtitle)
        root.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(24)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        saved = tx(strings, "party_ui_last_choice", "마지막 선택")
        locked = tx(strings, "party_ui_locked", "역할 변경이 잠겨 있습니다")
        self.leader_card = RoleCard(
            "leader",
            tx(strings, "party_ui_leader", "파티장"),
            tx(strings, "party_ui_leader_desc", "파티 전체의 사냥 계획과 운영을 관리합니다."),
            [
                ("users", tx(strings, "party_ui_feat_roster", "파티원 관리")),
                ("map", tx(strings, "party_ui_feat_map", "사냥터 및 순찰 지도")),
                ("crosshair", tx(strings, "party_ui_feat_hunt", "사냥 방식")),
                ("package", tx(strings, "party_ui_menu_supply", "마을 및 보급")),
                ("package", tx(strings, "party_ui_feat_loot", "아이템 및 루팅")),
            ],
            accent=_BLUE,
            selected_fill=_BLUE_SOFT,
            icon_kind="crown",
            saved_text=saved,
            lock_text=locked,
        )
        self.member_card = RoleCard(
            "member",
            tx(strings, "party_ui_member", "파티원"),
            tx(strings, "party_ui_member_desc", "파티장에게 연결되어 지정된 정책에 따라 사냥합니다."),
            [
                ("server", tx(strings, "party_ui_feat_server", "파티장 서버 연결")),
                ("activity", tx(strings, "party_ui_feat_link", "연결 상태 확인")),
                ("navigation", tx(strings, "party_ui_feat_follow", "따라가기 설정")),
                ("target", tx(strings, "party_ui_feat_target", "공격 대상 추종")),
                ("crosshair", tx(strings, "party_ui_feat_assist", "어시스트 설정")),
            ],
            accent=_BLUE,
            selected_fill=_BLUE_SOFT,
            icon_kind="user",
            saved_text=saved,
            lock_text=locked,
        )
        self.leader_card.chosen.connect(self.roleChosen.emit)
        self.member_card.chosen.connect(self.roleChosen.emit)
        row.addStretch(1)
        row.addWidget(self.leader_card)
        row.addWidget(self.member_card)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        gap = 24
        side = 16
        avail_w = max(0, self.width() - side * 2 - gap)
        width = min(310, avail_w // 2) if avail_w else 310
        title_block = 72
        avail_h = max(0, self.height() - title_block)
        height = min(320, avail_h) if avail_h else 320
        width = max(220, width)
        height = max(280, height)
        if self.leader_card.width() == width and self.leader_card.height() == height:
            return
        self.leader_card.setFixedSize(width, height)
        self.member_card.setFixedSize(width, height)

    def set_saved(self, role: str | None) -> None:
        self.leader_card.set_saved(role == "leader")
        self.member_card.set_saved(role == "member")

    def set_selected(self, role: str | None) -> None:
        self.leader_card.set_selected(role == "leader")
        self.member_card.set_selected(role == "member")

    def set_locked(self, locked: bool) -> None:
        self.leader_card.set_locked(locked)
        self.member_card.set_locked(locked)
