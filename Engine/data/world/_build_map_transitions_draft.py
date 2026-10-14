"""One-shot draft builder: 10_3 + world_nav -> engine/data/world/*.json

Run: python engine/data/world/_build_map_transitions_draft.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC_10_3 = ROOT / "Extra_data(temporary)" / "10_3_data"
SRC_WN = ROOT / "Extra_data(temporary)" / "world_nav_ready" / "providers"
OUT_DIR = Path(__file__).resolve().parent

KIND_FROM_CATEGORY = {
    "world-dungeon entry/exit": "ground_enter",
    "dungeon floor change": "floor_ladder",
    "dungeon zone link (same floor)": "zone_link",
    "dungeon passage link": "passage",
    "dungeon internal teleport": "interior_teleport",
    "world/building internal teleport": "world_interior",
    "ship transport": "ship",
    "building/interior": "building",
}

# Per-endpoint Manhattan tolerance when pairing world_nav ↔ 10_3.
# TMO vs live measurements often differ by a few tiles on each end.
MATCH_RADIUS_FROM = 8
MATCH_RADIUS_TO = 8


def _i(v):
    if v is None or v == "":
        return None
    return int(v)


def _is_pc_clone(map_id: int) -> bool:
    return map_id >= 7770


def _load_world_nav_maps() -> dict[int, dict]:
    raw = json.loads((SRC_WN / "00_maps.json").read_text(encoding="utf-8"))
    out: dict[int, dict] = {}
    for m in raw["maps"]:
        mid = int(m["mapId"])
        out[mid] = {
            "en": m.get("en"),
            "kr": m.get("kr"),
            "rect": m.get("rect"),
        }
    return out


def _load_10_3_maps() -> list[dict]:
    with open(SRC_10_3 / "maps.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_portals() -> list[dict]:
    with open(SRC_10_3 / "portals_all.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_wn_edges() -> list[dict]:
    edges: list[dict] = []
    for name in ("30_edges_ground_enter.json", "32_edges_floor_ladder.json"):
        raw = json.loads((SRC_WN / name).read_text(encoding="utf-8"))
        for e in raw.get("edges", []):
            if e.get("status") != "ok" or not e.get("endpoints_complete"):
                continue
            edges.append(
                {
                    "id": e["id"],
                    "type": e.get("type"),
                    "from": e["from"],
                    "to": e["to"],
                    "provider": raw.get("provider_id"),
                }
            )
    return edges


def _match_wn(
    wn_edges: list[dict],
    fm: int,
    fx: int,
    fy: int,
    tm: int,
    tx: int,
    ty: int,
):
    best = None
    best_score = None
    for e in wn_edges:
        ef, et = e["from"], e["to"]
        if int(ef["mapId"]) != fm or int(et["mapId"]) != tm:
            continue
        d_from = abs(int(ef["x"]) - fx) + abs(int(ef["y"]) - fy)
        d_to = abs(int(et["x"]) - tx) + abs(int(et["y"]) - ty)
        if d_from > MATCH_RADIUS_FROM or d_to > MATCH_RADIUS_TO:
            continue
        score = d_from + d_to
        if best_score is None or score < best_score:
            best_score = score
            best = {
                "id": e["id"],
                "type": e["type"],
                "provider": e["provider"],
                "from_delta": {
                    "dx": int(ef["x"]) - fx,
                    "dy": int(ef["y"]) - fy,
                    "manhattan": d_from,
                },
                "to_delta": {
                    "dx": int(et["x"]) - tx,
                    "dy": int(et["y"]) - ty,
                    "manhattan": d_to,
                },
                "manhattan_sum": score,
                "world_nav_from": {
                    "mapId": int(ef["mapId"]),
                    "x": int(ef["x"]),
                    "y": int(ef["y"]),
                },
                "world_nav_to": {
                    "mapId": int(et["mapId"]),
                    "x": int(et["x"]),
                    "y": int(et["y"]),
                },
            }
    return best


def build_maps_catalog(rows_10_3: list[dict], wn_maps: dict[int, dict]) -> dict:
    maps: dict[str, dict] = {}
    for r in rows_10_3:
        mid = int(r["map_id"])
        wn = wn_maps.get(mid, {})
        kr = r["name"]
        entry = {
            "mapId": mid,
            "kr": kr,
            "en": wn.get("en"),
            "complex": r.get("complex") or None,
            "floor": _i(r.get("floor")),
            "is_dungeon": str(r.get("is_dungeon", "")).lower() == "true",
            "pc_clone": _is_pc_clone(mid),
            "rect": {
                "x0": int(r["min_x"]),
                "y0": int(r["min_y"]),
                "x1": int(r["max_x"]),
                "y1": int(r["max_y"]),
            },
            "portal_count": int(r.get("portal_count") or 0),
            "region_count": int(r.get("region_count") or 0),
            "sources": {
                "tmo_10_3": True,
                "world_nav_00_maps": mid in wn_maps,
            },
        }
        if wn.get("rect"):
            entry["rect_world_nav"] = wn["rect"]
            if wn.get("kr") and wn["kr"] != kr:
                entry["kr_world_nav"] = wn["kr"]
        maps[str(mid)] = entry

    for mid, wn in wn_maps.items():
        if str(mid) in maps:
            continue
        maps[str(mid)] = {
            "mapId": mid,
            "kr": wn.get("kr"),
            "en": wn.get("en"),
            "complex": None,
            "floor": None,
            "is_dungeon": None,
            "pc_clone": _is_pc_clone(mid),
            "rect": wn.get("rect"),
            "portal_count": None,
            "region_count": None,
            "sources": {"tmo_10_3": False, "world_nav_00_maps": True},
        }
    return maps


def build_edges(
    portals: list[dict],
    maps: dict[str, dict],
    wn_edges: list[dict],
) -> tuple[list[dict], list[dict]]:
    edges: list[dict] = []
    edges_pc: list[dict] = []
    used_ids: set[str] = set()

    for r in portals:
        fm = int(r["source_map_id"])
        tm = int(r["target_map_id"])
        fx, fy = int(r["source_x"]), int(r["source_y"])
        tx, ty = int(r["target_x"]), int(r["target_y"])
        category = r["category"]
        kind = KIND_FROM_CATEGORY.get(category, "other")
        portal_id = r["portal_id"]
        edge_id = f"tmo:{portal_id}"
        if edge_id in used_ids:
            edge_id = f"tmo:{portal_id}:{fx},{fy}->{tx},{ty}"
        used_ids.add(edge_id)

        fm_info = maps.get(str(fm), {})
        tm_info = maps.get(str(tm), {})
        wn_match = _match_wn(wn_edges, fm, fx, fy, tm, tx, ty)

        edge = {
            "id": edge_id,
            "kind": kind,
            "cross_map": fm != tm,
            "from": {
                "mapId": fm,
                "x": fx,
                "y": fy,
                "kr": fm_info.get("kr") or r["source_map"],
                "en": fm_info.get("en"),
                "complex": fm_info.get("complex"),
                "floor": (
                    _i(r.get("source_floor"))
                    if r.get("source_floor") not in (None, "")
                    else fm_info.get("floor")
                ),
            },
            "to": {
                "mapId": tm,
                "x": tx,
                "y": ty,
                "kr": tm_info.get("kr") or r["target_map"],
                "en": tm_info.get("en"),
                "complex": tm_info.get("complex"),
                "floor": (
                    _i(r.get("target_floor"))
                    if r.get("target_floor") not in (None, "")
                    else tm_info.get("floor")
                ),
                "region": r.get("target_region") or None,
            },
            "bidirectional": False,
            "meta": {
                "portal_id": portal_id,
                "portal_name": r.get("portal_name") or None,
                "category": category,
                "source": "10_3_data/portals_all.csv",
                "pc_clone": _is_pc_clone(fm) or _is_pc_clone(tm),
                "world_nav_match": wn_match,
            },
        }
        if edge["meta"]["pc_clone"]:
            edges_pc.append(edge)
        else:
            edges.append(edge)

    matched_wn_ids = {
        e["meta"]["world_nav_match"]["id"]
        for e in edges + edges_pc
        if e["meta"].get("world_nav_match")
    }
    for we in wn_edges:
        if we["id"] in matched_wn_ids:
            continue
        fm = int(we["from"]["mapId"])
        tm = int(we["to"]["mapId"])
        fx, fy = int(we["from"]["x"]), int(we["from"]["y"])
        tx, ty = int(we["to"]["x"]), int(we["to"]["y"])
        fm_info = maps.get(str(fm), {})
        tm_info = maps.get(str(tm), {})
        kind = we.get("type") or "ground_enter"
        edge = {
            "id": f"world_nav:{we['id']}",
            "kind": kind,
            "cross_map": fm != tm,
            "from": {
                "mapId": fm,
                "x": fx,
                "y": fy,
                "kr": fm_info.get("kr"),
                "en": fm_info.get("en"),
                "complex": fm_info.get("complex"),
                "floor": fm_info.get("floor"),
            },
            "to": {
                "mapId": tm,
                "x": tx,
                "y": ty,
                "kr": tm_info.get("kr"),
                "en": tm_info.get("en"),
                "complex": tm_info.get("complex"),
                "floor": tm_info.get("floor"),
                "region": None,
            },
            "bidirectional": False,
            "meta": {
                "portal_id": None,
                "portal_name": we["id"],
                "category": f"world_nav:{kind}",
                "source": f"world_nav_ready/providers ({we['provider']})",
                "pc_clone": _is_pc_clone(fm) or _is_pc_clone(tm),
                "world_nav_match": {
                    "id": we["id"],
                    "type": kind,
                    "provider": we["provider"],
                    "from_delta": {"dx": 0, "dy": 0},
                    "to_delta": {"dx": 0, "dy": 0},
                    "manhattan_sum": 0,
                    "note": (
                        "no 10_3 portal within match radius; "
                        "kept as world_nav-only draft edge"
                    ),
                },
            },
        }
        if edge["meta"]["pc_clone"]:
            edges_pc.append(edge)
        else:
            edges.append(edge)

    return edges, edges_pc


def build_review(edges: list[dict]) -> dict:
    """Flag map-pairs where 10_3 and world_nav disagree (debug aid)."""
    by_pair_src: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"tmo": [], "world_nav": []}
    )
    for e in edges:
        pair = f"{e['from']['mapId']}->{e['to']['mapId']}"
        if e["id"].startswith("tmo:"):
            by_pair_src[pair]["tmo"].append(e["id"])
        elif e["id"].startswith("world_nav:"):
            by_pair_src[pair]["world_nav"].append(e["id"])

    conflicts = []
    for pair, buckets in sorted(by_pair_src.items()):
        if buckets["tmo"] and buckets["world_nav"]:
            conflicts.append(
                {
                    "pair": pair,
                    "tmo_ids": buckets["tmo"],
                    "world_nav_ids": buckets["world_nav"],
                    "note": (
                        "Same mapId pair has both TMO and unmatched world_nav edges; "
                        "compare from/to cells before promoting to production."
                    ),
                }
            )

    wn_only = [e["id"] for e in edges if e["id"].startswith("world_nav:")]
    tmo_matched = [
        e["id"]
        for e in edges
        if e["id"].startswith("tmo:") and e["meta"].get("world_nav_match")
    ]
    return {
        "match_radius_from": MATCH_RADIUS_FROM,
        "match_radius_to": MATCH_RADIUS_TO,
        "tmo_edges_matched_to_world_nav": tmo_matched,
        "world_nav_only_unmatched_ids": wn_only,
        "map_pairs_with_tmo_and_world_nav": conflicts,
    }


def build_index(edges: list[dict]) -> dict:
    by_from: dict[str, list[str]] = defaultdict(list)
    by_to: dict[str, list[str]] = defaultdict(list)
    by_kind: dict[str, list[str]] = defaultdict(list)
    by_complex: dict[str, list[str]] = defaultdict(list)
    by_pair: dict[str, list[str]] = defaultdict(list)
    cross: list[str] = []
    same: list[str] = []
    wn_verified: list[str] = []

    for e in edges:
        eid = e["id"]
        fm = str(e["from"]["mapId"])
        tm = str(e["to"]["mapId"])
        by_from[fm].append(eid)
        by_to[tm].append(eid)
        by_kind[e["kind"]].append(eid)
        by_pair[f"{fm}->{tm}"].append(eid)
        fc = e["from"].get("complex") or "_none"
        tc = e["to"].get("complex") or "_none"
        by_complex[fc].append(eid)
        if tc != fc:
            by_complex[tc].append(eid)
        if e["cross_map"]:
            cross.append(eid)
        else:
            same.append(eid)
        if e["meta"].get("world_nav_match"):
            wn_verified.append(eid)

    return {
        "by_from_mapId": dict(sorted(by_from.items(), key=lambda kv: int(kv[0]))),
        "by_to_mapId": dict(sorted(by_to.items(), key=lambda kv: int(kv[0]))),
        "by_map_pair": dict(sorted(by_pair.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "by_complex": dict(sorted(by_complex.items())),
        "cross_map_ids": cross,
        "same_map_ids": same,
        "world_nav_matched_ids": wn_verified,
    }


def main() -> None:
    wn_maps = _load_world_nav_maps()
    rows_10_3 = _load_10_3_maps()
    portals = _load_portals()
    wn_edges = _load_wn_edges()

    maps = build_maps_catalog(rows_10_3, wn_maps)
    edges, edges_pc = build_edges(portals, maps, wn_edges)
    index = build_index(edges)
    review = build_review(edges)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    transitions = {
        "schema_version": 1,
        "kind": "map_transitions",
        "status": "draft",
        "generated_at": now,
        "note": (
            "Draft map-transition graph. Primary geometry from TMO 10_3 portals_all.csv; "
            "map names/en enriched from world_nav 00_maps.json; world_nav ground_enter/"
            "floor_ladder ok-edges attached as world_nav_match (or world_nav-only rows). "
            "PC-clone maps (mapId>=7770) are excluded from edges[] and listed in "
            "edges_pc_clone[]. Not yet wired into the production bot loader. "
            "See review{} for TMO vs world_nav coordinate conflicts."
        ),
        "sources": [
            {
                "id": "10_3_portals",
                "path": "Extra_data(temporary)/10_3_data/portals_all.csv",
                "role": "primary_edges",
            },
            {
                "id": "10_3_maps",
                "path": "Extra_data(temporary)/10_3_data/maps.csv",
                "role": "map_catalog_kr_rect",
            },
            {
                "id": "world_nav_maps",
                "path": "Extra_data(temporary)/world_nav_ready/providers/00_maps.json",
                "role": "map_catalog_en_enrich",
            },
            {
                "id": "world_nav_ground_enter",
                "path": (
                    "Extra_data(temporary)/world_nav_ready/providers/"
                    "30_edges_ground_enter.json"
                ),
                "role": "verify_and_gap_fill",
            },
            {
                "id": "world_nav_floor_ladder",
                "path": (
                    "Extra_data(temporary)/world_nav_ready/providers/"
                    "32_edges_floor_ladder.json"
                ),
                "role": "verify_and_gap_fill",
            },
        ],
        "counts": {
            "maps": len(maps),
            "edges": len(edges),
            "edges_pc_clone": len(edges_pc),
            "cross_map": len(index["cross_map_ids"]),
            "same_map": len(index["same_map_ids"]),
            "world_nav_matched": len(review["tmo_edges_matched_to_world_nav"]),
            "world_nav_only": len(review["world_nav_only_unmatched_ids"]),
            "coord_conflict_pairs": len(review["map_pairs_with_tmo_and_world_nav"]),
            "by_kind": {k: len(v) for k, v in index["by_kind"].items()},
        },
        "maps": dict(sorted(maps.items(), key=lambda kv: int(kv[0]))),
        "edges": edges,
        "edges_pc_clone": edges_pc,
        "index": index,
        "review": review,
    }

    catalog = {
        "schema_version": 1,
        "kind": "maps_catalog",
        "status": "draft",
        "generated_at": now,
        "note": (
            "Sibling index of mapId -> names/rect. "
            "Same maps object as map_transitions.json."
        ),
        "count": len(maps),
        "maps": transitions["maps"],
    }

    out_t = OUT_DIR / "map_transitions.json"
    out_c = OUT_DIR / "maps_catalog.json"
    out_t.write_text(
        json.dumps(transitions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    out_c.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("wrote", out_t, "bytes", out_t.stat().st_size)
    print("wrote", out_c, "bytes", out_c.stat().st_size)
    print("counts", json.dumps(transitions["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
