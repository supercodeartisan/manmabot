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


def followers_from_party(
    snapshot: Any,
    local_map_id: Optional[int],
    *,
    self_name: str = "",
) -> list[Any]:
    """Non-leader party-memory rows → tile on this map, or ``OTHER_MAP``.

    ``snapshot`` is ``world.last_party`` (``in_party`` + ``members`` rows with
    name / map / tile). Rows without a readable tile are skipped.
    """
    from .leader import _party_map_id, _party_tile

    if not isinstance(snapshot, dict) or not snapshot.get("in_party"):
        return []
    me = str(self_name or "").strip().casefold()
    out: list[Any] = []
    for row in snapshot.get("members") or []:
        if not isinstance(row, dict) or bool(row.get("is_leader")):
            continue
        if me and str(row.get("name") or "").strip().casefold() == me:
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
    "FormationTarget",
    "LeaderLineWatch",
    "LineHold",
    "MemberFormation",
    "followers_from_party",
    "nearest_follower_gap",
    "nearest_gap_hold",
    "near_wait_open",
]
