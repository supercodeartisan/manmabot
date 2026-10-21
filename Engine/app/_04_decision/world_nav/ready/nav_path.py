"""Same-map A* on engine map-pack nav.png (standalone, no manmabot import)."""

from __future__ import annotations

import hashlib
import heapq
import json
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from .map_assets import MapPack, discover_map_packs

# White-tile connectivity. A diagonal step is allowed only when one of the
# two orthogonal corners is open, and that open corner already 4-connects
# the ends. Component ids are therefore the 4-connected white regions.
# They are not the fence-aware portal labels in nav_prebuild.
_COMPONENT_VERSION = 1
_COMPONENT_RULE = "white4"
_COMPONENT_DIRNAME = "walk_components"

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


def label_walk_components(walkable: Any):
    """4-connected ids for white tiles. ``0`` is blocked. Same rule as A* steps.

    An allowed diagonal does not join regions that 4-connectivity leaves
    apart: the open orthogonal corner already links the two ends. An 8-connected
    label would walk a blocked corner and change which hubs count as one walk.
    """
    import numpy as np
    from scipy import ndimage

    walk = np.asarray(walkable, dtype=bool)
    if walk.ndim != 2:
        raise ValueError("walkable must be 2-D")
    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    comp, _n = ndimage.label(walk, structure=structure)
    return np.asarray(comp, dtype=np.int32)


def _component_dir(pack: MapPack) -> Path | None:
    nav = pack.nav_path
    if nav is None:
        return None
    return Path(nav).parent / _COMPONENT_DIRNAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_stamp(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "source_sha256": _sha256(path),
        "source_size": int(stat.st_size),
        "source_mtime_ns": int(stat.st_mtime_ns),
    }


def _stamp_matches(meta: dict[str, Any], nav: Path, pack: MapPack, shape: tuple[int, int]) -> bool:
    if int(meta.get("version") or 0) != _COMPONENT_VERSION:
        return False
    if str(meta.get("rule") or "") != _COMPONENT_RULE:
        return False
    if int(meta.get("origin_x") or 0) != int(pack.origin_x):
        return False
    if int(meta.get("origin_y") or 0) != int(pack.origin_y):
        return False
    if int(meta.get("pixel_scale") or 1) != max(1, int(pack.pixel_scale)):
        return False
    if int(meta.get("height") or 0) != int(shape[0]) or int(meta.get("width") or 0) != int(shape[1]):
        return False
    try:
        stat = nav.stat()
    except OSError:
        return False
    if int(meta.get("source_size") or -1) != int(stat.st_size):
        return False
    if int(meta.get("source_mtime_ns") or -1) != int(stat.st_mtime_ns):
        # Same bytes renamed or copied: trust the hash, then refresh the stamp.
        if str(meta.get("source_sha256") or "") != _sha256(nav):
            return False
    return True


@dataclass
class WalkComponents:
    """White-tile component ids for one pack. ``0`` is blocked."""

    labels: Any
    origin_x: int
    origin_y: int
    width: int
    height: int


