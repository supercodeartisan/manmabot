"""Catalog of vision-region display names (``config/regions.yaml``).

Separate from weight path overrides in ``vision.regions``. Used by the
area editor combobox and ``add_region_name`` when creating a new label.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from app._02_vision.region_models import region_slug

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGIONS_PATH = _PROJECT_ROOT / "config" / "regions.yaml"


def regions_catalog_path() -> Path:
    return _DEFAULT_REGIONS_PATH


def normalize_region_name(name: str) -> str:
    """Collapse whitespace; keep lowercase for stable matching."""
    return " ".join(str(name).strip().lower().split())


def load_region_names(path: Optional[Path] = None) -> list[str]:
    """Return ordered unique region names from the catalog YAML."""
    catalog = path or _DEFAULT_REGIONS_PATH
    if not catalog.is_file():
        return []
    doc = yaml.safe_load(catalog.read_text(encoding="utf-8")) or {}
    raw: Any = None
    if isinstance(doc, dict):
        raw = doc.get("region_names")
        if raw is None:
            raw = doc.get("regions")
    elif isinstance(doc, list):
        raw = doc
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        name = normalize_region_name(str(item or ""))
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def save_region_names(names: list[str], path: Optional[Path] = None) -> Path:
    """Write the catalog (normalized, unique, keep insertion order)."""
    catalog = path or _DEFAULT_REGIONS_PATH
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in names:
        name = normalize_region_name(item)
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    catalog.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Vision-region name catalog (area YAML ``region:``).",
        "# Classifier + YOLO: app/models/regions/<slug>/<slug>.pt and <slug>_yolo.pt",
        "# Key is region_names (avoids clash with vision.regions on merge).",
        "region_names:",
    ]
    if not cleaned:
        lines.append("  []")
    else:
        for name in cleaned:
            lines.append(f"  - {name}")
    catalog.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return catalog


def add_region_name(
    name: str,
    path: Optional[Path] = None,
) -> list[str]:
    """Append a new region name if missing; return the updated list.

    Raises ``ValueError`` when the name is empty after normalization.
    """
    cleaned = normalize_region_name(name)
    if not cleaned:
        raise ValueError("Region name is empty")
    # Ensure slug is usable as a folder name.
    if not region_slug(cleaned):
        raise ValueError(f"Invalid region name: {name!r}")
    names = load_region_names(path)
    if cleaned not in names:
        names.append(cleaned)
        save_region_names(names, path)
    return names


__all__ = [
    "regions_catalog_path",
    "normalize_region_name",
    "load_region_names",
    "save_region_names",
    "add_region_name",
]
