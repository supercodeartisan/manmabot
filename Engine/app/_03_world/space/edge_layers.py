"""Layer3 bit0 walk layers (solid + N/E fence edges) from ``.s32`` blocks.

Runtime packs ship prebuilt ``nav_prebuild`` (+ ``nav.png`` fence display). ``.s32`` lives
under ``Support/field_s32/`` for offline rebuild only — not for distribution.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

OX = 0x7E00
# Pack origins (nav tile 0,0 = world origin).
TI_ORIGIN = (32256, 32704)
MAINLAND_ORIGIN = (32448, 32128)
TILE_PX = 4
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)

_AXIS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAG = ((1, -1), (-1, -1), (1, 1), (-1, 1))


def _parse_l3(data: bytes) -> np.ndarray:
    o = 64 * 128 * 4
    l2n = struct.unpack_from("<H", data, o)[0]
    o += 2 + l2n * 6
    return np.frombuffer(data[o : o + 64 * 64 * 4], dtype="<i2").reshape(64, 64, 2).copy()


def support_s32_dir(pack_id: str, *, project_root: Optional[Path] = None) -> Path:
    """``Support/field_s32/<pack_id>`` — build input, not shipped with the bot."""
    root = project_root or Path(__file__).resolve().parents[4]
    return root / "Support" / "field_s32" / str(pack_id)


@dataclass
class EdgeLayers:
    """bit0 layers: solid cell, north-edge block, east-edge block."""

    solid: np.ndarray
    block_n: np.ndarray
    block_e: np.ndarray
    covered: np.ndarray
    origin_x: int
    origin_y: int
    source: str = ""

    @property
    def width(self) -> int:
        return int(self.solid.shape[1])

    @property
    def height(self) -> int:
        return int(self.solid.shape[0])

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def standable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and not bool(self.solid[y, x])

    def north_blocked(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return True
        return bool(self.block_n[y, x])

    def east_blocked(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return True
        return bool(self.block_e[y, x])

    def can_axis(self, ax: int, ay: int, bx: int, by: int) -> bool:
        if not self.standable(ax, ay) or not self.standable(bx, by):
            return False
        dx, dy = bx - ax, by - ay
        if abs(dx) + abs(dy) != 1:
            return False
        if dy == -1:
            return not self.north_blocked(ax, ay)
        if dy == 1:
            return not self.north_blocked(bx, by)
        if dx == 1:
            return not self.east_blocked(ax, ay)
        if dx == -1:
            return not self.east_blocked(bx, by)
        return False

    def can_diagonal(self, ax: int, ay: int, bx: int, by: int) -> bool:
        if not self.standable(ax, ay) or not self.standable(bx, by):
            return False
        dx, dy = bx - ax, by - ay
        if abs(dx) != 1 or abs(dy) != 1:
            return False
        mid_x = (ax + dx, ay)
        mid_y = (ax, ay + dy)
        via_x = self.can_axis(ax, ay, mid_x[0], mid_x[1]) and self.can_axis(
            mid_x[0], mid_x[1], bx, by
        )
        via_y = self.can_axis(ax, ay, mid_y[0], mid_y[1]) and self.can_axis(
            mid_y[0], mid_y[1], bx, by
        )
        return via_x or via_y

    def can_step(self, ax: int, ay: int, bx: int, by: int) -> bool:
        dx, dy = bx - ax, by - ay
        adx, ady = abs(dx), abs(dy)
        if adx > 1 or ady > 1 or (dx == 0 and dy == 0):
            return False
        if adx + ady == 1:
            return self.can_axis(ax, ay, bx, by)
        return self.can_diagonal(ax, ay, bx, by)

    def neighbors(self, x: int, y: int) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for dx, dy in _AXIS + _DIAG:
            nx, ny = x + dx, y + dy
            if self.can_step(x, y, nx, ny):
                out.append((nx, ny))
        return out

    def walkable_mask(self) -> np.ndarray:
        """Standable tiles (not solid). Uncovered counted as solid already."""
        return ~np.asarray(self.solid, dtype=bool)

    def fence_bw_rgb(self, tile_px: int = TILE_PX) -> np.ndarray:
        """Black/white map at ``tile_px``² per tile; 1 px fence strips on blocked edges."""
        if tile_px < 2:
            raise ValueError("tile_px must be >= 2 for a 1 px edge strip")
        h, w = self.height, self.width
        stand = ~np.asarray(self.solid, dtype=bool)
        fine = np.empty((h * tile_px, w * tile_px, 3), dtype=np.uint8)
        fine[:] = _BLACK
        open_blocks = np.repeat(np.repeat(stand, tile_px, axis=0), tile_px, axis=1)
        fine[open_blocks] = _WHITE
        if h >= 2:
            north_open = stand[1:, :] & stand[:-1, :] & self.block_n[1:, :]
            ys, xs = np.where(north_open)
            y_south = ys + 1
            for ox in range(tile_px):
                fine[y_south * tile_px, xs * tile_px + ox] = _BLACK
                fine[y_south * tile_px - 1, xs * tile_px + ox] = _BLACK
        if w >= 2:
            east_open = stand[:, :-1] & stand[:, 1:] & self.block_e[:, :-1]
            ys, xs = np.where(east_open)
            for oy in range(tile_px):
                fine[ys * tile_px + oy, xs * tile_px + (tile_px - 1)] = _BLACK
                fine[ys * tile_px + oy, (xs + 1) * tile_px] = _BLACK
        return fine

    def save_fence_bw_png(self, path: Path, tile_px: int = TILE_PX) -> Path:
        from PIL import Image

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self.fence_bw_rgb(tile_px), mode="RGB").save(out)
        return out


def load_edge_layers(
    s32_dir: Path | str,
    *,
    origin_x: int,
    origin_y: int,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> EdgeLayers:
    """Load all ``.s32`` under ``s32_dir`` into a nav-tile grid at ``origin``."""
    root = Path(s32_dir)
    files = sorted(root.glob("*.s32"))
    if not files:
        raise FileNotFoundError(f"no .s32 under {root}")

    blocks: list[tuple[Path, int, int]] = []
    for path in files:
        bx = int(path.stem[:4], 16)
        by = int(path.stem[4:], 16)
        x0 = ((bx - OX) << 6) - int(origin_x)
        y0 = ((by - OX) << 6) - int(origin_y)
        blocks.append((path, x0, y0))

    if width is None or height is None:
        max_x = max(x0 + 64 for _, x0, _ in blocks)
        max_y = max(y0 + 64 for _, _, y0 in blocks)
        min_x = min(x0 for _, x0, _ in blocks)
        min_y = min(y0 for _, _, y0 in blocks)
        if min_x < 0 or min_y < 0:
            raise ValueError(
                f"s32 blocks extend before origin ({origin_x},{origin_y}): "
                f"min tile ({min_x},{min_y})"
            )
        width = int(width if width is not None else max_x)
        height = int(height if height is not None else max_y)

    w, h = int(width), int(height)
    solid = np.ones((h, w), dtype=bool)
    block_n = np.zeros((h, w), dtype=bool)
    block_e = np.zeros((h, w), dtype=bool)
    covered = np.zeros((h, w), dtype=bool)

    for path, x0, y0 in blocks:
        if x0 < 0 or y0 < 0 or x0 + 64 > w or y0 + 64 > h:
            raise ValueError(
                f"{path.name} tile window ({x0},{y0})+64 outside {w}x{h}"
            )
        attrs = _parse_l3(path.read_bytes())
        a1 = attrs[:, :, 0]
        a2 = attrs[:, :, 1]
        both = ((a1 & 1) != 0) & ((a2 & 1) != 0)
        solid[y0 : y0 + 64, x0 : x0 + 64] = both
        block_n[y0 : y0 + 64, x0 : x0 + 64] = (a1 & 1) != 0
        block_e[y0 : y0 + 64, x0 : x0 + 64] = (a2 & 1) != 0
        covered[y0 : y0 + 64, x0 : x0 + 64] = True

    return EdgeLayers(
        solid=solid,
        block_n=block_n,
        block_e=block_e,
        covered=covered,
        origin_x=int(origin_x),
        origin_y=int(origin_y),
        source=str(root),
    )


def edge_layers_from_arrays(
    solid: np.ndarray,
    block_n: np.ndarray,
    block_e: np.ndarray,
    *,
    origin_x: int,
    origin_y: int,
    covered: Optional[np.ndarray] = None,
    source: str = "",
) -> EdgeLayers:
    sol = np.asarray(solid, dtype=bool)
    if covered is None:
        covered = np.ones(sol.shape, dtype=bool)
    return EdgeLayers(
        solid=sol,
        block_n=np.asarray(block_n, dtype=bool),
        block_e=np.asarray(block_e, dtype=bool),
        covered=np.asarray(covered, dtype=bool),
        origin_x=int(origin_x),
        origin_y=int(origin_y),
        source=source,
    )
