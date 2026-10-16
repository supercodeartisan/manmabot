"""Build world-nav overlay snapshots for decision (session I/O boundary)."""
from __future__ import annotations

from typing import Any


def load_farm_area_dicts(map_id: str) -> list[dict[str, Any]]:
    """All farm area dicts for a pack (userdata overlay or engine yaml)."""
    return _load_named_area_dicts(map_id, kind="farm")


def load_safe_area_dicts(map_id: str) -> list[dict[str, Any]]:
    """All rest-area dicts for a pack (userdata overlay or engine yaml)."""
    return _load_named_area_dicts(map_id, kind="safe")


def _load_named_area_dicts(map_id: str, *, kind: str) -> list[dict[str, Any]]:
    import yaml

    from session.probes import farms_yaml_path, safe_yaml_path

    path = safe_yaml_path(map_id) if kind == "safe" else farms_yaml_path(map_id)
    if path is None or not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if kind == "safe":
        areas = doc.get("areas") or doc.get("safe_areas") or doc.get("farm_areas") or []
    else:
        areas = doc.get("areas") or doc.get("farm_areas") or []
    return [a for a in areas if isinstance(a, dict) and a.get("name")]


def build_map_overlays(pack_ids: list[str] | tuple[str, ...] | None) -> dict[str, Any]:
    """``{pack_id: {dungeon, areas, safe_areas, patrol}}`` for world_nav decide reads."""
    from session.probes import list_patrol_entries, map_style_is_dungeon

    out: dict[str, Any] = {}
    for raw in pack_ids or []:
        pack_id = str(raw or "").strip()
        if not pack_id or pack_id in out:
            continue
        out[pack_id] = {
            "dungeon": bool(map_style_is_dungeon(pack_id, None)),
            "areas": load_farm_area_dicts(pack_id),
            "safe_areas": load_safe_area_dicts(pack_id),
            "patrol": [
                (int(x), int(y), str(label or ""))
                for x, y, label in list_patrol_entries(pack_id)
            ],
        }
    return out


def pack_ids_for_routine(
    routine_rows: list[dict[str, Any]] | None,
    *,
    fallback_map: str = "",
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for row in routine_rows or []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("map_id") or "").strip()
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    fb = str(fallback_map or "").strip()
    if fb and fb not in seen:
        ids.append(fb)
    return ids


def install_world_nav_overlays(
    blackboard: Any,
    *,
    routine_rows: list[dict[str, Any]] | None,
    fallback_map: str = "",
) -> dict[str, Any]:
    """Normalize ownership: session builds overlays, decision only reads them."""
    from app._04_decision.world_nav.overlays import set_map_overlays

    overlays = build_map_overlays(
        pack_ids_for_routine(routine_rows, fallback_map=fallback_map)
    )
    set_map_overlays(blackboard, overlays)
    return overlays


__all__ = [
    "load_farm_area_dicts",
    "load_safe_area_dicts",
    "build_map_overlays",
    "pack_ids_for_routine",
    "install_world_nav_overlays",
]
