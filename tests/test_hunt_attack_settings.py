"""Hunt/Attack tab settings that are now wired into the engine."""
from __future__ import annotations

import time
from types import SimpleNamespace

from app._03_world.enums import ActionType
from app._03_world.objects import ObjectType, Position, WorldObject
from app._03_world.player import InventoryState, PlayerState, StatusEffect
from app._04_decision.behavior_tree import Status
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors import combat as combat_beh
from app._04_decision.behaviors import mode_actions
from app._04_decision.behaviors.combat import continue_sticky_combat
from app._04_decision import hunt_area
from app._04_decision import player_mode as pm
from app._05_action import humanize as hz
from manmabot_v1.profile import Profile
from manmabot_v1.schedule import ScheduleStore
from manmabot_v1.task_runtime import apply_runtime_settings, clamp_jitter_ms


def test_runtime_applies_hunt_attack_tab_fields():
    profile = Profile()
    task = ScheduleStore().create(profile)
    hunt = task.settings["hunt"]
    hunt["attack_jitter"] = True
    hunt["attack_jitter_ms"] = 200
    hunt["target_delay"] = True
    hunt["target_delay_min_ms"] = 50
    hunt["target_delay_max_ms"] = 90
    hunt["abandon_same"] = True
    hunt["abandon_seconds"] = 12
    hunt["antidote_auto"] = True
    hunt["area_empty"] = True
    hunt["area_empty_seconds"] = 15
    hunt["area_low_yield"] = True
    hunt["area_low_yield_adena"] = 2500
    hunt["area_low_yield_seconds"] = 90
    hunt["area_players"] = True
    hunt["area_player_count"] = 4
    apply_runtime_settings(task, profile)
    assert profile.attack_jitter is True
    assert profile.attack_jitter_ms == 50
    assert profile.target_delay is True
    assert profile.target_delay_min_ms == 50
    assert profile.target_delay_max_ms == 50
    assert profile.abandon_same is True
    assert profile.abandon_seconds == 12
    assert profile.antidote_auto is True
    assert profile.area_empty_seconds == 15
    assert profile.area_low_yield_adena == 2500
    assert profile.area_player_count == 4
    assert profile.buy_depoison is False


def test_abandon_same_drops_living_target_after_seconds():
    obj = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        species_name="monster_오크",
        world_rx=1,
        world_ry=0,
    )
    state = SimpleNamespace(
        get_object=lambda tid: obj if tid == 7 else None,
        missing_frames=lambda _tid: 0,
        monsters=lambda: [obj],
    )
    board = Blackboard()
    board.current_target_id = 7
    board.current_target_species = "monster_오크"
    board.target_engage_started = time.time() - 40
    prev = combat_beh.ABANDON_SAME_ENABLED
    prev_s = combat_beh.ABANDON_SECONDS
    combat_beh.ABANDON_SAME_ENABLED = True
    combat_beh.ABANDON_SECONDS = 30.0
    try:
        assert continue_sticky_combat(state, board) is False
        assert board.current_target_id is None
        assert 7 in board.given_up_target_ids
    finally:
        combat_beh.ABANDON_SAME_ENABLED = prev
        combat_beh.ABANDON_SECONDS = prev_s


