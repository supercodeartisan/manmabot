"""Farm-management knobs kept for ``configure.py`` sync (live upkeep is in mode_ticks)."""
from __future__ import annotations

from app._04_decision.farm_time import FARM_DURATION_LIMIT

INVENTORY_FULL_RATIO = 0.50

__all__ = [
    "INVENTORY_FULL_RATIO",
    "FARM_DURATION_LIMIT",
]
