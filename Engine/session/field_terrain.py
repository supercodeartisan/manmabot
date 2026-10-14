"""Walk / wall / unknown tiles around the player, for the field view.

Reads the pack ``nav.png`` only. Does not build a pathfinding terrain map.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# 0 wall, 1 walk, 2 unknown (nav.png red).
_WALL = 0
_WALK = 1
_UNKNOWN = 2
_NAMES = ("wall", "walk", "unknown")

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def _pack(map_id: str):
    from app._03_world.space.map_pack import load_map_pack, resolve_maps_dir
    from session.paths import manmabot_root

    mid = str(map_id or "").strip() or "talking_island"
    maps_dir = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
    if maps_dir is None:
        maps_dir = manmabot_root() / "data" / "maps"
    return load_map_pack(maps_dir, mid)


def _kinds(map_id: str):
    """uint8 grid, row = nav y, col = nav x. None when the pack has no image."""
    import numpy as np
    from PIL import Image

    try:
        pack = _pack(map_id)
    except Exception:
        return None
    path = Path(pack.terrain_path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(pack.id)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    except Exception:
        return None
    h, w, _ = rgb.shape
    scale = max(1, int(pack.pixel_scale))
    # Classify full-res pixels first, then majority-downsample (fence_bw
    # puts 1 px black strips on open tiles; top-left-only would mislabel them).
    walk = (rgb[:, :, 0] == 255) & (rgb[:, :, 1] == 255) & (rgb[:, :, 2] == 255)
    unknown = (rgb[:, :, 0] == 255) & (rgb[:, :, 1] == 0) & (rgb[:, :, 2] == 0)
    if scale > 1:
        th, tw = h // scale, w // scale
        if th < 1 or tw < 1:
            return None
        walk = walk[: th * scale, : tw * scale]
        unknown = unknown[: th * scale, : tw * scale]
        walk = walk.reshape(th, scale, tw, scale).mean(axis=(1, 3)) >= 0.5
        unknown = unknown.reshape(th, scale, tw, scale).mean(axis=(1, 3)) >= 0.5
    kind = np.zeros(walk.shape, dtype=np.uint8)
    kind[walk] = _WALK
    kind[unknown & ~walk] = _UNKNOWN
    with _lock:
        _cache[key] = (mtime, kind)
    return kind


def terrain_cells(map_id: str, origin: Any, radius: int) -> list[tuple[int, int, str]]:
    """Tiles within ``radius`` of the player's nav cell.

    Offsets are player-relative game tiles, matching field-view dots.
    """
    if origin is None:
        return []
    try:
        ox, oy = int(origin[0]), int(origin[1])
    except (TypeError, ValueError, IndexError):
        return []
    span = max(1, min(int(radius), 48))
    grid = _kinds(map_id)
    if grid is None:
        return []
    height, width = grid.shape
    cells: list[tuple[int, int, str]] = []
    y0 = max(0, oy - span)
    y1 = min(height, oy + span + 1)
    x0 = max(0, ox - span)
    x1 = min(width, ox + span + 1)
    window = grid[y0:y1, x0:x1]
    for iy in range(window.shape[0]):
        row = window[iy]
        for ix in range(window.shape[1]):
            cells.append((x0 + ix - ox, y0 + iy - oy, _NAMES[int(row[ix])]))
    return cells
