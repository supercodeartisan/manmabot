"""Discover raw dungeon PNGs + origin notes and bootstrap map packs.

Raw assets live under ``engine/maps/dungeons/`` (PNG + ``pos.txt``).
Saving from the patrol editor creates a loadable pack:

    engine/maps/<map_id>/meta.yaml
    engine/maps/<map_id>/nav.png
    images/real_maps/<map_id>.png
    userdata/maps/<map_id>/patrol.yaml
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from manmabot_v1.paths import (
    VERSION1_ROOT,
    assert_userdata_write,
    ensure_userdata,
    manmabot_root,
    map_overlay_slug,
    overlay_patrol_path,
)

_POS_LINE = re.compile(
    r"^(?P<name>\S+)\s+"
    r"origin_x\s*=\s*(?P<ox>-?\d+)\s+"
    r"origin(?:_y)?\s*=\s*(?P<oy>-?\d+)\s*$",
    re.IGNORECASE,
)
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


@dataclass(frozen=True)
class DungeonAsset:
    """One source map image with optional known world origin."""

    label: str
    image_path: Path
    origin_x: Optional[int] = None
    origin_y: Optional[int] = None
    suggested_id: str = ""


def dungeon_assets_root() -> Path:
    return manmabot_root() / "maps" / "dungeons"


def engine_maps_dir() -> Path:
    return manmabot_root() / "maps"


def real_maps_dir() -> Path:
    for name in ("real_maps", "Real_Maps"):
        path = VERSION1_ROOT / "images" / name
        if path.is_dir():
            return path
    path = VERSION1_ROOT / "images" / "real_maps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _norm_key(text: str) -> str:
    raw = str(text or "").lower()
    raw = raw.replace("dungen", "dungeon")
    return re.sub(r"[^a-z0-9]+", "", raw)


def suggest_map_id(stem: str) -> str:
    """Turn ``DesertDungeon_F1`` / ``Giran_dun_F1`` into a pack id with ``dungeon``."""
    raw = str(stem or "").strip()
    if not raw:
        return "dungeon_map"
    # CamelCase → underscores, keep existing separators
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    spaced = spaced.replace("-", "_").replace(" ", "_")
    spaced = re.sub(r"_+", "_", spaced).strip("_")
    parts = [p for p in spaced.split("_") if p]
    out: list[str] = []
    for part in parts:
        low = part.lower()
        if low in ("dun", "dungeon"):
            if not out or out[-1] != "dungeon":
                out.append("dungeon")
            continue
        # Keep floor tokens like F1 / f1 as F1
        if re.fullmatch(r"[Ff]\d+", part):
            out.append(f"F{part[1:]}")
            continue
        out.append(low)
    if "dungeon" not in out:
        inserted = False
        for i, token in enumerate(out):
            if re.fullmatch(r"F\d+", token):
                out.insert(i, "dungeon")
                inserted = True
                break
        if not inserted:
            out.append("dungeon")
    return map_overlay_slug("_".join(out))


def parse_pos_txt(path: Path) -> dict[str, tuple[int, int]]:
    """Map normalized name → (origin_x, origin_y)."""
    if not path.is_file():
        return {}
    out: dict[str, tuple[int, int]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = _POS_LINE.match(text)
        if not match:
            continue
        name = match.group("name")
        ox = int(match.group("ox"))
        oy = int(match.group("oy"))
        out[_norm_key(name)] = (ox, oy)
        out[_norm_key(suggest_map_id(name))] = (ox, oy)
    return out


def _lookup_origin(
    origins: dict[str, tuple[int, int]],
    *candidates: str,
) -> Optional[tuple[int, int]]:
    for cand in candidates:
        hit = origins.get(_norm_key(cand))
        if hit is not None:
            return hit
    # Fuzzy: any origin key contained in / containing the candidate
    for cand in candidates:
        key = _norm_key(cand)
        if not key:
            continue
        for ok, val in origins.items():
            if key in ok or ok in key:
                return val
    return None


def discover_dungeon_assets() -> list[DungeonAsset]:
    """Scan ``engine/maps/dungeons`` for PNGs and attach ``pos.txt`` origins."""
    root = dungeon_assets_root()
    if not root.is_dir():
        return []
    origins: dict[str, tuple[int, int]] = {}
    for pos in root.rglob("pos.txt"):
        origins.update(parse_pos_txt(pos))

    found: dict[str, DungeonAsset] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMG_EXTS:
            continue
        stem = path.stem
        mid = suggest_map_id(stem)
        origin = _lookup_origin(origins, stem, mid, path.name)
        asset = DungeonAsset(
            label=stem,
            image_path=path.resolve(),
            origin_x=None if origin is None else origin[0],
            origin_y=None if origin is None else origin[1],
            suggested_id=mid,
        )
        # Prefer Dun_map copies over nested duplicates
        prev = found.get(mid)
        if prev is None or "dun_map" in str(path).lower():
            found[mid] = asset
    return sorted(found.values(), key=lambda a: a.suggested_id.lower())


def pack_dir_for(map_id: str) -> Path:
    return engine_maps_dir() / map_overlay_slug(map_id)


def meta_yaml_text(
    *,
    map_id: str,
    name: str,
    origin_x: int,
    origin_y: int,
    pixel_scale: int = 1,
) -> str:
    mid = map_overlay_slug(map_id)
    display = str(name or mid).strip() or mid
    return (
        f"id: {mid}\n"
        f'name: "{display}"\n'
        f"origin_x: {int(origin_x)}\n"
        f"origin_y: {int(origin_y)}\n"
        f"pixel_scale: {max(1, int(pixel_scale))}\n"
        f"terrain: nav.png\n"
    )


def ensure_dungeon_pack(
    *,
    map_id: str,
    image_path: Path,
    origin_x: int,
    origin_y: int,
    pixel_scale: int = 1,
    display_name: str | None = None,
) -> Path:
    """Create/update ``engine/maps/<id>`` + ``images/real_maps/<id>.png``."""
    mid = map_overlay_slug(map_id)
    if "dungeon" not in mid.lower():
        mid = map_overlay_slug(f"{mid}_dungeon")
    src = Path(image_path)
    if not src.is_file():
        raise FileNotFoundError(f"Map image not found: {src}")

    pack = pack_dir_for(mid)
    pack.mkdir(parents=True, exist_ok=True)
    nav = pack / "nav.png"
    if src.resolve() != nav.resolve():
        shutil.copy2(src, nav)

    name = display_name or mid.replace("_", " ").title()
    (pack / "meta.yaml").write_text(
        meta_yaml_text(
            map_id=mid,
            name=name,
            origin_x=origin_x,
            origin_y=origin_y,
            pixel_scale=pixel_scale,
        ),
        encoding="utf-8",
    )

    art_dir = real_maps_dir()
    art = art_dir / f"{mid}.png"
    if src.resolve() != art.resolve():
        shutil.copy2(src, art)
    return pack


def save_patrol_overlay(
    map_id: str,
    points: list[tuple[int, int]],
    names: list[str] | None = None,
) -> Path:
    """Write Version 1 ``userdata/maps/<id>/patrol.yaml`` and mirror into the pack."""
    ensure_userdata()
    from app._04_decision.patrol import save_patrol_waypoints_yaml

    mid = map_overlay_slug(map_id)
    overlay = assert_userdata_write(overlay_patrol_path(mid))
    save_patrol_waypoints_yaml(overlay, points, names)

    pack = pack_dir_for(mid)
    if pack.is_dir():
        save_patrol_waypoints_yaml(pack / "patrol.yaml", points, names)
    return overlay


def load_pack_meta(map_id: str) -> Optional[dict]:
    path = pack_dir_for(map_id) / "meta.yaml"
    if not path.is_file():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else None
