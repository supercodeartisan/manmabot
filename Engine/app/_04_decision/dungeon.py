"""Dungeon map-pack mode: patrol midpoints, LOS attacks, short travel hops.

A pack is treated as a dungeon when its id or display name contains
``dungeon`` (case-insensitive), e.g. ``talking_island_dungeon_F1``.

Schedule / profile ``map_style`` can override via :func:`set_dungeon_mode_override`.
"""
from __future__ import annotations

from typing import Optional

from app._03_world.space.map_pack import get_active_map_pack
from app._03_world.space.terrain_map import TerrainMap

# Max Chebyshev tiles for one battle-screen travel click in dungeon.
DUNGEON_MAX_HOP_TILES = 3
# Hop/goal arrive radius in dungeon (field keeps farm_area.ARRIVE_TILES).
DUNGEON_ARRIVE_TILES = 1

# None = infer from pack id/name; True/False = schedule map_style override.
_dungeon_mode_override: Optional[bool] = None


def set_dungeon_mode_override(value: Optional[bool]) -> None:
    """Force dungeon/normal for the active session (``None`` clears override)."""
    global _dungeon_mode_override
    _dungeon_mode_override = None if value is None else bool(value)


def get_dungeon_mode_override() -> Optional[bool]:
    return _dungeon_mode_override


def is_dungeon_map(
    pack_id: str | None = None,
    name: str | None = None,
) -> bool:
    """True when the active (or given) map pack looks like a dungeon."""
    if pack_id is None and name is None:
        if _dungeon_mode_override is not None:
            return bool(_dungeon_mode_override)
        pack = get_active_map_pack()
        if pack is None:
            return False
        pack_id, name = pack.id, pack.name
    blob = f"{pack_id or ''} {name or ''}".lower()
    return "dungeon" in blob


def tiles_on_segment(
    ax: int,
    ay: int,
    bx: int,
    by: int,
) -> list[tuple[int, int]]:
    """Grid tiles on the straight segment A→B (inclusive), Chebyshev steps.

    Uses equal-step interpolation so diagonal moves do not skip cells.
    Good enough for dungeon LOS; walls on the line block attacks.
    """
    dx = bx - ax
    dy = by - ay
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return [(ax, ay)]
    out: list[tuple[int, int]] = []
    for i in range(steps + 1):
        x = ax + int(round(dx * i / steps))
        y = ay + int(round(dy * i / steps))
        if not out or out[-1] != (x, y):
            out.append((x, y))
    return out


def _los_step_open(
    terrain: TerrainMap,
    ax: int,
    ay: int,
    bx: int,
    by: int,
) -> bool:
    """True when the shared edge between adjacent tiles is not fenced.

    Unlike ``TerrainMap.can_step``, endpoints may be non-walkable (monster
    standing on a blocked nav cell). Intermediate L-path tiles for a
    diagonal still must be walkable.
    """
    from app._03_world.space.terrain_map import diagonal_open

    dx, dy = bx - ax, by - ay
    adx, ady = abs(dx), abs(dy)
    if adx > 1 or ady > 1 or (dx == 0 and dy == 0):
        return False
    if not terrain.has_edge_fences:
        if adx + ady == 1:
            return True
        return diagonal_open(terrain.walkable, ax, ay, bx, by)

    assert terrain.block_n is not None and terrain.block_e is not None

    def axis_open(x0: int, y0: int, x1: int, y1: int) -> bool:
        sx, sy = x1 - x0, y1 - y0
        if abs(sx) + abs(sy) != 1:
            return False
        if sy == -1:
            return not bool(terrain.block_n[y0, x0])
        if sy == 1:
            return not bool(terrain.block_n[y1, x1])
        if sx == 1:
            return not bool(terrain.block_e[y0, x0])
        if sx == -1:
            return not bool(terrain.block_e[y1, x1])
        return False

    if adx + ady == 1:
        return axis_open(ax, ay, bx, by)

    mx, my = ax + dx, ay + dy
    via_x = (
        terrain.is_walkable(mx, ay)
        and axis_open(ax, ay, mx, ay)
        and axis_open(mx, ay, bx, by)
    )
    via_y = (
        terrain.is_walkable(ax, my)
        and axis_open(ax, ay, ax, my)
        and axis_open(ax, my, bx, by)
    )
    return via_x or via_y


def line_of_sight_clear(
    terrain: TerrainMap,
    a: tuple[int, int],
    b: tuple[int, int],
) -> bool:
    """True when no wall/fence sits *between* A and B on the straight line.

    Walks Chebyshev-interpolated tiles from player ``a`` to goal ``b``.
    Intermediate tiles must be walkable. Every consecutive pair on the
    segment must have an open shared edge (N/E fences block even when both
    cells are open). Endpoints may be non-walkable; the edge into them is
    still checked.
    """
    ax, ay = a
    bx, by = b
    if ax == bx and ay == by:
        return True
    tiles = tiles_on_segment(ax, ay, bx, by)
    last = len(tiles) - 1
    for i, (x, y) in enumerate(tiles):
        if 0 < i < last and not terrain.is_walkable(x, y):
            return False
        if i < last:
            nx, ny = tiles[i + 1]
            if not _los_step_open(terrain, x, y, nx, ny):
                return False
    return True


def dungeon_max_hop_tiles() -> int:
    return int(DUNGEON_MAX_HOP_TILES)


def dungeon_arrive_tiles() -> int:
    return int(DUNGEON_ARRIVE_TILES)


def travel_arrive_tiles() -> int:
    """Arrive radius for shared travel/patrol: dungeon 1, otherwise field ARRIVE_TILES."""
    if is_dungeon_map():
        return dungeon_arrive_tiles()
    from app._04_decision.farm_area import ARRIVE_TILES

    return int(ARRIVE_TILES)


__all__ = [
    "DUNGEON_MAX_HOP_TILES",
    "DUNGEON_ARRIVE_TILES",
    "set_dungeon_mode_override",
    "get_dungeon_mode_override",
    "is_dungeon_map",
    "tiles_on_segment",
    "line_of_sight_clear",
    "dungeon_max_hop_tiles",
    "dungeon_arrive_tiles",
    "travel_arrive_tiles",
]
