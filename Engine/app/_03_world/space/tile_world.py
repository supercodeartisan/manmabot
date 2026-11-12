"""Nav tile ↔ game world coordinate for one already loaded map pack.

A stored hunt coordinate is a nav tile: one cell of the walk grid after the
pack image has been downsampled by ``pixel_scale``. One nav tile is one game
world step. ``pixel_scale`` counts image pixels per tile. It is not a
multiplier on the world coordinate.

    world_x = origin_x + tile_x
    world_y = origin_y + tile_y
    tile_x = world_x - origin_x
    tile_y = world_y - origin_y

This is the same pair as ``WalkGrid.nav_to_world`` / ``world_to_nav`` and
``pack_ids.nav_to_abs`` / ``abs_to_nav``. Y increases in the same direction
in the game, the nav grid, and the map image. The map editor draws a marker
at the tile center (tile + 0.5) but the stored value is the integer tile.

The pack object is the folder the editor already opened. A numeric game map
id is never used to pick an origin, so two packs that share a map id cannot
swap origins here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PackAxes:
    """Origin of nav tile (0, 0), plus the image scale that produced the tile."""

    pack_id: str
    origin_x: int
    origin_y: int
    pixel_scale: int

    def tile_to_world(self, tile_x: int, tile_y: int) -> tuple[int, int]:
        return self.origin_x + int(tile_x), self.origin_y + int(tile_y)

    def world_to_tile(self, world_x: int, world_y: int) -> tuple[int, int]:
        return int(world_x) - self.origin_x, int(world_y) - self.origin_y


def axes_from_pack(pack: Any) -> PackAxes | None:
    """Axes for this pack instance. ``None`` when the origin is not on the pack.

    Does not search other packs, and does not substitute another map's origin.
    """
    if pack is None:
        return None
    try:
        origin_x = pack.origin_x
        origin_y = pack.origin_y
        pixel_scale = pack.pixel_scale
    except AttributeError:
        return None
    if origin_x is None or origin_y is None or pixel_scale is None:
        return None
    try:
        ox, oy, scale = int(origin_x), int(origin_y), int(pixel_scale)
    except (TypeError, ValueError):
        return None
    if scale < 1:
        return None
    pack_id = str(getattr(pack, "id", "") or getattr(pack, "pack_id", "") or "").strip()
    if not pack_id:
        return None
    return PackAxes(pack_id, ox, oy, scale)


def raw_map_id_from_pack(pack: Any) -> int | None:
    """Numeric ``raw_map`` from this pack's own ``meta.yaml``.

    The pack is the folder already opened. This does not look up a pack by
    numeric id, and it does not treat the folder name as a game map id.
    ``None`` when the file or the field is missing.
    """
    root = getattr(pack, "root", None)
    if root is None:
        return None
    path = Path(root) / "meta.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        body = line.split("#", 1)[0].strip()
        if not body.startswith("raw_map:"):
            continue
        token = body.split(":", 1)[1].strip().strip("\"'")
        if token.lstrip("-").isdigit():
            return int(token)
        return None
    return None


def parse_world_int(text: str) -> int | None:
    """One integer token. Rejects blanks, decimals, and trailing junk."""
    body = str(text).strip()
    if not body:
        return None
    sign = 1
    if body[0] in "+-":
        if body[0] == "-":
            sign = -1
        body = body[1:]
    if not body.isdigit():
        return None
    return sign * int(body)


def stored_world_tuple(axes: PackAxes | None, area: dict) -> tuple[int, ...] | None:
    """World numbers for one stored mark. ``None`` when the origin or fields are missing.

    A point is ``(x, y)``. A rectangle is ``(x0, y0, x1, y1)``. The dict is not written.
    """
    if axes is None or not isinstance(area, dict):
        return None
    shape = str(area.get("shape") or "").strip().lower()
    try:
        if shape == "point":
            tile_x = int(area["x"] if "x" in area else area["x0"])
            tile_y = int(area["y"] if "y" in area else area["y0"])
            return axes.tile_to_world(tile_x, tile_y)
        x0, y0 = int(area["x0"]), int(area["y0"])
        x1, y1 = int(area["x1"]), int(area["y1"])
    except (KeyError, TypeError, ValueError):
        return None
    ax0, ay0 = axes.tile_to_world(x0, y0)
    ax1, ay1 = axes.tile_to_world(x1, y1)
    return (ax0, ay0, ax1, ay1)


def stored_world_note(axes: PackAxes | None, area: dict, *, unavailable: str) -> str:
    """Display text for one stored area or point. Does not write ``area``."""
    numbers = stored_world_tuple(axes, area)
    if numbers is None:
        return unavailable
    if len(numbers) == 2:
        return f"({numbers[0]}, {numbers[1]})"
    return f"({numbers[0]}, {numbers[1]} ~ {numbers[2]}, {numbers[3]})"


def clamp_popup_top_left(
    anchor_x: int,
    anchor_y: int,
    popup_w: int,
    popup_h: int,
    view_left: int,
    view_top: int,
    view_right: int,
    view_bottom: int,
) -> tuple[int, int]:
    """Keep a popup's top-left on ``anchor`` unless that would leave the view.

    The view edges are inclusive. A popup larger than the view keeps its
    top-left on the view's top-left.
    """
    x, y = int(anchor_x), int(anchor_y)
    width = max(1, int(popup_w))
    height = max(1, int(popup_h))
    if x + width - 1 > int(view_right):
        x = int(view_right) - width + 1
    if y + height - 1 > int(view_bottom):
        y = int(view_bottom) - height + 1
    if x < int(view_left):
        x = int(view_left)
    if y < int(view_top):
        y = int(view_top)
    return x, y
