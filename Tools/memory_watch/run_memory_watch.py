"""Launch the Memory Watch GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from memory_watch.memory_watch_gui import run_memory_watch


if __name__ == "__main__":
    raise SystemExit(run_memory_watch())
