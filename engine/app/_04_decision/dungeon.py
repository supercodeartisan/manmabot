"""Dungeon map-pack mode: patrol midpoints, LOS attacks, short travel hops.

A pack is treated as a dungeon when its id or display name contains
``dungeon`` (case-insensitive), e.g. ``talking_island_dungeon_F1``.

Schedule / profile ``map_style`` can override via :func:`set_dungeon_mode_override`.
"""
from __future__ import annotations

from typing import Optional

from app._03_world.map_pack import get_active_map_pack
from app._03_world.terrain_map import TerrainMap

# Max Chebyshev tiles for one battle-screen travel click in dungeon.
DUNGEON_MAX_HOP_TILES = 4

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


def line_of_sight_clear(
    terrain: TerrainMap,
    a: tuple[int, int],
    b: tuple[int, int],
) -> bool:
    """True when no wall/fence sits *between* A and B on the straight line.

    Walks Chebyshev-interpolated tiles from player ``a`` to goal ``b``.
    Player tile and goal tile are skipped: a monster/item may stand on a
    non-walkable nav cell without counting as a wall *between* the two.
    Any other blocked tile on the segment is a wall/fence hit.
    """
    ax, ay = a
    bx, by = b
    if ax == bx and ay == by:
        return True
    tiles = tiles_on_segment(ax, ay, bx, by)
    last = len(tiles) - 1
    for i, (x, y) in enumerate(tiles):
        if i == 0 or i == last:
            continue
        if not terrain.is_walkable(x, y):
            return False
    return True


def dungeon_max_hop_tiles() -> int:
    return int(DUNGEON_MAX_HOP_TILES)


__all__ = [
    "DUNGEON_MAX_HOP_TILES",
    "set_dungeon_mode_override",
    "get_dungeon_mode_override",
    "is_dungeon_map",
    "tiles_on_segment",
    "line_of_sight_clear",
    "dungeon_max_hop_tiles",
]
