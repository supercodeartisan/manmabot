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

Same-map movement guides may pick among equal-length shortest paths, then
offset 1–2 arbitrary path points onto walkable tiles (Chebyshev 1–2) and
recompute shortest segments through those vias. Distance queries keep
deterministic ``find_path``.
"""
from __future__ import annotations

import heapq
import random
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

# Equal-length shortest alternatives for same-map movement (strictly < 5).
MAX_SHORTEST_ALTERNATIVES = 4
_MAX_PARENTS_PER_NODE = 4
# After a shortest guide is chosen, pick 1–2 path points, offset each onto a
# walkable tile within PATH_NUDGE_RADIUS, then recompute shortest segments
# start → via(s) → goal.
PATH_NUDGE_COUNT_MIN = 1
PATH_NUDGE_COUNT_MAX = 2
PATH_NUDGE_RADIUS = 2
# Minimum path index gap between two via samples.
PATH_NUDGE_MIN_SEPARATION = 5


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


def _path_suffix_from(
    path: Sequence[tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    """Return ``path`` from ``start`` to ``goal`` when that segment is present."""
    if not path:
        return []
    tiles = [(int(x), int(y)) for x, y in path]
    want_start = (int(start[0]), int(start[1]))
    want_goal = (int(goal[0]), int(goal[1]))
    if tiles[-1] != want_goal:
        return []
    try:
        index = tiles.index(want_start)
    except ValueError:
        return []
    return tiles[index:]


def sticky_shortest_suffix(
    sticky_path: Sequence[tuple[int, int]] | None,
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    """Reuse a prior movement guide when still valid from ``start``."""
    suffix = _path_suffix_from(sticky_path or (), start, goal)
    if len(suffix) < 1:
        return []
    if len(suffix) == 1:
        return suffix
    for a, b in zip(suffix, suffix[1:]):
        if not terrain.can_step(a[0], a[1], b[0], b[1]):
            return []
    return suffix


def _walkable_offsets(
    terrain: TerrainMap,
    origin: tuple[int, int],
    *,
    radius: int,
    forbidden: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Walkable tiles within Chebyshev ``radius`` of ``origin`` (exclusive)."""
    ox, oy = int(origin[0]), int(origin[1])
    block = forbidden or set()
    found: list[tuple[int, int]] = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = max(abs(dx), abs(dy))
            if dist < 1 or dist > radius:
                continue
            cand = (ox + dx, oy + dy)
            if cand in block:
                continue
            if terrain.is_walkable(cand[0], cand[1]):
                found.append(cand)
    return found


def nudge_path_lateral(
    terrain: TerrainMap,
    path: Sequence[tuple[int, int]],
    goal: tuple[int, int],
    *,
    nudge_count: int | None = None,
    radius: int = PATH_NUDGE_RADIUS,
) -> list[tuple[int, int]]:
    """Deform a shortest path via 1–2 walkable offsets, then re-A* the pieces.

    1. Take any interior point(s) on ``path``.
    2. Move each by 1–``radius`` tiles onto a walkable cell.
    3. Recompute shortest segments ``start → via… → goal``.

    The joined route need not be globally shortest. If no via works, returns
    the original ``path``.
    """
    tiles = [(int(x), int(y)) for x, y in path]
    if len(tiles) < 3:
        return tiles
    start_xy = tiles[0]
    goal_xy = (int(goal[0]), int(goal[1]))
    if tiles[-1] != goal_xy:
        goal_xy = tiles[-1]
    interior = list(range(1, len(tiles) - 1))
    if not interior:
        return tiles
    if nudge_count is None:
        lo = min(PATH_NUDGE_COUNT_MIN, len(interior))
        hi = min(PATH_NUDGE_COUNT_MAX, len(interior))
        count = random.randint(lo, hi) if hi >= lo else 0
    else:
        count = max(0, min(int(nudge_count), len(interior), PATH_NUDGE_COUNT_MAX))
    if count <= 0:
        return tiles

    random.shuffle(interior)
    chosen_idx: list[int] = []
    for idx in interior:
        if any(abs(idx - kept) < PATH_NUDGE_MIN_SEPARATION for kept in chosen_idx):
            continue
        chosen_idx.append(idx)
        if len(chosen_idx) >= count:
            break
    if not chosen_idx:
        return tiles

    path_set = set(tiles)
    vias: list[tuple[int, tuple[int, int]]] = []
    for idx in sorted(chosen_idx):
        cands = _walkable_offsets(
            terrain,
            tiles[idx],
            radius=max(1, int(radius)),
            forbidden=path_set | {start_xy, goal_xy},
        )
        if not cands:
            # Fall back: any walkable offset, even if it sits on the old path.
            cands = _walkable_offsets(
                terrain,
                tiles[idx],
                radius=max(1, int(radius)),
                forbidden={start_xy, goal_xy, tiles[idx]},
            )
        if not cands:
            continue
        vias.append((idx, random.choice(cands)))
    if not vias:
        return tiles

    # Chain shortest paths through the vias in path order.
    cursor = start_xy
    out: list[tuple[int, int]] = [cursor]
    for _idx, via in vias:
        seg, _, _ = _find_path_search(terrain, cursor, via)
        if len(seg) < 2:
            return tiles
        out.extend(seg[1:])
        cursor = via
    tail, _, _ = _find_path_search(terrain, cursor, goal_xy)
    if len(tail) < 2:
        return tiles
    out.extend(tail[1:])
    return out


