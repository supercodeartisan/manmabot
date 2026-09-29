"""Converts vision objects into the resolution-independent World Model format.

All positions, sizes and velocities are normalized by the screen size so the
World Model and Decision modules never depend on the capture resolution:

    ratio = pixel_value / image_size

Pipeline position:
    Screen -> YOLO Detector -> ByteTrack Tracker -> Classifier -> World Model

Input:  List[TrackObject] and/or YOLO-only detection dicts
        + image_width (int) + image_height (int).
Output: List of normalized dicts. The four classification fields match the
        **v1 contract** that ``_03_world`` already reads. Vision owns this
        mapping; World does not need to know about v2 species names.

        When the classifier predicts a v2 species (not a v1 level band), two
        optional fields are also attached for dumps / debug / future World use:
            species_name            e.g. monster_개과_15
            species_confidence      fine-head confidence (detail_confidence)

v1 contract (do not change these key names or value spellings):
    classification                      coarse: monster | npc | player | item | background
    classification_confidence           float
    detail_classification               monster_1-10 | monster_11-20 | monster_21-30
                                        | monster_31-40 | monster_41-
                                        | item | npc | player | background | win
    detail_classification_confidence    float

A v2 checkpoint predicts a species (``monster_네루가 오크``) and a 5-way main
class. This module folds that back into a v1 level band before the list leaves
Vision, using ``monster_level`` on the classification dict or
``scripts/classify_model/label_tables.json``. Overlay / test_vision still see
the raw species name on the TrackObject itself.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

DEFAULT_WORLD_OUTPUT_DIR = (
    Path(__file__).resolve().parent / "output" / "world_state"
)

# Durable dumps for the World owner. They load ``objects`` and never need GPU.
HANDOFF_SCHEMA = "manmabot.vision_handoff.v1"
DEFAULT_HANDOFF_ROOT = Path(r"D:\Works\manma\results\vision_for_world")

_TABLES_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "classify_model"
    / "label_tables.json"
)

# Coarse names ``_03_world.constants.coarse_to_object_type`` already understands.
_MAIN_TO_V1 = {
    "background": "background",
    "bg": "background",
    "item": "item",
    "grounditem": "item",
    "monster": "monster",
    "npc": "npc",
    "player": "player",
    "window": "window",
    "win": "window",
}

_NON_MONSTER_DETAIL = {
    "item": "item",
    "npc": "npc",
    "player": "player",
    "background": "background",
    "window": "win",
}

# Same bands ``monster_level_from_detail`` parses in _03_world.
_LEVEL_BANDS = (
    (10, "monster_1-10"),
    (20, "monster_11-20"),
    (30, "monster_21-30"),
    (40, "monster_31-40"),
)

_level_lookup: Optional[Dict[str, int]] = None


def monster_band_from_level(level: int) -> str:
    """Map an exact species level onto the v1 detail band World already parses."""
    for cap, name in _LEVEL_BANDS:
        if int(level) <= cap:
            return name
    return "monster_41-"


def _looks_like_v1_band(name: Optional[str]) -> bool:
    if not name:
        return False
    text = name.strip().lower()
    if not text.startswith("monster_"):
        return False
    return "-" in text[len("monster_"):]


def _normalize_main(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _MAIN_TO_V1.get(name.strip().lower(), name.strip().lower())


def _strip_level(name: str) -> str:
    """``'monster_해골_10'`` -> ``'monster_해골'``; unchanged when there is none."""
    parts = name.split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        return "_".join(parts[:-1])
    return name


def _load_level_lookup() -> Dict[str, int]:
    global _level_lookup
    if _level_lookup is not None:
        return _level_lookup
    lookup: Dict[str, int] = {}
    if _TABLES_PATH.is_file():
        with open(_TABLES_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        lookup.update(data.get("species_level") or {})
        lookup.update(data.get("level_override") or {})
        for group in data.get("groups") or []:
            if group.get("mode") != "train":
                continue
            members = group.get("members") or []
            member_levels = [lookup[name] for name in members if name in lookup]
            if member_levels:
                lookup[group["name"]] = int(
                    round(sum(member_levels) / len(member_levels))
                )
    _level_lookup = lookup
    return lookup


def _level_from_classification(classification: Dict, detail: Optional[str]) -> Optional[int]:
    raw = classification.get("monster_level")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    if not detail:
        return None

    # A species name carries its level (``monster_해골_10``), but a checkpoint
    # or a table written before that used the bare name, and the two are mixed
    # freely across editions. Try both spellings before giving up: an unknown
    # level is read as "strong", which silently stops the bot farming.
    lookup = _load_level_lookup()
    names = (detail.strip(), _strip_level(detail.strip()))
    for name in names:
        if name in lookup:
            return lookup[name]
    lowered = {key.lower(): value for key, value in lookup.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]

    # The trailing number of a species name is its level by construction, so
    # it still answers the question when no table knows the species at all.
    tail = detail.strip().rsplit("_", 1)
    if len(tail) == 2 and tail[1].isdigit():
        return int(tail[1])
    return None


def to_v1_world_fields(classification: Optional[Dict]) -> Dict:
    """Four fields World already consumes. Raw v2 names stay on the track."""
    classification = classification or {}
    coarse = _normalize_main(classification.get("class_name"))
    detail = classification.get("detail_class_name")
    main_conf = classification.get("confidence")
    detail_conf = classification.get("detail_confidence")

    if _looks_like_v1_band(detail):
        detail_out = detail.strip()
    elif coarse == "monster":
        level = _level_from_classification(classification, detail)
        # Unknown monster level → open high band, never a low band.
        # World treats a high band as strong, so the bot will not farm it.
        detail_out = monster_band_from_level(level) if level is not None else "monster_41-"
    else:
        detail_out = _NON_MONSTER_DETAIL.get(coarse or "", detail)

    fields = {
        "classification": coarse,
        "classification_confidence": main_conf,
        "detail_classification": detail_out,
        "detail_classification_confidence": detail_conf,
    }
    fields.update(_species_fields(classification))
    return fields


def format_species_name(classification: Optional[Dict]) -> Optional[str]:
    """Build a display species id such as ``monster_개과_15`` from v2 output."""
    classification = classification or {}
    detail = (classification.get("detail_class_name") or "").strip()
    if not detail or _looks_like_v1_band(detail):
        return None

    coarse = _normalize_main(classification.get("class_name"))
    if coarse != "monster":
        return detail

    level = _level_from_classification(classification, detail)
    if level is None:
        return detail
    suffix = f"_{level}"
    if detail.endswith(suffix):
        return detail
    return f"{detail}{suffix}"


def _species_fields(classification: Optional[Dict]) -> Dict:
    """Optional v2 species identity alongside the v1 band fields."""
    classification = classification or {}
    name = format_species_name(classification)
    if not name:
        return {}

    fields: Dict[str, Union[str, float]] = {"species_name": name}
    raw_conf = classification.get("detail_confidence")
    if raw_conf is not None:
        try:
            fields["species_confidence"] = float(raw_conf)
        except (TypeError, ValueError):
            pass
    return fields


def _classification_fields(classification: Optional[Dict]) -> Dict:
    return to_v1_world_fields(classification)


def is_background_class(name: Optional[str]) -> bool:
    """ResNet coarse name for empty ground / false-positive boxes."""
    return _normalize_main(name) in ("background",)


def is_background_classification(classification: Optional[Dict]) -> bool:
    return is_background_class((classification or {}).get("class_name"))


def build_world_entry_from_track(
    track, image_width: int, image_height: int
) -> dict:
    """Convert one TrackObject into a normalized world-state record."""
    return {
        "track_id": track.track_id,
        "label": track.label,
        "class_id": int(track.class_id),
        "yolo_conf": track.confidence,
        "position_x": track.center[0] / image_width,
        "position_y": track.center[1] / image_height,
        "velocity_x": track.velocity[0] / image_width,
        "velocity_y": track.velocity[1] / image_height,
        "width_ratio": track.width / image_width,
        "height_ratio": track.height / image_height,
        **_classification_fields(track.classification),
        "occluded": bool(getattr(track, "occluded", False)),
        "frames_lost": int(getattr(track, "frames_lost", 0)),
    }


def build_world_entry_from_detection(
    det: Dict, image_width: int, image_height: int
) -> dict:
    """Convert one YOLO-only detection (no track_id yet) into world state."""
    center = det["center"]
    return {
        "track_id": None,
        "label": det["label"],
        "class_id": int(det["class_id"]),
        "yolo_conf": det["confidence"],
        "position_x": center["x"] / image_width,
        "position_y": center["y"] / image_height,
        "velocity_x": 0.0,
        "velocity_y": 0.0,
        "width_ratio": det["width"] / image_width,
        "height_ratio": det["height"] / image_height,
        **_classification_fields(det.get("classification")),
        "occluded": False,
        "frames_lost": 0,
    }


def build_world_model(tracks, image_width: int, image_height: int) -> List[dict]:
    """Convert tracked objects into the normalized World Model format."""
    return [
        build_world_entry_from_track(track, image_width, image_height)
        for track in tracks
        if not is_background_classification(getattr(track, "classification", None))
    ]


def save_world_state_json(
    world: List[dict],
    output_dir: Union[str, Path],
    filename: str = "world_state.json",
) -> Path:
    """Write one world-state list to a JSON file (creates folders as needed)."""
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    out_path = folder / filename
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(world, f, ensure_ascii=False, indent=2)
    return out_path


def make_handoff_payload(
    objects: List[dict],
    *,
    source_image: Optional[Union[str, Path]] = None,
    frame_index: Optional[int] = None,
    image_width: Optional[int] = None,
    image_height: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> dict:
    """Envelope around the v1 object list so a dump is self-describing.

    ``objects`` is exactly what ``_03_world.converter.vision_to_perception``
    already accepts. Extra keys are for Vision bookkeeping; World should
    ignore everything except ``objects``.
    """
    payload = {
        "schema": HANDOFF_SCHEMA,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_image": str(source_image) if source_image else None,
        "frame_index": frame_index,
        "image_width": image_width,
        "image_height": image_height,
        "object_count": len(objects),
        "notes": (
            "objects = VisionSystem.create_world_state() after the v1 label "
            "mapping. Pass that list to vision_to_perception / "
            "GameState.update_from_vision. Background boxes are already omitted. "
            "Optional species_name / species_confidence carry the raw v2 fine "
            "prediction (e.g. monster_개과_15); World may ignore them."
        ),
        "objects": objects,
    }
    if extra:
        payload["vision_extra"] = extra
    return payload


def save_handoff_json(
    objects: List[dict],
    output_dir: Union[str, Path],
    filename: str,
    **payload_kwargs,
) -> Path:
    """Write one handoff envelope. World reads payload['objects']."""
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            make_handoff_payload(objects, **payload_kwargs),
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return path


def load_handoff_objects(path: Union[str, Path]) -> List[dict]:
    """Read ``objects`` from an envelope, or a legacy bare list."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("objects"), list):
        return data["objects"]
    raise ValueError(f"Not a vision handoff file: {path}")
