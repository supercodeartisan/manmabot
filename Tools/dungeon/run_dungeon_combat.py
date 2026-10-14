"""Launch the standalone dungeon combat GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from dungeon.dungeon_combat_gui import run_dungeon_combat


if __name__ == "__main__":
    raise SystemExit(run_dungeon_combat())
