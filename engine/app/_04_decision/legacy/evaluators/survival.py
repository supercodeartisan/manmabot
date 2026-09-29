"""Survival evaluator: emergency handling (HP/MP critical)."""
from __future__ import annotations

from app._04_decision.types import ActionIntent, ActionType
from app._03_world import WorldState


def evaluate(world_state: WorldState) -> ActionIntent | None:
    """Return emergency action if HP is critically low."""
    player = world_state.player
    if player is None or player.hp is None or player.level is None:
        return None

    max_hp = player.level * 50  # rough estimate for Lineage Classic
    if max_hp <= 0:
        return None

    hp_ratio = player.hp / max_hp

    if hp_ratio < 0.2:
        return ActionIntent(
            action=ActionType.ESCAPE,
            priority=1.0,
            reason="critical hp",
        )

    if hp_ratio < 0.4:
        return ActionIntent(
            action=ActionType.USE_HP_POTION,
            priority=0.9,
            reason="low hp",
        )

    return None