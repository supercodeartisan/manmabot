"""Party hunt routine, stored apart from the solo bot routine.

The map folder (terrain, art, the shared area catalog) stays the solo pack.
Chosen maps, stay times, and the coordinate copy live here and on disk as
``party_routine.json``. ``normalize_routine`` drops these coordinate fields,
so a party row cannot become the solo ``routine.json`` by passing through it.
"""

from __future__ import annotations

import uuid
from typing import Any

from settings.farm_schedule import (
    MAX_ROUTINE_MINUTES,
    clamp_farm_stay_s,
    normalize_farm_stays_s,
)


def _area(item: Any) -> dict[str, Any] | None:
    """One hunt mark: a rectangle (drive) or a point (stake)."""
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    shape = str(item.get("shape") or "area").strip().lower()
    region = str(item.get("region") or "")
    if shape == "point":
        try:
            x = int(item["x"] if "x" in item else item["x0"])
            y = int(item["y"] if "y" in item else item["y0"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"name": name, "shape": "point", "region": region, "x": x, "y": y}
    try:
        x0 = int(item["x0"])
        y0 = int(item["y0"])
        x1 = int(item["x1"])
        y1 = int(item["y1"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "name": name,
        "shape": "area",
        "region": region,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
    }


def _game_map_id(value: Any) -> int | None:
    """Numeric game map id. A pack folder name is not a game map id."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _patrol_point(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        name = str(item.get("name") or "")
        try:
            x = int(item["x"])
            y = int(item["y"])
        except (KeyError, TypeError, ValueError):
            return None
        point: dict[str, Any] = {"x": x, "y": y, "name": name}
        # Optional dungeon fields. Absent keys stay absent so an old
        # {x, y, name} point is unchanged. Dwell stays on the point;
        # farm_stays_s remains the field-map stay table.
        if "stay_s" in item:
            point["stay_s"] = clamp_farm_stay_s(item.get("stay_s"))
        if "game_map_id" in item:
            game_id = _game_map_id(item.get("game_map_id"))
            if game_id is not None:
                point["game_map_id"] = game_id
        pack_id = item.get("pack_id")
        if isinstance(pack_id, str) and pack_id.strip():
            point["pack_id"] = pack_id.strip()
        return point
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        try:
            x = int(item[0])
            y = int(item[1])
        except (TypeError, ValueError):
            return None
        name = str(item[2]) if len(item) >= 3 else ""
        return {"x": x, "y": y, "name": name}
    return None


def _is_stationary_patrol_item(item: dict[str, Any]) -> bool:
    """Split one legacy flat ``patrol`` item. A stored plan uses ``type`` instead.

    An explicit ``type`` or ``kind`` wins. ``stay_s`` is only the fallback for
    a point written by the earlier point-only editor, which had no type field.
    ``{x, y, name}`` stays a patrol waypoint.
    """
    kind = str(item.get("type") or item.get("kind") or "").strip().lower()
    if kind == "point":
        return True
    if kind in ("patrol", "waypoint", "route"):
        return False
    return "stay_s" in item


def _normalize_dungeon_plan(raw: Any) -> list[dict[str, Any]] | None:
    """Validate ``dungeon_plan``. ``None`` means the key stays absent.

    Future dungeon hunting reads this plan and leaves today's leader schedule
    alone. ``duration_minutes`` on the row is still the whole dungeon visit.
    A patrol entry's ``duration_s`` is how long that route runs before
    stationary points. A point's ``stay_s`` is that point's dwell. The leader
    schedule does not read either value yet.

    The row's ``patrol`` list stays the first route's waypoints in the legacy
    ``{x, y, name}`` shape so the current schedule still walks that one route.
    """
    if not isinstance(raw, list) or not raw:
        return None
    plan: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower()
        entry_id = str(item.get("id") or "").strip()
        pack_id = item.get("pack_id")
        game_id = _game_map_id(item.get("game_map_id")) if "game_map_id" in item else None
        if kind == "patrol":
            waypoints: list[dict[str, Any]] = []
            for raw_point in item.get("waypoints") or []:
                point = _patrol_point(raw_point)
                if point is None:
                    continue
                waypoints.append(
                    {"x": point["x"], "y": point["y"], "name": point["name"]}
                )
            route: dict[str, Any] = {"type": "patrol", "waypoints": waypoints}
            if entry_id:
                route["id"] = entry_id
            if "duration_s" in item:
                route["duration_s"] = clamp_farm_stay_s(item.get("duration_s"))
            if isinstance(pack_id, str) and pack_id.strip():
                route["pack_id"] = pack_id.strip()
            if game_id is not None:
                route["game_map_id"] = game_id
            plan.append(route)
            continue
        if kind != "point":
            continue
        try:
            x = int(item["x"])
            y = int(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        point_entry: dict[str, Any] = {
            "type": "point",
            "x": x,
            "y": y,
            "name": str(item.get("name") or entry_id or ""),
        }
        if entry_id:
            point_entry["id"] = entry_id
        if "stay_s" in item:
            point_entry["stay_s"] = clamp_farm_stay_s(item.get("stay_s"))
        if isinstance(pack_id, str) and pack_id.strip():
            point_entry["pack_id"] = pack_id.strip()
        if game_id is not None:
            point_entry["game_map_id"] = game_id
        plan.append(point_entry)
    return plan or None


def dungeon_plan_from_document(bound: Any) -> list[dict[str, Any]]:
    """Editor view of one dungeon row.

    A stored ``dungeon_plan`` wins. Otherwise the legacy ``patrol`` list is
    one route, except items that already carry a dwell, which are stationary
    points from the earlier point-only save.
    """
    if not isinstance(bound, dict):
        return []
    stored = _normalize_dungeon_plan(bound.get("dungeon_plan"))
    if stored:
        return stored
    waypoints: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    for raw in bound.get("patrol") or []:
        point = _patrol_point(raw)
        if point is None or not isinstance(raw, dict):
            if point is not None:
                waypoints.append(
                    {"x": point["x"], "y": point["y"], "name": point["name"]}
                )
            continue
        if _is_stationary_patrol_item(raw):
            entry: dict[str, Any] = {
                "type": "point",
                "x": point["x"],
                "y": point["y"],
                "name": point["name"],
            }
            if "stay_s" in point:
                entry["stay_s"] = point["stay_s"]
            if "game_map_id" in point:
                entry["game_map_id"] = point["game_map_id"]
            if "pack_id" in point:
                entry["pack_id"] = point["pack_id"]
            points.append(entry)
        else:
            waypoints.append({"x": point["x"], "y": point["y"], "name": point["name"]})
    plan: list[dict[str, Any]] = []
    if waypoints:
        plan.append({"type": "patrol", "id": "patrol_1", "waypoints": waypoints})
    for index, entry in enumerate(points, start=1):
        entry.setdefault("id", f"point_{index}")
        plan.append(entry)
    return plan


def legacy_patrol_waypoints(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First route only, legacy shape. Later routes stay in ``dungeon_plan``."""
    for entry in plan:
        if entry.get("type") != "patrol":
            continue
        return [
            {"x": int(point["x"]), "y": int(point["y"]), "name": str(point.get("name") or "")}
            for point in entry.get("waypoints") or []
            if isinstance(point, dict)
        ]
    return []


def dungeon_plan_extends_legacy(plan: list[dict[str, Any]]) -> bool:
    """True when the legacy ``patrol`` list cannot represent this plan alone."""
    routes = [entry for entry in plan if entry.get("type") == "patrol"]
    points = [entry for entry in plan if entry.get("type") == "point"]
    if not routes and not points:
        return False
    if points or len(routes) != 1:
        return True
    return "duration_s" in routes[0]


def normalize_party_routine(raw: Any) -> list[dict[str, Any]]:
    """Ordered party battle/break rows, including their own coordinate copy."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        map_id = str(item.get("map_id") or "").strip()
        if not map_id:
            continue
        kind = str(item.get("kind") or "battle").strip().lower()
        if kind not in ("battle", "break"):
            kind = "battle"
        try:
            minutes = int(item.get("duration_minutes", 60))
        except (TypeError, ValueError):
            minutes = 60
        minutes = max(1, min(MAX_ROUTINE_MINUTES, minutes))
        entry_id = str(item.get("id") or "").strip() or uuid.uuid4().hex
        if entry_id in seen:
            entry_id = uuid.uuid4().hex
        seen.add(entry_id)
        farms: list[str] = []
        farms_raw = item.get("selected_farms") or []
        if isinstance(farms_raw, list):
            for name in farms_raw:
                text = str(name).strip()
                if text and text not in farms:
                    farms.append(text)
        stays = normalize_farm_stays_s(item.get("farm_stays_s"))
        areas: list[dict[str, Any]] = []
        seen_areas: set[tuple] = set()
        for raw_area in item.get("areas") or []:
            area = _area(raw_area)
            if area is None:
                continue
            if area["shape"] == "point":
                key = ("point", area["name"], area["x"], area["y"])
            else:
                key = (
                    "area",
                    area["name"],
                    area["x0"],
                    area["y0"],
                    area["x1"],
                    area["y1"],
                )
            if key in seen_areas:
                continue
            seen_areas.add(key)
            areas.append(area)
        patrol: list[dict[str, Any]] = []
        for raw_point in item.get("patrol") or []:
            point = _patrol_point(raw_point)
            if point is not None:
                patrol.append(point)
        row = {
            "id": entry_id,
            "map_id": map_id,
            "kind": kind,
            "duration_minutes": minutes,
            "selected_farms": farms,
            "farm_stays_s": {name: stays[name] for name in farms if name in stays},
            "coords_saved": bool(item.get("coords_saved")),
            "areas": areas,
            "patrol": patrol,
        }
        # Absent on old rows. Present only when a plan was already stored.
        if "dungeon_plan" in item:
            plan = _normalize_dungeon_plan(item.get("dungeon_plan"))
            if plan:
                row["dungeon_plan"] = plan
        out.append(row)
    return out


def take_party_routine(
    settings: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Remove ``party.routine`` from a settings copy and return it normalized.

    Callers pass a copy. The solo ``move.routine`` / ``routine.json`` path is
    left untouched.
    """
    party = settings.get("party")
    if not isinstance(party, dict):
        return settings, []
    routine = normalize_party_routine(party.pop("routine", None))
    return settings, routine
