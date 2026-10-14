"""UI package.

Toolkit-free helpers live here (coordinator, i18n, fonts, scale).
The operator console is ``ui_qt``. Legacy ttk modules remain for Tools.
"""
from __future__ import annotations


def run_app() -> int:
    """Compatibility entry → Qt schedule console."""
    from ui_qt.app import run_schedule_app

    return int(run_schedule_app())
