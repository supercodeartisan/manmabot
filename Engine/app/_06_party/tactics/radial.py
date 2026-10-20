"""Open-field formation: fan slots around the leader within ``radius`` tiles.

``fan_slots`` gives one offset per member, spread over an arc behind (or in
front of) the leader's move direction; with no direction it is a full ring.
``resolve_slot`` moves a slot that is blocked or behind an obstacle to the
nearest tile the leader can see. ``pace_for_slot`` says whether the member
should hurry to its slot, keep pace, or wait for the leader to pass.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from ._grid import Tile, cheb, sign, walkable

HURRY = "hurry"
KEEP = "keep"
WAIT = "wait"


def _arc_offset(angle: float, radius: int) -> Tile:
    return (int(round(radius * math.cos(angle))), int(round(radius * math.sin(angle))))


def fan_slots(
    count: int,
    move_dir: Optional[Tile] = None,
    *,
    radius: int = 3,
    spread_deg: float = 150.0,
    facing: str = "rear",
) -> list[Tile]:
    n = max(0, int(count))
    if n == 0:
        return []
    r = max(1, int(radius))
    has_dir = move_dir is not None and tuple(move_dir) != (0, 0)
    if has_dir:
        center = math.atan2(float(move_dir[1]), float(move_dir[0]))
        if facing == "rear":
            center += math.pi
        spread = math.radians(max(0.0, min(360.0, float(spread_deg))))
        angles = [
            center if n == 1 else center + spread * (i / (n - 1) - 0.5)
            for i in range(n)
        ]
    else:
        angles = [2.0 * math.pi * i / n for i in range(n)]

    used: set[Tile] = set()
    out: list[Tile] = []
    nudge = math.radians(360.0 / (8 * r))
    for base in angles:
        off = _arc_offset(base, r)
        k = 1
        while (off in used or off == (0, 0)) and k <= 16:
            step = nudge * ((k + 1) // 2) * (1 if k % 2 else -1)
            off = _arc_offset(base + step, r)
            k += 1
        used.add(off)
        out.append(off)
    return out


def clear_line(terrain: Any, a: Tile, b: Tile) -> bool:
    """Bresenham walk from ``a`` to ``b`` over walkable tiles.

    A diagonal step needs at least one open shoulder, matching movement.
    ``a`` itself is not tested.
    """
    x0, y0 = int(a[0]), int(a[1])
    x1, y1 = int(b[0]), int(b[1])
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = sign(x1 - x0)
    sy = sign(y1 - y0)
    err = dx + dy
    x, y = x0, y0
    while (x, y) != (x1, y1):
        e2 = 2 * err
        nx, ny = x, y
        if e2 >= dy:
            err += dy
            nx += sx
        if e2 <= dx:
            err += dx
            ny += sy
        if not walkable(terrain, nx, ny):
            return False
        if nx != x and ny != y:
            if not (walkable(terrain, nx, y) or walkable(terrain, x, ny)):
                return False
        x, y = nx, ny
    return True


def resolve_slot(
    terrain: Any,
    leader: Tile,
    offset: Tile,
    *,
    radius: int = 3,
    occupied: Iterable[Tile] = (),
) -> Optional[Tile]:
    lx, ly = int(leader[0]), int(leader[1])
    r = max(1, int(radius))
    taken = {(int(x), int(y)) for x, y in occupied}
    ideal = (lx + int(offset[0]), ly + int(offset[1]))

    def ok(t: Tile) -> bool:
        return (
            t != (lx, ly)
            and t not in taken
            and walkable(terrain, t[0], t[1])
            and clear_line(terrain, (lx, ly), t)
        )

    if ok(ideal):
        return ideal
    candidates = [
        (lx + dx, ly + dy)
        for dy in range(-r, r + 1)
        for dx in range(-r, r + 1)
        if (dx, dy) != (0, 0)
    ]
    candidates.sort(
        key=lambda t: (
            cheb(t, ideal),
            (t[0] - ideal[0]) ** 2 + (t[1] - ideal[1]) ** 2,
            t[1],
            t[0],
        )
    )
    for t in candidates:
        if ok(t):
            return t
    return None


def pace_for_slot(
    member: Tile,
    slot: Tile,
    leader: Tile,
    move_dir: Optional[Tile] = None,
    *,
    tolerance: int = 1,
) -> str:
    if cheb(member, slot) <= max(0, int(tolerance)):
        return KEEP
    if move_dir is not None and tuple(move_dir) != (0, 0):
        mdx, mdy = int(move_dir[0]), int(move_dir[1])
        ahead = (member[0] - leader[0]) * mdx + (member[1] - leader[1]) * mdy
        slot_side = (slot[0] - leader[0]) * mdx + (slot[1] - leader[1]) * mdy
        if ahead > 0 and slot_side <= 0:
            return WAIT
    return HURRY


__all__ = [
    "HURRY",
    "KEEP",
    "WAIT",
    "clear_line",
    "fan_slots",
    "pace_for_slot",
    "resolve_slot",
]
