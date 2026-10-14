"""Load world-nav graph: talking-scroll hubs from providers; map transitions
from ``engine/data/world/map_transitions.json`` (user-edited production edges).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ENGINE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = _ENGINE_ROOT / "data" / "world_nav" / "manifest.json"
DEFAULT_PROVIDERS = _ENGINE_ROOT / "data" / "world_nav" / "providers"
# User-maintained transition graph (manual coordinate fixes live here).
DEFAULT_MAP_TRANSITIONS = _ENGINE_ROOT / "data" / "world" / "map_transitions.json"
ROOT = DEFAULT_MANIFEST.parent

# Kinds the live runner can execute as enter-at-cell / ladder gate clicks.
# Ships / interior teleports stay out of the top-level planner.
LIVE_EDGE_KINDS = frozenset({"ground_enter", "floor_ladder"})


@dataclass
class Hub:
    index: int
    name: str
    region: str
    map_id: int
    x: int
    y: int
    ui: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.map_id, self.x, self.y)

    def label(self) -> str:
        return f"{self.region}/{self.name}"


@dataclass
class Transition:
    edge_id: str
    edge_type: str
    from_map: int
    from_x: int
    from_y: int
    to_map: int
    to_x: int
    to_y: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def from_key(self) -> tuple[int, int, int]:
        return (self.from_map, self.from_x, self.from_y)

    @property
    def to_key(self) -> tuple[int, int, int]:
        return (self.to_map, self.to_x, self.to_y)


@dataclass
class WorldNavGraph:
    scroll_cost_tiles: int = 10
    hubs: list[Hub] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    map_names: dict[int, str] = field(default_factory=dict)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    source_dir: Path = ROOT
    transitions_source: str = ""

    def map_label(self, map_id: int) -> str:
        return self.map_names.get(map_id, f"map {map_id}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _cell_ok(d: dict[str, Any]) -> bool:
    return d.get("mapId") is not None and d.get("x") is not None and d.get("y") is not None


def _edge_kind(e: dict[str, Any]) -> str:
    return str(e.get("kind") or e.get("type") or "").strip()


def load_transitions_from_map_file(
    path: Path,
    *,
    kinds: frozenset[str] = LIVE_EDGE_KINDS,
) -> tuple[list[Transition], dict[int, str]]:
    """Load user-edited edges (+ map labels) from map_transitions.json."""
    doc = _load_json(path)
    map_names: dict[int, str] = {}
    maps = doc.get("maps") or {}
    if isinstance(maps, dict):
        for _key, m in maps.items():
            if not isinstance(m, dict) or m.get("mapId") is None:
                continue
            mid = int(m["mapId"])
            map_names[mid] = str(m.get("kr") or m.get("en") or mid)
    elif isinstance(maps, list):
        for m in maps:
            if not isinstance(m, dict) or m.get("mapId") is None:
                continue
            mid = int(m["mapId"])
            map_names[mid] = str(m.get("kr") or m.get("en") or mid)

    transitions: list[Transition] = []
    for e in doc.get("edges") or []:
        if not isinstance(e, dict):
            continue
        et = _edge_kind(e)
        if et not in kinds:
            continue
        # Draft rows may omit status; only skip explicit non-ok.
        status = e.get("status")
        if status is not None and status != "ok":
            continue
        if e.get("endpoints_complete") is False:
            continue
        frm, to = e.get("from") or {}, e.get("to") or {}
        if not _cell_ok(frm) or not _cell_ok(to):
            continue
        meta = dict(e.get("meta") or {})
        if e.get("manual_override") or meta.get("manual_override"):
            meta = dict(meta)
            meta["has_manual_override"] = True
        transitions.append(
            Transition(
                edge_id=str(e.get("id") or f"{et}:{frm.get('mapId')}:{to.get('mapId')}"),
                edge_type=et,
                from_map=int(frm["mapId"]),
                from_x=int(frm["x"]),
                from_y=int(frm["y"]),
                to_map=int(to["mapId"]),
                to_x=int(to["x"]),
                to_y=int(to["y"]),
                meta=meta,
            )
        )
    return transitions, map_names


def load_graph(
    manifest_path: Path | None = None,
    providers_dir: Path | None = None,
    map_transitions_path: Path | None = None,
) -> WorldNavGraph:
    """Build the planning graph.

    - Hubs / scroll cost / gaps: ``world_nav`` providers (talking scroll).
    - Map transitions: ``map_transitions.json`` when present (manual edits).
      Falls back to provider edge files only if that file is missing.
    """
    manifest_path = manifest_path or DEFAULT_MANIFEST
    providers_dir = providers_dir or DEFAULT_PROVIDERS
    map_transitions_path = map_transitions_path or DEFAULT_MAP_TRANSITIONS
    manifest = _load_json(manifest_path)
    costs = manifest.get("costs") or {}
    scroll_cost = int(costs.get("talking_scroll_tiles", 10))

    hubs: list[Hub] = []
    transitions: list[Transition] = []
    map_names: dict[int, str] = {}
    gaps: list[dict[str, Any]] = []
    transitions_source = ""

    for entry in manifest.get("providers", []):
        if not entry.get("enabled", True):
            continue
        path = providers_dir / entry["file"]
        if not path.exists():
            continue
        doc = _load_json(path)
        kind = entry.get("kind") or doc.get("kind")

        if kind == "catalog" and "maps" in doc:
            for m in doc["maps"]:
                map_names[int(m["mapId"])] = m.get("kr") or m.get("en") or str(m["mapId"])

        if doc.get("provider_id") == "hubs.talking_scroll" or "hubs" in doc:
            for h in doc.get("hubs", []):
                if h.get("mapId") is None or h.get("x") is None or h.get("y") is None:
                    continue
                hubs.append(
                    Hub(
                        index=int(h["index"]),
                        name=str(h["name"]),
                        region=str(h["region"]),
                        map_id=int(h["mapId"]),
                        x=int(h["x"]),
                        y=int(h["y"]),
                        ui=dict(h.get("ui") or {}),
                    )
                )

        if "gaps" in doc:
            gaps.extend(doc["gaps"])

    if map_transitions_path.is_file():
        transitions, mt_names = load_transitions_from_map_file(map_transitions_path)
        map_names.update(mt_names)
        transitions_source = str(map_transitions_path)
    else:
        # Legacy fallback: provider edge JSON only if map_transitions is absent.
        transitions_source = f"providers:{providers_dir}"
        for entry in manifest.get("providers", []):
            if not entry.get("enabled", True):
                continue
            path = providers_dir / entry["file"]
            if not path.exists():
                continue
            doc = _load_json(path)
            kind = entry.get("kind") or doc.get("kind")
            if kind == "edges" or "edges" in doc:
                if doc.get("provider_id", "").startswith("hubs."):
                    continue
                for e in doc.get("edges", []):
                    if e.get("status") != "ok":
                        continue
                    if e.get("endpoints_complete") is False:
                        continue
                    frm, to = e.get("from") or {}, e.get("to") or {}
                    if not _cell_ok(frm) or not _cell_ok(to):
                        continue
                    et = str(e.get("type") or "")
                    if et not in LIVE_EDGE_KINDS:
                        continue
                    transitions.append(
                        Transition(
                            edge_id=str(e["id"]),
                            edge_type=et,
                            from_map=int(frm["mapId"]),
                            from_x=int(frm["x"]),
                            from_y=int(frm["y"]),
                            to_map=int(to["mapId"]),
                            to_x=int(to["x"]),
                            to_y=int(to["y"]),
                            meta=dict(e.get("meta") or {}),
                        )
                    )

    return WorldNavGraph(
        scroll_cost_tiles=scroll_cost,
        hubs=hubs,
        transitions=transitions,
        map_names=map_names,
        gaps=gaps,
        source_dir=manifest_path.parent,
        transitions_source=transitions_source,
    )
