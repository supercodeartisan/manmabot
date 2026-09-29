"""print_state entities → vision handoff, and the reversible hybrid click source."""
from __future__ import annotations

import json
import time
from pathlib import Path

from app._03_world.converter import vision_to_perception
from app._03_world.memory_entities import (
    EntityShadow,
    LiveEntitySweep,
    TrackIds,
    decision_rows,
    entities_to_vision,
    fill_unleveled_from_vision,
    load_species_ids,
    project_memory_to_content,
    summarize_shadow,
)
from app._03_world.objects import ObjectType, WorldObject
from app._03_world.world_coords import WorldOrigin
from app._04_decision.combat_query import object_absolute_tile, tile_distance_from_player


def _frame() -> dict:
    return {
        "client_w": 800,
        "client_h": 600,
        "entities": [
            {
                "ent": "0xSELF",
                "class": "MyPlayer",
                "name": "Roshan",
                "species": 0,
                "screen": {"x": 400, "y": 300, "src": "self"},
            },
            {
                "ent": "0xMOB",
                "class": "Monster",
                "name": "警衛",
                "species": 10,
                "screen": {"x": 600, "y": 200, "src": "pres"},
            },
            {
                "ent": "0xOFF",
                "class": "Monster",
                "name": "off",
                "species": 11,
                "screen": {"x": 900, "y": 10, "src": "pres"},
            },
            {
                "ent": "0xNPC",
                "class": "InteractiveNPC",
                "name": "Door",
                "species": 8,
                "screen": {"x": 100, "y": 100, "src": "pres"},
            },
        ],
    }


def test_on_screen_targets_skip_self_and_offscreen():
    rows = entities_to_vision(_frame(), species={})
    kinds = [row["classification"] for row in rows]
    assert kinds == ["monster", "npc"]
    monster = rows[0]
    assert monster["position_x"] == 600 / 800
    assert monster["position_y"] == 200 / 600
    assert monster["memory_name"] == "警衛"
    assert "detail_classification" not in monster


def test_iscr_wins_over_raw_screen():
    snap = {
        "client_w": 800,
        "client_h": 600,
        "entities": [
            {
                "ent": "0xMOB",
                "class": "Monster",
                "name": "orc",
                "species": 10,
                "screen": {"x": 100, "y": 100, "src": "pres"},
                "iscr": {"x": 640, "y": 240},
            }
        ],
    }
    rows = entities_to_vision(snap, species={})
    assert len(rows) == 1
    assert rows[0]["position_x"] == 640 / 800
    assert rows[0]["position_y"] == 240 / 600


def test_species_table_makes_a_farmable_monster():
    table = {10: {"name": "monster_경비", "level": 4}}
    rows = entities_to_vision(_frame(), species=table)
    monster = rows[0]
    assert monster["species_name"] == "monster_경비_4"
    assert monster["detail_classification"] == "monster_1-10"
    perceived = vision_to_perception([monster])
    assert len(perceived) == 1
    assert perceived[0].object_type is ObjectType.MONSTER


def test_unknown_level_is_not_a_monster_target():
    rows = entities_to_vision(_frame(), species={}, aliases={})
    perceived = vision_to_perception(rows)
    types = [item.object_type for item in perceived]
    assert ObjectType.MONSTER not in types
    assert ObjectType.NPC in types


def test_korean_and_chinese_names_use_vision_levels():
    from app._03_world.constants import monster_level_from_species
    from app._03_world.memory_entities import resolve_catalog_key

    assert resolve_catalog_key("고블린") == "monster_고블린"
    assert resolve_catalog_key("哥布林") == "monster_고블린"
    assert resolve_catalog_key("杜賓狗") == "monster_도베르만"
    assert resolve_catalog_key("杜宾犬") == "monster_도베르만"
    assert resolve_catalog_key("地靈") == "monster_그렘린"
    assert monster_level_from_species("monster_고블린") == 2
    assert monster_level_from_species("monster_도베르만") == 6
    assert monster_level_from_species("monster_그렘린") == 4

    snap = {
        "client_w": 800,
        "client_h": 600,
        "entities": [
            {
                "ent": "0xG",
                "class": "Monster",
                "name": "哥布林",
                "species": 245,
                "screen": {"x": 400, "y": 300, "src": "pres"},
            },
            {
                "ent": "0xD",
                "class": "Monster",
                "name": "杜賓狗",
                "species": 177,
                "screen": {"x": 420, "y": 310, "src": "pres"},
            },
            {
                "ent": "0xR",
                "class": "Monster",
                "name": "도베르만",
                "species": 1,
                "screen": {"x": 440, "y": 320, "src": "pres"},
            },
        ],
    }
    rows = entities_to_vision(snap, species={})
    perceived = vision_to_perception(rows)
    assert [p.object_type for p in perceived] == [
        ObjectType.MONSTER,
        ObjectType.MONSTER,
        ObjectType.MONSTER,
    ]
    assert perceived[0].species_name == "monster_고블린_2"
    assert perceived[1].species_name == "monster_도베르만_6"
    assert perceived[2].species_name == "monster_도베르만_6"


