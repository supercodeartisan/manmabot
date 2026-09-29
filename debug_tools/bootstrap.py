"""Shared bootstrap for debug_tools entry points."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from debug_tools import OUTPUT_DIR, PROJECT_ROOT


def bootstrap() -> Path:
    """Ensure project root / engine are on sys.path and MANMABOT_ROOT is set."""
    root = PROJECT_ROOT
    engine = root / "engine"
    os.environ.setdefault("MANMABOT_ROOT", str(engine.resolve()))
    for path in (root, engine):
        text = str(path.resolve())
        if text not in sys.path:
            sys.path.insert(0, text)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return root
