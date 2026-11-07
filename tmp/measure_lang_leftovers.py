"""List Korean labels that survive a switch to simplified Chinese."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "UI"), str(ROOT / "Engine")]
os.environ["QT_QPA_PLATFORM"] = "windows"

import settings.trial_store as trial  # noqa: E402

trial.save_trial = lambda *_a, **_k: None
trial.save_app_state = lambda *_a, **_k: None

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QTabWidget,
    QTableWidget,
    QWidget,
)
from settings.profile import load_profile  # noqa: E402
from ui_qt.shell import schedule_shell as shell_mod  # noqa: E402

shell_mod.ScheduleShell._warm_memory_monitor = lambda self: None
app = QApplication.instance() or QApplication([])
profile = load_profile()
profile.always_on_top = False
profile.language = "ko"
shell = shell_mod.ScheduleShell(profile)
shell.show()
app.processEvents()
import time
before = {id(widget) for widget in shell.findChildren(QWidget)}
old_t = dict(shell.t)
t0 = time.perf_counter()
shell.language_combo.blockSignals(True)
for index in range(shell.language_combo.count()):
    if shell.language_combo.itemData(index) == "zh":
        shell.language_combo.setCurrentIndex(index)
shell.language_combo.blockSignals(False)
shell._on_language_changed()
print("handler_ms", round((time.perf_counter() - t0) * 1000, 1))
app.processEvents()
after = list(shell.findChildren(QWidget))
new_widgets = [widget for widget in after if id(widget) not in before]
print("new", len(new_widgets), "delta", len(after) - len(before))
for widget in new_widgets[:12]:
    print(" +", type(widget).__name__, widget.objectName(), repr(widget.parent().__class__.__name__ if widget.parent() else None))
from ui_qt.i18n_refresh import _apply_keyed_text
for button in shell.findChildren(QRadioButton):
    if button.property("txKey") == "party_ui_keep_hunting":
        key = button.property("txKey")
        print(
            "apply",
            type(key).__name__,
            repr(button.text()),
            repr(old_t.get(key)),
            repr(shell.t.get(key)),
            _apply_keyed_text(button.text(), key, old_t, shell.t),
        )
def _hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


seen = []
for widget in after:
    chunks: list[str] = []
    if isinstance(widget, (QLabel, QAbstractButton)):
        chunks.append(widget.text())
    if isinstance(widget, QGroupBox):
        chunks.append(widget.title())
    if isinstance(widget, QLineEdit):
        chunks.append(widget.placeholderText())
    if isinstance(widget, QComboBox):
        chunks.extend(widget.itemText(row) for row in range(widget.count()))
    if isinstance(widget, QTabWidget):
        chunks.extend(widget.tabText(row) for row in range(widget.count()))
    if isinstance(widget, QTableWidget):
        chunks.extend(
            widget.horizontalHeaderItem(col).text()
            for col in range(widget.columnCount())
            if widget.horizontalHeaderItem(col) is not None
        )
        for row in range(widget.rowCount()):
            for col in range(widget.columnCount()):
                item = widget.item(row, col)
                if item is not None:
                    chunks.append(item.text())
    tip = widget.toolTip()
    if tip:
        chunks.append(tip)
    for text in chunks:
        if text and _hangul(text):
            seen.append(f"{type(widget).__name__}: {text}")
for line in seen:
    print(line)
print("hangul", len(seen))
from settings.accounts import AccountStore
from ui_qt.dialogs.accounts_dialog import AccountEditorDialog, AccountsDialog

listing = AccountsDialog(shell.t, shell, profile=profile, language=shell.language)
listed = []
for row in range(listing.table.rowCount()):
    item = listing.table.item(row, 1)
    if item is not None:
        listed.append(item.text())
print("listed_servers", listed)
editor = AccountEditorDialog(
    shell,
    strings=shell.t,
    language=shell.language,
    store=AccountStore(),
    profile=profile,
)
servers = [editor.server.itemText(row) for row in range(min(editor.server.count(), 8))]
print("new_account_servers", servers)
print("new_account_locale", editor.locale.currentData())
editor._reload_servers("ko")
ko_grid = [editor.server.itemText(row) for row in range(min(editor.server.count(), 4))]
print("ko_grid_while_zh", ko_grid)
print(
    "server_hangul",
    [text for text in servers + ko_grid if any("\uac00" <= ch <= "\ud7a3" for ch in text)],
)
editor.deleteLater()
listing.deleteLater()
app.processEvents()
shell.language_combo.blockSignals(True)
for index in range(shell.language_combo.count()):
    if shell.language_combo.itemData(index) == "ko":
        shell.language_combo.setCurrentIndex(index)
shell.language_combo.blockSignals(False)
t1 = time.perf_counter()
shell._on_language_changed()
print("back_ms", round((time.perf_counter() - t1) * 1000, 1))
app.processEvents()
schedule_servers = []
for row in range(shell.schedule_list.table.rowCount()):
    item = shell.schedule_list.table.item(row, 6)
    if item is not None:
        schedule_servers.append(item.text())
print("schedule_servers", schedule_servers)
stuck = []
for widget in shell.findChildren(QWidget):
    chunks = []
    if isinstance(widget, (QLabel, QAbstractButton)):
        chunks.append(widget.text())
    if isinstance(widget, QTableWidget):
        for row in range(widget.rowCount()):
            for col in range(widget.columnCount()):
                item = widget.item(row, col)
                if item is not None:
                    chunks.append(item.text())
    for text in chunks:
        if text and any("\u4e00" <= ch <= "\u9fff" for ch in text):
            window = widget.window()
            stuck.append(
                f"{type(widget).__name__} win={type(window).__name__}:{window.windowTitle()}: {text}"
            )
print("cjk_after_ko", len(stuck))
for line in stuck[:40]:
    print(" ", line)
shell.close()
app.processEvents()