def test_track_id_stays_with_the_address():
    tracks = TrackIds()
    first = entities_to_vision(_frame(), id_map=tracks, species={})
    second = entities_to_vision(_frame(), id_map=tracks, species={})
    assert first[0]["track_id"] == second[0]["track_id"]
    assert first[0]["track_id"] != first[1]["track_id"]


def test_summary_pairs_nearby_same_class():
    memory = entities_to_vision(_frame(), species={10: {"level": 4}})
    vision = [
        {
            "classification": "monster",
            "position_x": memory[0]["position_x"] + 0.01,
            "position_y": memory[0]["position_y"],
        }
    ]
    text = summarize_shadow(vision, memory)
    assert "paired=1" in text
    assert "unleveled=" not in text


def test_shadow_ignores_a_stale_file(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_frame()) + "\n", encoding="utf-8")
    old = time.time() - 30
    import os
    os.utime(path, (old, old))
    shadow = EntityShadow(path, stale_s=2.0, log_interval_s=0.0)
    assert shadow.observe([]) is None


def test_live_sweep_reads_the_caller_not_a_file():
    class _Reader:
        def __init__(self) -> None:
            self.closed = False

        def snapshot(self) -> dict:
            return _frame()

        def close(self) -> None:
            self.closed = True

    reader = _Reader()
    sweep = LiveEntitySweep(
        log_interval_s=0.0,
        reader=reader,
        species_path=Path("missing-species-ids.json"),
    )
    snap, rows, line = sweep.poll([])
    assert snap is not None and snap["client_w"] == 800
    assert [row["classification"] for row in rows] == ["monster", "npc"]
    assert line is not None and line.startswith("Entity shadow:")
    sweep.close()
    assert reader.closed


def test_species_file_round_trip(tmp_path: Path):
    path = tmp_path / "species_ids.json"
    path.write_text(
        json.dumps({"ids": {"10": {"name": "monster_경비", "level": 4}, "x": {}}}),
        encoding="utf-8",
    )
    table = load_species_ids(path)
    assert table[10]["level"] == 4
    assert 0 not in table


def test_unleveled_memory_monster_borrows_nearby_vision_level():
    memory = entities_to_vision(
        {
            "client_w": 800,
            "client_h": 600,
            "entities": [
                {
                    "ent": "0xRABBIT",
                    "class": "Monster",
                    "name": "兔子",
                    "species": 206,
                    "screen": {"x": 200, "y": 180, "src": "pres"},
                }
            ],
        },
        aliases={},
    )
    assert memory[0].get("detail_classification") is None
    vision = [
        {
            "classification": "monster",
            "position_x": memory[0]["position_x"] + 0.02,
            "position_y": memory[0]["position_y"],
            "detail_classification": "monster_1-10",
            "detail_classification_confidence": 0.91,
        },
        {
            "classification": "monster",
            "position_x": 0.9,
            "position_y": 0.9,
            "species_name": "monster_오크_2",
            "species_confidence": 1.0,
            "detail_classification": "monster_1-10",
            "detail_classification_confidence": 1.0,
        },
    ]
    assert fill_unleveled_from_vision(memory, vision) == 1
    assert memory[0]["detail_classification"] == "monster_1-10"
    assert memory[0]["level_source"] == "vision"
    assert vision[1]["species_name"] == "monster_오크_2"


def test_content_projection_matches_clicks_and_drops_pillarbox():
    rows = [
        {"position_x": 960 / 1920, "position_y": 100 / 1080, "classification": "monster"},
        {"position_x": 100 / 1920, "position_y": 100 / 1080, "classification": "item"},
    ]
    projected = project_memory_to_content(
        rows,
        client_w=1920,
        client_h=1080,
        crop_left=240,
        crop_top=0,
        crop_w=1440,
        crop_h=1080,
    )
    assert len(projected) == 1
    assert abs(projected[0]["position_x"] - 0.5) < 1e-6
    identity = project_memory_to_content(
        [{"position_x": 0.25, "position_y": 0.5}],
        client_w=800,
        client_h=600,
    )
    assert identity[0]["position_x"] == 0.25


