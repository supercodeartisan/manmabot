"""Debug tools package — standalone inspectors (no bot control)."""
from __future__ import annotations

from pathlib import Path

DEBUG_TOOLS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DEBUG_TOOLS_ROOT.parent
OUTPUT_DIR = DEBUG_TOOLS_ROOT / "output"
