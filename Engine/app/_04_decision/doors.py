"""Live door tiles from the print_state snapshot.

``not_permitted`` tiles are walls for pathfinding. A door cursor clicks only
when the nearest door is ``close``. ``open`` and ``unknown`` skip that point.
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
    found: list[tuple[int, int, str]] = []
    for row in _entity_rows(snapshot):
        if not _is_door_row(row):
            continue
        tile = _nav_tile(row)
        if tile is None:
            continue
        found.append((tile[0], tile[1], _state_of(row)))
    _DOORS = tuple(found)
    _WALLS = frozenset(tile for tile in ((x, y) for x, y, state in found if state == "not_permitted"))


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


def retarget_open_door(
    guide: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    start: tuple[int, int],
    click: tuple[int, int] | None,
    max_hop: int | None,
) -> tuple[tuple[int, int] | None, bool]:
    """Click the guide tile after an open door this hop would pass.

    Returns ``(tile, replaced)``. ``replaced`` is false when this hop does not
    cross an open door. ``replaced`` true and ``tile`` None means the doorway
    cannot be cleared inside the hop, so the caller must not click a side tile.
    The tile just past the door may be one step beyond ``max_hop``.
    """
    sx, sy = int(start[0]), int(start[1])
    if click is None and max_hop is None:
        return click, False
    if click is not None and max_hop is None:
        limit = max(abs(int(click[0]) - sx), abs(int(click[1]) - sy))
    else:
        limit = int(max_hop) if max_hop is not None else 0
    seen_start = False
    door_i: int | None = None
    click_i: int | None = None
    click_t = (int(click[0]), int(click[1])) if click is not None else None
    tiles = [(int(raw[0]), int(raw[1])) for raw in guide]
    for index, tile in enumerate(tiles):
        if tile == (sx, sy):
            seen_start = True
            if click_t == tile:
                click_i = index
            continue
        if not seen_start and tiles and tiles[0] != (sx, sy):
            # Guide may already begin at the character without repeating it.
            seen_start = True
        if not seen_start:
            continue
        if click_t == tile and click_i is None:
            click_i = index
        dist = max(abs(tile[0] - sx), abs(tile[1] - sy))
        if dist > limit:
            break
        if door_state_at(tile[0], tile[1]) == "open":
            door_i = index
    if door_i is None:
        return click, False
    if click_i is not None and click_i > door_i:
        return click, False
    for index in range(door_i + 1, len(tiles)):
        tile = tiles[index]
        if door_state_at(tile[0], tile[1]) == "open":
            continue
        dist = max(abs(tile[0] - sx), abs(tile[1] - sy))
        if dist > limit + (index - door_i):
            return None, True
        return tile, True
    return None, True


def tiles_after(
    guide: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    tile: tuple[int, int],
    *,
    count: int = 2,
) -> list[tuple[int, int]]:
    """Guide tiles strictly after ``tile``, at most ``count``."""
    target = (int(tile[0]), int(tile[1]))
    tiles = [(int(raw[0]), int(raw[1])) for raw in guide]
    for index, item in enumerate(tiles):
        if item != target:
            continue
        out: list[tuple[int, int]] = []
        for step in tiles[index + 1 :]:
            if door_state_at(step[0], step[1]) == "open":
                continue
            out.append(step)
            if len(out) >= int(count):
                break
        return out
    return []


def _entity_rows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("entities")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _is_door_row(row: dict[str, Any]) -> bool:
    if str(row.get("door") or "").strip():
        return True
    if str(row.get("class") or "") != "InteractiveNPC":
        return False
    if str(row.get("name") or "") == "Door":
        return True
    try:
        return int(row.get("species") or 0) == 8
    except (TypeError, ValueError):
        return False


def _state_of(row: dict[str, Any]) -> str:
    token = str(row.get("door") or "").strip().lower()
    if token in _STATES:
        return token
    return "unknown"


def _nav_tile(row: dict[str, Any]) -> Optional[tuple[int, int]]:
    world = row.get("world")
    if not isinstance(world, dict):
        return None
    try:
        cx = int(world.get("cx"))
        cy = int(world.get("cy"))
    except (TypeError, ValueError):
        return None
    from app._03_world.merge.memory_sync import game_to_nav

    return game_to_nav(cx, cy)
