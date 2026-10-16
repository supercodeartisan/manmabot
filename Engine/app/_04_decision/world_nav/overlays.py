"""Injected map overlay data for world_nav (no session/settings I/O here).

Session/Start builds ``SCRATCH_MAP_OVERLAYS`` via ``set_map_overlays``.
Decision only reads dicts: farm areas, rest areas, patrol tiles, dungeon flag.
"""
from __future__ import annotations

from typing import Any

SCRATCH_MAP_OVERLAYS = "map_overlays"


def set_map_overlays(blackboard: Any, overlays: dict[str, Any] | None) -> None:
    """Install per-pack overlay snapshots (session ownership)."""
    blackboard.scratch[SCRATCH_MAP_OVERLAYS] = dict(overlays or {})


def get_map_overlay(blackboard: Any, pack_id: str) -> dict[str, Any]:
    mid = str(pack_id or "").strip()
    if not mid:
        return {}
    table = blackboard.scratch.get(SCRATCH_MAP_OVERLAYS)
    if not isinstance(table, dict):
        return {}
    row = table.get(mid)
    return dict(row) if isinstance(row, dict) else {}


def is_dungeon_pack(blackboard: Any, pack_id: str) -> bool:
    ov = get_map_overlay(blackboard, pack_id)
    if "dungeon" in ov:
        return bool(ov.get("dungeon"))
    return "dungeon" in str(pack_id or "").lower()


def _rects_in_selection_order(
    areas: Any,
    selected: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    """Return area dicts in the operator's selection order."""
    by_name: dict[str, dict[str, Any]] = {}
    for area in areas or []:
        if not isinstance(area, dict):
            continue
        name = str(area.get("name") or "").strip()
        if name and name not in by_name:
            by_name[name] = area
    out: list[dict[str, Any]] = []
    for name in selected or []:
        text = str(name or "").strip()
        if not text:
            continue
        area = by_name.get(text)
        if area is not None:
            out.append(area)
    return out


def farm_rects_selected(
    blackboard: Any,
    pack_id: str,
    selected: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    """Return injected farm area dicts in selection order (pure filter)."""
    areas = get_map_overlay(blackboard, pack_id).get("areas") or []
    return _rects_in_selection_order(areas, selected)


def safe_rects_selected(
    blackboard: Any,
    pack_id: str,
    selected: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    """Return injected rest-area dicts in selection order (pure filter)."""
    areas = get_map_overlay(blackboard, pack_id).get("safe_areas") or []
    return _rects_in_selection_order(areas, selected)


def patrol_entries(
    blackboard: Any, pack_id: str
) -> list[tuple[int, int, str]]:
    raw = get_map_overlay(blackboard, pack_id).get("patrol") or []
    out: list[tuple[int, int, str]] = []
    for item in raw:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                nx, ny = int(item[0]), int(item[1])
                label = str(item[2]) if len(item) >= 3 else ""
                out.append((nx, ny, label))
        except (TypeError, ValueError):
            continue
    return out


__all__ = [
    "SCRATCH_MAP_OVERLAYS",
    "set_map_overlays",
    "get_map_overlay",
    "is_dungeon_pack",
    "farm_rects_selected",
    "safe_rects_selected",
    "patrol_entries",
]
