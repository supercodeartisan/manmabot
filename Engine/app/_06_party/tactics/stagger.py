"""Per-member attack delays inside one volley.

Each member gets a distinct delay in ``[lo_ms, hi_ms]`` with at least
``min_gap_ms`` between any two, assigned in a shuffled order so the same
member is not always first.
"""
from __future__ import annotations

import random
from typing import Optional, Sequence


def stagger_delays(
    names: Sequence[str],
    rng: Optional[random.Random] = None,
    *,
    lo_ms: float = 10.0,
    hi_ms: float = 40.0,
    min_gap_ms: float = 5.0,
) -> dict[str, float]:
    """Return ``{name: delay_seconds}``."""
    n = len(names)
    if n == 0:
        return {}
    r = rng if rng is not None else random.Random()
    lo = max(0.0, float(lo_ms))
    hi = max(lo, float(hi_ms))
    gap = max(0.0, float(min_gap_ms))
    if n > 1:
        gap = min(gap, (hi - lo) / (n - 1))
    room = hi - lo - gap * (n - 1)
    picks = sorted(r.uniform(0.0, room) for _ in range(n))
    delays = [lo + p + i * gap for i, p in enumerate(picks)]
    order = list(names)
    r.shuffle(order)
    return {name: delays[i] / 1000.0 for i, name in enumerate(order)}


__all__ = ["stagger_delays"]
