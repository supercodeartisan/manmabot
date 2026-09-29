"""UI package.

Keep this module free of CustomTkinter imports so classic-Tk entry points
(schedule console, debug player) work without that dependency.
"""
from __future__ import annotations


def run_app() -> int:
    """Compatibility wrapper for the legacy CustomTkinter operator window."""
    from manmabot_v1.ui.app import run_app as _run_app

    return int(_run_app())
