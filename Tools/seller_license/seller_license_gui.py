"""Redirect — seller UI lives under ``Seller/seller_license_gui.py``."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parents[2] / "Seller" / "seller_license_gui.py"
if not _TARGET.is_file():
    raise SystemExit(f"missing seller UI: {_TARGET}")
sys.argv[0] = str(_TARGET)
runpy.run_path(str(_TARGET), run_name="__main__")
