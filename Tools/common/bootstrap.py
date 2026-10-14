"""Shared bootstrap for Tools entry points."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from common import OUTPUT_DIR, PROJECT_ROOT


def bootstrap() -> Path:
    """Ensure product root / Engine / UI / Tools are on sys.path."""
    root = PROJECT_ROOT
    engine = root / "Engine"
    ui_root = root / "UI"
    tools = root / "Tools"
    os.environ.setdefault("MANMABOT_ROOT", str(engine.resolve()))
    for path in (root, engine, ui_root, tools):
        text = str(path.resolve())
        if text not in sys.path:
            sys.path.insert(0, text)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return root
