"""Parse live doors from a print_state snapshot into absolute nav tiles."""
from __future__ import annotations

from typing import Any, Optional

from app._04_decision.door_navigation.types import DoorRecord, DoorState

_TOKEN_MAP = {
    "open": DoorState.OPEN,
    "close": DoorState.CLOSED,
    "closed": DoorState.CLOSED,
    "not_permitted": DoorState.NOT_PERMITTED,
    "unknown": DoorState.UNKNOWN,
}


def parse_doors(snapshot: dict[str, Any] | None) -> list[DoorRecord]:
    """Door rows from one print_state frame. Empty when the snapshot is missing."""
    out: list[DoorRecord] = []
    for row in _entity_rows(snapshot):
        if not _is_door_row(row):
            continue
        world = _world_xy(row)
        tile = _nav_tile(world)
        if world is None or tile is None:
            continue
        gfx = _optional_int(row.get("doorType") or row.get("doorGfx") or row.get("gfx"))
        frame = _optional_int(row.get("doorFrame") or row.get("frame"))
        out.append(
            DoorRecord(
                tile=tile,
                state=_classify_row(row),
                world=world,
                ent=str(row.get("ent") or row.get("guid") or ""),
                name=str(row.get("name") or "Door"),
                species=_species(row),
                gfx=gfx,
                frame=frame,
            )
        )
    return out


def seal_tiles(doors: list[DoorRecord]) -> frozenset[tuple[int, int]]:
    """Absolute nav tiles that must stay walls for pathfinding."""
    return frozenset(d.tile for d in doors if d.state is DoorState.NOT_PERMITTED)


def find_door_at(
    doors: list[DoorRecord],
    tile: tuple[int, int],
    *,
    radius: int = 0,
) -> Optional[DoorRecord]:
    """Closest door within Chebyshev ``radius`` of ``tile``, else None."""
    ax, ay = int(tile[0]), int(tile[1])
    best: Optional[DoorRecord] = None
    best_d = int(radius) + 1
    for door in doors:
        dist = max(abs(door.tile[0] - ax), abs(door.tile[1] - ay))
        if dist < best_d:
            best_d = dist
            best = door
    return best


def door_on_guide(
    doors: list[DoorRecord],
    guide: list[tuple[int, int]],
    start: tuple[int, int],
    click: tuple[int, int] | None,
    *,
    radius: int = 0,
) -> Optional[DoorRecord]:
    """First door on the guide from ``start`` through ``click`` (inclusive)."""
    if click is None:
        return None
    tiles = [(int(x), int(y)) for x, y in guide]
    sx, sy = int(start[0]), int(start[1])
    click_t = (int(click[0]), int(click[1]))
    if click_t == (sx, sy):
        return None
    seen_start = (sx, sy) not in tiles
    reached_click = False
    for tile in tiles:
        if tile == (sx, sy):
            seen_start = True
            continue
        if not seen_start:
            if tiles and tiles[0] != (sx, sy):
                seen_start = True
            else:
                continue
        door = find_door_at(doors, tile, radius=radius)
        if door is not None:
            return door
        if tile == click_t:
            reached_click = True
            break
    if not reached_click and click_t not in tiles and radius > 0:
        return find_door_at(doors, click_t, radius=radius)
    return None


def tile_past_door(
    guide: list[tuple[int, int]],
    door_tile: tuple[int, int],
    doors: list[DoorRecord],
) -> Optional[tuple[int, int]]:
    """First non-door guide tile strictly after the door cell on ``guide``."""
    target = (int(door_tile[0]), int(door_tile[1]))
    tiles = [(int(x), int(y)) for x, y in guide]
    door_i: Optional[int] = None
    best_d = 3
    for index, item in enumerate(tiles):
        dist = max(abs(item[0] - target[0]), abs(item[1] - target[1]))
        if dist < best_d:
            best_d = dist
            door_i = index
    if door_i is None:
        return None
    for step in tiles[door_i + 1 :]:
        if find_door_at(doors, step, radius=0) is not None:
            continue
        return step
    return None


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


def _classify_row(row: dict[str, Any]) -> DoorState:
    token = str(row.get("door") or "").strip().lower()
    return _TOKEN_MAP.get(token, DoorState.UNKNOWN)


def _world_xy(row: dict[str, Any]) -> Optional[tuple[int, int]]:
    world = row.get("world")
    if not isinstance(world, dict):
        return None
    try:
        return int(world.get("cx")), int(world.get("cy"))
    except (TypeError, ValueError):
        return None


def _nav_tile(world: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
    if world is None:
        return None
    from app._03_world.merge.memory_sync import game_to_nav

    return game_to_nav(world[0], world[1])


def _species(row: dict[str, Any]) -> int:
    try:
        return int(row.get("species") or 8)
    except (TypeError, ValueError):
        return 8


def _optional_int(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, str) and raw.lower().startswith("0x"):
            return int(raw, 16)
        return int(raw)
    except (TypeError, ValueError):
        return None
