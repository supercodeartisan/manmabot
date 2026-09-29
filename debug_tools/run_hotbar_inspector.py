"""Launch the hotbar detection inspector GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from debug_tools.bootstrap import bootstrap

bootstrap()

from debug_tools.hotbar_inspector import run_hotbar_inspector


if __name__ == "__main__":
    raise SystemExit(run_hotbar_inspector())
