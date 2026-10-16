"""Pure follow geometry: travel/stop bands + approach tile (never on leader)."""
from __future__ import annotations

import random
from typing import Callable, Iterable, Optional


def follow_kind(
    distance: int,
    *,
    follow_tiles: int = 8,
    stop_tiles: int = 2,
    leader_farming: bool = False,
    leader_stopped: bool = False,
    chasing: bool = False,
    **_legacy: object,
) -> tuple[str, bool]:
    """Return ``(band, chasing)`` where band is follow|near.

    Travel: chase only when farther than ``follow_tiles``.
    Stopped/idle: tighten until within ``stop_tiles``.
    Combat (``leader_farming``): caller handles assist/close-in; here ``near``
    means within the travel leash so policy can assist.
    """
    del chasing, _legacy
    dist = int(distance)
    follow = max(1, int(follow_tiles))
    stop = max(0, min(follow, int(stop_tiles)))
    if leader_farming:
        if dist > follow:
            return "follow", True
        return "near", False
    if dist > follow:
        return "follow", True
    if leader_stopped and dist > stop:
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
    prefer_near: Optional[tuple[int, int]] = None,
) -> Optional[tuple[int, int]]:
    """Walkable tile near target; never the target's own cell.

    Prefers ``previous`` when still valid. Otherwise picks the candidate
    closest to ``prefer_near`` (usually the player) for smoother paths.
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
    if prefer_near is not None:
        px, py = int(prefer_near[0]), int(prefer_near[1])
        return min(
            candidates,
            key=lambda t: (
                max(abs(int(t[0]) - px), abs(int(t[1]) - py)),
                abs(int(t[0]) - tx) + abs(int(t[1]) - ty),
                int(t[0]),
                int(t[1]),
            ),
        )
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
