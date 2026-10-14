"""Avoidance hop on EdgeLayers (can_step). Imports interim_waypoint / region helpers only."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app._03_world.space.world_coords import (
    WorldOrigin,
    absolute_to_relative,
    in_battle_click_region,
    tile_chebyshev,
)
from app._04_decision.avoidance import AVOID_RADIUS, interim_waypoint
from app._04_decision.pathfinding import game_client_walk_tiles
from app._04_decision.player_mode import TRAVEL_MAX_HOP_TILES

from ti_edge_nav.graph import EdgePortalGraph, plan_path
from ti_edge_nav.layers import EdgeLayers

_NEIGHBORS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


@dataclass
class EdgeHopPlan:
    guide: list[tuple[int, int]] = field(default_factory=list)
    waypoint: tuple[int, int] | None = None
    click: tuple[int, int] | None = None
    polyline: list[tuple[int, int]] = field(default_factory=list)
    note: str = ""
    considered: set[tuple[int, int]] = field(default_factory=set)


def _polyline(start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    sx, sy = int(start[0]), int(start[1])
    dx = int(goal[0]) - sx
    dy = int(goal[1]) - sy
    return [(sx + rx, sy + ry) for rx, ry in game_client_walk_tiles(dx, dy)]


def _cell_blocked(
    layers: EdgeLayers,
    bodies: set[tuple[int, int]],
    x: int,
    y: int,
) -> bool:
    if (x, y) in bodies:
        return True
    return not layers.standable(x, y)


def edge_line_clear(
    layers: EdgeLayers,
    bodies: set[tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> bool:
    """Client polyline must pass can_step and miss living bodies."""
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])
    absolute = [(sx + rx, sy + ry) for rx, ry in game_client_walk_tiles(gx - sx, gy - sy)]
    if not absolute:
        return False
    prev = absolute[0]
    for tile in absolute[1:]:
        if _cell_blocked(layers, bodies, tile[0], tile[1]):
            return False
        if not layers.can_step(prev[0], prev[1], tile[0], tile[1]):
            return False
        prev = tile
    return True


def _in_click_region(origin: WorldOrigin, tile: tuple[int, int]) -> bool:
    rx, ry = absolute_to_relative(int(tile[0]), int(tile[1]), origin)
    return in_battle_click_region(rx, ry)


def _guide_to_waypoint(
    start: tuple[int, int],
    waypoint: tuple[int, int],
    guide: Optional[list[tuple[int, int]]],
) -> list[tuple[int, int]]:
    if guide:
        try:
            begin = guide.index(start)
            end = guide.index(waypoint)
        except ValueError:
            begin = end = -1
        if begin >= 0 and end > begin:
            return [(int(x), int(y)) for x, y in guide[begin : end + 1]]
    return _polyline(start, waypoint)


def _guide_through(
    guide: list[tuple[int, int]],
    start: tuple[int, int],
    waypoint: tuple[int, int],
) -> list[tuple[int, int]]:
    begin: int | None = None
    end: int | None = None
    for index, tile in enumerate(guide):
        if tile == start and begin is None:
            begin = index
        if tile == waypoint:
            end = index
    if begin is None or end is None or end <= begin:
        return []
    return guide[begin : end + 1]


def _bfs_edge(
    layers: EdgeLayers,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked,
) -> list[tuple[int, int]]:
    queue: deque[tuple[int, int]] = deque([start])
    parent: dict[tuple[int, int], Optional[tuple[int, int]]] = {start: None}
    gx, gy = goal
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        cx, cy = current
        neighbors: list[tuple[int, int]] = []
        for dx, dy in _NEIGHBORS:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in parent or blocked(nx, ny):
                continue
            if not layers.can_step(cx, cy, nx, ny):
                continue
            neighbors.append((nx, ny))
        neighbors.sort(key=lambda tile: max(abs(tile[0] - gx), abs(tile[1] - gy)))
        for tile in neighbors:
            parent[tile] = current
            queue.append(tile)
    if goal not in parent:
        return []
    path: list[tuple[int, int]] = []
    cursor: Optional[tuple[int, int]] = goal
    while cursor is not None:
        path.append(cursor)
        cursor = parent[cursor]
    path.reverse()
    return path


def _plan_avoidance_click(
    layers: EdgeLayers,
    origin: WorldOrigin,
    guide: Optional[list[tuple[int, int]]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    *,
    max_hop: int,
) -> Optional[tuple[int, int]]:
    start = (int(origin.x), int(origin.y))
    goal_tile = (int(waypoint[0]), int(waypoint[1]))
    if start == goal_tile:
        return None
    # Empty bodies: still require hop/region/can_step (waypoint may be > hop).
    if not bodies:
        if _click_allowed(layers, origin, start, goal_tile, bodies, max_hop):
            return goal_tile
        return None
    if edge_line_clear(layers, bodies, start, goal_tile) and _in_click_region(
        origin, goal_tile
    ) and tile_chebyshev(start[0], start[1], goal_tile[0], goal_tile[1]) <= int(max_hop):
        return goal_tile

    sx, sy = start

    def window_blocked(x: int, y: int) -> bool:
        if (x, y) == start:
            return False
        if max(abs(x - sx), abs(y - sy)) > AVOID_RADIUS:
            return True
        return _cell_blocked(layers, bodies, x, y)

    guide_tiles = _guide_to_waypoint(start, goal_tile, guide)
    local_goal: Optional[tuple[int, int]] = None
    for tile in reversed(guide_tiles):
        if tile == start:
            break
        if not window_blocked(tile[0], tile[1]):
            local_goal = tile
            break
    if local_goal is None:
        return None

    path = _bfs_edge(layers, start, local_goal, window_blocked)
    if not path:
        return None

    hop = max(1, int(max_hop))
    for tile in reversed(path[1:]):
        if tile_chebyshev(sx, sy, tile[0], tile[1]) > hop:
            continue
        if not _in_click_region(origin, tile):
            continue
        if edge_line_clear(layers, bodies, start, tile):
            return tile
    return None


def _click_allowed(
    layers: EdgeLayers,
    origin: WorldOrigin,
    start: tuple[int, int],
    click: tuple[int, int],
    bodies: set[tuple[int, int]],
    max_hop: int,
) -> bool:
    sx, sy = int(start[0]), int(start[1])
    cx, cy = int(click[0]), int(click[1])
    if tile_chebyshev(sx, sy, cx, cy) > int(max_hop):
        return False
    if not _in_click_region(origin, (cx, cy)):
        return False
    return edge_line_clear(layers, bodies, (sx, sy), (cx, cy))


def _farthest_guide_click(
    layers: EdgeLayers,
    origin: WorldOrigin,
    start: tuple[int, int],
    guide: list[tuple[int, int]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    max_hop: int,
) -> tuple[int, int] | None:
    """Last guide tile toward ``waypoint`` that still passes hop / region / can_step."""
    best: tuple[int, int] | None = None
    for tile in _guide_through(guide, start, waypoint)[1:]:
        if _click_allowed(layers, origin, start, tile, bodies, max_hop):
            best = (int(tile[0]), int(tile[1]))
    return best


def _choose_click(
    layers: EdgeLayers,
    origin: WorldOrigin,
    start: tuple[int, int],
    guide: list[tuple[int, int]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    max_hop: int,
) -> tuple[tuple[int, int] | None, str]:
    click = _plan_avoidance_click(
        layers, origin, guide, waypoint, bodies, max_hop=int(max_hop)
    )
    if click is not None and not _click_allowed(
        layers, origin, start, click, bodies, max_hop
    ):
        click = None
    if click is None:
        # Prefer the farthest legal hop on the guide — not the first neighbor.
        click = _farthest_guide_click(
            layers, origin, start, guide, waypoint, bodies, max_hop
        )
    if click is None:
        return None, "window has no safe click"
    click = (int(click[0]), int(click[1]))
    if click == waypoint:
        note = "line is clear, click is the guide waypoint"
    elif click in _guide_through(guide, start, waypoint):
        note = "line is clear, click is the hop toward the waypoint"
    else:
        note = "a body blocks the guide line, click steps aside"
    return click, note


def plan_edge_hop(
    layers: EdgeLayers,
    graph: EdgePortalGraph,
    start: tuple[int, int],
    goal: tuple[int, int],
    bodies: set[tuple[int, int]],
    *,
    max_hop: int | None = None,
) -> EdgeHopPlan:
    """Guide from edge pathfinder, then avoidance hop click."""
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])
    hop = int(TRAVEL_MAX_HOP_TILES if max_hop is None else max_hop)
    near = {
        (int(x), int(y))
        for x, y in bodies
        if max(abs(int(x) - sx), abs(int(y) - sy)) <= int(AVOID_RADIUS)
        and (int(x), int(y)) != (sx, sy)
    }
    if (sx, sy) == (gx, gy):
        return EdgeHopPlan(note="already on the goal", considered=near)
    guide = plan_path(layers, graph, (sx, sy), (gx, gy))
    if not guide:
        return EdgeHopPlan(note="no path to the goal", considered=near)
    waypoint = interim_waypoint((sx, sy), guide, near)
    if waypoint is None:
        return EdgeHopPlan(guide=guide, note="no click on the guide", considered=near)
    origin = WorldOrigin(x=sx, y=sy)
    click, note = _choose_click(layers, origin, (sx, sy), guide, waypoint, near, hop)
    if click is None:
        return EdgeHopPlan(
            guide=guide, waypoint=waypoint, note=note, considered=near
        )
    return EdgeHopPlan(
        guide=guide,
        waypoint=waypoint,
        click=click,
        polyline=_polyline((sx, sy), click),
        note=note,
        considered=near,
    )


def line_still_clear(
    layers: EdgeLayers,
    start: tuple[int, int],
    click: tuple[int, int],
    bodies: set[tuple[int, int]],
) -> bool:
    sx, sy = int(start[0]), int(start[1])
    near = {
        (int(x), int(y))
        for x, y in bodies
        if max(abs(int(x) - sx), abs(int(y) - sy)) <= int(AVOID_RADIUS)
    }
    return edge_line_clear(layers, near, (sx, sy), (int(click[0]), int(click[1])))
