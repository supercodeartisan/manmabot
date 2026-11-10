"""Walk goal for one member: side line, corridor trail, or standing grid.

The leader tile comes from this tick's memory pose. Slots are local.
While the leader is moving, the side line comes first. Seat 0 stands on
the leader's right; the next seat stands on the left. A trail tile is
used only when that side has no free tile. A stopped leader uses a 5×5
grid for up to five people and a 7×7 grid for more. The leader's own
tile is never a slot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from .follow import unit8
from .tactics._grid import Tile, cheb, walkable

# Same-map teleport. A jump this far drops the sticky slot.
_JUMP_TILES = 6
# Keep the previous side tile only while it is still the ideal. A one-tile
# leader step moves the slot immediately.
_ARRIVE = 0


@dataclass(frozen=True)
class FormationGoal:
    kind: str  # side | trail | stand | none
    tile: Optional[Tile]
    reason: str


def right_of(forward: tuple[int, int]) -> tuple[int, int]:
    """90° clockwise from ``forward`` (x right, y down)."""
    fx, fy = unit8(forward)
    if fx == 0 and fy == 0:
        return (1, 0)
    return (-fy, fx)


def primary_lateral(seat: int) -> int:
    """+1, -1, +2, -2, … for seats 0, 1, 2, 3, …"""
    n = max(0, int(seat))
    mag = n // 2 + 1
    return mag if n % 2 == 0 else -mag


def stand_radius(followers: int) -> int:
    """2 → 5×5 for up to five people. 3 → 7×7 when there are more."""
    return 2 if int(followers) <= 5 else 3


def choose_formation_goal(
    leader: Optional[Tile],
    *,
    forward: Optional[tuple[int, int]],
    seat: Optional[int],
    followers: int,
    stopped: bool,
    trail_tile: Optional[Tile],
    terrain: Any = None,
    occupied: Optional[set[Tile]] = None,
    previous: Optional[Tile] = None,
    previous_leader: Optional[Tile] = None,
) -> FormationGoal:
    """One absolute navigation tile, or ``none`` when no legal slot exists."""
    if leader is None:
        return FormationGoal("none", None, "no_leader")
    leader_t = (int(leader[0]), int(leader[1]))
    blocked = {(int(x), int(y)) for x, y in (occupied or set())}
    blocked.add(leader_t)
    sticky = previous
    if (
        sticky is not None
        and previous_leader is not None
        and cheb(previous_leader, leader_t) > _JUMP_TILES
    ):
        sticky = None
    count = max(1, int(followers))
    seat_i = 0 if seat is None else max(0, int(seat))

    if stopped:
        tile = _stand_tile(
            leader_t, seat_i, count, terrain, blocked, sticky
        )
        if tile is None:
            return FormationGoal("stand", None, "stand_full")
        return FormationGoal("stand", tile, f"stand_r{stand_radius(count)}")

    tile = _side_tile(
        leader_t,
        forward,
        seat_i,
        count,
        terrain,
        blocked,
        sticky,
    )
    if tile is not None:
        return FormationGoal("side", tile, f"side{primary_lateral(seat_i):+d}")

    if trail_tile is not None:
        trail = (int(trail_tile[0]), int(trail_tile[1]))
        if trail != leader_t and _free(terrain, trail, blocked):
            return FormationGoal("trail", trail, f"trail_seat{seat_i}")
    return FormationGoal("side", None, "side_blocked")


def _side_offsets(seat: int, followers: int) -> list[tuple[int, int]]:
    """Lateral, longitudinal offsets for this seat, nearest first."""
    lat = primary_lateral(seat)
    owned = {primary_lateral(i) for i in range(max(1, followers))}
    step = 1 if lat > 0 else -1
    candidates: list[tuple[int, int]] = [(lat, 0), (lat, 1), (lat, -1)]
    extra = step
    while abs(extra) <= abs(lat) + 3:
        if extra not in owned:
            candidates.append((extra, 0))
        extra += step
    return candidates


def _facing(forward: Optional[tuple[int, int]]) -> tuple[int, int]:
    facing = unit8(forward)
    return facing if facing != (0, 0) else (0, -1)


def _side_tile(
    leader: Tile,
    forward: Optional[tuple[int, int]],
    seat: int,
    followers: int,
    terrain: Any,
    blocked: set[Tile],
    previous: Optional[Tile],
) -> Optional[Tile]:
    facing = _facing(forward)
    candidates = _side_offsets(seat, followers)
    ideal = _offset_tile(leader, facing, candidates[0][0], candidates[0][1])
    if (
        previous is not None
        and previous not in blocked
        and _free(terrain, previous, blocked)
        and cheb(previous, ideal) <= _ARRIVE
    ):
        return previous
    for lat_i, long_i in candidates:
        tile = _offset_tile(leader, facing, lat_i, long_i)
        if tile in blocked or not _corridor_free(leader, facing, lat_i, long_i, terrain, blocked):
            continue
        return tile
    return None


def _offset_tile(
    leader: Tile,
    facing: tuple[int, int],
    lateral: int,
    longitudinal: int,
) -> Tile:
    fx, fy = facing
    rx, ry = right_of(facing)
    return (
        int(leader[0]) + rx * int(lateral) + fx * int(longitudinal),
        int(leader[1]) + ry * int(lateral) + fy * int(longitudinal),
    )


def _corridor_free(
    leader: Tile,
    facing: tuple[int, int],
    lateral: int,
    longitudinal: int,
    terrain: Any,
    blocked: set[Tile],
) -> bool:
    """Every step from the leader to the slot is a free tile."""
    goal = _offset_tile(leader, facing, lateral, longitudinal)
    if cheb(leader, goal) <= 1:
        return _free(terrain, goal, blocked)
    if terrain is None and not blocked:
        return True
    rx, ry = right_of(facing)
    fx, fy = facing
    cx, cy = int(leader[0]), int(leader[1])
    steps = abs(int(lateral)) + abs(int(longitudinal))
    sx = 0 if lateral == 0 else (1 if lateral > 0 else -1)
    lx = 0 if longitudinal == 0 else (1 if longitudinal > 0 else -1)
    for i in range(1, abs(int(lateral)) + 1):
        cx = int(leader[0]) + rx * sx * i
        cy = int(leader[1]) + ry * sx * i
        if not _free(terrain, (cx, cy), blocked):
            return False
    base_x, base_y = cx, cy
    for i in range(1, abs(int(longitudinal)) + 1):
        tx = base_x + fx * lx * i
        ty = base_y + fy * lx * i
        if not _free(terrain, (tx, ty), blocked):
            return False
    return steps > 0


def _stand_tile(
    leader: Tile,
    seat: int,
    followers: int,
    terrain: Any,
    blocked: set[Tile],
    previous: Optional[Tile],
) -> Optional[Tile]:
    radius = stand_radius(followers)
    slots = _grid_slots(leader, radius, terrain, blocked)
    if seat < len(slots):
        chosen = slots[seat]
        if (
            previous is not None
            and previous == chosen
        ):
            return previous
        return chosen
    return None


def _grid_slots(
    leader: Tile,
    radius: int,
    terrain: Any,
    blocked: set[Tile],
) -> list[Tile]:
    lx, ly = leader
    found: list[Tile] = []
    r = max(1, int(radius))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if max(abs(dx), abs(dy)) > r or (dx == 0 and dy == 0):
                continue
            tile = (lx + dx, ly + dy)
            if tile in blocked or not _free(terrain, tile, blocked):
                continue
            if not _reachable(leader, tile, terrain, blocked):
                continue
            found.append(tile)
    found.sort(key=lambda t: (math.atan2(t[1] - ly, t[0] - lx), cheb(t, leader)))
    return found


def _reachable(start: Tile, goal: Tile, terrain: Any, blocked: set[Tile]) -> bool:
    limit = cheb(start, goal)
    if limit <= 1:
        return True
    seen = {start}
    fringe = [start]
    for _ in range(limit):
        nxt: list[Tile] = []
        for cx, cy in fringe:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    tile = (cx + dx, cy + dy)
                    if tile in seen or tile in blocked:
                        continue
                    if terrain is not None and not walkable(terrain, tile[0], tile[1]):
                        continue
                    if tile == goal:
                        return True
                    seen.add(tile)
                    nxt.append(tile)
        fringe = nxt
        if not fringe:
            return False
    return False


def _free(terrain: Any, tile: Tile, blocked: set[Tile]) -> bool:
    if tile in blocked:
        return False
    if terrain is None:
        return True
    return walkable(terrain, tile[0], tile[1])


__all__ = [
    "FormationGoal",
    "choose_formation_goal",
    "primary_lateral",
    "right_of",
    "stand_radius",
]
