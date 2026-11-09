"""Launch the supply inventory grid click calibrator."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from supply_grid.grid_calibrator import main


if __name__ == "__main__":
    main()
