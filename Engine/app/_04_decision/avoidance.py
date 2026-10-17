"""Local click around alive bodies.

Travel (field and dungeon), patrol, loot, and farm search hops call
``plan_body_click``.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Optional

from app._02_state.objects import ObjectStatus, ObjectType, Relationship
from app._03_world.space.terrain_map import TerrainMap
from app._03_world.space.world_coords import (
    WorldOrigin,
    absolute_to_relative,
    in_battle_click_region,
    tile_chebyshev,
)
from app._04_decision.pathfinding import game_client_walk_tiles

# Chebyshev radius around the character. 21×21, center included.
AVOID_RADIUS = 10

_BODY_TYPES = (ObjectType.PLAYER, ObjectType.NPC, ObjectType.MONSTER)
_NEIGHBORS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)


def travel_max_hop() -> int:
    """Same hop cap ``plan_travel_click`` uses for the field or a dungeon."""
    from app._04_decision.dungeon import dungeon_max_hop_tiles, is_dungeon_map
    from app._04_decision import player_mode as pm

    if is_dungeon_map():
        return int(dungeon_max_hop_tiles())
    return int(pm.TRAVEL_MAX_HOP_TILES)


def avoid_bodies(blackboard: object) -> set[tuple[int, int]]:
    """Body tiles refreshed for this decision, or an empty set."""
    raw = getattr(blackboard, "avoid_body_tiles", None)
    if not raw:
        return set()
    return {(int(x), int(y)) for x, y in raw}


def _memory_monster(obj: object) -> bool:
    """True when print_state classed this row as a monster.

    Species catalog and blacklist do not apply. ``SummonedMonster`` is
    stored as the same coarse class.
    """
    kind = getattr(obj, "memory_class", None)
    return isinstance(kind, str) and kind.strip().lower() == "monster"


def _avoid_body(obj: object) -> bool:
    """Players and NPCs stay on object type. Monsters use memory class."""
    kind = getattr(obj, "object_type", None)
    if kind in (ObjectType.PLAYER, ObjectType.NPC):
        return True
    return _memory_monster(obj)


def _body_candidates(state: object) -> list:
    if hasattr(state, "all_objects"):
        return list(state.all_objects())
    found = []
    for kind in _BODY_TYPES:
        found.extend(state.objects(kind))
    return found


def collect_body_tiles(
    state: object,
    origin: WorldOrigin,
    *,
    ignore_ids: Iterable[int] = (),
) -> set[tuple[int, int]]:
    """Alive player / NPC / memory-monster centers inside the local window.

    Players and NPCs use object type. A monster is a print_state
    ``monster`` row, including one the species filter typed as OTHER.
    The character's own tile is omitted. Tiles farther than
    ``AVOID_RADIUS`` are omitted. ``ignore_ids`` is empty for travel,
    search, and loot.
    """
    if state is None or not hasattr(state, "objects"):
        return set()
    from app._04_decision.combat_query import object_absolute_tile
    from app._04_decision.target_selector import MAX_MISSED_FRAMES

    start = (int(origin.x), int(origin.y))
    ignored = {int(item) for item in ignore_ids}
    missing = getattr(state, "missing_frames", None)
    tiles: set[tuple[int, int]] = set()
    for obj in _body_candidates(state):
        if not _avoid_body(obj):
            continue
        if getattr(obj, "status", None) is ObjectStatus.DEAD:
            continue
        if getattr(obj, "relationship", None) is Relationship.SELF:
            continue
        track_id = getattr(obj, "track_id", None)
        if track_id is not None and int(track_id) in ignored:
            continue
        if callable(missing) and track_id is not None:
            if int(missing(int(track_id))) > int(MAX_MISSED_FRAMES):
                continue
        try:
            tile = object_absolute_tile(obj, origin)
        except (TypeError, ValueError, AttributeError):
            continue
        if tile == start:
            continue
        if tile_chebyshev(start[0], start[1], tile[0], tile[1]) > AVOID_RADIUS:
            continue
        tiles.add((int(tile[0]), int(tile[1])))
    return tiles


def _cell_blocked(
    terrain: TerrainMap,
    bodies: set[tuple[int, int]],
    x: int,
    y: int,
) -> bool:
    if (x, y) in bodies:
        return True
    return not terrain.is_walkable(x, y)


def click_clear(
    terrain: TerrainMap,
    bodies: set[tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> bool:
    """True when the client polyline misses walls, fences, and living bodies.

    Each step uses ``terrain.can_step`` (N/E fences when present; otherwise
    diagonal pinch). Bodies and blocked cells still close the tile stepped on.
    """
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])
    tiles = game_client_walk_tiles(gx - sx, gy - sy)
    absolute = [(sx + rx, sy + ry) for rx, ry in tiles]
    prev = absolute[0]
    for tile in absolute[1:]:
        if _cell_blocked(terrain, bodies, tile[0], tile[1]):
            return False
        if not terrain.can_step(prev[0], prev[1], tile[0], tile[1]):
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
    dx = int(waypoint[0]) - int(start[0])
    dy = int(waypoint[1]) - int(start[1])
    sx, sy = int(start[0]), int(start[1])
    return [(sx + rx, sy + ry) for rx, ry in game_client_walk_tiles(dx, dy)]


def plan_avoidance_click(
    terrain: TerrainMap,
    origin: WorldOrigin,
    guide: Optional[list[tuple[int, int]]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    *,
    max_hop: int,
) -> Optional[tuple[int, int]]:
    """One click toward ``waypoint`` that stays off nearby bodies.

    A clear, in-region waypoint is returned unchanged. Otherwise BFS
    inside the window and the farthest client-clear tile on that path
    is the click. ``None`` means the window has no click; the caller
    leaves that to the existing unstick sweep.
    """
    start = (int(origin.x), int(origin.y))
    goal_tile = (int(waypoint[0]), int(waypoint[1]))
    if start == goal_tile:
        return None
    # Empty bodies: still require hop / region / clear (waypoint may exceed hop).
    if not bodies:
        if _click_allowed(terrain, origin, start, goal_tile, bodies, max_hop):
            return goal_tile
        return None
    if (
        click_clear(terrain, bodies, start, goal_tile)
        and _in_click_region(origin, goal_tile)
        and tile_chebyshev(start[0], start[1], goal_tile[0], goal_tile[1])
        <= int(max_hop)
    ):
        return goal_tile

    sx, sy = start

    def window_blocked(x: int, y: int) -> bool:
        if (x, y) == start:
            return False
        if max(abs(x - sx), abs(y - sy)) > AVOID_RADIUS:
            return True
        return _cell_blocked(terrain, bodies, x, y)

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

    path = _bfs(terrain, start, local_goal, window_blocked)
    if not path:
        return None

    hop = max(1, int(max_hop))
    for tile in reversed(path[1:]):
        if tile_chebyshev(sx, sy, tile[0], tile[1]) > hop:
            continue
        if not _in_click_region(origin, tile):
            continue
        if click_clear(terrain, bodies, start, tile):
            return tile
    return None


def _bfs(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked,
) -> list[tuple[int, int]]:
    """8-connected shortest path using ``terrain.can_step``."""
    queue: deque[tuple[int, int]] = deque([start])
    parent: dict[tuple[int, int], Optional[tuple[int, int]]] = {start: None}
    gx, gy = goal
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        cx, cy = current
        neighbors = []
        for dx, dy in _NEIGHBORS:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in parent or blocked(nx, ny):
                continue
            if not terrain.can_step(cx, cy, nx, ny):
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


GROUND_RECLICK_S = 0.1


@dataclass
class BodyClick:
    """One patrol or loot hop. ``click`` is the ground click, not the interim tile."""

    guide: list[tuple[int, int]] = field(default_factory=list)
    waypoint: tuple[int, int] | None = None
    click: tuple[int, int] | None = None
    note: str = ""


def interim_waypoint(
    start: tuple[int, int],
    guide: list[tuple[int, int]],
    bodies: set[tuple[int, int]],
) -> tuple[int, int] | None:
    """Last free guide tile before the path leaves the avoid window.

    Walk forward from the character. A living body is skipped. The first
    tile outside ``AVOID_RADIUS`` ends the search.
    """
    sx, sy = int(start[0]), int(start[1])
    begin = 0
    for index, raw in enumerate(guide):
        if (int(raw[0]), int(raw[1])) == (sx, sy):
            begin = index
            break
    chosen: tuple[int, int] | None = None
    for x, y in guide[begin:]:
        tile = (int(x), int(y))
        if tile == (sx, sy):
            continue
        if max(abs(tile[0] - sx), abs(tile[1] - sy)) > int(AVOID_RADIUS):
            break
        if tile in bodies:
            continue
        chosen = tile
    return chosen


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


def _click_allowed(
    terrain: TerrainMap,
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
    rx, ry = absolute_to_relative(cx, cy, origin)
    if not in_battle_click_region(rx, ry):
        return False
    return click_clear(terrain, bodies, (sx, sy), (cx, cy))


def _farthest_guide_click(
    terrain: TerrainMap,
    origin: WorldOrigin,
    start: tuple[int, int],
    guide: list[tuple[int, int]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    max_hop: int,
) -> tuple[int, int] | None:
    """Last guide tile toward ``waypoint`` that still passes hop / region / clear."""
    best: tuple[int, int] | None = None
    for tile in _guide_through(guide, start, waypoint)[1:]:
        if _click_allowed(terrain, origin, start, tile, bodies, max_hop):
            best = (int(tile[0]), int(tile[1]))
    return best


def _adjacent_guide_step(
    terrain: TerrainMap,
    origin: WorldOrigin,
    start: tuple[int, int],
    guide: list[tuple[int, int]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    max_hop: int,
) -> tuple[int, int] | None:
    """The next guide tile when it sits one step from the character.

    Used only after the longer hop has no click. A tile farther than one
    step stays out; a closed line stays out.
    """
    sx, sy = int(start[0]), int(start[1])
    wx, wy = int(waypoint[0]), int(waypoint[1])
    start_goal = tile_chebyshev(sx, sy, wx, wy)
    through = _guide_through(guide, start, (wx, wy))
    ordered: list[tuple[int, int]] = []
    if len(through) >= 2:
        ordered.append((int(through[1][0]), int(through[1][1])))
    else:
        for raw in guide:
            tx, ty = int(raw[0]), int(raw[1])
            if (tx, ty) == (sx, sy):
                continue
            if tile_chebyshev(sx, sy, tx, ty) != 1:
                continue
            if tile_chebyshev(tx, ty, wx, wy) > start_goal:
                continue
            ordered.append((tx, ty))
            break
    for tile in ordered:
        if tile_chebyshev(sx, sy, tile[0], tile[1]) != 1:
            continue
        if _click_allowed(terrain, origin, start, tile, bodies, max_hop):
            return tile
    return None


def choose_body_click(
    terrain: TerrainMap,
    origin: WorldOrigin,
    start: tuple[int, int],
    guide: list[tuple[int, int]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    max_hop: int,
) -> tuple[tuple[int, int] | None, str]:
    """Avoidance click toward ``waypoint``, still capped by the hop."""
    click = plan_avoidance_click(
        terrain,
        origin,
        guide,
        waypoint,
        bodies,
        max_hop=int(max_hop),
    )
    if click is not None and not _click_allowed(
        terrain, origin, start, click, bodies, max_hop
    ):
        click = None
    if click is None:
        # Farthest legal hop on the guide — not the first Chebyshev neighbor.
        click = _farthest_guide_click(
            terrain, origin, start, guide, waypoint, bodies, max_hop
        )
    if click is None:
        # The longer hop is closed. One guide tile beside the character
        # is still a step, when that single line is open.
        click = _adjacent_guide_step(
            terrain, origin, start, guide, waypoint, bodies, max_hop
        )
    if click is None:
        return None, "window has no safe click"
    click = (int(click[0]), int(click[1]))
    if click == waypoint:
        note = "line is clear, click is the guide waypoint"
    elif click in _guide_through(guide, start, waypoint) or click in {
        (int(x), int(y)) for x, y in guide
    }:
        note = "line is clear, click is the hop toward the waypoint"
    else:
        note = "a body blocks the guide line, click steps aside"
    return click, note


def _guide_to_goal(
    terrain: TerrainMap,
    origin: WorldOrigin,
    goal: tuple[int, int],
    *,
    max_hop: int,
    cluster: int | None,
    coarse: object | None,
    portal_graph: object | None,
) -> list[tuple[int, int]]:
    if coarse is not None or portal_graph is not None:
        from app._04_decision.hierarchical_path import (
            DEFAULT_CLUSTER,
            plan_travel_click_hierarchical,
        )

        _dest, path, _wp, _coarse = plan_travel_click_hierarchical(
            terrain,
            origin,
            goal,
            cluster=int(DEFAULT_CLUSTER if cluster is None else cluster),
            coarse=coarse,
            portal_graph=portal_graph,
            max_hop=int(max_hop),
        )
    else:
        from app._04_decision.pathfinding import plan_travel_click

        _dest, path, _wp = plan_travel_click(
            terrain,
            origin,
            goal,
            cluster=cluster,
            max_hop=int(max_hop),
        )
    return [(int(x), int(y)) for x, y in path]


def plan_body_click(
    terrain: TerrainMap,
    origin: WorldOrigin,
    goal: tuple[int, int],
    bodies: set[tuple[int, int]],
    *,
    max_hop: int | None = None,
    cluster: int | None = None,
    coarse: object | None = None,
    portal_graph: object | None = None,
) -> BodyClick:
    """Guide, interim waypoint, and the one hop click around living bodies.

    The guide is terrain only. Living bodies are not walls. The interim
    waypoint is the last free guide tile before the path leaves the avoid
    window. The returned click is inside the hop and the click region.
    """
    sx, sy = int(origin.x), int(origin.y)
    gx, gy = int(goal[0]), int(goal[1])
    if (sx, sy) == (gx, gy):
        return BodyClick(note="already on the goal")
    hop = travel_max_hop() if max_hop is None else int(max_hop)
    guide = _guide_to_goal(
        terrain,
        origin,
        (gx, gy),
        max_hop=hop,
        cluster=cluster,
        coarse=coarse,
        portal_graph=portal_graph,
    )
    near = {
        (int(x), int(y))
        for x, y in bodies
        if max(abs(int(x) - sx), abs(int(y) - sy)) <= int(AVOID_RADIUS)
        and (int(x), int(y)) != (sx, sy)
    }
    if not guide:
        _log_avoid_plan((sx, sy), hop, near, None, None, "no path to the goal")
        return BodyClick(note="no path to the goal")
    waypoint = interim_waypoint((sx, sy), guide, near)
    if waypoint is None:
        _log_avoid_plan((sx, sy), hop, near, None, None, "no click on the guide")
        return BodyClick(guide=guide, note="no click on the guide")
    click, note = choose_body_click(
        terrain, origin, (sx, sy), guide, waypoint, near, hop
    )
    _log_avoid_plan((sx, sy), hop, near, click, waypoint, note)
    return BodyClick(guide=guide, waypoint=waypoint, click=click, note=note)


def classify_ground_reclick(
    moving: bool | None,
    last_click_at: float,
    *,
    now: float,
) -> str:
    """``repeat`` when the body is not walking and 0.1s has passed.

    An unread action slot and a body that is already walking return ``hold``.
    """
    if moving is None or moving:
        return "hold"
    if float(last_click_at) <= 0.0 or (float(now) - float(last_click_at)) >= GROUND_RECLICK_S:
        return "repeat"
    return "hold"


def log_ground_pause(
    kind: str,
    waypoint: tuple[int, int],
    moving: bool | None,
    last_click_at: float,
    now: float,
    reason: str,
) -> None:
    """One line when a ground click is repeated because the body is not walking."""
    from app.bot_log import event

    gap = -1.0
    if float(last_click_at) > 0.0:
        gap = float(now) - float(last_click_at)
    state = "unread" if moving is None else ("1" if moving else "0")
    event(
        "travel",
        "pause reclick kind=%s wp=%s moving=%s gap=%.2f reason=%s",
        kind,
        (int(waypoint[0]), int(waypoint[1])),
        state,
        gap,
        reason,
    )


_avoid_quiet_at = 0.0
_avoid_quiet_key: tuple | None = None


def _log_avoid_plan(
    start: tuple[int, int],
    hop: int,
    near: set[tuple[int, int]],
    click: tuple[int, int] | None,
    waypoint: tuple[int, int] | None,
    note: str,
) -> None:
    """One line per planned hop. A repeated no-click stays quiet for 2s."""
    global _avoid_quiet_at, _avoid_quiet_key
    import time

    from app.bot_log import event

    sx, sy = int(start[0]), int(start[1])
    dist = -1
    if click is not None:
        dist = tile_chebyshev(sx, sy, int(click[0]), int(click[1]))
    nearest = "-"
    if near:
        nx, ny = min(
            near,
            key=lambda tile: tile_chebyshev(sx, sy, int(tile[0]), int(tile[1])),
        )
        nearest = f"({int(nx) - sx},{int(ny) - sy})"
    if click is None:
        key = (None, waypoint, note, len(near))
        now = time.time()
        if key == _avoid_quiet_key and (now - _avoid_quiet_at) < 2.0:
            return
        _avoid_quiet_key = key
        _avoid_quiet_at = now
    event(
        "avoid",
        "hop click=%s wp=%s dist=%s cap=%s bodies=%d near=%s note=%s",
        click,
        waypoint,
        dist,
        int(hop),
        len(near),
        nearest,
        note,
    )


def apply_avoidance(
    terrain: TerrainMap,
    origin: WorldOrigin,
    guide: Optional[list[tuple[int, int]]],
    waypoint: tuple[int, int],
    bodies: set[tuple[int, int]],
    *,
    max_hop: int,
    kind: str,
) -> Optional[tuple[int, int]]:
    """Return the click tile, or ``None`` when no safe click exists.

    An empty body set returns ``waypoint`` and does not search.
    """
    if not bodies:
        return (int(waypoint[0]), int(waypoint[1]))
    chosen = plan_avoidance_click(
        terrain,
        origin,
        guide,
        waypoint,
        bodies,
        max_hop=max_hop,
    )
    from app.bot_log import event

    if chosen is None:
        event("avoid", "%s blocked wp=%s", kind, waypoint)
        return None
    if chosen != (int(waypoint[0]), int(waypoint[1])):
        event("avoid", "%s sidestep wp=%s click=%s", kind, waypoint, chosen)
    return chosen


__all__ = [
    "AVOID_RADIUS",
    "GROUND_RECLICK_S",
    "BodyClick",
    "apply_avoidance",
    "avoid_bodies",
    "choose_body_click",
    "classify_ground_reclick",
    "log_ground_pause",
    "click_clear",
    "collect_body_tiles",
    "interim_waypoint",
    "plan_avoidance_click",
    "plan_body_click",
    "travel_max_hop",
]
