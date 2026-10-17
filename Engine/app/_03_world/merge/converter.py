"""Handoff dicts (memory or vision) → PerceptionObject list."""
from __future__ import annotations

from typing import Any

from app._02_state.objects import PerceptionObject, Position, Velocity, Identity, Size
from app._03_world.constants import object_type_from_classifiers


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce confidences / ratios; treat missing/None as ``default``."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_cell(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_loot_qty(value: Any) -> int | None:
    if value is None or value == "" or value == -1:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_loot_contrib(value: Any) -> int | None:
    if value is None or value == "" or value == -1:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_loot_own(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    return text


def _opt_guid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def handoff_to_perception(handoff_rows: list[dict[str, Any]]) -> list[PerceptionObject]:
    """Convert perception handoff dicts to PerceptionObject list.

    Rows come from print_state (memory handoff). ObjectType is derived from
    coarse + species (preferred) or detail band. ``label`` is display-only.

    Rows with ``track_id is None`` or coarse ``background`` are skipped.
    Missing velocity/size keys default to 0 (memory stubs need not fill them).
    """
    objects = []
    for v in handoff_rows:
        track_id = v.get("track_id")
        if track_id is None:
            continue
        coarse = v.get("classification")
        if isinstance(coarse, str) and coarse.strip().lower() in ("background", "bg"):
            continue
        coarse_conf = _as_float(v.get("classification_confidence"), 0.0)
        detail_conf = _as_float(v.get("detail_classification_confidence"), 0.0)
        species_name = v.get("species_name")
        if isinstance(species_name, str):
            species_name = species_name.strip() or None
        else:
            species_name = None
        memory_name = v.get("memory_name")
        if isinstance(memory_name, str):
            memory_name = memory_name.strip() or None
        else:
            memory_name = None
        if species_name is None and memory_name is not None:
            species_name = memory_name
        species_conf_raw = v.get("species_confidence")
        species_conf = (
            _as_float(species_conf_raw, detail_conf)
            if species_conf_raw is not None
            else None
        )
        obj_type = object_type_from_classifiers(
            coarse,
            v.get("detail_classification"),
            coarse_conf,
            detail_conf,
            species_name=species_name,
            species_conf=species_conf,
        )
        memory_class = None
        if isinstance(coarse, str):
            memory_class = coarse.strip().lower() or None
        objects.append(PerceptionObject(
            track_id=int(track_id),
            object_type=obj_type,
            position=Position(
                x=_as_float(v.get("position_x"), 0.0),
                y=_as_float(v.get("position_y"), 0.0),
            ),
            velocity=Velocity(
                x=_as_float(v.get("velocity_x"), 0.0),
                y=_as_float(v.get("velocity_y"), 0.0),
            ),
            identity=Identity(
                name=str(species_name or memory_name or coarse or ""),
                confidence=coarse_conf,
            ),
            size=Size(
                width=_as_float(v.get("width_ratio"), 0.0),
                height=_as_float(v.get("height_ratio"), 0.0),
            ),
            label=v.get("label"),
            class_id=v.get("class_id"),
            yolo_conf=_as_float(v.get("yolo_conf"), 0.0),
            detail_classification=v.get("detail_classification"),
            detail_classification_confidence=detail_conf,
            species_name=species_name,
            species_confidence=_as_float(
                species_conf if species_conf is not None else detail_conf, 0.0
            ),
            occluded=bool(v.get("occluded", False)),
            frames_lost=int(v.get("frames_lost") or 0),
            world_cx=_opt_cell(v.get("world_cx")),
            world_cy=_opt_cell(v.get("world_cy")),
            world_rx=_opt_cell(v.get("world_rx")),
            world_ry=_opt_cell(v.get("world_ry")),
            bait=bool(v.get("bait", False)),
            loot_contrib=_opt_loot_contrib(v.get("loot_contrib")),
            loot_qty=_opt_loot_qty(v.get("loot_qty")),
            loot_own=_opt_loot_own(v.get("loot_own")),
            memory_guid=_opt_guid(v.get("memory_guid")),
            memory_class=memory_class,
        ))
    return objects


# Backward-compatible alias (VisionSystem historically owned this name).
vision_to_perception = handoff_to_perception
