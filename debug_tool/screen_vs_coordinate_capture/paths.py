"""Paths for this folder only — copy the folder anywhere."""
from __future__ import annotations

from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = TOOL_DIR / "output"
SETTINGS_PATH = TOOL_DIR / "settings.json"
