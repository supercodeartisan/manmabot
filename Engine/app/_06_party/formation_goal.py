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
# A new travel direction replaces the formation heading after this many tiles.
_HEADING_CONFIRM_TILES = 2


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


def advance_heading(
    heading: Optional[tuple[int, int]],
    pending_dir: Optional[tuple[int, int]],
    pending_tiles: int,
    step: Optional[tuple[int, int]],
) -> tuple[Optional[tuple[int, int]], Optional[tuple[int, int]], int, bool]:
    """Keep the formation heading until a new direction lasts two tiles.

    The first real step sets the heading. One strafe or backstep does not.
    Returns heading, pending direction, pending tiles, and whether the
    heading was committed on this step.
    """
    direction = unit8(step)
    if direction == (0, 0):
        return heading, pending_dir, int(pending_tiles), False
    current = unit8(heading)
    if current == (0, 0):
        return direction, None, 0, True
    if direction == current:
        return current, None, 0, False
    dist = max(abs(int(step[0])), abs(int(step[1]))) if step is not None else 1
    if pending_dir == direction:
        run = int(pending_tiles) + max(1, dist)
    else:
        run = max(1, dist)
    if run >= _HEADING_CONFIRM_TILES:
        return direction, None, 0, True
    return current, direction, run, False


def nearer_lateral(
    leader: Tile,
    heading: tuple[int, int],
    lateral: int,
    prefer: Tile,
) -> int:
    """Same distance on the side closer to ``prefer``. A tie keeps the sign."""
    mag = abs(int(lateral)) or 1
    current = mag if int(lateral) >= 0 else -mag
    plus = _offset_tile(leader, _facing(heading), mag, 0)
    minus = _offset_tile(leader, _facing(heading), -mag, 0)
    if cheb(prefer, plus) == cheb(prefer, minus):
        return current
    if cheb(prefer, plus) < cheb(prefer, minus):
        return mag
    return -mag


def signed_lateral(
    leader: Tile,
    heading: tuple[int, int],
    tile: Tile,
) -> Optional[int]:
    """Lateral steps of ``tile`` in ``heading``'s frame. None when it is not a side slot."""
    fx, fy = _facing(heading)
    rx, ry = right_of((fx, fy))
    dx = int(tile[0]) - int(leader[0])
    dy = int(tile[1]) - int(leader[1])
    lat = dx * rx + dy * ry
    along = dx * fx + dy * fy
    if lat == 0 or abs(along) > abs(lat):
        return None
    return int(lat)


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
    lateral: Optional[int] = None,
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

    if stopped and lateral is not None:
        held = _held_side_tile(
            leader_t,
            forward,
            int(lateral),
            count,
            terrain,
            blocked,
            sticky,
        )
        if held is not None:
            return held
        return FormationGoal("stand", None, "stand_full")

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
        lateral=lateral,
    )
    if tile is not None:
        return FormationGoal("side", tile, f"side{primary_lateral(seat_i):+d}")

    if trail_tile is not None:
        trail = (int(trail_tile[0]), int(trail_tile[1]))
        if trail != leader_t and _free(terrain, trail, blocked):
            return FormationGoal("trail", trail, f"trail_seat{seat_i}")
    return FormationGoal("side", None, "side_blocked")


def _side_offsets(
    seat: int,
    followers: int,
    lateral: Optional[int] = None,
) -> list[tuple[int, int]]:
    """Lateral, longitudinal offsets for this seat, nearest first."""
    lat = primary_lateral(seat) if lateral is None else int(lateral)
    if lat == 0:
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
    lateral: Optional[int] = None,
) -> Optional[Tile]:
    facing = _facing(forward)
    candidates = _side_offsets(seat, followers, lateral)
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


def _held_side_tile(
    leader: Tile,
    forward: Optional[tuple[int, int]],
    lateral: int,
    followers: int,
    terrain: Any,
    blocked: set[Tile],
    prefer: Optional[Tile],
) -> Optional[FormationGoal]:
    """Keep the latched side inside the stand box. A bad tile takes the nearest."""
    facing = _facing(forward)
    radius = stand_radius(followers)
    rebased = _offset_tile(leader, facing, int(lateral), 0)
    if (
        cheb(rebased, leader) <= radius
        and rebased not in blocked
        and _free(terrain, rebased, blocked)
    ):
        return FormationGoal("side", rebased, f"hold{int(lateral):+d}")
    nearest = _nearest_stand_tile(leader, radius, terrain, blocked, prefer)
    if nearest is None:
        return None
    return FormationGoal("side", nearest, "hold_near")


def _nearest_stand_tile(
    leader: Tile,
    radius: int,
    terrain: Any,
    blocked: set[Tile],
    prefer: Optional[Tile],
) -> Optional[Tile]:
    lx, ly = int(leader[0]), int(leader[1])
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
    if not found:
        return None
    if prefer is None:
        return found[0]
    return min(found, key=lambda tile: (cheb(tile, prefer), cheb(tile, leader)))


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


def closing_slot(
    *,
    held: bool,
    previous: Optional[Tile],
    previous_kind: str,
    chosen: FormationGoal,
    origin: Optional[Tile],
    hop: Optional[Tile],
    leader: Optional[Tile],
) -> FormationGoal:
    """Keep the previous walk slot when the new hop steps away from the leader.

    A real stand (``held``) keeps the new grid cell. No previous slot, or a
    hop that does not move farther from the leader, keeps ``chosen``.
    """
    if held or previous is None or chosen.tile is None or hop is None:
        return chosen
    if origin is None or leader is None:
        return chosen
    prev = (int(previous[0]), int(previous[1]))
    if prev == (int(chosen.tile[0]), int(chosen.tile[1])):
        return chosen
    if cheb(hop, leader) > cheb(origin, leader):
        kind = previous_kind if previous_kind in ("side", "trail", "stand") else "side"
        return FormationGoal(kind, prev, "keep_closing")
    return chosen


def _free(terrain: Any, tile: Tile, blocked: set[Tile]) -> bool:
    if tile in blocked:
        return False
    if terrain is None:
        return True
    return walkable(terrain, tile[0], tile[1])


__all__ = [
    "FormationGoal",
    "advance_heading",
    "choose_formation_goal",
    "closing_slot",
    "nearer_lateral",
    "primary_lateral",
    "right_of",
    "signed_lateral",
    "stand_radius",
]
