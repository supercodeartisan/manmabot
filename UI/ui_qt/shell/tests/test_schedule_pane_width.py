"""The schedule sash stays put when the UI language changes."""
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

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from ui_qt.shell.schedule_list import _PANE_WIDTH
from ui_qt.shell.schedule_shell import ScheduleShell


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _boundary(shell: ScheduleShell) -> tuple[int, int, int]:
    pane = shell.schedule_list
    host = pane.parentWidget()
    edge = host.mapTo(shell, QPoint(host.width(), 0)).x()
    editor_x = shell.editor.mapTo(shell, QPoint(0, 0)).x()
    return edge, editor_x, int(host.width())


def _fits(shell: ScheduleShell) -> None:
    pane = shell.schedule_list
    host = pane.parentWidget()
    width = int(host.width())
    for widget in (*pane.weekday_checks, pane.random_minutes, pane.account_combo):
        right = widget.mapTo(host, QPoint(widget.width(), 0)).x()
        assert right <= width, (widget, right, width)


def test_language_switch_keeps_the_sash() -> None:
    app = _app()
    shell = ScheduleShell()
    shell._closing = True
    shell._poll_timer.stop()
    shell.show()
    app.processEvents()
    try:
        assert shell.schedule_list.preferred_pane_width() == _PANE_WIDTH == 350
        edges: list[int] = []
        editors: list[int] = []
        for lang in ("ko", "zh", "ko", "zh", "ko", "zh"):
            shell._rebuild_for_language(lang)
            app.processEvents()
            edge, editor_x, width = _boundary(shell)
            assert width == _PANE_WIDTH
            assert edge == editor_x
            edges.append(edge)
            editors.append(editor_x)
            _fits(shell)
        assert len(set(edges)) == 1
        assert len(set(editors)) == 1
        shell.resize(1000, 700)
        app.processEvents()
        shell._lock_pane_split()
        app.processEvents()
        edge, editor_x, width = _boundary(shell)
        assert width == _PANE_WIDTH
        assert edge == edges[0]
        assert editor_x == editors[0]
    finally:
        shell.close()
        app.processEvents()


if __name__ == "__main__":
    test_language_switch_keeps_the_sash()
    print("ok")
