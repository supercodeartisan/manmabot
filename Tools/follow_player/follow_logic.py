"""Pure follow rules: when to walk, when to hunt, which empty tile to aim at.

A monster whose attack target is me or the followed player is chosen before
ordinary hunting. Guid compare lives here so it can be tested without a DLL.

The live tool reads these numbers from the GUI every tick, so a pause and an
edit apply on the next check without restarting the window.
"""
from __future__ import annotations

import random
from typing import Callable, Iterable, Optional


def action_kind(distance: int, follow_tiles: int, attack_tiles: int) -> str:
    """``follow`` when far, ``hunt`` when close, ``hold`` in the gap.

    If the two thresholds overlap, catching up wins: do not stop to fight
    while the followed player is still at or beyond the follow distance.
    """
    dist = int(distance)
    if dist >= int(follow_tiles):
        return "follow"
    if dist <= int(attack_tiles):
        return "hunt"
    return "hold"


def tiles_in_radius(
    cx: int,
    cy: int,
    radius: int,
    *,
    include_center: bool = False,
) -> list[tuple[int, int]]:
    """Chebyshev disk around ``(cx, cy)``. Center is the followed player."""
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
    """Random walkable tile within ``radius`` of the followed player.

    Keeps ``previous`` while it is still inside the disk and still empty, so
    a 0.5s recheck does not pick a new goal every time the player shuffles.
    The player's own tile is never a candidate.
    """
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


_STRIKE_CLASSES = frozenset({"Monster", "SummonedMonster"})


def guid_key(value: object) -> Optional[int]:
    """Normalize ``0x...`` / decimal guid text. ``0`` and blank are absent."""
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def within_chebyshev(
    ax: int,
    ay: int,
    bx: int,
    by: int,
    limit: int,
) -> bool:
    """True when the two tiles are at most ``limit`` apart (Chebyshev)."""
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by))) <= int(limit)


def strike_hits(row: object, wanted: set[int]) -> bool:
    """True when this monster swing's target guid is me or the followed player."""
    if not isinstance(row, dict) or not wanted:
        return False
    if str(row.get("class") or "") not in _STRIKE_CLASSES:
        return False
    key = guid_key(row.get("tgt"))
    return key is not None and key in wanted
