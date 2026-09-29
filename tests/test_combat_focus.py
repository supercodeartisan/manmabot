"""Loot first unless a close sticky kill or a monster within 5 tiles."""
from __future__ import annotations

import time
from types import SimpleNamespace

from app._03_world.objects import ObjectStatus, ObjectType, WorldObject
from app._04_decision.behavior_tree import Status
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors.combat import (
    begin_engage,
    continue_sticky_combat,
    sticky_target_alive,
)
from app._04_decision.behaviors.mode_actions import (
    _record_hp_ratio,
    farm_loot_or_combat,
    hp_spike_drop,
)


def _monster(
    *,
    track_id: int = 7,
    status: ObjectStatus = ObjectStatus.ALIVE,
    rx: int = 1,
    ry: int = 0,
) -> WorldObject:
    return WorldObject(
        track_id=track_id,
        object_type=ObjectType.MONSTER,
        species_name="monster_오크",
        status=status,
        world_rx=rx,
        world_ry=ry,
    )


def _state(obj: WorldObject | None, *, missed: int = 0):
    return _state_many([] if obj is None else [obj], missed=missed)


def _state_many(objs: list[WorldObject], *, missed: int = 0):
    by_id = {item.track_id: item for item in objs}
    return SimpleNamespace(
        get_object=lambda tid: by_id.get(tid),
        missing_frames=lambda _tid: missed,
        monsters=lambda: list(objs),
    )


def _patch_loot_combat(monkeypatch, called: list[str]) -> None:
    from app._04_decision.behaviors import mode_actions

    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_combat",
        lambda *_args, **_kwargs: called.append("combat") or Status.SUCCESS,
    )
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_loot",
        lambda *_args, **_kwargs: called.append("loot") or Status.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "clear_loot_hop", lambda *_args, **_kwargs: None)


def test_sticky_keeps_living_target_past_ten_seconds() -> None:
    obj = _monster()
    state = _state(obj)
    board = Blackboard()
    board.current_target_id = obj.track_id
    board.current_target_species = "monster_오크"
    board.target_engage_started = time.time() - 120
    assert sticky_target_alive(state, obj.track_id)
    assert continue_sticky_combat(state, board) is True
    assert board.current_target_id == obj.track_id


def test_sticky_drops_dead_or_lost_target() -> None:
    dead = _monster(status=ObjectStatus.DEAD)
    board = Blackboard()
    board.current_target_id = dead.track_id
    board.current_target_species = "monster_오크"
    board.current_target_world = (1, 0)
    board.target_engage_started = time.time()
    assert continue_sticky_combat(_state(dead), board) is False
    assert board.current_target_id is None
    assert board.current_target_species is None

    board = Blackboard()
    board.current_target_id = 99
    board.current_target_species = "monster_오크"
    board.current_target_world = (1, 0)
    assert continue_sticky_combat(_state(None), board) is False
    assert board.current_target_id is None
    assert board.current_target_species is None


def test_sticky_rebinds_when_entity_id_changes() -> None:
    first = _monster(track_id=7)
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    rebound = _monster(track_id=88)
    assert continue_sticky_combat(_state(rebound), board) is True
    assert board.current_target_id == 88
    assert board.current_target_species == "monster_오크"


def test_sticky_rebind_keeps_last_cell_not_closer_mob() -> None:
    first = _monster(track_id=7, rx=2, ry=0)
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    same_cell = _monster(track_id=88, rx=2, ry=0)
    nearer = _monster(track_id=11, rx=1, ry=0)
    assert continue_sticky_combat(_state_many([nearer, same_cell]), board) is True
    assert board.current_target_id == same_cell.track_id


def test_sticky_rebinds_nearest_same_species_when_window_empty_without_death() -> None:
    first = _monster(track_id=7, rx=1, ry=0)
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    other = _monster(track_id=88, rx=4, ry=0)
    assert continue_sticky_combat(_state(other), board) is True
    assert board.current_target_id == other.track_id


