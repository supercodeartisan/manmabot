"""Launch the Memory Read Bench GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from memory_bench.memory_bench_gui import run_memory_bench


if __name__ == "__main__":
    raise SystemExit(run_memory_bench())
