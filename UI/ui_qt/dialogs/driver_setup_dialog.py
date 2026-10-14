"""Modal Interception + memory driver setup (Qt)."""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n.strings import ui_strings
from session.driver_setup import driver_readiness, install_interception_driver
from session.monitor_launch import ensure_monitor_connected
from ui_qt.theme import tokens


class _WorkerBridge(QObject):
    finished = Signal(str)
    logLine = Signal(str)


class DriverSetupDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        language: str = "en",
        require_ready: bool = True,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = ui_strings(language)
        self.require_ready = require_ready
        self.on_log = on_log
        self.ready = False
        self._working = False
        self._bridge = _WorkerBridge(self)
        self._bridge.finished.connect(self._memory_done)
        self._bridge.logLine.connect(
            self._forward_log, Qt.ConnectionType.QueuedConnection
        )

        self.setWindowTitle(self.s.drivers_setup)
        self.setFixedSize(480, 330)
        self.setModal(True)

        root = QVBoxLayout(self)
        title = QLabel(self.s.drivers_setup)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)
        hint = QLabel(self.s.drivers_setup_hint)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        root.addWidget(hint)

        self.input_status = self._status_row(
            self.s.interception_driver,
            self.s.install_interception,
            self._install_input,
        )
        root.addWidget(self.input_status["row"])
        self.memory_status = self._status_row(
            self.s.lamp_memory,
            self.s.setup_memory_reader,
            self._setup_memory,
        )
        root.addWidget(self.memory_status["row"])

        self.restart_hint = QLabel("")
        self.restart_hint.setWordWrap(True)
        self.restart_hint.setStyleSheet("color: #ca8a04;")
        root.addWidget(self.restart_hint)
        root.addStretch(1)

        footer = QHBoxLayout()
        self.retry_btn = QPushButton(self.s.check_again)
        self.retry_btn.clicked.connect(self.refresh)
        footer.addWidget(self.retry_btn)
        footer.addStretch(1)
        self.close_btn = QPushButton(self.s.species_done)
        self.close_btn.clicked.connect(self._close)
        footer.addWidget(self.close_btn)
        root.addLayout(footer)
        self.refresh()

    def _status_row(self, title: str, button_text: str, command) -> dict[str, Any]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(QLabel(title), stretch=1)
        status = QLabel("")
        layout.addWidget(status)
        button = QPushButton(button_text)
        button.clicked.connect(command)
        layout.addWidget(button)
        return {"row": row, "label": status, "button": button}

    def _set_working(self, working: bool) -> None:
        self._working = working
        for item in (self.input_status, self.memory_status):
            item["button"].setEnabled(not working)
        self.retry_btn.setEnabled(not working)
        self.close_btn.setEnabled(not working)

    def refresh(self) -> None:
        state = driver_readiness()
        self.ready = bool(state.ready)
        for ok, detail, item in (
            (state.interception, state.interception_detail, self.input_status),
            (state.memory, state.memory_detail, self.memory_status),
        ):
            item["label"].setText(
                self.s.driver_ready if ok else self.s.driver_not_ready
            )
            item["label"].setStyleSheet(
                "color: #16a34a;" if ok else "color: #dc2626;"
            )
            item["label"].setToolTip(str(detail or ""))

    def _forward_log(self, message: str) -> None:
        if self.on_log is not None:
            self.on_log(str(message))

    def _thread_log(self, message: str) -> None:
        """Marshal monitor install logs onto the UI thread."""
        self._bridge.logLine.emit(str(message))

    def _install_input(self) -> None:
        ok, detail = install_interception_driver(log=self.on_log)
        self.restart_hint.setText(str(detail or ""))
        if ok and self.on_log:
            self.on_log(str(detail))
        self.refresh()

    def _setup_memory(self) -> None:
        if self._working:
            return
        self._set_working(True)
        self.memory_status["label"].setText(self.s.wizard_starting_monitor)

        def runner() -> None:
            result = ensure_monitor_connected(
                elevate=True,
                start_driver=True,
                timeout_s=20.0,
                log=self._thread_log,
            )
            self._bridge.finished.emit(str(getattr(result, "detail", "") or ""))

        threading.Thread(target=runner, name="qt-driver-setup", daemon=True).start()

    def _memory_done(self, detail: str) -> None:
        self.restart_hint.setText(detail)
        self._set_working(False)
        self.refresh()

    def _close(self) -> None:
        if self._working:
            return
        if self.require_ready and not self.ready:
            QMessageBox.information(self, self.s.drivers_setup, self.s.drivers_setup_hint)
            return
        self.accept()

    def reject(self) -> None:
        if self._working:
            return
        super().reject()


def show_driver_setup(
    parent: QWidget | None,
    *,
    language: str = "en",
    require_ready: bool = True,
    on_log: Callable[[str], None] | None = None,
) -> bool:
    dialog = DriverSetupDialog(
        parent,
        language=language,
        require_ready=require_ready,
        on_log=on_log,
    )
    dialog.exec()
    return bool(dialog.ready)
