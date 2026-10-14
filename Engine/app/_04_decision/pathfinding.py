"""Absolute-world A* pathfinding and safe battle-click waypoint selection.

Click validity uses the client walk polyline (not A* slack):

    abs(dx) > abs(dy):  (0,0) -> (z, dy) -> (dx, dy)
        z = sgn(dx) * abs(dy)
    abs(dx) < abs(dy):  (0,0) -> (dx, z) -> (dx, dy)
        z = sgn(dy) * abs(dx)
    abs(dx) == abs(dy): (0,0) -> (dx, dy)  (pure diagonal)

    valid iff every tile after the start on that polyline is walkable.

Waypoint pick: walk A* path near→far; accept tiles in the relative click
    parallelogram that pass validity; stop at first failure; click last accepted.
"""
from __future__ import annotations

import heapq
from typing import TYPE_CHECKING, Optional, Sequence

from app._02_state.objects import Position
from app._03_world.space.terrain_map import TerrainMap
from app._03_world.space.world_coords import (
    CLICK_PATH_SLACK,
    WorldOrigin,
    absolute_to_relative,
    in_battle_click_region,
    tile_chebyshev,
    world_to_content,
)

if TYPE_CHECKING:
    import numpy as np


_NEIGHBOR_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)


def _sign(delta: int) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def _goal_aligned_neighbors(
    terrain: TerrainMap,
    cx: int,
    cy: int,
    gx: int,
    gy: int,
) -> list[tuple[int, int]]:
    """Walkable 8-neighbors, greedy Chebyshev step first (no fixed direction bias)."""
    sdx = _sign(gx - cx)
    sdy = _sign(gy - cy)
    ranked: list[tuple[tuple[int, int, int], tuple[int, int]]] = []
    for dx, dy in _NEIGHBOR_OFFSETS:
        nx, ny = cx + dx, cy + dy
        if not terrain.can_step(cx, cy, nx, ny):
            continue
        # 0 = exact greedy step; then fewer axes fighting the goal.
        mismatch = int(dx != sdx) + int(dy != sdy)
        ranked.append(((mismatch, tile_chebyshev(nx, ny, gx, gy), dx * dx + dy * dy), (nx, ny)))
    ranked.sort(key=lambda item: item[0])
    return [n for _, n in ranked]