def test_antidote_uses_hotbar_when_poisoned(monkeypatch):
    from app._05_action.spell_box import configure_spell_box

    board = Blackboard()
    player = PlayerState(
        track_id=-1,
        position=Position(0.5, 0.5),
        buffs=[StatusEffect(name="10", duration=20.0)],
        inventory=InventoryState(depoison=3, bag_ready=True),
    )
    state = SimpleNamespace(player=player)
    monkeypatch.setattr(pm, "ANTIDOTE_AUTO", True)
    configure_spell_box(
        {"depoison": {"box": 1, "key": "f5", "enabled": True, "reuse_s": 0.0}}
    )
    monkeypatch.setattr("app._04_decision.spells.mark_slot_used", lambda *_a, **_k: None)
    assert mode_actions.player_is_poisoned(state) is True
    result = mode_actions.maybe_use_antidote(state, board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.USE_DEPOISON
    configure_spell_box()


def test_antidote_skips_empty_bag(monkeypatch):
    from app._05_action.spell_box import configure_spell_box

    board = Blackboard()
    player = PlayerState(
        track_id=-1,
        position=Position(0.5, 0.5),
        poisoned=True,
        inventory=InventoryState(depoison=0, bag_ready=True),
    )
    state = SimpleNamespace(player=player)
    monkeypatch.setattr(pm, "ANTIDOTE_AUTO", True)
    configure_spell_box(
        {"depoison": {"box": 1, "key": "f5", "enabled": True, "reuse_s": 0.0}}
    )
    assert mode_actions.maybe_use_antidote(state, board) is None
    configure_spell_box()


def test_target_delay_idles_before_engage(monkeypatch):
    board = Blackboard()
    target = WorldObject(
        track_id=3,
        object_type=ObjectType.MONSTER,
        species_name="monster_오크",
        world_rx=1,
        world_ry=0,
    )
    state = SimpleNamespace(get_object=lambda tid: target if tid == 3 else None)
    monkeypatch.setattr(pm, "TARGET_DELAY_ENABLED", True)
    monkeypatch.setattr(pm, "TARGET_DELAY_MIN_MS", 80)
    monkeypatch.setattr(pm, "TARGET_DELAY_MAX_MS", 80)
    monkeypatch.setattr(mode_actions, "nearest_attackable", lambda *_a, **_k: target)
    monkeypatch.setattr(mode_actions, "continue_sticky_combat", lambda *_a, **_k: False)
    result = mode_actions.continue_or_start_combat(state, board)
    assert result is Status.SUCCESS
    assert board.intent.action is ActionType.IDLE
    assert board.intent.reason == "target delay"
    assert board.current_target_id is None
    board.target_select_until = time.time() - 0.01
    result = mode_actions.continue_or_start_combat(state, board)
    assert result is Status.SUCCESS
    assert board.intent.action is ActionType.ATTACK
    assert board.current_target_id == 3


def test_area_empty_and_low_yield_and_players(monkeypatch):
    board = Blackboard()
    board.world_origin = SimpleNamespace(x=10, y=10)
    board.farm_watch_started = time.time() - 200
    board.farm_adena_start = 100
    board.farm_empty_since = time.time() - 70
    state = SimpleNamespace(
        player=PlayerState(
            track_id=-1,
            position=Position(0.5, 0.5),
            inventory=InventoryState(adena=150, bag_ready=True),
        ),
        players=lambda: [
            WorldObject(track_id=11, object_type=ObjectType.PLAYER, position=Position(0.4, 0.4)),
            WorldObject(track_id=12, object_type=ObjectType.PLAYER, position=Position(0.6, 0.6)),
        ],
    )
    monkeypatch.setattr(hunt_area, "is_inside_active_farm", lambda _b: True)
    monkeypatch.setattr(
        "app._04_decision.combat_query.count_attackable",
        lambda *_a, **_k: 0,
    )
    monkeypatch.setattr(pm, "AREA_EMPTY_ENABLED", True)
    monkeypatch.setattr(pm, "AREA_EMPTY_SECONDS", 60.0)
    monkeypatch.setattr(pm, "AREA_LOW_YIELD_ENABLED", False)
    monkeypatch.setattr(pm, "AREA_PLAYERS_ENABLED", False)
    assert hunt_area.rotate_reason(state, board) == "no monsters"

    monkeypatch.setattr(pm, "AREA_EMPTY_ENABLED", False)
    monkeypatch.setattr(pm, "AREA_LOW_YIELD_ENABLED", True)
    monkeypatch.setattr(pm, "AREA_LOW_YIELD_ADENA", 1000)
    monkeypatch.setattr(pm, "AREA_LOW_YIELD_SECONDS", 180.0)
    assert hunt_area.rotate_reason(state, board) == "low adena yield"

    monkeypatch.setattr(pm, "AREA_LOW_YIELD_ENABLED", False)
    monkeypatch.setattr(pm, "AREA_PLAYERS_ENABLED", True)
    monkeypatch.setattr(pm, "AREA_PLAYER_COUNT", 2)
    assert hunt_area.rotate_reason(state, board) == "nearby players"


def test_adena_count_from_inventory_snapshot():
    from app._03_world.memory_inventory import inventory_state_from_snapshot

    state = inventory_state_from_snapshot(
        {
            "items": [
                {"id": 5, "count": 1100, "name": "아데나"},
                {"id": 76, "count": 2, "name": "해독제"},
            ]
        }
    )
    assert state.adena == 1100
    assert state.depoison == 2


def test_attack_jitter_widens_interval():
    prev_on = hz.ATTACK_JITTER_ENABLED
    prev_ms = hz.ATTACK_JITTER_MS
    hz.ATTACK_JITTER_ENABLED = False
    base = hz.attack_gap((0.15, 0.25))
    hz.ATTACK_JITTER_ENABLED = True
    hz.ATTACK_JITTER_MS = 120
    wide = hz.attack_gap((0.15, 0.25))
    hz.ATTACK_JITTER_ENABLED = prev_on
    hz.ATTACK_JITTER_MS = prev_ms
    assert abs(base - 0.20) < 1e-6
    assert abs(wide - 0.20) < 1e-6
    lo, hi = 0.15, 0.25
    pad = 0.12
    assert (max(0.02, lo - pad) + max(lo, hi + pad)) / 2 == wide


def test_jitter_ms_clamped_to_10_50():
    assert clamp_jitter_ms(9) == 10
    assert clamp_jitter_ms(10) == 10
    assert clamp_jitter_ms(50) == 50
    assert clamp_jitter_ms(200) == 50
    profile = Profile()
    task = ScheduleStore().create(profile)
    hunt = task.settings["hunt"]
    hunt["attack_jitter_ms"] = 5
    hunt["target_delay_min_ms"] = 5
    hunt["target_delay_max_ms"] = 90
    apply_runtime_settings(task, profile)
    assert profile.attack_jitter_ms == 10
    assert profile.target_delay_min_ms == 10
    assert profile.target_delay_max_ms == 50


def test_return_checkboxes_stay_off_when_unchecked():
    profile = Profile()
    task = ScheduleStore().create(profile)
    hunt = task.settings["hunt"]
    hunt["return_mp_enabled"] = False
    hunt["return_potion_enabled"] = False
    hunt["return_arrow_enabled"] = False
    hunt["return_weight_enabled"] = False
    hunt["attack_jitter"] = False
    hunt["target_delay"] = False
    hunt["antidote_auto"] = False
    apply_runtime_settings(task, profile)
    assert profile.return_mp_enabled is False
    assert profile.return_potion_enabled is False
    assert profile.return_arrow_enabled is False
    assert profile.return_weight_enabled is False
    assert profile.attack_jitter is False
    assert profile.target_delay is False
    assert profile.antidote_auto is False
