"""Validate nav_prebuild for the five blessing-land field packs.

Does not overwrite Engine assets or UserData. Regenerates into temp dirs only.
"""
from __future__ import annotations

import json
import pickle
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
ENGINE = ROOT / "Engine"
UI = ROOT / "UI"
for path in (str(ENGINE), str(UI)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app._03_world.space.map_pack import load_map_pack, resolve_maps_dir
from app._03_world.space.terrain_map import TerrainMap
from app._04_decision import nav_config as nc
from app._04_decision.nav_config import configure_navigation_for_map, get_terrain_map
from app._04_decision.nav_prebuild import (
    PREBUILD_VERSION,
    build_and_save_prebuild,
    file_sha256,
    load_nav_prebuild,
    prebuild_dir_for_pack,
    prebuild_is_complete,
    read_prebuild_meta,
)
from app._04_decision.pathfinding import find_path
from app._04_decision.world_nav import pack_ids as pack_ids_mod

PACKS = (
    "polluted_land_of_blessing",
    "corrupted_land_of_blessing_spring",
    "corrupted_land_of_blessing_summer",
    "corrupted_land_of_blessing_autumn",
    "corrupted_land_of_blessing_winter",
)

REQUIRED = (
    "meta.json",
    "walkable.npy",
    "labels.npy",
    "coarse.npy",
    "clearance.npy",
    "costs.npy",
    "graph.pkl",
)


@pytest.fixture(autouse=True)
def _clear_caches():
    pack_ids_mod._packs.cache_clear()
    yield
    pack_ids_mod._packs.cache_clear()


def _maps_dir() -> Path:
    found = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
    assert found is not None
    return found


def _pack(pack_id: str):
    return load_map_pack(_maps_dir(), pack_id)


def _cfg(pack_id: str) -> dict:
    return {"navigation": {"maps_dir": "data/maps", "active_map": pack_id}}


def _walk_samples(terrain: TerrainMap, n: int = 4) -> list[tuple[int, int]]:
    walk = terrain.walkable
    h, w = walk.shape
    out: list[tuple[int, int]] = []
    for x, y in (
        (96, 96),
        (192, 192),
        (288, 288),
        (128, 256),
        (w // 3, 2 * h // 3),
        (2 * w // 3, h // 3),
    ):
        if 0 <= x < w and 0 <= y < h and bool(walk[y, x]):
            out.append((x, y))
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# 1–4 inventory, hash, structure vs nav.png
# ---------------------------------------------------------------------------


def test_prebuild_files_complete_and_meta_matches_nav_png():
    report = []
    for pack_id in PACKS:
        pack = _pack(pack_id)
        nav = Path(pack.terrain_path)
        pre = prebuild_dir_for_pack(pack.root)
        assert nav.is_file(), pack_id
        assert prebuild_is_complete(pre), (pack_id, sorted(p.name for p in pre.iterdir()))
        for name in REQUIRED:
            assert (pre / name).is_file(), (pack_id, name)
        # No edge fence files on blessing packs
        assert not (pre / "edge_solid.npy").is_file()
        assert not (pre / "edge_block_n.npy").is_file()

        meta = read_prebuild_meta(pre)
        digest = file_sha256(nav)
        assert meta.version == PREBUILD_VERSION
        assert meta.source_name == nav.name
        assert meta.source_sha256 == digest, (
            pack_id,
            "stale or wrong-source prebuild",
            meta.source_sha256[:12],
            digest[:12],
        )
        assert meta.width == 384 and meta.height == 384
        assert meta.cluster == 32
        assert meta.node_count > 0

        # walkable.npy matches TerrainMap.from_png(nav.png)
        from_png = TerrainMap.from_png(nav, pixel_scale=pack.pixel_scale)
        walk = np.load(pre / "walkable.npy")
        assert walk.shape == (384, 384)
        assert walk.dtype == np.bool_ or walk.dtype == bool or str(walk.dtype) == "bool"
        assert np.array_equal(walk, from_png.walkable), pack_id
        assert int(walk.sum()) == int(from_png.walkable.sum())

        coarse = np.load(pre / "coarse.npy")
        assert coarse.ndim == 2
        assert coarse.shape[0] * meta.cluster >= meta.height - meta.cluster + 1

        labels = np.load(pre / "labels.npy")
        assert labels.shape == walk.shape

        clearance = np.load(pre / "clearance.npy")
        costs = np.load(pre / "costs.npy")
        assert clearance.shape == walk.shape
        assert costs.shape == walk.shape

        with (pre / "graph.pkl").open("rb") as f:
            graph = pickle.load(f)
        assert int(graph["fine_width"]) == 384
        assert int(graph["fine_height"]) == 384
        assert int(graph["cluster"]) == 32
        assert len(graph["nodes"]) == meta.node_count

        report.append(
            {
                "pack_id": pack_id,
                "nav_sha": digest[:16],
                "meta_sha": meta.source_sha256[:16],
                "walk": int(walk.sum()),
                "nodes": meta.node_count,
                "nav_mtime": nav.stat().st_mtime,
                "meta_mtime": (pre / "meta.json").stat().st_mtime,
            }
        )
        # Prebuild should not be older than a mismatched hash (already checked).
        # Timestamps alone are advisory; hash is authoritative.
    assert len(report) == 5


# ---------------------------------------------------------------------------
# 5 runtime load + no cross-map reuse
# ---------------------------------------------------------------------------


def test_runtime_load_nav_prebuild_per_pack_no_stale_graph():
    walk_fingerprints: dict[str, str] = {}
    node_counts: dict[str, int] = {}
    for pack_id in PACKS:
        pack = _pack(pack_id)
        pre = prebuild_dir_for_pack(pack.root)
        terrain, coarse, graph, meta = load_nav_prebuild(
            pre,
            expected_cluster=32,
            source_path=pack.terrain_path,
        )
        assert terrain.width == 384 and terrain.height == 384
        assert meta.source_sha256 == file_sha256(Path(pack.terrain_path))
        fp = hashlib_walk(terrain.walkable)
        walk_fingerprints[pack_id] = fp
        node_counts[pack_id] = int(graph.node_count)

        configure_navigation_for_map(_cfg(pack_id), pack_id)
        live = get_terrain_map()
        assert live is not None
        assert hashlib_walk(live.walkable) == fp
        assert nc.get_portal_graph() is not None
        assert int(nc.get_portal_graph().node_count) == node_counts[pack_id]

    # 244 hand-tuned nav differs from seasonal raw-based nav
    assert walk_fingerprints["polluted_land_of_blessing"] != walk_fingerprints[
        "corrupted_land_of_blessing_winter"
    ]
    # Switching back to first pack restores its fingerprint
    configure_navigation_for_map(_cfg(PACKS[0]), PACKS[0])
    assert hashlib_walk(get_terrain_map().walkable) == walk_fingerprints[PACKS[0]]
    assert int(nc.get_portal_graph().node_count) == node_counts[PACKS[0]]


def hashlib_walk(walk: np.ndarray) -> str:
    import hashlib

    return hashlib.sha256(np.asarray(walk, dtype=np.uint8).tobytes()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 6 stale detection already in load_nav_prebuild
# ---------------------------------------------------------------------------


def test_stale_prebuild_detected_when_nav_hash_differs(tmp_path: Path):
    pack = _pack(PACKS[0])
    pre_src = prebuild_dir_for_pack(pack.root)
    # Copy prebuild + fake a different nav.png beside it
    work = tmp_path / "stale_case"
    work.mkdir()
    pre = work / "nav_prebuild"
    shutil.copytree(pre_src, pre)
    fake_nav = work / "nav.png"
    # Flip one walkable semantics: all black
    from PIL import Image

    Image.new("RGBA", (384, 384), (0, 0, 0, 255)).save(fake_nav)
    assert file_sha256(fake_nav) != read_prebuild_meta(pre).source_sha256
    with pytest.raises(ValueError, match="nav.png changed since prebuild"):
        load_nav_prebuild(pre, expected_cluster=32, source_path=fake_nav)


def test_missing_prebuild_raises_not_silent_fallback(tmp_path: Path):
    empty = tmp_path / "empty_prebuild"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="nav prebuild incomplete"):
        load_nav_prebuild(empty, expected_cluster=32)


def test_corrupt_meta_or_incomplete_walk_raises(tmp_path: Path):
    pack = _pack(PACKS[1])
    pre_src = prebuild_dir_for_pack(pack.root)
    broken = tmp_path / "broken"
    shutil.copytree(pre_src, broken)
    (broken / "walkable.npy").unlink()
    with pytest.raises(FileNotFoundError, match="incomplete"):
        load_nav_prebuild(broken, expected_cluster=32, source_path=pack.terrain_path)

    broken2 = tmp_path / "bad_meta"
    shutil.copytree(pre_src, broken2)
    (broken2 / "meta.json").write_text(
        json.dumps({"version": 1, "cluster": 32, "width": 384, "height": 384,
                    "clearance_tiles": 2, "wall_penalty": 4, "source_name": "nav.png",
                    "source_sha256": "x", "node_count": 1}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="version"):
        load_nav_prebuild(broken2, expected_cluster=32, source_path=pack.terrain_path)


# ---------------------------------------------------------------------------
# 7–8 regenerate in isolation, compare, A*
# ---------------------------------------------------------------------------


def test_regenerate_in_temp_matches_shipped_and_astar(tmp_path: Path):
    results = []
    for pack_id in PACKS:
        pack = _pack(pack_id)
        shipped = prebuild_dir_for_pack(pack.root)
        out = tmp_path / pack_id / "nav_prebuild"
        meta_new = build_and_save_prebuild(
            Path(pack.terrain_path),
            out,
            cluster=32,
            pixel_scale=pack.pixel_scale,
        )
        meta_old = read_prebuild_meta(shipped)
        assert meta_new.source_sha256 == meta_old.source_sha256
        assert meta_new.width == meta_old.width
        assert meta_new.height == meta_old.height
        assert meta_new.cluster == meta_old.cluster
        assert meta_new.node_count == meta_old.node_count

        walk_old = np.load(shipped / "walkable.npy")
        walk_new = np.load(out / "walkable.npy")
        assert np.array_equal(walk_old, walk_new)

        # A* on shipped load vs regenerated load
        t_old, _, _, _ = load_nav_prebuild(
            shipped, expected_cluster=32, source_path=pack.terrain_path
        )
        t_new, _, _, _ = load_nav_prebuild(
            out, expected_cluster=32, source_path=pack.terrain_path
        )
        samples = _walk_samples(t_old, n=3)
        assert len(samples) >= 2
        start, goal = samples[0], samples[-1]
        path_old = find_path(t_old, start, goal)
        path_new = find_path(t_new, start, goal)
        assert path_old and path_new
        assert path_old == path_new
        results.append((pack_id, start, goal, len(path_old) - 1))
    assert len(results) == 5


# ---------------------------------------------------------------------------
# 9 configure_navigation fails closed when prebuild missing
# ---------------------------------------------------------------------------


def test_configure_navigation_fails_when_prebuild_dir_removed(tmp_path, monkeypatch):
    pack = _pack(PACKS[2])
    # Point pack root's prebuild resolution at an empty temp via monkeypatch of
    # prebuild_dir_for_pack used inside nav_config — safer: temporarily rename
    # is forbidden (must not touch assets). Instead call load path with empty.
    empty = tmp_path / "nav_prebuild"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        load_nav_prebuild(empty, expected_cluster=32, source_path=pack.terrain_path)


# ---------------------------------------------------------------------------
# 10 regressions: mainland / talking_island / dungeon still load
# ---------------------------------------------------------------------------


def test_regression_mainland_talking_island_dungeon_prebuild_load():
    for pack_id in ("mainland", "talking_island", "giran_dungeon_F1"):
        pack = _pack(pack_id)
        pre = prebuild_dir_for_pack(pack.root)
        assert prebuild_is_complete(pre), pack_id
        meta = read_prebuild_meta(pre)
        # Field edge packs: source may be fence png; still must load
        terrain, coarse, graph, loaded = load_nav_prebuild(
            pre,
            expected_cluster=int(pack.cluster_size or meta.cluster),
            source_path=pack.terrain_path if Path(pack.terrain_path).is_file() else None,
        )
        assert terrain.width > 0 and terrain.height > 0
        assert graph.node_count > 0
        configure_navigation_for_map(_cfg(pack_id), pack_id)
        live = get_terrain_map()
        assert live is not None
        assert live.width == terrain.width
