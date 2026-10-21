"""Load engine/maps packs for planner GUI display + A* (no manmabot imports).

Display image and walkability both come from the pack terrain (meta ``terrain``,
usually ``nav.png``). ``images/real_maps`` is not used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

# ready/ -> world_nav -> _04_decision -> app -> engine
_ENGINE_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = _ENGINE_ROOT.parent
ENGINE_MAPS = _ENGINE_ROOT / "data" / "maps"
CATALOG = _ENGINE_ROOT / "data" / "world_nav" / "providers" / "00_maps.json"

# Packs without raw_map but known game mapId
_PACK_MAP_ID = {
    "talking_island": 0,
    "mainland": 4,
}


@dataclass(frozen=True)
class MapPack:
    pack_id: str
    display_name: str
    map_id: int
    origin_x: int
    origin_y: int
    pixel_scale: int
    image_path: Path
    meta_path: Path
    nav_path: Path | None = None

    def world_to_pixel(self, wx: int, wy: int) -> tuple[float, float]:
        ps = max(1, self.pixel_scale)
        return ((wx - self.origin_x) * ps, (wy - self.origin_y) * ps)

    def pixel_to_world(self, px: float, py: float) -> tuple[int, int]:
        ps = max(1, self.pixel_scale)
        return (int(round(px / ps + self.origin_x)), int(round(py / ps + self.origin_y)))

    def contains_world(self, wx: int, wy: int, img_w: int, img_h: int) -> bool:
        px, py = self.world_to_pixel(wx, wy)
        return 0 <= px < img_w and 0 <= py < img_h


def _parse_meta(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, Any] = {"pack_id": path.parent.name}
    for key in ("id", "name", "raw_map", "terrain"):
        m = re.search(rf"^{key}:\s*[\"']?([^\"'\n#]+)", text, re.M)
        if m:
            out[key] = m.group(1).strip().strip('"').strip("'")
    for key in ("origin_x", "origin_y", "pixel_scale"):
        m = re.search(rf"^{key}:\s*(-?\d+)", text, re.M)
        if m:
            out[key] = int(m.group(1))
    return out


def _kr_names() -> dict[int, str]:
    import json

    if not CATALOG.is_file():
        return {}
    try:
        doc = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    for m in doc.get("maps", []):
        try:
            out[int(m["mapId"])] = str(m.get("kr") or m.get("en") or m["mapId"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def discover_map_packs() -> list[MapPack]:
    """All packs with image + origin + resolvable numeric mapId."""
    kr = _kr_names()
    packs: list[MapPack] = []
    if not ENGINE_MAPS.is_dir():
        return packs
    for meta_path in sorted(ENGINE_MAPS.glob("*/meta.yaml")):
        meta = _parse_meta(meta_path)
        pack_id = str(meta.get("id") or meta_path.parent.name)
        origin_x = meta.get("origin_x")
        origin_y = meta.get("origin_y")
        if origin_x is None or origin_y is None:
            continue
        raw = meta.get("raw_map")
        if raw is not None and str(raw).strip().lstrip("-").isdigit():
            map_id = int(str(raw).strip())
        elif pack_id in _PACK_MAP_ID:
            map_id = _PACK_MAP_ID[pack_id]
        else:
            continue
        terrain = meta_path.parent / str(meta.get("terrain") or "nav.png")
        if not terrain.is_file():
            continue
        en_name = str(meta.get("name") or pack_id)
        display = kr.get(map_id) or en_name
        # Same engine/maps terrain for GUI display and A* walkability.
        packs.append(
            MapPack(
                pack_id=pack_id,
                display_name=display,
                map_id=map_id,
                origin_x=int(origin_x),
                origin_y=int(origin_y),
                pixel_scale=int(meta.get("pixel_scale") or 1),
                image_path=terrain,
                meta_path=meta_path,
                nav_path=terrain,
            )
        )
    # Unique display labels: if same display_name, append pack_id
    counts: dict[str, int] = {}
    for p in packs:
        counts[p.display_name] = counts.get(p.display_name, 0) + 1
    if any(c > 1 for c in counts.values()):
        fixed: list[MapPack] = []
        for p in packs:
            name = p.display_name
            if counts[name] > 1:
                name = f"{name} ({p.pack_id})"
            fixed.append(
                MapPack(
                    pack_id=p.pack_id,
                    display_name=name,
                    map_id=p.map_id,
                    origin_x=p.origin_x,
                    origin_y=p.origin_y,
                    pixel_scale=p.pixel_scale,
                    image_path=p.image_path,
                    meta_path=p.meta_path,
                    nav_path=p.nav_path,
                )
            )
        packs = fixed
    packs.sort(key=lambda p: (p.display_name, p.map_id))
    return packs


_IMAGE_SIZE: dict[str, tuple[int, int]] = {}


def pack_image_size(pack: MapPack) -> tuple[int, int] | None:
    """Pixel size of the pack nav image. Header only; cached per path."""
    key = str(pack.image_path)
    hit = _IMAGE_SIZE.get(key)
    if hit is not None:
        return hit
    try:
        with Image.open(pack.image_path) as im:
            size = (int(im.size[0]), int(im.size[1]))
    except OSError:
        return None
    _IMAGE_SIZE[key] = size
    return size


def open_pack_image(pack: MapPack) -> Image.Image:
    im = Image.open(pack.image_path)
    im.load()
    return im.convert("RGB")