def test_sticky_omit_without_death_clears_when_no_same_species() -> None:
    obj = _monster()
    board = Blackboard()
    begin_engage(_state(obj), board, obj.track_id)
    ghost = _state(obj, missed=1)
    ghost.last_print_state = {"entities": []}
    assert sticky_target_alive(ghost, obj.track_id) is False
    assert continue_sticky_combat(ghost, board) is False
    assert board.current_target_id is None
    assert board.current_target_species is None
    assert obj.status is not ObjectStatus.DEAD


def test_sticky_confirms_death_only_with_species_dead_in_window() -> None:
    first = _monster(track_id=7, rx=1, ry=0)
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    corpse = _monster(track_id=7, status=ObjectStatus.DEAD, rx=1, ry=0)
    assert continue_sticky_combat(_state(corpse), board) is False
    assert board.current_target_id is None
    assert board.current_target_species is None


def test_sticky_drops_after_one_miss_without_print_state() -> None:
    obj = _monster()
    board = Blackboard()
    begin_engage(_state(obj), board, obj.track_id)
    assert continue_sticky_combat(_state(obj, missed=0), board) is True
    assert continue_sticky_combat(_state(obj, missed=2), board) is True
    assert board.current_target_id == obj.track_id
    assert board.current_target_species == "monster_오크"


def _fake_nearest(obj):
    from app._04_decision.combat_query import (
        in_near_monster_box,
        tile_distance_from_player,
    )

    def nearest(*_a, near_box=False, near_tiles=None, screen_only=False, **_k):
        if obj is None:
            return None
        if near_tiles is not None:
            if tile_distance_from_player(obj) > int(near_tiles):
                return None
        elif near_box and not in_near_monster_box(obj):
            return None
        if screen_only:
            from app._04_decision.combat_query import object_on_screen

            if not object_on_screen(obj):
                return None
        return obj

    return nearest


def test_near_monster_box_is_four_by_five() -> None:
    from app._04_decision.combat_query import in_near_monster_box

    assert in_near_monster_box(_monster(rx=4, ry=5)) is True
    assert in_near_monster_box(_monster(rx=5, ry=0)) is False
    assert in_near_monster_box(_monster(rx=0, ry=6)) is False
    assert in_near_monster_box(_monster(rx=-4, ry=-5)) is True


def test_loot_approach_threat_is_five_tiles() -> None:
    from app._04_decision.combat_query import in_loot_approach_threat

    assert in_loot_approach_threat(_monster(rx=5, ry=0)) is True
    assert in_loot_approach_threat(_monster(rx=4, ry=5)) is True
    assert in_loot_approach_threat(_monster(rx=6, ry=0)) is False
    assert in_loot_approach_threat(_monster(rx=0, ry=6)) is False


def test_attack_click_range_covers_zero_to_eight() -> None:
    from app._03_world.objects import Position
    from app._04_decision.combat_query import in_attack_click_range
    from app._04_decision import player_mode as pm

    assert pm.ATTACK_CLICK_TILES == 8
    assert pm.STICKY_LOOT_HOLD_TILES == 2
    assert pm.LOOT_KEEP_TILES == 8
    assert in_attack_click_range(_monster(rx=0, ry=0)) is True
    assert in_attack_click_range(_monster(rx=7, ry=0)) is True
    assert in_attack_click_range(_monster(rx=8, ry=0)) is True
    off = _monster(rx=9, ry=0)
    off.position = Position(1.2, 0.5)
    assert in_attack_click_range(off) is False
    seen = _monster(rx=12, ry=0)
    seen.position = Position(0.4, 0.5)
    assert in_attack_click_range(seen) is True


def test_sticky_holds_loot_only_within_two_tiles() -> None:
    from app._04_decision.combat_query import sticky_holds_loot

    assert sticky_holds_loot(_monster(rx=2, ry=0)) is True
    assert sticky_holds_loot(_monster(rx=1, ry=1)) is True
    assert sticky_holds_loot(_monster(rx=3, ry=0)) is False


