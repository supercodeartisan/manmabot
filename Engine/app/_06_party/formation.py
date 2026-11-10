"""Moving-mode formation: open field vs narrow passage, single-file trail.

Composes ``tactics.terrain_kind`` and ``tactics.trail`` into two stateful
objects the session can call each tick. Pure: no memory reads, no input, no
decision-layer imports; the caller passes the terrain and tiles.

- ``MemberFormation`` (one per member bot): records the leader's tiles,
  classifies the area around the leader, and in a narrow area returns the
  trail tile for this member's roster seat. In an open area it returns no
  tile, so the caller keeps its open-field follow.
- ``LeaderLineWatch`` (moving leader): records its own tiles and says whether
  to wait because half or more members are more than ``lag_tiles`` behind.
  A wait never lasts longer than ``max_hold_s``; after that the leader walks
  on for ``cooldown_s`` before it may wait again.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from .tactics._grid import Tile, cheb
from .tactics.terrain_kind import NARROW, OPEN, TerrainReading, classify_area
from .tactics.trail import LeaderTrail

# Re-read the area once the leader has moved this far since the last reading.
RECLASSIFY_TILES = 2
# Steps between members on the trail (member i stands spacing*(i+1) behind).
TRAIL_SPACING = 2
# Follower marker for "in party, but on another map".
OTHER_MAP = "other_map"


@dataclass(frozen=True)
class FormationTarget:
    kind: str  # OPEN | NARROW | "unknown"
    tile: Optional[Tile]
    reason: str


class _AreaKind:
    """terrain_kind with hysteresis, re-read only after the leader moves."""

    def __init__(self, *, radius: int, reclassify_tiles: int) -> None:
        self._radius = max(1, int(radius))
        self._every = max(1, int(reclassify_tiles))
        self.reading: Optional[TerrainReading] = None
        self._at: Optional[Tile] = None

    @property
    def kind(self) -> Optional[str]:
        return None if self.reading is None else self.reading.kind

    def reset(self) -> None:
        self.reading = None
        self._at = None

    def update(self, terrain: Any, center: Tile) -> Optional[TerrainReading]:
        if terrain is None:
            return self.reading
        if self._at is not None and cheb(self._at, center) < self._every:
            return self.reading
        self.reading = classify_area(
            terrain, center, radius=self._radius, previous=self.kind
        )
        self._at = center
        return self.reading


class MemberFormation:
    def __init__(
        self,
        *,
        spacing: int = TRAIL_SPACING,
        radius: int = 6,
        reclassify_tiles: int = RECLASSIFY_TILES,
        trail_len: int = 256,
        jump_tiles: int = 6,
    ) -> None:
        self.spacing = max(1, int(spacing))
        self.trail = LeaderTrail(max_len=trail_len, jump_tiles=jump_tiles)
        self._area = _AreaKind(radius=radius, reclassify_tiles=reclassify_tiles)

    @property
    def kind(self) -> Optional[str]:
        return self._area.kind

    @property
    def reading(self) -> Optional[TerrainReading]:
        return self._area.reading

    def reset(self) -> None:
        """Leader lost / other map: forget the trail and the area reading."""
        self.trail.reset()
        self._area.reset()

    def observe(self, terrain: Any, leader_tile: Optional[Tile]) -> None:
        if leader_tile is None:
            return
        tile = (int(leader_tile[0]), int(leader_tile[1]))
        self.trail.push(tile)
        self._area.update(terrain, tile)

    def target(self, seat_index: Optional[int]) -> FormationTarget:
        kind = self.kind
        if kind is None:
            return FormationTarget("unknown", None, "no_reading")
        if kind == OPEN:
            return FormationTarget(OPEN, None, "open_field")
        if seat_index is None:
            return FormationTarget(NARROW, None, "no_seat")
        tile = self.trail.follower_target(int(seat_index), spacing=self.spacing)
        if tile is None:
            return FormationTarget(NARROW, None, "trail_empty")
        return FormationTarget(NARROW, tile, f"trail_seat{int(seat_index)}")


@dataclass(frozen=True)
class LineHold:
    hold: bool
    reason: str
    behind: int = 0
    known: int = 0
    held_s: float = 0.0


class LeaderLineWatch:
    """Moving leader: wait when half or more known members lag ``lag_tiles``.

    Lag of one member = max(straight Chebyshev distance, steps behind the head
    on the leader's own trail), so a member around a corner counts by the walk.
    ``OTHER_MAP`` counts as behind; ``None`` (not in party memory) is ignored.
    """

    def __init__(
        self,
        *,
        lag_tiles: int = 30,
        max_hold_s: float = 8.0,
        cooldown_s: float = 6.0,
        trail_len: int = 512,
        jump_tiles: int = 6,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.lag_tiles = max(1, int(lag_tiles))
        self.max_hold_s = max(0.5, float(max_hold_s))
        self.cooldown_s = max(0.0, float(cooldown_s))
        self.trail = LeaderTrail(max_len=trail_len, jump_tiles=jump_tiles)
        self._clock = clock
        self._hold_since: Optional[float] = None
        self._free_until = float("-inf")

    def reset(self) -> None:
        self.trail.reset()
        self._hold_since = None
        self._free_until = float("-inf")

    def observe(self, leader_tile: Optional[Tile]) -> None:
        if leader_tile is None:
            return
        self.trail.push((int(leader_tile[0]), int(leader_tile[1])))

    def lag_of(self, follower: Any) -> Optional[int]:
        if follower is None:
            return None
        if follower == OTHER_MAP:
            return self.lag_tiles + 1
        head = self.trail.head
        if head is None:
            return None
        tile = (int(follower[0]), int(follower[1]))
        lag = cheb(tile, head)
        p = self.trail.progress_of(tile)
        if p is not None:
            lag = max(lag, self.trail.head_index - p)
        return lag

    def check(self, followers: Sequence[Any]) -> LineHold:
        """``followers``: tile, ``OTHER_MAP``, or ``None`` per member."""
        now = self._clock()
        lags = [lag for lag in (self.lag_of(f) for f in followers) if lag is not None]
        known = len(lags)
        behind = sum(1 for lag in lags if lag > self.lag_tiles)
        if known == 0 or behind * 2 < known:
            self._hold_since = None
            return LineHold(False, "together" if known else "no_members", behind, known)
        if now < self._free_until:
            return LineHold(False, "cooldown", behind, known)
        if self._hold_since is None:
            self._hold_since = now
        held = now - self._hold_since
        if held >= self.max_hold_s:
            self._hold_since = None
            self._free_until = now + self.cooldown_s
            return LineHold(False, "wait_timeout", behind, known, held)
        return LineHold(True, "members_behind", behind, known, held)


# A required member this far off their own seat starts the moving wait.
SLOT_LAG_TILES = 6
# Ignore a single bad sample before the leader stops.
SLOT_LAG_HOLD_S = 0.3
# Back inside the seat: side tile, or the stand seat's 3×3.
SLOT_REJOIN_TILES = 1
# One member is waited for this long, then left. There is no second try.
FORMATION_HOLD_MAX_S = 10.0
RECOVER_ATTEMPTS = 1
RECOVER_GAP_S = 0.0
# Same still window the member uses before a standing formation.
LEADER_STILL_S = 0.7


@dataclass
class _SeatLag:
    seen_in_slot: bool = False
    attempts: int = 0
    hold_since: Optional[float] = None
    behind_since: Optional[float] = None
    cooldown_until: float = 0.0
    exhausted: bool = False


class FormationLagWatch:
    """Wait on each member's distance to their own seat.

    A member who has not reached the seat holds the leader at once. After
    that, 6 tiles for 0.3 seconds holds. Ten seconds ends that member's wait.
    Another member keeps their own ten seconds. Reaching 1 tile clears that
    member. A spent wait leaves only that member behind.
    """

    def __init__(self) -> None:
        self.aligned = False
        self.degraded = False
        self.line_shape: Optional[str] = None
        self.still_age = 0.0
        self._seats: dict[str, _SeatLag] = {}
        self._tile: Optional[Tile] = None
        self._forward: Optional[tuple[int, int]] = None
        self._still_since: Optional[float] = None

    def reset(self) -> None:
        self.aligned = False
        self.degraded = False
        self.line_shape = None
        self.still_age = 0.0
        self._seats.clear()
        self._tile = None
        self._forward = None
        self._still_since = None

    def note_leader(self, tile: Tile, now: float) -> tuple[Optional[tuple[int, int]], bool]:
        """Return the last step and whether the leader has stood for ``LEADER_STILL_S``."""
        current = (int(tile[0]), int(tile[1]))
        if self._tile is None or current != self._tile:
            if self._tile is not None and current != self._tile:
                self._forward = (
                    current[0] - self._tile[0],
                    current[1] - self._tile[1],
                )
            self._tile = current
            self._still_since = float(now)
            self.still_age = 0.0
            return self._forward, False
        if self._still_since is None:
            self._still_since = float(now)
        self.still_age = float(now) - self._still_since
        return self._forward, self.still_age >= LEADER_STILL_S

    def _consider(self, seat: _SeatLag, error: int, now: float) -> tuple[bool, str]:
        if error <= SLOT_REJOIN_TILES:
            seat.seen_in_slot = True
            seat.attempts = 0
            seat.exhausted = False
            seat.hold_since = None
            seat.behind_since = None
            seat.cooldown_until = 0.0
            return False, "in_slot"
        if seat.exhausted:
            return False, "degraded"
        if float(now) < seat.cooldown_until:
            return False, "recover"
        if seat.seen_in_slot and error < SLOT_LAG_TILES:
            seat.behind_since = None
            seat.hold_since = None
            return False, "closing"
        if seat.seen_in_slot:
            if seat.behind_since is None:
                seat.behind_since = float(now)
            if float(now) - seat.behind_since < SLOT_LAG_HOLD_S:
                return False, "lag_arming"
        if seat.hold_since is None:
            seat.hold_since = float(now)
        held = float(now) - seat.hold_since
        if held >= FORMATION_HOLD_MAX_S:
            seat.attempts += 1
            seat.hold_since = None
            seat.behind_since = None
            if seat.attempts >= RECOVER_ATTEMPTS:
                seat.exhausted = True
                return False, "degraded"
            seat.cooldown_until = float(now) + RECOVER_GAP_S
            return False, "recover"
        why = "depart" if not seat.seen_in_slot else "slot_behind"
        return True, why

    def update(
        self, rows: Sequence[tuple[str, Optional[int]]], now: float
    ) -> LineHold:
        """``rows`` are ``(name, seat error)``. ``None`` is an unread pose."""
        named = [
            (str(name), None if err is None else int(err))
            for name, err in rows
            if str(name or "").strip()
        ]
        if not named:
            self.aligned = False
            self.degraded = False
            return LineHold(False, "no_members", 0, 0)
        hold_name = ""
        hold_why = ""
        behind = 0
        known = 0
        reasons: list[str] = []
        for name, err in named:
            seat = self._seats.setdefault(name, _SeatLag())
            if err is None:
                reasons.append(f"WAIT_POSE:{name}")
                continue
            known += 1
            waiting, why = self._consider(seat, err, now)
            reasons.append(f"{why}:{name}")
            if err > SLOT_REJOIN_TILES and not seat.exhausted:
                behind += 1
            if waiting and not hold_name:
                hold_name = name
                hold_why = why
        live = [self._seats[name] for name, err in named if err is not None]
        self.aligned = bool(live) and all(
            seat.seen_in_slot or seat.exhausted for seat in live
        )
        self.degraded = bool(live) and any(seat.exhausted for seat in live)
        if hold_name:
            return LineHold(True, f"{hold_why}:{hold_name}", behind, known)
        if any(text.startswith("recover:") for text in reasons):
            return LineHold(False, "recover", behind, known)
        if any(text.startswith("degraded:") for text in reasons):
            return LineHold(False, "degraded", behind, known)
        if any(text.startswith("closing:") for text in reasons):
            return LineHold(False, "closing", behind, known)
        if any(text.startswith("lag_arming:") for text in reasons):
            return LineHold(False, "lag_arming", behind, known)
        if known == 0:
            return LineHold(False, "WAIT_POSE", 0, 0)
        return LineHold(False, "in_slot", 0, known)


def followers_from_party(
    snapshot: Any,
    local_map_id: Optional[int],
    *,
    self_name: str = "",
    omit_names: Any = (),
) -> list[Any]:
    """Non-leader party-memory rows → tile on this map, or ``OTHER_MAP``.

    ``snapshot`` is ``world.last_party`` (``in_party`` + ``members`` rows with
    name / map / tile). Rows without a readable tile are skipped.
    """
    from .leader import _party_map_id, _party_tile

    if not isinstance(snapshot, dict) or not snapshot.get("in_party"):
        return []
    me = str(self_name or "").strip().casefold()
    skipped = {
        str(name or "").strip().casefold()
        for name in (omit_names or ())
        if str(name or "").strip()
    }
    out: list[Any] = []
    for row in snapshot.get("members") or []:
        if not isinstance(row, dict) or bool(row.get("is_leader")):
            continue
        row_name = str(row.get("name") or "").strip().casefold()
        if me and row_name == me:
            continue
        if row_name and row_name in skipped:
            continue
        mid = _party_map_id(row)
        if local_map_id is not None and mid is not None and int(mid) != int(local_map_id):
            out.append(OTHER_MAP)
            continue
        tile = _party_tile(row)
        if tile is not None:
            out.append((int(tile[0]), int(tile[1])))
    return out


def nearest_follower_gap(
    leader: Tile,
    followers: Sequence[Any],
) -> tuple[Optional[int], int]:
    """Closest same-map follower, and how many followers are on another map.

    The first value is ``None`` when no same-map tile was readable.
    """
    lx, ly = int(leader[0]), int(leader[1])
    nearest: Optional[int] = None
    other = 0
    for follower in followers:
        if follower == OTHER_MAP:
            other += 1
            continue
        if not isinstance(follower, tuple) or len(follower) != 2:
            continue
        gap = cheb((lx, ly), (int(follower[0]), int(follower[1])))
        if nearest is None or gap < nearest:
            nearest = gap
    return nearest, other


def near_wait_open(rally_state: str) -> bool:
    """The leader distance hold starts only after the start rally is finished."""
    return str(rally_state or "") == "done"


def nearest_gap_hold(
    nearest: Optional[int],
    other_map: int,
    limit: int,
) -> bool:
    """True when the closest follower is farther than ``limit`` tiles.

    A same-map distance wins. If every known follower is on another map,
    that gap is already past the limit. No known follower does not wait.
    """
    cap = max(1, int(limit))
    if nearest is not None:
        return int(nearest) > cap
    return int(other_map) > 0


__all__ = [
    "NARROW",
    "OPEN",
    "OTHER_MAP",
    "RECLASSIFY_TILES",
    "TRAIL_SPACING",
    "FORMATION_HOLD_MAX_S",
    "FormationLagWatch",
    "FormationTarget",
    "LeaderLineWatch",
    "SLOT_LAG_TILES",
    "LineHold",
    "MemberFormation",
    "followers_from_party",
    "nearest_follower_gap",
    "nearest_gap_hold",
    "near_wait_open",
]