def _enumerate_shortest_from_parents(
    came_from: dict[tuple[int, int], list[tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    max_paths: int,
) -> list[list[tuple[int, int]]]:
    """Collect up to ``max_paths`` distinct start→goal routes on the parent DAG."""
    if max_paths <= 0:
        return []
    if start == goal:
        return [[start]]
    found: list[list[tuple[int, int]]] = []

    def dfs(node: tuple[int, int], suffix: list[tuple[int, int]]) -> None:
        if len(found) >= max_paths:
            return
        if node == start:
            found.append([start] + suffix)
            return
        parents = list(came_from.get(node) or ())
        random.shuffle(parents)
        for parent in parents:
            dfs(parent, [node] + suffix)

    dfs(goal, [])
    return found


def _find_shortest_parent_dag(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    allowed: Optional["np.ndarray"] = None,
) -> tuple[dict[tuple[int, int], list[tuple[int, int]]], int, bool]:
    """A* that keeps equal-g parents; continues until f exceeds g(goal).

    Returns ``(came_from_multi, expanded, entered_loop)``.
    """
    sx, sy = start
    gx, gy = goal
    if not terrain.is_walkable(sx, sy) or not terrain.is_walkable(gx, gy):
        return {}, 0, False
    if start == goal:
        return {}, 0, False

    def ok(x: int, y: int) -> bool:
        if not terrain.is_walkable(x, y):
            return False
        if allowed is None:
            return True
        return bool(allowed[y, x])

    if not ok(sx, sy) or not ok(gx, gy):
        return {}, 0, False

    def h(x: int, y: int) -> int:
        return tile_chebyshev(x, y, gx, gy)

    def tie(x: int, y: int) -> int:
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
    came_from: dict[tuple[int, int], list[tuple[int, int]]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}
    closed: set[tuple[int, int]] = set()
    g_goal: int | None = None

    while open_heap:
        f_cur, _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if g_goal is not None and f_cur > g_goal:
            break
        if current == goal:
            g_goal = g_score[current]
            closed.add(current)
            continue
        closed.add(current)
        cx, cy = current
        for nx, ny in neighbors(cx, cy):
            neighbor = (nx, ny)
            tentative = g_score[current] + terrain.tile_cost(nx, ny)
            if g_goal is not None and tentative > g_goal:
                continue
            prev = g_score.get(neighbor)
            if prev is not None and tentative > prev:
                continue
            if prev is not None and tentative == prev:
                parents = came_from.setdefault(neighbor, [])
                if current not in parents and len(parents) < _MAX_PARENTS_PER_NODE:
                    parents.append(current)
                continue
            came_from[neighbor] = [current]
            g_score[neighbor] = tentative
            if neighbor in closed and neighbor != goal:
                # Better g found after an outdated close — reopen.
                closed.discard(neighbor)
            counter += 1
            f = tentative + h(nx, ny)
            heapq.heappush(open_heap, (f, tie(nx, ny), counter, neighbor))
    return came_from, len(closed), True


def list_shortest_paths(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    allowed: Optional["np.ndarray"] = None,
    max_paths: int = MAX_SHORTEST_ALTERNATIVES,
) -> list[list[tuple[int, int]]]:
    """Up to ``max_paths`` distinct equal-length shortest paths (may be 1)."""
    cap = max(1, min(int(max_paths), MAX_SHORTEST_ALTERNATIVES))
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])
    start_xy = (sx, sy)
    goal_xy = (gx, gy)
    if start_xy == goal_xy:
        if terrain.is_walkable(sx, sy):
            return [[start_xy]]
        return []
    came_from, _expanded, entered = _find_shortest_parent_dag(
        terrain, start_xy, goal_xy, allowed=allowed
    )
    if not entered or goal_xy not in came_from:
        one, _, _ = _find_path_search(
            terrain, start_xy, goal_xy, allowed=allowed
        )
        return [one] if one else []
    paths = _enumerate_shortest_from_parents(
        came_from, start_xy, goal_xy, max_paths=cap
    )
    if paths:
        return paths
    one, _, _ = _find_path_search(
        terrain, start_xy, goal_xy, allowed=allowed
    )
    return [one] if one else []