def test_surround_count_uses_two_tile_disk() -> None:
    from app._04_decision.combat_query import count_monsters_within_tiles
    from app._04_decision import player_mode as pm

    close = [_monster(track_id=i, rx=2, ry=0) for i in range(4)]
    mixed = close[:3] + [_monster(track_id=99, rx=5, ry=0)]
    assert count_monsters_within_tiles(_state_many(close), pm.SURROUND_TILES) == 4
    assert count_monsters_within_tiles(_state_many(mixed), pm.SURROUND_TILES) == 3
    assert pm.SURROUND_TILES == 2


def test_emergency_teleport_requires_four_within_two_tiles(monkeypatch) -> None:
    from app._03_world import ActionType
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors.mode_ticks import _maybe_emergency_teleport
    from app._05_action.spell_box import configure_spell_box

    monkeypatch.setattr(pm, "RANDOM_TELEPORT_ENABLED", True)
    monkeypatch.setattr(pm, "TELEPORT_WHEN_SURROUNDED", True)
    monkeypatch.setattr(pm, "TELEPORT_ON_PLAYER", False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    try:
        close = [_monster(track_id=i, rx=2, ry=0) for i in range(4)]
        board = Blackboard()
        result = _maybe_emergency_teleport(_state_many(close), board)
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action is ActionType.TELEPORT
        assert "surrounded x4" in board.intent.reason

        far_mix = close[:3] + [_monster(track_id=99, rx=6, ry=0)]
        board = Blackboard()
        assert _maybe_emergency_teleport(_state_many(far_mix), board) is None
        assert board.intent is None
    finally:
        configure_spell_box()


def test_farm_fights_after_loot_cursor_miss(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    close = _monster(track_id=3, rx=4, ry=0)
    called: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_combat",
        lambda *_args, **_kwargs: called.append("combat") or Status.SUCCESS,
    )
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_loot",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mode_actions, "clear_loot_hop", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(close))
    board = Blackboard()
    board.current_item_id = 99
    board.scratch["loot_click_failed"] = True
    result = farm_loot_or_combat(_state(close), board)
    assert result is Status.SUCCESS
    assert called == ["combat"]
    assert "loot_click_failed" not in board.scratch


def test_farm_loots_melee_monster_when_item_available(monkeypatch) -> None:
    """Loot priority #1: nearby monster does not interrupt sticky loot."""
    from app._04_decision.behaviors import mode_actions

    close = _monster(track_id=3, rx=2, ry=1)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(close))
    board = Blackboard()
    board.current_item_id = 99
    result = farm_loot_or_combat(_state(close), board)
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_farm_loots_five_tile_monster_when_item_available(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    close = _monster(track_id=3, rx=5, ry=0)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(close))
    board = Blackboard()
    board.current_item_id = 99
    result = farm_loot_or_combat(_state(close), board)
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_farm_loots_when_standing_and_monster_is_beyond_five(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    far = _monster(track_id=3, rx=6, ry=0)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(far))
    board = Blackboard()
    board.current_item_id = 99
    result = farm_loot_or_combat(_state(far), board)
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_farm_keeps_looting_while_walking_even_with_five_tile_threat(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    close = _monster(track_id=3, rx=5, ry=0)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(close))
    board = Blackboard()
    board.current_item_id = 99
    board.loot_approach_active = True
    result = farm_loot_or_combat(_state(close), board)
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_farm_keeps_looting_when_walk_threat_is_beyond_five(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    far = _monster(track_id=3, rx=6, ry=0)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(far))
    board = Blackboard()
    board.loot_approach_active = True
    result = farm_loot_or_combat(_state(far), board)
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_farm_loots_when_monster_is_outside_near_box(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    far = _monster(track_id=3, rx=8)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(far))
    result = farm_loot_or_combat(_state(None), Blackboard())
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_cursor_fail_does_not_drop_living_monster() -> None:
    from app._04_decision.attack_feedback import note_cursor_verify_fail

    obj = _monster()
    board = Blackboard()
    begin_engage(_state(obj), board, obj.track_id)
    for _ in range(8):
        assert note_cursor_verify_fail(board, obj.track_id, is_item=False) is False
    assert board.current_target_id == obj.track_id


