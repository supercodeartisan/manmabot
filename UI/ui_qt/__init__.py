"""PySide6 operator shell (default console; ttk via run.py --ui tk)."""

from __future__ import annotations

__all__ = ["run_schedule_app"]


def run_schedule_app() -> int:
    from ui_qt.app import run_schedule_app as _run

    return int(_run())
