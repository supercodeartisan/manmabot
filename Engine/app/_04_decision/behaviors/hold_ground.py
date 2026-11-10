"""Standing shot distance. A character hits inside this reach without stepping."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import CharacterType
from app._04_decision import player_mode as pm

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState

# Melee: farther clicks walk the character. Elf uses solo ``ATTACK_CLICK_TILES``.
MELEE_REACH_TILES = 1


def hold_ground_reach(state: "GameState") -> int:
    """Tiles this character hits without stepping."""
    player = getattr(state, "player", None)
    kind = getattr(player, "character_type", None)
    if kind is CharacterType.MAGE and pm.uses_spell_aim():
        from app._03_world import constants as world_constants

        return int(world_constants.MAGE_SPELL_RANGE)
    if kind is CharacterType.ELF:
        return int(pm.ATTACK_CLICK_TILES)
    return MELEE_REACH_TILES


__all__ = [
    "MELEE_REACH_TILES",
    "hold_ground_reach",
]