def test_seven_tile_monster_is_attackable_without_walk_path(monkeypatch) -> None:
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.combat_query import list_attackable

    far = _monster(track_id=3, rx=7, ry=0)
    far.world_cx = 17
    far.world_cy = 10
    state = _state(far)
    state.player = None
    monkeypatch.setattr(
        "app._04_decision.combat_query.attack_path_clickable",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.dungeon.is_dungeon_map",
        lambda: False,
    )
    kept = list_attackable(
        state, origin=WorldOrigin(x=10, y=10), check_path=True
    )
    assert [obj.track_id for obj in kept] == [3]


def test_adjacent_blocked_tile_is_still_attackable(monkeypatch) -> None:
    import numpy as np

    from app._03_world.terrain_map import TerrainMap
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.combat_query import attack_path_clickable

    walkable = np.ones((20, 20), dtype=bool)
    walkable[10, 11] = False
    terrain = TerrainMap(walkable=walkable)
    origin = WorldOrigin(x=10, y=10)
    monkeypatch.setattr(
        "app._04_decision.combat_query.object_absolute_tile",
        lambda *_a, **_k: (11, 10),
    )
    assert attack_path_clickable(_monster(), origin, terrain) is True


def test_farm_finishes_far_sticky_before_loot(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    far = _monster(track_id=7, rx=8)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(far))
    board = Blackboard()
    begin_engage(_state(far), board, far.track_id)
    result = farm_loot_or_combat(_state(far), board)
    assert result is Status.SUCCESS
    assert called == ["combat"]


def test_five_unmoved_attacks_keep_living_sticky() -> None:
    from app._03_world import ActionType
    from app._04_decision.behaviors.mode_actions import continue_or_start_combat

    obj = _monster(rx=3, ry=0)
    state = _state(obj)
    board = Blackboard()
    begin_engage(state, board, obj.track_id)
    for _ in range(6):
        assert continue_or_start_combat(state, board, allow_new=False) is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action is ActionType.ATTACK
    assert board.current_target_id == obj.track_id


def test_farm_loots_when_sticky_gone_without_species_or_death(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    first = _monster(track_id=7, rx=1, ry=0)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", lambda *_a, **_k: None)
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    result = farm_loot_or_combat(_state(None), board)
    assert result is Status.SUCCESS
    assert called == ["loot"]
    assert board.current_target_id is None
    assert board.current_target_species is None


def test_farm_takes_new_species_when_sticky_vanished_without_death(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    first = _monster(track_id=7, rx=1, ry=0)
    other = WorldObject(
        track_id=88,
        object_type=ObjectType.MONSTER,
        species_name="monster_늑대",
        status=ObjectStatus.ALIVE,
        world_rx=2,
        world_ry=0,
    )
    called: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_combat",
        lambda *_args, **_kwargs: called.append("combat") or Status.SUCCESS,
    )
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_loot",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mode_actions, "clear_loot_hop", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(other))
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    result = farm_loot_or_combat(_state(other), board)
    assert result is Status.SUCCESS
    assert called == ["combat"]
    assert board.current_target_species is None

def test_farm_does_not_loot_while_living_sticky_unmoved(monkeypatch) -> None:
    from app._03_world import ActionType
    from app._04_decision.behaviors.mode_actions import continue_or_start_combat

    obj = _monster(rx=6, ry=0)
    state = _state(obj)
    board = Blackboard()
    begin_engage(state, board, obj.track_id)
    looted = {"n": 0}

    def _loot(*_a, **_k):
        looted["n"] += 1
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.continue_or_start_loot",
        _loot,
    )
    for _ in range(6):
        result = farm_loot_or_combat(state, board)
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action is ActionType.ATTACK
        assert board.current_target_id == obj.track_id
    assert looted["n"] == 0
    assert continue_or_start_combat(state, board, allow_new=False) is Status.SUCCESS


