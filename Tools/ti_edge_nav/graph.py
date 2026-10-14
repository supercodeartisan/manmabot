"""Portal-style graph on EdgeLayers (axis edges first, then diagonal)."""
from __future__ import annotations

import heapq
import pickle
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from ti_edge_nav.layers import EdgeLayers

DEFAULT_CLUSTER = 32

_AXIS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAG = ((1, -1), (-1, -1), (1, 1), (-1, 1))


@dataclass
class PortalNode:
    id: int
    cx: int
    cy: int
    local_id: int
    rep_x: int
    rep_y: int
    tile_count: int = 0


@dataclass
class EdgePortalGraph:
    cluster: int
    fine_width: int
    fine_height: int
    labels: np.ndarray
    nodes: list[PortalNode]
    edges: dict[int, list[tuple[int, int]]] = field(default_factory=dict)

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
        if not abstract_path:
            return np.zeros((self.fine_height, self.fine_width), dtype=bool)
        ids = np.fromiter(set(abstract_path), dtype=np.int32)
        return np.isin(self.labels, ids)


def build_edge_portal_graph(
    layers: EdgeLayers,
    cluster: int = DEFAULT_CLUSTER,
) -> EdgePortalGraph:
    """HPA* components using ``can_step`` (axis + 2-step diagonal rule)."""
    if cluster < 1:
        raise ValueError("cluster must be >= 1")
    fw, fh = layers.width, layers.height
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
                for x in range(x0, x1):
                    if labels[y, x] >= 0 or not layers.standable(x, y):
                        continue
                    nid = len(nodes)
                    q: deque[tuple[int, int]] = deque([(x, y)])
                    labels[y, x] = nid
                    count = 0
                    sx_sum = 0
                    sy_sum = 0
                    seed_x, seed_y = x, y
                    while q:
                        cx_, cy_ = q.popleft()
                        count += 1
                        sx_sum += cx_
                        sy_sum += cy_
                        # Axis first, then diagonal (same can_step, order stable).
                        for dx, dy in _AXIS + _DIAG:
                            nx, ny = cx_ + dx, cy_ + dy
                            if nx < x0 or ny < y0 or nx >= x1 or ny >= y1:
                                continue
                            if labels[ny, nx] >= 0:
                                continue
                            if not layers.can_step(cx_, cy_, nx, ny):
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

    def _try_border(x0: int, y0: int, x1: int, y1: int) -> None:
        if not layers.can_step(x0, y0, x1, y1):
            return
        _link(int(labels[y0, x0]), int(labels[y1, x1]))

    for cy in range(ch):
        y0 = cy * cluster
        y1 = min(fh, y0 + cluster)
        for cx in range(cw - 1):
            x_left = (cx + 1) * cluster - 1
            x_right = x_left + 1
            if x_right >= fw:
                continue
            for y in range(y0, y1):
                _try_border(x_left, y, x_right, y)
                if y + 1 < y1:
                    _try_border(x_left, y, x_right, y + 1)
                    _try_border(x_right, y, x_left, y + 1)

    for cy in range(ch - 1):
        y_top = (cy + 1) * cluster - 1
        y_bot = y_top + 1
        if y_bot >= fh:
            continue
        for cx in range(cw):
            x0 = cx * cluster
            x1 = min(fw, x0 + cluster)
            for x in range(x0, x1):
                _try_border(x, y_top, x, y_bot)
                if x + 1 < x1:
                    _try_border(x, y_top, x + 1, y_bot)
                    _try_border(x + 1, y_top, x, y_bot)

    # Four-cluster corners.
    for cy in range(ch - 1):
        y_top = (cy + 1) * cluster - 1
        y_bot = y_top + 1
        if y_bot >= fh:
            continue
        for cx in range(cw - 1):
            x_left = (cx + 1) * cluster - 1
            x_right = x_left + 1
            if x_right >= fw:
                continue
            _try_border(x_left, y_bot, x_right, y_top)
            _try_border(x_left, y_top, x_right, y_bot)

    return EdgePortalGraph(
        cluster=cluster,
        fine_width=fw,
        fine_height=fh,
        labels=labels,
        nodes=nodes,
        edges=dict(edges),
    )


