"""Map-only check for a party hunt dot.

Live characters are ignored. A dot is refused when the nav grid has no
terrain, the cell is blocked, or nothing can step onto that cell.
"""
from __future__ import annotations

from typing import Any


def hunt_point_refused(terrain: Any, x: int, y: int) -> bool:
    if terrain is None:
        return True
    try:
        tx, ty = int(x), int(y)
    except (TypeError, ValueError):
        return True
    if not terrain.is_walkable(tx, ty):
        return True
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            if terrain.can_step(tx + dx, ty + dy, tx, ty):
                return False
    return True


__all__ = ["hunt_point_refused"]
