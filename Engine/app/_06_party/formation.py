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
# Fresh reading inside this distance is back on the seat.
SLOT_REJOIN_TILES = 1
# A member already on the seat stays on it until they step past this.
RELEASE_SLOP_TILES = 2
# Same 4-tile return the member already uses. The leader withholds the next hop.
YIELD_TILES = 4
# No closer reading for this long, with a fresh tile, is blocked.
PROGRESS_STALE_S = 2.0
# A companion already in this wait keeps this long when the pose drops.
UNKNOWN_GRACE_S = 2.0
# Ten seconds means the formation did not recover. It does not drop a member.
FORMATION_HOLD_MAX_S = 10.0
# Re-pick a seat this many times, then the wait becomes a hand-needed hold.
RECOVERY_TRIES = 2
# Approaching members are re-checked inside this budget. It does not reset.
RECOVERY_BUDGET_S = 10.0
# Same still window the member uses before a standing formation.
LEADER_STILL_S = 0.7

READY = "READY"
APPROACHING = "APPROACHING"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
EXCLUDED = "EXCLUDED"


@dataclass(frozen=True)
class SeatSample:
    """One companion this tick. ``error`` ``None`` is an unread pose."""

    name: str
    error: Optional[int] = None
    tile: Optional[Tile] = None
    seat: Optional[int] = None
    excluded: bool = False


def hop_widens_gap(
    origin: Tile,
    click: Tile,
    members: Sequence[Tile],
) -> bool:
    """True when ``click`` is farther from any listed member than ``origin`` is."""
    ox, oy = int(origin[0]), int(origin[1])
    cx, cy = int(click[0]), int(click[1])
    for member in members:
        mx, my = int(member[0]), int(member[1])
        now = max(abs(ox - mx), abs(oy - my))
        nxt = max(abs(cx - mx), abs(cy - my))
        if nxt > now:
            return True
    return False


@dataclass
class _Companion:
    state: str = UNKNOWN
    seen_in_slot: bool = False
    joining: bool = False
    seat: Optional[int] = None
    last_error: Optional[int] = None
    last_tile: Optional[Tile] = None
    best_error: Optional[int] = None
    progress_at: Optional[float] = None
    behind_since: Optional[float] = None
    unknown_since: Optional[float] = None


