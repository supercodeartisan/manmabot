"""Travel/search ground clicks: NORMAL cursor + local tile ring fallbacks."""
from __future__ import annotations

from app._03_world import Position
from app._03_world.world_coords import (
    content_to_world,
    in_battle_click_region,
    world_to_content,
)
from app._04_decision import player_mode as pm


def _chebyshev_content_ring(
    primary: Position,
    cx: int,
    cy: int,
    radius: float,
) -> list[Position]:
    """Primary content point, then in-view tile centers at Chebyshev 1..floor(r)."""
    out: list[Position] = [primary]
    seen: set[tuple[int, int]] = {(int(cx), int(cy))}
    for dist in range(1, max(0, int(radius)) + 1):
        offsets: list[tuple[int, int]] = []
        for dy in range(-dist, dist + 1):
            for dx in range(-dist, dist + 1):
                if max(abs(dx), abs(dy)) != dist:
                    continue
                offsets.append((dx, dy))
        # Cardinals first so the attack cursor is usually found sooner.
        offsets.sort(key=lambda p: (int(p[0] != 0 and p[1] != 0), abs(p[0]) + abs(p[1])))
        ring: list[Position] = []
        for dx, dy in offsets:
            nx, ny = int(cx) + dx, int(cy) + dy
            if (nx, ny) in seen:
                continue
            if not in_battle_click_region(nx, ny):
                continue
            seen.add((nx, ny))
            ring.append(world_to_content(float(nx), float(ny)))
        out.extend(ring)
    return out


def _fractional_content_ring(cx: float, cy: float, radius: float) -> list[Position]:
    """Eight points on the Chebyshev square of ``radius`` (half-tile support)."""
    r = float(radius)
    if r <= 0:
        return []
    offsets = (
        (0.0, -r), (r, -r), (r, 0.0), (r, r),
        (0.0, r), (-r, r), (-r, 0.0), (-r, -r),
    )
    out: list[Position] = []
    seen: set[tuple[int, int]] = set()
    for dx, dy in offsets:
        nx, ny = float(cx) + dx, float(cy) + dy
        key = (round(nx * 2), round(ny * 2))
        if key in seen:
            continue
        if abs(nx) < 1e-6 and abs(ny) < 1e-6:
            continue
        if not in_battle_click_region(nx, ny):
            continue
        seen.add(key)
        out.append(world_to_content(nx, ny))
    return out


def content_destinations_ring(
    primary: Position,
    radius: int | None = None,
) -> list[Position]:
    """Primary content dest, then Chebyshev rings of in-view relative tiles.

    Ring order is near→far. Used when the planned hop sits under a non-NORMAL
    cursor (monster / NPC / door); action tries these until one verifies.
    """
    if radius is None:
        radius = pm.TRAVEL_CURSOR_FALLBACK_RADIUS
    center = content_to_world(primary.x, primary.y)
    return _chebyshev_content_ring(
        primary, int(center.x), int(center.y), int(radius)
    )


def object_cursor_search_destinations(
    obj: object,
    radius: int | None = None,
) -> list[Position]:
    """Screen UV of ``obj``, its memory cell, then a tight fractional hunt.

    The memory cell must be probed: marking it ``seen`` and only walking
    neighbors skipped the monster when it stood next to the player (the
    projected UV often lands on the local character).
    """
    if radius is None:
        radius = pm.ATTACK_CURSOR_SEARCH_TILES
    radius = float(radius)
    pos = getattr(obj, "position", None)
    primary = Position(
        x=float(getattr(pos, "x", 0.0) or 0.0),
        y=float(getattr(pos, "y", 0.0) or 0.0),
    )
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    if rx is not None and ry is not None:
        cx, cy = int(rx), int(ry)
    else:
        tile = content_to_world(primary.x, primary.y)
        cx, cy = int(tile.x), int(tile.y)

    out: list[Position] = [primary]
    seen: set[tuple[int, int]] = set()

    def add_tile(tx: int, ty: int) -> None:
        key = (int(tx), int(ty))
        if key in seen or key == (0, 0):
            return
        if not in_battle_click_region(key[0], key[1]):
            return
        seen.add(key)
        out.append(world_to_content(float(key[0]), float(key[1])))

    add_tile(cx, cy)
    for dest in _chebyshev_content_ring(primary, cx, cy, int(radius))[1:]:
        tile = content_to_world(dest.x, dest.y)
        add_tile(int(tile.x), int(tile.y))
    frac = radius - int(radius)
    if frac > 1e-6:
        out.extend(_fractional_content_ring(float(cx), float(cy), radius))
    return out


def relative_tile_of_content(content: Position) -> tuple[int, int]:
    tile = content_to_world(content.x, content.y)
    return int(tile.x), int(tile.y)


__all__ = [
    "content_destinations_ring",
    "object_cursor_search_destinations",
    "relative_tile_of_content",
]
