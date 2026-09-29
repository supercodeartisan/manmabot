"""Build VisionSystem options from ``config['vision']``."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app._02_vision.region_models import resolve_region_models


def vision_system_kwargs(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Kwargs for ``VisionSystem(...)`` from the vision.system + detector blocks."""
    section = (config or {}).get("vision") or {}
    system = dict(section.get("system") or {})
    detector = section.get("detector") or {}

    if "conf" in detector and "detector_conf" not in system:
        system["detector_conf"] = float(detector["conf"])
    if "iou" in detector and "detector_iou" not in system:
        system["detector_iou"] = float(detector["iou"])
    if "imgsz" in detector and "detector_imgsz" not in system:
        system["detector_imgsz"] = int(detector["imgsz"])

    # Drop unknown keys VisionSystem may not accept — keep only known.
    from app._02_vision.vision_system import VisionSystem
    import inspect

    # Pull classifier edition/path into kwargs if present in nested blocks.
    clf = section.get("classifier") or {}
    if clf.get("edition") and "classifier_edition" not in system:
        system["classifier_edition"] = clf["edition"]
    if clf.get("model_path") and "classifier_model_path" not in system:
        system["classifier_model_path"] = clf["model_path"]
    det = section.get("detector") or {}
    if det.get("model_path") and "detector_model_path" not in system:
        system["detector_model_path"] = det["model_path"]

    sig = inspect.signature(VisionSystem.__init__)
    allowed = {name for name in sig.parameters if name != "self"}
    return {k: v for k, v in system.items() if k in allowed}


def resolve_active_vision_region(
    config: Optional[dict[str, Any]] = None,
    *,
    farm_region: str = "",
) -> str:
    """Farm ``region:`` wins; otherwise the active map pack's ``default_region``."""
    key = str(farm_region or "").strip()
    if key:
        return key
    nav = (config or {}).get("navigation") or {}
    map_id = str(nav.get("active_map") or "").strip()
    if not map_id:
        return ""
    try:
        from app._03_world.map_pack import load_map_pack, resolve_maps_dir

        maps_dir = resolve_maps_dir(config)
        if maps_dir is None:
            return ""
        pack = load_map_pack(maps_dir, map_id)
        return str(pack.default_region or "").strip()
    except Exception:
        return ""


def apply_region_model_paths(
    kwargs: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
    *,
    region: str = "",
) -> dict[str, Any]:
    """Stamp detector/classifier paths for ``region`` onto VisionSystem kwargs."""
    models = resolve_region_models(region, config)
    if models.detector_path:
        kwargs["detector_model_path"] = models.detector_path
    if models.classifier_path:
        kwargs["classifier_model_path"] = models.classifier_path
    if models.classifier_edition and "classifier_edition" not in kwargs:
        kwargs["classifier_edition"] = models.classifier_edition
    return kwargs


def resolve_detector_model_path(
    config: Optional[dict[str, Any]] = None,
    *,
    region: str = "",
) -> Optional[str]:
    if region:
        return resolve_region_models(region, config).detector_path
    section = (config or {}).get("vision") or {}
    detector = section.get("detector") or {}
    path = detector.get("model_path")
    if not path:
        return None
    return str(Path(path))


def resolve_classifier_edition(config: Optional[dict[str, Any]] = None) -> Optional[str]:
    section = (config or {}).get("vision") or {}
    clf = section.get("classifier") or {}
    edition = clf.get("edition")
    return str(edition) if edition else None


def resolve_classifier_model_path(
    config: Optional[dict[str, Any]] = None,
    *,
    region: str = "",
) -> Optional[str]:
    if region:
        return resolve_region_models(region, config).classifier_path
    section = (config or {}).get("vision") or {}
    clf = section.get("classifier") or {}
    path = clf.get("model_path")
    if not path:
        return None
    return str(path)


def sync_vision_region(
    vision: Any,
    config: Optional[dict[str, Any]] = None,
    *,
    farm_index: int = 0,
    region_override: str = "",
) -> bool:
    """Switch YOLO/classifier to the active farm's region (or map default).

    ``region_override`` (talking-scroll geography) wins over farm region.
    """
    key = str(region_override or "").strip()
    if key:
        region = key
    else:
        farm_region = ""
        try:
            from app._04_decision.nav_config import get_active_farm

            farm = get_active_farm(int(farm_index))
            if farm is not None:
                farm_region = str(farm.region or "")
        except Exception:
            pass
        region = resolve_active_vision_region(config, farm_region=farm_region)
    setter = getattr(vision, "set_region", None)
    if setter is None:
        return False
    return bool(setter(region, config))


__all__ = [
    "vision_system_kwargs",
    "resolve_active_vision_region",
    "apply_region_model_paths",
    "resolve_detector_model_path",
    "resolve_classifier_edition",
    "resolve_classifier_model_path",
    "sync_vision_region",
]
