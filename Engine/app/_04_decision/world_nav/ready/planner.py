"""World-nav coarse planner: walk (A*) + talking scroll + map transitions.

Standalone — does not import manmabot. Planning only (no execution).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .graph import Hub, Transition, WorldNavGraph, load_graph
from .map_assets import discover_map_packs
from .nav_path import WalkService

NodeKey = tuple[int, int, int]  # mapId, x, y

# Late import path for teleporter links (lives next to session, not ready/).
def _teleporter_links(transitions: list[Transition], *, adena: int | None):
    from app._04_decision.world_nav.npc_teleporters import load_npc_teleporter_links

    return load_npc_teleporter_links(transitions, adena=adena)


@dataclass(frozen=True)
class Pose:
    map_id: int
    x: int
    y: int

    def key(self) -> NodeKey:
        return (self.map_id, self.x, self.y)


@dataclass(frozen=True)
class Goal:
    kind: Literal["map", "point"]
    map_id: int
    x: int | None = None
    y: int | None = None

    @staticmethod
    def map_goal(map_id: int) -> Goal:
        return Goal(kind="map", map_id=map_id)

    @staticmethod
    def point_goal(map_id: int, x: int, y: int) -> Goal:
        return Goal(kind="point", map_id=map_id, x=x, y=y)

    def is_satisfied(self, pose: Pose) -> bool:
        if pose.map_id != self.map_id:
            return False
        if self.kind == "map":
            return True
        return pose.x == self.x and pose.y == self.y


@dataclass
class PlanStep:
    op: Literal["walk", "talking_scroll", "map_transition", "npc_teleporter"]
    cost_tiles: int
    detail: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        if self.op == "walk":
            a = self.detail["from"]
            b = self.detail["to"]
            n = len(self.detail.get("path") or [])
            return (
                f"WALK map{a['mapId']} ({a['x']},{a['y']}) -> ({b['x']},{b['y']}) "
                f"[{self.cost_tiles} tiles A* path_pts={n}]"
            )
        if self.op == "talking_scroll":
            t = self.detail["to"]
            return (
                f"SCROLL -> {self.detail.get('label', '')} "
                f"map{t['mapId']} ({t['x']},{t['y']}) [+{self.cost_tiles}]"
            )
        if self.op == "npc_teleporter":
            a = self.detail["from"]
            b = self.detail["to"]
            kind = self.detail.get("teleport_kind") or "dungeon_gate"
            dest = self.detail.get("destination_dungeon")
            land = f"land map{b['mapId']}({b['x']},{b['y']})"
            if kind == "field_land":
                where = land
            else:
                where = f"gate ({b['x']},{b['y']}) dest_map={dest}"
            return (
                f"NPC_TP {self.detail.get('behavior_id', '')} "
                f"map{a['mapId']}({a['x']},{a['y']}) -> {where} "
                f"adena={self.detail.get('adena_cost', 0)} "
                f"[+{self.cost_tiles}]"
            )
        t = self.detail
        frm, to = t["from"], t["to"]
        return (
            f"TRANSITION {t.get('edge_id', '')} "
            f"map{frm['mapId']}({frm['x']},{frm['y']}) -> "
            f"map{to['mapId']}({to['x']},{to['y']}) [+{self.cost_tiles}]"
        )


@dataclass
class PlanResult:
    ok: bool
    total_cost_tiles: int = 0
    steps: list[PlanStep] = field(default_factory=list)
    end_pose: Pose | None = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total_cost_tiles": self.total_cost_tiles,
            "error": self.error,
            "end_pose": None
            if self.end_pose is None
            else {
                "mapId": self.end_pose.map_id,
                "x": self.end_pose.x,
                "y": self.end_pose.y,
            },
            "steps": [
                {"op": s.op, "cost_tiles": s.cost_tiles, "detail": s.detail, "summary": s.summary()}
                for s in self.steps
            ],
            "meta": self.meta,
        }


@dataclass
class _Prev:
    prev_key: NodeKey | None
    op: str
    cost: int
    detail: dict[str, Any]


class WorldNavPlanner:
    def __init__(
        self,
        graph: WorldNavGraph | None = None,
        walk: WalkService | None = None,
    ) -> None:
        self.graph = graph or load_graph()
        if walk is None:
            from .nav_path import shared_walk_service

            walk = shared_walk_service()
        self.walk = walk

    def reload(self, manifest_path: Path | None = None) -> None:
        self.graph = load_graph(manifest_path)
        self.walk.set_packs(discover_map_packs())

    def plan(
        self,
        start: Pose,
        goal: Goal,
        *,
        has_talking_scroll: bool = True,
        adena: int | None = None,
        use_npc_teleporters: bool = True,
    ) -> PlanResult:
        g = self.graph
        if goal.kind == "point" and (goal.x is None or goal.y is None):
            return PlanResult(ok=False, error="PointGoal requires x and y")

        # Already on goal map → walk only (no scroll/TP/transition off-map).
        same_map = int(start.map_id) == int(goal.map_id)
        from app._04_decision.world_nav.npc_teleporters import (
            NEAR_ENTRANCE_NO_TELEPORTER_TILES,
            near_goal_ground_enter,
        )

        near_entrance = (
            False
            if same_map
            else near_goal_ground_enter(
                g.transitions,
                start_map=start.map_id,
                start_x=start.x,
                start_y=start.y,
                goal_map=goal.map_id,
                radius=NEAR_ENTRANCE_NO_TELEPORTER_TILES,
            )
        )
        # Same-map field teleporters (e.g. Giran → Dragon Valley field) must stay
        # eligible; dungeon_gate links remain useful mainly when leaving the map.
        # Near a goal ground_enter: prefer walk — no NPC TP.
        allow_npc_tp = bool(use_npc_teleporters) and not near_entrance
        # Talking scroll is allowed on the same map too: meta-search compares
        # scroll_cost vs walk (e.g. scroll to Giran hub then field TP beats a
        # 500+ tile walk to the NPC). Near a goal ground_enter: prefer walk.
        allow_scroll = bool(has_talking_scroll) and not near_entrance
        tp_links = (
            _teleporter_links(g.transitions, adena=adena) if allow_npc_tp else []
        )
        if tp_links:
            from app._04_decision.world_nav.npc_teleporters import (
                filter_teleporter_links_for_goal,
            )

            # dungeon_gate only when its destination serves the goal map;
            # field_land always eligible (same-map region hops). Stops e.g.
            # Gludin→dungeon7 shutter from winning a path to Dragon Valley.
            tp_links = filter_teleporter_links_for_goal(
                tp_links,
                g.transitions,
                goal_map=int(goal.map_id),
                same_map=same_map,
            )
            if not tp_links:
                allow_npc_tp = False

        nodes: set[NodeKey] = {start.key()}
        for h in g.hubs:
            nodes.add(h.key)
        for t in g.transitions:
            nodes.add(t.from_key)
            nodes.add(t.to_key)
        for link in tp_links:
            nodes.add(link.npc_key)
            nodes.add(link.gate_key)
        if goal.kind == "point":
            nodes.add((goal.map_id, int(goal.x), int(goal.y)))

        by_map: dict[int, list[NodeKey]] = {}
        for n in nodes:
            by_map.setdefault(n[0], []).append(n)

        hub_keys = {h.key for h in g.hubs}
        transition_from_keys = {t.from_key for t in g.transitions}
        npc_keys = {link.npc_key for link in tp_links}
        goal_keys: set[NodeKey] = set()
        if goal.kind == "point":
            goal_keys.add((goal.map_id, int(goal.x), int(goal.y)))

        transitions_from: dict[NodeKey, list[Transition]] = {}
        dungeon_floors: set[int] = set()
        for t in g.transitions:
            transitions_from.setdefault(t.from_key, []).append(t)
            if t.from_floor is not None:
                dungeon_floors.add(int(t.from_map))
            if t.to_floor is not None:
                dungeon_floors.add(int(t.to_map))
        # Once the search is on this map, leaving it cannot help a hunt there.
        goal_is_dungeon_floor = int(goal.map_id) in dungeon_floors
        # These maps are entered at their own mainland door. An interior
        # ladder would step in through another floor.
        from app._04_decision.dungeon_floor_route import is_direct_field_door_map

        own_field_door = is_direct_field_door_map(int(goal.map_id))

        teleporters_from: dict[NodeKey, list[Any]] = {}
        for link in tp_links:
            teleporters_from.setdefault(link.npc_key, []).append(link)

        scroll_cost = g.scroll_cost_tiles

        dist: dict[NodeKey, int] = {start.key(): 0}
        prev: dict[NodeKey, _Prev] = {}
        pq: list[tuple[int, NodeKey]] = [(0, start.key())]
        visited: set[NodeKey] = set()

        found: NodeKey | None = None
        walk_fail = 0
        walk_ok = 0
        walk_skipped = 0

        def _cheb(a: NodeKey, b: NodeKey) -> int:
            return max(abs(a[1] - b[1]), abs(a[2] - b[2]))

        def _useful_walk(u: NodeKey, v: NodeKey) -> bool:
            """Skip long hub↔hub walks when scroll can do it cheaper."""
            if v in transition_from_keys or v in goal_keys or v in npc_keys:
                return True
            if u in npc_keys:
                return True
            if goal.kind == "map" and v[0] == goal.map_id:
                # any node already on goal map satisfies MapGoal — no walk needed
                return False
            if allow_scroll and v in hub_keys:
                # Scroll to that hub costs scroll_cost; only walk if clearly cheaper.
                return _cheb(u, v) < scroll_cost
            if allow_scroll and u in hub_keys and v in hub_keys:
                return _cheb(u, v) < scroll_cost
            return True

        while pq:
            cost, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            u_pose = Pose(u[0], u[1], u[2])
            if goal.is_satisfied(u_pose):
                found = u
                break

            # Same-map walks: Chebyshev for meta-search speed; A* filled in on final path.
            for v in by_map.get(u[0], []):
                if v == u:
                    continue
                if not _useful_walk(u, v):
                    walk_skipped += 1
                    continue
                w = _cheb(u, v)
                # Chebyshev crosses a wall. A yard that ends before the
                # other cell is not a walk, so the search keeps the door.
                if not self.walk.same_component(u[0], u[1], u[2], v[1], v[2]):
                    walk_fail += 1
                    continue
                walk_ok += 1
                nc = cost + w
                if nc < dist.get(v, 10**18):
                    dist[v] = nc
                    prev[v] = _Prev(
                        u,
                        "walk",
                        w,
                        {
                            "from": {"mapId": u[0], "x": u[1], "y": u[2]},
                            "to": {"mapId": v[0], "x": v[1], "y": v[2]},
                            "metric": "chebyshev_meta",
                        },
                    )
                    heapq.heappush(pq, (nc, v))

            # Talking scroll to a hub (same map or cross-map). Cost is compared
            # with walk; near the goal door this edge is omitted above.
            if allow_scroll:
                for h in g.hubs:
                    if same_map and int(h.map_id) != int(goal.map_id):
                        continue
                    v = h.key
                    w = g.scroll_cost_tiles
                    nc = cost + w
                    if nc < dist.get(v, 10**18):
                        dist[v] = nc
                        prev[v] = _Prev(
                            u,
                            "talking_scroll",
                            w,
                            {
                                "from": {"mapId": u[0], "x": u[1], "y": u[2]},
                                "to": {"mapId": v[0], "x": v[1], "y": v[2]},
                                "label": h.label(),
                                "plan_index": h.index,
                                "region": h.region,
                                "name": h.name,
                                "ui": h.ui,
                            },
                        )
                        heapq.heappush(pq, (nc, v))

            # Start already on the goal map: no transition off it.
            # Goal is a dungeon floor and this node is already there: same ban.
            # Ladders that climb toward a deeper goal still expand, because
            # those nodes are not on the goal map yet.
            if not same_map:
                on_goal_floor = (
                    goal_is_dungeon_floor and int(u[0]) == int(goal.map_id)
                )
                for t in transitions_from.get(u, []):
                    if on_goal_floor and int(t.to_map) != int(u[0]):
                        continue
                    if own_field_door and t.edge_type == "floor_ladder":
                        continue
                    v = t.to_key
                    w = 0
                    nc = cost + w
                    if nc < dist.get(v, 10**18):
                        dist[v] = nc
                        prev[v] = _Prev(
                            u,
                            "map_transition",
                            w,
                            {
                                "edge_id": t.edge_id,
                                "edge_type": t.edge_type,
                                "from": {
                                    "mapId": t.from_map,
                                    "x": t.from_x,
                                    "y": t.from_y,
                                },
                                "to": {"mapId": t.to_map, "x": t.to_x, "y": t.to_y},
                                "meta": t.meta,
                            },
                        )
                        heapq.heappush(pq, (nc, v))

            # NPC teleporter: dialog shortcut to a planned arrival cell.
            # dungeon_gate → gate approach (live land rewritten after execute).
            # field_land → absolute land xy (often same mainland map).
            # Disabled when already near the destination entrance.
            for link in teleporters_from.get(u, []):
                v = link.land_key
                w = int(link.cost_tiles)
                nc = cost + w
                if nc < dist.get(v, 10**18):
                    dist[v] = nc
                    kind = str(
                        getattr(link, "teleport_kind", None) or "dungeon_gate"
                    )
                    detail: dict[str, Any] = {
                        "behavior_id": link.behavior_id,
                        "name": link.name,
                        "adena_cost": link.adena_cost,
                        "teleport_kind": kind,
                        "destination_dungeon": int(link.destination_dungeon),
                        "gate_edge_id": str(
                            getattr(link, "gate_edge_id", "") or ""
                        ),
                        "from": {
                            "mapId": link.map_id,
                            "x": link.npc_x,
                            "y": link.npc_y,
                        },
                        "to": {
                            "mapId": int(link.land_map_id),
                            "x": int(link.land_x),
                            "y": int(link.land_y),
                        },
                        "land_map_id": int(link.land_map_id),
                        "land_xy": [int(link.land_x), int(link.land_y)],
                    }
                    if kind != "field_land" and int(link.destination_dungeon) > 0:
                        detail["gate_to"] = {
                            "mapId": link.destination_dungeon,
                            "x": int(getattr(link, "gate_to_x", 0) or 0),
                            "y": int(getattr(link, "gate_to_y", 0) or 0),
                        }
                        # Dungeon shutter TPs stay on the NPC map until the gate walk.
                        detail["land_map_id"] = int(link.map_id)
                        detail["to"] = {
                            "mapId": int(link.map_id),
                            "x": int(link.land_x),
                            "y": int(link.land_y),
                        }
                    prev[v] = _Prev(u, "npc_teleporter", w, detail)
                    heapq.heappush(pq, (nc, v))

        meta = {
            "has_talking_scroll": has_talking_scroll,
            "allow_talking_scroll": allow_scroll,
            "adena": adena,
            "use_npc_teleporters": use_npc_teleporters,
            "allow_npc_teleporters": allow_npc_tp,
            "same_map_no_intermap": same_map,
            "stay_on_goal_dungeon_floor": goal_is_dungeon_floor,
            "near_entrance_no_teleporter": near_entrance,
            "near_entrance_radius": NEAR_ENTRANCE_NO_TELEPORTER_TILES,
            "npc_teleporter_links": len(tp_links),
            "scroll_cost_tiles": g.scroll_cost_tiles,
            "walk_metric": "astar",
            "walk_ok": walk_ok,
            "walk_fail": walk_fail,
            "walk_skipped": walk_skipped,
            "hubs": len(g.hubs),
            "transitions": len(g.transitions),
            "nodes": len(nodes),
            "goal": {
                "kind": goal.kind,
                "mapId": goal.map_id,
                "x": goal.x,
                "y": goal.y,
            },
            "start": {"mapId": start.map_id, "x": start.x, "y": start.y},
            "execution_policy": "on_failure: report_to_user_no_retry (planning_only)",
        }

        if found is None:
            why = "no path"
            if not has_talking_scroll:
                why += " (no talking scroll; walk+transition only)"
            return PlanResult(ok=False, error=why, meta=meta)

        steps_rev: list[PlanStep] = []
        cur: NodeKey | None = found
        while cur is not None and cur in prev:
            p = prev[cur]
            steps_rev.append(PlanStep(op=p.op, cost_tiles=p.cost, detail=dict(p.detail)))  # type: ignore[arg-type]
            cur = p.prev_key
        steps_rev.reverse()
        steps = [s for s in steps_rev if not (s.op == "walk" and s.cost_tiles == 0)]

        # Refine walk segments with real A* paths (nav.png). Meta-search used Chebyshev.
        total = 0
        refined: list[PlanStep] = []
        for s in steps:
            if s.op != "walk":
                total += s.cost_tiles
                refined.append(s)
                continue
            a, b = s.detail["from"], s.detail["to"]
            wr = self.walk.walk(a["mapId"], a["x"], a["y"], b["x"], b["y"])
            if not wr.ok:
                meta["walk_refine_fail"] = wr.error
                return PlanResult(
                    ok=False,
                    error=f"A* walk failed on map{a['mapId']} "
                    f"({a['x']},{a['y']})->({b['x']},{b['y']}): {wr.error}",
                    meta=meta,
                )
            detail = dict(s.detail)
            detail["path"] = [{"x": x, "y": y} for x, y in wr.path_world]
            detail["metric"] = "astar"
            detail["chebyshev_meta"] = s.cost_tiles
            refined.append(PlanStep(op="walk", cost_tiles=wr.cost, detail=detail))
            total += wr.cost
            walk_ok += 1

        meta["walk_metric"] = "astar"
        meta["total_chebyshev_meta"] = dist[found]
        meta["total_astar"] = total

        return PlanResult(
            ok=True,
            total_cost_tiles=total,
            steps=refined,
            end_pose=Pose(found[0], found[1], found[2]),
            meta=meta,
        )


def plan(
    start: Pose,
    goal: Goal,
    *,
    has_talking_scroll: bool = True,
    adena: int | None = None,
    use_npc_teleporters: bool = True,
    graph: WorldNavGraph | None = None,
) -> PlanResult:
    return WorldNavPlanner(graph).plan(
        start,
        goal,
        has_talking_scroll=has_talking_scroll,
        adena=adena,
        use_npc_teleporters=use_npc_teleporters,
    )
