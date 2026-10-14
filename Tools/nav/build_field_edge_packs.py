"""Build TI/mainland ``nav.png`` (fence_bw) + edge nav_prebuild from Support/field_s32.

``.s32`` stays under Support (not deployed). Pack folders get ``nav.png`` + nav_prebuild only.
Previous ``nav.png`` is copied to ``legacy/`` before overwrite when missing there.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))
from common.bootstrap import bootstrap  # noqa: E402

bootstrap()

from app._03_world.space.edge_layers import (  # noqa: E402
    MAINLAND_ORIGIN,
    TI_ORIGIN,
    load_edge_layers,
    support_s32_dir,
)
from app._03_world.space.map_pack import list_map_packs  # noqa: E402
from app._03_world.space.terrain_map import (  # noqa: E402
    DEFAULT_CLEARANCE_TILES,
    DEFAULT_WALL_PENALTY,
)
from app._04_decision.hierarchical_path import DEFAULT_CLUSTER  # noqa: E402
from app._04_decision.nav_prebuild import (  # noqa: E402
    build_and_save_edge_prebuild,
    prebuild_dir_for_pack,
)

_NAV_NAME = "nav.png"

_FIELD = {
    "talking_island": {
        "origin": TI_ORIGIN,
        "width": 512,
        "height": 576,
    },
    "mainland": {
        "origin": MAINLAND_ORIGIN,
        "width": None,
        "height": None,
    },
}


def _ensure_junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        return
    if not target.is_dir():
        raise FileNotFoundError(f"s32 source missing: {target}")
    # Directory junction (no admin required for same-machine paths).
    import subprocess

    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"mklink /J failed: {r.stderr or r.stdout}")


def _link_defaults() -> None:
    _ensure_junction(support_s32_dir("talking_island", project_root=ROOT), Path(r"D:\map_0"))
    _ensure_junction(support_s32_dir("mainland", project_root=ROOT), Path(r"D:\map_4"))


def _build_one(pack_id: str, *, force: bool) -> None:
    cfg = _FIELD[pack_id]
    packs = {p.id: p for p in list_map_packs(ROOT / "Engine" / "data" / "maps")}
    pack = packs.get(pack_id)
    if pack is None:
        raise FileNotFoundError(f"map pack not found: {pack_id}")
    s32 = support_s32_dir(pack_id, project_root=ROOT)
    if not s32.is_dir() or not any(s32.glob("*.s32")):
        raise FileNotFoundError(f"no .s32 under {s32}")

    ox, oy = cfg["origin"]
    layers = load_edge_layers(
        s32,
        origin_x=ox,
        origin_y=oy,
        width=cfg["width"],
        height=cfg["height"],
    )
    nav_path = pack.root / _NAV_NAME
    if nav_path.is_file():
        legacy = pack.root / "legacy"
        legacy.mkdir(parents=True, exist_ok=True)
        prev = legacy / "nav_prev.png"
        if not prev.is_file():
            shutil.copy2(nav_path, prev)

    layers.save_fence_bw_png(nav_path, tile_px=4)
    print(f"wrote {nav_path} ({layers.width}x{layers.height} tiles)")

    meta_path = pack.root / "meta.yaml"
    text = meta_path.read_text(encoding="utf-8")
    # Point terrain at nav.png and pixel_scale 4 (idempotent-ish replace).
    lines = []
    for line in text.splitlines():
        if line.startswith("pixel_scale:"):
            lines.append("pixel_scale: 4")
        elif line.startswith("terrain:"):
            lines.append(f"terrain: {_NAV_NAME}")
        else:
            lines.append(line)
    meta_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = prebuild_dir_for_pack(pack.root)
    cluster = int(pack.cluster_size or DEFAULT_CLUSTER)
    t0 = time.perf_counter()
    meta = build_and_save_edge_prebuild(
        layers,
        nav_path,
        out,
        cluster=cluster,
        clearance_tiles=int(pack.clearance_tiles or DEFAULT_CLEARANCE_TILES),
        wall_penalty=int(pack.wall_penalty or DEFAULT_WALL_PENALTY),
    )
    ms = (time.perf_counter() - t0) * 1000.0
    uncovered = int((~layers.covered).sum())
    print(
        f"ok {pack_id} {meta.width}x{meta.height} nodes={meta.node_count} "
        f"cluster={meta.cluster} uncovered={uncovered} ({ms:.0f} ms) edges=yes"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        default="",
        help="talking_island | mainland (default: both)",
    )
    parser.add_argument("--force", action="store_true", help="unused; always rebuild")
    parser.add_argument(
        "--skip-link",
        action="store_true",
        help="do not create Support junctions to D:\\map_0 / D:\\map_4",
    )
    args = parser.parse_args()
    if not args.skip_link:
        try:
            _link_defaults()
        except Exception as exc:
            print(f"warn: Support junction: {exc}", file=sys.stderr)

    only = str(args.only or "").strip()
    ids = [only] if only else list(_FIELD)
    for pack_id in ids:
        if pack_id not in _FIELD:
            print(f"unknown pack {pack_id!r}", file=sys.stderr)
            return 2
        _build_one(pack_id, force=bool(args.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
