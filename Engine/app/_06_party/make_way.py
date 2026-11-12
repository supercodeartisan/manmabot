"""Narrow passage: a blocked leader asks the members beside him to step off his line.

The leader sees the guide line and knows it has no click. A member only sees
the leader standing. So the leader sends ``make_way`` with its tile and the
next guide tiles, and a member within ``MAKE_WAY_RADIUS`` clicks one open tile
off that line, then stands ``MAKE_WAY_HOLD_S`` before it follows again.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Iterable, Optional, Sequence

Tile = tuple[int, int]

MAKE_WAY = "make_way"
# Leader travel with no safe click this long asks for room.
MAKE_WAY_BLOCKED_S = 3.0
# The leader does not ask again sooner than this.
MAKE_WAY_RESEND_S = 5.0
# After the step-off walk, the member stands this long before following.
MAKE_WAY_HOLD_S = 2.0
# Walk time allowed per tile of the step-off click before the stand starts.
MAKE_WAY_WALK_S_PER_TILE = 0.7
# A request older than this on the member is ignored.
MAKE_WAY_FRESH_S = 2.0
# Members within this many tiles of the leader step off.
MAKE_WAY_RADIUS = 3
# The step-off click stays within this many tiles of the member.
MAKE_WAY_STEP_TILES = 3
# Guide tiles the leader sends ahead of itself.
MAKE_WAY_GUIDE_TILES = 6
# A party click ring closes a player's eight neighbors, so a member clears
# the line only from this many tiles away.
MAKE_WAY_CLEAR_GAP = 2
# Travel notes that mean the leader has no click on its guide.
BLOCKED_NOTES = frozenset({"window has no safe click", "no click on the guide"})


def _cheb(a: Tile, b: Tile) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def _unit(dx: int, dy: int) -> Tile:
    return (0 if dx == 0 else (1 if dx > 0 else -1), 0 if dy == 0 else (1 if dy > 0 else -1))


class LeaderBlockWatch:
    """Says when a leader blocked for ``MAKE_WAY_BLOCKED_S`` should ask again."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._since: Optional[float] = None
        self._sent_at = float("-inf")

    def reset(self) -> None:
        self._since = None

    def note(self, blocked: bool) -> bool:
        now = self._clock()
        if not blocked:
            self._since = None
            return False
        if self._since is None:
            self._since = now
            return False
        if now - self._since < MAKE_WAY_BLOCKED_S:
            return False
        if now - self._sent_at < MAKE_WAY_RESEND_S:
            return False
        self._sent_at = now
        return True


def guide_ahead(
    guide: Iterable[Any],
    start: Tile,
    limit: int = MAKE_WAY_GUIDE_TILES,
) -> list[Tile]:
    """Guide tiles after ``start``, at most ``limit``."""
    tiles: list[Tile] = []
    for raw in guide or ():
        try:
            tiles.append((int(raw[0]), int(raw[1])))
        except (TypeError, ValueError, IndexError):
            continue
    sx, sy = int(start[0]), int(start[1])
    try:
        begin = tiles.index((sx, sy)) + 1
    except ValueError:
        begin = 0
    return [t for t in tiles[begin:] if t != (sx, sy)][: max(0, int(limit))]


def make_way_message(
    *,
    map_id: Optional[int],
    x: int,
    y: int,
    guide: Sequence[Tile],
) -> dict[str, Any]:
    return {
        "type": MAKE_WAY,
        "from": "leader",
        "id": uuid.uuid4().hex[:8],
        "map_id": map_id,
        "x": int(x),
        "y": int(y),
        "guide": [[int(t[0]), int(t[1])] for t in guide],
    }


