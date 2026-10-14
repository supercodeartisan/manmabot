"""Shared helpers for Tools entry points."""
from __future__ import annotations

from pathlib import Path

COMMON_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = COMMON_ROOT.parent
PROJECT_ROOT = TOOLS_ROOT.parent
OUTPUT_DIR = TOOLS_ROOT / "output"
