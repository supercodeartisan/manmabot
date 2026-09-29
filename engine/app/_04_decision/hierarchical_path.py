"""Two-level hierarchical pathfinding for real-time long-range travel.

Level 1: portal/component abstract A* (sound cluster components + border links),
         with legacy optimistic CoarseMap as fallback when no portal graph exists.
Level 2: fine A* along the abstract corridor (masked), then local window, then
         full fine A* so planning does not fail when a path exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np

from app._03_world.objects import Position
from app._03_world.terrain_map import TerrainMap
from app._03_world.world_coords import CLICK_PATH_SLACK, WorldOrigin, tile_chebyshev
from app._04_decision.pathfinding import (
    find_path,
    select_click_waypoint,
    waypoint_to_content,
)

if TYPE_CHECKING:
    from app._04_decision.portal_graph import PortalGraph

DEFAULT_CLUSTER = 32
# Use hierarchy when the fine map is larger than this many tiles.
HIERARCHICAL_AREA_THRESHOLD = 50_000
# Local fine window radius in clusters around the player.
LOCAL_CLUSTER_RADIUS = 2
# How many abstract / coarse steps ahead to aim the local fine goal.
COARSE_LOOKAHEAD = 2


@dataclass
class CoarseMap:
    """Downsampled walkability grid: one cell = ``cluster``×``cluster`` fine tiles."""

    cluster: int
    walkable: np.ndarray  # bool (coarse_h, coarse_w)
    fine_width: int
    fine_height: int

    @property
    def width(self) -> int:
        return int(self.walkable.shape[1])

    @property
    def height(self) -> int:
        return int(self.walkable.shape[0])

    @classmethod
    def from_terrain(
        cls,
        terrain: TerrainMap,
        cluster: int = DEFAULT_CLUSTER,
    ) -> "CoarseMap":
        if cluster < 1:
            raise ValueError("cluster must be >= 1")
        fw, fh = terrain.width, terrain.height
        cw = (fw + cluster - 1) // cluster
        ch = (fh + cluster - 1) // cluster
        coarse = np.zeros((ch, cw), dtype=bool)
        fine = terrain.walkable
        for cy in range(ch):
            y0 = cy * cluster
            y1 = min(fh, y0 + cluster)
            for cx in range(cw):
                x0 = cx * cluster
                x1 = min(fw, x0 + cluster)
                block = fine[y0:y1, x0:x1]
                if terrain.clearance is not None:
                    clr = terrain.clearance[y0:y1, x0:x1]
                    # Prefer cells that contain a tile inset from walls.
                    has_clear = bool(np.any(block & (clr >= 1)))
                    if has_clear:
                        coarse[cy, cx] = True
                    else:
                        # Thin 1-tile passes: all walkable tiles hug a wall.
                        coarse[cy, cx] = bool(np.any(block))
                else:
                    coarse[cy, cx] = bool(np.any(block))
        return cls(
            cluster=cluster,
            walkable=coarse,
            fine_width=fw,
            fine_height=fh,
        )

    def as_terrain(self) -> TerrainMap:
        return TerrainMap.from_array(self.walkable)

    def fine_to_coarse(self, x: int, y: int) -> tuple[int, int]:
        return x // self.cluster, y // self.cluster

    def coarse_bounds(self, cx: int, cy: int) -> tuple[int, int, int, int]:
        """Return fine (x0, y0, x1, y1) half-open bounds for a coarse cell."""
        x0 = cx * self.cluster
        y0 = cy * self.cluster
        x1 = min(self.fine_width, x0 + self.cluster)
        y1 = min(self.fine_height, y0 + self.cluster)
        return x0, y0, x1, y1

    def coarse_center_fine(self, cx: int, cy: int) -> tuple[int, int]:
        x0, y0, x1, y1 = self.coarse_bounds(cx, cy)
        return (x0 + x1 - 1) // 2, (y0 + y1 - 1) // 2


def find_coarse_path(
    coarse: CoarseMap,
    start_fine: tuple[int, int],
    goal_fine: tuple[int, int],
) -> list[tuple[int, int]]:
    """A* on the coarse grid. Returns coarse cell coordinates."""
    sc = coarse.fine_to_coarse(*start_fine)
    gc = coarse.fine_to_coarse(*goal_fine)
    return find_path(coarse.as_terrain(), sc, gc)


def _nearest_walkable(
    terrain: TerrainMap,
    x: int,
    y: int,
    max_radius: int = 64,
) -> Optional[tuple[int, int]]:
    """Spiral search for a walkable fine tile near ``(x, y)``."""
    if terrain.is_walkable(x, y):
        return x, y
    for r in range(1, max_radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                nx, ny = x + dx, y + dy
                if terrain.is_walkable(nx, ny):
                    return nx, ny
    return None


def _best_tile_in_cluster(
    terrain: TerrainMap,
    coarse: CoarseMap,
    cx: int,
    cy: int,
    goal_fine: tuple[int, int],
) -> Optional[tuple[int, int]]:
    """Walkable tile in the coarse cell closest to the final goal (not cell center)."""
    x0, y0, x1, y1 = coarse.coarse_bounds(cx, cy)
    gx, gy = goal_fine
    best: Optional[tuple[int, int]] = None
    best_key: Optional[tuple[int, int]] = None
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not terrain.is_walkable(x, y):
                continue
            key = (tile_chebyshev(x, y, gx, gy), (x - gx) * (x - gx) + (y - gy) * (y - gy))
            if best_key is None or key < best_key:
                best_key = key
                best = (x, y)
    return best


def _local_fine_goal(
    terrain: TerrainMap,
    coarse: CoarseMap,
    coarse_path: list[tuple[int, int]],
    start_fine: tuple[int, int],
    goal_fine: tuple[int, int],
) -> tuple[int, int]:
    """Pick a fine goal inside the local window from the coarse corridor."""
    if not coarse_path:
        return goal_fine

    start_c = coarse.fine_to_coarse(*start_fine)
    try:
        idx = coarse_path.index(start_c)
    except ValueError:
        idx = 0

    look = min(len(coarse_path) - 1, idx + COARSE_LOOKAHEAD)
    goal_c = coarse.fine_to_coarse(*goal_fine)
    if goal_c in coarse_path[idx : look + 1]:
        return goal_fine

    cx, cy = coarse_path[look]
    found = _best_tile_in_cluster(terrain, coarse, cx, cy, goal_fine)
    if found is not None:
        return found
    center = coarse.coarse_center_fine(cx, cy)
    nearest = _nearest_walkable(terrain, center[0], center[1], max_radius=coarse.cluster)
    return nearest if nearest is not None else goal_fine


def _clamp_window(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    radius: int,
) -> tuple[int, int, int, int]:
    """Axis-aligned fine window covering start, goal, and radius margin."""
    xs = [start[0], goal[0]]
    ys = [start[1], goal[1]]
    x0 = max(0, min(xs) - radius)
    y0 = max(0, min(ys) - radius)
    x1 = min(terrain.width, max(xs) + radius + 1)
    y1 = min(terrain.height, max(ys) + radius + 1)
    return x0, y0, x1, y1


def find_path_in_window(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    window: tuple[int, int, int, int],
) -> list[tuple[int, int]]:
    """Fine A* restricted to ``window`` (x0,y0,x1,y1 half-open)."""
    x0, y0, x1, y1 = window
    if not (x0 <= start[0] < x1 and y0 <= start[1] < y1):
        return []
    if not (x0 <= goal[0] < x1 and y0 <= goal[1] < y1):
        return []

    local = terrain.submap(x0, y0, x1, y1)
    local_start = (start[0] - x0, start[1] - y0)
    local_goal = (goal[0] - x0, goal[1] - y0)
    local_path = find_path(local, local_start, local_goal)
    return [(x + x0, y + y0) for x, y in local_path]


def plan_travel_click_hierarchical(
    terrain: TerrainMap,
    origin: WorldOrigin,
    goal: tuple[int, int],
    *,
    cluster: int = DEFAULT_CLUSTER,
    coarse: Optional[CoarseMap] = None,
    portal_graph: Optional["PortalGraph"] = None,
    slack: int = CLICK_PATH_SLACK,
    max_hop: int | None = None,
) -> tuple[
    Optional[Position],
    list[tuple[int, int]],
    Optional[tuple[int, int]],
    list[tuple[int, int]],
]:
    """Portal/component guide + corridor fine path → content click destination.

    Prefers a prebuilt ``portal_graph`` (sound cluster components). Falls back
    to legacy optimistic ``CoarseMap`` only when no portal graph is available.
    If corridor/window refine fails, falls back to full fine A* so planning
    does not return empty when a fine path exists.

    Returns ``(content_dest, fine_path, absolute_waypoint, coarse_cell_path)``.
    """
    from app._04_decision.portal_graph import (
        find_path_in_corridor,
    )

    start = (origin.x, origin.y)
    if not terrain.is_walkable(*start) or not terrain.is_walkable(*goal):
        return None, [], None, []

    graph = portal_graph
    coarse_cells: list[tuple[int, int]] = []
    abstract: list[int] = []

    if graph is None:
        try:
            from app._04_decision.nav_config import get_portal_graph

            cached = get_portal_graph()
            if cached is not None and cached.cluster == cluster:
                graph = cached
        except Exception:
            graph = None

    if graph is not None:
        abstract = graph.find_abstract_path(start, goal)
        coarse_cells = graph.coarse_cell_path(abstract)
        fine_path = []
        if abstract:
            local_goal = graph.lookahead_goal_tile(
                abstract, start, goal, lookahead=COARSE_LOOKAHEAD
            )
            start_n = graph.node_at(*start)
            try:
                idx = abstract.index(start_n) if start_n is not None else 0
            except ValueError:
                idx = 0
            look = min(len(abstract) - 1, idx + COARSE_LOOKAHEAD)
            hop_nodes = abstract[idx : look + 1]
            mask = graph.corridor_mask(hop_nodes)
            fine_path = find_path_in_corridor(terrain, start, local_goal, mask)
            if not fine_path and local_goal != goal:
                # Widen to the full abstract corridor (sound but larger).
                mask = graph.corridor_mask(abstract)
                fine_path = find_path_in_corridor(terrain, start, local_goal, mask)
                if not fine_path:
                    fine_path = find_path_in_corridor(terrain, start, goal, mask)
            if not fine_path:
                radius = LOCAL_CLUSTER_RADIUS * cluster
                window = _clamp_window(terrain, start, local_goal, radius)
                fine_path = find_path_in_window(terrain, start, local_goal, window)
                if not fine_path:
                    window = _clamp_window(terrain, start, local_goal, radius * 2)
                    fine_path = find_path_in_window(
                        terrain, start, local_goal, window
                    )
    else:
        # Legacy optimistic coarse (tests / tiny maps without portal build).
        cmap = coarse if coarse is not None else CoarseMap.from_terrain(terrain, cluster)
        coarse_cells = find_coarse_path(cmap, start, goal)
        if not coarse_cells:
            fine_path = find_path(terrain, start, goal)
        else:
            local_goal = _local_fine_goal(terrain, cmap, coarse_cells, start, goal)
            radius = LOCAL_CLUSTER_RADIUS * cmap.cluster
            window = _clamp_window(terrain, start, local_goal, radius)
            fine_path = find_path_in_window(terrain, start, local_goal, window)
            if not fine_path:
                window = _clamp_window(terrain, start, local_goal, radius * 2)
                fine_path = find_path_in_window(terrain, start, local_goal, window)

    # Must-not-fail: full fine A* when hierarchical refine finds nothing.
    if not fine_path:
        fine_path = find_path(terrain, start, goal)
        if not fine_path:
            return None, [], None, coarse_cells

    waypoint = select_click_waypoint(
        fine_path, origin, slack=slack, terrain=terrain, max_hop=max_hop
    )
    if waypoint is None:
        return None, fine_path, None, coarse_cells
    return waypoint_to_content(waypoint, origin), fine_path, waypoint, coarse_cells


__all__ = [
    "DEFAULT_CLUSTER",
    "HIERARCHICAL_AREA_THRESHOLD",
    "CoarseMap",
    "find_coarse_path",
    "find_path_in_window",
    "plan_travel_click_hierarchical",
]
