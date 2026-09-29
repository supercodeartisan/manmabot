"""Per-class combat execution strategies (action layer).

Decision still emits ``ATTACK`` + ``target_id``; each character class
interprets that differently (timed clicks, cast loop, …).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app._03_world import CharacterType

if TYPE_CHECKING:
    from app._01_capture.window_bounds import WindowBounds
    from app._03_world import WorldState
    from app._04_decision.types import ActionIntent
    from app._05_action.controller import ActionExecutor


class CombatStrategy(Protocol):
    """Execute one combat tick for a character class."""

    def attack(
        self,
        executor: "ActionExecutor",
        action: "ActionIntent",
        game_state: "WorldState",
        bounds: "WindowBounds",
        *,
        mid_act: bool,
    ) -> None:
        """Apply attack input for this tick (may no-op while throttled)."""


def combat_strategy_for(character: CharacterType) -> CombatStrategy:
    """Return the combat strategy for ``character``."""
    from app._05_action.combat_strategies.elf import ElfCombatStrategy
    from app._05_action.combat_strategies.knight import KnightCombatStrategy
    from app._05_action.combat_strategies.mage import MageCombatStrategy
    from app._05_action.combat_strategies.royal import RoyalCombatStrategy

    if character is CharacterType.MAGE:
        return MageCombatStrategy()
    if character is CharacterType.ELF:
        return ElfCombatStrategy()
    if character is CharacterType.ROYAL:
        return RoyalCombatStrategy()
    # KNIGHT and any unknown → knight timed clicks for now
    return KnightCombatStrategy()


__all__ = [
    "CombatStrategy",
    "combat_strategy_for",
]
