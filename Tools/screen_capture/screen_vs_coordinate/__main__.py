"""python -m from this folder, or from a parent package."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run import main

if __name__ == "__main__":
    raise SystemExit(main())
