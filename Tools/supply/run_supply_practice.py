"""Launch the supply practice GUI (Administrator required)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _early_elevate() -> None:
    """UAC before heavy imports so a medium-integrity process exits quickly."""
    if os.name != "nt":
        return
    try:
        import ctypes

        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        pass
    from supply.elevate_supply_practice import main as elevate_main

    raise SystemExit(0 if elevate_main() == 0 else 1)


if __name__ == "__main__":
    _early_elevate()

    from common.bootstrap import bootstrap

    bootstrap()

    from supply.supply_practice_gui import run_supply_practice

    raise SystemExit(run_supply_practice())
