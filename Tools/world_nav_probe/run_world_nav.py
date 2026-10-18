"""Launch the World Nav Probe GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from world_nav_probe.world_nav_gui import run_world_nav_probe


if __name__ == "__main__":
    raise SystemExit(run_world_nav_probe())
