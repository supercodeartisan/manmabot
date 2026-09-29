"""Farm-area hunt order and stay times for general maps."""
from __future__ import annotations

from typing import Any

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
