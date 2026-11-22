"""Shared march: the leader's committed walk, and each member's place on it.

Tiles are absolute navigation tiles, the same space as ``world_origin`` and
``blackboard.nav_path``. ``ActionIntent.destination`` is a screen click and
is never put on the wire.

``MARCH_GAP_TILES`` and the two-tile look-ahead are assumptions. They are
not measured click-to-pose delay. A click that was refused, a click that is
waiting for the next pose, and a body that has actually stopped stay
separate: progress is recorded only from an observed tile.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .follow import unit8
from .formation import TRAIL_SPACING
from .formation_goal import advance_heading, choose_formation_goal, right_of
from .leader_pace import PACE_GAP_TILES
from .tactics._grid import Tile, cheb, walkable

PATH_TYPE = "formation_path"
# Same number the chebyshev pace already uses. Not a measured recovery time.
MARCH_GAP_TILES = int(PACE_GAP_TILES)
# How far ahead of a still leader the side slot is placed, in path steps.
MARCH_LOOKAHEAD = 2
# Tiles of the committed path sent on one frame.
MARCH_WINDOW = 12
# Past this much gap the front stops. A smaller excess only shortens the slot.
MARCH_HOLD_EXCESS = 2
# Extra tiles past a seat's normal place. Not a measured pose delay.
# A mage 8 behind the leader, plus this 2, holds the front at that sum.
MARCH_ALLOWED_LAG = 2
# How many tiles behind the leader a frame still carries.
MARCH_TRAIL = 12
# Steps of the shared path inspected for a one-tile passage.
MARCH_NARROW_LOOK = 3

_MAX_TILES = 32


@dataclass(frozen=True)
class MarchPath:
    """One accepted leader path.

    ``tiles[0]`` is full-path index ``base``. ``cursor`` is the leader's
    index inside this message, so the leader's full index is ``base + cursor``.
    ``door``, ``exit_at``, and ``admit`` are the leader's passage turn.
    """

    session: str
    rev: int
    seq: int
    map_id: int
    cursor: int
    tiles: tuple[Tile, ...]
    clear: bool
    base: int = 0
    door: Optional[int] = None
    exit_at: Optional[int] = None
    admit: Optional[int] = None


@dataclass(frozen=True)
class MarchMove:
    """What this member should do with the current path.

    ``owns`` is true while this session and map still accept the shared path.
    A missing click this tick does not clear that. ``plan`` is the click or
    idle for this tick; it may be an idle retry while ``owns`` stays true.
    Ordinary leader follow runs only when ``owns`` is false.

    ``advance`` is the policy bit: the current slot is still open, so
    ``stop_tiles`` may not hold. It is not ``slot_dist``.

    ``reason`` tells the walk branch why this tick stopped:
    ``pace_wait`` and ``door_wait`` are normal holds, ``in_transit`` is a
    click already out, ``retry`` / ``no_path`` keep the goal without a new
    click, ``click_rejected`` drops that hop. ``go`` is a hop that already
    fits the arrival limit.
    """

    advance: bool
    plan: Any
    goal: Optional[Tile]
    rev: int
    reason: str = ""
    owns: bool = False


def march_message(
    *,
    map_id: int,
    rev: int,
    seq: int,
    cursor: int,
    tiles: Sequence[Tile],
    clear: bool = False,
    base: int = 0,
    door: Optional[int] = None,
    exit_at: Optional[int] = None,
    admit: Optional[int] = None,
) -> dict[str, Any]:
    """Leader frame. ``session`` is stamped later by ``publish_body``.

    ``base`` is the full-path index of ``tiles[0]``. ``cursor`` is the
    leader's index inside ``tiles``. ``door`` / ``exit`` / ``admit`` are
    full-path indexes and the seat allowed to enter, or omitted on open ground.
    """
    body: dict[str, Any] = {
        "type": PATH_TYPE,
        "from": "leader",
        "map_id": int(map_id),
        "rev": int(rev),
        "seq": int(seq),
        "base": int(base),
        "cursor": int(cursor),
        "tiles": [[int(t[0]), int(t[1])] for t in tiles],
        "clear": bool(clear),
    }
    if door is not None:
        body["door"] = int(door)
    if exit_at is not None:
        body["exit"] = int(exit_at)
    if admit is not None:
        body["admit"] = int(admit)
    return body


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_march(body: Any) -> Optional[MarchPath]:
    """A usable path, or None. A clear frame is usable and ends the march."""
    if not isinstance(body, dict):
        return None
    if str(body.get("type") or "") != PATH_TYPE:
        return None
    try:
        rev = int(body.get("rev"))
        seq = int(body.get("seq"))
        map_id = int(body.get("map_id"))
        cursor = int(body.get("cursor") or 0)
        base = int(body.get("base") or 0)
    except (TypeError, ValueError):
        return None
    door = _optional_int(body.get("door"))
    exit_at = _optional_int(body.get("exit"))
    admit = _optional_int(body.get("admit"))
    if body.get("door") is not None and door is None:
        return None
    if body.get("exit") is not None and exit_at is None:
        return None
    if body.get("admit") is not None and admit is None:
        return None
    clear = bool(body.get("clear"))
    raw = body.get("tiles")
    tiles: list[Tile] = []
    if isinstance(raw, list):
        if len(raw) > _MAX_TILES:
            return None
        for item in raw:
            try:
                tiles.append((int(item[0]), int(item[1])))
            except (TypeError, ValueError, IndexError):
                return None
    if not clear and not tiles:
        return None
    if tiles:
        cursor = max(0, min(cursor, len(tiles) - 1))
    else:
        cursor = 0
    return MarchPath(
        session=str(body.get("session") or ""),
        rev=rev,
        seq=seq,
        map_id=map_id,
        cursor=cursor,
        tiles=tuple(tiles),
        clear=clear,
        base=base,
        door=door,
        exit_at=exit_at,
        admit=admit,
    )


def accept_march(
    body: Any,
    *,
    local_map_id: Optional[int],
    session: str,
) -> Optional[MarchPath]:
    """The path this member may walk, or None to keep ordinary follow.

    Another map, a clear, a missing session, or a session that is not the
    one this client is following is ignored. Stale seq is filtered before
    this, by ``MemberOrders``.
    """
    path = body if isinstance(body, MarchPath) else parse_march(body)
    if path is None or path.clear:
        return None
    if not path.session or path.session != str(session or ""):
        return None
    if local_map_id is None or int(path.map_id) != int(local_map_id):
        return None
    return path


def progress_index(
    tiles: Sequence[Tile],
    tile: Tile,
    *,
    previous: Optional[int] = None,
    near: int = 1,
) -> Optional[int]:
    """Index of ``tile`` on the polyline.

    A fold such as a U-turn has two tiles a short Chebyshev apart and a long
    walk apart. The index may move forward only by about that Chebyshev, so
    the far arm is not treated as progress. The earliest matching index wins
    when several tiles are equally close.
    """
    if not tiles:
        return None
    here = (int(tile[0]), int(tile[1]))
    limit = max(0, int(near))
    hits = [
        i
        for i, point in enumerate(tiles)
        if cheb(point, here) <= limit
    ]
    if not hits:
        return None
    if previous is None:
        return min(hits, key=lambda i: (cheb(tiles[i], here), i))
    prev = int(previous)
    if prev < 0 or prev >= len(tiles):
        return min(hits, key=lambda i: (cheb(tiles[i], here), i))
    budget = cheb(tiles[prev], here) + limit
    forward = [i for i in hits if prev <= i <= prev + budget]
    if forward:
        return min(forward, key=lambda i: (cheb(tiles[i], here), i))
    behind = [i for i in hits if i <= prev]
    return max(behind) if behind else None


def leader_path_gap(
    guide: Sequence[Tile],
    here: Tile,
    followers: Sequence[Any],
) -> Optional[int]:
    """How far the leader is ahead of the rearmost member still on this path.

    A follower on another map, or whose tile is not on the polyline, is left
    out. The party does not wait for them.
    """
    if not guide:
        return None
    cursor = progress_index(guide, here, previous=None, near=1)
    if cursor is None:
        cursor = 0
    indexes: list[Optional[int]] = []
    for follower in followers:
        if not isinstance(follower, tuple) or len(follower) != 2:
            indexes.append(None)
            continue
        indexes.append(
            progress_index(guide, (int(follower[0]), int(follower[1])), previous=None, near=1)
        )
    return line_gap(cursor, indexes)


def line_gap(head: int, progresses: Sequence[Optional[int]]) -> Optional[int]:
    """How far ``head`` is ahead of the rearmost known index.

    ``None`` entries are other maps, stale reports, or a dropped connection.
    They do not hold the line.
    """
    known = [int(p) for p in progresses if p is not None]
    if not known:
        return None
    return int(head) - min(known)


def pace_aim(
    desired: int,
    me_progress: Optional[int],
    tail: Optional[int],
) -> Optional[int]:
    """Index to aim at, or None when this body is too far ahead of ``tail``.

    ``tail`` is the rearmost other member. The rear member's own progress is
    not a reason to stop, so a healer who just finished can walk immediately.
    One or two steps of excess shorten the aim. More than that holds.
    ``MARCH_GAP_TILES`` is the same assumption as the leader's chebyshev pace,
    not a measured pose delay.
    """
    if me_progress is None or tail is None:
        return int(desired)
    excess = int(me_progress) - int(tail) - MARCH_GAP_TILES
    if excess <= 0:
        return int(desired)
    if excess > MARCH_HOLD_EXCESS:
        return None
    return min(int(desired), int(tail) + MARCH_GAP_TILES)


def seat_back(seat: int) -> int:
    """Tiles this seat normally stands behind the leader. The leader is 0."""
    return TRAIL_SPACING * (max(0, int(seat)) + 1)


def head_limit(rows: Sequence[tuple[int, int]]) -> Optional[int]:
    """Full-path index the front may reach once every click has landed.

    ``rows`` are ``(progress, seat_back)`` for members actually on this path.
    An empty list does not call ``min``; the caller keeps ordinary follow.
    ``MARCH_ALLOWED_LAG`` is an assumption, not a measured pose delay.
    """
    if not rows:
        return None
    return min(int(progress) + int(back) + MARCH_ALLOWED_LAG for progress, back in rows)


def clip_leader_hop(
    share: "MarchShare",
    hop: Optional[Tile],
    member_progress: Sequence[Optional[int]],
) -> Optional[Tile]:
    """Leader click tile after the arrival limit, or None when the click waits.

    No observed member means no limit: the existing walk continues.
    The leader's own seat offset is 0.
    """
    rows = [
        (int(progress), seat_back(seat))
        for seat, progress in enumerate(member_progress)
        if progress is not None
    ]
    limit = head_limit(rows)
    if limit is None or hop is None:
        return hop
    hop_full = share.index_of(hop)
    if hop_full is None:
        return hop
    nxt = aim_index(hop_full, share.cursor_full, 0, limit)
    if nxt is None:
        return None
    if int(nxt) >= int(hop_full):
        return hop
    return share.tile_at(int(nxt))


def aim_index(
    desired: int,
    me_progress: Optional[int],
    my_back: int,
    limit: Optional[int],
) -> Optional[int]:
    """Full index this click may land on, or None to hold.

    The limit is where the body will be when the click finishes, not where
    it is standing now. A result at or behind ``me_progress`` is a hold.
    """
    if limit is None:
        return int(desired)
    nxt = min(int(desired), int(limit) - int(my_back))
    if me_progress is not None and nxt <= int(me_progress):
        return None
    return nxt


class MarchShare:
    """Leader polyline plus the recent tiles ``nav_path`` no longer contains.

    ``nav_path`` is often rebuilt from the leader's current tile, so the
    frame's rear half comes from tiles this object has actually seen.
    A ``member_hello`` resends the current frame even when the client count
    does not change. Indexes stay stable: dropping old tiles moves ``base``,
    it does not renumber the mage standing at index 12.
    """

    def __init__(self) -> None:
        self.rev = 0
        self.seq = 0
        self.active = False
        self._full: list[Tile] = []
        self._origin = 0
        self._cursor = 0
        self._sig: Optional[tuple] = None
        self._last: Optional[dict[str, Any]] = None
        self._hello = False
        self._seen: dict[int, int] = {}

    def reset(self) -> None:
        self.rev = 0
        self.seq = 0
        self.active = False
        self._full = []
        self._origin = 0
        self._cursor = 0
        self._sig = None
        self._last = None
        self._hello = False
        self._seen = {}

    def note_hello(self) -> None:
        """A member_hello arrived. The next update repeats the current frame."""
        self._hello = True

    @property
    def cursor_full(self) -> int:
        return int(self._cursor)

    def index_of(self, tile: Tile) -> Optional[int]:
        """Full-path index of an observed tile, or None when it is not on the line."""
        if not self._full:
            return None
        local_prev = self._cursor - self._origin
        local = progress_index(self._full, tile, previous=local_prev, near=1)
        if local is None:
            return None
        return self._origin + int(local)

    def tile_at(self, full: int) -> Optional[Tile]:
        local = int(full) - self._origin
        if local < 0 or local >= len(self._full):
            return None
        return self._full[local]

    def update(
        self,
        *,
        map_id: Optional[int],
        here: Optional[Tile],
        guide: Sequence[Tile],
        traveling: bool,
        pace_idle: bool,
        cancel: bool,
        clients: int = 0,
        terrain: Any = None,
        seats: Sequence[Any] = (),
    ) -> Optional[dict[str, Any]]:
        """A frame to broadcast, or None when nothing changed.

        A pace idle keeps the path. Extending the same polyline keeps ``rev``.
        A future that leaves the polyline bumps ``rev``. ``clients`` is unused
        for resend: a replacement connection can keep the same count, so only
        ``note_hello`` repeats the frame.
        """
        del clients
        if cancel or map_id is None or here is None:
            return self._clear(map_id)
        forward = _tiles(guide)
        keep = bool(traveling or (pace_idle and self.active))
        if not keep or not forward:
            return self._clear(map_id)
        stood = (int(here[0]), int(here[1]))
        diverged = self._absorb(stood, forward)
        if diverged:
            self.rev += 1
            self._seen = {}
        if not self._full:
            return self._clear(map_id)
        self._trim()
        window, base, cursor = self._frame_window()
        if not window:
            return self._clear(map_id)
        door, exit_at, admit = choose_admission(
            window, base, cursor, terrain, self._seat_indexes(seats)
        )
        signature = (
            self.rev,
            base,
            cursor,
            window,
            door,
            exit_at,
            admit,
            int(map_id),
        )
        hello = self._hello
        self._hello = False
        if signature == self._sig and not hello:
            return None
        self.seq += 1
        self._sig = signature
        self.active = True
        body = march_message(
            map_id=int(map_id),
            rev=self.rev,
            seq=self.seq,
            cursor=cursor,
            tiles=window,
            clear=False,
            base=base,
            door=door,
            exit_at=exit_at,
            admit=admit,
        )
        self._last = body
        return body

    def _absorb(self, here: Tile, forward: Sequence[Tile]) -> bool:
        """Splice the observed tile onto the stored line. True when the future changed."""
        if not self._full:
            self._full = [here]
            self._origin = 0
            self._cursor = 0
            self._extend(forward)
            return True
        local = progress_index(
            self._full,
            here,
            previous=self._cursor - self._origin,
            near=1,
        )
        if local is None:
            self._full = [here]
            self._origin = 0
            self._cursor = 0
            self._extend(forward)
            return True
        self._cursor = self._origin + int(local)
        return self._extend(forward)

    def _extend(self, forward: Sequence[Tile]) -> bool:
        """Attach the recalculated guide. True when it leaves the stored future."""
        local_c = self._cursor - self._origin
        if local_c < 0 or local_c >= len(self._full):
            return False
        here = self._full[local_c]
        future = list(forward)
        if future and future[0] == here:
            future = future[1:]
        elif (
            future
            and local_c + 1 < len(self._full)
            and future[0] == self._full[local_c + 1]
        ):
            pass
        old = self._full[local_c + 1 :]
        for i, tile in enumerate(future):
            if i < len(old) and old[i] != tile:
                self._full = self._full[: local_c + 1 + i] + future[i:]
                return True
        if len(future) > len(old):
            self._full.extend(future[len(old) :])
        return False

    def _trim(self) -> None:
        keep = self._cursor - (MARCH_TRAIL + MARCH_WINDOW)
        if keep <= self._origin:
            return
        drop = keep - self._origin
        if drop <= 0 or drop >= len(self._full):
            return
        self._full = self._full[drop:]
        self._origin += drop

    def _frame_window(self) -> tuple[tuple[Tile, ...], int, int]:
        start = max(self._origin, self._cursor - MARCH_TRAIL)
        end = min(self._origin + len(self._full) - 1, self._cursor + MARCH_WINDOW)
        local_start = start - self._origin
        local_end = end - self._origin
        window = tuple(self._full[local_start : local_end + 1])
        return window, start, self._cursor - start

    def _seat_indexes(self, seats: Sequence[Any]) -> list[Optional[int]]:
        out: list[Optional[int]] = []
        for seat, raw in enumerate(seats):
            if not isinstance(raw, tuple) or len(raw) != 2:
                out.append(None)
                continue
            try:
                tile = (int(raw[0]), int(raw[1]))
            except (TypeError, ValueError):
                out.append(None)
                continue
            previous = self._seen.get(seat)
            local_prev = None if previous is None else int(previous) - self._origin
            local = progress_index(self._full, tile, previous=local_prev, near=1)
            if local is None:
                out.append(None)
                continue
            full = self._origin + int(local)
            self._seen[seat] = full
            out.append(full)
        return out

    def _clear(self, map_id: Optional[int]) -> Optional[dict[str, Any]]:
        if not self.active:
            self._hello = False
            return None
        self.seq += 1
        self.rev += 1
        self.active = False
        self._full = []
        self._origin = 0
        self._cursor = 0
        self._sig = None
        self._hello = False
        self._seen = {}
        body = march_message(
            map_id=0 if map_id is None else int(map_id),
            rev=self.rev,
            seq=self.seq,
            cursor=0,
            tiles=(),
            clear=True,
        )
        self._last = body
        return body


def path_forward(tiles: Sequence[Tile], index: int) -> tuple[int, int]:
    i = max(0, min(int(index), len(tiles) - 1)) if tiles else 0
    if i + 1 < len(tiles):
        return unit8((tiles[i + 1][0] - tiles[i][0], tiles[i + 1][1] - tiles[i][1]))
    if i > 0:
        return unit8((tiles[i][0] - tiles[i - 1][0], tiles[i][1] - tiles[i - 1][1]))
    return (0, 0)


def has_side_room(tile: Tile, forward: tuple[int, int], terrain: Any) -> bool:
    """True when a body can stand one tile off ``tile``.

    Unknown terrain is treated as open. A missing wall must not force a file
    that the member cannot check.
    """
    if terrain is None or forward == (0, 0):
        return True
    rx, ry = right_of(forward)
    left = (int(tile[0]) - rx, int(tile[1]) - ry)
    right = (int(tile[0]) + rx, int(tile[1]) + ry)
    return walkable(terrain, left[0], left[1]) or walkable(terrain, right[0], right[1])


def narrow_ahead(tiles: Sequence[Tile], index: int, terrain: Any) -> bool:
    """True when this index, or one of the next few steps, has no side tile."""
    if not tiles or terrain is None:
        return False
    last = min(len(tiles) - 1, int(index) + MARCH_NARROW_LOOK)
    for i in range(max(0, int(index)), last + 1):
        if not has_side_room(tiles[i], path_forward(tiles, i), terrain):
            return True
    return False


def narrow_exit(tiles: Sequence[Tile], index: int, terrain: Any) -> int:
    """First index at or after ``index`` that has a side tile again."""
    i = max(0, int(index))
    while i < len(tiles) and not has_side_room(tiles[i], path_forward(tiles, i), terrain):
        i += 1
    return min(i, len(tiles) - 1) if tiles else 0


def file_blocked(
    seat: int,
    progress: Optional[int],
    door: int,
    exit_index: int,
    others: Sequence[tuple[int, Optional[int]]],
) -> bool:
    """True when a lower seat still owns the passage.

    A member already at the door keeps walking so the exit can clear.
    The front participating seat is never held by someone behind. A missing
    progress does not count as occupying the door.
    """
    if progress is not None and int(progress) >= int(door):
        return False
    ahead = [
        int(idx)
        for other, idx in others
        if int(other) < int(seat) and idx is not None
    ]
    if not ahead:
        return False
    return any(idx < int(exit_index) for idx in ahead)


def note_heading(
    scratch: dict[str, Any],
    step: tuple[int, int],
) -> tuple[int, int]:
    """Reuse the two-tile heading latch. The first real step commits."""
    heading, pending, run, _committed = advance_heading(
        scratch.get("march_heading"),
        scratch.get("march_heading_pending"),
        int(scratch.get("march_heading_run") or 0),
        step,
    )
    if heading is not None:
        scratch["march_heading"] = heading
    if pending is not None:
        scratch["march_heading_pending"] = pending
        scratch["march_heading_run"] = int(run)
    else:
        scratch.pop("march_heading_pending", None)
        scratch.pop("march_heading_run", None)
    faced = unit8(heading)
    return faced if faced != (0, 0) else unit8(step)


def full_progress(
    path: MarchPath,
    tile: Tile,
    previous: Optional[int],
) -> Optional[int]:
    """Full-path index of ``tile``. ``previous`` is already a full-path index."""
    local_prev = None
    if previous is not None:
        local_prev = int(previous) - int(path.base)
        if local_prev < 0 or local_prev >= len(path.tiles):
            local_prev = None
    local = progress_index(path.tiles, tile, previous=local_prev, near=1)
    if local is None:
        return None
    full = int(path.base) + int(local)
    if previous is not None and local_prev is None and full > int(previous) + 2:
        return None
    return full


def path_tile(path: MarchPath, full: int) -> Optional[Tile]:
    local = int(full) - int(path.base)
    if local < 0 or local >= len(path.tiles):
        return None
    return path.tiles[local]


def choose_admission(
    tiles: Sequence[Tile],
    base: int,
    cursor: int,
    terrain: Any,
    seat_full: Sequence[Optional[int]],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Leader's passage turn: ``(door, exit, admit)`` as full-path indexes.

    Open ground and a missing wall return no turn. ``admit`` is the lowest
    seat still before the door, and only when the exit has a free side tile.
    A missing progress does not count as having cleared the door.
    """
    if terrain is None or not tiles:
        return None, None, None
    cursor_full = int(base) + int(cursor)
    known = [int(p) for p in seat_full if p is not None]
    start = min(known + [cursor_full])
    door = None
    last = min(int(base) + len(tiles) - 1, cursor_full + MARCH_NARROW_LOOK)
    for full in range(max(int(base), start), last + 1):
        local = full - int(base)
        if not has_side_room(tiles[local], path_forward(tiles, local), terrain):
            door = full
            break
    if door is None:
        return None, None, None
    exit_local = narrow_exit(tiles, door - int(base), terrain)
    exit_full = int(base) + int(exit_local)
    exit_tile = tiles[exit_local]
    exit_open = has_side_room(exit_tile, path_forward(tiles, exit_local), terrain)
    occupied = any(p == exit_full for p in seat_full if p is not None)
    admit = None
    if exit_open and not occupied:
        for seat, prog in enumerate(seat_full):
            if prog is None:
                break
            if int(prog) < int(door):
                admit = seat
                break
    return door, exit_full, admit


