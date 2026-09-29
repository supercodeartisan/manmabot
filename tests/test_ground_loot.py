"""Field pickup lists and monster blacklist keys from Chinese names."""
from __future__ import annotations

from types import SimpleNamespace

from app._03_world.constants import configure_species_blacklist, is_species_blacklisted
from app._03_world.memory_entities import entities_to_vision
from app._03_world.objects import Identity, ObjectType, WorldObject
from app._04_decision.combat_query import list_lootable
from app._04_decision.ground_loot import configure_ground_loot, ground_item_allowed


def _item(name: str, track_id: int = 1) -> WorldObject:
    return WorldObject(
        track_id=track_id,
        object_type=ObjectType.ITEM,
        identity=Identity(name, 1.0),
        species_name=name,
        label="object",
    )


class _Items:
    def __init__(self, rows: list[WorldObject]) -> None:
        self._rows = rows

    def items(self) -> list[WorldObject]:
        return list(self._rows)

    def missing_frames(self, _track_id: int) -> int:
        return 0


def test_chinese_monster_name_matches_blacklist_key() -> None:
    configure_species_blacklist(["monster_오크"])
    try:
        rows = entities_to_vision(
            {
                "client_w": 800,
                "client_h": 600,
                "entities": [
                    {
                        "ent": "0xORC",
                        "class": "Monster",
                        "name": "妖魔",
                        "species": 0,
                        "screen": {"x": 120, "y": 80, "src": "pres"},
                    }
                ],
            }
        )
        assert rows[0]["species_name"] == "monster_오크_2"
        assert is_species_blacklisted(rows[0]["species_name"])
        assert is_species_blacklisted("monster_오크")
    finally:
        configure_species_blacklist([])


def test_whitelist_matches_korean_and_chinese_item_names() -> None:
    configure_ground_loot("whitelist", ["빨간 물약", "아데나"])
    try:
        assert ground_item_allowed(_item("紅色藥水"))
        assert ground_item_allowed(_item("金幣"))
        assert ground_item_allowed(_item("金币"))
        assert not ground_item_allowed(_item("파란 물약"))
        kept = list_lootable(
            _Items([_item("紅色藥水", 1), _item("파란 물약", 2)]),
            loot_mode="all_items",
        )
        assert [obj.species_name for obj in kept] == ["紅色藥水"]
    finally:
        configure_ground_loot("all", [])


def test_adena_only_keeps_unnamed_ground_pile() -> None:
    from app._04_decision.combat_query import is_adena
    from app._04_decision.player_mode import LOOT_MODE_ADENA

    unnamed = WorldObject(
        track_id=4,
        object_type=ObjectType.ITEM,
        identity=Identity("item", 1.0),
        species_name="",
        detail_classification="item",
    )
    assert is_adena(unnamed) is True
    kept = list_lootable(_Items([unnamed]), loot_mode=LOOT_MODE_ADENA)
    assert [obj.track_id for obj in kept] == [4]


def test_list_lootable_screen_only_drops_off_window_uv() -> None:
    from app._03_world.objects import Position

    on = _item("아데나", 1)
    on.position = Position(x=0.4, y=0.5)
    off = _item("아데나", 2)
    off.position = Position(x=1.2, y=0.5)
    kept = list_lootable(_Items([on, off]), loot_mode="all_items", screen_only=True)
    assert [row.track_id for row in kept] == [1]


def test_list_lootable_keeps_near_item_with_off_window_uv() -> None:
    from app._03_world.objects import Position

    pile = _item("아데나", 8)
    pile.position = Position(x=1.15, y=0.4)
    pile.world_rx = 1
    pile.world_ry = 0
    kept = list_lootable(_Items([pile]), loot_mode="all_items", screen_only=True)
    assert [row.track_id for row in kept] == [8]


def test_list_lootable_keeps_near_player_item_outside_farm() -> None:
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.farm_area import FarmRect

    pile = _item("아데나", 6)
    pile.world_rx = 0
    pile.world_ry = 1
    pile.world_cx = 100
    pile.world_cy = 100
    farm = FarmRect(x0=200, y0=200, x1=220, y1=220)
    kept = list_lootable(
        _Items([pile]),
        loot_mode="all_items",
        farm=farm,
        origin=WorldOrigin(x=10, y=10),
    )
    assert [obj.track_id for obj in kept] == [6]


def test_list_lootable_drops_print_state_ghost() -> None:
    ghost = _item("아데나", 9)
    world = _Items([ghost])
    world.last_print_state = {"entities": []}
    world.missing_frames = lambda _tid: 1
    kept = list_lootable(world, loot_mode="all_items")
    assert kept == []


def test_list_lootable_keeps_memory_item_without_vision_reachability() -> None:
    hidden = _item("아데나", 3)
    hidden.occluded = True
    hidden.frames_lost = 9
    kept = list_lootable(_Items([hidden]), loot_mode="all_items")
    assert [obj.track_id for obj in kept] == [3]


def test_blacklist_skips_listed_ground_items_only() -> None:
    configure_ground_loot("blacklist", ["아데나"])
    try:
        assert not ground_item_allowed(_item("金幣"))
        assert ground_item_allowed(_item("紅色藥水"))
        assert ground_item_allowed(SimpleNamespace(species_name="", identity=None, label=None))
    finally:
        configure_ground_loot("all", [])


def test_empty_whitelist_picks_up_nothing() -> None:
    configure_ground_loot("whitelist", [])
    try:
        assert not ground_item_allowed(_item("金幣"))
    finally:
        configure_ground_loot("all", [])


def test_species_whitelist_attacks_only_listed_monsters() -> None:
    from app._03_world.constants import configure_species_filter
    from app._04_decision.species_rules import is_blacklisted_object

    configure_species_filter("whitelist", [], ["monster_오크"])
    try:
        orc = SimpleNamespace(species_name="monster_오크_2", detail_classification="monster_1-10")
        wolf = SimpleNamespace(species_name="monster_늑대인간_9", detail_classification="monster_1-10")
        assert not is_blacklisted_object(orc)
        assert is_blacklisted_object(wolf)
        configure_species_filter("whitelist", [], [])
        assert is_blacklisted_object(orc)
    finally:
        configure_species_filter("blacklist", [], [])
