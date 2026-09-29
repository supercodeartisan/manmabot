from __future__ import annotations

from types import SimpleNamespace

from manmabot_v1.bot_controller import BotController, RunState
from manmabot_v1.debug_snapshot import (
    STATUS_SECTIONS,
    build_runtime_snapshot,
    columns_for_section,
    rows_for_section,
    section_text,
)
from manmabot_v1.profile import Profile
from manmabot_v1.ui.schedule_i18n import TABLE


def test_status_sections_are_selectable_and_translated():
    expected = {
        "overview", "player", "decision", "world", "navigation",
        "memory", "vision", "hotbar", "logs", "preview", "tables",
    }
    assert set(STATUS_SECTIONS) == expected
    for language, strings in TABLE.items():
        for section in STATUS_SECTIONS:
            assert f"debug_{section}" in strings, language


def test_snapshot_rows_expose_live_player_and_decision():
    player = SimpleNamespace(
        hp=420, max_hp=500, hp_ratio=0.84, mp=80, max_mp=200, mp_ratio=0.4,
        level=12, exp_percent=3.5, alive=True, zone="Talking Island",
        character_type=SimpleNamespace(value="elf"),
        position=SimpleNamespace(x=0.5, y=0.6),
        inventory=SimpleNamespace(weight_ratio=0.22),
        buffs=[SimpleNamespace(name="sunlight", duration=12.0)],
    )
    monster = SimpleNamespace(
        track_id=7, object_type=SimpleNamespace(value="monster"),
        species_name="orc", yolo_conf=0.91, position=SimpleNamespace(x=0.4, y=0.5),
        detail_classification="monster_1-10", frames_lost=0, identity=None, label=None,
    )
    world = SimpleNamespace(
        player=player, frame_id=33,         last_memory_snapshot={
            "player": {
                "hp": 420, "maxHp": 500, "mp": 80, "maxMp": 200, "pos": [10, 20],
                "food": 17, "lawful": 2217, "ac": -6, "weight": 654, "maxWeight": 1950,
                "sp": 12, "classId": 1, "online": True,
                "stats": {"str": 12, "dex": 12, "con": 12, "int": 12, "wis": 12, "cha": 12},
            },
            "buffs": [{"id": 4, "remain": 12, "stacks": 1}],
            "items": [1, 2],
            "skills": [{"id": 8, "name": "heal", "level": 1}],
            "party": [{"name": "ally", "hp": 40, "class": "elf"}],
            "entities": [1],
        },
        last_print_state={
            "entities": [
                {
                    "class": "Monster", "name": "orc", "species": 0,
                    "ent": "0xABC", "world": {"cx": 1, "cy": 2},
                    "screen": {"x": 3, "y": 4, "src": "pres"},
                    "iscr": {"x": 5, "y": 6},
                },
            ]
        },
        last_inventory={"items": [{"slot": 0, "id": 5, "name": "아데나", "count": 1100, "kind": 0, "fmt": "$4"}]},
        last_hotbar={
            "n": 24,
            "slots": [
                {
                    "slot": 0, "box": 1, "key": "f5", "type": "SPELL",
                    "name": "힐", "label": "힐(4/0)", "count": 0,
                },
                {
                    "slot": 8, "box": 2, "key": "f5", "type": "ITEM",
                    "name": "체력 회복제", "label": "체력 회복제", "count": 12,
                },
            ],
        },
        all_objects=lambda: [monster],
        counts=lambda: {"monster": 1, "item": 0},
    )
    blackboard = SimpleNamespace(
        player_mode=SimpleNamespace(value="farming"),
        current_goal="attack", current_target_id=7, current_item_id=None,
        tick_count=9, farm_area_index=1, farm_elapsed_seconds=12.5,
        farm_time_inside=True, needs_arrows=False, given_up_target_ids={},
        blacklisted_target_ids=set(), resume_mode=None, world_origin=SimpleNamespace(x=40, y=80),
        nav_goal=(41, 82), nav_waypoint=(41, 81), nav_path=[(40, 80), (41, 81), (41, 82)],
        travel_purpose="enter_farm", travel_hop_active=True, travel_stuck_tile=None,
        search_waypoint=None, search_hop_active=False, search_stuck_tile=None,
        loot_approach_waypoint=None, loot_approach_active=False,
        virtual_position=SimpleNamespace(x=0.5, y=0.5), patrol_index=0, leg_history=[],
    )
    action = SimpleNamespace(
        action=SimpleNamespace(value="attack"), reason="weak monster",
        target_id=7, priority=1.0, mid_act=False, destination=SimpleNamespace(x=0.42, y=0.51),
    )
    snap = build_runtime_snapshot(
        state="running",
        profile=Profile(character="elf", active_map="talking_island", loot_mode="all_items"),
        world=world,
        blackboard=blackboard,
        action=action,
        vision=[{"track_id": 7, "classification": "monster", "species_name": "orc", "yolo_conf": 0.9, "position_x": 0.4, "position_y": 0.5}],
        spell_slots={"heal": {"box": 1, "key": "f5", "enabled": True}},
        hotbar_layout={"boxes": {"1": {"f5": {"kr_name": "힐", "role": "heal", "kind": "SPELL"}}}},
        loop={"note": "tick", "fps": 12.5, "tick_ms": 80, "frame_id": 33},
        worker_alive=True,
    )
    assert snap["overview"]["state"] == "running"
    assert snap["player"]["hp"] == 420
    assert snap["decision"]["action"] == "attack"
    assert snap["world"]["objects"][0]["name"] == "orc"
    assert rows_for_section("overview", snap)
    assert rows_for_section("player", snap)[0][0] == "hp"
    world_rows = rows_for_section("world", snap)
    assert world_rows[0][2] == "orc"
    assert "attack" in section_text("decision", snap)
    assert columns_for_section("world")[0][0] == "id"
    assert "tables" in snap
    assert snap["tables"]["player"]
    assert snap["tables"]["entities"][0]["name"] == "orc"
    assert snap["tables"]["entities"][0]["ent"] == "0xABC"
    assert snap["tables"]["entities"][0]["iscr"] == "5, 6"
    assert snap["tables"]["inventory"][0]["id"] == 5
    assert snap["tables"]["hotbar"][0]["name"] == "힐"
    assert snap["tables"]["hotbar"][0]["key"] == "F5"
    assert snap["tables"]["hotbar"][0]["role"] == "heal"
    assert snap["tables"]["hotbar"][8]["type"] == "ITEM"
    assert snap["tables"]["hotbar"][8]["count"] == 12
    assert any(row[0] == "hotbar" for row in rows_for_section("tables", snap))
    assert snap["tables"]["buffs"][0]["id"] == 4
    assert snap["tables"]["skills"][0]["name"] == "heal"
    assert snap["tables"]["party"][0]["name"] == "ally"


