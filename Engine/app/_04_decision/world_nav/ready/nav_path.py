"""Same-map A* on engine map-pack nav.png (standalone, no manmabot import)."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from .map_assets import MapPack, discover_map_packs

_NEIGHBORS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


@dataclass
class WalkGrid:
    """Nav tile grid: one cell = one world tile (after pixel_scale downsample)."""

    walkable: Any  # numpy 2d bool or list[list[bool]]
    width: int
    height: int
    origin_x: int
    origin_y: int
    pack_id: str

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return bool(self.walkable[y, x]) if hasattr(self.walkable, "shape") else bool(self.walkable[y][x])

    def world_to_nav(self, wx: int, wy: int) -> tuple[int, int]:
        return wx - self.origin_x, wy - self.origin_y

    def nav_to_world(self, nx: int, ny: int) -> tuple[int, int]:
        return nx + self.origin_x, ny + self.origin_y

    def snap_walkable(self, nx: int, ny: int, radius: int = 2) -> tuple[int, int] | None:
        """Nearest walkable nav cell within Chebyshev ``radius`` (gate cells may be blocked)."""
        if self.is_walkable(nx, ny):
            return nx, ny
        best: tuple[int, int, int] | None = None  # dist2, x, y
        for r in range(1, radius + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    x, y = nx + dx, ny + dy
                    if not self.is_walkable(x, y):
                        continue
                    d2 = dx * dx + dy * dy
                    if best is None or d2 < best[0]:
                        best = (d2, x, y)
            if best is not None:
                return best[1], best[2]
        return None


def load_walk_grid(pack: MapPack) -> WalkGrid | None:
    nav = pack.nav_path
    if nav is None or not nav.is_file():
        return None
    im = Image.open(nav).convert("RGB")
    w, h = im.size
    scale = max(1, pack.pixel_scale)
    try:
        import numpy as np

        arr = np.asarray(im, dtype=np.uint8)
        mask = (arr[:, :, 0] >= 250) & (arr[:, :, 1] >= 250) & (arr[:, :, 2] >= 250)
        if scale > 1:
            th, tw = h // scale, w // scale
            if th < 1 or tw < 1:
                return None
            blocks = mask[: th * scale, : tw * scale]
            blocks = blocks.reshape(th, scale, tw, scale)
            mask = blocks.mean(axis=(1, 3)) >= 0.5
        else:
            th, tw = h, w
        walk = mask  # keep numpy for fast A*
    except Exception:
        pix = im.load()
        assert pix is not None
        if scale == 1:
            walk = [[False] * w for _ in range(h)]
            for y in range(h):
                for x in range(w):
                    r, g, b = pix[x, y][:3]
                    walk[y][x] = r >= 250 and g >= 250 and b >= 250
            tw, th = w, h
        else:
            tw, th = w // scale, h // scale
            if tw < 1 or th < 1:
                return None
            walk = [[False] * tw for _ in range(th)]
            for ty in range(th):
                for tx in range(tw):
                    walkable = 0
                    total = scale * scale
                    for oy in range(scale):
                        for ox in range(scale):
                            r, g, b = pix[tx * scale + ox, ty * scale + oy][:3]
                            if r >= 250 and g >= 250 and b >= 250:
                                walkable += 1
                    walk[ty][tx] = walkable * 2 >= total
    return WalkGrid(
        walkable=walk,
        width=tw,
        height=th,
        origin_x=pack.origin_x,
        origin_y=pack.origin_y,
        pack_id=pack.pack_id,
    )


def _chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def astar_nav(
    grid: WalkGrid,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    """8-connected A*, step cost 1. Returns nav-tile path including start/goal."""
    sx, sy = start
    gx, gy = goal
    if not grid.is_walkable(sx, sy) or not grid.is_walkable(gx, gy):
        return []
    if start == goal:
        return [start]

    open_heap: list[tuple[int, int, tuple[int, int]]] = []
    heapq.heappush(open_heap, (0, 0, start))
    g_score: dict[tuple[int, int], int] = {start: 0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    closed: set[tuple[int, int]] = set()
    seq = 0

    while open_heap:
        _, _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path
        cx, cy = cur
        cg = g_score[cur]
        for dx, dy in _NEIGHBORS:
            nx, ny = cx + dx, cy + dy
            if not grid.is_walkable(nx, ny):
                continue
            if dx != 0 and dy != 0:
                if not grid.is_walkable(cx + dx, cy) and not grid.is_walkable(cx, cy + dy):
                    continue
            ng = cg + 1
            nxt = (nx, ny)
            if ng >= g_score.get(nxt, 10**18):
                continue
            g_score[nxt] = ng
            came[nxt] = cur
            seq += 1
            f = ng + _chebyshev(nx, ny, gx, gy)
            heapq.heappush(open_heap, (f, seq, nxt))
    return []


@dataclass
class WalkResult:
    ok: bool
    cost: int
    path_world: list[tuple[int, int]]  # inclusive
    error: str | None = None


class WalkService:
    """Cached A* between world cells on a mapId."""

    def __init__(self, packs: Iterable[MapPack] | None = None) -> None:
        self._packs: dict[int, MapPack] = {}
        self._grids: dict[int, WalkGrid | None] = {}
        self._cache: dict[tuple[int, int, int, int, int], WalkResult] = {}
        if packs is not None:
            self.set_packs(packs)
        else:
            self.set_packs(discover_map_packs())

    def set_packs(self, packs: Iterable[MapPack]) -> None:
        self._packs = {p.map_id: p for p in packs}
        self._grids.clear()
        self._cache.clear()

    def _grid(self, map_id: int) -> WalkGrid | None:
        if map_id in self._grids:
            return self._grids[map_id]
        pack = self._packs.get(map_id)
        grid = load_walk_grid(pack) if pack is not None else None
        self._grids[map_id] = grid
        return grid

    def walk(self, map_id: int, x0: int, y0: int, x1: int, y1: int) -> WalkResult:
        key = (map_id, x0, y0, x1, y1)
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        grid = self._grid(map_id)
        if grid is None:
            # No nav data: fall back to Chebyshev so planner still works
            cost = max(abs(x1 - x0), abs(y1 - y0))
            res = WalkResult(
                ok=True,
                cost=cost,
                path_world=[(x0, y0), (x1, y1)] if cost else [(x0, y0)],
                error="no_nav_fallback_chebyshev",
            )
            self._cache[key] = res
            return res

        s = grid.snap_walkable(*grid.world_to_nav(x0, y0))
        g = grid.snap_walkable(*grid.world_to_nav(x1, y1))
        if s is None or g is None:
            res = WalkResult(ok=False, cost=0, path_world=[], error="unwalkable_endpoint")
            self._cache[key] = res
            return res

        nav_path = astar_nav(grid, s, g)
        if not nav_path:
            res = WalkResult(ok=False, cost=0, path_world=[], error="astar_no_path")
            self._cache[key] = res
            return res

        world_path = [grid.nav_to_world(nx, ny) for nx, ny in nav_path]
        # Ensure exact requested endpoints are represented (snapped path may differ by a few tiles)
        if world_path[0] != (x0, y0):
            world_path[0] = (x0, y0)
        if world_path[-1] != (x1, y1):
            world_path[-1] = (x1, y1)
        cost = max(0, len(nav_path) - 1)
        res = WalkResult(ok=True, cost=cost, path_world=world_path)
        self._cache[key] = res
        return res
