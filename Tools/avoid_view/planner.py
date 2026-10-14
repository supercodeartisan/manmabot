"""One travel hop for the avoid-view tool.

The guide still comes from the bot's pathfinder. The interim waypoint does
not: walk the guide from the character and keep the last tile that is still
inside ``AVOID_RADIUS`` and is not a living body. The first step outside that
radius ends the search, so a later tile that comes back inside is not used.
The click is still the avoidance hop, so a far waypoint is not itself the
ground click. Dungeon patrol and loot use the same plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app._03_world.space.map_pack import MapPack, list_map_packs
from app._03_world.space.world_coords import WorldOrigin
from app._04_decision.avoidance import (
    AVOID_RADIUS,
    choose_body_click as _choose_click,
    click_clear,
    interim_waypoint,
    plan_body_click,
)
from app._04_decision.dungeon import DUNGEON_MAX_HOP_TILES
from app._04_decision.nav_prebuild import load_nav_prebuild
from app._04_decision.pathfinding import game_client_walk_tiles
from app._04_decision.player_mode import TRAVEL_MAX_HOP_TILES

_MAPS = Path(__file__).resolve().parents[2] / "Engine" / "data" / "maps"


@dataclass
class LoadedMap:
    pack_id: str
    name: str
    origin_x: int
    origin_y: int
    terrain: object
    coarse: object
    graph: object


@dataclass
class HopPlan:
    guide: list[tuple[int, int]] = field(default_factory=list)
    waypoint: tuple[int, int] | None = None
    click: tuple[int, int] | None = None
    polyline: list[tuple[int, int]] = field(default_factory=list)
    note: str = ""
    considered: set[tuple[int, int]] = field(default_factory=set)


def maps_dir() -> Path:
    return _MAPS


def list_packs() -> list[MapPack]:
    return list_map_packs(_MAPS)


def default_hop(pack_id: str) -> int:
    if "dungeon" in str(pack_id).lower():
        return int(DUNGEON_MAX_HOP_TILES)
    return int(TRAVEL_MAX_HOP_TILES)


def load_map(pack: MapPack) -> LoadedMap:
    terrain, coarse, graph, _meta = load_nav_prebuild(pack.root / "nav_prebuild")
    return LoadedMap(
        pack_id=str(pack.id),
        name=str(pack.name),
        origin_x=int(pack.origin_x),
        origin_y=int(pack.origin_y),
        terrain=terrain,
        coarse=coarse,
        graph=graph,
    )


def _polyline(start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    dx = int(goal[0]) - int(start[0])
    dy = int(goal[1]) - int(start[1])
    sx, sy = int(start[0]), int(start[1])
    return [(sx + rx, sy + ry) for rx, ry in game_client_walk_tiles(dx, dy)]


def plan_hop(
    loaded: LoadedMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    bodies: set[tuple[int, int]],
    *,
    max_hop: int,
) -> HopPlan:
    """Guide path, next waypoint, and the one avoidance click."""
    sx, sy = int(start[0]), int(start[1])
    near = {
        (int(x), int(y))
        for x, y in bodies
        if max(abs(int(x) - sx), abs(int(y) - sy)) <= int(AVOID_RADIUS)
        and (int(x), int(y)) != (sx, sy)
    }
    if (sx, sy) == (int(goal[0]), int(goal[1])):
        return HopPlan(note="already on the goal", considered=near)
    planned = plan_body_click(
        loaded.terrain,
        WorldOrigin(x=sx, y=sy),
        (int(goal[0]), int(goal[1])),
        set(bodies),
        max_hop=int(max_hop),
        coarse=loaded.coarse,
        portal_graph=loaded.graph,
        cluster=int(loaded.graph.cluster),
    )
    if planned.click is None:
        return HopPlan(
            guide=planned.guide,
            waypoint=planned.waypoint,
            note=planned.note,
            considered=near,
        )
    return HopPlan(
        guide=planned.guide,
        waypoint=planned.waypoint,
        click=planned.click,
        polyline=_polyline((sx, sy), planned.click),
        note=planned.note,
        considered=near,
    )


def line_still_clear(
    loaded: LoadedMap,
    start: tuple[int, int],
    click: tuple[int, int],
    bodies: set[tuple[int, int]],
) -> bool:
    sx, sy = int(start[0]), int(start[1])
    near = {
        (int(x), int(y))
        for x, y in bodies
        if max(abs(int(x) - sx), abs(int(y) - sy)) <= int(AVOID_RADIUS)
    }
    return click_clear(loaded.terrain, near, (sx, sy), (int(click[0]), int(click[1])))
