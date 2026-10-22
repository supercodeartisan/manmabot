"""Catalog and plan world-nav routes. Does not walk, click, or scroll."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from app._04_decision.world_nav.npc_teleporters import load_npc_teleporter_links
from app._04_decision.world_nav.ready.graph import WorldNavGraph, load_graph
from app._04_decision.world_nav.ready.map_assets import discover_map_packs
from app._04_decision.world_nav.ready.planner import Goal, Pose, WorldNavPlanner


ProgressFn = Callable[[str], None]
CancelFn = Callable[[], bool]


@dataclass(frozen=True)
class GoalChoice:
    key: str
    label: str
    kind: str  # map | point
    map_id: int
    x: int | None = None
    y: int | None = None


@dataclass
class Catalog:
    graph: WorldNavGraph
    planner: WorldNavPlanner
    goals: list[GoalChoice]
    pack_ids: dict[int, str]


def load_catalog() -> Catalog:
    graph = load_graph()
    packs = discover_map_packs()
    pack_ids = {int(p.map_id): p.pack_id for p in packs}
    goals: list[GoalChoice] = []
    for mid in _graph_map_ids(graph):
        name = graph.map_label(mid)
        pack = pack_ids.get(mid, "no-pack")
        goals.append(
            GoalChoice(
                key=f"map:{mid}",
                label=f"map {mid}  {name}  [{pack}]",
                kind="map",
                map_id=mid,
            )
        )
    for hub in graph.hubs:
        goals.append(
            GoalChoice(
                key=f"hub:{hub.index}",
                label=(
                    f"hub {hub.index}  {hub.region}/{hub.name}  "
                    f"map {hub.map_id} ({hub.x},{hub.y})"
                ),
                kind="point",
                map_id=hub.map_id,
                x=hub.x,
                y=hub.y,
            )
        )
    links = load_npc_teleporter_links(graph.transitions, adena=None)
    for link in links:
        if getattr(link, "is_field_land", False):
            dest_bit = (
                f"→ field map{link.land_map_id} ({link.land_x},{link.land_y})"
            )
            key_tail = f"field:{link.land_map_id}:{link.land_x}:{link.land_y}"
        else:
            dest_bit = f"→ dungeon {link.destination_dungeon}"
            key_tail = link.gate_edge_id or f"dungeon:{link.destination_dungeon}"
        goals.append(
            GoalChoice(
                key=f"npc:{link.behavior_id}:{key_tail}",
                label=(
                    f"npc {link.behavior_id}  {link.name}  "
                    f"map {link.map_id} ({link.npc_x},{link.npc_y}) "
                    f"{dest_bit}"
                ),
                kind="point",
                map_id=link.map_id,
                x=link.npc_x,
                y=link.npc_y,
            )
        )
    return Catalog(graph=graph, planner=WorldNavPlanner(graph), goals=goals, pack_ids=pack_ids)


def goal_choices(catalog: Catalog, *, scope: str) -> list[GoalChoice]:
    if scope == "maps":
        return [g for g in catalog.goals if g.key.startswith("map:")]
    if scope == "hubs":
        return [g for g in catalog.goals if g.key.startswith("hub:")]
    if scope == "npcs":
        return [g for g in catalog.goals if g.key.startswith("npc:")]
    return list(catalog.goals)


def choice_to_goal(choice: GoalChoice) -> Goal:
    if choice.kind == "point" and choice.x is not None and choice.y is not None:
        return Goal.point_goal(choice.map_id, choice.x, choice.y)
    return Goal.map_goal(choice.map_id)


def read_live_pose() -> tuple[int, int, int]:
    """MapSubsystem mapId plus tile xy. Raises if the game is not readable."""
    from session.elevate import prepare_runtime

    prepare_runtime()
    from app._01_perception.sensors import shared_sensors
    from app._03_world.merge.memory_sync import (
        player_game_xy_from_snapshot,
        player_map_id_from_snapshot,
    )

    buf = shared_sensors().capture_field()
    snap = buf.player if buf.player_ok and isinstance(buf.player, dict) else None
    print_snap = buf.print_state if isinstance(buf.print_state, dict) else None
    mid = player_map_id_from_snapshot(snap) if snap is not None else None
    xy = player_game_xy_from_snapshot(print_snap) if print_snap is not None else None
    if xy is None and snap is not None:
        xy = player_game_xy_from_snapshot(snap)
    if mid is None or xy is None:
        raise RuntimeError("live pose unavailable (mapId or xy). Game should be in-world.")
    return int(mid), int(xy[0]), int(xy[1])


def catalog_report(catalog: Catalog) -> str:
    g = catalog.graph
    links = load_npc_teleporter_links(g.transitions, adena=None)
    maps = [c for c in catalog.goals if c.key.startswith("map:")]
    hubs = [c for c in catalog.goals if c.key.startswith("hub:")]
    lines = [
        "World Nav Probe — catalog (plan only, no movement)",
        f"hubs {len(g.hubs)}   transitions {len(g.transitions)}   "
        f"graph maps {len(maps)}   npc links {len(links)}",
        f"scroll cost {g.scroll_cost_tiles} tiles",
        f"transitions: {g.transitions_source}",
        "",
        "── graph maps ──",
    ]
    for choice in maps:
        lines.append(f"  {choice.label}")
    lines.append("")
    lines.append("── talking-scroll hubs ──")
    for choice in hubs:
        lines.append(f"  {choice.label}")
    lines.append("")
    lines.append("── npc teleporter links (world_nav behaviors) ──")
    if not links:
        lines.append("  (none)")
    for link in links:
        if getattr(link, "is_field_land", False):
            dest_bit = (
                f"field map{link.land_map_id} ({link.land_x},{link.land_y})"
            )
        else:
            dest_bit = (
                f"gate {link.gate_edge_id} ({link.land_x},{link.land_y}) "
                f"dest {link.destination_dungeon}"
            )
        lines.append(
            f"  {link.behavior_id}  {link.name}  map {link.map_id} "
            f"({link.npc_x},{link.npc_y}) fare={link.adena_cost} {dest_bit}"
        )
    if g.gaps:
        lines.append("")
        lines.append(f"── recorded gaps {len(g.gaps)} ──")
        for gap in g.gaps[:40]:
            lines.append(f"  {gap}")
        if len(g.gaps) > 40:
            lines.append(f"  … {len(g.gaps) - 40} more")
    return "\n".join(lines)


def format_plan(choice: GoalChoice, result, *, elapsed_s: float) -> str:
    lines = [
        f"goal  {choice.label}",
        f"ok={result.ok}  cost={result.total_cost_tiles}  "
        f"steps={len(result.steps)}  {elapsed_s:.2f}s",
    ]
    if result.error:
        lines.append(f"error  {result.error}")
    if result.end_pose is not None:
        end = result.end_pose
        lines.append(f"end  map {end.map_id} ({end.x},{end.y})")
    ops: list[str] = []
    for step in result.steps:
        ops.append(step.op)
        lines.append(f"  {step.summary()}")
    if ops:
        lines.append("ops  " + ",".join(ops))
    return "\n".join(lines)


def plan_one(
    catalog: Catalog,
    start: tuple[int, int, int],
    choice: GoalChoice,
    *,
    has_talking_scroll: bool,
    adena: int | None,
    use_npc_teleporters: bool,
) -> str:
    pose = Pose(int(start[0]), int(start[1]), int(start[2]))
    t0 = time.perf_counter()
    result = catalog.planner.plan(
        pose,
        choice_to_goal(choice),
        has_talking_scroll=has_talking_scroll,
        adena=adena,
        use_npc_teleporters=use_npc_teleporters,
    )
    elapsed = time.perf_counter() - t0
    header = (
        f"start map {pose.map_id} ({pose.x},{pose.y})  "
        f"scroll={has_talking_scroll}  npc_tp={use_npc_teleporters}  "
        f"adena={adena if adena is not None else 'any'}"
    )
    return header + "\n" + format_plan(choice, result, elapsed_s=elapsed)


def sweep(
    catalog: Catalog,
    start: tuple[int, int, int],
    choices: list[GoalChoice],
    *,
    has_talking_scroll: bool,
    adena: int | None,
    use_npc_teleporters: bool,
    progress: Optional[ProgressFn] = None,
    cancelled: Optional[CancelFn] = None,
) -> str:
    pose = Pose(int(start[0]), int(start[1]), int(start[2]))
    ok_n = 0
    fail_n = 0
    lines = [
        "World Nav Probe — sweep (plan only, no movement)",
        f"start map {pose.map_id} ({pose.x},{pose.y})",
        f"targets {len(choices)}  scroll={has_talking_scroll}  "
        f"npc_tp={use_npc_teleporters}  adena={adena if adena is not None else 'any'}",
        "",
    ]
    t_all = time.perf_counter()
    for i, choice in enumerate(choices, start=1):
        if cancelled is not None and cancelled():
            lines.append("")
            lines.append(f"cancelled after {i - 1}/{len(choices)}")
            break
        if progress is not None:
            progress(f"{i}/{len(choices)}  {choice.label}")
        t0 = time.perf_counter()
        result = catalog.planner.plan(
            pose,
            choice_to_goal(choice),
            has_talking_scroll=has_talking_scroll,
            adena=adena,
            use_npc_teleporters=use_npc_teleporters,
        )
        elapsed = time.perf_counter() - t0
        mark = "OK" if result.ok else "FAIL"
        if result.ok:
            ok_n += 1
        else:
            fail_n += 1
        ops = ",".join(step.op for step in result.steps) or "-"
        err = f"  {result.error}" if result.error else ""
        lines.append(
            f"{mark}  {elapsed:6.2f}s  cost={result.total_cost_tiles:<6}  "
            f"{ops}  {choice.label}{err}"
        )
    elapsed_all = time.perf_counter() - t_all
    lines.append("")
    lines.append(
        f"done  ok {ok_n}  fail {fail_n}  {elapsed_all:.1f}s"
    )
    return "\n".join(lines)


def _graph_map_ids(graph: WorldNavGraph) -> list[int]:
    ids: set[int] = set()
    for hub in graph.hubs:
        ids.add(int(hub.map_id))
    for edge in graph.transitions:
        ids.add(int(edge.from_map))
        ids.add(int(edge.to_map))
    return sorted(ids)