def find_path_random_shortest(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    allowed: Optional["np.ndarray"] = None,
    max_paths: int = MAX_SHORTEST_ALTERNATIVES,
    sticky_path: Sequence[tuple[int, int]] | None = None,
    apply_lateral_nudge: bool = True,
) -> list[tuple[int, int]]:
    """Pick uniformly among equal-length shortest paths, then via-deform.

    1. Collect up to ``max_paths`` equal-shortest routes and choose one at random.
    2. Optionally offset 1–2 path points onto walkable tiles and recompute
       shortest ``start→via→goal`` segments (joined route need not be shortest).

    Used by same-map movement guides. Combat / distance keep ``find_path``.
    Sticky reuses the deformed guide across hops to the same goal.
    """
    import time

    from app._04_decision.astar_trace import labels_from_stack, record_search

    start_xy = (int(start[0]), int(start[1]))
    goal_xy = (int(goal[0]), int(goal[1]))
    reused = sticky_shortest_suffix(sticky_path, terrain, start_xy, goal_xy)
    if reused:
        return reused

    t0 = time.perf_counter()
    paths: list[list[tuple[int, int]]] = []
    chosen: list[tuple[int, int]] = []
    expanded = 0
    entered = False
    try:
        came_from, expanded, entered = _find_shortest_parent_dag(
            terrain, start_xy, goal_xy, allowed=allowed
        )
        if entered and goal_xy in came_from:
            paths = _enumerate_shortest_from_parents(
                came_from,
                start_xy,
                goal_xy,
                max_paths=max(1, min(int(max_paths), MAX_SHORTEST_ALTERNATIVES)),
            )
        if paths:
            chosen = random.choice(paths)
        else:
            chosen, expanded, entered = _find_path_search(
                terrain, start_xy, goal_xy, allowed=allowed
            )
            if chosen:
                paths = [chosen]
        if chosen and apply_lateral_nudge:
            chosen = nudge_path_lateral(terrain, chosen, goal_xy)
        return chosen
    finally:
        if entered:
            cause, search = labels_from_stack()
            record_search(
                cause=cause,
                search=f"{search}+alt{len(paths)}",
                ms=(time.perf_counter() - t0) * 1000.0,
                start=start_xy,
                goal=goal_xy,
                steps=max(0, len(chosen) - 1),
                expanded=expanded,
            )


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
    picked = last_clear if last_clear is not None else last_ok
    if picked is None:
        return None
    from app._04_decision.doors import retarget_open_door

    beyond, replaced = retarget_open_door(
        [(int(x), int(y)) for x, y in path],
        (int(ox), int(oy)),
        picked,
        max_hop,
    )
    if not replaced:
        return picked
    if beyond is None:
        return None
    rx, ry = absolute_to_relative(int(beyond[0]), int(beyond[1]), origin)
    if not in_battle_click_region(rx, ry):
        return None
    try:
        beyond_i = next(
            i
            for i, tile in enumerate(path)
            if (int(tile[0]), int(tile[1])) == beyond
        )
    except StopIteration:
        return None
    if not is_click_valid(path, beyond_i, slack=slack, terrain=terrain):
        return None
    return beyond


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
    sticky_path: Sequence[tuple[int, int]] | None = None,
) -> tuple[Optional[Position], list[tuple[int, int]], Optional[tuple[int, int]]]:
    """Pathfind from origin to goal and pick a content click destination.

    On large maps uses hierarchical (coarse + local fine) search. Returns
    ``(content_dest, path, absolute_waypoint)``. ``content_dest`` is ``None``
    if unreachable or no valid in-view click hop.

    Fine guides pick among equal-length shortest alternatives. Pass
    ``sticky_path`` (prior guide to the same goal) to keep one choice across hops.

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
            sticky_path=sticky_path,
        )
        return dest, path, wp

    start = (origin.x, origin.y)
    path = find_path_random_shortest(
        terrain, start, goal, sticky_path=sticky_path
    )
    if not path:
        return None, [], None
    waypoint = select_click_waypoint(
        path, origin, slack=slack, terrain=terrain, max_hop=max_hop
    )
    if waypoint is None:
        return None, path, None
    return waypoint_to_content(waypoint, origin), path, waypoint


__all__ = [
    "MAX_SHORTEST_ALTERNATIVES",
    "PATH_NUDGE_COUNT_MAX",
    "PATH_NUDGE_RADIUS",
    "find_path",
    "find_path_random_shortest",
    "list_shortest_paths",
    "nudge_path_lateral",
    "sticky_shortest_suffix",
    "game_client_walk_tiles",
    "is_game_walk_clear",
    "is_click_valid",
    "select_click_waypoint",
    "waypoint_to_content",
    "plan_travel_click",
]

from app._04_decision.decide_spans import traced

plan_travel_click = traced(plan_travel_click)
