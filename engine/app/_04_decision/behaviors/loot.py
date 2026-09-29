"""Loot behavior (Priority 4): pick up the nearest item."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ObjectType
from app._04_decision.behavior_tree import (
    ActionNode,
    ConditionNode,
    Node,
    Selector,
    Sequence,
    Status,
)
from app._04_decision.behaviors.loot_hop import begin_loot_item, tick_loot_item
from app._04_decision.target_selector import select_item

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


def _item_valid(state: "GameState", blackboard: "Blackboard") -> bool:
    item_id = blackboard.current_item_id
    if item_id is None:
        return False
    obj = state.get_object(item_id)
    if obj is None or obj.object_type is not ObjectType.ITEM:
        blackboard.current_item_id = None
        return False
    return True


def _pick_item(state: "GameState", blackboard: "Blackboard") -> bool:
    item = select_item(state)
    if item is not None:
        begin_loot_item(blackboard, item.track_id)
        return True
    blackboard.current_item_id = None
    return False


def _loot(
    state: "GameState",
    blackboard: "Blackboard",
    mid_act: bool,
) -> Status:
    item_id = blackboard.current_item_id
    if item_id is None:
        return Status.FAILURE
    obj = state.get_object(item_id)
    if obj is None:
        blackboard.current_item_id = None
        return Status.FAILURE
    return tick_loot_item(state, blackboard, obj, fresh=not mid_act)


def build_loot_node() -> Node:
    """Loot: keep looting the remembered item, else pick a new one."""
    return Selector(
        [
            Sequence(
                [
                    ConditionNode(_item_valid, "item_valid"),
                    ActionNode(lambda s, b: _loot(s, b, True), "loot_current"),
                ],
                name="continue_loot",
            ),
            Sequence(
                [
                    ConditionNode(_pick_item, "item_found"),
                    ActionNode(lambda s, b: _loot(s, b, False), "loot_new"),
                ],
                name="engage_loot",
            ),
        ],
        name="loot",
    )


__all__ = ["build_loot_node"]
