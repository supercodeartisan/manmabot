"""Nested settings sections shared by schedules and trial.

``routine`` is a sibling of settings (not under ``move.routine`` on disk).
UI/compat layers may still embed routine inside ``move`` via merge helpers.
"""
from __future__ import annotations

import copy
from typing import Any

from settings.farm_schedule import normalize_routine
from settings.spell_defaults import spell_slot_bindings

TOP_SECTIONS = ("move", "hunt", "recovery", "magic", "equipment", "other")


def empty_settings() -> dict[str, dict[str, Any]]:
    return {section: {} for section in TOP_SECTIONS}


def normalize_settings(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize section dict; strip embedded routine from move."""
    src = raw if isinstance(raw, dict) else {}
    out = empty_settings()
    for section in TOP_SECTIONS:
        block = src.get(section)
        out[section] = dict(block) if isinstance(block, dict) else {}
    move = out["move"]
    move.pop("routine", None)
    hunt = out["hunt"]
    recovery = out["recovery"]
    for key in ("random_teleport_enabled", "random_teleport_hp_below"):
        if key in hunt and key not in recovery:
            recovery[key] = hunt.pop(key)
    equipment = out["equipment"]
    old_arrow_type = str(equipment.pop("arrow_type", "")).lower()
    if old_arrow_type and "buy_normal_arrows" not in equipment:
        equipment["buy_normal_arrows"] = old_arrow_type == "normal"
    if old_arrow_type and "buy_silver_arrows" not in equipment:
        equipment["buy_silver_arrows"] = old_arrow_type == "silver"
    magic = out["magic"]
    if "spell_slots" in magic:
        magic["spell_slots"] = spell_slot_bindings(magic.get("spell_slots"))
    return out


def split_settings_routine(
    settings: Any,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return (settings_without_routine, routine_rows)."""
    src = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    move = src.get("move") if isinstance(src.get("move"), dict) else {}
    routine = normalize_routine(move.get("routine") if isinstance(move, dict) else None)
    normalized = normalize_settings(src)
    return normalized, routine


def merge_settings_routine(
    settings: Any,
    routine: Any,
) -> dict[str, dict[str, Any]]:
    """Embed routine into move for UI / ScheduleTask compat."""
    out = normalize_settings(settings)
    out["move"]["routine"] = normalize_routine(routine)
    return out


def read_json_object(path: Any) -> dict[str, Any] | None:
    import json
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def read_json_list(path: Any) -> list[Any] | None:
    import json
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, list) else None
