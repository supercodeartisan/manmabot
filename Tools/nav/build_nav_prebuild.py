"""Offline-build ``nav_prebuild/`` for every map pack (or one pack).

PNG-only rebuild. Field packs with N/E edge layers (Talking Island / mainland)
must use ``Tools/nav/build_field_edge_packs.py`` instead — this tool refuses
those packs so a casual ``--force`` cannot strip ``edge_*.npy``.

Usage:
  python Tools/nav/build_nav_prebuild.py
  python Tools/nav/build_nav_prebuild.py --only some_dungeon
  python Tools/nav/build_nav_prebuild.py --force
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))
from common.bootstrap import bootstrap  # noqa: E402

bootstrap()

from app._03_world.space.map_pack import list_map_packs  # noqa: E402
from app._03_world.space.terrain_map import (  # noqa: E402
    DEFAULT_CLEARANCE_TILES,
    DEFAULT_WALL_PENALTY,
)
from app._04_decision.hierarchical_path import DEFAULT_CLUSTER  # noqa: E402
from app._04_decision.nav_prebuild import (  # noqa: E402
    build_and_save_prebuild,
    file_sha256,
    has_edge_prebuild,
    prebuild_dir_for_pack,
    prebuild_is_complete,
    read_prebuild_meta,
)


def _maps_dir(arg: str | None) -> Path:
    if arg:
        path = Path(arg)
        return path if path.is_absolute() else ROOT / path
    return ROOT / "Engine" / "data" / "maps"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maps-dir",
        default=None,
        help="Map packs root (default: Engine/data/maps)",
    )
    parser.add_argument("--only", default="", help="Build a single pack id")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when meta matches current nav.png",
    )
    parser.add_argument(
        "--cluster",
        type=int,
        default=0,
        help="Override cluster size (0 = pack meta or default 32)",
    )
    args = parser.parse_args()
    maps_dir = _maps_dir(args.maps_dir)
    packs = list_map_packs(maps_dir)
    only = str(args.only or "").strip()
    if only:
        packs = [p for p in packs if p.id == only]
        if not packs:
            print(f"no pack id={only!r} under {maps_dir}", file=sys.stderr)
            return 2

    built = skipped = failed = 0
    t_all = time.perf_counter()
    for pack in packs:
        out = prebuild_dir_for_pack(pack.root)
        cluster = (
            int(args.cluster)
            if int(args.cluster) > 0
            else int(pack.cluster_size or DEFAULT_CLUSTER)
        )
        clearance = int(pack.clearance_tiles or DEFAULT_CLEARANCE_TILES)
        wall_penalty = int(pack.wall_penalty or DEFAULT_WALL_PENALTY)
        try:
            if has_edge_prebuild(out):
                print(
                    f"skip {pack.id} (edge fence prebuild — use "
                    f"Tools/nav/Build_Field_Edge_Packs.bat)",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            digest = file_sha256(pack.terrain_path)
            if not args.force and prebuild_is_complete(out):
                meta = read_prebuild_meta(out)
                if (
                    meta.source_sha256 == digest
                    and int(meta.cluster) == cluster
                    and meta.width > 0
                ):
                    print(f"skip {pack.id} (up to date)")
                    skipped += 1
                    continue
            t0 = time.perf_counter()
            meta = build_and_save_prebuild(
                pack.terrain_path,
                out,
                cluster=cluster,
                pixel_scale=pack.pixel_scale,
                clearance_tiles=clearance,
                wall_penalty=wall_penalty,
            )
            ms = (time.perf_counter() - t0) * 1000.0
            print(
                f"ok {pack.id} {meta.width}x{meta.height} nodes={meta.node_count} "
                f"cluster={meta.cluster} ({ms:.0f} ms)"
            )
            built += 1
        except Exception as exc:
            failed += 1
            print(f"FAIL {pack.id}: {exc}", file=sys.stderr)
    elapsed = time.perf_counter() - t_all
    print(
        f"done built={built} skipped={skipped} failed={failed} "
        f"packs={len(packs)} ({elapsed:.1f}s)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