def find_fine_path(
    layers: EdgeLayers,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    allowed: Optional[np.ndarray] = None,
) -> list[tuple[int, int]]:
    """A* with step cost 1; neighbors from ``can_step``."""
    sx, sy = start
    gx, gy = goal
    if not layers.standable(sx, sy) or not layers.standable(gx, gy):
        return []
    if start == goal:
        return [start]

    def ok(x: int, y: int) -> bool:
        if not layers.standable(x, y):
            return False
        if allowed is None:
            return True
        return bool(allowed[y, x])

    if not ok(sx, sy) or not ok(gx, gy):
        return []

    def h(x: int, y: int) -> int:
        return max(abs(x - gx), abs(y - gy))

    open_heap: list[tuple[int, int, tuple[int, int]]] = []
    counter = 0
    heapq.heappush(open_heap, (h(sx, sy), counter, start))
    came: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path
        closed.add(cur)
        cx, cy = cur
        for dx, dy in _AXIS + _DIAG:
            nx, ny = cx + dx, cy + dy
            if not ok(nx, ny):
                continue
            if not layers.can_step(cx, cy, nx, ny):
                continue
            nxt = (nx, ny)
            if nxt in closed:
                continue
            tentative = g_score[cur] + 1
            prev = g_score.get(nxt)
            if prev is not None and tentative >= prev:
                continue
            came[nxt] = cur
            g_score[nxt] = tentative
            counter += 1
            heapq.heappush(open_heap, (tentative + h(nx, ny), counter, nxt))
    return []


def plan_path(
    layers: EdgeLayers,
    graph: EdgePortalGraph,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    lookahead: int = 2,
) -> list[tuple[int, int]]:
    """Abstract corridor refine, then full fine fallback."""
    abstract = graph.find_abstract_path(start, goal)
    fine: list[tuple[int, int]] = []
    if abstract:
        start_n = graph.node_at(*start)
        try:
            idx = abstract.index(start_n) if start_n is not None else 0
        except ValueError:
            idx = 0
        look = min(len(abstract) - 1, idx + max(1, lookahead))
        hop = abstract[idx : look + 1]
        mask = graph.corridor_mask(hop)
        # Aim at lookahead node rep, or goal if inside hop.
        goal_n = graph.node_at(*goal)
        if goal_n is not None and goal_n in hop:
            local_goal = goal
        else:
            node = graph.nodes[abstract[look]]
            local_goal = (node.rep_x, node.rep_y)
        fine = find_fine_path(layers, start, local_goal, allowed=mask)
        if not fine and local_goal != goal:
            mask = graph.corridor_mask(abstract)
            fine = find_fine_path(layers, start, goal, allowed=mask)
    if not fine:
        fine = find_fine_path(layers, start, goal)
    return fine


def cache_dir() -> Path:
    return Path(__file__).resolve().parent / "cache"


def save_cache(
    layers: EdgeLayers,
    graph: EdgePortalGraph,
    path: Path | None = None,
) -> Path:
    out = path or (cache_dir() / "talking_island_edge.pkl")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "source": layers.source,
        "origin": (layers.origin_x, layers.origin_y),
        "solid": layers.solid,
        "block_n": layers.block_n,
        "block_e": layers.block_e,
        "covered": layers.covered,
        "graph": graph,
    }
    with out.open("wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return out


def load_cache(path: Path | None = None) -> tuple[EdgeLayers, EdgePortalGraph]:
    src = path or (cache_dir() / "talking_island_edge.pkl")
    with src.open("rb") as fh:
        payload = pickle.load(fh)
    layers = EdgeLayers(
        solid=payload["solid"],
        block_n=payload["block_n"],
        block_e=payload["block_e"],
        covered=payload["covered"],
        origin_x=int(payload["origin"][0]),
        origin_y=int(payload["origin"][1]),
        source=str(payload.get("source") or ""),
    )
    return layers, payload["graph"]
