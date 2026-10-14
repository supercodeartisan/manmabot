"""Launch the follow-and-hunt GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from follow_player.follow_gui import run_follow_player


if __name__ == "__main__":
    raise SystemExit(run_follow_player())
