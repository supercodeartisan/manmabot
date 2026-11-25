"""Blessing-land field packs: mapId mapping, coords, field mode, farms."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
ENGINE = ROOT / "Engine"
UI = ROOT / "UI"
for path in (ENGINE, UI, str(ENGINE)):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from app._03_world.space.map_pack import load_map_pack, resolve_maps_dir
from app._03_world.space.terrain_map import TerrainMap
from app._03_world.space.tile_world import axes_from_pack
from app._04_decision.dungeon import is_dungeon_map
from app._04_decision.world_nav import pack_ids as pack_ids_mod
from app._04_decision.world_nav.pack_ids import map_id_to_pack_id, pack_id_to_map_id
from app._04_decision.world_nav.ready.map_assets import discover_map_packs

pack_ids_mod._packs.cache_clear()
from i18n.localized_names import map_display_name
from session.probes import list_map_choices
from settings.farm_schedule import normalize_routine
from ui.hangul_sort import map_choice_sort_key
from ui.reachable_battle_maps import (
    BLESSING_LAND_FIELD_MAP_IDS,
    BLESSING_LAND_HIDDEN_MAP_IDS,
    battle_picker_choices,
    break_picker_choices,
)

# Season base packs own live mapId / nav_prebuild.
BASE_EXPECTED = (
    ("polluted_land_of_blessing", 244, "오염된 축복의 땅"),
    ("corrupted_land_of_blessing_spring", 2450, "타락한 축복의 땅의 봄"),
    ("corrupted_land_of_blessing_summer", 245, "타락한 축복의 땅의 여름"),
    ("corrupted_land_of_blessing_autumn", 2452, "타락한 축복의 땅의 가을"),
    ("corrupted_land_of_blessing_winter", 2454, "타락한 축복의 땅의 겨울"),
)

# Solo battle picker: season × race.
PICKER_EXPECTED = (
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
ORIGIN = (32640, 32768)
SIZE = (384, 384)


def _maps_dir() -> Path:
    found = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
    assert found is not None
    return found


def test_five_field_packs_exist_with_unique_raw_maps() -> None:
    maps_dir = _maps_dir()
    by_raw: dict[int, str] = {}
    for pack_id, mid, _ko in BASE_EXPECTED:
        pack = load_map_pack(maps_dir, pack_id)
        assert pack.id == pack_id
        assert (pack.root / "nav.png").is_file()
        assert (pack.root / "farms.yaml").is_file()
        assert (pack.root / "nav_prebuild" / "meta.json").is_file()
        assert pack.origin_x == ORIGIN[0]
        assert pack.origin_y == ORIGIN[1]
        assert pack.pixel_scale == 1
        assert not is_dungeon_map(pack.id, pack.name)
        assert mid not in by_raw
        by_raw[mid] = pack_id
    for mid, pack_id in by_raw.items():
        assert map_id_to_pack_id(mid) == pack_id
    owner_ids = {pack_id for pack_id in by_raw.values()}
    discovered_owners = {
        p.pack_id for p in discover_map_packs() if p.pack_id in owner_ids
    }
    assert discovered_owners == owner_ids


def test_map_id_to_pack_id_is_unique_and_correct() -> None:
    for pack_id, mid, _ko in BASE_EXPECTED:
        assert map_id_to_pack_id(mid) == pack_id
        assert pack_id_to_map_id(pack_id) == mid
    # Legacy dungeon pack no longer owns 244.
    assert map_id_to_pack_id(244) == "polluted_land_of_blessing"
    packs_244 = [p for p in discover_map_packs() if int(p.map_id) == 244]
    assert any(p.pack_id == "polluted_land_of_blessing" for p in packs_244)
    # Base + four race variants share live mapId 244.
    assert len(packs_244) >= 5
    for pack_id, mid, _ko in PICKER_EXPECTED:
        assert pack_id_to_map_id(pack_id) == mid
        assert map_id_to_pack_id(mid) == {
            244: "polluted_land_of_blessing",
            2450: "corrupted_land_of_blessing_spring",
            245: "corrupted_land_of_blessing_summer",
            2452: "corrupted_land_of_blessing_autumn",
            2454: "corrupted_land_of_blessing_winter",
        }[mid]


def test_coordinate_round_trip() -> None:
    maps_dir = _maps_dir()
    for pack_id, _mid, _ko in BASE_EXPECTED:
        pack = load_map_pack(maps_dir, pack_id)
        axes = axes_from_pack(pack)
        assert axes is not None
        for tx, ty in ((0, 0), (100, 50), (383, 383)):
            wx, wy = axes.tile_to_world(tx, ty)
            assert (wx, wy) == (ORIGIN[0] + tx, ORIGIN[1] + ty)
            assert axes.world_to_tile(wx, wy) == (tx, ty)


def test_nav_loads_as_walkable_terrain() -> None:
    maps_dir = _maps_dir()
    for pack_id, _mid, _ko in BASE_EXPECTED:
        pack = load_map_pack(maps_dir, pack_id)
        terrain = TerrainMap.from_png(pack.terrain_path, pixel_scale=1)
        assert terrain.walkable.shape == (SIZE[1], SIZE[0])
        assert bool(terrain.walkable.any())
        assert not bool(terrain.walkable.all())


def test_farms_yaml_round_trip(tmp_path: Path) -> None:
    """Each pack keeps its own farms file; seasons do not share paths."""
    maps_dir = _maps_dir()
    paths: dict[str, Path] = {}
    for pack_id, _mid, _ko in BASE_EXPECTED:
        pack = load_map_pack(maps_dir, pack_id)
        assert pack.farm_areas_path is not None
        paths[pack_id] = Path(pack.farm_areas_path)
    assert len(set(paths.values())) == len(BASE_EXPECTED)
    sample = tmp_path / "farms.yaml"
    doc = {
        "areas": [
            {
                "name": "area_test",
                "region": "blessing_land",
                "x0": 10,
                "y0": 20,
                "x1": 40,
                "y1": 60,
            }
        ]
    }
    sample.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    loaded = yaml.safe_load(sample.read_text(encoding="utf-8"))
    assert loaded["areas"][0]["x0"] == 10
    assert loaded["areas"][0]["y1"] == 60
    # World ↔ tile for the saved rect corners uses the pack origin.
    pack = load_map_pack(maps_dir, "polluted_land_of_blessing")
    axes = axes_from_pack(pack)
    assert axes is not None
    assert axes.tile_to_world(10, 20) == (ORIGIN[0] + 10, ORIGIN[1] + 20)
    assert axes.world_to_tile(ORIGIN[0] + 40, ORIGIN[1] + 60) == (40, 60)


def test_battle_picker_order_and_break_exclusion() -> None:
    catalog = list(list_map_choices("ko"))
    catalog.sort(key=map_choice_sort_key)
    battle = battle_picker_choices(catalog)
    battle.sort(key=map_choice_sort_key)
    ids = [mid for mid, _label, _d in battle]
    assert ids[:22] == [
        "talking_island",
        "mainland",
        *BLESSING_LAND_FIELD_MAP_IDS,
    ]
    assert tuple(BLESSING_LAND_FIELD_MAP_IDS) == tuple(p[0] for p in PICKER_EXPECTED)
    labels = {
        mid: label
        for mid, label, _d in battle
        if mid in BLESSING_LAND_FIELD_MAP_IDS
    }
    for pack_id, _mid, ko in PICKER_EXPECTED:
        assert labels[pack_id] == ko
        assert map_display_name(pack_id, "ko") == ko
        assert not any(row[2] for row in battle if row[0] == pack_id)
    # Season base packs are not offered in the solo battle picker.
    for pack_id, _mid, _ko in BASE_EXPECTED:
        assert pack_id not in ids
    break_ids = {mid for mid, _l, _d in break_picker_choices(catalog)}
    assert break_ids.isdisjoint(BLESSING_LAND_HIDDEN_MAP_IDS)


def test_legacy_routine_map_id_migrates() -> None:
    rows = normalize_routine(
        [
            {
                "id": "a",
                "map_id": "polluted_land_of_blessing_dungeon",
                "kind": "battle",
                "duration_minutes": 30,
                "selected_farms": ["area_1"],
            }
        ]
    )
    assert rows[0]["map_id"] == "polluted_land_of_blessing"