def snap_component_cell(
    labels: Any,
    x: int,
    y: int,
    radius: int = 2,
) -> tuple[int, int] | None:
    """Nearest positive component cell. Same radius order as ``WalkGrid.snap_walkable``."""
    height, width = labels.shape

    def on(cx: int, cy: int) -> bool:
        return 0 <= cx < width and 0 <= cy < height and int(labels[cy, cx]) > 0

    if on(x, y):
        return x, y
    best: tuple[int, int, int] | None = None
    for r in range(1, radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                nx, ny = x + dx, y + dy
                if not on(nx, ny):
                    continue
                dist = dx * dx + dy * dy
                if best is None or dist < best[0]:
                    best = (dist, nx, ny)
        if best is not None:
            return best[1], best[2]
    return None


def try_load_components(pack: MapPack) -> WalkComponents | None:
    """Load a stamp-matching component file. Does not decode ``nav.png``."""
    import numpy as np

    directory = _component_dir(pack)
    nav = None if pack.nav_path is None else Path(pack.nav_path)
    if directory is None or nav is None or not nav.is_file():
        return None
    labels_path = directory / "labels.npy"
    meta_path = directory / "meta.json"
    if not labels_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    shape = (int(meta.get("height") or 0), int(meta.get("width") or 0))
    if not _stamp_matches(meta, nav, pack, shape):
        return None
    try:
        labels = np.asarray(np.load(labels_path), dtype=np.int32)
    except (OSError, ValueError):
        return None
    if labels.shape != shape:
        return None
    if int(meta.get("source_mtime_ns") or -1) != int(nav.stat().st_mtime_ns):
        _write_component_cache(directory, labels, nav, pack, shape)
    return WalkComponents(
        labels=labels,
        origin_x=int(pack.origin_x),
        origin_y=int(pack.origin_y),
        width=int(shape[1]),
        height=int(shape[0]),
    )


def load_or_build_components(pack: MapPack, grid: WalkGrid):
    """Read this pack's component ids, building them once when the file is stale.

    The file sits beside ``nav.png`` and is keyed by that image. It is not
    ``nav_prebuild/labels.npy``.
    """
    import numpy as np

    walk = np.asarray(grid.walkable, dtype=bool)
    directory = _component_dir(pack)
    nav = None if pack.nav_path is None else Path(pack.nav_path)
    labels_path = None if directory is None else directory / "labels.npy"
    meta_path = None if directory is None else directory / "meta.json"
    if (
        directory is not None
        and nav is not None
        and nav.is_file()
        and labels_path is not None
        and meta_path is not None
        and labels_path.is_file()
        and meta_path.is_file()
    ):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and _stamp_matches(meta, nav, pack, walk.shape):
                labels = np.load(labels_path)
                if labels.shape == walk.shape:
                    if int(meta.get("source_mtime_ns") or -1) != int(nav.stat().st_mtime_ns):
                        _write_component_cache(directory, labels, nav, pack, walk.shape)
                    return np.asarray(labels, dtype=np.int32)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    labels = label_walk_components(walk)
    if directory is not None and nav is not None and nav.is_file():
        _write_component_cache(directory, labels, nav, pack, walk.shape)
    return labels


def _write_component_cache(
    directory: Path,
    labels: Any,
    nav: Path,
    pack: MapPack,
    shape: tuple[int, int],
) -> None:
    import numpy as np

    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "labels.tmp.npy"
    np.save(tmp, np.asarray(labels, dtype=np.int32))
    tmp.replace(directory / "labels.npy")
    meta = {
        "version": _COMPONENT_VERSION,
        "rule": _COMPONENT_RULE,
        "origin_x": int(pack.origin_x),
        "origin_y": int(pack.origin_y),
        "pixel_scale": max(1, int(pack.pixel_scale)),
        "width": int(shape[1]),
        "height": int(shape[0]),
    }
    meta.update(_source_stamp(nav))
    (directory / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
        self._components: dict[int, Any] = {}
        self._labels: dict[int, dict[tuple[int, int], int]] = {}
        self._closed: dict[int, bool] = {}
        self._next_comp = 1
        if packs is not None:
            self.set_packs(packs)
        else:
            self.set_packs(discover_map_packs())

    def set_packs(self, packs: Iterable[MapPack]) -> None:
        self._packs = {p.map_id: p for p in packs}
        self._grids.clear()
        self._cache.clear()
        self._components.clear()
        self._labels.clear()
        self._closed.clear()
        self._next_comp = 1

    def _grid(self, map_id: int) -> WalkGrid | None:
        if map_id in self._grids:
            return self._grids[map_id]
        pack = self._packs.get(map_id)
        grid = load_walk_grid(pack) if pack is not None else None
        self._grids[map_id] = grid
        return grid

    def preload_pack(self, pack_id: str) -> None:
        """Load one pack's component ids. Map load calls this before a route."""
        for pack in self._packs.values():
            if pack.pack_id == str(pack_id):
                self.ensure_map(int(pack.map_id))
                return

    def preload_known(self) -> None:
        """Read every pack's component file. Planning then only compares ids."""
        for map_id in list(self._packs):
            self.ensure_map(int(map_id))

    def ensure_map(self, map_id: int) -> None:
        """Make this map's component ids ready. A warm file is a read, not a flood."""
        if map_id in self._components:
            return
        pack = self._packs.get(map_id)
        if pack is None:
            self._components[map_id] = None
            return
        import time

        t0 = time.perf_counter()
        try:
            loaded = try_load_components(pack)
            if loaded is None:
                grid = self._grid(map_id)
                if grid is None:
                    self._components[map_id] = None
                    return
                labels = load_or_build_components(pack, grid)
                loaded = WalkComponents(
                    labels=labels,
                    origin_x=int(grid.origin_x),
                    origin_y=int(grid.origin_y),
                    width=int(grid.width),
                    height=int(grid.height),
                )
        except Exception as exc:
            self._components[map_id] = None
            _log_components_fail(pack.pack_id, map_id, exc)
            return
        self._components[map_id] = loaded
        _log_components(pack.pack_id, map_id, (time.perf_counter() - t0) * 1000.0)

    def _grid_from_components(self, map_id: int) -> WalkGrid | None:
        """Walk mask from ids already in memory. ``0`` is blocked, same as the PNG."""
        comp = self._components.get(map_id)
        if not isinstance(comp, WalkComponents):
            return None
        pack = self._packs.get(map_id)
        return WalkGrid(
            walkable=comp.labels,
            width=int(comp.width),
            height=int(comp.height),
            origin_x=int(comp.origin_x),
            origin_y=int(comp.origin_y),
            pack_id=pack.pack_id if pack is not None else "",
        )

    def walk(self, map_id: int, x0: int, y0: int, x1: int, y1: int) -> WalkResult:
        key = (map_id, x0, y0, x1, y1)
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        self.ensure_map(map_id)
        grid = self._grid_from_components(map_id)
        if grid is None:
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

    def same_component(
        self,
        map_id: int,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        *,
        cap: int = 80000,
    ) -> bool:
        """True when a one-tile walk can exist between the two cells.

        Prepared component ids answer this. The ids use the same white-tile
        steps as ``astar_nav``. A missing grid still counts as connected, and
        a grid that cannot be labeled falls back to the capped flood.
        """
        self.ensure_map(map_id)
        comp = self._components.get(map_id)
        if isinstance(comp, WalkComponents):
            start = snap_component_cell(
                comp.labels, int(x0) - comp.origin_x, int(y0) - comp.origin_y
            )
            goal = snap_component_cell(
                comp.labels, int(x1) - comp.origin_x, int(y1) - comp.origin_y
            )
            if start is None or goal is None:
                return False
            if start == goal:
                return True
            sid = int(comp.labels[start[1], start[0]])
            gid = int(comp.labels[goal[1], goal[0]])
            if sid <= 0 or gid <= 0:
                return False
            return sid == gid
        grid = self._grid(map_id)
        if grid is None:
            return True
        start = grid.snap_walkable(*grid.world_to_nav(x0, y0))
        goal = grid.snap_walkable(*grid.world_to_nav(x1, y1))
        if start is None or goal is None:
            return False
        if start == goal:
            return True
        return self._flood_same(grid, start, goal, cap=cap)

    def _flood_same(
        self,
        grid: WalkGrid,
        start: tuple[int, int],
        goal: tuple[int, int],
        *,
        cap: int,
    ) -> bool:
        """Capped flood used only when component ids are unavailable."""
        labels = self._labels.setdefault(id(grid), {})
        start_id = labels.get(start)
        goal_id = labels.get(goal)
        if start_id is not None and goal_id is not None:
            return start_id == goal_id
        if start_id is not None and goal_id is None and self._closed.get(start_id):
            return False
        if goal_id is not None and start_id is None and self._closed.get(goal_id):
            return False
        if start_id is None:
            origin, target = start, goal
        else:
            origin, target = goal, start
        comp = self._next_comp
        self._next_comp += 1
        pending: deque[tuple[int, int]] = deque([origin])
        labels[origin] = comp
        seen = 0
        while pending:
            x, y = pending.popleft()
            seen += 1
            if (x, y) == target or labels.get(target) == comp:
                return True
            if seen >= cap:
                return True
            for dx, dy in _NEIGHBORS:
                nx, ny = x + dx, y + dy
                if not grid.is_walkable(nx, ny):
                    continue
                if dx != 0 and dy != 0:
                    if not grid.is_walkable(x + dx, y) and not grid.is_walkable(x, y + dy):
                        continue
                prev = labels.get((nx, ny))
                if prev is None:
                    labels[(nx, ny)] = comp
                    pending.append((nx, ny))
                    continue
                if prev == comp:
                    continue
                if labels.get(target) == prev:
                    return True
        self._closed[comp] = True
        return labels.get(target) == comp


_shared_walk: WalkService | None = None
_shared_lock = threading.Lock()


def shared_walk_service() -> WalkService:
    """One walk service for the process. Component ids survive the next plan."""
    global _shared_walk
    with _shared_lock:
        if _shared_walk is None:
            _shared_walk = WalkService()
        return _shared_walk


def _log_components(pack_id: str, map_id: int, elapsed_ms: float) -> None:
    try:
        from app.bot_log import get_logger
    except Exception:
        return
    get_logger("nav").info(
        "walk components ready pack=%s map=%s (%.0f ms)",
        pack_id,
        int(map_id),
        float(elapsed_ms),
    )


def _log_components_fail(pack_id: str, map_id: int, exc: Exception) -> None:
    try:
        from app.bot_log import get_logger
    except Exception:
        return
    get_logger("nav").warning(
        "walk components failed pack=%s map=%s (%s)",
        pack_id,
        int(map_id),
        exc,
    )
