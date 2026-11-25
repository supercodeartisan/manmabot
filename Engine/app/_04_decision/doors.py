"""Legacy door helpers. Live room-door control lives in ``door_navigation``.

These wrappers keep TerrainMap sealing and open-door retarget working for
callers that have not switched to ``handle_door_navigation`` yet. The cache
is filled by ``refresh_live_doors`` and by the door-navigation module.
"""
from __future__ import annotations

from typing import Any, Optional

_DOORS: tuple[tuple[int, int, str], ...] = ()
_WALLS: frozenset[tuple[int, int]] = frozenset()
_STATES = ("open", "close", "not_permitted", "unknown")


def tile_sealed(x: int, y: int) -> bool:
    """True when a live door at this nav tile cannot be opened."""
    return (int(x), int(y)) in _WALLS


def refresh_live_doors(snapshot: dict[str, Any] | None) -> None:
    """Replace the door list from one print_state frame."""
    global _DOORS, _WALLS
    from app._04_decision.door_navigation.snapshot import parse_doors, seal_tiles

    doors = parse_doors(snapshot)
    _DOORS = tuple((d.tile[0], d.tile[1], d.state.value) for d in doors)
    _WALLS = seal_tiles(doors)


def door_state_near(x: int, y: int, radius: int = 1) -> str | None:
    """State of the closest door within Chebyshev ``radius``, else None."""
    best: str | None = None
    best_d = int(radius) + 1
    ax, ay = int(x), int(y)
    for dx, dy, state in _DOORS:
        dist = max(abs(dx - ax), abs(dy - ay))
        if dist < best_d:
            best_d = dist
            best = state
    return best


def cursor_on_door_action(state: str | None) -> str:
    """What a door cursor at ``state`` may do: ``open``, ``redirect``, or ``wall``."""
    if state == "close":
        return "open"
    if state == "not_permitted":
        return "wall"
    return "redirect"


def door_state_at(x: int, y: int) -> str | None:
    """State of a door standing on this nav tile, else None."""
    ax, ay = int(x), int(y)
    for dx, dy, state in _DOORS:
        if dx == ax and dy == ay:
            return state
    return None


def closed_door_before_click(
    guide: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    start: tuple[int, int],
    click: tuple[int, int] | None,
) -> tuple[int, int] | None:
    """First ``close`` door on the guide from ``start`` through ``click``."""
    from app._04_decision.door_navigation.snapshot import door_on_guide
    from app._04_decision.door_navigation.types import DoorState

    doors_list = [_cache_record(x, y, state) for x, y, state in _DOORS]
    found = door_on_guide(
        doors_list,
        [(int(a), int(b)) for a, b in guide],
        (int(start[0]), int(start[1])),
        None if click is None else (int(click[0]), int(click[1])),
        radius=0,
    )
    if found is None or found.state is not DoorState.CLOSED:
        return None
    return found.tile


def retarget_open_door(
    guide: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    start: tuple[int, int],
    click: tuple[int, int] | None,
    max_hop: int | None,
) -> tuple[tuple[int, int] | None, bool]:
    """Click the guide tile after an open door this hop would pass."""
    from app._04_decision.door_navigation.snapshot import (
        door_on_guide,
        tile_past_door,
    )
    from app._04_decision.door_navigation.types import DoorState

    doors_list = [_cache_record(x, y, state) for x, y, state in _DOORS]
    guide_tiles = [(int(a), int(b)) for a, b in guide]
    start_t = (int(start[0]), int(start[1]))
    click_t = None if click is None else (int(click[0]), int(click[1]))
    door = door_on_guide(doors_list, guide_tiles, start_t, click_t, radius=0)
    if door is None or door.state is not DoorState.OPEN:
        return click, False
    # Click already beyond the door: leave it.
    if click_t is not None:
        try:
            door_i = min(
                (
                    (max(abs(tile[0] - door.tile[0]), abs(tile[1] - door.tile[1])), i)
                    for i, tile in enumerate(guide_tiles)
                ),
                key=lambda pair: pair[0],
            )[1]
            click_i = guide_tiles.index(click_t)
            if click_i > door_i:
                return click, False
        except (ValueError, IndexError):
            pass
    past = tile_past_door(guide_tiles, door.tile, doors_list)
    if past is None:
        return None, True
    sx, sy = start_t
    if max_hop is None:
        if click_t is None:
            return past, True
        limit = max(abs(click_t[0] - sx), abs(click_t[1] - sy))
    else:
        limit = int(max_hop)
    dist = max(abs(past[0] - sx), abs(past[1] - sy))
    door_dist = max(abs(door.tile[0] - sx), abs(door.tile[1] - sy))
    if dist > limit and dist > door_dist + 1:
        return None, True
    return past, True


def tiles_after(
    guide: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    tile: tuple[int, int],
    *,
    count: int = 2,
) -> list[tuple[int, int]]:
    """Guide tiles strictly after ``tile``, at most ``count``."""
    from app._04_decision.door_navigation.snapshot import find_door_at

    doors_list = [_cache_record(x, y, state) for x, y, state in _DOORS]
    target = (int(tile[0]), int(tile[1]))
    tiles = [(int(raw[0]), int(raw[1])) for raw in guide]
    for index, item in enumerate(tiles):
        if item != target:
            continue
        out: list[tuple[int, int]] = []
        for step in tiles[index + 1 :]:
            if find_door_at(doors_list, step, radius=0) is not None:
                if door_state_at(step[0], step[1]) == "open":
                    continue
            if door_state_at(step[0], step[1]) == "open":
                continue
            out.append(step)
            if len(out) >= int(count):
                break
        return out
    return []


def _cache_record(x: int, y: int, state: str):
    from app._04_decision.door_navigation.types import DoorRecord, DoorState

    token = str(state or "").strip().lower()
    mapped = {
        "open": DoorState.OPEN,
        "close": DoorState.CLOSED,
        "not_permitted": DoorState.NOT_PERMITTED,
        "unknown": DoorState.UNKNOWN,
    }.get(token, DoorState.UNKNOWN)
    return DoorRecord(tile=(int(x), int(y)), state=mapped, world=(int(x), int(y)))
