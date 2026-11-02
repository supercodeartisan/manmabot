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


def _patrol_point(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        name = str(item.get("name") or "")
        try:
            x = int(item["x"])
            y = int(item["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"x": x, "y": y, "name": name}
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        try:
            x = int(item[0])
            y = int(item[1])
        except (TypeError, ValueError):
            return None
        name = str(item[2]) if len(item) >= 3 else ""
        return {"x": x, "y": y, "name": name}
    return None


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
        out.append(
            {
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
        )
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