class FormationLagWatch:
    """One party wait. Members keep a state; the party decides when to walk.

    Before anyone has stood on a seat, one readable member outside that seat
    starts the wait. After that, 6 tiles for 0.3 seconds starts it. The
    companion set, facing, and clock are fixed for that wait. A dropped pose
    stays unknown. Ten seconds, or a member who is not closing, opens recovery.
    The leader walks when every companion in the wait is on an allowed seat.
    """

    def __init__(self) -> None:
        self.aligned = False
        self.degraded = False
        self.line_shape: Optional[str] = None
        self.still_age = 0.0
        self.session_on = False
        self.action_needed = False
        self.reform_pending = False
        self._companions: dict[str, _Companion] = {}
        self._session: set[str] = set()
        self._session_since: Optional[float] = None
        self._recovery_since: Optional[float] = None
        self._reform_tries = 0
        self._tile: Optional[Tile] = None
        self._forward: Optional[tuple[int, int]] = None
        self._still_since: Optional[float] = None
        self._locked_tile: Optional[Tile] = None
        self._locked_forward: Optional[tuple[int, int]] = None

    def reset(self) -> None:
        self.aligned = False
        self.degraded = False
        self.line_shape = None
        self.still_age = 0.0
        self.session_on = False
        self.action_needed = False
        self.reform_pending = False
        self._companions.clear()
        self._session.clear()
        self._session_since = None
        self._recovery_since = None
        self._reform_tries = 0
        self._tile = None
        self._forward = None
        self._still_since = None
        self._locked_tile = None
        self._locked_forward = None

    @property
    def session_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._session))

    @property
    def locked_tile(self) -> Optional[Tile]:
        return self._locked_tile

    @property
    def locked_forward(self) -> Optional[tuple[int, int]]:
        return self._locked_forward

    def seat_for(self, name: str) -> Optional[int]:
        comp = self._companions.get(str(name))
        if comp is None or not self.session_on:
            return None
        return comp.seat

    def member_state(self, name: str) -> str:
        comp = self._companions.get(str(name))
        return UNKNOWN if comp is None else comp.state

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
            stood = False
        else:
            if self._still_since is None:
                self._still_since = float(now)
            self.still_age = float(now) - self._still_since
            stood = self.still_age >= LEADER_STILL_S
        if self.session_on and stood and self._locked_tile is None:
            self._locked_tile = current
            self._locked_forward = self._forward
        return self._forward, stood

    def consume_reform(self, now: float) -> bool:
        """One seat re-pick. Progress is measured again from this moment."""
        if not self.reform_pending:
            return False
        self.reform_pending = False
        self._reform_tries += 1
        for name in self._session:
            comp = self._companions.get(name)
            if comp is None or comp.state != BLOCKED:
                continue
            comp.best_error = comp.last_error
            comp.progress_at = float(now)
        return True

    def yield_tiles(self) -> list[Tile]:
        """Members at least ``YIELD_TILES`` off a seat while the party is not waiting."""
        if self.session_on:
            return []
        found: list[Tile] = []
        for comp in self._companions.values():
            if comp.joining or comp.state == EXCLUDED:
                continue
            if comp.last_tile is None or comp.last_error is None:
                continue
            if comp.last_error >= YIELD_TILES:
                found.append(comp.last_tile)
        return found

    def _open_session(self, now: float) -> None:
        self.session_on = True
        self.action_needed = False
        self._session_since = float(now)
        self._recovery_since = None
        self._reform_tries = 0
        self.reform_pending = False
        self._locked_tile = None
        self._locked_forward = self._forward
        self._session = {
            name
            for name, comp in self._companions.items()
            if comp.state != EXCLUDED and not comp.joining and comp.last_error is not None
        }

    def _close_session(self) -> None:
        self.session_on = False
        self.action_needed = False
        self.reform_pending = False
        self._session.clear()
        self._session_since = None
        self._recovery_since = None
        self._reform_tries = 0
        self._locked_tile = None
        self._locked_forward = None
        for comp in self._companions.values():
            comp.joining = False

    def _mark(self, comp: _Companion, sample: SeatSample, now: float, in_session: bool) -> None:
        if sample.excluded:
            comp.state = EXCLUDED
            comp.joining = False
            comp.unknown_since = None
            return
        if sample.seat is not None and comp.seat is None:
            comp.seat = int(sample.seat)
        if sample.error is None:
            comp.last_error = None
            if in_session:
                if comp.unknown_since is None:
                    comp.unknown_since = float(now)
                comp.state = UNKNOWN
            return
        comp.unknown_since = None
        error = int(sample.error)
        comp.last_error = error
        if sample.tile is not None:
            comp.last_tile = (int(sample.tile[0]), int(sample.tile[1]))
        ready = error <= SLOT_REJOIN_TILES or (
            comp.state == READY and error <= RELEASE_SLOP_TILES
        )
        if ready:
            comp.state = READY
            comp.seen_in_slot = True
            comp.best_error = error
            comp.progress_at = float(now)
            comp.behind_since = None
            return
        if comp.best_error is None or error < comp.best_error:
            comp.best_error = error
            comp.progress_at = float(now)
        age = 0.0 if comp.progress_at is None else float(now) - comp.progress_at
        comp.state = BLOCKED if age >= PROGRESS_STALE_S else APPROACHING

    def _ensure_recovery(self, now: float) -> None:
        if self._recovery_since is None:
            self._recovery_since = float(now)

    def update(self, rows: Sequence[Any], now: float) -> LineHold:
        """``rows`` are ``SeatSample`` or ``(name, error)``."""
        samples: list[SeatSample] = []
        for row in rows:
            if isinstance(row, SeatSample):
                if str(row.name or "").strip():
                    samples.append(row)
                continue
            name = str(row[0] or "").strip()
            if not name:
                continue
            err = row[1]
            tile = row[2] if len(row) > 2 else None
            samples.append(
                SeatSample(
                    name,
                    None if err is None else int(err),
                    None if tile is None else (int(tile[0]), int(tile[1])),
                )
            )
        if not samples and not self.session_on:
            self.aligned = False
            self.degraded = False
            return LineHold(False, "no_members", 0, 0)

        seen: set[str] = set()
        for sample in samples:
            name = str(sample.name).strip()
            seen.add(name)
            comp = self._companions.setdefault(name, _Companion())
            if (
                self.session_on
                and name not in self._session
                and not sample.excluded
                and comp.last_error is None
                and not comp.seen_in_slot
            ):
                comp.joining = True
            self._mark(comp, sample, now, name in self._session)

        if self.session_on:
            for name in list(self._session):
                if name in seen:
                    continue
                comp = self._companions.setdefault(name, _Companion())
                if comp.unknown_since is None:
                    comp.unknown_since = float(now)
                comp.last_error = None
                comp.state = UNKNOWN

        if not self.session_on:
            trigger = ""
            for name, comp in self._companions.items():
                if comp.joining or comp.state == EXCLUDED or comp.last_error is None:
                    continue
                if not comp.seen_in_slot and comp.last_error > SLOT_REJOIN_TILES:
                    trigger = f"depart:{name}"
                    break
                if comp.seen_in_slot and comp.last_error >= SLOT_LAG_TILES:
                    if comp.behind_since is None:
                        comp.behind_since = float(now)
                    if float(now) - comp.behind_since >= SLOT_LAG_HOLD_S:
                        trigger = f"slot_behind:{name}"
                        break
                else:
                    comp.behind_since = None
            if trigger:
                self._open_session(now)
                for name in self._session:
                    comp = self._companions[name]
                    comp.progress_at = float(now)
                    comp.best_error = comp.last_error
                    if comp.state != READY:
                        comp.state = APPROACHING
            else:
                live = [
                    comp
                    for comp in self._companions.values()
                    if comp.last_error is not None and comp.state != EXCLUDED and not comp.joining
                ]
                self.aligned = bool(live) and all(comp.seen_in_slot for comp in live)
                self.degraded = False
                if any(
                    comp.seen_in_slot and comp.last_error is not None and comp.last_error >= SLOT_LAG_TILES
                    for comp in live
                ):
                    return LineHold(False, "lag_arming", 0, len(live))
                if any(comp.last_error is not None and comp.last_error > SLOT_REJOIN_TILES for comp in live):
                    return LineHold(False, "closing", 0, len(live))
                if live:
                    return LineHold(False, "in_slot", 0, len(live))
                return LineHold(False, "no_members", 0, 0)

        for name in list(self._session):
            comp = self._companions.get(name)
            if comp is not None and comp.state == EXCLUDED:
                self._session.discard(name)
        if not self._session:
            self._close_session()
            return LineHold(False, "excluded", 0, 0)

        held = 0.0 if self._session_since is None else float(now) - self._session_since
        pending = sorted(
            (name for name in self._session if self._companions[name].state != READY),
            key=lambda name: (self._companions[name].seen_in_slot, name),
        )
        behind = len(pending)
        known = sum(
            1
            for name in self._session
            if self._companions[name].last_error is not None
        )
        if not pending:
            self.aligned = True
            self.degraded = False
            self._close_session()
            return LineHold(False, "together", 0, known, held)

        blocked = [
            name
            for name in pending
            if self._companions[name].state == BLOCKED
        ]
        unknown = [
            name
            for name in pending
            if self._companions[name].state == UNKNOWN
            and self._companions[name].unknown_since is not None
            and float(now) - float(self._companions[name].unknown_since) >= UNKNOWN_GRACE_S
        ]
        if blocked or unknown or held >= FORMATION_HOLD_MAX_S:
            self._ensure_recovery(now)
        if blocked and self._reform_tries < RECOVERY_TRIES and not self.reform_pending:
            self.reform_pending = True

        self.action_needed = False
        if self._recovery_since is not None:
            budget_done = float(now) - self._recovery_since >= RECOVERY_BUDGET_S
            tries_done = self._reform_tries >= RECOVERY_TRIES and not self.reform_pending
            if tries_done and blocked:
                self.action_needed = True
            elif tries_done and unknown and not any(
                self._companions[name].state == APPROACHING for name in pending
            ):
                self.action_needed = True
            elif budget_done:
                self.action_needed = True
        self.degraded = self.action_needed
        self.aligned = False
        focus = pending[0]
        if self.action_needed:
            why = "action_needed"
        elif self._recovery_since is not None:
            why = "recover"
        elif not self._companions[focus].seen_in_slot:
            why = "depart"
        else:
            why = "slot_behind"
        return LineHold(True, f"{why}:{focus}", behind, known, held)


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
    "READY",
    "APPROACHING",
    "BLOCKED",
    "UNKNOWN",
    "EXCLUDED",
    "SeatSample",
    "YIELD_TILES",
    "hop_widens_gap",
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
