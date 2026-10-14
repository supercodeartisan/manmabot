"""``python -m session`` entry (also used by PyInstaller)."""
from __future__ import annotations

from session.elevate import prepare_runtime
from ui_qt.app import run_schedule_app

if __name__ == "__main__":
    prepare_runtime()
    raise SystemExit(run_schedule_app())
