"""Dungeon patrol: ordered midpoints the bot travels between."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml

from app.bot_log import get_logger
from app._03_world.map_pack import get_active_map_pack
from app._03_world.terrain_map import TerrainMap
from app._03_world.world_coords import tile_chebyshev
from app._04_decision.dungeon import is_dungeon_map
from app._04_decision.farm_area import ARRIVE_TILES
from app._04_decision.mode_control import begin_travel
from app._04_decision.nav_config import get_terrain_map

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard

PURPOSE_PATROL = "patrol"

_patrol_waypoints: list[tuple[int, int]] = []


def get_patrol_waypoints() -> list[tuple[int, int]]:
    return list(_patrol_waypoints)


def set_patrol_waypoints(points: list[tuple[int, int]]) -> None:
    global _patrol_waypoints
    _patrol_waypoints = list(points)


def clear_patrol_waypoints() -> None:
    set_patrol_waypoints([])


def _snap_walkable(
    terrain: TerrainMap,
    x: int,
    y: int,
    *,
    radius: int = 6,
) -> Optional[tuple[int, int]]:
    if terrain.is_walkable(x, y):
        return (x, y)
    best: Optional[tuple[int, int]] = None
    best_d: Optional[int] = None
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            nx, ny = x + dx, y + dy
            if not terrain.is_walkable(nx, ny):
                continue
            d = tile_chebyshev(x, y, nx, ny)
            if best_d is None or d < best_d:
                best_d = d
                best = (nx, ny)
    return best


def load_patrol_waypoints_from_yaml(
    path: Path | str | None,
    *,
    terrain: Optional[TerrainMap] = None,
) -> list[tuple[int, int]]:
    """Parse ``patrol.yaml``: ``waypoints: [{x, y}, ...]`` (nav tiles)."""
    if path is None:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    with p.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    raw: Any
    if isinstance(doc, list):
        raw = doc
    elif isinstance(doc, dict):
        raw = doc.get("waypoints") or doc.get("points") or doc.get("areas") or []
    else:
        return []
    if not isinstance(raw, list):
        return []

    terr = terrain if terrain is not None else get_terrain_map()
    out: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "x" in item and "y" in item:
            x, y = int(item["x"]), int(item["y"])
        elif "x0" in item and "y0" in item:
            x = (int(item["x0"]) + int(item.get("x1", item["x0"]))) // 2
            y = (int(item["y0"]) + int(item.get("y1", item["y0"]))) // 2
        else:
            continue
        if terr is not None:
            snapped = _snap_walkable(terr, x, y)
            if snapped is None:
                continue
            x, y = snapped
        out.append((x, y))
    return out


def _userdata_overlay_patrol(map_id: str) -> Optional[Path]:
    mid = str(map_id or "").strip()
    if not mid:
        return None
    overlay = (
        Path(__file__).resolve().parents[3] / "userdata" / "maps" / mid / "patrol.yaml"
    )
    return overlay if overlay.is_file() else None


def configure_patrol_waypoints(
    *,
    path: Path | str | None = None,
    terrain: Optional[TerrainMap] = None,
) -> list[tuple[int, int]]:
    """Load patrol points from overlay, then pack ``patrol.yaml``."""
    if path is None:
        pack = get_active_map_pack()
        if pack is not None and is_dungeon_map(pack.id, pack.name):
            path = _userdata_overlay_patrol(pack.id) or pack.patrol_path or (
                pack.root / "patrol.yaml"
            )
        elif is_dungeon_map() and pack is not None:
            path = pack.patrol_path or (pack.root / "patrol.yaml")
    points = load_patrol_waypoints_from_yaml(path, terrain=terrain)
    set_patrol_waypoints(points)
    log = get_logger("nav")
    if points:
        log.info("patrol waypoints=%s (%s)", len(points), path)
    elif is_dungeon_map():
        log.warning("dungeon map but no patrol waypoints at %s", path)
    return points


def nearest_patrol_index(
    origin: tuple[int, int],
    waypoints: list[tuple[int, int]] | None = None,
) -> int:
    pts = waypoints if waypoints is not None else _patrol_waypoints
    if not pts:
        return 0
    ox, oy = origin
    best_i = 0
    best_d: Optional[int] = None
    for i, (x, y) in enumerate(pts):
        d = tile_chebyshev(ox, oy, x, y)
        if best_d is None or d < best_d:
            best_d = d
            best_i = i
    return best_i


def ensure_patrol_index(blackboard: "Blackboard") -> None:
    if blackboard.scratch.get("patrol_ready"):
        return
    pts = _patrol_waypoints
    if not pts:
        blackboard.patrol_index = 0
        blackboard.scratch["patrol_ready"] = True
        return
    origin = (blackboard.world_origin.x, blackboard.world_origin.y)
    blackboard.patrol_index = nearest_patrol_index(origin, pts)
    blackboard.scratch["patrol_ready"] = True


def current_patrol_goal(
    blackboard: "Blackboard",
) -> Optional[tuple[int, int]]:
    pts = _patrol_waypoints
    if not pts:
        return None
    ensure_patrol_index(blackboard)
    idx = int(blackboard.patrol_index) % len(pts)
    return pts[idx]


def advance_patrol(blackboard: "Blackboard") -> Optional[tuple[int, int]]:
    """Advance to the next midpoint (wrap). Returns that tile."""
    pts = _patrol_waypoints
    if not pts:
        return None
    ensure_patrol_index(blackboard)
    blackboard.patrol_index = (int(blackboard.patrol_index) + 1) % len(pts)
    return pts[blackboard.patrol_index]


def patrol_arrived(blackboard: "Blackboard") -> bool:
    goal = current_patrol_goal(blackboard)
    if goal is None:
        return True
    return (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            goal[0],
            goal[1],
        )
        <= ARRIVE_TILES
    )


def begin_or_continue_patrol(blackboard: "Blackboard") -> bool:
    """Start/keep travel to the current patrol midpoint. True if traveling."""
    from app._04_decision.mode_control import set_mode
    from app._04_decision.player_mode import PlayerMode

    goal = current_patrol_goal(blackboard)
    if goal is None:
        return False

    if patrol_arrived(blackboard):
        goal = advance_patrol(blackboard)
        if goal is None:
            return False

    if (
        blackboard.nav_goal == goal
        and blackboard.travel_purpose == PURPOSE_PATROL
    ):
        if blackboard.player_mode is not PlayerMode.TRAVELING:
            set_mode(blackboard, PlayerMode.TRAVELING)
        return True

    begin_travel(
        blackboard,
        goal,
        purpose=PURPOSE_PATROL,
        reason=f"patrol waypoint {int(blackboard.patrol_index)}",
    )
    return True


def patrol_waypoints_yaml_text(
    points: list[tuple[int, int]],
    names: list[str] | None = None,
) -> str:
    """Serialize dungeon midpoints to pack ``patrol.yaml`` format."""
    lines = [
        "# Patrol midpoints (nav tiles). Dungeon mode travels these in order.",
        "waypoints:",
    ]
    if not points:
        lines.append("  # (empty — Place midpoints, then Save)")
        return "\n".join(lines) + "\n"
    labels = names or []
    for i, (x, y) in enumerate(points):
        name = (
            labels[i]
            if i < len(labels) and str(labels[i]).strip()
            else f"mid_{i + 1}"
        )
        lines.append(f"  - {{ x: {x}, y: {y}, name: {name} }}")
    return "\n".join(lines) + "\n"


def save_patrol_waypoints_yaml(
    path: Path | str,
    points: list[tuple[int, int]],
    names: list[str] | None = None,
) -> Path:
    """Write ``patrol.yaml``; create parent folders if needed."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(patrol_waypoints_yaml_text(points, names), encoding="utf-8")
    return out


def load_patrol_entries_from_yaml(
    path: Path | str | None,
) -> list[tuple[int, int, str]]:
    """``(x, y, name)`` rows from ``patrol.yaml`` (no walkable snap)."""
    if path is None:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    with p.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    if isinstance(doc, list):
        raw = doc
    elif isinstance(doc, dict):
        raw = doc.get("waypoints") or doc.get("points") or []
    else:
        return []
    if not isinstance(raw, list):
        return []
    out: list[tuple[int, int, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        if "x" not in item or "y" not in item:
            continue
        name = str(item.get("name") or f"mid_{i + 1}")
        out.append((int(item["x"]), int(item["y"]), name))
    return out


__all__ = [
    "PURPOSE_PATROL",
    "get_patrol_waypoints",
    "set_patrol_waypoints",
    "clear_patrol_waypoints",
    "load_patrol_waypoints_from_yaml",
    "configure_patrol_waypoints",
    "nearest_patrol_index",
    "ensure_patrol_index",
    "current_patrol_goal",
    "advance_patrol",
    "patrol_arrived",
    "begin_or_continue_patrol",
    "patrol_waypoints_yaml_text",
    "save_patrol_waypoints_yaml",
    "load_patrol_entries_from_yaml",
]
