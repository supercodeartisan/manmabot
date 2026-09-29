"""Resolve classifier and YOLO weights from an area ``region`` name.

Map pack id (``talking_island``) is geography. Area ``region``
(``talking island``) selects which **vision pack** to use.

Thin layout (default)::

    app/models/regions/<slug>/<slug>.pt         # classifier
    app/models/regions/<slug>/<slug>_yolo.pt    # YOLO detector
    # optional aliases / extras beside them:
    #   yolo.pt
    #   class_names.json
    #   detail_class_names.json

``slug`` = region with spaces → underscores (``talking island`` → ``talking_island``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REGIONS_ROOT = _PROJECT_ROOT / "app" / "models" / "regions"


def region_slug(region: str) -> str:
    """Folder-safe slug: ``\"talking island\"`` → ``talking_island``."""
    return "_".join(str(region).strip().lower().split())


def region_pack_dir(region: str, *, regions_root: Optional[Path] = None) -> Path:
    root = Path(regions_root) if regions_root is not None else _REGIONS_ROOT
    return root / region_slug(region)


def region_classifier_path(
    region: str, *, regions_root: Optional[Path] = None
) -> Path:
    """Convention path: ``regions/<slug>/<slug>.pt``."""
    slug = region_slug(region)
    return region_pack_dir(region, regions_root=regions_root) / f"{slug}.pt"


def region_detector_path(
    region: str, *, regions_root: Optional[Path] = None
) -> Path:
    """Primary convention path: ``regions/<slug>/<slug>_yolo.pt``."""
    slug = region_slug(region)
    return region_pack_dir(region, regions_root=regions_root) / f"{slug}_yolo.pt"


def region_detector_candidates(
    region: str, *, regions_root: Optional[Path] = None
) -> list[Path]:
    """Lookup order for a region's YOLO file."""
    folder = region_pack_dir(region, regions_root=regions_root)
    slug = region_slug(region)
    return [
        folder / f"{slug}_yolo.pt",
        folder / "yolo.pt",
        folder / f"{slug}_det.pt",
    ]


@dataclass(frozen=True)
class RegionModels:
    """Resolved paths for one vision region (detector + classifier)."""

    region: str
    slug: str
    detector_path: Optional[str]
    classifier_path: Optional[str]
    classifier_edition: Optional[str]


def _abs_model_path(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return str(path)


def _first_existing(paths: list[Path]) -> Optional[Path]:
    for path in paths:
        if path.is_file():
            return path
    return None


def resolve_region_models(
    region: str,
    config: Optional[dict[str, Any]] = None,
    *,
    regions_root: Optional[Path] = None,
) -> RegionModels:
    """Resolve YOLO + classifier for ``region``.

    Order for each role:
      1. ``vision.regions[<region>].detector`` / ``.classifier`` override
      2. Convention file under ``app/models/regions/<slug>/`` if it exists
      3. Global ``vision.detector.model_path`` / ``vision.classifier.model_path``
    """
    section = (config or {}).get("vision") or {}
    regions = section.get("regions") or {}
    key = str(region or "").strip()
    slug = region_slug(key) if key else ""

    entry: dict[str, Any] = {}
    if key and isinstance(regions, dict):
        if key in regions and isinstance(regions[key], dict):
            entry = regions[key]
        elif slug in regions and isinstance(regions[slug], dict):
            entry = regions[slug]

    det = section.get("detector") or {}
    clf = section.get("classifier") or {}
    root = Path(regions_root) if regions_root is not None else _REGIONS_ROOT

    detector: Optional[str] = None
    det_override = (
        entry.get("detector")
        or entry.get("detector_path")
        or entry.get("yolo")
        or entry.get("yolo_path")
    )
    if det_override:
        detector = str(det_override)
    elif slug:
        found = _first_existing(
            region_detector_candidates(key, regions_root=root)
        )
        if found is not None:
            try:
                detector = str(found.relative_to(_PROJECT_ROOT)).replace("\\", "/")
            except ValueError:
                detector = str(found)
    if not detector:
        detector = det.get("model_path")

    classifier: Optional[str] = None
    clf_override = entry.get("classifier") or entry.get("classifier_path")
    if clf_override:
        classifier = str(clf_override)
    elif slug:
        convention = region_classifier_path(key, regions_root=root)
        if convention.is_file():
            try:
                classifier = str(convention.relative_to(_PROJECT_ROOT)).replace(
                    "\\", "/"
                )
            except ValueError:
                classifier = str(convention)
    if not classifier:
        classifier = clf.get("model_path")

    edition = (
        entry.get("edition") or entry.get("classifier_edition") or clf.get("edition")
    )

    return RegionModels(
        region=key,
        slug=slug,
        detector_path=_abs_model_path(detector if detector else None),
        classifier_path=_abs_model_path(classifier if classifier else None),
        classifier_edition=str(edition) if edition else None,
    )


__all__ = [
    "RegionModels",
    "region_slug",
    "region_pack_dir",
    "region_classifier_path",
    "region_detector_path",
    "region_detector_candidates",
    "resolve_region_models",
]
