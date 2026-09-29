"""Farm management behavior: inventory and area upkeep (legacy BT node)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._04_decision.behavior_tree import (
    ActionNode,
    ConditionNode,
    Node,
    Selector,
    Sequence,
    Status,
)
from app._04_decision.behaviors.travel import (
    clear_travel,
    emit_travel_hop,
)
from app._04_decision.farm_area import ARRIVE_TILES
from app._04_decision.farm_tour import advance_farm_tour
from app._04_decision.farm_time import (
    FARM_DURATION_LIMIT,
    farm_time_exceeded,
    reset_farm_timer,
)
from app._04_decision.mode_control import (
    PURPOSE_NEXT_FARM,
    begin_travel,
)
from app._04_decision.nav_config import (
    get_farm_areas,
    get_terrain_map,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

INVENTORY_FULL_RATIO = 0.50


def _need_shop(state: "GameState", blackboard: "Blackboard") -> bool:
    from app._04_decision.shop_trip import needs_shop

    return needs_shop(state, blackboard)


def _return_home(state: "GameState", blackboard: "Blackboard") -> Status:
    """Legacy node: shop trip (same as live modes)."""
    from app._04_decision.shop_trip import tick_shop_trip

    status = tick_shop_trip(state, blackboard)
    return status if status is not None else Status.FAILURE


def _farm_time_exceeded(state: "GameState", blackboard: "Blackboard") -> bool:
    if blackboard.scratch.get("changing_area"):
        return True
    return farm_time_exceeded(blackboard)


def _change_area(state: "GameState", blackboard: "Blackboard") -> Status:
    farms = get_farm_areas()
    terrain = get_terrain_map()
    if not farms or terrain is None:
        return Status.FAILURE

    if blackboard.scratch.get("changing_area") and blackboard.nav_goal is not None:
        blackboard.current_goal = "change_area"
        if emit_travel_hop(
            blackboard, reason="traveling to next farm", priority=0.4
        ):
            return Status.SUCCESS
        blackboard.scratch.pop("changing_area", None)
        reset_farm_timer(blackboard)
        blackboard.farm_visit.clear()
        clear_travel(blackboard)
        return Status.FAILURE

    next_index = advance_farm_tour(blackboard)
    farm = farms[next_index]
    start = (blackboard.world_origin.x, blackboard.world_origin.y)
    goal = farm.interior_walkable(terrain, start, margin=ARRIVE_TILES)
    if goal is None:
        return Status.FAILURE

    blackboard.farm_visit.clear()
    blackboard.scratch["changing_area"] = True
    begin_travel(
        blackboard,
        goal,
        purpose=PURPOSE_NEXT_FARM,
        reason="farming time exceeded",
    )
    blackboard.current_goal = "change_area"
    if emit_travel_hop(
        blackboard, reason="farming time exceeded", priority=0.4
    ):
        return Status.SUCCESS
    blackboard.scratch.pop("changing_area", None)
    reset_farm_timer(blackboard)
    return Status.FAILURE


def build_farm_management_node() -> Node:
    """Farm: shop for arrows when needed, else rotate area on a timer."""
    return Selector(
        [
            Sequence(
                [
                    ConditionNode(_need_shop, "need_shop"),
                    ActionNode(_return_home, "return_home"),
                ],
                name="return_home",
            ),
            Sequence(
                [
                    ConditionNode(_farm_time_exceeded, "farm_time_exceeded"),
                    ActionNode(_change_area, "change_area"),
                ],
                name="change_area",
            ),
        ],
        name="farm_management",
    )


__all__ = [
    "build_farm_management_node",
    "INVENTORY_FULL_RATIO",
    "FARM_DURATION_LIMIT",
]