def member_goal(
    path: MarchPath,
    *,
    seat: int,
    followers: int,
    me: Tile,
    terrain: Any,
    heading: tuple[int, int],
    others: Sequence[tuple[int, Optional[int]]],
    previous_progress: Optional[int],
) -> tuple[str, Optional[Tile]]:
    """``go`` with a tile, ``pace_wait`` / ``door_wait``, or ``fallback``.

    ``fallback`` is the ordinary follow click. A short rear history does not
    send the member to ``tiles[0]``. Passage order comes from ``path.admit``.
    A member still before ``exit`` stays in file after the leader is outside.
    """
    tiles = path.tiles
    if not tiles:
        return "fallback", None
    cursor_full = int(path.base) + int(path.cursor)
    progress = full_progress(path, me, previous_progress)
    if progress is None:
        # Not on this window. Walk to this seat's slot by the leader,
        # never to tiles[0] just because the body is off the line.
        anchor = path_tile(path, cursor_full)
        forward = heading if heading != (0, 0) else path_forward(tiles, path.cursor)
        if anchor is None:
            return "fallback", None
        formed = choose_formation_goal(
            anchor,
            forward=forward,
            seat=seat,
            followers=max(1, int(followers)),
            stopped=False,
            trail_tile=None,
            terrain=terrain,
            occupied=set(),
            previous=None,
            lateral=None,
        )
        if formed.tile is None or formed.tile == me:
            return "fallback", None
        if terrain is not None and not walkable(terrain, formed.tile[0], formed.tile[1]):
            return "fallback", None
        return "go", formed.tile
    forward = heading if heading != (0, 0) else path_forward(tiles, path.cursor)
    rows = [
        (int(idx), seat_back(other))
        for other, idx in others
        if idx is not None and int(other) != int(seat)
    ]
    limit = head_limit(rows)
    back = seat_back(seat)
    in_file = path.door is not None and (
        path.exit_at is None or int(progress) < int(path.exit_at)
    )
    if in_file:
        if int(progress) < int(path.door) and (
            path.admit is None or int(seat) != int(path.admit)
        ):
            return "door_wait", None
        target = cursor_full - back
        if target < int(path.base):
            return "fallback", None
        landed = aim_index(target, progress, back, limit)
        taken = _occupied_ahead(path, seat, others)
        if landed is None or int(landed) <= int(progress):
            nxt = int(progress) + 1
            if (
                path.exit_at is not None
                and nxt <= int(path.exit_at)
                and nxt < cursor_full
            ):
                step = path_tile(path, nxt)
                if step is not None and step not in taken and step != me:
                    if terrain is None or walkable(terrain, step[0], step[1]):
                        return "go", step
            return ("pace_wait" if landed is None else "door_wait"), None
        step = path_tile(path, int(landed))
        if step is None:
            return "fallback", None
        if step in taken or step == me:
            return "door_wait", None
        if terrain is not None and not walkable(terrain, step[0], step[1]):
            return "fallback", None
        return "go", step
    desired = min(int(path.base) + len(tiles) - 1, cursor_full + MARCH_LOOKAHEAD)
    landed = aim_index(desired, progress, back, limit)
    if landed is None:
        return "pace_wait", None
    anchor = path_tile(path, int(landed))
    if anchor is None:
        return "fallback", None
    formed = choose_formation_goal(
        anchor,
        forward=forward,
        seat=seat,
        followers=max(1, int(followers)),
        stopped=False,
        trail_tile=None,
        terrain=terrain,
        occupied=set(),
        previous=None,
        lateral=None,
    )
    if formed.tile is None:
        return "fallback", None
    if terrain is not None and not walkable(terrain, formed.tile[0], formed.tile[1]):
        return "fallback", None
    if formed.tile == me:
        return "pace_wait", None
    return "go", formed.tile


