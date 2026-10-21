"""Tile helpers shared by the tactics modules.

``terrain`` is any object with ``is_walkable(x, y) -> bool`` (the live
``Terrain`` pack satisfies this). Errors and out-of-range reads count as blocked.
"""
from __future__ import annotations

from typing import Any

Tile = tuple[int, int]

N8: tuple[Tile, ...] = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)


def walkable(terrain: Any, x: int, y: int) -> bool:
    try:
        return bool(terrain.is_walkable(int(x), int(y)))
    except Exception:
        return False


def cheb(a: Tile, b: Tile) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def sign(v: int) -> int:
    return (v > 0) - (v < 0)
