"""Terrain / walkability map for absolute-world navigation.

Expected PNG layout (when you export the painted map):
  - By default one pixel = one world tile (``pixel_scale=1``).
  - ``pixel_scale=N`` means each N×N pixel block is one WCS tile
    (``nav.png`` uses 4×4).
  - Default color legend (RGB):
      walkable : (255, 255, 255) white
      blocked  : (0, 0, 0) black
      blocked  : (255, 0, 0) red   # unknown / unmapped outside (not pathable)
  - Other colors are treated as blocked unless listed in ``color_legend``.

Prefer ``navigation.maps_dir`` + ``active_map`` (see ``map_pack``).
Legacy: set ``navigation.terrain_map`` to a PNG path.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable, Optional, Union

import numpy as np

# RGB -> walkable flag. Extend when your map uses more terrain classes.
DEFAULT_COLOR_LEGEND: dict[tuple[int, int, int], bool] = {
    (255, 255, 255): True,   # known walkable
    (0, 0, 0): False,        # blocked walls / water / etc.
    (255, 0, 0): False,      # unknown / outside (not pathable)
}

# Soft clearance: tiles this far (Chebyshev) from walls stay cheap.
DEFAULT_CLEARANCE_TILES = 2
DEFAULT_WALL_PENALTY = 4


def _chebyshev_dist_to_blocked(walkable: np.ndarray) -> np.ndarray:
    """Chebyshev distance from each tile to the nearest blocked tile.

    Fully walkable maps have no blocked seed, so every tile gets a large
    distance (open-field step cost stays 1).
    """
    if walkable.size == 0:
        return np.zeros(walkable.shape, dtype=np.int32)
    if bool(np.all(walkable)):
        inf = max(int(walkable.shape[0]), int(walkable.shape[1]), 1)
        return np.full(walkable.shape, inf, dtype=np.int32)
    from scipy.ndimage import distance_transform_cdt

    return distance_transform_cdt(walkable, metric="chessboard").astype(np.int32)


def _build_clearance_and_costs(
    walkable: np.ndarray,
    clearance_tiles: int,
    wall_penalty: int,
) -> tuple[np.ndarray, np.ndarray]:
    """``clearance`` is 0 for tiles 8-adjacent to blocked (or blocked)."""
    dist_blocked = _chebyshev_dist_to_blocked(walkable)
    clearance = np.maximum(dist_blocked - 1, 0).astype(np.int32)
    clearance = np.where(walkable, clearance, 0).astype(np.int32)
    deficit = np.maximum(0, int(clearance_tiles) - clearance)
    costs = (1 + int(wall_penalty) * deficit).astype(np.int32)
    costs = np.where(walkable, costs, 0).astype(np.int32)
    return clearance, costs


class TileKind(IntEnum):
    BLOCKED = 0
    WALKABLE = 1


@dataclass
class TerrainMap:
    """Discrete absolute-world grid of walkable / blocked tiles."""

    walkable: np.ndarray  # bool array shape (height, width), row=y, col=x
    clearance: Optional[np.ndarray] = None  # dist_to_wall; 0 = 8-adjacent to blocked
    costs: Optional[np.ndarray] = None
    clearance_tiles: int = DEFAULT_CLEARANCE_TILES
    wall_penalty: int = DEFAULT_WALL_PENALTY

    def __post_init__(self) -> None:
        if self.clearance is None or self.costs is None:
            self.clearance, self.costs = _build_clearance_and_costs(
                self.walkable, self.clearance_tiles, self.wall_penalty
            )

    @property
    def width(self) -> int:
        return int(self.walkable.shape[1])

    @property
    def height(self) -> int:
        return int(self.walkable.shape[0])

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return bool(self.walkable[y, x])

    def dist_to_wall(self, x: int, y: int) -> int:
        """Chebyshev rings from blocked: 0 means 8-adjacent (or blocked / OOB)."""
        if not self.in_bounds(x, y) or self.clearance is None:
            return 0
        return int(self.clearance[y, x])

    def tile_cost(self, x: int, y: int) -> int:
        """A* step cost to *enter* ``(x, y)``. Unwalkable / OOB → 0 (unused)."""
        if not self.is_walkable(x, y) or self.costs is None:
            return 0
        return int(self.costs[y, x])

    def submap(self, x0: int, y0: int, x1: int, y1: int) -> "TerrainMap":
        """Window view that keeps precomputed clearance/costs (no recompute)."""
        clr = None if self.clearance is None else self.clearance[y0:y1, x0:x1]
        cst = None if self.costs is None else self.costs[y0:y1, x0:x1]
        return TerrainMap(
            walkable=self.walkable[y0:y1, x0:x1],
            clearance=clr,
            costs=cst,
            clearance_tiles=self.clearance_tiles,
            wall_penalty=self.wall_penalty,
        )

    def neighbors8(self, x: int, y: int) -> Iterable[tuple[int, int]]:
        """8-connected walkable neighbors (Chebyshev steps)."""
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.is_walkable(nx, ny):
                    yield nx, ny

    @classmethod
    def from_array(
        cls,
        walkable: np.ndarray,
        *,
        clearance_tiles: int = DEFAULT_CLEARANCE_TILES,
        wall_penalty: int = DEFAULT_WALL_PENALTY,
        clearance: Optional[np.ndarray] = None,
        costs: Optional[np.ndarray] = None,
    ) -> "TerrainMap":
        arr = np.asarray(walkable, dtype=bool)
        if arr.ndim != 2:
            raise ValueError("walkable array must be 2-D (height, width)")
        return cls(
            walkable=arr,
            clearance=clearance,
            costs=costs,
            clearance_tiles=clearance_tiles,
            wall_penalty=wall_penalty,
        )

    @classmethod
    def from_png(
        cls,
        path: Union[str, Path],
        color_legend: Optional[dict[tuple[int, int, int], bool]] = None,
        pixel_scale: int = 1,
        clearance_tiles: int = DEFAULT_CLEARANCE_TILES,
        wall_penalty: int = DEFAULT_WALL_PENALTY,
    ) -> "TerrainMap":
        """Load a PNG; ``pixel_scale`` pixels per WCS tile on each axis."""
        from PIL import Image

        if pixel_scale < 1:
            raise ValueError("pixel_scale must be >= 1")

        legend = color_legend if color_legend is not None else DEFAULT_COLOR_LEGEND
        img = Image.open(path).convert("RGB")
        pixels = np.asarray(img, dtype=np.uint8)
        h, w, _ = pixels.shape
        walkable = np.zeros((h, w), dtype=bool)
        for rgb, is_walk in legend.items():
            if not is_walk:
                continue
            mask = (
                (pixels[:, :, 0] == rgb[0])
                & (pixels[:, :, 1] == rgb[1])
                & (pixels[:, :, 2] == rgb[2])
            )
            walkable |= mask

        if pixel_scale > 1:
            th, tw = h // pixel_scale, w // pixel_scale
            if th < 1 or tw < 1:
                raise ValueError(
                    f"image {w}x{h} is smaller than pixel_scale={pixel_scale}"
                )
            blocks = walkable[: th * pixel_scale, : tw * pixel_scale]
            blocks = blocks.reshape(th, pixel_scale, tw, pixel_scale)
            # Majority of the N×N block walkable -> walkable tile.
            walkable = blocks.mean(axis=(1, 3)) >= 0.5
        return cls.from_array(
            walkable,
            clearance_tiles=clearance_tiles,
            wall_penalty=wall_penalty,
        )

    @classmethod
    def from_npy(
        cls,
        path: Union[str, Path],
        *,
        clearance_tiles: int = DEFAULT_CLEARANCE_TILES,
        wall_penalty: int = DEFAULT_WALL_PENALTY,
    ) -> "TerrainMap":
        """Load a bool / 0-1 array saved with ``numpy.save``."""
        arr = np.load(path)
        return cls.from_array(
            arr.astype(bool),
            clearance_tiles=clearance_tiles,
            wall_penalty=wall_penalty,
        )


_current: Optional[TerrainMap] = None


def get_terrain_map() -> Optional[TerrainMap]:
    return _current


def set_terrain_map(terrain: Optional[TerrainMap]) -> None:
    global _current
    _current = terrain


def configure_terrain_map(config: Optional[dict] = None) -> Optional[TerrainMap]:
    """Load terrain from ``config['navigation']['terrain_map']`` if set."""
    section = (config or {}).get("navigation") or {}
    path = section.get("terrain_map")
    if not path:
        set_terrain_map(None)
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"navigation.terrain_map not found: {p}")
    pixel_scale = int(section.get("pixel_scale", 1))
    clearance_tiles = int(section.get("clearance_tiles", DEFAULT_CLEARANCE_TILES))
    wall_penalty = int(section.get("wall_penalty", DEFAULT_WALL_PENALTY))
    if p.suffix.lower() == ".npy":
        terrain = TerrainMap.from_npy(
            p, clearance_tiles=clearance_tiles, wall_penalty=wall_penalty
        )
    else:
        terrain = TerrainMap.from_png(
            p,
            pixel_scale=pixel_scale,
            clearance_tiles=clearance_tiles,
            wall_penalty=wall_penalty,
        )
    set_terrain_map(terrain)
    return terrain
