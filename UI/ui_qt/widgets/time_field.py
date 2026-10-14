"""HH:MM(:SS) spin field — parity with classic ``_TimeField``."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ui_qt.widgets.step_spin import StepSpinBox


class TimeField(QWidget):
    """Hour/minute spins; seconds fixed at 00 in the stored value."""

    textChanged = Signal(str)

    def __init__(self, initial: str = "00:00:00", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guard = False
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setObjectName("timeField")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.hour = StepSpinBox(two_digit=True, compact=True)
        self.hour.setRange(0, 23)
        self.hour.setWrapping(True)
        self.minute = StepSpinBox(two_digit=True, compact=True)
        self.minute.setRange(0, 59)
        self.minute.setWrapping(True)
        for spin in (self.hour, self.minute):
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._push)
            spin.editingFinished.connect(self._normalize_spins)
        row.addWidget(self.hour)
        row.addWidget(QLabel(":"))
        row.addWidget(self.minute)
        self._fit_spins()
        self.setText(initial)

    def _fit_spins(self) -> None:
        """Size hour/minute steppers for two digits + right-side buttons."""
        metrics = QFontMetrics(self.font())
        pt = self.font().pointSize()
        if pt <= 0:
            pt = max(8, round(self.font().pixelSize() * 0.75))
        field = max(metrics.horizontalAdvance("88"), metrics.boundingRect("88").width())
        width = max(field + 36, 64)
        height = max(metrics.height() + max(8, round(pt * 0.7)), 26)
        for spin in (self.hour, self.minute):
            spin.setFixedWidth(width)
            spin.setFixedHeight(height)
        self.updateGeometry()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_spins()

    def changeEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QEvent

        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_spins()

    def text(self) -> str:
        return f"{self.hour.value():02d}:{self.minute.value():02d}:00"

    def setText(self, value: str) -> None:
        bits = str(value or "00:00:00").split(":")
        try:
            hour = int(str(bits[0]).split(".", 1)[0])
        except (ValueError, IndexError):
            hour = 0
        try:
            minute = int(str(bits[1]).split(".", 1)[0]) if len(bits) > 1 else 0
        except ValueError:
            minute = 0
        self._guard = True
        try:
            self.hour.setValue(max(0, min(23, hour)))
            self.minute.setValue(max(0, min(59, minute)))
        finally:
            self._guard = False

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.hour.setEnabled(enabled)
        self.minute.setEnabled(enabled)

    def _normalize_spins(self) -> None:
        """Pad/clamp like classic ``_TimeField._normalize`` on FocusOut/Return."""
        self._guard = True
        try:
            self.hour.setValue(max(0, min(23, int(self.hour.value()))))
            self.minute.setValue(max(0, min(59, int(self.minute.value()))))
        finally:
            self._guard = False
        self._push()

    def _push(self) -> None:
        if self._guard:
            return
        self.textChanged.emit(self.text())
