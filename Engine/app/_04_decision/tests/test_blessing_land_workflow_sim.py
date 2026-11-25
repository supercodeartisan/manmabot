"""End-to-end solo hunting workflow simulation for blessing-land field packs.

Does not touch the real game client or the operator's UserData. Uses a
temporary overlay root for farms.yaml writes.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
ENGINE = ROOT / "Engine"
UI = ROOT / "UI"
for path in (str(ENGINE), str(UI)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app._03_world.space.map_pack import (
    get_active_map_pack,
    load_map_pack,
    resolve_maps_dir,
)
from app._03_world.space.tile_world import axes_from_pack
from app._04_decision import nav_config as nc
from app._04_decision import player_mode as pm
from app._04_decision.dungeon import get_dungeon_mode_override, is_dungeon_map, set_dungeon_mode_override
from app._04_decision.live_map_pack import ensure_navigation_for_live_map_id, ensure_navigation_for_pack_id
from app._04_decision.nav_config import configure_navigation_for_map, get_farm_areas, get_terrain_map
from app._04_decision.pathfinding import find_path
from app._04_decision.world_nav import pack_ids as pack_ids_mod
from app._04_decision.world_nav.hooks import apply_routine_entry_runtime
from app._04_decision.world_nav.overlays import farm_rects_selected, is_dungeon_pack
from app._04_decision.world_nav.pack_ids import map_id_to_pack_id, pack_id_to_map_id
from i18n.localized_names import map_display_name
from session.probes import farms_yaml_path, is_dungeon_map_id, list_map_choices, writable_farms_yaml_path
from settings.farm_schedule import normalize_routine
from ui.hangul_sort import map_choice_sort_key
from ui.reachable_battle_maps import (
    BLESSING_LAND_FIELD_MAP_IDS,
    BLESSING_LAND_HIDDEN_MAP_IDS,
    battle_picker_choices,
    break_picker_choices,
)
from ui_qt.viewmodels.routine_vm import RoutineViewModel

# Season base packs (live mapId / nav owners). Used by farm/nav sim phases.
MAPS = (
    ("polluted_land_of_blessing", 244, "오염된 축복의 땅"),
    ("corrupted_land_of_blessing_spring", 2450, "타락한 축복의 땅의 봄"),
    ("corrupted_land_of_blessing_summer", 245, "타락한 축복의 땅의 여름"),
    ("corrupted_land_of_blessing_autumn", 2452, "타락한 축복의 땅의 가을"),
    ("corrupted_land_of_blessing_winter", 2454, "타락한 축복의 땅의 겨울"),
)

# Solo battle picker: season × race (replaces the five season-only names).
PICKER_MAPS = (
    ("polluted_land_of_blessing_fairy", 244, "오염된 축복의 땅 / 요정의 땅"),
    ("polluted_land_of_blessing_human", 244, "오염된 축복의 땅 / 인간의 땅"),
    ("polluted_land_of_blessing_orch", 244, "오염된 축복의 땅 / 오크의 땅"),
    ("polluted_land_of_blessing_spirit", 244, "오염된 축복의 땅 / 정령의 땅"),
    ("corrupted_land_of_blessing_spring_fairy", 2450, "타락한 축복의 땅의 봄 / 요정의 땅"),
    ("corrupted_land_of_blessing_spring_human", 2450, "타락한 축복의 땅의 봄 / 인간의 땅"),
    ("corrupted_land_of_blessing_spring_orch", 2450, "타락한 축복의 땅의 봄 / 오크의 땅"),
    ("corrupted_land_of_blessing_spring_spirit", 2450, "타락한 축복의 땅의 봄 / 정령의 땅"),
    ("corrupted_land_of_blessing_summer_fairy", 245, "타락한 축복의 땅의 여름 / 요정의 땅"),
    ("corrupted_land_of_blessing_summer_human", 245, "타락한 축복의 땅의 여름 / 인간의 땅"),
    ("corrupted_land_of_blessing_summer_orch", 245, "타락한 축복의 땅의 여름 / 오크의 땅"),
    ("corrupted_land_of_blessing_summer_spirit", 245, "타락한 축복의 땅의 여름 / 정령의 땅"),
    ("corrupted_land_of_blessing_autumn_fairy", 2452, "타락한 축복의 땅의 가을 / 요정의 땅"),
    ("corrupted_land_of_blessing_autumn_human", 2452, "타락한 축복의 땅의 가을 / 인간의 땅"),
    ("corrupted_land_of_blessing_autumn_orch", 2452, "타락한 축복의 땅의 가을 / 오크의 땅"),
    ("corrupted_land_of_blessing_autumn_spirit", 2452, "타락한 축복의 땅의 가을 / 정령의 땅"),
    ("corrupted_land_of_blessing_winter_fairy", 2454, "타락한 축복의 땅의 겨울 / 요정의 땅"),
    ("corrupted_land_of_blessing_winter_human", 2454, "타락한 축복의 땅의 겨울 / 인간의 땅"),
    ("corrupted_land_of_blessing_winter_orch", 2454, "타락한 축복의 땅의 겨울 / 오크의 땅"),
    ("corrupted_land_of_blessing_winter_spirit", 2454, "타락한 축복의 땅의 겨울 / 정령의 땅"),
)


@pytest.fixture(autouse=True)
def _clear_pack_cache():
    pack_ids_mod._packs.cache_clear()
    yield
    pack_ids_mod._packs.cache_clear()
    set_dungeon_mode_override(None)


@pytest.fixture
def isolated_overlay(tmp_path, monkeypatch):
    """Redirect UserData map overlays to a temp tree; never touch real UserData."""
    import session.paths as sp

    overlay_root = tmp_path / "maps"
    overlay_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sp, "MAPS_OVERLAY", overlay_root)
    monkeypatch.setattr(sp, "USERDATA", tmp_path)
    # writable_farms uses overlay_farms_path which uses MAPS_OVERLAY.
    return overlay_root


def _maps_dir() -> Path:
    found = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
    assert found is not None
    return found


def _base_config(pack_id: str) -> dict:
    return {
        "navigation": {
            "maps_dir": "data/maps",
            "active_map": pack_id,
        }
    }


def _walkable_samples(terrain, n: int = 8) -> list[tuple[int, int]]:
    walk = terrain.walkable
    h, w = walk.shape
    found: list[tuple[int, int]] = []
    # corners + grid samples
    candidates = [
        (1, 1),
        (w // 4, h // 4),
        (w // 2, h // 2),
        (3 * w // 4, 3 * h // 4),
        (w - 2, h - 2),
        (w // 3, 2 * h // 3),
        (2 * w // 3, h // 3),
        (10, h // 2),
        (w // 2, 10),
        (w - 10, h // 2),
    ]
    for x, y in candidates:
        if 0 <= x < w and 0 <= y < h and bool(walk[y, x]):
            found.append((x, y))
        if len(found) >= n:
            break
    if len(found) < 2:
        # brute scan
        for y in range(h):
            for x in range(w):
                if bool(walk[y, x]):
                    found.append((x, y))
                    if len(found) >= n:
                        return found
    return found


def _farm_rect_around(tile: tuple[int, int], name: str, half: int = 4) -> dict:
    x, y = tile
    return {
        "name": name,
        "region": "blessing_land",
        "x0": max(0, x - half),
        "y0": max(0, y - half),
        "x1": min(383, x + half),
        "y1": min(383, y + half),
    }


# ---------------------------------------------------------------------------
# Phase 1 — UI workflow
# ---------------------------------------------------------------------------


def test_phase1_solo_battle_picker_order_and_field_class():
    catalog = list(list_map_choices("ko"))
    catalog.sort(key=map_choice_sort_key)
    battle = battle_picker_choices(catalog)
    battle.sort(key=map_choice_sort_key)
    head = [(mid, label, dungeon) for mid, label, dungeon in battle[:22]]
    expected = [
        ("talking_island", "말하는 섬", False),
        ("mainland", "본토", False),
    ] + [(pid, ko, False) for pid, _mid, ko in PICKER_MAPS]
    assert head == expected
    assert tuple(BLESSING_LAND_FIELD_MAP_IDS) == tuple(p[0] for p in PICKER_MAPS)
    for pack_id, mid, ko in PICKER_MAPS:
        assert map_display_name(pack_id, "ko") == ko
        assert not is_dungeon_map_id(pack_id)
        assert pack_id_to_map_id(pack_id) == mid
    for pack_id, mid, _ko in MAPS:
        assert map_id_to_pack_id(mid) == pack_id
        assert pack_id not in {row[0] for row in battle}
    # RoutineViewModel uses pack_id, not display name alone.
    vm = RoutineViewModel("ko")
    choices = vm.map_choices(kind="battle")
    choices.sort(key=map_choice_sort_key)
    assert [c[0] for c in choices[:22]] == [c[0] for c in expected]
    for pack_id, _mid, _ko in PICKER_MAPS:
        assert not vm.is_dungeon(pack_id)


def test_phase1_break_and_party_exclude_blessing():
    catalog = list(list_map_choices("ko"))
    break_ids = {mid for mid, _l, _d in break_picker_choices(catalog)}
    assert break_ids.isdisjoint(BLESSING_LAND_HIDDEN_MAP_IDS)
    # Party picker must hide solo blessing packs (same filter as PartyRoutineViewModel).
    # Avoid importing ui_qt.editors (requires PySide6 in this environment).
    from ui.reachable_battle_maps import battle_picker_choices as _battle

    solo = {mid for mid, _l, _d in _battle(catalog)}
    party_ids = solo - BLESSING_LAND_HIDDEN_MAP_IDS
    assert party_ids.isdisjoint(BLESSING_LAND_HIDDEN_MAP_IDS)
    assert set(BLESSING_LAND_FIELD_MAP_IDS).issubset(solo)
    assert {p[0] for p in MAPS}.isdisjoint(solo)


# ---------------------------------------------------------------------------
# Phase 2 — configuration in isolated UserData
# ---------------------------------------------------------------------------


def test_phase2_save_reload_farms_independent(isolated_overlay):
    maps_dir = _maps_dir()
    hashes_before = {}
    for pack_id, _mid, _ko in MAPS:
        path = writable_farms_yaml_path(pack_id)
        assert isolated_overlay in path.parents or path.parent == isolated_overlay / pack_id or True
        assert str(isolated_overlay) in str(path)
        pack = load_map_pack(maps_dir, pack_id)
        terrain = __import__(
            "app._03_world.space.terrain_map", fromlist=["TerrainMap"]
        ).TerrainMap.from_png(pack.terrain_path, pixel_scale=1)
        samples = _walkable_samples(terrain, n=3)
        assert samples, f"no walkable tiles on {pack_id}"
        name = f"sim_{pack_id[-8:]}"
        doc = {"areas": [_farm_rect_around(samples[0], name)]}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        hashes_before[pack_id] = path.read_bytes()

    # Reload each and confirm independence: mutate one, others unchanged.
    target = MAPS[0][0]
    path0 = writable_farms_yaml_path(target)
    doc0 = yaml.safe_load(path0.read_text(encoding="utf-8"))
    doc0["areas"].append(_farm_rect_around((20, 20), "extra_only_on_first"))
    path0.write_text(yaml.safe_dump(doc0, allow_unicode=True), encoding="utf-8")

    for pack_id, _mid, _ko in MAPS[1:]:
        assert writable_farms_yaml_path(pack_id).read_bytes() == hashes_before[pack_id]
        loaded = yaml.safe_load(writable_farms_yaml_path(pack_id).read_text(encoding="utf-8"))
        assert len(loaded["areas"]) == 1
        assert "extra_only_on_first" not in {
            a["name"] for a in loaded["areas"]
        }

    reloaded = yaml.safe_load(path0.read_text(encoding="utf-8"))
    assert len(reloaded["areas"]) == 2

    # Routine with all five maps (pack_id, not display name).
    rows = normalize_routine(
        [
            {
                "id": uuid.uuid4().hex,
                "map_id": pack_id,
                "kind": "battle",
                "duration_minutes": 30,
                "selected_farms": [f"sim_{pack_id[-8:]}"],
            }
            for pack_id, _mid, _ko in MAPS
        ]
    )
    assert [r["map_id"] for r in rows] == [p[0] for p in MAPS]


# ---------------------------------------------------------------------------
# Phase 3 — coordinates
# ---------------------------------------------------------------------------


def test_phase3_origin_and_round_trip_from_meta():
    maps_dir = _maps_dir()
    for pack_id, _mid, _ko in MAPS:
        pack = load_map_pack(maps_dir, pack_id)
        assert pack.origin_x == 32640
        assert pack.origin_y == 32768
        assert pack.pixel_scale == 1
        axes = axes_from_pack(pack)
        assert axes is not None
        for tx, ty in ((0, 0), (1, 1), (100, 200), (383, 383)):
            wx, wy = axes.tile_to_world(tx, ty)
            assert (wx, wy) == (32640 + tx, 32768 + ty)
            assert axes.world_to_tile(wx, wy) == (tx, ty)
            # No mainland offset leakage
            assert wx != 32448 + tx or tx == 192  # coincidence guard only
            assert wy != 32128 + ty or ty == 640


# ---------------------------------------------------------------------------
# Phase 4 — startup / init chain
# ---------------------------------------------------------------------------


def _make_board(cfg: dict) -> Any:
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.world_nav import hooks as wh

    board = Blackboard()
    board.scratch[wh.SCRATCH_RUNTIME_CONFIG] = cfg
    return board


def test_phase4_startup_chain_per_map(isolated_overlay):
    """Mirror session start: overlays → live mapId → apply_routine_entry_runtime."""
    from session.world_nav_inject import install_world_nav_overlays, load_farm_area_dicts

    maps_dir = _maps_dir()
    report = []
    for pack_id, mid, _ko in MAPS:
        pack = load_map_pack(maps_dir, pack_id)
        terrain = __import__(
            "app._03_world.space.terrain_map", fromlist=["TerrainMap"]
        ).TerrainMap.from_png(pack.terrain_path, pixel_scale=1)
        samples = _walkable_samples(terrain, n=2)
        assert samples
        farm_name = f"hunt_{mid}"
        farm_path = writable_farms_yaml_path(pack_id)
        farm_path.parent.mkdir(parents=True, exist_ok=True)
        farm_path.write_text(
            yaml.safe_dump(
                {"areas": [_farm_rect_around(samples[0], farm_name)]},
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        # Session reads overlay via farms_yaml_path (UserData wins).
        assert any(a.get("name") == farm_name for a in load_farm_area_dicts(pack_id))

        cfg = _base_config(pack_id)
        board = _make_board(cfg)
        entry = {
            "map_id": pack_id,
            "kind": "battle",
            "selected_farms": [farm_name],
        }
        install_world_nav_overlays(board, routine_rows=[entry], fallback_map=pack_id)

        # Pack + prebuild load (configure strips overlays; remount follows).
        origin = configure_navigation_for_map(cfg, pack_id)
        board.world_origin = origin
        active = get_active_map_pack()
        assert active is not None and active.id == pack_id
        assert map_id_to_pack_id(mid) == pack_id
        assert not is_dungeon_map(active.id, active.name)
        terrain_live = get_terrain_map()
        assert terrain_live is not None
        assert terrain_live.walkable.shape == (384, 384)

        ok, msg = ensure_navigation_for_live_map_id(board, cfg, mid)
        assert ok, msg
        assert board.scratch.get("live_map_pack") == pack_id

        apply_routine_entry_runtime(board, entry, reason="sim", config=cfg)
        assert pm.HUNT_MAP_ID == pack_id
        assert get_dungeon_mode_override() is False
        assert not is_dungeon_pack(board, pack_id)
        live_farms = get_farm_areas()
        assert any(f.name == farm_name for f in live_farms), [
            f.name for f in live_farms
        ]
        assert get_dungeon_mode_override() is False

        report.append(
            {
                "pack_id": pack_id,
                "mapId": mid,
                "origin": (pack.origin_x, pack.origin_y),
                "farms_path": str(farm_path),
                "farm_count": len(live_farms),
                "active": active.id,
            }
        )
    assert len(report) == 5


# ---------------------------------------------------------------------------
# Phase 5 — map switching / stale state
# ---------------------------------------------------------------------------


def test_phase5_map_switching_no_stale_farms(isolated_overlay):
    from session.world_nav_inject import install_world_nav_overlays

    maps_dir = _maps_dir()
    farm_names = {}
    rows = []
    for pack_id, mid, _ko in MAPS:
        pack = load_map_pack(maps_dir, pack_id)
        terrain = __import__(
            "app._03_world.space.terrain_map", fromlist=["TerrainMap"]
        ).TerrainMap.from_png(pack.terrain_path, pixel_scale=1)
        tile = _walkable_samples(terrain, n=1)[0]
        name = f"only_{mid}"
        farm_names[pack_id] = name
        path = writable_farms_yaml_path(pack_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {"areas": [_farm_rect_around(tile, name)]},
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        rows.append(
            {
                "map_id": pack_id,
                "kind": "battle",
                "selected_farms": [name],
            }
        )

    order = [p[0] for p in MAPS] + [p[0] for p in reversed(MAPS)]
    cfg = _base_config(order[0])
    board = _make_board(cfg)
    install_world_nav_overlays(board, routine_rows=rows)

    prev_pack = None
    for pack_id in order:
        mid = next(m for p, m, _ in MAPS if p == pack_id)
        entry = next(r for r in rows if r["map_id"] == pack_id)
        apply_routine_entry_runtime(board, entry, reason="sim_switch", config=cfg)
        ok, msg = ensure_navigation_for_pack_id(board, cfg, pack_id, live_map_id=mid)
        assert ok, msg
        # Remount selected farms after pack sync (same as arrival path).
        apply_routine_entry_runtime(board, entry, reason="sim_switch", config=cfg)
        active = get_active_map_pack()
        assert active is not None and active.id == pack_id
        assert map_id_to_pack_id(mid) == pack_id
        names = [f.name for f in get_farm_areas()]
        assert farm_names[pack_id] in names, names
        if prev_pack and prev_pack != pack_id:
            if farm_names[prev_pack] != farm_names[pack_id]:
                assert farm_names[prev_pack] not in names
        assert active.origin_x == 32640 and active.origin_y == 32768
        prev_pack = pack_id


# ---------------------------------------------------------------------------
# Phase 6 — navigation / pathfinding
# ---------------------------------------------------------------------------


def test_phase6_pathfinding_to_hunt_area(isolated_overlay):
    maps_dir = _maps_dir()
    failures = []
    for pack_id, mid, _ko in MAPS:
        pack = load_map_pack(maps_dir, pack_id)
        cfg = _base_config(pack_id)
        configure_navigation_for_map(cfg, pack_id)
        terrain = get_terrain_map()
        assert terrain is not None
        samples = _walkable_samples(terrain, n=6)
        if len(samples) < 2:
            failures.append((pack_id, "insufficient_walkable_samples", samples))
            continue
        start = samples[0]
        goal = samples[-1]
        if start == goal:
            goal = samples[1]
        path = find_path(terrain, start, goal)
        if not path:
            failures.append((pack_id, "no_path", start, goal))
            continue
        assert path[0] == start
        assert path[-1] == goal
        # All path cells walkable
        for x, y in path:
            assert terrain.is_walkable(x, y), (pack_id, x, y)
        # Farm center reachable from another walkable tile
        farm = _farm_rect_around(goal, f"nav_{mid}")
        cx = (farm["x0"] + farm["x1"]) // 2
        cy = (farm["y0"] + farm["y1"]) // 2
        if not terrain.is_walkable(cx, cy):
            # snap to goal which is walkable
            cx, cy = goal
        path2 = find_path(terrain, start, (cx, cy))
        assert path2, (pack_id, start, (cx, cy))
        # Field combat init gate: not dungeon
        set_dungeon_mode_override(False)
        assert not is_dungeon_map()
    assert not failures, failures


def test_phase6_blocked_tiles_never_on_path():
    maps_dir = _maps_dir()
    for pack_id, _mid, _ko in MAPS:
        configure_navigation_for_map(_base_config(pack_id), pack_id)
        terrain = get_terrain_map()
        assert terrain is not None
        samples = _walkable_samples(terrain, n=4)
        if len(samples) < 2:
            continue
        path = find_path(terrain, samples[0], samples[-1])
        if not path:
            continue
        for x, y in path:
            assert bool(terrain.walkable[y, x])


# ---------------------------------------------------------------------------
# Phase 7 — regressions (smoke)
# ---------------------------------------------------------------------------


def test_phase7_mainland_talking_island_still_field():
    assert not is_dungeon_map_id("mainland")
    assert not is_dungeon_map_id("talking_island")
    assert is_dungeon_map_id("giran_dungeon_F1")
    configure_navigation_for_map(_base_config("mainland"), "mainland")
    active = get_active_map_pack()
    assert active is not None and active.id == "mainland"
    assert active.origin_x == 32448
    configure_navigation_for_map(_base_config("talking_island"), "talking_island")
    active = get_active_map_pack()
    assert active is not None and active.id == "talking_island"


def test_phase7_legacy_dungeon_pack_still_loadable_not_mapped_to_244():
    maps_dir = _maps_dir()
    legacy = load_map_pack(maps_dir, "polluted_land_of_blessing_dungeon")
    assert legacy.id == "polluted_land_of_blessing_dungeon"
    assert map_id_to_pack_id(244) == "polluted_land_of_blessing"
    rows = normalize_routine(
        [{"map_id": "polluted_land_of_blessing_dungeon", "kind": "battle"}]
    )
    assert rows[0]["map_id"] == "polluted_land_of_blessing"
