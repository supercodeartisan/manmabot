"""Unified application entry.

``MainWindow`` remains importable as a compatibility reference, but normal
launches use the single-root schedule/operator console.
"""
from __future__ import annotations

import sys

from manmabot_v1.paths import ensure_userdata


def run_app() -> int:
    ensure_userdata()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Manmabot.Version1"
            )
        except Exception:
            pass
    from manmabot_v1.ui.schedule_ui import run_schedule_app

    return run_schedule_app()
