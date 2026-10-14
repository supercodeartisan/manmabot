"""Companion debug window for the Qt schedule console."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget, QMainWindow

from session.bot_controller import BotController
from ui_qt.debug.debug_panel import DebugPanel
from ui_qt.theme import tokens


class DebugWindow(QMainWindow):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: BotController,
        get_logs: Callable[[], list[str]],
        t: dict[str, str],
        on_close: Callable[[], None] | None = None,
        get_arming: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._on_close = on_close
        self._closing = False
        self.t = t
        self.setWindowTitle(t.get("debug_title", "Bot debug"))
        self.resize(1180, 700)
        self.setMinimumSize(900, 520)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        top.addStretch(1)
        self.topmost = QCheckBox(t.get("always_on_top", "Always on top"))
        self.topmost.setChecked(True)
        self.topmost.toggled.connect(self._on_topmost)
        top.addWidget(self.topmost)
        layout.addLayout(top)

        self.panel = DebugPanel(
            controller=controller,
            get_logs=get_logs,
            t=t,
            get_arming=get_arming,
            note_text=t.get("debug_same_run", "Same live run as the operator console."),
        )
        layout.addWidget(self.panel, stretch=1)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.controller.add_debug_watcher()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(200)

    def _on_topmost(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        self.show()

    def _on_poll(self) -> None:
        if self._closing:
            return
        self.panel.refresh()
        delay = 50 if self.panel._section in ("preview", "field_view") else 200
        self._poll.setInterval(delay)

    def closeEvent(self, event) -> None:
        if self._closing:
            event.accept()
            return
        self._closing = True
        self._poll.stop()
        try:
            self.panel.shutdown()
        except Exception:
            pass
        try:
            self.controller.remove_debug_watcher()
        except Exception:
            pass
        callback = self._on_close
        event.accept()
        if callback is not None:
            callback()
