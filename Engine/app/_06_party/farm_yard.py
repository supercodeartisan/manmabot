"""Turret farm yard: a flexible box around the leader for party hunting.

Members may step inside the yard (assist / short close-in) but do not chase
targets outside it, so the party stays together.
"""
from __future__ import annotations

from typing import Any, Optional

# Base half-extents → ~5×7 tiles (width=5, height=7) for small parties.
_BASE_HALF_W = 2
_BASE_HALF_H = 3
_MAX_HALF_W = 6
_MAX_HALF_H = 8


def yard_half_extents(
    party_size: int,
    *,
    half_w: Optional[int] = None,
    half_h: Optional[int] = None,
    scale_with_roster: bool = True,
) -> tuple[int, int]:
    """Return ``(half_w, half_h)`` Chebyshev-style axis half-sizes from the anchor."""
    if half_w is not None and half_h is not None:
        return (
            max(1, min(_MAX_HALF_W, int(half_w))),
            max(1, min(_MAX_HALF_H, int(half_h))),
        )
    n = max(1, int(party_size))
    w = _BASE_HALF_W
    h = _BASE_HALF_H
    if scale_with_roster and n > 5:
        extra = n - 5
        w = _BASE_HALF_W + (extra + 1) // 2
        h = _BASE_HALF_H + extra // 2
    return (
        max(1, min(_MAX_HALF_W, w)),
        max(1, min(_MAX_HALF_H, h)),
    )


def in_yard(
    tile: Optional[tuple[int, int]],
    anchor: Optional[tuple[int, int]],
    *,
    half_w: int,
    half_h: int,
) -> bool:
    if tile is None or anchor is None:
        return False
    dx = abs(int(tile[0]) - int(anchor[0]))
    dy = abs(int(tile[1]) - int(anchor[1]))
    return dx <= int(half_w) and dy <= int(half_h)


def clamp_to_yard(
    tile: tuple[int, int],
    anchor: tuple[int, int],
    *,
    half_w: int,
    half_h: int,
) -> tuple[int, int]:
    ax, ay = int(anchor[0]), int(anchor[1])
    x = max(ax - int(half_w), min(ax + int(half_w), int(tile[0])))
    y = max(ay - int(half_h), min(ay + int(half_h), int(tile[1])))
    return (x, y)


def tile_from_obj(obj: Any, origin: Any) -> Optional[tuple[int, int]]:
    if obj is None or origin is None:
        return None
    try:
        from app._04_decision.combat_query import object_absolute_tile

        return object_absolute_tile(obj, origin)
    except Exception:
        return None


__all__ = [
    "clamp_to_yard",
    "in_yard",
    "tile_from_obj",
    "yard_half_extents",
]
