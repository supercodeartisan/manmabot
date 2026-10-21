"""Leader jump detection and staggered regroup plans for followers.

A random teleport scroll lands on a random tile of the current map, not on the
leader, so reading one does not regroup the party. The default response to a
leader jump is ``rejoin`` (the walk / world-nav / join-map route). On small
maps, ``random_teleport`` with ``RandomTeleportLoop`` repeats the scroll until
the member lands near the leader or runs out of attempts.

Each member starts its response ``stagger_s * (index + 1)`` seconds after the
jump plus a small jitter, so followers do not all act on the same tick.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from ._grid import cheb

NONE = "none"
REJOIN = "rejoin"
RANDOM_TELEPORT = "random_teleport"

MAP_CHANGE = "map_change"
SAME_MAP_JUMP = "same_map_jump"


@dataclass(frozen=True)
class Pose:
    map_id: int
    x: int
    y: int

    @property
    def tile(self) -> tuple[int, int]:
        return (int(self.x), int(self.y))


@dataclass(frozen=True)
class JumpEvent:
    kind: str
    before: Pose
    after: Pose
    tiles: Optional[int]


@dataclass(frozen=True)
class RegroupPlan:
    action: str
    delay_s: float
    reason: str


def detect_leader_jump(
    prev: Optional[Pose],
    cur: Optional[Pose],
    *,
    jump_tiles: int = 12,
) -> Optional[JumpEvent]:
    if prev is None or cur is None:
        return None
    if int(prev.map_id) != int(cur.map_id):
        return JumpEvent(MAP_CHANGE, prev, cur, None)
    d = cheb(prev.tile, cur.tile)
    if d > max(2, int(jump_tiles)):
        return JumpEvent(SAME_MAP_JUMP, prev, cur, d)
    return None


def plan_regroup(
    event: Optional[JumpEvent],
    member: Pose,
    *,
    member_index: int,
    rng: Optional[random.Random] = None,
    stagger_s: float = 0.1,
    jitter_s: float = 0.03,
    near_tiles: int = 10,
    allow_random_tp: bool = False,
) -> RegroupPlan:
    if event is None:
        return RegroupPlan(NONE, 0.0, "no_jump")
    after = event.after
    if int(member.map_id) == int(after.map_id) and cheb(member.tile, after.tile) <= int(near_tiles):
        return RegroupPlan(NONE, 0.0, "already_near")
    r = rng if rng is not None else random.Random()
    delay = max(0.0, float(stagger_s)) * (max(0, int(member_index)) + 1)
    delay += r.uniform(0.0, max(0.0, float(jitter_s)))
    same_map = int(member.map_id) == int(after.map_id)
    if allow_random_tp and same_map:
        return RegroupPlan(RANDOM_TELEPORT, delay, f"{event.kind} small_map")
    return RegroupPlan(REJOIN, delay, event.kind)


class RandomTeleportLoop:
    """Repeat random teleports until near the leader (small maps only)."""

    TELEPORT = "teleport"
    DONE = "done"
    GIVE_UP = "give_up"

    def __init__(self, *, near_tiles: int = 10, max_attempts: int = 8) -> None:
        self.near_tiles = max(1, int(near_tiles))
        self.max_attempts = max(1, int(max_attempts))
        self.attempts = 0

    def step(self, member: Pose, leader: Pose) -> str:
        if int(member.map_id) == int(leader.map_id) and cheb(member.tile, leader.tile) <= self.near_tiles:
            return self.DONE
        if int(member.map_id) != int(leader.map_id) or self.attempts >= self.max_attempts:
            return self.GIVE_UP
        self.attempts += 1
        return self.TELEPORT


__all__ = [
    "MAP_CHANGE",
    "NONE",
    "RANDOM_TELEPORT",
    "REJOIN",
    "SAME_MAP_JUMP",
    "JumpEvent",
    "Pose",
    "RandomTeleportLoop",
    "RegroupPlan",
    "detect_leader_jump",
    "plan_regroup",
]
