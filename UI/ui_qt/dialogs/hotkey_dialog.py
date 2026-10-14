"""Hotkey editor + capture — parity with classic ``edit_hotkeys`` / ``_capture_hotkey``."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from i18n.strings import DEFAULT_HOTKEYS
from ui_qt.theme.apply import mark_accent


def _key_combo(event: QKeyEvent) -> str | None:
    key = event.key()
    if key in (
        Qt.Key.Key_Shift,
        Qt.Key.Key_Control,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_AltGr,
    ):
        return None
    if key == Qt.Key.Key_Escape:
        return "escape"
    mods: list[str] = []
    modifiers = event.modifiers()
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        mods.append("ctrl")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        mods.append("shift")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        mods.append("alt")
    named = {
        Qt.Key.Key_F1: "f1",
        Qt.Key.Key_F2: "f2",
        Qt.Key.Key_F3: "f3",
        Qt.Key.Key_F4: "f4",
        Qt.Key.Key_F5: "f5",
        Qt.Key.Key_F6: "f6",
        Qt.Key.Key_F7: "f7",
        Qt.Key.Key_F8: "f8",
        Qt.Key.Key_F9: "f9",
        Qt.Key.Key_F10: "f10",
        Qt.Key.Key_F11: "f11",
        Qt.Key.Key_F12: "f12",
        Qt.Key.Key_Space: "space",
        Qt.Key.Key_Tab: "tab",
        Qt.Key.Key_Return: "return",
        Qt.Key.Key_Enter: "enter",
        Qt.Key.Key_Backspace: "backspace",
        Qt.Key.Key_Delete: "delete",
        Qt.Key.Key_Insert: "insert",
        Qt.Key.Key_Home: "home",
        Qt.Key.Key_End: "end",
        Qt.Key.Key_PageUp: "pageup",
        Qt.Key.Key_PageDown: "pagedown",
        Qt.Key.Key_Left: "left",
        Qt.Key.Key_Right: "right",
        Qt.Key.Key_Up: "up",
        Qt.Key.Key_Down: "down",
    }.get(key)
    if named is None:
        text = event.text().strip().lower()
        if text and text.isprintable() and len(text) == 1:
            named = text
        else:
            seq = QKeySequence(key).toString().strip().lower()
            named = seq or None
    if not named:
        return None
    return "+".join([*dict.fromkeys(mods), named])


class HotkeyCaptureDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        strings: dict[str, str],
        action: str,
        used: set[str],
        on_captured: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.t = strings
        self.action = action
        self.used = used
        self.on_captured = on_captured
        self._rejected: str | None = None
        self.setWindowTitle(self.t.get("capture_key", "Capture key"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.t.get("hotkey_capture_prompt", "Press a key…")))
        cancel = QPushButton(self.t.get("cancel", "Cancel"))
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.grabKeyboard()
        self.setFocus()

    def closeEvent(self, event) -> None:
        self.releaseKeyboard()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        combo = _key_combo(event)
        if combo is None:
            return
        if combo == "escape":
            self.reject()
            return
        if combo in self.used:
            if combo == self._rejected:
                return
            self._rejected = combo
            QMessageBox.warning(
                self,
                self.t.get("hotkeys", "Hotkeys"),
                self.t.get("hotkey_in_use", "In use: {key}").format(key=combo),
            )
            return
        self.on_captured(combo)
        self.accept()


class HotkeyEditorDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        strings: dict[str, str],
        initial: dict[str, str],
        on_save: Callable[[dict[str, str]], str | None],
    ) -> None:
        super().__init__(parent)
        self.t = strings
        self.on_save = on_save
        self.values = {
            "pause_resume": str(
                initial.get("pause_resume") or DEFAULT_HOTKEYS["pause_resume"]
            ).lower(),
            "stop": str(initial.get("stop") or DEFAULT_HOTKEYS["stop"]).lower(),
        }
        self.setWindowTitle(self.t.get("hotkeys", "Hotkeys"))
        self.setModal(True)
        self.setFixedWidth(420)
        layout = QGridLayout(self)
        self.labels: dict[str, QLabel] = {}
        for row, (key, label_key) in enumerate(
            (("pause_resume", "pause_hotkey"), ("stop", "stop_hotkey"))
        ):
            layout.addWidget(QLabel(self.t.get(label_key, key)), row, 0)
            field = QLabel(self.values[key])
            field.setObjectName("hotkeyField")
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setMinimumWidth(120)
            field.setStyleSheet(
                "QLabel#hotkeyField { border: 1px solid #d5dbe3; padding: 4px 12px; "
                "background: #ffffff; color: #3a82f6; }"
            )
            self.labels[key] = field
            layout.addWidget(field, row, 1)
            capture = QPushButton(self.t.get("capture_key", "Capture"))
            capture.clicked.connect(lambda _=False, action=key: self._capture(action))
            layout.addWidget(capture, row, 2)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton(self.t.get("save", "Save"))
        mark_accent(save)
        save.clicked.connect(self._save)
        cancel = QPushButton(self.t.get("cancel", "Cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons, 2, 0, 1, 3)

    def _capture(self, action: str) -> None:
        used = {value for key, value in self.values.items() if key != action}
        dialog = HotkeyCaptureDialog(
            self,
            strings=self.t,
            action=action,
            used=used,
            on_captured=lambda combo: self._set(action, combo),
        )
        dialog.exec()

    def _set(self, action: str, combo: str) -> None:
        self.values[action] = combo
        self.labels[action].setText(combo)

    def _save(self) -> None:
        error = self.on_save(dict(self.values))
        if error:
            QMessageBox.critical(self, self.t.get("hotkeys", "Hotkeys"), str(error))
            return
        self.accept()