def _occupied_ahead(
    path: MarchPath,
    seat: int,
    others: Sequence[tuple[int, Optional[int]]],
) -> set[Tile]:
    taken: set[Tile] = set()
    for other, idx in others:
        if idx is None or int(other) >= int(seat):
            continue
        tile = path_tile(path, int(idx))
        if tile is not None:
            taken.add(tile)
    return taken


def _tiles(guide: Sequence[Tile]) -> list[Tile]:
    out: list[Tile] = []
    for raw in guide or ():
        try:
            tile = (int(raw[0]), int(raw[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if not out or out[-1] != tile:
            out.append(tile)
    return out


def _window(tiles: Sequence[Tile], here: Tile) -> tuple[tuple[Tile, ...], int]:
    idx = progress_index(tiles, here, previous=None, near=1)
    if idx is None:
        idx = 0
    window = tuple(tiles[idx : idx + MARCH_WINDOW])
    return window, 0


def observe_line(
    snapshot: Any,
    tiles: Sequence[Tile],
    *,
    local_map_id: Optional[int],
    self_name: str,
    seen: dict[str, int],
    base: int = 0,
) -> list[tuple[int, Optional[int]]]:
    """``(seat, full-path progress)`` for other members.

    ``seen`` stores full-path indexes. A row on another map, or off this
    window, is None and does not hold the line. Progress comes from the
    party-memory tile, never from a click we sent.
    """
    from .leader import _party_map_id, _party_tile

    if not isinstance(snapshot, dict):
        return []
    me = str(self_name or "").strip().casefold()
    out: list[tuple[int, Optional[int]]] = []
    seat = 0
    for row in snapshot.get("members") or []:
        if not isinstance(row, dict) or bool(row.get("is_leader")):
            continue
        name = str(row.get("name") or "").strip()
        key = name.casefold()
        if me and key == me:
            seat += 1
            continue
        mid = _party_map_id(row)
        other_map = (
            local_map_id is not None
            and mid is not None
            and int(mid) != int(local_map_id)
        )
        tile = None if other_map else _party_tile(row)
        if tile is None:
            out.append((seat, None))
            seat += 1
            continue
        previous = seen.get(key)
        local_prev = None if previous is None else int(previous) - int(base)
        if local_prev is not None and (local_prev < 0 or local_prev >= len(tiles)):
            local_prev = None
        local = progress_index(
            tiles,
            (int(tile[0]), int(tile[1])),
            previous=local_prev,
            near=1,
        )
        progress = None if local is None else int(base) + int(local)
        if (
            progress is not None
            and previous is not None
            and local_prev is None
            and progress > int(previous) + 2
        ):
            progress = None
        if progress is not None and key:
            seen[key] = int(progress)
        out.append((seat, progress))
        seat += 1
    return out


def slot_ahead(me: Tile, goal: Optional[Tile], forward: tuple[int, int]) -> bool:
    """True when ``goal`` is not behind ``me`` along ``forward``."""
    if goal is None or (int(goal[0]), int(goal[1])) == (int(me[0]), int(me[1])):
        return False
    fx, fy = int(forward[0]), int(forward[1])
    if fx == 0 and fy == 0:
        return True
    dx = int(goal[0]) - int(me[0])
    dy = int(goal[1]) - int(me[1])
    return dx * fx + dy * fy >= 0


def _others_tail(others: Sequence[tuple[int, Optional[int]]]) -> Optional[int]:
    known = [int(idx) for _seat, idx in others if idx is not None]
    return min(known) if known else None


def _first_narrow(tiles: Sequence[Tile], index: int, terrain: Any) -> int:
    i = max(0, int(index))
    while i < len(tiles) and has_side_room(tiles[i], path_forward(tiles, i), terrain):
        i += 1
    return min(i, len(tiles) - 1) if tiles else 0


__all__ = [
    "MARCH_ALLOWED_LAG",
    "MARCH_GAP_TILES",
    "MARCH_LOOKAHEAD",
    "MARCH_WINDOW",
    "PATH_TYPE",
    "MarchMove",
    "MarchPath",
    "MarchShare",
    "accept_march",
    "aim_index",
    "choose_admission",
    "clip_leader_hop",
    "file_blocked",
    "full_progress",
    "has_side_room",
    "head_limit",
    "leader_path_gap",
    "line_gap",
    "march_message",
    "member_goal",
    "narrow_ahead",
    "note_heading",
    "observe_line",
    "pace_aim",
    "parse_march",
    "path_forward",
    "path_tile",
    "progress_index",
    "seat_back",
    "slot_ahead",
]
