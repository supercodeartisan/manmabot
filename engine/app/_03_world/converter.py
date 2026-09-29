"""Vision to perception conversion."""
from __future__ import annotations

from typing import Any

from .constants import object_type_from_classifiers
from .objects import PerceptionObject, Position, Velocity, Identity, Size


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce vision confidences; treat missing/None as ``default``."""
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


def vision_to_perception(vision_output: list[dict[str, Any]]) -> list[PerceptionObject]:
    """Convert VisionSystem output to PerceptionObject list.

    ObjectType is derived from ResNet coarse + species (preferred) or detail
    band. YOLO ``label`` is kept for display but never decides the type.

    Rows with ``track_id is None`` (YOLO-only stubs) or ResNet ``background``
    are skipped — those stay vision-debug only.
    """
    objects = []
    for v in vision_output:
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
        objects.append(PerceptionObject(
            track_id=int(track_id),
            object_type=obj_type,
            position=Position(x=v["position_x"], y=v["position_y"]),
            velocity=Velocity(x=v["velocity_x"], y=v["velocity_y"]),
            identity=Identity(
                name=str(species_name or memory_name or coarse or ""),
                confidence=coarse_conf,
            ),
            size=Size(width=v["width_ratio"], height=v["height_ratio"]),
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
        ))
    return objects
