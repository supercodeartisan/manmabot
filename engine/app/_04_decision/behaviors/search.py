"""Search behavior (Priority 5): scan the active farm area."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._04_decision.behavior_tree import ActionNode, Node, Status
from app._04_decision.behaviors.travel import emit_travel_hop
from app._04_decision.farm_area import ARRIVE_TILES
from app._04_decision.mode_control import PURPOSE_ENTER_FARM, begin_travel
from app._04_decision.nav_config import get_active_farm, get_terrain_map
from app._04_decision.behaviors.search_hop import emit_search_hop

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

# Anti-spam: the character is screen-centered, so movement cannot be read
# from its position. A waypoint (leg) is held (emitted with ``mid_act=True``)
# while its age counter is below LEG_TICKS; once the counter reaches
# LEG_TICKS, search rolls the next leg. Each new leg is a real click.
LEG_TICKS = 30


def _enter_farm_if_needed(blackboard: "Blackboard") -> Status | None:
    """If outside the active farm, TRAVEL to the nearest walkable entry.

    Never returns ``None`` while outside the farm: callers must not fall
    through to in-farm search (clamp-to-edge would invent wild clicks).
    """
    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()
    if farm is None or terrain is None:
        return None
    ox, oy = blackboard.world_origin.x, blackboard.world_origin.y
    if farm.contains(ox, oy):
        return None

    start = (ox, oy)
    goal = farm.interior_walkable(terrain, start, margin=ARRIVE_TILES)
    if goal is None:
        blackboard.current_goal = "enter_farm"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.25,
            reason="enter farm, no walkable entry",
        )
        return Status.SUCCESS
    if blackboard.nav_goal != goal:
        begin_travel(
            blackboard,
            goal,
            purpose=PURPOSE_ENTER_FARM,
            reason="enter farm area",
        )
    blackboard.current_goal = "enter_farm"
    if emit_travel_hop(blackboard, reason="enter farm area", priority=0.25):
        return Status.SUCCESS
    blackboard.emit(
        ActionType.IDLE,
        priority=0.25,
        reason="enter farm, path blocked",
    )
    return Status.SUCCESS


def _search(state: "GameState", blackboard: "Blackboard") -> Status:
    player = state.player
    if player is None:
        return Status.FAILURE

    entering = _enter_farm_if_needed(blackboard)
    if entering is not None:
        return entering

    # Unit tests may run without an initialized terrain map; fall back to the
    # legacy tick-based leg hold in that case.
    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()
    if farm is None or terrain is None:
        dest = blackboard.search_destination
        if dest is None:
            dest = blackboard.movement_planner.next_leg(
                blackboard, "search area", persist=True
            )
            reason = "search area"
            blackboard.search_leg_ticks = 0
            mid_act = False
        else:
            blackboard.search_leg_ticks += 1
            if blackboard.search_leg_ticks >= LEG_TICKS:
                dest = blackboard.movement_planner.next_leg(
                    blackboard, "stuck, jumping elsewhere", persist=False
                )
                reason = "stuck, jumping elsewhere"
                blackboard.search_leg_ticks = 0
                mid_act = False
            else:
                reason = "search area"
                mid_act = True

        blackboard.search_destination = dest
        blackboard.last_search_tick = blackboard.tick_count
        blackboard.current_goal = "search"
        blackboard.emit(
            ActionType.SEARCHING,
            destination=dest,
            priority=0.2,
            reason=reason,
            mid_act=mid_act,
        )
        return Status.SUCCESS

    blackboard.current_goal = "search"
    emit_search_hop(
        blackboard,
        reason="search area",
        priority=0.2,
        max_leg_ticks=LEG_TICKS,
    )
    if blackboard.intent is None:
        return Status.FAILURE
    return Status.SUCCESS


def build_search_node() -> Node:
    """Search: no other behavior active, so scan the farm area."""
    return ActionNode(_search, "search")


__all__ = [
    "build_search_node",
    "LEG_TICKS",
]
