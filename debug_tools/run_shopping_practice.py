"""Launch the shopping practice GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from debug_tools.bootstrap import bootstrap

bootstrap()

from debug_tools.shopping_practice import run_shopping_practice


if __name__ == "__main__":
    raise SystemExit(run_shopping_practice())
