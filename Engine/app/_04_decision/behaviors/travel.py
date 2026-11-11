"""Shared TRAVELING hop driver: A* clicks with memory-near-waypoint waits."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world import ActionType, Position
from app._03_world.space.world_coords import tile_chebyshev
from app._04_decision.behaviors.unstick import (
    SCRATCH_ESCAPED,
    reset_unstick_tries,
    try_enter_farm_detour,
    try_movement_unstick,
)
from app._04_decision.nav_config import get_terrain_map
from app._04_decision.pathfinding import waypoint_to_content
from app._04_decision import player_mode as pm

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard

# Walk that starts right after a talking-scroll landing. The hop uses the
# shorter tile path instead of the 32-tile cluster corridor.
SCRATCH_WORLD_NAV_SHORT_WALK = "world_nav_short_walk"


def clear_travel(blackboard: "Blackboard") -> None:
    blackboard.nav_goal = None
    blackboard.nav_path.clear()
    blackboard.nav_waypoint = None
    blackboard.travel_destination = None
    blackboard.travel_leg_ticks = 0
    blackboard.last_travel_tick = 0
    blackboard.travel_click_at = 0.0
    blackboard.travel_hop_active = False
    blackboard.travel_stuck_tile = None
    blackboard.travel_stuck_since_tick = 0
    blackboard.travel_stuck_since_time = 0.0
    blackboard.travel_unstick_active = False
    blackboard.travel_soft_unstick_done = False
    reset_unstick_tries(blackboard)
    from app._04_decision.patrol import clear_patrol_click_block

    clear_patrol_click_block(blackboard)


def start_travel(
    blackboard: "Blackboard",
    goal: tuple[int, int],
    *,
    reason: str,
) -> None:
    """Begin (or retarget) guided travel to an absolute tile."""
    blackboard.nav_goal = goal
    blackboard.nav_path.clear()
    blackboard.nav_waypoint = None
    blackboard.travel_destination = None
    blackboard.travel_leg_ticks = 0
    blackboard.last_travel_tick = 0
    from app._04_decision.behaviors.search_hop import clear_search_hop

    clear_search_hop(blackboard)
    blackboard.travel_hop_active = False
    blackboard.travel_click_at = 0.0
    blackboard.travel_stuck_tile = None
    blackboard.travel_stuck_since_tick = 0
    blackboard.travel_stuck_since_time = 0.0
    blackboard.travel_unstick_active = False
    blackboard.travel_soft_unstick_done = False
    reset_unstick_tries(blackboard)
    blackboard.scratch["travel_reason"] = reason
    from app._04_decision.patrol import clear_patrol_click_block

    clear_patrol_click_block(blackboard)


def travel_arrived(blackboard: "Blackboard") -> bool:
    goal = blackboard.nav_goal
    if goal is None:
        return True
    from app._04_decision.dungeon import travel_arrive_tiles

    return (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            goal[0],
            goal[1],
        )
        <= travel_arrive_tiles()
    )


def _near_tile(blackboard: "Blackboard", tile: tuple[int, int]) -> bool:
    """Hop complete on the same tile, or one tile away across an open step.

    Chebyshev 1 counts only when ``can_step`` can cross that edge. Standing
    against a fence is not an arrival. A missing terrain map keeps the
    distance check. The final goal still uses ``travel_arrived``.
    """
    from app._04_decision.dungeon import travel_arrive_tiles

    ox = int(blackboard.world_origin.x)
    oy = int(blackboard.world_origin.y)
    dist = tile_chebyshev(ox, oy, int(tile[0]), int(tile[1]))
    if dist > travel_arrive_tiles():
        return False
    if dist != 1:
        return True
    terrain = get_terrain_map()
    if terrain is None:
        return True
    return bool(terrain.can_step(ox, oy, int(tile[0]), int(tile[1])))


def _route_anchor(tiles: list[tuple[int, int]], px: int, py: int) -> int:
    """Guide index of the live tile, or the nearest guide tile."""
    here = (int(px), int(py))
    for index, tile in enumerate(tiles):
        if tile == here:
            return index
    best_i = 0
    best_d = 10**9
    for index, (x, y) in enumerate(tiles):
        dist = max(abs(x - px), abs(y - py))
        if dist < best_d:
            best_d = dist
            best_i = index
    return best_i


def _route_cell_clickable(
    terrain: object,
    origin: object,
    start: tuple[int, int],
    tile: tuple[int, int],
    bodies: set[tuple[int, int]],
    hop: int,
) -> bool:
    """True when a click from the live tile walks this route cell."""
    from app._03_world.space.world_coords import absolute_to_relative, in_battle_click_region
    from app._04_decision.avoidance import click_clear

    if tile_chebyshev(start[0], start[1], tile[0], tile[1]) > int(hop):
        return False
    if not terrain.is_walkable(tile[0], tile[1]):
        return False
    rx, ry = absolute_to_relative(tile[0], tile[1], origin)
    if not in_battle_click_region(rx, ry):
        return False
    return click_clear(terrain, bodies, start, tile)


def _next_route_click(
    terrain: object,
    origin: object,
    guide: list[tuple[int, int]],
    goal: tuple[int, int] | None,
    bodies: set[tuple[int, int]],
    *,
    max_hop: int,
) -> tuple[int, int] | None:
    """Farthest route cell the live tile can click without leaving the path.

    The scan stops at the first cell whose client walk hits a wall, a fence,
    or a body, and keeps the last cell that was still clear. A closed door is
    the click. An open door's click is the tile just past the doorway. Cells
    past the goal are left out.
    """
    from app._04_decision.doors import door_state_at

    if not guide:
        return None
    tiles = [(int(x), int(y)) for x, y in guide]
    px, py = int(origin.x), int(origin.y)
    start = (px, py)
    anchor = _route_anchor(tiles, px, py)
    goal_at: int | None = None
    if goal is not None:
        goal_tile = (int(goal[0]), int(goal[1]))
        for index, tile in enumerate(tiles):
            if tile == goal_tile and index >= anchor:
                goal_at = index
                break
    hop = int(max_hop)
    best: tuple[int, int] | None = None
    index = anchor + 1
    while index < len(tiles):
        if goal_at is not None and index > goal_at:
            break
        tile = tiles[index]
        state = door_state_at(tile[0], tile[1])
        if state == "close":
            if _route_cell_clickable(terrain, origin, start, tile, bodies, hop):
                best = tile
            break
        if state == "open":
            beyond: tuple[int, int] | None = None
            for follow in tiles[index + 1 :]:
                if door_state_at(follow[0], follow[1]) == "open":
                    continue
                beyond = follow
                break
            if beyond is not None and _route_cell_clickable(
                terrain, origin, start, beyond, bodies, hop + 1
            ):
                best = beyond
            break
        if not _route_cell_clickable(terrain, origin, start, tile, bodies, hop):
            break
        best = tile
        if goal_at is not None and index == goal_at:
            break
        index += 1
    if best == start:
        return None
    return best


def _client_line_continues(
    start: tuple[int, int],
    waypoint: tuple[int, int],
    farther: tuple[int, int],
) -> bool:
    """True when the client walk P→C passes through W and does not turn there.

    ``game_client_walk_tiles`` is diagonal first, then the leftover axis.
    The step into W and the step out of W must be the same vector.
    Dungeon and field both use this for the two-tile straight extend.
    """
    from app._04_decision.pathfinding import game_client_walk_tiles

    sx, sy = int(start[0]), int(start[1])
    wx, wy = int(waypoint[0]), int(waypoint[1])
    cx, cy = int(farther[0]), int(farther[1])
    absolute = [
        (sx + rx, sy + ry)
        for rx, ry in game_client_walk_tiles(cx - sx, cy - sy)
    ]
    try:
        index = absolute.index((wx, wy))
    except ValueError:
        return False
    if index <= 0 or index >= len(absolute) - 1:
        return False
    into = (wx - absolute[index - 1][0], wy - absolute[index - 1][1])
    out = (absolute[index + 1][0] - wx, absolute[index + 1][1] - wy)
    return into == out


def _straight_extend_waypoint(
    blackboard: "Blackboard",
    terrain: object,
    bodies: set[tuple[int, int]],
) -> tuple[int, int] | None:
    """Farthest guide tile past the current click that stays on the same line.

    Dungeon and field. The hop cap, click region, and arrival radius are
    unchanged. An open door or the final goal ends the scan.
    """
    from app._03_world.space.world_coords import absolute_to_relative, in_battle_click_region
    from app._04_decision.avoidance import click_clear, travel_max_hop
    from app._04_decision.doors import door_state_at
    from app._04_decision.pathfinding import is_game_walk_clear

    waypoint = blackboard.nav_waypoint
    if waypoint is None:
        return None
    origin = blackboard.world_origin
    start = (int(origin.x), int(origin.y))
    current = (int(waypoint[0]), int(waypoint[1]))
    guide = [(int(x), int(y)) for x, y in blackboard.nav_path]
    try:
        start_at = guide.index(current)
    except ValueError:
        return None
    goal = blackboard.nav_goal
    goal_at: int | None = None
    if goal is not None:
        goal_tile = (int(goal[0]), int(goal[1]))
        for index, tile in enumerate(guide):
            if tile == goal_tile:
                goal_at = index
                break
    hop = int(travel_max_hop())
    best: tuple[int, int] | None = None
    for index in range(start_at + 1, len(guide)):
        if goal_at is not None and index > goal_at:
            break
        tile = guide[index]
        if door_state_at(tile[0], tile[1]) == "open":
            break
        if tile_chebyshev(start[0], start[1], tile[0], tile[1]) > hop:
            break
        rx, ry = absolute_to_relative(tile[0], tile[1], origin)
        if not in_battle_click_region(rx, ry):
            break
        if not _client_line_continues(start, current, tile):
            break
        if not is_game_walk_clear(terrain, start, tile):
            break
        if not click_clear(terrain, bodies, start, tile):
            break
        best = tile
        if goal_at is not None and index == goal_at:
            break
    if best == current:
        return None
    return best


def _reset_stuck(blackboard: "Blackboard") -> None:
    blackboard.travel_stuck_tile = (
        blackboard.world_origin.x,
        blackboard.world_origin.y,
    )
    blackboard.travel_stuck_since_tick = blackboard.tick_count
    blackboard.travel_stuck_since_time = time.time()
    blackboard.travel_soft_unstick_done = False


def _stuck_sample(blackboard: "Blackboard") -> tuple[int, float]:
    """Ticks and seconds on the current tile. Resets the clock on a tile change."""
    cur = (blackboard.world_origin.x, blackboard.world_origin.y)
    if blackboard.travel_stuck_tile is not None and blackboard.travel_stuck_tile != cur:
        reset_unstick_tries(blackboard)
    if blackboard.travel_stuck_tile != cur:
        _reset_stuck(blackboard)
        return 0, 0.0
    ticks = blackboard.tick_count - blackboard.travel_stuck_since_tick
    elapsed = time.time() - blackboard.travel_stuck_since_time
    return ticks, elapsed


def _should_reclick(blackboard: "Blackboard") -> bool:
    last = float(blackboard.travel_click_at or 0.0)
    if last <= 0.0:
        return True
    return (time.time() - last) >= pm.TRAVEL_RECLICK_SECONDS


def _mark_travel_unstick(blackboard: "Blackboard") -> None:
    """Keep travel session; drop the blocked hop so the next tick can replan."""
    from app.bot_log import event

    event(
        "travel",
        "unstick purpose=%s wp=%s",
        blackboard.travel_purpose,
        blackboard.nav_waypoint,
    )
    blackboard.travel_hop_active = False
    blackboard.travel_destination = None
    blackboard.nav_waypoint = None
    blackboard.travel_unstick_active = True
    blackboard.nav_path.clear()
    blackboard.last_travel_tick = blackboard.tick_count


_SCRATCH_HOP_LIFE = "hop_click_life"


def _client_cells(
    px: int, py: int, gx: int, gy: int
) -> list[tuple[int, int]]:
    from app._04_decision.pathfinding import game_client_walk_tiles

    return [
        (px + dx, py + dy)
        for dx, dy in game_client_walk_tiles(gx - px, gy - py)
    ]


def _cells_text(cells: list[tuple[int, int]] | None) -> str:
    if not cells:
        return "-"
    return ">".join(f"{x},{y}" for x, y in cells)


def _path_is_prefix(
    short: list[tuple[int, int]], long: list[tuple[int, int]]
) -> int:
    if not short:
        return 0
    return int(len(short) <= len(long) and long[: len(short)] == short)


def _moving_bit() -> int:
    from app._05_action.body_pose import body_is_moving

    moving = body_is_moving()
    if moving is True:
        return 1
    if moving is False:
        return 0
    return -1


def _log_hop_click(
    blackboard: "Blackboard",
    new_click: tuple[int, int],
) -> None:
    """Record P, the click being replaced, and the click sent now.

    A later line says whether the body stopped in the 0.3–0.7s after this
    click. The click itself is unchanged.
    """
    from app.bot_log import event

    moving = _moving_bit()
    click_time = time.time()
    previous = blackboard.scratch.get(_SCRATCH_HOP_LIFE)
    if isinstance(previous, dict) and not previous.get("reported"):
        elapsed = click_time - float(previous["click_time"])
        if moving == 0 and float(previous["stopped_at"]) < 0.0:
            previous["stopped"] = 1
            previous["stopped_at"] = elapsed
        previous["reported"] = True
        event(
            "travel",
            "hop lifecycle prefix=%s stopped=%s stopped_at=%.3f elapsed=%.3f "
            "player=%s active=%s next=%s",
            int(previous["prefix"]),
            int(previous["stopped"]),
            float(previous["stopped_at"]),
            elapsed,
            previous["player"],
            previous["active"] if previous["active"] is not None else "-",
            previous["next"],
        )
    origin = blackboard.world_origin
    player = (int(origin.x), int(origin.y))
    active = blackboard.nav_waypoint
    nxt = (int(new_click[0]), int(new_click[1]))
    if active is None:
        active_cell = None
        dist = -1
        path_w: list[tuple[int, int]] = []
    else:
        active_cell = (int(active[0]), int(active[1]))
        dist = tile_chebyshev(player[0], player[1], active_cell[0], active_cell[1])
        path_w = _client_cells(player[0], player[1], active_cell[0], active_cell[1])
    path_c = _client_cells(player[0], player[1], nxt[0], nxt[1])
    prefix = _path_is_prefix(path_w, path_c)
    event(
        "travel",
        "hop click player=%s active=%s next=%s dist=%s prefix=%s moving=%s "
        "click_time=%.3f path_w=%s path_c=%s",
        player,
        active_cell if active_cell is not None else "-",
        nxt,
        dist,
        prefix,
        moving,
        click_time,
        _cells_text(path_w),
        _cells_text(path_c),
    )
    blackboard.scratch[_SCRATCH_HOP_LIFE] = {
        "click_time": click_time,
        "prefix": prefix,
        "player": player,
        "active": active_cell,
        "next": nxt,
        "stopped": 0,
        "stopped_at": -1.0,
        "reported": False,
    }


def _watch_hop_motion(blackboard: "Blackboard", moving: bool | None) -> None:
    """One line if the body stops within 0.7s after the logged click."""
    life = blackboard.scratch.get(_SCRATCH_HOP_LIFE)
    if not isinstance(life, dict) or life.get("reported"):
        return
    elapsed = time.time() - float(life["click_time"])
    if moving is False and elapsed <= 0.7:
        life["stopped"] = 1
        if float(life["stopped_at"]) < 0.0:
            life["stopped_at"] = elapsed
    if elapsed < 0.7:
        return
    from app.bot_log import event

    life["reported"] = True
    event(
        "travel",
        "hop lifecycle prefix=%s stopped=%s stopped_at=%.3f elapsed=%.3f "
        "player=%s active=%s next=%s",
        int(life["prefix"]),
        int(life["stopped"]),
        float(life["stopped_at"]),
        elapsed,
        life["player"],
        life["active"] if life["active"] is not None else "-",
        life["next"],
    )


def _emit_click(
    blackboard: "Blackboard",
    *,
    content: Position,
    waypoint: tuple[int, int],
    reason: str,
    priority: float,
    mid_act: bool,
) -> None:
    from app.bot_log import event

    if not mid_act:
        _log_hop_click(blackboard, (int(waypoint[0]), int(waypoint[1])))
    blackboard.nav_waypoint = waypoint
    blackboard.travel_destination = content
    blackboard.last_travel_tick = blackboard.tick_count
    blackboard.travel_hop_active = True
    if not mid_act:
        blackboard.travel_click_at = time.time()
        from app._04_decision.clickgap import note_plan

        note_plan(f"travel wp={waypoint} reason={reason}")
        event(
            "travel",
            "hop begin wp=%s purpose=%s reason=%s",
            waypoint,
            blackboard.travel_purpose,
            reason,
        )
    blackboard.emit(
        ActionType.TRAVELING,
        destination=content,
        priority=priority,
        reason=reason,
        mid_act=mid_act,
    )


def _follow_body_click(
    blackboard: "Blackboard",
    state: object | None,
    terrain: object,
    waypoint: tuple[int, int],
    *,
    reason: str,
    priority: float,
) -> bool:
    """Hold or repeat the current click. False asks the caller to replan.

    A walking body is left alone. A body that is not walking gets the same
    absolute tile again every 0.1s. Hold and repeat both rebuild the screen
    point from the absolute tile and the current origin. A blocked click
    line returns False so the next interim waypoint can be chosen. Walls are
    checked even when ``state`` is missing; living bodies need ``state``.
    """
    from app._04_decision.avoidance import (
        classify_ground_reclick,
        click_bodies,
        click_clear,
    )
    from app._05_action.body_pose import body_is_moving

    origin = blackboard.world_origin
    start = (int(origin.x), int(origin.y))
    moving = body_is_moving()
    _watch_hop_motion(blackboard, moving)
    if moving is not True:
        bodies = click_bodies(state, origin, blackboard)
        if not click_clear(terrain, bodies, start, waypoint):
            from app.bot_log import event

            event(
                "avoid",
                "line closed kind=travel wp=%s bodies=%d from=%s",
                waypoint,
                len(bodies),
                start,
            )
            from app._04_decision.behaviors.unstick import note_confined_line_closed

            note_confined_line_closed(blackboard)
            blackboard.travel_hop_active = False
            blackboard.travel_destination = None
            blackboard.nav_waypoint = None
            blackboard.travel_unstick_active = False
            return False
    now = time.time()
    follow = classify_ground_reclick(
        moving,
        float(blackboard.travel_click_at or 0.0),
        now=now,
    )
    if follow == "repeat":
        from app._04_decision.avoidance import log_ground_pause

        log_ground_pause(
            "travel",
            waypoint,
            moving,
            float(blackboard.travel_click_at or 0.0),
            now,
            reason,
        )
    # Hold and repeat both aim at the absolute tile under the current origin.
    # A screen point baked on an older origin lands past a wall once the
    # player tile changes. The action layer aims again at the click itself.
    content = waypoint_to_content(waypoint, origin)
    _emit_click(
        blackboard,
        content=content,
        waypoint=waypoint,
        reason=reason,
        priority=priority,
        mid_act=follow != "repeat",
    )
    return True


def emit_gate_sidestep(
    blackboard: "Blackboard",
    state: object | None,
    *,
    player_abs: tuple[int, int],
    entrance_abs: tuple[int, int],
    reason: str,
    priority: float = 0.6,
) -> bool:
    """One existing body-avoid click, one tile off a blocked gate.

    The goal is two tiles away from the door so the hop is not already
    arrived. ``plan_body_click`` still steps aside when a body blocks
    that line. Returns False when no walkable step exists.
    """
    from app._04_decision.avoidance import click_bodies, plan_body_click

    terrain = get_terrain_map()
    if terrain is None:
        return False
    origin = blackboard.world_origin
    ox, oy = int(origin.x), int(origin.y)
    px, py = int(player_abs[0]), int(player_abs[1])
    fx, fy = int(entrance_abs[0]), int(entrance_abs[1])
    sx = 0 if px == fx else (1 if px > fx else -1)
    sy = 0 if py == fy else (1 if py > fy else -1)
    if sx == 0 and sy == 0:
        sx = 1
    bodies = click_bodies(state, origin, blackboard)
    for csx, csy in ((sx, sy), (-sy, sx), (sy, -sx), (-sx, -sy)):
        raw = (ox + 2 * int(csx), oy + 2 * int(csy))
        goal = _snap_aside(terrain, raw, avoid=(ox, oy))
        if goal is None:
            continue
        planned = plan_body_click(
            terrain,
            origin,
            goal,
            bodies,
            max_hop=1,
            force_flat=True,
        )
        click = planned.click
        if click is None or (int(click[0]), int(click[1])) == (ox, oy):
            continue
        content = waypoint_to_content((int(click[0]), int(click[1])), origin)
        _emit_click(
            blackboard,
            content=content,
            waypoint=(int(click[0]), int(click[1])),
            reason=reason,
            priority=priority,
            mid_act=False,
        )
        return True
    return False


def _snap_aside(
    terrain: object,
    raw: tuple[int, int],
    *,
    avoid: tuple[int, int],
) -> tuple[int, int] | None:
    """Walkable tile at ``raw`` or a neighbor, never the tile we are leaving."""
    ax, ay = int(avoid[0]), int(avoid[1])
    x, y = int(raw[0]), int(raw[1])
    if terrain.is_walkable(x, y) and (x, y) != (ax, ay):
        return (x, y)
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if (nx, ny) != (ax, ay) and terrain.is_walkable(nx, ny):
                return (nx, ny)
    return None


def emit_travel_hop(
    blackboard: "Blackboard",
    *,
    reason: str,
    priority: float,
    state: object | None = None,
) -> bool:
    """Emit TRAVELING for one hop. Returns False if arrived or unreachable.

    Re-clicks about every ``TRAVEL_RECLICK_SECONDS`` from live memory
    position. Same tile ~2.5s → 360° walkable clicks; all radius-2
    tiles failing, or low HP → teleport or talking
    scroll. Enter / next-farm with no A* path walks a 5-tile ring first.
    """
    if blackboard.nav_goal is None:
        blackboard.scratch["travel_hop_miss"] = "no_nav_goal"
        return False
    if travel_arrived(blackboard):
        blackboard.scratch["travel_hop_miss"] = "already_arrived"
        return False

    # Interrupted by another behavior: replan from live memory position.
    if (
        blackboard.last_travel_tick > 0
        and blackboard.tick_count - blackboard.last_travel_tick > 1
    ):
        blackboard.travel_hop_active = False
        blackboard.travel_destination = None
        blackboard.nav_waypoint = None
        blackboard.travel_unstick_active = False

    terrain = get_terrain_map()
    if terrain is None:
        clear_travel(blackboard)
        blackboard.scratch["travel_hop_miss"] = "no_terrain"
        return False

    def _walk_unstick(tile: tuple[int, int], dest: Position) -> None:
        blackboard.travel_unstick_active = True
        blackboard.nav_path.clear()
        _emit_click(
            blackboard,
            content=dest,
            waypoint=tile,
            reason="unstick nearby",
            priority=priority,
            mid_act=False,
        )

    def _consume_unstick() -> bool:
        if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
            _mark_travel_unstick(blackboard)
        return True

    def _fail_hop(miss: str) -> bool:
        from app._04_decision.mode_control import PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM

        entering = blackboard.travel_purpose in (
            PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM,
        )
        if entering:
            _stuck_sample(blackboard)

            def _detour_walk(tile: tuple[int, int], dest: Position) -> None:
                blackboard.travel_unstick_active = True
                blackboard.nav_path.clear()
                _emit_click(
                    blackboard,
                    content=dest,
                    waypoint=tile,
                    reason="enter farm, walk around",
                    priority=priority,
                    mid_act=False,
                )

            if try_enter_farm_detour(blackboard, on_walk=_detour_walk):
                return _consume_unstick()
            blackboard.scratch["travel_hop_miss"] = (
                "no_path_enter_farm" if miss == "no_path" else miss
            )
            return False
        _ticks, elapsed = _stuck_sample(blackboard)
        if try_movement_unstick(
            blackboard,
            stuck=elapsed >= pm.TRAVEL_UNSTICK_SECONDS,
            action=ActionType.TRAVELING,
            reason="unstick nearby",
            priority=priority,
            on_walk=_walk_unstick,
        ):
            return _consume_unstick()
        blackboard.scratch["travel_hop_miss"] = miss
        return False

    # Active hop. Within one tile the click is dropped and the next click
    # is planned on this tick. Two tiles out, while walking, a farther tile
    # is used only on the same straight line. Dungeon matches 2026-10-19.
    if blackboard.travel_hop_active and blackboard.nav_waypoint is not None:
        wp = (int(blackboard.nav_waypoint[0]), int(blackboard.nav_waypoint[1]))
        from app._04_decision.mode_control import PURPOSE_ENTER_FARM

        if _near_tile(blackboard, wp):
            from app.bot_log import event

            event(
                "travel",
                "hop arrive wp=%s purpose=%s",
                wp,
                blackboard.travel_purpose,
            )
            blackboard.travel_hop_active = False
            blackboard.travel_destination = None
            blackboard.nav_waypoint = None
            blackboard.travel_unstick_active = False
            if travel_arrived(blackboard):
                blackboard.scratch["travel_hop_miss"] = "hop_arrive_final"
                return False
            # Fall through and plan the next hop this tick.
        else:
            from app._05_action.body_pose import body_is_moving

            if (
                body_is_moving() is True
                and not blackboard.travel_unstick_active
                and tile_chebyshev(
                    int(blackboard.world_origin.x),
                    int(blackboard.world_origin.y),
                    wp[0],
                    wp[1],
                )
                == 2
            ):
                from app._04_decision.avoidance import click_bodies

                bodies = click_bodies(state, blackboard.world_origin, blackboard)
                extended = _straight_extend_waypoint(blackboard, terrain, bodies)
                if extended is not None:
                    from app.bot_log import event

                    event(
                        "travel",
                        "hop extend wp=%s -> %s purpose=%s",
                        wp,
                        extended,
                        blackboard.travel_purpose,
                    )
                    _emit_click(
                        blackboard,
                        content=waypoint_to_content(
                            extended, blackboard.world_origin
                        ),
                        waypoint=extended,
                        reason=reason,
                        priority=priority,
                        mid_act=False,
                    )
                    return True

        if not _near_tile(blackboard, wp):
            _ticks, elapsed = _stuck_sample(blackboard)
            if try_movement_unstick(
                blackboard,
                stuck=elapsed >= pm.TRAVEL_UNSTICK_SECONDS,
                action=ActionType.TRAVELING,
                reason="unstick nearby",
                priority=priority,
                on_walk=_walk_unstick,
                allow_escape=blackboard.travel_purpose != PURPOSE_ENTER_FARM,
            ):
                return _consume_unstick()
            if _follow_body_click(
                blackboard,
                state,
                terrain,
                wp,
                reason=reason,
                priority=priority,
            ):
                return True
            # The click line closed. Fall through and pick the next one.

    # Field and dungeon: same avoidance hop (guide → interim → click).
    from app._04_decision.avoidance import click_bodies, plan_body_click
    from app._04_decision.clickgap import note_hold
    from app._04_decision.patrol import PURPOSE_PATROL, clear_patrol_click_block

    origin = blackboard.world_origin
    bodies = click_bodies(state, origin, blackboard)
    short_walk = (
        blackboard.travel_purpose == "world_nav"
        and bool(blackboard.scratch.get(SCRATCH_WORLD_NAV_SHORT_WALK))
    )
    planned = plan_body_click(
        terrain,
        origin,
        (int(blackboard.nav_goal[0]), int(blackboard.nav_goal[1])),
        bodies,
        force_flat=short_walk,
    )
    from app._04_decision.behaviors.unstick import note_confined_planned_avoid

    note_confined_planned_avoid(blackboard, planned, bodies)
    if not planned.guide or planned.click is None:
        if planned.note == "no path to the goal" or not planned.guide:
            clear_patrol_click_block(blackboard)
            return _fail_hop("no_path")
        blocked_for = 0.0
        if blackboard.travel_purpose == PURPOSE_PATROL:
            from app._04_decision.patrol import (
                PATROL_NO_CLICK_SKIP_S,
                patrol_click_blocked_for,
                skip_blocked_patrol_point,
            )

            blocked_for = patrol_click_blocked_for(
                blackboard,
                (int(blackboard.nav_goal[0]), int(blackboard.nav_goal[1])),
                now=time.time(),
            )
            if blocked_for >= float(PATROL_NO_CLICK_SKIP_S):
                if skip_blocked_patrol_point(blackboard):
                    return True
        elif planned.note == "window has no safe click":
            # No forward tile. The same 5s unstick used by a stuck hop
            # takes over; patrol still waits for its own skip above.
            _ticks, elapsed = _stuck_sample(blackboard)
            if try_movement_unstick(
                blackboard,
                stuck=elapsed >= pm.TRAVEL_UNSTICK_SECONDS,
                action=ActionType.TRAVELING,
                reason="unstick nearby",
                priority=priority,
                on_walk=_walk_unstick,
            ):
                return _consume_unstick()
        note_hold(
            f"travel:{planned.note}",
            (
                f"travel no click note={planned.note} "
                f"wp={planned.waypoint} blocked_for={blocked_for:.1f}s"
            ),
        )
        blackboard.nav_path = list(planned.guide)
        blackboard.travel_hop_active = False
        blackboard.nav_waypoint = None
        blackboard.travel_destination = None
        blackboard.emit(
            ActionType.IDLE,
            priority=priority,
            reason=planned.note,
        )
        return True
    blackboard.scratch.pop("travel_hop_miss", None)
    blackboard.nav_path = list(planned.guide)
    clear_patrol_click_block(blackboard)
    _emit_click(
        blackboard,
        content=waypoint_to_content(planned.click, origin),
        waypoint=planned.click,
        reason=reason,
        priority=priority,
        mid_act=False,
    )
    return True


__all__ = [
    "clear_travel",
    "start_travel",
    "travel_arrived",
    "emit_travel_hop",
]

from app._04_decision.decide_spans import traced

emit_travel_hop = traced(emit_travel_hop)
