"""Axis-aligned farm rectangles in absolute WCS tiles."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app._03_world.terrain_map import TerrainMap
from app._03_world.world_coords import tile_chebyshev

# Coarse coverage cells for SEARCHING visit memory.
DEFAULT_COVERAGE_CELL = 16
# Travel arrives when Chebyshev distance to goal is at most this.
ARRIVE_TILES = 2


@dataclass(frozen=True)
class FarmRect:
    """Inclusive absolute-tile box: ``x0..x1``, ``y0..y1``.

    ``region`` selects vision model packs (not the map-pack id). Example:
    areas on the Talking Island *map* use ``region="talking island"``.
    """

    x0: int
    y0: int
    x1: int
    y1: int
    name: str = ""
    region: str = ""

    def __post_init__(self) -> None:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError(
                f"FarmRect {self.name!r} has inverted bounds "
                f"({self.x0},{self.y0})-({self.x1},{self.y1})"
            )

    def contains(self, x: int, y: int) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def clamp(self, x: int, y: int) -> tuple[int, int]:
        return (
            min(max(x, self.x0), self.x1),
            min(max(y, self.y0), self.y1),
        )

    def center(self) -> tuple[int, int]:
        return (self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2

    def nearest_walkable(
        self,
        terrain: TerrainMap,
        start: tuple[int, int],
    ) -> Optional[tuple[int, int]]:
        """Walkable tile in this rect closest to ``start`` (Chebyshev).

        Used as the TRAVELING entry goal when changing farm area: the nearest
        point in the farm relative to where travel begins.
        """
        sx, sy = start
        best: Optional[tuple[int, int]] = None
        best_key: Optional[tuple[int, int, int]] = None
        for y in range(self.y0, self.y1 + 1):
            for x in range(self.x0, self.x1 + 1):
                if not terrain.is_walkable(x, y):
                    continue
                d = tile_chebyshev(sx, sy, x, y)
                # Tie-break: prefer closer to start in Euclidean², then lower x,y.
                key = (d, (x - sx) * (x - sx) + (y - sy) * (y - sy), x, y)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (x, y)
        return best

    def interior_walkable(
        self,
        terrain: TerrainMap,
        start: tuple[int, int],
        *,
        margin: int = ARRIVE_TILES,
    ) -> Optional[tuple[int, int]]:
        """Nearest walkable inset by ``margin`` so ARRIVE_TILES still leaves us inside.

        Edge entry goals are unsafe: arriving within ``ARRIVE_TILES`` of the
        farm border can complete travel while ``contains`` is still False,
        which previously left farming with no intent (idle).
        """
        if margin <= 0:
            return self.nearest_walkable(terrain, start)
        ix0 = self.x0 + margin
        iy0 = self.y0 + margin
        ix1 = self.x1 - margin
        iy1 = self.y1 - margin
        if ix0 <= ix1 and iy0 <= iy1:
            inner = FarmRect(ix0, iy0, ix1, iy1, name=self.name, region=self.region)
            goal = inner.nearest_walkable(terrain, start)
            if goal is not None:
                return goal
        return self.nearest_walkable(terrain, start)

    def coverage_cell(self, x: int, y: int, cell: int = DEFAULT_COVERAGE_CELL) -> tuple[int, int]:
        return x // cell, y // cell


def farm_rect_from_mapping(data: dict, *, index: int = 0) -> FarmRect:
    """Build a FarmRect from a config mapping."""
    try:
        x0 = int(data["x0"])
        y0 = int(data["y0"])
        x1 = int(data["x1"])
        y1 = int(data["y1"])
    except KeyError as exc:
        raise ValueError(f"farm_areas[{index}] missing {exc}") from exc
    name = str(data.get("name") or f"farm_{index}")
    region = str(data.get("region") or "").strip()
    return FarmRect(x0=x0, y0=y0, x1=x1, y1=y1, name=name, region=region)


def farm_areas_yaml_text(
    rects: list[FarmRect],
    *,
    default_region: str = "",
) -> str:
    """Serialize farm rects to the pack ``farms.yaml`` format."""
    lines = [
        "# Areas (nav tiles). region selects vision models (not the map pack id).",
        "areas:",
    ]
    if not rects:
        lines.append("  []")
        return "\n".join(lines) + "\n"
    for i, rect in enumerate(rects, start=1):
        name = rect.name.strip() or f"area_{i}"
        region = (rect.region or default_region).strip()
        lines.extend(
            [
                f"  - name: {name}",
                f"    region: {region}",
                f"    x0: {rect.x0}",
                f"    y0: {rect.y0}",
                f"    x1: {rect.x1}",
                f"    y1: {rect.y1}",
            ]
        )
    return "\n".join(lines) + "\n"


def save_farm_areas_yaml(
    path: str | Path,
    rects: list[FarmRect],
    *,
    default_region: str = "",
) -> Path:
    """Write ``farms.yaml``; create parent folders if needed."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        farm_areas_yaml_text(rects, default_region=default_region),
        encoding="utf-8",
    )
    return out


__all__ = [
    "ARRIVE_TILES",
    "DEFAULT_COVERAGE_CELL",
    "FarmRect",
    "farm_rect_from_mapping",
    "farm_areas_yaml_text",
    "save_farm_areas_yaml",
]