def test_monster_tile_change_resets_unmoved_attacks() -> None:
    from app._03_world import ActionType
    from app._04_decision.behaviors.mode_actions import continue_or_start_combat

    obj = _monster(rx=3, ry=0)
    state = _state(obj)
    board = Blackboard()
    begin_engage(state, board, obj.track_id)
    for _ in range(4):
        assert continue_or_start_combat(state, board, allow_new=False) is Status.SUCCESS
    obj.world_rx = 4
    for _ in range(4):
        assert continue_or_start_combat(state, board, allow_new=False) is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action is ActionType.ATTACK
    assert board.current_target_id == obj.track_id


def test_farm_resumes_far_sticky_when_no_loot(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    far = _monster(track_id=7, rx=8)
    called: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_combat",
        lambda *_args, **_kwargs: called.append("combat") or Status.SUCCESS,
    )
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_loot",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(far))
    board = Blackboard()
    begin_engage(_state(far), board, far.track_id)
    result = farm_loot_or_combat(_state(far), board)
    assert result is Status.SUCCESS
    assert called == ["combat"]


def test_farm_attacks_window_monster_when_no_loot(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    far = _monster(track_id=3, rx=8)
    called: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_combat",
        lambda *_args, **_kwargs: called.append("combat") or Status.SUCCESS,
    )
    monkeypatch.setattr(
        mode_actions,
        "continue_or_start_loot",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(far))
    result = farm_loot_or_combat(_state(None), Blackboard())
    assert result is Status.SUCCESS
    assert called == ["combat"]


def test_farm_rebounds_close_target_after_id_change(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    first = _monster(track_id=7, rx=1)
    rebound = _monster(track_id=88, rx=1)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(rebound))
    board = Blackboard()
    begin_engage(_state(first), board, first.track_id)
    result = farm_loot_or_combat(_state(rebound), board)
    assert result is Status.SUCCESS
    assert called == ["combat"]
    assert board.current_target_id == 88


def test_farm_finishes_close_target_before_adena(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    close = _monster(track_id=7, rx=1)
    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", _fake_nearest(close))
    board = Blackboard()
    board.current_target_id = 7
    board.current_item_id = 5
    result = farm_loot_or_combat(_state(close), board)
    assert result is Status.SUCCESS
    assert called == ["combat"]


def test_farm_loots_only_when_no_attackable(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions

    called: list[str] = []
    _patch_loot_combat(monkeypatch, called)
    monkeypatch.setattr(mode_actions, "nearest_attackable", lambda *_a, **_k: None)
    result = farm_loot_or_combat(_state(None), Blackboard())
    assert result is Status.SUCCESS
    assert called == ["loot"]


def test_hp_spike_drop_detects_fast_loss() -> None:
    board = Blackboard()
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 0.4, 0.92)]
    _record_hp_ratio(board, 0.60)
    assert hp_spike_drop(board) is True
    quiet = Blackboard()
    quiet.scratch["hp_ratio_hist"] = [(now - 0.4, 0.80)]
    _record_hp_ratio(quiet, 0.78)
    assert hp_spike_drop(quiet) is False


def test_hp_spike_drop_survives_slow_combat_tick() -> None:
    """Decide/act gaps above the old 0.5s window must still count as a spike."""
    board = Blackboard()
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 1.2, 0.90)]
    _record_hp_ratio(board, 0.65)
    assert hp_spike_drop(board) is True


def test_hp_spike_drop_detects_accumulated_window() -> None:
    board = Blackboard()
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 0.4, 0.90), (now - 0.2, 0.80)]
    _record_hp_ratio(board, 0.68)
    assert hp_spike_drop(board) is True
    short = Blackboard()
    short.scratch["hp_ratio_hist"] = [(now - 0.4, 0.90), (now - 0.2, 0.80)]
    _record_hp_ratio(short, 0.75)
    assert hp_spike_drop(short) is False


