"""Farm-area hunt order and stay times for general maps."""
from __future__ import annotations

import uuid
from typing import Any

MAX_ROUTINE_MINUTES = 10080

MIN_FARM_STAY_S = 60.0
MAX_FARM_STAY_S = 24 * 3600.0
DEFAULT_FARM_STAY_S = 600.0
MIN_FARM_STAY_MIN = 1
MAX_FARM_STAY_MIN = 1440


def clamp_farm_stay_s(value: Any, default: float = DEFAULT_FARM_STAY_S) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = float(default)
    return max(MIN_FARM_STAY_S, min(MAX_FARM_STAY_S, seconds))


def stay_minutes_from_s(seconds: float) -> int:
    return max(
        MIN_FARM_STAY_MIN,
        min(MAX_FARM_STAY_MIN, int(round(float(seconds) / 60.0))),
    )


def stay_s_from_minutes(minutes: Any, default_s: float = DEFAULT_FARM_STAY_S) -> float:
    try:
        mins = int(minutes)
    except (TypeError, ValueError):
        return clamp_farm_stay_s(default_s)
    return clamp_farm_stay_s(mins * 60.0)


def normalize_farm_stays_s(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            continue
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        out[name] = clamp_farm_stay_s(seconds)
    return out


def stay_seconds_for(
    name: str,
    stays: dict[str, float] | None,
    default_s: float,
) -> float:
    stays = stays or {}
    if name in stays:
        return clamp_farm_stay_s(stays[name], default_s)
    return clamp_farm_stay_s(default_s)


def normalize_routine(raw: Any) -> list[dict[str, Any]]:
    """Ordered battle/break maps saved with a schedule."""
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
        raw_minutes = item.get("duration_minutes", 60)
        try:
            minutes = int(raw_minutes)
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
        out.append(
            {
                "id": entry_id,
                "map_id": map_id,
                "kind": kind,
                "duration_minutes": minutes,
                "selected_farms": farms,
                "farm_stays_s": {name: stays[name] for name in farms if name in stays},
            }
        )
    return out


def routine_is_break_only(raw: Any) -> bool:
    """True when the routine has rows and every row is break (no battle).

    Empty routine is False — callers fall back to a single hunt map.
    """
    rows = normalize_routine(raw)
    if not rows:
        return False
    return all(str(row.get("kind") or "") == "break" for row in rows)


def farm_rects_in_selection_order(
    areas: list[Any],
    selected: list[str],
) -> list[dict[str, Any]]:
    """Return YAML area dicts in the user's selected order (skip unknown names)."""
    by_name: dict[str, dict[str, Any]] = {}
    for area in areas:
        if isinstance(area, dict) and area.get("name"):
            by_name[str(area["name"])] = area
    return [by_name[name] for name in selected if name in by_name]
