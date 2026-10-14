"""Offline navigation prebuild: walkable + portal graph on disk.

Runtime loads these files; it does not rebuild from ``nav.png``.
Dungeon packs: ``Tools/nav/build_nav_prebuild.py``.
Field packs with N/E fences: ``Tools/nav/build_field_edge_packs.py``
(``Build_Field_Edge_Packs.bat``). Do not PNG-rebuild those with the dungeon tool.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from app._03_world.space.terrain_map import (
    DEFAULT_CLEARANCE_TILES,
    DEFAULT_WALL_PENALTY,
    TerrainMap,
)
from app._04_decision.hierarchical_path import DEFAULT_CLUSTER, CoarseMap
from app._04_decision.portal_graph import PortalGraph, PortalNode, build_portal_graph

if TYPE_CHECKING:
    from app._03_world.space.edge_layers import EdgeLayers

PREBUILD_DIRNAME = "nav_prebuild"
PREBUILD_VERSION = 2
_META_NAME = "meta.json"
_WALK_NAME = "walkable.npy"
_LABELS_NAME = "labels.npy"
_COARSE_NAME = "coarse.npy"
_CLEARANCE_NAME = "clearance.npy"
_COSTS_NAME = "costs.npy"
_GRAPH_NAME = "graph.pkl"
_EDGE_SOLID_NAME = "edge_solid.npy"
_EDGE_BLOCK_N_NAME = "edge_block_n.npy"
_EDGE_BLOCK_E_NAME = "edge_block_e.npy"


@dataclass(frozen=True)
class NavPrebuildMeta:
    version: int
    cluster: int
    width: int
    height: int
    clearance_tiles: int
    wall_penalty: int
    source_name: str
    source_sha256: str
    node_count: int

    def to_json(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "cluster": int(self.cluster),
            "width": int(self.width),
            "height": int(self.height),
            "clearance_tiles": int(self.clearance_tiles),
            "wall_penalty": int(self.wall_penalty),
            "source_name": str(self.source_name),
            "source_sha256": str(self.source_sha256),
            "node_count": int(self.node_count),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "NavPrebuildMeta":
        return cls(
            version=int(raw.get("version") or 0),
            cluster=int(raw["cluster"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
            clearance_tiles=int(raw.get("clearance_tiles", DEFAULT_CLEARANCE_TILES)),
            wall_penalty=int(raw.get("wall_penalty", DEFAULT_WALL_PENALTY)),
            source_name=str(raw.get("source_name") or ""),
            source_sha256=str(raw.get("source_sha256") or ""),
            node_count=int(raw.get("node_count") or 0),
        )


def prebuild_dir_for_pack(pack_root: Path) -> Path:
    return Path(pack_root) / PREBUILD_DIRNAME


def prebuild_dir_beside_terrain(terrain_path: Path) -> Path:
    return Path(terrain_path).resolve().parent / PREBUILD_DIRNAME


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prebuild_is_complete(directory: Path) -> bool:
    root = Path(directory)
    return all(
        (root / name).is_file()
        for name in (
            _META_NAME,
            _WALK_NAME,
            _LABELS_NAME,
            _COARSE_NAME,
            _CLEARANCE_NAME,
            _COSTS_NAME,
            _GRAPH_NAME,
        )
    )


def read_prebuild_meta(directory: Path) -> NavPrebuildMeta:
    path = Path(directory) / _META_NAME
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"nav prebuild meta must be an object: {path}")
    return NavPrebuildMeta.from_json(raw)


def build_from_terrain(
    terrain: TerrainMap,
    *,
    cluster: int = DEFAULT_CLUSTER,
) -> tuple[CoarseMap, PortalGraph]:
    coarse = CoarseMap.from_terrain(terrain, cluster)
    graph = build_portal_graph(terrain, cluster)
    return coarse, graph


def edge_prebuild_paths(directory: Path) -> tuple[Path, Path, Path]:
    root = Path(directory)
    return (
        root / _EDGE_SOLID_NAME,
        root / _EDGE_BLOCK_N_NAME,
        root / _EDGE_BLOCK_E_NAME,
    )


def has_edge_prebuild(directory: Path) -> bool:
    return all(p.is_file() for p in edge_prebuild_paths(directory))


def save_nav_prebuild(
    directory: Path,
    terrain: TerrainMap,
    coarse: CoarseMap,
    graph: PortalGraph,
    *,
    source_path: Path,
    cluster: int,
) -> NavPrebuildMeta:
    """Write walkable / labels / coarse / graph next to a map pack."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    if graph.labels.shape != terrain.walkable.shape:
        raise ValueError("portal labels shape must match terrain.walkable")
    if coarse.fine_width != terrain.width or coarse.fine_height != terrain.height:
        raise ValueError("coarse map fine size must match terrain")
    if int(coarse.cluster) != int(cluster) or int(graph.cluster) != int(cluster):
        raise ValueError("cluster mismatch while saving nav prebuild")

    meta = NavPrebuildMeta(
        version=PREBUILD_VERSION,
        cluster=int(cluster),
        width=int(terrain.width),
        height=int(terrain.height),
        clearance_tiles=int(terrain.clearance_tiles),
        wall_penalty=int(terrain.wall_penalty),
        source_name=source.name,
        source_sha256=file_sha256(source),
        node_count=int(graph.node_count),
    )
    np.save(root / _WALK_NAME, np.asarray(terrain.walkable, dtype=np.bool_))
    np.save(root / _LABELS_NAME, np.asarray(graph.labels, dtype=np.int32))
    np.save(root / _COARSE_NAME, np.asarray(coarse.walkable, dtype=np.bool_))
    if terrain.clearance is None or terrain.costs is None:
        raise ValueError("terrain clearance/costs required to save nav prebuild")
    np.save(root / _CLEARANCE_NAME, np.asarray(terrain.clearance, dtype=np.int32))
    np.save(root / _COSTS_NAME, np.asarray(terrain.costs, dtype=np.int32))
    if terrain.has_edge_fences:
        assert terrain.block_n is not None and terrain.block_e is not None
        solid = ~np.asarray(terrain.walkable, dtype=bool)
        np.save(root / _EDGE_SOLID_NAME, solid)
        np.save(root / _EDGE_BLOCK_N_NAME, np.asarray(terrain.block_n, dtype=np.bool_))
        np.save(root / _EDGE_BLOCK_E_NAME, np.asarray(terrain.block_e, dtype=np.bool_))
    else:
        for path in edge_prebuild_paths(root):
            if path.is_file():
                path.unlink()
    payload = {
        "cluster": int(graph.cluster),
        "fine_width": int(graph.fine_width),
        "fine_height": int(graph.fine_height),
        "nodes": [
            (
                int(n.id),
                int(n.cx),
                int(n.cy),
                int(n.local_id),
                int(n.rep_x),
                int(n.rep_y),
                int(n.tile_count),
            )
            for n in graph.nodes
        ],
        "edges": {
            int(nid): [(int(nb), int(cost)) for nb, cost in nbrs]
            for nid, nbrs in graph.edges.items()
        },
    }
    with (root / _GRAPH_NAME).open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    with (root / _META_NAME).open("w", encoding="utf-8") as f:
        json.dump(meta.to_json(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return meta


def build_and_save_prebuild(
    source_nav: Path,
    directory: Path,
    *,
    cluster: int = DEFAULT_CLUSTER,
    pixel_scale: int = 1,
    clearance_tiles: int = DEFAULT_CLEARANCE_TILES,
    wall_penalty: int = DEFAULT_WALL_PENALTY,
) -> NavPrebuildMeta:
    """Load terrain PNG, build graphs, write ``nav_prebuild/``.

    Refuses when ``directory`` already has edge fence files — those packs must
    be rebuilt with ``build_and_save_edge_prebuild`` / field edge bat.
    """
    if has_edge_prebuild(directory):
        raise ValueError(
            f"refusing PNG-only prebuild at {directory}: edge_*.npy present; "
            f"use Tools/nav/build_field_edge_packs.py"
        )
    terrain = TerrainMap.from_png(
        source_nav,
        pixel_scale=max(1, int(pixel_scale)),
        clearance_tiles=int(clearance_tiles),
        wall_penalty=int(wall_penalty),
    )
    coarse, graph = build_from_terrain(terrain, cluster=int(cluster))
    return save_nav_prebuild(
        directory,
        terrain,
        coarse,
        graph,
        source_path=source_nav,
        cluster=int(cluster),
    )


def build_and_save_edge_prebuild(
    layers: EdgeLayers,
    fence_png: Path,
    directory: Path,
    *,
    cluster: int = DEFAULT_CLUSTER,
    clearance_tiles: int = DEFAULT_CLEARANCE_TILES,
    wall_penalty: int = DEFAULT_WALL_PENALTY,
) -> NavPrebuildMeta:
    """Build portal graph with ``can_step`` from Layer3 bit0; ship fence PNG as source."""
    walk = layers.walkable_mask()
    terrain = TerrainMap(
        walkable=walk,
        clearance_tiles=int(clearance_tiles),
        wall_penalty=int(wall_penalty),
        block_n=np.asarray(layers.block_n, dtype=bool),
        block_e=np.asarray(layers.block_e, dtype=bool),
    )
    coarse, graph = build_from_terrain(terrain, cluster=int(cluster))
    return save_nav_prebuild(
        directory,
        terrain,
        coarse,
        graph,
        source_path=Path(fence_png),
        cluster=int(cluster),
    )


def load_nav_prebuild(
    directory: Path,
    *,
    expected_cluster: Optional[int] = None,
    source_path: Optional[Path] = None,
    clearance_tiles: Optional[int] = None,
    wall_penalty: Optional[int] = None,
) -> tuple[TerrainMap, CoarseMap, PortalGraph, NavPrebuildMeta]:
    """Load offline nav pack. Raises if missing, stale, or cluster mismatch."""
    root = Path(directory)
    if not prebuild_is_complete(root):
        raise FileNotFoundError(
            f"nav prebuild incomplete under {root} "
            f"(need {_META_NAME}, {_WALK_NAME}, {_LABELS_NAME}, "
            f"{_COARSE_NAME}, {_CLEARANCE_NAME}, {_COSTS_NAME}, {_GRAPH_NAME})"
        )
    meta = read_prebuild_meta(root)
    if meta.version != PREBUILD_VERSION:
        raise ValueError(
            f"nav prebuild version {meta.version} != {PREBUILD_VERSION} at {root}"
        )
    if expected_cluster is not None and int(meta.cluster) != int(expected_cluster):
        raise ValueError(
            f"nav prebuild cluster={meta.cluster} != expected {expected_cluster} "
            f"at {root}; rebuild offline"
        )
    if source_path is not None and Path(source_path).is_file():
        digest = file_sha256(source_path)
        if meta.source_sha256 and digest != meta.source_sha256:
            raise ValueError(
                f"nav.png changed since prebuild at {root}; "
                f"run Tools/nav/build_nav_prebuild.py"
            )

    walk = np.load(root / _WALK_NAME)
    labels = np.load(root / _LABELS_NAME)
    coarse_walk = np.load(root / _COARSE_NAME)
    clearance = np.load(root / _CLEARANCE_NAME)
    costs = np.load(root / _COSTS_NAME)
    with (root / _GRAPH_NAME).open("rb") as f:
        payload = pickle.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"corrupt graph.pkl at {root}")

    clr = int(clearance_tiles if clearance_tiles is not None else meta.clearance_tiles)
    pen = int(wall_penalty if wall_penalty is not None else meta.wall_penalty)
    block_n = block_e = None
    if has_edge_prebuild(root):
        _solid_p, bn_p, be_p = edge_prebuild_paths(root)
        block_n = np.asarray(np.load(bn_p), dtype=bool)
        block_e = np.asarray(np.load(be_p), dtype=bool)
    terrain = TerrainMap(
        walkable=np.asarray(walk, dtype=bool),
        clearance=np.asarray(clearance, dtype=np.int32),
        costs=np.asarray(costs, dtype=np.int32),
        clearance_tiles=clr,
        wall_penalty=pen,
        block_n=block_n,
        block_e=block_e,
    )
    if terrain.width != meta.width or terrain.height != meta.height:
        raise ValueError(
            f"walkable size {terrain.width}x{terrain.height} != meta "
            f"{meta.width}x{meta.height} at {root}"
        )
    labels_i = np.asarray(labels, dtype=np.int32)
    if labels_i.shape != terrain.walkable.shape:
        raise ValueError(f"labels shape mismatch at {root}")

    nodes = [
        PortalNode(
            id=int(row[0]),
            cx=int(row[1]),
            cy=int(row[2]),
            local_id=int(row[3]),
            rep_x=int(row[4]),
            rep_y=int(row[5]),
            tile_count=int(row[6]),
        )
        for row in payload.get("nodes") or []
    ]
    edges_raw = payload.get("edges") or {}
    edges = {
        int(nid): [(int(nb), int(cost)) for nb, cost in (nbrs or [])]
        for nid, nbrs in edges_raw.items()
    }
    graph = PortalGraph(
        cluster=int(payload.get("cluster") or meta.cluster),
        fine_width=int(payload.get("fine_width") or meta.width),
        fine_height=int(payload.get("fine_height") or meta.height),
        labels=labels_i,
        nodes=nodes,
        edges=edges,
    )
    coarse = CoarseMap(
        cluster=int(meta.cluster),
        walkable=np.asarray(coarse_walk, dtype=bool),
        fine_width=int(meta.width),
        fine_height=int(meta.height),
    )
    return terrain, coarse, graph, meta


__all__ = [
    "PREBUILD_DIRNAME",
    "PREBUILD_VERSION",
    "NavPrebuildMeta",
    "prebuild_dir_for_pack",
    "prebuild_dir_beside_terrain",
    "prebuild_is_complete",
    "has_edge_prebuild",
    "file_sha256",
    "build_from_terrain",
    "save_nav_prebuild",
    "build_and_save_prebuild",
    "build_and_save_edge_prebuild",
    "load_nav_prebuild",
    "read_prebuild_meta",
]