def _closer_to_line(
    candidate: tuple[int, int],
    incumbent: tuple[int, int],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> bool:
    """True when ``candidate`` lies closer to the start→goal line than ``incumbent``."""
    sx, sy = start
    gx, gy = goal
    vx, vy = gx - sx, gy - sy
    denom = vx * vx + vy * vy
    if denom == 0:
        return False

    def dist_sq(p: tuple[int, int]) -> int:
        px, py = p[0] - sx, p[1] - sy
        cross = vx * py - vy * px
        return cross * cross

    return dist_sq(candidate) < dist_sq(incumbent)


def find_path(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    allowed: Optional["np.ndarray"] = None,
) -> list[tuple[int, int]]:
    """8-connected A* on ``terrain``. Returns path including start and goal.

    Records one row for the debug A* tab when the search loop actually runs.
    """
    import time

    from app._04_decision.astar_trace import labels_from_stack, record_search

    t0 = time.perf_counter()
    path: list[tuple[int, int]] = []
    expanded = 0
    entered = False
    try:
        path, expanded, entered = _find_path_search(
            terrain, start, goal, allowed=allowed
        )
        return path
    finally:
        if entered:
            cause, search = labels_from_stack()
            record_search(
                cause=cause,
                search=search,
                ms=(time.perf_counter() - t0) * 1000.0,
                start=(int(start[0]), int(start[1])),
                goal=(int(goal[0]), int(goal[1])),
                steps=max(0, len(path) - 1),
                expanded=expanded,
            )


def _find_path_search(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    allowed: Optional["np.ndarray"] = None,
) -> tuple[list[tuple[int, int]], int, bool]:
    """Run A*. Returns ``(path, tiles expanded, entered the search loop)``.

    Step cost is ``terrain.tile_cost`` (1 in open ground, higher next to walls).
    Heuristic is plain Chebyshev (admissible: min step cost is 1). Among
    equal-g paths, expansion prefers the greedy step toward the goal so the
    route does not inherit a fixed 8-direction priority from neighbor order.

    When ``allowed`` is set (bool array same shape as walkable), only those
    tiles may be expanded (plus start/goal must still be walkable).
    """
    sx, sy = start
    gx, gy = goal
    if not terrain.is_walkable(sx, sy) or not terrain.is_walkable(gx, gy):
        return [], 0, False
    if start == goal:
        return [start], 0, False

    def ok(x: int, y: int) -> bool:
        if not terrain.is_walkable(x, y):
            return False
        if allowed is None:
            return True
        return bool(allowed[y, x])

    if not ok(sx, sy) or not ok(gx, gy):
        return [], 0, False

    def h(x: int, y: int) -> int:
        return tile_chebyshev(x, y, gx, gy)

    def tie(x: int, y: int) -> int:
        # Euclidean² toward the goal; only used when Chebyshev f is tied.
        dx, dy = x - gx, y - gy
        return dx * dx + dy * dy

    def neighbors(cx: int, cy: int) -> list[tuple[int, int]]:
        raw = _goal_aligned_neighbors(terrain, cx, cy, gx, gy)
        if allowed is None:
            return raw
        return [(nx, ny) for nx, ny in raw if ok(nx, ny)]

    open_heap: list[tuple[int, int, int, tuple[int, int]]] = []
    counter = 0
    heapq.heappush(open_heap, (h(sx, sy), tie(sx, sy), counter, start))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            return _reconstruct(came_from, current), len(closed), True
        closed.add(current)
        cx, cy = current
        for nx, ny in neighbors(cx, cy):
            neighbor = (nx, ny)
            if neighbor in closed:
                continue
            tentative = g_score[current] + terrain.tile_cost(nx, ny)
            prev = g_score.get(neighbor)
            if prev is not None and tentative > prev:
                continue
            if prev is not None and tentative == prev:
                # Same length: keep the parent closer to the start–goal line.
                if not _closer_to_line(current, came_from[neighbor], start, goal):
                    continue
            came_from[neighbor] = current
            g_score[neighbor] = tentative
            counter += 1
            f = tentative + h(nx, ny)
            heapq.heappush(open_heap, (f, tie(nx, ny), counter, neighbor))
    return [], len(closed), True


def _reconstruct(
    came_from: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path


def game_client_walk_tiles(dx: int, dy: int) -> list[tuple[int, int]]:
    """Relative tiles on the Lineage client ground-click walk polyline.

    Inclusive from ``(0, 0)`` to ``(dx, dy)``. Diagonal first, in tile
    coordinates, then the leftover axis leg. Matches in-game movement, not A*.
    """
    if dx == 0 and dy == 0:
        return [(0, 0)]
    adx, ady = abs(dx), abs(dy)
    sx, sy = _sign(dx), _sign(dy)
    tiles: list[tuple[int, int]] = [(0, 0)]
    x = y = 0
    for _ in range(min(adx, ady)):
        x += sx
        y += sy
        tiles.append((x, y))
    if adx > ady:
        for _ in range(adx - ady):
            x += sx
            tiles.append((x, y))
    elif ady > adx:
        for _ in range(ady - adx):
            y += sy
            tiles.append((x, y))
    return tiles


def is_game_walk_clear(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> bool:
    """True when the client walk polyline start→goal can step each segment.

    Walkable cells alone are not enough: field packs also require
    ``terrain.can_step`` across N/E fences between consecutive tiles.
    """
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])
    tiles = game_client_walk_tiles(gx - sx, gy - sy)
    if not tiles:
        return True
    prev = (sx + tiles[0][0], sy + tiles[0][1])
    for rx, ry in tiles[1:]:
        tile = (sx + rx, sy + ry)
        if not terrain.is_walkable(tile[0], tile[1]):
            return False
        if not terrain.can_step(prev[0], prev[1], tile[0], tile[1]):
            return False
        prev = tile
    return True


def is_click_valid(
    path: Sequence[tuple[int, int]],
    click_index: int,
    slack: int | None = None,
    terrain: Optional[TerrainMap] = None,
) -> bool:
    """True when ``path[click_index]`` is a safe ground click from ``path[0]``.

    With ``terrain``: client walk polyline must stay on walkable tiles (replaces
    A* slack). Without ``terrain``: legacy ``astar_d <= chev_d + slack`` for
    boot/tests.
    """
    if click_index <= 0 or click_index >= len(path):
        return False
    ox, oy = path[0]
    cx, cy = path[click_index]
    if terrain is not None:
        return is_game_walk_clear(terrain, (ox, oy), (cx, cy))
    if slack is None:
        slack = CLICK_PATH_SLACK
    chev_d = tile_chebyshev(ox, oy, cx, cy)
    astar_d = click_index  # unit step cost from start
    return astar_d <= chev_d + slack


def select_click_waypoint(
    path: Sequence[tuple[int, int]],
    origin: WorldOrigin,
    slack: int | None = None,
    terrain: Optional[TerrainMap] = None,
    *,
    max_hop: int | None = None,
) -> Optional[tuple[int, int]]:
    """Last near→far path tile in the click parallelogram that is click-safe.

    ``path[0]`` must be the character's current absolute tile. Returns the
    absolute click tile, or ``None`` if no safe hop exists.

    When ``terrain`` is set, skip tiles with ``dist_to_wall == 0`` (8-adjacent
    to blocked) if a farther-or-equal valid tile with clearance exists.

    ``max_hop`` caps Chebyshev distance from ``path[0]`` (dungeon short hops).
    """
    if slack is None:
        slack = CLICK_PATH_SLACK
    if len(path) < 2:
        return None

    ox, oy = path[0]
    last_ok: Optional[tuple[int, int]] = None
    last_clear: Optional[tuple[int, int]] = None
    for i in range(1, len(path)):
        ax, ay = path[i]
        if max_hop is not None and tile_chebyshev(ox, oy, ax, ay) > max_hop:
            break
        rx, ry = absolute_to_relative(ax, ay, origin)
        if not in_battle_click_region(rx, ry):
            break
        if not is_click_valid(path, i, slack=slack, terrain=terrain):
            break
        last_ok = (ax, ay)
        if terrain is None or terrain.dist_to_wall(ax, ay) >= 1:
            last_clear = (ax, ay)
    return last_clear if last_clear is not None else last_ok


def waypoint_to_content(
    absolute_tile: tuple[int, int],
    origin: WorldOrigin,
) -> Position:
    """Absolute click tile → content-normalized destination for ActionIntent."""
    rx, ry = absolute_to_relative(absolute_tile[0], absolute_tile[1], origin)
    return world_to_content(float(rx), float(ry))


def plan_travel_click(
    terrain: TerrainMap,
    origin: WorldOrigin,
    goal: tuple[int, int],
    slack: int | None = None,
    *,
    cluster: int | None = None,
    force_flat: bool = False,
    max_hop: int | None = None,
) -> tuple[Optional[Position], list[tuple[int, int]], Optional[tuple[int, int]]]:
    """Pathfind from origin to goal and pick a content click destination.

    On large maps uses hierarchical (coarse + local fine) search. Returns
    ``(content_dest, path, absolute_waypoint)``. ``content_dest`` is ``None``
    if unreachable or no valid in-view click hop.

    When ``max_hop`` is omitted: dungeon → ``DUNGEON_MAX_HOP_TILES`` (3),
    otherwise field → ``player_mode.TRAVEL_MAX_HOP_TILES`` (default 5).
    Client-walk clear check still applies inside ``select_click_waypoint``.
    """
    if slack is None:
        slack = CLICK_PATH_SLACK
    if max_hop is None:
        from app._04_decision.dungeon import dungeon_max_hop_tiles, is_dungeon_map
        from app._04_decision import player_mode as pm

        if is_dungeon_map():
            max_hop = dungeon_max_hop_tiles()
        else:
            max_hop = int(pm.TRAVEL_MAX_HOP_TILES)
    from app._04_decision.hierarchical_path import (
        DEFAULT_CLUSTER,
        HIERARCHICAL_AREA_THRESHOLD,
        plan_travel_click_hierarchical,
    )

    area = terrain.width * terrain.height
    if not force_flat and area > HIERARCHICAL_AREA_THRESHOLD:
        try:
            from app._04_decision.nav_config import (
                get_cluster_size,
                get_coarse_map,
                get_portal_graph,
            )

            cached = get_coarse_map()
            portals = get_portal_graph()
            cfg_cluster = get_cluster_size()
        except Exception:
            cached = None
            portals = None
            cfg_cluster = DEFAULT_CLUSTER
        use_cluster = cluster if cluster is not None else cfg_cluster
        dest, path, wp, _coarse = plan_travel_click_hierarchical(
            terrain,
            origin,
            goal,
            cluster=use_cluster,
            coarse=cached if cached is not None and cached.cluster == use_cluster else None,
            portal_graph=(
                portals
                if portals is not None and portals.cluster == use_cluster
                else None
            ),
            slack=slack,
            max_hop=max_hop,
        )
        return dest, path, wp

    start = (origin.x, origin.y)
    path = find_path(terrain, start, goal)
    if not path:
        return None, [], None
    waypoint = select_click_waypoint(
        path, origin, slack=slack, terrain=terrain, max_hop=max_hop
    )
    if waypoint is None:
        return None, path, None
    return waypoint_to_content(waypoint, origin), path, waypoint


__all__ = [
    "find_path",
    "game_client_walk_tiles",
    "is_game_walk_clear",
    "is_click_valid",
    "select_click_waypoint",
    "waypoint_to_content",
    "plan_travel_click",
]

from app._04_decision.decide_spans import traced

plan_travel_click = traced(plan_travel_click)
