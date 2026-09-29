"""Lighter HPA*-style portal graph: cluster connected components + border links.

Each abstract node is one 8-connected walkable component inside a CLUSTER×CLUSTER
cell. Neighboring components are linked only when fine tiles touch across the
shared border — so disconnected pockets inside the same cluster never form a
false transit (A–B and B–C does not imply A–C through the wrong pocket).

Intra-component distances are not precomputed (lighter init). Online planning
refines along the abstract corridor and falls back to fine A* if needed.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app._03_world.terrain_map import TerrainMap
from app._04_decision.pathfinding import find_path

DEFAULT_CLUSTER = 32

_NEIGHBOR8: tuple[tuple[int, int], ...] = (
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
class PortalNode:
    """One connected component inside a coarse cluster."""

    id: int
    cx: int
    cy: int
    local_id: int
    # Representative fine tile (any walkable tile in the component).
    rep_x: int
    rep_y: int
    tile_count: int = 0


@dataclass
class PortalGraph:
    """Abstract graph over cluster components."""

    cluster: int
    fine_width: int
    fine_height: int
    # labels[y, x] = node id, or -1 if blocked / empty.
    labels: np.ndarray
    nodes: list[PortalNode]
    # adjacency: node_id -> list[(neighbor_id, cost)]
    edges: dict[int, list[tuple[int, int]]] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    def node_at(self, x: int, y: int) -> Optional[int]:
        if not (0 <= x < self.fine_width and 0 <= y < self.fine_height):
            return None
        nid = int(self.labels[y, x])
        return nid if nid >= 0 else None

    def find_abstract_path(
        self,
        start_fine: tuple[int, int],
        goal_fine: tuple[int, int],
    ) -> list[int]:
        """A* on component nodes. Returns node-id path (inclusive)."""
        import heapq

        s = self.node_at(*start_fine)
        g = self.node_at(*goal_fine)
        if s is None or g is None:
            return []
        if s == g:
            return [s]

        def h(nid: int) -> int:
            n = self.nodes[nid]
            gx, gy = goal_fine
            return max(abs(n.rep_x - gx), abs(n.rep_y - gy))

        open_heap: list[tuple[int, int, int]] = []
        counter = 0
        heapq.heappush(open_heap, (h(s), counter, s))
        came_from: dict[int, int] = {}
        g_score: dict[int, int] = {s: 0}
        closed: set[int] = set()

        while open_heap:
            _, _, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            if current == g:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path
            closed.add(current)
            for nb, cost in self.edges.get(current, ()):
                if nb in closed:
                    continue
                tentative = g_score[current] + cost
                prev = g_score.get(nb)
                if prev is not None and tentative >= prev:
                    continue
                came_from[nb] = current
                g_score[nb] = tentative
                counter += 1
                heapq.heappush(open_heap, (tentative + h(nb), counter, nb))
        return []

    def corridor_mask(self, abstract_path: list[int]) -> np.ndarray:
        """Boolean fine mask: tiles belonging to abstract path components."""
        if not abstract_path:
            return np.zeros((self.fine_height, self.fine_width), dtype=bool)
        ids = np.fromiter(set(abstract_path), dtype=np.int32)
        return np.isin(self.labels, ids)

    def lookahead_goal_tile(
        self,
        abstract_path: list[int],
        start_fine: tuple[int, int],
        goal_fine: tuple[int, int],
        *,
        lookahead: int = 2,
    ) -> tuple[int, int]:
        """Fine tile to aim for in a path component a few hops ahead."""
        if not abstract_path:
            return goal_fine
        start_n = self.node_at(*start_fine)
        try:
            idx = abstract_path.index(start_n) if start_n is not None else 0
        except ValueError:
            idx = 0
        goal_n = self.node_at(*goal_fine)
        look = min(len(abstract_path) - 1, idx + max(1, lookahead))
        if goal_n is not None and goal_n in abstract_path[idx : look + 1]:
            return goal_fine
        node = self.nodes[abstract_path[look]]
        return node.rep_x, node.rep_y

    def coarse_cell_path(self, abstract_path: list[int]) -> list[tuple[int, int]]:
        """Deduped (cx, cy) sequence for UI / legacy coarse_path consumers."""
        out: list[tuple[int, int]] = []
        for nid in abstract_path:
            n = self.nodes[nid]
            cell = (n.cx, n.cy)
            if not out or out[-1] != cell:
                out.append(cell)
        return out


def build_portal_graph(
    terrain: TerrainMap,
    cluster: int = DEFAULT_CLUSTER,
) -> PortalGraph:
    """Build component nodes + border adjacency (no intra all-pairs BFS)."""
    if cluster < 1:
        raise ValueError("cluster must be >= 1")
    walk = terrain.walkable
    fh, fw = int(walk.shape[0]), int(walk.shape[1])
    labels = np.full((fh, fw), -1, dtype=np.int32)
    nodes: list[PortalNode] = []
    edges: dict[int, list[tuple[int, int]]] = defaultdict(list)

    cw = (fw + cluster - 1) // cluster
    ch = (fh + cluster - 1) // cluster

    for cy in range(ch):
        y0 = cy * cluster
        y1 = min(fh, y0 + cluster)
        for cx in range(cw):
            x0 = cx * cluster
            x1 = min(fw, x0 + cluster)
            local_id = 0
            for y in range(y0, y1):
                row = walk[y]
                lab_row = labels[y]
                for x in range(x0, x1):
                    if not row[x] or lab_row[x] >= 0:
                        continue
                    nid = len(nodes)
                    q: deque[tuple[int, int]] = deque()
                    q.append((x, y))
                    lab_row[x] = nid
                    count = 0
                    sx_sum = 0
                    sy_sum = 0
                    seed_x, seed_y = x, y
                    while q:
                        cx_, cy_ = q.popleft()
                        count += 1
                        sx_sum += cx_
                        sy_sum += cy_
                        for dx, dy in _NEIGHBOR8:
                            nx, ny = cx_ + dx, cy_ + dy
                            if nx < x0 or ny < y0 or nx >= x1 or ny >= y1:
                                continue
                            if labels[ny, nx] >= 0 or not walk[ny, nx]:
                                continue
                            labels[ny, nx] = nid
                            q.append((nx, ny))
                    rx, ry = seed_x, seed_y
                    if count > 0:
                        rx = sx_sum // count
                        ry = sy_sum // count
                        if labels[ry, rx] != nid:
                            rx, ry = seed_x, seed_y
                    nodes.append(
                        PortalNode(
                            id=nid,
                            cx=cx,
                            cy=cy,
                            local_id=local_id,
                            rep_x=rx,
                            rep_y=ry,
                            tile_count=count,
                        )
                    )
                    local_id += 1

    linked: set[tuple[int, int]] = set()

    def _link(a: int, b: int) -> None:
        if a < 0 or b < 0 or a == b:
            return
        key = (a, b) if a < b else (b, a)
        if key in linked:
            return
        linked.add(key)
        na, nb = nodes[a], nodes[b]
        cost = max(1, max(abs(na.rep_x - nb.rep_x), abs(na.rep_y - nb.rep_y)))
        edges[a].append((b, cost))
        edges[b].append((a, cost))

    for cy in range(ch):
        y0 = cy * cluster
        y1 = min(fh, y0 + cluster)
        for cx in range(cw - 1):
            x_left = (cx + 1) * cluster - 1
            x_right = x_left + 1
            if x_right >= fw:
                continue
            for y in range(y0, y1):
                a = int(labels[y, x_left])
                b = int(labels[y, x_right])
                if a >= 0 and b >= 0:
                    _link(a, b)
                if y + 1 < y1:
                    if a >= 0:
                        _link(a, int(labels[y + 1, x_right]))
                    if b >= 0:
                        _link(b, int(labels[y + 1, x_left]))

    for cy in range(ch - 1):
        y_top = (cy + 1) * cluster - 1
        y_bot = y_top + 1
        if y_bot >= fh:
            continue
        for cx in range(cw):
            x0 = cx * cluster
            x1 = min(fw, x0 + cluster)
            for x in range(x0, x1):
                a = int(labels[y_top, x])
                b = int(labels[y_bot, x])
                if a >= 0 and b >= 0:
                    _link(a, b)
                if x + 1 < x1:
                    if a >= 0:
                        _link(a, int(labels[y_bot, x + 1]))
                    if b >= 0:
                        _link(b, int(labels[y_top, x + 1]))

    return PortalGraph(
        cluster=cluster,
        fine_width=fw,
        fine_height=fh,
        labels=labels,
        nodes=nodes,
        edges=dict(edges),
    )


def find_path_in_corridor(
    terrain: TerrainMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    mask: np.ndarray,
) -> list[tuple[int, int]]:
    """Fine A* restricted to ``mask`` (and walkable). Always allows start/goal."""
    if mask.shape != terrain.walkable.shape:
        raise ValueError("mask shape must match terrain.walkable")
    allowed = mask.copy()
    sx, sy = start
    gx, gy = goal
    if 0 <= sy < allowed.shape[0] and 0 <= sx < allowed.shape[1]:
        allowed[sy, sx] = True
    if 0 <= gy < allowed.shape[0] and 0 <= gx < allowed.shape[1]:
        allowed[gy, gx] = True
    return find_path(terrain, start, goal, allowed=allowed)


__all__ = [
    "DEFAULT_CLUSTER",
    "PortalNode",
    "PortalGraph",
    "build_portal_graph",
    "find_path_in_corridor",
]