def test_debug_watcher_does_not_enable_preview():
    controller = BotController()
    controller.add_debug_watcher()
    assert not controller._preview_enabled.is_set()
    controller.add_preview_watcher()
    assert controller._preview_enabled.is_set()
    controller.remove_preview_watcher()
    assert not controller._preview_enabled.is_set()
    controller.remove_debug_watcher()


def test_preview_skips_encode_when_unread_frame_waiting(monkeypatch):
    controller = BotController()
    controller.set_preview_enabled(True)
    controller._preview_q.put(b"old")
    called: list[object] = []

    def fake_encode(image, **_kwargs):
        called.append(image)
        return b"new"

    monkeypatch.setattr(
        "app._02_vision.preview.encode_preview_jpeg", fake_encode
    )
    controller._push_preview_image(object())
    assert called == []
    assert controller.pop_preview_jpeg() == b"old"
    controller._push_preview_image(object())
    assert called
    assert controller.pop_preview_jpeg() == b"new"


def test_start_does_not_block_the_ui_thread(monkeypatch):
    import time

    import manmabot_v1.bot_controller as bot_mod

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: slept.append(float(seconds)))

    controller = BotController()
    profile = Profile(wizard_completed=True, selected_farms=["a"])
    monkeypatch.setattr(controller, "start_gates_ok", lambda _profile: None)
    monkeypatch.setattr(
        bot_mod, "probe_game", lambda: SimpleNamespace(lamp="green", hwnd=11)
    )
    monkeypatch.setattr(
        bot_mod, "pause_reason_from_game", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(bot_mod, "bring_game_to_front", lambda _hwnd: None)
    monkeypatch.setattr(
        bot_mod.threading,
        "Thread",
        lambda *args, **kwargs: SimpleNamespace(
            start=lambda: None, is_alive=lambda: False
        ),
    )
    assert controller.start(profile) is None
    assert slept == []
    assert controller.state == RunState.RUNNING


def test_controller_debug_snapshot_follows_same_run_state():
    controller = BotController()
    empty = controller.debug_snapshot()
    assert empty["overview"]["state"] == RunState.STOPPED.value
    assert empty["overview"]["worker_alive"] is False
    controller.add_debug_watcher()
    controller._publish_debug(
        loop={"note": "paused", "fps": 0, "tick_ms": 0, "frame_id": 0},
    )
    live = controller.debug_snapshot()
    assert live["overview"]["note"] == "paused"
    controller.remove_debug_watcher()
    controller._publish_debug(loop={"note": "should_skip"})
    assert controller.debug_snapshot()["overview"]["note"] == "paused"
