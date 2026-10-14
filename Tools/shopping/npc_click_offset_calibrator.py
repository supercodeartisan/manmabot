"""Redirect: use ``bot_data_editors.npc_click_offset_calibrator``."""
from bot_data_editors.npc_click_offset_calibrator import (  # noqa: F401
    NpcClickOffsetCalibrator,
    compute_candidate_a,
    run_npc_click_offset_calibrator,
)

__all__ = [
    "NpcClickOffsetCalibrator",
    "compute_candidate_a",
    "run_npc_click_offset_calibrator",
]
