"""Unified application entry — Qt schedule / operator console."""
from __future__ import annotations

import sys

from session.paths import ensure_userdata


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
    from ui_qt.app import run_schedule_app

    return int(run_schedule_app())
