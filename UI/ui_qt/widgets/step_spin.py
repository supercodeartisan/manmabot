"""Value field with inset ▲/▼ — same chrome pattern as QComboBox drop-down."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class _TwoDigitSpin(QSpinBox):
    """Always show two digits (classic time field)."""

    def textFromValue(self, value: int) -> str:  # noqa: N802
        return f"{int(value):02d}"

    def valueFromText(self, text: str) -> int:  # noqa: N802
        raw = str(text or "").strip()
        if not raw:
            return 0
        try:
            return int(raw.split(".", 1)[0])
        except ValueError:
            return 0


class StepSpinBox(QWidget):
    """Integer spin: one input frame with inset ▲/▼ (combo drop-down style).

    Duck-types the common ``QSpinBox`` API used across the Qt UI so call sites
    can swap ``QSpinBox()`` → ``StepSpinBox()`` without logic changes.
    """

    valueChanged = Signal(int)
    editingFinished = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        two_digit: bool = False,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stepSpin")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Inset padding matches QComboBox::drop-down { margin: 2px }.
        inset = 2
        row = QHBoxLayout(self)
        row.setContentsMargins(1, inset, inset, inset)
        row.setSpacing(2)

        self._spin: QSpinBox = _TwoDigitSpin() if two_digit else QSpinBox()
        self._spin.setObjectName("stepSpinField")
        self._spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin.setKeyboardTracking(False)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._spin.valueChanged.connect(self.valueChanged.emit)
        self._spin.editingFinished.connect(self.editingFinished.emit)
        self._spin.installEventFilter(self)
        line = self._spin.lineEdit()
        if line is not None:
            line.setAlignment(Qt.AlignmentFlag.AlignCenter)
            line.installEventFilter(self)

        btn_w = 18 if compact else 20
        btns = QWidget()
        btns.setObjectName("stepSpinBtns")
        btns.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        btns.setFixedWidth(btn_w)
        btns.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        btns.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btns = btns
        col = QVBoxLayout(btns)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._up = QPushButton("▲")
        self._up.setObjectName("stepSpinUp")
        self._up.setFlat(True)
        self._up.setAutoDefault(False)
        self._up.setDefault(False)
        self._up.setAutoRepeat(True)
        self._up.setAutoRepeatDelay(400)
        self._up.setAutoRepeatInterval(60)
        self._up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._up.setCursor(Qt.CursorShape.PointingHandCursor)
        self._up.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._up.clicked.connect(self._spin.stepUp)

        self._down = QPushButton("▼")
        self._down.setObjectName("stepSpinDown")
        self._down.setFlat(True)
        self._down.setAutoDefault(False)
        self._down.setDefault(False)
        self._down.setAutoRepeat(True)
        self._down.setAutoRepeatDelay(400)
        self._down.setAutoRepeatInterval(60)
        self._down.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._down.setCursor(Qt.CursorShape.PointingHandCursor)
        self._down.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._down.clicked.connect(self._spin.stepDown)

        col.addWidget(self._up, 1)
        col.addWidget(self._down, 1)

        row.addWidget(self._spin, 1)
        row.addWidget(btns, 0)

        self._compact = compact
        self.setMinimumWidth(68 if compact else 78)
        self._fit_default_size()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            focused = event.type() == QEvent.Type.FocusIn
            self.setProperty("spinFocused", focused)
            self.style().unpolish(self)
            self.style().polish(self)
        return super().eventFilter(watched, event)

    def _fit_default_size(self) -> None:
        metrics = QFontMetrics(self.font())
        pt = self.font().pointSize()
        if pt <= 0:
            pt = max(8, round(self.font().pixelSize() * 0.75))
        height = max(metrics.height() + max(8, round(pt * 0.7)), 26 if not self._compact else 24)
        self.setMinimumHeight(height)
        self.setFixedHeight(height)

    # --- QSpinBox-compatible API -------------------------------------------------

    def value(self) -> int:
        return int(self._spin.value())

    def setValue(self, value: int) -> None:
        self._spin.setValue(int(value))

    def minimum(self) -> int:
        return int(self._spin.minimum())

    def maximum(self) -> int:
        return int(self._spin.maximum())

    def setMinimum(self, value: int) -> None:
        self._spin.setMinimum(int(value))

    def setMaximum(self, value: int) -> None:
        self._spin.setMaximum(int(value))

    def setRange(self, low: int, high: int) -> None:
        self._spin.setRange(int(low), int(high))

    def setSuffix(self, suffix: str) -> None:
        self._spin.setSuffix(suffix)

    def setPrefix(self, prefix: str) -> None:
        self._spin.setPrefix(prefix)

    def setSingleStep(self, step: int) -> None:
        self._spin.setSingleStep(int(step))

    def setWrapping(self, wrapping: bool) -> None:
        self._spin.setWrapping(bool(wrapping))

    def setAlignment(self, alignment: Qt.AlignmentFlag) -> None:
        self._spin.setAlignment(alignment)
        line = self._spin.lineEdit()
        if line is not None:
            line.setAlignment(alignment)

    def setKeyboardTracking(self, enable: bool) -> None:
        self._spin.setKeyboardTracking(bool(enable))

    def setReadOnly(self, enable: bool) -> None:
        self._spin.setReadOnly(bool(enable))
        self._up.setEnabled(not enable and self.isEnabled())
        self._down.setEnabled(not enable and self.isEnabled())

    def lineEdit(self):
        return self._spin.lineEdit()

    def stepUp(self) -> None:
        self._spin.stepUp()

    def stepDown(self) -> None:
        self._spin.stepDown()

    def blockSignals(self, block: bool) -> bool:  # noqa: N802
        a = super().blockSignals(block)
        self._spin.blockSignals(block)
        return a

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self._spin.setEnabled(enabled)
        self._up.setEnabled(enabled)
        self._down.setEnabled(enabled)

    def setFixedWidth(self, w: int) -> None:  # noqa: N802
        super().setFixedWidth(w)

    def setFixedHeight(self, h: int) -> None:  # noqa: N802
        super().setFixedHeight(h)

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        metrics = QFontMetrics(self.font())
        w = max(hint.width(), metrics.horizontalAdvance("00000") + 36)
        h = max(hint.height(), self.minimumHeight())
        hint.setWidth(w)
        hint.setHeight(h)
        return hint

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_default_size()