def test_memory_world_cell_drives_distance_and_nav_tile():
    rows = entities_to_vision(
        {
            "client_w": 800,
            "client_h": 600,
            "player": {"x": 32553, "y": 33079},
            "entities": [
                {
                    "ent": "0xMOB",
                    "class": "Monster",
                    "name": "妖魔",
                    "species": 0,
                    "world": {"cx": 32561, "cy": 33086},
                    "screen": {"x": 400, "y": 300, "src": "pres"},
                }
            ],
        }
    )
    assert rows[0]["world_rx"] == 8
    assert rows[0]["world_ry"] == 7
    perceived = vision_to_perception(rows)
    obj = WorldObject.from_perception(perceived[0])
    assert tile_distance_from_player(obj) == 8
    assert object_absolute_tile(obj, WorldOrigin(0, 0)) == (32561 - 32256, 33086 - 32704)


def test_vision_source_is_kept_when_hybrid_sweep_fails():
    vision = [{"track_id": 1, "classification": "monster"}]
    memory = [{"track_id": 9, "classification": "item"}]
    assert decision_rows("vision", vision, memory, sweep_ok=True) == (vision, "vision")
    assert decision_rows("hybrid", vision, memory, sweep_ok=False) == (vision, "vision")
    assert decision_rows("hybrid", vision, memory, sweep_ok=True) == (memory, "hybrid")


def test_adena_and_item_classes_become_loot_rows():
    rows = entities_to_vision(
        {
            "client_w": 800,
            "client_h": 600,
            "player": {"x": 32556, "y": 32993},
            "entities": [
                {
                    "ent": "0xAD",
                    "class": "ADENA",
                    "name": "",
                    "species": 1,
                    "world": {"cx": 32557, "cy": 32993},
                    "screen": {"x": 420, "y": 310, "src": "cell"},
                },
                {
                    "ent": "0xIT",
                    "class": "ITEM",
                    "name": "金幣",
                    "species": 1,
                    "world": {"cx": 32558, "cy": 32993},
                    "screen": {"x": 440, "y": 310, "src": "cell"},
                },
            ],
        }
    )
    assert [row["classification"] for row in rows] == ["item", "item"]
    assert rows[0]["memory_name"] == "adena"
    perceived = vision_to_perception(rows)
    assert [item.object_type for item in perceived] == [
        ObjectType.ITEM,
        ObjectType.ITEM,
    ]


def test_offscreen_item_with_world_cell_is_kept():
    rows = entities_to_vision(
        {
            "client_w": 800,
            "client_h": 600,
            "player": {"x": 32556, "y": 32993},
            "entities": [
                {
                    "ent": "0xOFFITEM",
                    "class": "Item",
                    "name": "아데나",
                    "species": 1,
                    "world": {"cx": 32557, "cy": 32993},
                    "screen": {"x": 900, "y": 10, "src": "cell"},
                }
            ],
        }
    )
    assert len(rows) == 1
    assert rows[0]["classification"] == "item"
    assert rows[0]["world_rx"] == 1
    assert rows[0]["memory_name"] == "아데나"


def test_print_state_player_vitals_use_snake_case_keys():
    from app._03_world.gamestate import GameState
    from app._03_world.memory_sync import apply_print_state_vitals, player_from_snapshot

    player = player_from_snapshot(
        {"player": {"hp": 40, "max_hp": 80, "mp": 10, "max_mp": 46, "lv": 11}}
    )
    assert player.hp == 40
    assert player.max_hp == 80
    assert player.hp_ratio == 0.5
    assert player.mp == 10
    assert player.max_mp == 46
    assert player.level == 11

    world = GameState()
    assert world.player.hp is None
    assert apply_print_state_vitals(
        world,
        {"player": {"x": 32556, "y": 32993, "hp": 24, "max_hp": 80, "mp": 20, "max_mp": 46, "lv": 11}},
    )
    assert world.player.hp == 24
    assert world.player.max_hp == 80
    assert world.player.hp_ratio == 0.3


def test_print_state_player_xy_sets_nav_origin():
    from app._03_world.memory_sync import world_origin_from_snapshot

    origin = world_origin_from_snapshot(
        {"player": {"x": 32556, "y": 32993, "hp": 79}}
    )
    assert origin is not None
    assert origin.x == 32556 - 32256
    assert origin.y == 32993 - 32704
    monitor = world_origin_from_snapshot({"player": {"pos": [32556, 32993]}})
    assert monitor == origin