def parse_make_way(body: Any) -> Optional[tuple[Optional[int], Tile, list[Tile]]]:
    """``(map_id, leader tile, guide)`` from a request, or None when unusable."""
    if not isinstance(body, dict):
        return None
    try:
        leader = (int(body["x"]), int(body["y"]))
    except (KeyError, TypeError, ValueError):
        return None
    try:
        map_id = None if body.get("map_id") is None else int(body["map_id"])
    except (TypeError, ValueError):
        map_id = None
    guide: list[Tile] = []
    for raw in body.get("guide") or []:
        try:
            guide.append((int(raw[0]), int(raw[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return map_id, leader, guide[:MAKE_WAY_GUIDE_TILES]


def _passes(start: Tile, end: Tile, tile: Tile) -> bool:
    """True when the straight walk from ``start`` to ``end`` crosses ``tile``."""
    sx, sy = int(start[0]), int(start[1])
    ex, ey = int(end[0]), int(end[1])
    n = max(abs(ex - sx), abs(ey - sy))
    for i in range(1, n + 1):
        x = sx + round((ex - sx) * i / n)
        y = sy + round((ey - sy) * i / n)
        if (x, y) == (int(tile[0]), int(tile[1])):
            return True
    return False


def line_gap(tile: Tile, line: Iterable[Tile]) -> int:
    gaps = [_cheb(tile, t) for t in line]
    return min(gaps) if gaps else MAKE_WAY_CLEAR_GAP


def plan_make_way(
    member: Tile,
    leader: Tile,
    guide: Sequence[Tile],
    *,
    open_tile: Callable[[Tile], bool],
    step_tiles: int = MAKE_WAY_STEP_TILES,
) -> Optional[Tile]:
    """One open tile off the leader's line, or None when the member is not in the way.

    The line is the leader tile and its guide. A tile ``MAKE_WAY_CLEAR_GAP``
    from every line tile is preferred, then one tile off it. Behind the leader
    beats beside it, and beside beats ahead. Nearer the member breaks ties.
    With no tile off the line, a member behind the leader backs up along the
    heading, and a member ahead of him walks on ahead.
    """
    mx, my = int(member[0]), int(member[1])
    lx, ly = int(leader[0]), int(leader[1])
    line = [(lx, ly)] + [(int(t[0]), int(t[1])) for t in guide]
    if line_gap((mx, my), line) >= MAKE_WAY_CLEAR_GAP:
        return None
    heading = _unit(guide[0][0] - lx, guide[0][1] - ly) if guide else (0, 0)
    on_line = set(line)
    r = max(1, int(step_tiles))

    def side(tile: Tile) -> int:
        if heading == (0, 0):
            return 1
        dot = (tile[0] - lx) * heading[0] + (tile[1] - ly) * heading[1]
        return 0 if dot < 0 else (1 if dot == 0 else 2)

    best: Optional[Tile] = None
    best_key: Optional[tuple[int, int, int, int, int]] = None
    for y in range(my - r, my + r + 1):
        for x in range(mx - r, mx + r + 1):
            tile = (x, y)
            if tile == (mx, my) or tile in on_line:
                continue
            gap = min(line_gap(tile, line), MAKE_WAY_CLEAR_GAP)
            if gap < 1 or _passes((mx, my), tile, (lx, ly)) or not open_tile(tile):
                continue
            key = (-gap, side(tile), _cheb((mx, my), tile), y, x)
            if best_key is None or key < best_key:
                best_key = key
                best = tile
    if best is not None:
        return best
    if heading == (0, 0):
        return None
    # Ahead of the leader there is no backing up through him: walk on ahead.
    sign = 1 if side((mx, my)) == 2 else -1
    for k in range(r, 0, -1):
        tile = (mx + sign * heading[0] * k, my + sign * heading[1] * k)
        if not _passes((mx, my), tile, (lx, ly)) and open_tile(tile):
            return tile
    return None


__all__ = [
    "BLOCKED_NOTES",
    "LeaderBlockWatch",
    "MAKE_WAY",
    "MAKE_WAY_BLOCKED_S",
    "MAKE_WAY_FRESH_S",
    "MAKE_WAY_GUIDE_TILES",
    "MAKE_WAY_HOLD_S",
    "MAKE_WAY_RADIUS",
    "MAKE_WAY_RESEND_S",
    "MAKE_WAY_STEP_TILES",
    "MAKE_WAY_WALK_S_PER_TILE",
    "guide_ahead",
    "line_gap",
    "make_way_message",
    "parse_make_way",
    "plan_make_way",
]
