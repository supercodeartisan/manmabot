"""Arrival-based hop driver for farm SEARCHING.

Coverage goals still come from ``MovementPlanner.next_leg``. Each hop click
is chosen with ``plan_body_click`` (same guide→interim→hop as travel/loot).
While a hop is active, a standing body re-clicks about every 0.1s.
"""

from __future__ import annotations

import time
from app._03_world import ActionType
from app._03_world.space.world_coords import tile_chebyshev
from app._04_decision.behaviors.unstick import (
    SCRATCH_ESCAPED,
    reset_unstick_tries,
    try_movement_unstick,
)
from app._04_decision.farm_area import ARRIVE_TILES
from app._04_decision.nav_config import (
    get_active_farm,
    get_coverage_cell,
    get_terrain_map,
)
from app._04_decision import player_mode as pm


def suspend_search_click(blackboard) -> None:
    """Drop the click that is in flight. ``search_leg_goal`` stays.

    Loot, a fight, a wall step, and a supply pickup take the tick without
    ending the coverage leg. The next search tick plans a new hop from the
    live tile toward that same goal. The 60-tick cap counts only ticks that
    run this function's caller, so a gap does not add to it.
    """
    blackboard.search_leg_ticks = 0
    blackboard.search_destination = None
    blackboard.search_waypoint = None
    blackboard.search_hop_active = False
    blackboard.search_click_at = 0.0
    blackboard.search_stuck_tile = None
    blackboard.search_stuck_since_tick = 0
    blackboard.search_stuck_since_time = 0.0
    blackboard.search_unstick_active = False
    reset_unstick_tries(blackboard)


def clear_search_hop(blackboard) -> None:
    """Drop the click and the coverage goal.

    Used when the leg is no longer a hunt target: arrival already clears the
    goal on its own path, and this call covers a new mark, leaving the farm,
    and the start of travel or retreat.
    """
    suspend_search_click(blackboard)
    blackboard.search_leg_goal = None


def _near_tile(blackboard, tile: tuple[int, int]) -> bool:
    return (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            tile[0],
            tile[1],
        )
        <= ARRIVE_TILES
    )


def _reset_stuck(blackboard) -> None:
    blackboard.search_stuck_tile = (
        blackboard.world_origin.x,
        blackboard.world_origin.y,
    )
    blackboard.search_stuck_since_tick = blackboard.tick_count
    blackboard.search_stuck_since_time = time.time()


def _is_stuck(blackboard) -> bool:
    cur = (blackboard.world_origin.x, blackboard.world_origin.y)
    if blackboard.search_stuck_tile is not None and blackboard.search_stuck_tile != cur:
        reset_unstick_tries(blackboard)
    if blackboard.search_stuck_tile != cur:
        _reset_stuck(blackboard)
        return False
    if blackboard.search_stuck_since_time <= 0:
        _reset_stuck(blackboard)
        return False
    elapsed = time.time() - blackboard.search_stuck_since_time
    return elapsed >= pm.TRAVEL_UNSTICK_SECONDS


def _emit_search_click(
    blackboard,
    *,
    destination,
    waypoint: tuple[int, int],
    reason: str,
    priority: float,
    mid_act: bool,
) -> None:
    from app.bot_log import event

    blackboard.search_destination = destination
    blackboard.search_waypoint = waypoint
    blackboard.search_hop_active = True
    blackboard.search_unstick_active = False
    blackboard.search_leg_ticks = 0
    if not mid_act:
        blackboard.search_click_at = time.time()
        from app._04_decision.clickgap import note_plan

        note_plan(f"search wp={waypoint} reason={reason}")
        event(
            "search",
            "hop start wp=%s reason=%s",
            waypoint,
            reason,
        )
    blackboard.emit(
        ActionType.SEARCHING,
        destination=destination,
        priority=priority,
        reason=reason,
        mid_act=mid_act,
    )


