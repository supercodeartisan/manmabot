"""Launch the NPC click-offset calibrator (writes npc_behaviors.yaml)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from bot_data_editors.npc_click_offset_calibrator import (
    run_npc_click_offset_calibrator,
)


if __name__ == "__main__":
    raise SystemExit(run_npc_click_offset_calibrator())
