"""Redirect: NPC click-offset editor lives under Tools/bot_data_editors/."""
from __future__ import annotations

import runpy
from pathlib import Path

_TARGET = (
    Path(__file__).resolve().parents[1]
    / "bot_data_editors"
    / "run_npc_click_offset.py"
)
runpy.run_path(str(_TARGET), run_name="__main__")
