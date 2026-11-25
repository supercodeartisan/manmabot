"""Build the five blessing-land field packs from verified terrain sources.

244 uses the hand-tuned shipping ``nav.png`` from the legacy dungeon pack.
Season packs use ``obstacle_tiles_raw/map_<id>.png`` after verifying pure
black/white pixels that match ``TerrainMap`` DEFAULT_COLOR_LEGEND
(white walkable, black blocked). Does not copy 244 nav onto other seasons.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MAPS = ROOT / "Engine" / "data" / "maps"
RAW = MAPS / "obstacle_tiles_raw"
LEGACY = MAPS / "polluted_land_of_blessing_dungeon"

ORIGIN_X = 32640
ORIGIN_Y = 32768

PACKS = (
    ("polluted_land_of_blessing", 244, "Polluted Land of Blessing"),
    ("corrupted_land_of_blessing_spring", 2450, "Corrupted Land of Blessing - Spring"),
    ("corrupted_land_of_blessing_summer", 245, "Corrupted Land of Blessing - Summer"),
    ("corrupted_land_of_blessing_autumn", 2452, "Corrupted Land of Blessing - Autumn"),
    ("corrupted_land_of_blessing_winter", 2454, "Corrupted Land of Blessing - Winter"),
)


def _raw_to_nav_rgba(src: Path, dst: Path) -> tuple[int, int, int, int]:
    im = Image.open(src).convert("RGB")
    arr = np.asarray(im)
    flat = arr.reshape(-1, 3)
    if not bool(np.all((flat == 0) | (flat == 255))):
        raise SystemExit(f"non black/white pixels in {src}")
    rgba = Image.fromarray(arr, mode="RGB").convert("RGBA")
    dst.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(dst)
    walk = int(np.all(arr == 255, axis=2).sum())
    block = int(np.all(arr == 0, axis=2).sum())
    return im.size[0], im.size[1], walk, block


def _write_legacy_meta() -> None:
    text = """id: polluted_land_of_blessing_dungeon
name: "Polluted Land of Blessing (legacy)"
# Live mapId 244 is owned by polluted_land_of_blessing (field pack).
# This folder stays loadable by pack_id for old UserData/tooling paths.
# raw_map intentionally omitted so map_id_to_pack_id(244) is unique.
legacy_superseded_by: polluted_land_of_blessing
origin_x: 32640
origin_y: 32768
pixel_scale: 1
terrain: nav.png
patrol: patrol.yaml
"""
    (LEGACY / "meta.yaml").write_text(text, encoding="utf-8")


def main() -> int:
    if not (LEGACY / "nav.png").is_file():
        print(f"missing legacy nav: {LEGACY / 'nav.png'}", file=sys.stderr)
        return 2
    _write_legacy_meta()
    print("demoted", LEGACY.name)

    for pack_id, mid, name in PACKS:
        pack = MAPS / pack_id
        pack.mkdir(parents=True, exist_ok=True)
        nav = pack / "nav.png"
        if mid == 244:
            shutil.copy2(LEGACY / "nav.png", nav)
            im = Image.open(nav)
            w, h = im.size
            print(f"ok {pack_id} nav from legacy hand-tuned {w}x{h}")
        else:
            src = RAW / f"map_{mid}.png"
            w, h, walk, block = _raw_to_nav_rgba(src, nav)
            print(
                f"ok {pack_id} nav from obstacle_tiles_raw "
                f"{w}x{h} walk={walk} block={block}"
            )
        (pack / "farms.yaml").write_text(
            "# Areas (nav tiles). region selects vision models "
            "(not the map pack id).\nareas: []\n",
            encoding="utf-8",
        )
        (pack / "meta.yaml").write_text(
            f"""id: {pack_id}
name: "{name}"
# Field hunt pack. Origin from map_transitions rect / obstacle_tiles_raw map_{mid}.
raw_map: "{mid}"
origin_x: {ORIGIN_X}
origin_y: {ORIGIN_Y}
pixel_scale: 1
terrain: nav.png
farms: farms.yaml
default_region: blessing_land
""",
            encoding="utf-8",
        )
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