def test_apply_hp_actions_escapes_on_nearby_spike(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.behavior_tree import Status as St
    from app._04_decision.player_mode import PlayerMode

    chosen: list[str] = []
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 0.3, 0.90)]

    monkeypatch.setattr(mode_actions, "_nearby_monster_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": True,
            "hp_potion": True,
            "mother_tree": False,
            "teleport": True,
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: chosen.append(action_id) or St.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )

    # apply_hp_actions imports hp_ratio from mode_control — patch that path.
    monkeypatch.setattr(
        "app._04_decision.mode_control.hp_ratio",
        lambda _state: 0.58,
    )
    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is St.SUCCESS
    assert chosen == ["teleport"]


def test_apply_hp_actions_spike_falls_back_to_safe_zone(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.behavior_tree import Status as St
    from app._04_decision.player_mode import PlayerMode

    chosen: list[str] = []
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 0.3, 0.90)]

    monkeypatch.setattr(mode_actions, "_nearby_monster_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": False,
            "hp_potion": False,
            "mother_tree": False,
            "teleport": False,
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: chosen.append(action_id) or St.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.mode_control.hp_ratio",
        lambda _state: 0.58,
    )
    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is St.SUCCESS
    assert chosen == ["safe_zone"]


def test_apply_hp_actions_uses_heal_same_tick_when_spike_cannot_escape(monkeypatch) -> None:
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.behavior_tree import Status as St
    from app._04_decision.player_mode import PlayerMode
    from manmabot_v1.hp_actions import to_engine_actions
    from app._04_decision.configure import configure_decision

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "heal", "enabled": True, "hp_below": 55},
                            {"id": "hp_potion", "enabled": True, "hp_below": 55},
                            {"id": "teleport", "enabled": True, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    chosen: list[str] = []
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 0.3, 0.90)]

    monkeypatch.setattr(mode_actions, "_nearby_monster_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": True,
            "hp_potion": True,
            "mother_tree": False,
            "teleport": False,
            "safe_zone": False,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: chosen.append(action_id) or St.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.mode_control.hp_ratio",
        lambda _state: 0.50,
    )
    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is St.SUCCESS
    assert chosen == ["heal"]


def test_heal_presses_skill_without_clicking_self() -> None:
    from app._03_world import CharacterType
    from app._05_action.controller import ActionExecutor

    exe = ActionExecutor(enabled=False, character=CharacterType.ELF, humanize=False)
    pressed: list[str] = []
    clicked: list[object] = []
    exe._press_assigned_skill = lambda name, duration=None: pressed.append(name)
    exe.mouse.move_and_click = lambda *a, **k: clicked.append((a, k))
    exe._heal(object())
    assert pressed == ["heal"]
    assert clicked == []


def test_emit_heal_does_not_wait_for_magic_cooldown() -> None:
    from app._04_decision.behaviors.mode_actions import emit_heal
    from app._04_decision.behavior_tree import Status
    from app._04_decision.blackboard import Blackboard
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box({"heal": {"box": 1, "key": "f8", "enabled": True}})
    try:
        board = Blackboard()
        board.magic_last_cast = time.time()
        result = emit_heal(board, reason="low hp")
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action.value == "heal"
    finally:
        configure_spell_box()


def test_los_ignores_goal_tile_unwalkable() -> None:
    """Wall check is only between player and mob — goal cell may be blocked."""
    import numpy as np

    from app._03_world.terrain_map import TerrainMap
    from app._04_decision.dungeon import line_of_sight_clear

    walkable = np.ones((20, 20), dtype=bool)
    walkable[10, 15] = False  # monster standing tile
    terrain = TerrainMap(walkable=walkable)
    assert line_of_sight_clear(terrain, (10, 10), (15, 10)) is True
    walkable[10, 12] = False  # wall between
    assert line_of_sight_clear(terrain, (10, 10), (15, 10)) is False


