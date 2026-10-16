"""Pure follow geometry: hysteresis kind + approach tile (never on leader)."""
from __future__ import annotations

import random
from typing import Callable, Iterable, Optional


def follow_kind(
    distance: int,
    *,
    follow_start: int,
    follow_stop: int,
    chasing: bool,
) -> tuple[str, bool]:
    """Return ``(kind, chasing)`` where kind is follow|near.

    ``follow`` while far or still closing the hysteresis band.
    ``near`` when within ``follow_stop`` (eligible for assist/hold).
    """
    dist = int(distance)
    start = max(1, int(follow_start))
    stop = max(0, min(start, int(follow_stop)))
    if chasing:
        if dist > stop:
            return "follow", True
        return "near", False
    if dist >= start:
        return "follow", True
    return "near", False


def tiles_in_radius(
    cx: int,
    cy: int,
    radius: int,
    *,
    include_center: bool = False,
) -> list[tuple[int, int]]:
    r = max(0, int(radius))
    out: list[tuple[int, int]] = []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if max(abs(dx), abs(dy)) > r:
                continue
            if dx == 0 and dy == 0 and not include_center:
                continue
            out.append((int(cx) + dx, int(cy) + dy))
    return out


def choose_approach_tile(
    is_walkable: Callable[[int, int], bool],
    target: tuple[int, int],
    radius: int,
    occupied: Iterable[tuple[int, int]],
    rng: random.Random,
    previous: Optional[tuple[int, int]] = None,
    *,
    exclude: Iterable[tuple[int, int]] = (),
) -> Optional[tuple[int, int]]:
    """Walkable tile near leader; never the leader's own cell."""
    tx, ty = int(target[0]), int(target[1])
    blocked = {(int(x), int(y)) for x, y in occupied}
    blocked.add((tx, ty))
    blocked.update((int(x), int(y)) for x, y in exclude)

    def ok(tile: tuple[int, int]) -> bool:
        x, y = int(tile[0]), int(tile[1])
        if (x, y) in blocked:
            return False
        if max(abs(x - tx), abs(y - ty)) > int(radius):
            return False
        try:
            return bool(is_walkable(x, y))
        except Exception:
            return False

    if previous is not None and ok(previous):
        return (int(previous[0]), int(previous[1]))
    candidates = [tile for tile in tiles_in_radius(tx, ty, radius) if ok(tile)]
    if not candidates:
        return None
    return rng.choice(candidates)


def guid_key(value: object) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


__all__ = [
    "choose_approach_tile",
    "follow_kind",
    "guid_key",
    "tiles_in_radius",
]
