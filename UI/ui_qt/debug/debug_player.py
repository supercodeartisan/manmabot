"""Standalone Qt debug player (parity with retired ttk ``DebugPlayer``)."""

from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n.strings import ui_language
from session.bot_controller import RunState
from session.paths import LOG_DIR, ensure_userdata
from session.probes import Lamp, localize_probe_detail
from settings.profile import Profile, load_profile, save_profile
from ui.schedule_i18n import tr
from ui_qt.debug.debug_panel import DebugPanel
from ui_qt.facade.qt_bridge import QtBridge
from ui_qt.theme import apply_classic_qt_theme, tokens
from ui_qt.theme.apply import mark_accent
from ui_qt.theme.run_glyphs import run_glyph


class DebugPlayerWindow(QMainWindow):
    """Independent bot player for debugging (separate from the schedule console)."""

    def __init__(self, profile: Profile | None = None) -> None:
        super().__init__()
        ensure_userdata()
        self.profile = profile or load_profile()
        self.language = ui_language(self.profile.language)
        self.profile.language = self.language
        self.t = tr(self.language)
        self._log_lines: list[str] = []
        self._closing = False

        self.setWindowTitle(self.t.get("debug_player_title", "ZF"))
        self.resize(1100, 720)
        self.setMinimumSize(860, 540)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.bridge = QtBridge(self.profile, parent=self)
        self.bridge.stateChanged.connect(
            self._on_operator_change, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.logLine.connect(
            self.append_log, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.hotbarUpdated.connect(
            self._on_hotbar, Qt.ConnectionType.QueuedConnection
        )

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(self._build_header())

        self.panel = DebugPanel(
            controller=self.bridge.controller,
            get_logs=lambda: list(self._log_lines),
            t=self.t,
            get_arming=lambda: self.bridge.arming,
            note_text=self.t.get("debug_player_hint", ""),
        )
        layout.addWidget(self.panel, stretch=1)

        self.bridge.controller.add_debug_watcher()
        self._refresh_controls()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(50)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.game_lamp = QLabel("")
        self.memory_lamp = QLabel("")
        self.map_lamp = QLabel("")
        for lamp in (self.game_lamp, self.memory_lamp, self.map_lamp):
            lamp.setStyleSheet(f"color: {tokens.TEXT};")
            row.addWidget(lamp)
        row.addStretch(1)

        self.topmost = QCheckBox(self.t.get("always_on_top", "Always on top"))
        self.topmost.setChecked(True)
        self.topmost.toggled.connect(self._on_topmost)
        row.addWidget(self.topmost)

        self.start_btn = QPushButton(self.t.get("start", "Start"))
        self.start_btn.setIcon(run_glyph("start"))
        self.start_btn.clicked.connect(self._start)
        mark_accent(self.start_btn)
        self.resume_btn = QPushButton(self.t.get("resume", "Resume"))
        self.resume_btn.setIcon(run_glyph("resume"))
        self.resume_btn.clicked.connect(self.bridge.resume)
        self.stop_btn = QPushButton(self.t.get("stop", "Stop"))
        self.stop_btn.setIcon(run_glyph("stop"))
        self.stop_btn.clicked.connect(self.bridge.stop)
        for button in (self.start_btn, self.resume_btn, self.stop_btn):
            row.addWidget(button)
        return row

    def _on_topmost(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        self.show()

    def _start(self) -> None:
        error = self.bridge.start()
        if error:
            QMessageBox.warning(
                self,
                self.t.get("cannot_start", "Cannot start"),
                self.bridge.start_error_text(error, self.t),
            )
        self._refresh_controls()

    def _on_hotbar(self, layout: object, slots: object) -> None:
        from settings.spell_defaults import spell_slot_bindings

        self.profile.hotbar_layout = dict(layout or {})
        self.profile.spell_slots = spell_slot_bindings(slots)
        try:
            save_profile(self.profile)
        except Exception:
            pass

    def append_log(self, message: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {message}"
        self._log_lines = (self._log_lines + [line])[-500:]
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with (LOG_DIR / "v1-debug.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            pass
        if getattr(self.panel, "_section", "") == "logs":
            try:
                self.panel.refresh(force=True)
            except Exception:
                pass

    def _on_operator_change(self) -> None:
        self._refresh_controls()
        try:
            self.panel.refresh(force=True)
        except Exception:
            pass

    def _refresh_controls(self) -> None:
        try:
            game, memory, map_probe = self.bridge.probes()

            def lamp(label: QLabel, result) -> None:
                mark = (
                    "●"
                    if result.lamp == Lamp.GREEN
                    else ("◐" if result.lamp == Lamp.YELLOW else "○")
                )
                label.setText(
                    f"{mark} {localize_probe_detail(result.detail, self.language)}"
                )

            lamp(self.game_lamp, game)
            lamp(self.memory_lamp, memory)
            lamp(self.map_lamp, map_probe)
        except Exception:
            pass
        state = self.bridge.controller.state
        arming = self.bridge.arming
        self.start_btn.setEnabled(state == RunState.STOPPED and not arming)
        self.resume_btn.setEnabled(state == RunState.PAUSED)
        self.stop_btn.setEnabled(state != RunState.STOPPED or arming)

    def _on_poll(self) -> None:
        if self._closing:
            return
        self.bridge.poll()
        self._refresh_controls()
        self.panel.refresh()
        delay = 50 if getattr(self.panel, "_section", "") in ("preview", "field_view") else 200
        self._poll.setInterval(delay)

    def closeEvent(self, event) -> None:  # noqa: N802
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
            self.bridge.controller.remove_debug_watcher()
        except Exception:
            pass
        try:
            self.bridge.close()
        except Exception:
            pass
        event.accept()


def run_debug_player() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZF")
        except Exception:
            pass

    from PySide6.QtGui import QIcon

    from settings.map_previews import brand_icon_path

    ensure_userdata()
    app = QApplication.instance() or QApplication(sys.argv)
    profile = load_profile()
    language = ui_language(profile.language)
    app.setApplicationName("종횡" if language == "ko" else "纵锋")
    logo = brand_icon_path()
    if logo is not None:
        app.setWindowIcon(QIcon(str(logo)))
    from ui_qt.theme import tokens
    from ui_qt.theme.apply import font_roles_for_window

    body, section, _title = font_roles_for_window(
        tokens.DEFAULT_WIDTH, tokens.DEFAULT_HEIGHT
    )
    apply_classic_qt_theme(app, language, font_size=body, section_size=section)
    window = DebugPlayerWindow(profile)
    window.show()
    return int(app.exec())
