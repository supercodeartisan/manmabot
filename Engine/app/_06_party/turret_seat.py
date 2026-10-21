"""Turret seats: one radial slot per roster member around the anchored leader.

Uses the ``tactics.radial`` fan (full ring when the leader is not walking) so
members spread around the leader instead of stacking on one side. A blocked or
out-of-sight slot moves to the nearest tile the leader can see.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .tactics.radial import fan_slots, resolve_slot

Tile = tuple[int, int]

SEAT_RADIUS = 2


def seat_radius(half_w: int, half_h: int) -> int:
    """Ring radius that stays inside the turret yard."""
    return max(1, min(SEAT_RADIUS, int(half_w), int(half_h)))


def turret_seat(
    terrain: Any,
    leader: Tile,
    index: Optional[int],
    count: int,
    *,
    radius: int = SEAT_RADIUS,
    avoid: Iterable[Tile] = (),
) -> Optional[Tile]:
    """Absolute seat tile for roster ``index`` of ``count`` members, or None."""
    if index is None or terrain is None or leader is None:
        return None
    n = max(int(count), int(index) + 1, 1)
    offsets = fan_slots(n, None, radius=max(1, int(radius)))
    if not offsets:
        return None
    offset = offsets[int(index) % len(offsets)]
    return resolve_slot(
        terrain,
        (int(leader[0]), int(leader[1])),
        offset,
        radius=max(1, int(radius)),
        occupied=avoid,
    )


__all__ = ["SEAT_RADIUS", "seat_radius", "turret_seat"]
