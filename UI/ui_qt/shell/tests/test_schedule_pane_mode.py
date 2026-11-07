"""Party mode locks the schedule pane without dropping its rows."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[4]
for _path in (_ROOT / "UI", _ROOT / "Engine"):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from PySide6.QtWidgets import QApplication, QPushButton

from settings.schedule import ScheduleStore, ScheduleTask
from ui_qt.shell.schedule_list import ScheduleListPane
from ui_qt.shell.schedule_shell import ScheduleShell


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pane() -> ScheduleListPane:
    task = ScheduleTask(name="알파", enabled=True)
    return ScheduleListPane(
        store=ScheduleStore(),
        tasks=[task],
        strings={},
        language="ko",
    )


def _shell(pane: ScheduleListPane, mode: str) -> ScheduleShell:
    shell = ScheduleShell.__new__(ScheduleShell)
    shell._settings_mode = mode
    shell.schedule_list = pane
    return shell


def test_party_mode_disables_schedule_pane_without_resizing_or_dropping_rows() -> None:
    _app()
    pane = _pane()
    pane.resize(314, 700)
    pane.show()
    before = (pane.width(), pane.height(), pane.pos())
    names = [task.name for task in pane.tasks]
    shell = _shell(pane, "solo")
    shell._apply_schedule_pane_mode()
    assert pane.isEnabled() is True
    add = next(button for button in pane.findChildren(QPushButton) if button.isEnabled())

    shell._settings_mode = "party"
    shell._apply_schedule_pane_mode()
    assert pane.isEnabled() is False
    assert pane.routine_box.isEnabled() is False
    assert pane.routine_table.isEnabled() is False
    assert "color: #a0a6ad" in pane.routine_box.styleSheet()
    assert pane.isHidden() is False
    assert (pane.width(), pane.height(), pane.pos()) == before
    assert [task.name for task in pane.tasks] == names
    assert add.isEnabled() is False
    assert shell._commit_add() is False
    assert shell._commit_update() is False
    assert [task.name for task in pane.tasks] == names

    shell._settings_mode = "solo"
    shell._apply_schedule_pane_mode()
    assert pane.isEnabled() is True
    assert pane.routine_box.isEnabled() is True
    assert pane.routine_box.styleSheet() == ""
    assert add.isEnabled() is True
    assert [task.name for task in pane.tasks] == names


def test_party_mode_does_not_tick_the_schedule_clock() -> None:
    shell = ScheduleShell.__new__(ScheduleShell)
    shell._settings_mode = "party"
    shell._session = None
    shell._drive_schedule()