def _note_coverage(blackboard, tile: tuple[int, int]) -> None:
    cell = get_coverage_cell()
    key = (int(tile[0]) // cell, int(tile[1]) // cell)
    blackboard.farm_visit[key] = blackboard.farm_visit.get(key, 0) + 1


def _emit_body_hop(
    blackboard,
    *,
    state: object | None,
    terrain,
    goal: tuple[int, int],
    reason: str,
    priority: float,
) -> bool:
    """Click one avoidance hop toward ``goal``. False = no click this tick."""
    from app._04_decision.avoidance import collect_body_tiles, plan_body_click
    from app._04_decision.pathfinding import waypoint_to_content

    origin = blackboard.world_origin
    bodies = collect_body_tiles(state, origin) if state is not None else set()
    planned = plan_body_click(
        terrain,
        origin,
        (int(goal[0]), int(goal[1])),
        bodies,
    )
    from app._04_decision.behaviors.unstick import note_confined_planned_avoid

    note_confined_planned_avoid(blackboard, planned, bodies)
    if planned.click is not None:
        wp = (int(planned.click[0]), int(planned.click[1]))
        _emit_search_click(
            blackboard,
            destination=waypoint_to_content(wp, origin),
            waypoint=wp,
            reason=reason,
            priority=priority,
            mid_act=False,
        )
        return True

    # Path exists but no safe click yet — hold without dropping the leg goal.
    if planned.guide:
        from app._04_decision.clickgap import note_hold

        note_hold(
            f"search:{planned.note}",
            f"search no click note={planned.note} goal={goal}",
        )
        blackboard.search_hop_active = True
        blackboard.search_waypoint = None
        blackboard.search_destination = None
        blackboard.last_search_tick = blackboard.tick_count
        blackboard.emit(
            ActionType.SEARCHING,
            destination=waypoint_to_content(
                (int(goal[0]), int(goal[1])), origin
            ),
            priority=priority,
            reason=planned.note or reason,
            mid_act=True,
        )
        return False

    return False


def _start_leg(
    blackboard,
    *,
    state: object | None,
    terrain,
    reason: str,
    priority: float,
    persist: bool,
) -> bool:
    dest = blackboard.movement_planner.next_leg(
        blackboard, reason, persist=persist
    )
    if not blackboard.leg_history:
        clear_search_hop(blackboard)
        return False
    last_leg = blackboard.leg_history[-1]
    goal = last_leg.absolute_target
    if goal is None or not last_leg.walkable:
        clear_search_hop(blackboard)
        return False
    blackboard.search_leg_goal = (int(goal[0]), int(goal[1]))
    if _emit_body_hop(
        blackboard,
        state=state,
        terrain=terrain,
        goal=blackboard.search_leg_goal,
        reason=reason,
        priority=priority,
    ):
        blackboard.last_search_tick = blackboard.tick_count
        return True
    # Planner gave a goal but avoidance had no path — keep goal for next tick
    # via spiral fallback in mode_ticks when intent is missing.
    if dest is not None and blackboard.intent is None:
        clear_search_hop(blackboard)
        return False
    blackboard.last_search_tick = blackboard.tick_count
    return blackboard.intent is not None


def _follow_body_click(
    blackboard,
    state: object | None,
    terrain,
    waypoint: tuple[int, int],
    *,
    reason: str,
    priority: float,
) -> bool:
    """Hold or re-click the current hop. False = click line closed, replan hop."""
    from app._04_decision.avoidance import (
        classify_ground_reclick,
        click_clear,
        collect_body_tiles,
    )
    from app._04_decision.pathfinding import waypoint_to_content
    from app._05_action.body_pose import body_is_moving

    origin = blackboard.world_origin
    start = (int(origin.x), int(origin.y))
    moving = body_is_moving()
    if moving is not True and state is not None:
        bodies = collect_body_tiles(state, origin)
        if not click_clear(terrain, bodies, start, waypoint):
            from app.bot_log import event

            event(
                "avoid",
                "line closed kind=search wp=%s bodies=%d from=%s",
                waypoint,
                len(bodies),
                start,
            )
            from app._04_decision.behaviors.unstick import note_confined_line_closed

            note_confined_line_closed(blackboard)
            blackboard.search_hop_active = False
            blackboard.search_destination = None
            blackboard.search_waypoint = None
            return False
    now = time.time()
    follow = classify_ground_reclick(
        moving,
        float(blackboard.search_click_at or 0.0),
        now=now,
    )
    if follow == "repeat":
        from app._04_decision.avoidance import log_ground_pause

        log_ground_pause(
            "search",
            waypoint,
            moving,
            float(blackboard.search_click_at or 0.0),
            now,
            reason,
        )
    content = blackboard.search_destination
    if content is None:
        content = waypoint_to_content(waypoint, origin)
    _emit_search_click(
        blackboard,
        destination=content,
        waypoint=waypoint,
        reason=reason,
        priority=priority,
        mid_act=follow != "repeat",
    )
    return True


def emit_search_hop(
    blackboard,
    *,
    reason: str,
    priority: float,
    max_leg_ticks: int,
    state: object | None = None,
) -> bool:
    """Emit ActionType.SEARCHING for the current tick.

    Returns ``True`` if a click was emitted (mid_act=False), ``False`` if we
    only kept walking (mid_act=True).

    A gap of more than one tick means another action took the ladder. The
    click is dropped. The coverage goal stays, and this call plans a new hop
    from the live tile toward that goal. A new goal is chosen when the old
    one is already gone, the body is on it, or the 60-tick cap fires.
    """
    if blackboard.last_search_tick > 0 and blackboard.tick_count - blackboard.last_search_tick > 1:
        suspend_search_click(blackboard)

    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()

    if farm is None or terrain is None:
        clear_search_hop(blackboard)
        return False

    origin = (blackboard.world_origin.x, blackboard.world_origin.y)
    if not farm.contains(*origin):
        # Outside farm: enter-farm travel owns movement; do not invent hops.
        clear_search_hop(blackboard)
        return False

    # Plan a new coverage leg if we have nothing active.
    if blackboard.search_waypoint is None or not blackboard.search_hop_active:
        goal = blackboard.search_leg_goal
        if goal is not None and not _near_tile(blackboard, goal):
            # Same coverage goal; only the hop click was dropped.
            if _emit_body_hop(
                blackboard,
                state=state,
                terrain=terrain,
                goal=goal,
                reason=reason,
                priority=priority,
            ):
                blackboard.last_search_tick = blackboard.tick_count
                return True
            if blackboard.intent is not None:
                return False
        return _start_leg(
            blackboard,
            state=state,
            terrain=terrain,
            reason=reason,
            priority=priority,
            persist=True,
        )

    # Active hop: reached the hop click tile.
    if _near_tile(blackboard, blackboard.search_waypoint):
        from app.bot_log import event

        event(
            "search",
            "hop arrive wp=%s",
            blackboard.search_waypoint,
        )
        goal = blackboard.search_leg_goal
        if goal is not None and _near_tile(blackboard, goal):
            _note_coverage(blackboard, goal)
            blackboard.search_destination = None
            blackboard.search_waypoint = None
            blackboard.search_leg_goal = None
            blackboard.search_hop_active = False
            blackboard.search_unstick_active = False
            blackboard.search_leg_ticks = 0
            return emit_search_hop(
                blackboard,
                reason=reason,
                priority=priority,
                max_leg_ticks=max_leg_ticks,
                state=state,
            )
        # Intermediate avoidance hop: keep coverage goal, plan the next click.
        blackboard.search_destination = None
        blackboard.search_waypoint = None
        blackboard.search_hop_active = False
        blackboard.search_unstick_active = False
        blackboard.search_leg_ticks = 0
        if goal is None:
            return emit_search_hop(
                blackboard,
                reason=reason,
                priority=priority,
                max_leg_ticks=max_leg_ticks,
                state=state,
            )
        if _emit_body_hop(
            blackboard,
            state=state,
            terrain=terrain,
            goal=goal,
            reason=reason,
            priority=priority,
        ):
            blackboard.last_search_tick = blackboard.tick_count
            return True
        return emit_search_hop(
            blackboard,
            reason=reason,
            priority=priority,
            max_leg_ticks=max_leg_ticks,
            state=state,
        )

    # Not arrived yet -> safety cap based on age.
    blackboard.search_leg_ticks += 1
    if blackboard.search_leg_ticks >= max_leg_ticks:
        from app.bot_log import event

        event("search", "hop replan (leg ticks=%s)", blackboard.search_leg_ticks)
        return _start_leg(
            blackboard,
            state=state,
            terrain=terrain,
            reason="stuck, jumping elsewhere",
            priority=priority,
            persist=False,
        )

    # Soft stuck → 360° nearby clicks, then teleport / talking scroll.
    if try_movement_unstick(
        blackboard,
        stuck=_is_stuck(blackboard),
        action=ActionType.SEARCHING,
        reason="unstick nearby",
        priority=priority,
        on_walk=lambda tile, dest: _emit_search_click(
            blackboard,
            destination=dest,
            waypoint=tile,
            reason="unstick nearby",
            priority=priority,
            mid_act=False,
        ),
    ):
        if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
            blackboard.search_hop_active = False
            blackboard.search_destination = None
            blackboard.search_waypoint = None
            blackboard.search_unstick_active = True
            blackboard.search_leg_ticks = 0
        else:
            blackboard.search_unstick_active = True
        blackboard.last_search_tick = blackboard.tick_count
        return True

    # Standing / blocked: re-click the same hop (~0.1s) like travel.
    wp = blackboard.search_waypoint
    if wp is not None:
        held_ticks = blackboard.search_leg_ticks
        if _follow_body_click(
            blackboard,
            state,
            terrain,
            wp,
            reason=reason,
            priority=priority,
        ):
            blackboard.search_leg_ticks = held_ticks
            blackboard.last_search_tick = blackboard.tick_count
            from app._04_decision.clickgap import note_hold

            if blackboard.intent is not None and blackboard.intent.mid_act:
                note_hold(
                    f"search:{wp}",
                    f"search wp={wp} leg={held_ticks}/{max_leg_ticks}",
                )
            return not bool(
                blackboard.intent is not None and blackboard.intent.mid_act
            )
        # Click line closed — replan avoidance toward the same coverage goal.
        goal = blackboard.search_leg_goal
        if goal is not None and _emit_body_hop(
            blackboard,
            state=state,
            terrain=terrain,
            goal=goal,
            reason=reason,
            priority=priority,
        ):
            blackboard.last_search_tick = blackboard.tick_count
            return True

    # Keep current destination, no click this tick.
    dest = blackboard.search_destination
    if dest is not None:
        blackboard.last_search_tick = blackboard.tick_count
        from app._04_decision.clickgap import note_hold

        note_hold(
            f"search:{blackboard.search_waypoint}",
            (
                f"search wp={blackboard.search_waypoint} "
                f"leg={blackboard.search_leg_ticks}/{max_leg_ticks}"
            ),
        )
        blackboard.emit(
            ActionType.SEARCHING,
            destination=dest,
            priority=priority,
            reason=reason,
            mid_act=True,
        )
        return False

    # Stale hop (travel cleared the click dest but left waypoint/active).
    clear_search_hop(blackboard)
    return emit_search_hop(
        blackboard,
        reason=reason,
        priority=priority,
        max_leg_ticks=max_leg_ticks,
        state=state,
    )


__all__ = [
    "clear_search_hop",
    "emit_search_hop",
    "suspend_search_click",
]

from app._04_decision.decide_spans import traced

emit_search_hop = traced(emit_search_hop)