def test_island_wall_blocks_engage_without_detour(monkeypatch) -> None:
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.combat_query import can_engage_target, list_attackable

    far = _monster(track_id=3, rx=4, ry=0)
    far.world_cx = 14
    far.world_cy = 10
    state = _state(far)
    state.player = None
    origin = WorldOrigin(x=10, y=10)
    monkeypatch.setattr(
        "app._04_decision.dungeon.is_dungeon_map",
        lambda: False,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.attack_line_clear",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.attack_path_clickable",
        lambda *_a, **_k: False,
    )
    assert can_engage_target(far, origin) is False
    assert list_attackable(state, origin=origin, check_path=True) == []


def test_island_wall_allows_engage_with_detour_path(monkeypatch) -> None:
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.combat_query import can_engage_target

    far = _monster(track_id=3, rx=4, ry=0)
    origin = WorldOrigin(x=10, y=10)
    monkeypatch.setattr(
        "app._04_decision.dungeon.is_dungeon_map",
        lambda: False,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.attack_line_clear",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.attack_path_clickable",
        lambda *_a, **_k: True,
    )
    assert can_engage_target(far, origin) is True


def test_sticky_keeps_target_when_wall_blocks(monkeypatch) -> None:
    """Sticky must not give up on wall alone — detour path handles movement."""
    from app._03_world.world_coords import WorldOrigin

    obj = _monster(track_id=7, rx=3, ry=0)
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    begin_engage(_state(obj), board, obj.track_id)
    monkeypatch.setattr(
        "app._04_decision.combat_query.can_engage_target",
        lambda *_a, **_k: False,
    )
    assert continue_sticky_combat(_state(obj), board) is True
    assert board.current_target_id == 7
    assert 7 not in board.given_up_target_ids


def test_emergency_teleport_cooldown_blocks_repeat(monkeypatch) -> None:
    from app._03_world import ActionType
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors import mode_ticks
    from app._05_action.spell_box import configure_spell_box

    monkeypatch.setattr(pm, "RANDOM_TELEPORT_ENABLED", True)
    monkeypatch.setattr(pm, "TELEPORT_WHEN_SURROUNDED", True)
    monkeypatch.setattr(pm, "TELEPORT_ON_PLAYER", False)
    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    close = [_monster(track_id=i, rx=2, ry=0) for i in range(4)]
    board = Blackboard()
    try:
        assert mode_ticks._maybe_emergency_teleport(_state_many(close), board) is Status.SUCCESS
        assert board.intent.action is ActionType.TELEPORT
        board.intent = None
        assert mode_ticks._maybe_emergency_teleport(_state_many(close), board) is None
        assert board.intent is None
        board.scratch[mode_ticks.SCRATCH_EMERGENCY_TP_AT] = time.time() - 9.0
        assert mode_ticks._maybe_emergency_teleport(_state_many(close), board) is Status.SUCCESS
    finally:
        configure_spell_box()


def test_emergency_teleport_runs_during_shop_trip(monkeypatch) -> None:
    from app._03_world import ActionType
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors.mode_ticks import _maybe_emergency_teleport
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP
    from app._05_action.spell_box import configure_spell_box

    monkeypatch.setattr(pm, "RANDOM_TELEPORT_ENABLED", True)
    monkeypatch.setattr(pm, "TELEPORT_WHEN_SURROUNDED", True)
    monkeypatch.setattr(pm, "TELEPORT_ON_PLAYER", False)
    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    close = [_monster(track_id=i, rx=2, ry=0) for i in range(4)]
    board = Blackboard()
    board.scratch[SCRATCH_SHOP_TRIP] = True
    try:
        result = _maybe_emergency_teleport(_state_many(close), board)
        assert result is Status.SUCCESS
        assert board.intent.action is ActionType.TELEPORT
    finally:
        configure_spell_box()
