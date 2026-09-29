"""Survival behavior: potion on low HP (critical → Retreating via modes)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._04_decision.behavior_tree import (
    ActionNode,
    ConditionNode,
    Node,
    Selector,
    Sequence,
    Status,
)
from app._04_decision.player_mode import HP_CRITICAL_RATIO, HP_LOW_RATIO

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


def _hp_ratio(state: "GameState", blackboard: "Blackboard") -> float | None:
    player = state.player
    if player is None or player.hp is None:
        return None
    if player.max_hp:
        return player.hp / player.max_hp
    return player.hp_ratio


def _is_critical(state: "GameState", blackboard: "Blackboard") -> bool:
    ratio = _hp_ratio(state, blackboard)
    return ratio is not None and ratio <= HP_CRITICAL_RATIO


def _is_low(state: "GameState", blackboard: "Blackboard") -> bool:
    ratio = _hp_ratio(state, blackboard)
    return ratio is not None and ratio <= HP_LOW_RATIO


def _use_hp_potion(state: "GameState", blackboard: "Blackboard") -> Status:
    from app._04_decision import player_mode as pm
    from app._05_action.spell_box import slot_is_enabled

    if not pm.HP_RECOVER_ENABLED or not pm.USE_HP_POTION:
        return Status.FAILURE
    if not slot_is_enabled("hp_potion"):
        return Status.FAILURE
    blackboard.current_goal = "survival_potion"
    blackboard.emit(ActionType.USE_HP_POTION, priority=0.9, reason="low hp")
    return Status.SUCCESS


def build_survival_node() -> Node:
    """Survival: drink a potion when HP is low (not critical).

    Critical HP is handled by PlayerMode.RETREATING in the mode dispatcher;
    this node remains for unit tests and any legacy selectors.
    """
    return Selector(
        [
            Sequence(
                [
                    ConditionNode(_is_low, "hp_low"),
                    # Critical is also ≤ low; modes handle retreat first.
                    # For the standalone node, potion still fires on critical.
                    ActionNode(_use_hp_potion, "use_hp_potion"),
                ],
                name="low_hp",
            ),
        ],
        name="survival",
    )


__all__ = ["build_survival_node", "HP_CRITICAL_RATIO", "HP_LOW_RATIO"]
