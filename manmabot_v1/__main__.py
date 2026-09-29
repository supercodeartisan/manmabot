"""``python -m manmabot_v1`` entry (also used by PyInstaller)."""
from __future__ import annotations

from manmabot_v1.elevate import prepare_runtime
from manmabot_v1.ui.app import run_app

if __name__ == "__main__":
    prepare_runtime()
    raise SystemExit(run_app())
