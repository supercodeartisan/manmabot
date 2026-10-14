"""Elf combat: one left-click per attack tick (same path as knight)."""
from __future__ import annotations

from app._05_action.combat_strategies.knight import KnightCombatStrategy


class ElfCombatStrategy(KnightCombatStrategy):
    """Same one-click-per-tick path as knight (bow/melee auto-attack)."""
