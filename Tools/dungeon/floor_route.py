"""Patrol-editor view of the shared dungeon floor calculator.

Path ordering and logical cells come from
``app._04_decision.dungeon_floor_route``. This file only adds the editor's
route-file writer. The live bot does not import this module.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app._04_decision.dungeon_floor_route import (
    GATE_TRANSITION_KIND,
    ClickPoint,
    FloorStep,
    FloorTransition,
    FloorWalk,
    MapChoice,
    PickedPoint,
    PortalEdge,
    RouteError,
    RouteSegment,
    _mouse_hops,
    _snap,
    _terrain_from_nav,
    choice_for_pack,
    choice_for_raw_map,
    floors_entrances_path,
    list_engine_maps,
    load_portal_edges,
    plan_floor_route,
    plan_floor_steps,
    steps_from_segments,
)
from session.paths import TOOLS_USERDATA_DIR, ensure_userdata

__all__ = [
    "ClickPoint",
    "GATE_TRANSITION_KIND",
    "FloorStep",
    "FloorTransition",
    "FloorWalk",
    "MapChoice",
    "PickedPoint",
    "PortalEdge",
    "RouteError",
    "RouteSegment",
    "_mouse_hops",
    "_snap",
    "_terrain_from_nav",
    "choice_for_pack",
    "choice_for_raw_map",
    "floors_entrances_path",
    "list_engine_maps",
    "load_portal_edges",
    "plan_floor_route",
    "plan_floor_steps",
    "save_route",
    "steps_from_segments",
]


def save_route(segments: list[RouteSegment]) -> list[Path]:
    """Write each floor's click points as patrol waypoints, plus one route file.

    Editor only. The live bot must not call this.
    """
    from settings.dungeon_assets import save_patrol_overlay

    ensure_userdata()
    written: list[Path] = []
    route_segments: list[dict] = []
    for segment in segments:
        points = [(c.nav_x, c.nav_y) for c in segment.clicks]
        names = [c.name for c in segment.clicks]
        if points:
            written.append(save_patrol_overlay(segment.choice.pack_id, points, names))
        route_segments.append(
            {
                "pack_id": segment.choice.pack_id,
                "kr": segment.choice.kr,
                "path_steps": max(0, len(segment.path) - 1),
                "clicks": [
                    {
                        "x": c.nav_x,
                        "y": c.nav_y,
                        "world_x": c.world_x,
                        "world_y": c.world_y,
                        "name": c.name,
                    }
                    for c in segment.clicks
                ],
            }
        )
    route_path = TOOLS_USERDATA_DIR / "dungeon_floor_route.yaml"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(
        yaml.safe_dump(
            {"segments": route_segments},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    written.append(route_path)
    return written
