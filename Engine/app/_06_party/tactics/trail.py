"""Dungeon formation: single file along the leader's tile history.

``LeaderTrail`` records each tile the leader stands on, filling gaps between
polls with straight steps, and resets on a jump (teleport / map change).
Follower ``i`` targets the trail point ``spacing * (i + 1)`` steps behind the
head, so each member walks exactly where the leader walked.

``leader_hold`` tells the leader to stop when a follower is stuck at the last
corner or has fallen far behind its expected place in the line.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional, Sequence

from ._grid import Tile, cheb, sign


class LeaderTrail:
    def __init__(self, *, max_len: int = 256, jump_tiles: int = 6) -> None:
        self._pts: deque[Tile] = deque()
        self._base = 0
        self._max_len = max(8, int(max_len))
        self._jump = max(2, int(jump_tiles))

    def __len__(self) -> int:
        return len(self._pts)

    @property
    def head_index(self) -> int:
        return self._base + len(self._pts) - 1

    @property
    def head(self) -> Optional[Tile]:
        return self._pts[-1] if self._pts else None

    def reset(self) -> None:
        self._base += len(self._pts)
        self._pts.clear()

    def point(self, index: int) -> Optional[Tile]:
        i = int(index) - self._base
        if 0 <= i < len(self._pts):
            return self._pts[i]
        return None

    def push(self, tile: Tile) -> bool:
        """Record the leader tile. Returns ``True`` when the trail changed."""
        t = (int(tile[0]), int(tile[1]))
        if self._pts and self._pts[-1] == t:
            return False
        if self._pts and cheb(self._pts[-1], t) > self._jump:
            self.reset()
        if self._pts:
            x, y = self._pts[-1]
            while cheb((x, y), t) > 1:
                x += sign(t[0] - x)
                y += sign(t[1] - y)
                self._append((x, y))
        self._append(t)
        return True

    def _append(self, t: Tile) -> None:
        self._pts.append(t)
        while len(self._pts) > self._max_len:
            self._pts.popleft()
            self._base += 1

    def follower_target(self, slot_index: int, *, spacing: int = 2) -> Optional[Tile]:
        if not self._pts:
            return None
        back = max(1, int(spacing)) * (max(0, int(slot_index)) + 1)
        idx = max(self._base, self.head_index - back)
        return self.point(idx)

    def progress_of(self, tile: Tile, *, near: int = 1) -> Optional[int]:
        """Newest trail index within ``near`` tiles of ``tile``."""
        t = (int(tile[0]), int(tile[1]))
        for i in range(len(self._pts) - 1, -1, -1):
            if cheb(self._pts[i], t) <= near:
                return self._base + i
        return None

    def last_corner(self, *, min_turn_deg: float = 90.0, window: int = 2) -> Optional[int]:
        """Newest trail index where the heading turns by ``min_turn_deg`` or more."""
        w = max(1, int(window))
        limit = math.cos(math.radians(float(min_turn_deg))) + 1e-9
        pts = self._pts
        for i in range(len(pts) - 1 - w, w - 1, -1):
            ax, ay = pts[i][0] - pts[i - w][0], pts[i][1] - pts[i - w][1]
            bx, by = pts[i + w][0] - pts[i][0], pts[i + w][1] - pts[i][1]
            na = math.hypot(ax, ay)
            nb = math.hypot(bx, by)
            if na == 0 or nb == 0:
                continue
            if (ax * bx + ay * by) / (na * nb) <= limit:
                return self._base + i
        return None


@dataclass(frozen=True)
class HoldDecision:
    hold: bool
    reason: str
    corner_index: Optional[int] = None
    follower: Optional[int] = None


def leader_hold(
    trail: LeaderTrail,
    followers: Sequence[Optional[Tile]],
    *,
    spacing: int = 2,
    corner_clear_steps: int = 1,
    past_corner_steps: int = 3,
    max_extra_lag: int = 6,
) -> HoldDecision:
    """Whether the leader should stop and let the line catch up.

    Follower ``i`` is expected ``spacing * (i + 1)`` steps behind the head.
    A ``None`` entry (position unknown) keeps its slot but is not checked.
    The leader holds when:

    - ``corner``: the leader is past the last corner by that expected lag plus
      ``past_corner_steps``, but follower ``i`` has not cleared the corner
    - ``lag``: follower ``i`` is more than ``max_extra_lag`` steps behind its
      expected place, or is off the trail and that far from the head
    """
    head = trail.head
    if head is None:
        return HoldDecision(False, "no_trail")
    head_i = trail.head_index
    corner = trail.last_corner()
    step = max(1, int(spacing))
    for i, tile in enumerate(followers):
        if tile is None:
            continue
        expected = step * (i + 1)
        p = trail.progress_of(tile)
        if p is None:
            if cheb(tile, head) > expected + int(max_extra_lag):
                return HoldDecision(True, "lag", corner, i)
            continue
        if (
            corner is not None
            and p < corner + int(corner_clear_steps)
            and head_i - corner >= expected + int(past_corner_steps)
        ):
            return HoldDecision(True, "corner", corner, i)
        if head_i - p > expected + int(max_extra_lag):
            return HoldDecision(True, "lag", corner, i)
    return HoldDecision(False, "clear", corner)


__all__ = ["HoldDecision", "LeaderTrail", "leader_hold"]
