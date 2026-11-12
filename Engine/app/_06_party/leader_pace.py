"""Moving leader: hold one travel click while the members fall behind.

Not a stand. The body still walks out the click it already has. A hold lasts
at most ``PACE_HOLD_S``; after it, or once the gap closes, the leader clicks
freely for ``PACE_COOLDOWN_S``.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional, Sequence

PACE_HOLD_S = 1.0
PACE_COOLDOWN_S = 2.0
# A member farther than this behind the leader slows the next click.
PACE_GAP_TILES = 3
# A member farther than this is lost, busy, or stuck. It does not slow the leader.
PACE_IGNORE_TILES = 12


def _cheb(a: Any, b: Any) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def pace_gap(leader: Any, followers: Sequence[Any]) -> Optional[int]:
    """Farthest same-map follower within ``PACE_IGNORE_TILES``, else None."""
    gaps = [
        _cheb(leader, f)
        for f in followers
        if isinstance(f, tuple) and len(f) == 2
    ]
    near = [g for g in gaps if g <= PACE_IGNORE_TILES]
    return max(near) if near else None


class LeaderPace:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._since: Optional[float] = None
        self._free_until = float("-inf")

    @property
    def holding(self) -> bool:
        return self._since is not None

    def reset(self) -> None:
        self._since = None

    def check(self, *, behind: bool) -> bool:
        """True when this travel click waits."""
        now = self._clock()
        if not behind:
            if self._since is not None:
                self._since = None
                self._free_until = now + PACE_COOLDOWN_S
            return False
        if now < self._free_until:
            return False
        if self._since is None:
            self._since = now
        if now - self._since >= PACE_HOLD_S:
            self._since = None
            self._free_until = now + PACE_COOLDOWN_S
            return False
        return True


__all__ = [
    "LeaderPace",
    "PACE_COOLDOWN_S",
    "PACE_GAP_TILES",
    "PACE_HOLD_S",
    "PACE_IGNORE_TILES",
    "pace_gap",
]
