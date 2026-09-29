"""Elf combat: click target on a 90–140 ms wall-clock cadence (no mouse hold)."""
from __future__ import annotations

from app._05_action.combat_strategies.knight import KnightCombatStrategy


class ElfCombatStrategy(KnightCombatStrategy):
    """Same timed left-clicks as knight (bow/melee auto-attack)."""
