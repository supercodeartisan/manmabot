"""Map packs: PNG + world origin + per-map areas under ``maps/<id>/``.

Each pack folder contains ``meta.yaml``, a terrain image, and optional
``farms`` / ``safe`` / ``home`` YAML (nav-tile rects). Area entries may set
``region`` for vision models — that is not the same as the map pack id.
The bot selects one pack via ``navigation.maps_dir`` + ``navigation.active_map``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_active: Optional["MapPack"] = None

_DEFAULT_AREA_NAMES = {
    "farms": "farms.yaml",
    "safe": "safe.yaml",
    "home": "home.yaml",
    "patrol": "patrol.yaml",
}


@dataclass(frozen=True)
class MapPack:
    """One map's walkability image, game-world origin, and area YAML paths.

    Map id/name ≠ area ``region`` (vision model key on each farm/safe/home rect).
    """

    id: str
    name: str
    root: Path
    terrain_path: Path
    origin_x: int
    origin_y: int
    pixel_scale: int
    clearance_tiles: Optional[int] = None
    wall_penalty: Optional[int] = None
    cluster_size: Optional[int] = None
    farm_areas_path: Optional[Path] = None
    safe_areas_path: Optional[Path] = None
    home_path: Optional[Path] = None
    patrol_path: Optional[Path] = None
    # Default ``region`` stamped on new areas drawn for this map (vision models).
    default_region: str = ""


def get_active_map_pack() -> Optional[MapPack]:
    return _active


def set_active_map_pack(pack: Optional[MapPack]) -> None:
    global _active
    _active = pack


def resolve_maps_dir(
    config: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    """Absolute ``maps_dir`` from config, or ``None`` if unset."""
    section = (config or {}).get("navigation") or {}
    maps_dir = section.get("maps_dir")
    if not maps_dir:
        return None
    root = Path(str(maps_dir))
    if not root.is_absolute():
        root = _PROJECT_ROOT / root
    return root


def list_map_packs(
    maps_dir: str | Path,
) -> list[MapPack]:
    """Load every valid pack under ``maps_dir`` (sorted by folder name)."""
    root = Path(maps_dir)
    if not root.is_dir():
        return []
    skip = {"_legacy_dungeons", "obstacle_tiles_raw", "dungeons", "new"}
    packs: list[MapPack] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name in skip or child.name.startswith("_"):
            continue
        try:
            packs.append(load_map_pack(root, child.name))
        except (OSError, ValueError, FileNotFoundError):
            continue
    return packs


def _pack_area_path(
    pack_dir: Path,
    meta: dict[str, Any],
    key: str,
) -> Optional[Path]:
    """Resolve optional area YAML path inside the pack folder."""
    raw = meta.get(key)
    if raw is False:
        return None
    if raw is None:
        name = _DEFAULT_AREA_NAMES.get(key)
        if not name:
            return None
        candidate = pack_dir / name
        return candidate.resolve() if candidate.is_file() else None
    name = str(raw).strip()
    if not name:
        return None
    path = Path(name)
    if not path.is_absolute():
        path = pack_dir / path
    return path.resolve()


def load_map_pack(
    maps_dir: str | Path,
    map_id: str,
    *,
    section: Optional[dict[str, Any]] = None,
) -> MapPack:
    """Load one pack folder ``maps_dir/<map_id>`` (does not set active)."""
    section = section or {}
    root = Path(maps_dir)
    if not root.is_absolute():
        root = _PROJECT_ROOT / root
    pack_dir = root / str(map_id)
    meta_path = pack_dir / "meta.yaml"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Map pack meta not found: {meta_path}")

    with meta_path.open("r", encoding="utf-8") as f:
        meta = yaml.safe_load(f) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"Map meta must be a mapping: {meta_path}")

    pack_id = str(meta.get("id") or map_id)
    name = str(meta.get("name") or pack_id)
    origin_x = int(meta.get("origin_x", section.get("map_origin_x", 0)))
    origin_y = int(meta.get("origin_y", section.get("map_origin_y", 0)))
    pixel_scale = int(meta.get("pixel_scale", section.get("pixel_scale", 1)))
    terrain_name = str(meta.get("terrain") or "nav.png")
    terrain_path = pack_dir / terrain_name
    if not terrain_path.is_file():
        raise FileNotFoundError(f"Map pack terrain not found: {terrain_path}")

    clr = meta.get("clearance_tiles")
    pen = meta.get("wall_penalty")
    cluster = meta.get("cluster_size")
    default_region = str(meta.get("default_region") or "").strip()
    return MapPack(
        id=pack_id,
        name=name,
        root=pack_dir,
        terrain_path=terrain_path.resolve(),
        origin_x=origin_x,
        origin_y=origin_y,
        pixel_scale=max(1, pixel_scale),
        clearance_tiles=int(clr) if clr is not None else None,
        wall_penalty=int(pen) if pen is not None else None,
        cluster_size=int(cluster) if cluster is not None else None,
        farm_areas_path=_pack_area_path(pack_dir, meta, "farms"),
        safe_areas_path=_pack_area_path(pack_dir, meta, "safe"),
        home_path=_pack_area_path(pack_dir, meta, "home"),
        patrol_path=_pack_area_path(pack_dir, meta, "patrol"),
        default_region=default_region,
    )


def resolve_active_map_pack(
    config: Optional[dict[str, Any]] = None,
) -> Optional[MapPack]:
    """Load ``maps/<active_map>`` when ``maps_dir`` and ``active_map`` are set.

    Returns ``None`` for legacy configs that only set ``terrain_map`` /
    ``map_origin_*`` (tests and older YAML).
    """
    section = (config or {}).get("navigation") or {}
    maps_dir = resolve_maps_dir(config)
    active = section.get("active_map")
    if maps_dir is None or not active:
        set_active_map_pack(None)
        return None

    pack = load_map_pack(maps_dir, str(active), section=section)
    set_active_map_pack(pack)
    return pack


def navigation_with_map_pack(
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return a config copy with terrain/origin/areas filled from the active pack.

    If no pack is configured, returns ``config`` unchanged (or ``{}``).
    Explicit ``farm_areas_file`` / ``safe_areas_file`` / ``home_file`` in config
    still win when already set (non-empty override).
    """
    if config is None:
        return {}
    section = dict(config.get("navigation") or {})
    pack = resolve_active_map_pack({"navigation": section})
    if pack is None:
        return config

    section["terrain_map"] = str(pack.terrain_path)
    section["map_origin_x"] = pack.origin_x
    section["map_origin_y"] = pack.origin_y
    section["pixel_scale"] = pack.pixel_scale
    if pack.clearance_tiles is not None:
        section["clearance_tiles"] = pack.clearance_tiles
    if pack.wall_penalty is not None:
        section["wall_penalty"] = pack.wall_penalty
    if pack.cluster_size is not None:
        section["cluster_size"] = pack.cluster_size

    # Prefer pack area files unless the caller forced an override path.
    if not section.get("farm_areas_file") and pack.farm_areas_path is not None:
        section["farm_areas_file"] = str(pack.farm_areas_path)
    if not section.get("safe_areas_file") and pack.safe_areas_path is not None:
        section["safe_areas_file"] = str(pack.safe_areas_path)
    if not section.get("home_file") and pack.home_path is not None:
        section["home_file"] = str(pack.home_path)

    out = dict(config)
    out["navigation"] = section
    return out


__all__ = [
    "MapPack",
    "get_active_map_pack",
    "set_active_map_pack",
    "resolve_maps_dir",
    "list_map_packs",
    "load_map_pack",
    "resolve_active_map_pack",
    "navigation_with_map_pack",
]
