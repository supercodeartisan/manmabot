"""Classify the area around the leader as open field or narrow dungeon.

Two measures over a ``(2r+1)²`` window:

- ``open_ratio``: walkable tiles / all tiles
- ``narrow_ratio``: walkable tiles with at most 5 walkable neighbours /
  walkable tiles (corridor and wall-edge tiles)

Hysteresis keeps the kind from flapping at a room/corridor boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ._grid import N8, Tile, walkable

OPEN = "open"
NARROW = "narrow"

_NARROW_NEIGHBOURS = 5


@dataclass(frozen=True)
class TerrainReading:
    kind: str
    open_ratio: float
    narrow_ratio: float
    radius: int


def classify_area(
    terrain: Any,
    center: Tile,
    *,
    radius: int = 6,
    open_threshold: float = 0.6,
    narrow_threshold: float = 0.45,
    hysteresis: float = 0.05,
    previous: Optional[str] = None,
) -> TerrainReading:
    r = max(1, int(radius))
    cx, cy = int(center[0]), int(center[1])
    total = 0
    walk = 0
    narrow = 0
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            total += 1
            if not walkable(terrain, x, y):
                continue
            walk += 1
            open_n = sum(1 for dx, dy in N8 if walkable(terrain, x + dx, y + dy))
            if open_n <= _NARROW_NEIGHBOURS:
                narrow += 1
    open_ratio = walk / total if total else 0.0
    narrow_ratio = narrow / walk if walk else 1.0

    th_open = float(open_threshold)
    th_narrow = float(narrow_threshold)
    h = max(0.0, float(hysteresis))
    if previous == OPEN:
        th_open -= h
        th_narrow += h
    elif previous == NARROW:
        th_open += h
        th_narrow -= h
    kind = OPEN if open_ratio >= th_open and narrow_ratio <= th_narrow else NARROW
    return TerrainReading(kind, open_ratio, narrow_ratio, r)


__all__ = ["NARROW", "OPEN", "TerrainReading", "classify_area"]
