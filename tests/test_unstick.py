"""Blocked-path recovery: 360° nearby clicks, then teleport / talking scroll."""
from __future__ import annotations

import math
from types import SimpleNamespace

from app._03_world import ActionType, CharacterType, ObjectType
from app._03_world.objects import WorldObject
from app._03_world.world_coords import WorldOrigin
from app._04_decision.blackboard import Blackboard
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.unstick import (
    combat_sidestep_tiles,
    inner_ring_exhausted,
    next_sweep_tile,
    reset_unstick_tries,
    try_combat_approach_unstick,
    try_combat_blocked_unstick,
    try_enter_farm_detour,
    try_confined_escape,
    try_movement_unstick,
    try_unstick_escape,
    walkable_around,
)
from app._04_decision import player_mode as pm


class _Terrain:
    def __init__(self, blocked: set[tuple[int, int]] | None = None) -> None:
        self.blocked = blocked or set()

    def is_walkable(self, x: int, y: int) -> bool:
        return (x, y) not in self.blocked


def test_walkable_around_is_compass_then_near() -> None:
    tiles = walkable_around(_Terrain(), (10, 10), 2)
    assert (10, 10) not in tiles
    assert (13, 10) not in tiles
    assert (12, 10) in tiles
    east = [(x, y) for x, y in tiles if math.atan2(y - 10, x - 10) == 0.0]
    assert east == [(11, 10), (12, 10)]


def test_inner_ring_exhausted_when_all_radius_two_tried() -> None:
    board = Blackboard()
    terrain = _Terrain()
    origin = (10, 10)
    while not inner_ring_exhausted(board, terrain, origin):
        assert next_sweep_tile(board, terrain, origin) is not None
    inner = walkable_around(terrain, origin, 2)
    tried = {tuple(item) for item in board.scratch["unstick_tried"]}
    assert inner
    assert all(tile in tried for tile in inner)


def test_inner_ring_exhausted_when_no_walkable_inner() -> None:
    board = Blackboard()
    blocked = {
        (10 + dx, 10 + dy)
        for dy in range(-2, 3)
        for dx in range(-2, 3)
        if not (dx == 0 and dy == 0)
    }
    terrain = _Terrain(blocked)
    assert walkable_around(terrain, (10, 10), 2) == []
    assert inner_ring_exhausted(board, terrain, (10, 10))


def test_movement_unstick_clicks_first_walkable(monkeypatch) -> None:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    terrain = _Terrain()
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: terrain,
    )
    assert try_movement_unstick(board, stuck=True, action=ActionType.TRAVELING)
    assert board.intent is not None
    assert board.intent.action is ActionType.TRAVELING
    assert board.intent.reason == "unstick nearby"
    tried = {tuple(item) for item in board.scratch["unstick_tried"]}
    assert len(tried) == 1


def test_movement_unstick_holds_during_sweep_gap(monkeypatch) -> None:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    terrain = _Terrain()
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: terrain,
    )
    assert try_movement_unstick(board, stuck=True)
    first = {tuple(item) for item in board.scratch["unstick_tried"]}
    board.intent = None
    assert try_movement_unstick(board, stuck=True) is True
    assert board.intent is None
    assert {tuple(item) for item in board.scratch["unstick_tried"]} == first


def test_escape_teleports_when_ready(monkeypatch) -> None:
    board = Blackboard()
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.spells.try_unstick_teleport",
        lambda _bb, **_k: True,
    )
    assert try_unstick_escape(board) is True
    assert board.scratch.get("unstick_escaped") is True
    assert "unstick_tried" not in board.scratch


def test_escape_scrolls_when_teleport_unavailable(monkeypatch) -> None:
    board = Blackboard()
    calls: list[str] = []

    def _scroll(_bb, **kwargs):
        calls.append(str(kwargs.get("reason")))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.spells.try_unstick_teleport",
        lambda _bb, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.talking_scroll_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.farm_return_scroll_spot",
        lambda: "giran_teleporter",
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll",
        _scroll,
    )
    assert try_unstick_escape(board) is True
    assert calls == ["unstick talking scroll"]


def test_escape_waits_until_inside_farm(monkeypatch) -> None:
    from app._04_decision.farm_area import FarmRect

    board = Blackboard()
    board.world_origin = WorldOrigin(x=1, y=1)
    farm = FarmRect(100, 100, 120, 120, name="hunt")
    escaped: list[bool] = []
    monkeypatch.setattr(
        "app._04_decision.nav_config.get_active_farm",
        lambda _index: farm,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.spells.try_unstick_teleport",
        lambda _bb, **_k: escaped.append(True) or True,
    )
    assert try_unstick_escape(board) is False
    assert escaped == []
    assert try_unstick_escape(board, allow_outside_farm=True) is True
    assert escaped == [True]
    board.world_origin = WorldOrigin(x=110, y=110)
    assert try_unstick_escape(board) is True
    assert escaped == [True, True]


def test_travel_path_fail_walks_around_before_escape(monkeypatch) -> None:
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel
    from app._04_decision.mode_control import PURPOSE_ENTER_FARM

    board = Blackboard()
    board.world_origin = WorldOrigin(x=1, y=1)
    board.travel_purpose = PURPOSE_ENTER_FARM
    start_travel(board, (110, 110), reason="enter farm area")
    terrain = _Terrain()
    monkeypatch.setattr(
        "app._04_decision.behaviors.travel.get_terrain_map",
        lambda: terrain,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: terrain,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.travel.plan_travel_click",
        lambda *_a, **_k: (None, [], None),
    )
    escaped: list[bool] = []
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.try_unstick_escape",
        lambda *_a, **_k: escaped.append(True) or True,
    )
    assert emit_travel_hop(board, reason="enter farm area", priority=0.25) is True
    assert escaped == []
    assert board.intent is not None
    assert board.intent.reason == "enter farm, walk around"
    assert board.nav_goal == (110, 110)


def test_enter_farm_detour_escapes_after_ring_exhausted(monkeypatch) -> None:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    terrain = _Terrain()
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: terrain,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.walkable_around",
        lambda *_a, **_k: [(11, 10)],
    )
    kwargs_seen: list[dict] = []
    walked: list[tuple[int, int]] = []

    def _escape(_bb, **kwargs):
        kwargs_seen.append(kwargs)
        return True

    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.try_unstick_escape",
        _escape,
    )
    assert try_enter_farm_detour(
        board, on_walk=lambda tile, _dest: walked.append(tile)
    ) is True
    assert walked == [(11, 10)]
    assert kwargs_seen == []
    board.scratch["enter_farm_detour_click_at"] = 0.0
    assert try_enter_farm_detour(
        board, on_walk=lambda tile, _dest: walked.append(tile)
    ) is True
    assert walked == [(11, 10)]
    assert kwargs_seen and kwargs_seen[0].get("allow_outside_farm") is True
    assert kwargs_seen[0].get("urgent") is True


def test_enter_farm_detour_does_not_change_movement_radius() -> None:
    assert pm.ENTER_FARM_DETOUR_RADIUS == 5
    assert pm.TRAVEL_UNSTICK_RADIUS == 3
    assert pm.TRAVEL_UNSTICK_INNER_RADIUS == 2


def test_combat_unstick_skips_adjacent_and_mages(monkeypatch) -> None:
    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_rx=1,
        world_ry=0,
    )
    state = SimpleNamespace(
        get_object=lambda _tid: mob,
        player=SimpleNamespace(character_type=CharacterType.KNIGHT),
        character_type=CharacterType.KNIGHT,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.tile_distance_from_player",
        lambda _obj: 1,
    )
    assert try_combat_approach_unstick(state, board) is False

    mage_state = SimpleNamespace(
        get_object=lambda _tid: mob,
        player=SimpleNamespace(character_type=CharacterType.MAGE),
        character_type=CharacterType.MAGE,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.tile_distance_from_player",
        lambda _obj: 5,
    )
    assert try_combat_approach_unstick(mage_state, board) is False


def test_combat_approach_unstick_never_runs_in_combat(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_rx=4,
        world_ry=0,
    )
    state = SimpleNamespace(
        get_object=lambda _tid: mob,
        player=SimpleNamespace(character_type=CharacterType.KNIGHT, hp=None),
        character_type=CharacterType.KNIGHT,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.tile_distance_from_player",
        lambda _obj: 4,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: _Terrain(),
    )
    board.scratch["unstick_combat_tile"] = [10, 10]
    board.scratch["unstick_combat_at"] = time.time() - 2.5
    assert try_combat_approach_unstick(state, board) is False
    assert board.intent is None


def test_unstick_wait_is_five_seconds() -> None:
    assert pm.TRAVEL_UNSTICK_SECONDS == 5.0
    assert pm.LOOT_APPROACH_STUCK_SECONDS == 5.0
    assert pm.COMBAT_BLOCKED_UNSTICK_SECONDS == 2.0
    assert pm.COMBAT_BLOCKED_UNSTICK_RADIUS == 2
    assert pm.ATTACK_CLICK_TILES == 8
    assert pm.UNSTICK_BURST_COUNT == 3
    assert pm.UNSTICK_BURST_WINDOW_S == 20.0
    assert pm.UNSTICK_CONFINED_TILES == 5
    assert pm.UNSTICK_CONFINED_SECONDS == 13.0
    assert pm.TRAVEL_UNSTICK_RADIUS == 3
    assert pm.TRAVEL_UNSTICK_INNER_RADIUS == 2
    reset_unstick_tries(Blackboard())


def _combat_state(mob: WorldObject, character=CharacterType.KNIGHT):
    return SimpleNamespace(
        get_object=lambda _tid: mob,
        player=SimpleNamespace(character_type=character, hp=None),
        character_type=character,
    )


def test_combat_sidestep_tiles_are_perpendicular() -> None:
    assert combat_sidestep_tiles((10, 10), (20, 10)) == [(10, 12), (10, 8)]
    assert combat_sidestep_tiles((10, 10), (10, 20)) == [(8, 10), (12, 10)]


def test_combat_blocked_unstick_waits_two_seconds(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_cx=20,
        world_cy=10,
        world_rx=10,
        world_ry=0,
    )
    state = _combat_state(mob)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: _Terrain(),
    )
    board.scratch["combat_block_tid"] = 7
    board.scratch["combat_block_tile"] = [20, 10]
    board.scratch["combat_block_at"] = time.time() - 1.5
    assert try_combat_blocked_unstick(state, board) is False
    assert board.intent is None


def test_combat_blocked_unstick_sidesteps_off_attack_line(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_cx=20,
        world_cy=10,
        world_rx=10,
        world_ry=0,
    )
    state = _combat_state(mob)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: _Terrain(),
    )
    escaped: list[bool] = []
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.try_unstick_escape",
        lambda *_a, **_k: escaped.append(True) or True,
    )
    board.scratch["combat_block_tid"] = 7
    board.scratch["combat_block_tile"] = [20, 10]
    board.scratch["combat_block_at"] = time.time() - 2.1
    assert try_combat_blocked_unstick(state, board) is True
    assert board.intent is not None
    assert board.intent.action is ActionType.SEARCHING
    assert board.intent.reason == "sidestep combat block"
    assert board.scratch.get("combat_block_sidestep") is True
    assert escaped == []


def test_combat_blocked_unstick_sidesteps_in_melee(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_cx=12,
        world_cy=10,
        world_rx=2,
        world_ry=0,
    )
    state = _combat_state(mob)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.get_terrain_map",
        lambda: _Terrain(),
    )
    board.scratch["combat_block_tid"] = 7
    board.scratch["combat_block_tile"] = [12, 10]
    board.scratch["combat_block_at"] = time.time() - 2.1
    assert try_combat_blocked_unstick(state, board) is True
    assert board.intent is not None
    assert board.intent.reason == "sidestep combat block"


def test_combat_blocked_unstick_gives_up_after_sidestep_fails(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_cx=20,
        world_cy=10,
        world_rx=10,
        world_ry=0,
    )
    state = _combat_state(mob)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    board.scratch["combat_block_tid"] = 7
    board.scratch["combat_block_tile"] = [20, 10]
    board.scratch["combat_block_at"] = time.time() - 2.1
    board.scratch["combat_block_sidestep"] = True
    assert try_combat_blocked_unstick(state, board) is False
    assert board.current_target_id is None
    assert 7 in board.given_up_target_ids


def test_combat_blocked_unstick_resets_when_monster_moves(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.current_target_id = 7
    board.world_origin = WorldOrigin(x=10, y=10)
    mob = WorldObject(
        track_id=7,
        object_type=ObjectType.MONSTER,
        world_cx=22,
        world_cy=10,
        world_rx=12,
        world_ry=0,
    )
    state = _combat_state(mob)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    board.scratch["combat_block_tid"] = 7
    board.scratch["combat_block_tile"] = [20, 10]
    board.scratch["combat_block_at"] = time.time() - 8.0
    board.scratch["combat_block_sidestep"] = True
    assert try_combat_blocked_unstick(state, board) is False
    assert board.intent is None
    assert board.current_target_id == 7
    assert tuple(board.scratch["combat_block_tile"]) == (22, 10)
    assert "combat_block_sidestep" not in board.scratch


def test_third_stuck_in_window_escapes(monkeypatch) -> None:
    import time

    from app._04_decision.behaviors import unstick as unstick_mod

    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    now = time.time()
    board.scratch["unstick_event_times"] = [now - 10.0, now - 5.0]
    escaped: list[bool] = []

    monkeypatch.setattr(
        unstick_mod,
        "try_unstick_escape",
        lambda _bb, **_k: escaped.append(True) or True,
    )
    monkeypatch.setattr(unstick_mod, "get_terrain_map", lambda: _Terrain())
    assert try_movement_unstick(board, stuck=True) is True
    assert escaped == [True]


def test_low_hp_skips_sweep_and_escapes(monkeypatch) -> None:
    from app._04_decision.behaviors import unstick as unstick_mod

    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    board.scratch["hp_ratio_hist"] = [(0.0, 0.10)]
    escaped: list[bool] = []

    monkeypatch.setattr(
        unstick_mod,
        "try_unstick_escape",
        lambda _bb, **kwargs: escaped.append(bool(kwargs.get("urgent"))) or True,
    )
    monkeypatch.setattr(unstick_mod, "get_terrain_map", lambda: _Terrain())
    assert try_movement_unstick(board, stuck=True) is True
    assert escaped == [True]
    assert board.intent is None


def test_teleport_on_live_hotbar_requires_skill_name() -> None:
    from app._04_decision.spells import teleport_on_live_hotbar

    empty = SimpleNamespace(last_hotbar={"slots": [{"name": "힐"}]})
    assert teleport_on_live_hotbar(empty) is False
    skill = SimpleNamespace(last_hotbar={"slots": [{"name": "텔레포트"}]})
    assert teleport_on_live_hotbar(skill) is True
    book = SimpleNamespace(last_hotbar={"slots": [{"name": "마법서 (텔레포트)"}]})
    assert teleport_on_live_hotbar(book) is False
    mass = SimpleNamespace(last_hotbar={"slots": [{"name": "매스 텔레포트"}]})
    assert teleport_on_live_hotbar(mass) is False


def test_unstick_teleport_skips_when_skill_missing_from_hotbar(monkeypatch) -> None:
    from app._04_decision.spells import try_unstick_teleport
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    board = Blackboard()
    try:
        assert try_unstick_teleport(
            board,
            ignore_cooldown=True,
            state=SimpleNamespace(last_hotbar={"slots": [{"name": "힐"}]}),
        ) is False
        assert try_unstick_teleport(
            board,
            ignore_cooldown=True,
            state=SimpleNamespace(last_hotbar={"slots": [{"name": "텔레포트"}]}),
        ) is True
        assert board.intent is not None
        assert board.intent.action == ActionType.TELEPORT
    finally:
        configure_spell_box()


def test_unstick_teleport_skips_when_mana_reserved(monkeypatch) -> None:
    """Known low MP must not claim TELEPORT success (scroll fallback can run)."""
    from app._04_decision.spells import try_unstick_teleport
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    board = Blackboard()
    low_mp = SimpleNamespace(
        last_hotbar={"slots": [{"name": "텔레포트"}]},
        player=SimpleNamespace(mp=3, max_mp=100),
    )
    try:
        assert try_unstick_teleport(
            board, ignore_cooldown=True, state=low_mp
        ) is False
        assert board.intent is None
    finally:
        configure_spell_box()


def test_confined_escape_scrolls_when_mana_blocks_teleport(monkeypatch) -> None:
    import time

    from app._04_decision.spells import try_unstick_teleport
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    board = Blackboard()
    board.world_origin = WorldOrigin(x=14, y=10)
    board.scratch["unstick_confined_origin"] = [10, 10]
    board.scratch["unstick_confined_since"] = time.time() - 13.1
    scrolled: list[dict] = []
    low_mp = SimpleNamespace(
        last_hotbar={"slots": [{"name": "텔레포트"}]},
        player=SimpleNamespace(mp=0, max_mp=50),
    )

    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.talking_scroll_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.farm_return_scroll_spot",
        lambda: "ti_spellbook",
    )

    def _scroll(_bb, **kwargs):
        scrolled.append(kwargs)
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll",
        _scroll,
    )
    try:
        assert try_unstick_teleport(
            board, ignore_cooldown=True, reason="check", state=low_mp
        ) is False
        assert try_confined_escape(board, state=low_mp) is True
        assert scrolled[0]["spot_id"] == "ti_spellbook"
    finally:
        configure_spell_box()


def test_confined_escape_after_thirteen_seconds_inside_five_tiles(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.world_origin = WorldOrigin(x=14, y=10)
    board.scratch["unstick_confined_origin"] = [10, 10]
    board.scratch["unstick_confined_since"] = time.time() - 13.1
    scrolled: list[dict] = []

    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.spells.try_unstick_teleport",
        lambda _bb, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.talking_scroll_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.farm_return_scroll_spot",
        lambda: "ti_spellbook",
    )

    def _scroll(_bb, **kwargs):
        scrolled.append(kwargs)
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll",
        _scroll,
    )
    assert try_confined_escape(board) is True
    assert scrolled[0]["spot_id"] == "ti_spellbook"
    assert scrolled[0]["reason"] == "unstick confined"


def test_confined_escape_uses_teleport_when_skill_on_hotbar(monkeypatch) -> None:
    import time

    board = Blackboard()
    board.world_origin = WorldOrigin(x=14, y=10)
    board.scratch["unstick_confined_origin"] = [10, 10]
    board.scratch["unstick_confined_since"] = time.time() - 13.1
    teleported: list[str] = []
    scrolled: list[bool] = []

    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.spells.try_unstick_teleport",
        lambda _bb, **kwargs: teleported.append(str(kwargs.get("reason"))) or True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll",
        lambda *_a, **_k: scrolled.append(True) or Status.SUCCESS,
    )
    assert try_confined_escape(board) is True
    assert teleported == ["unstick confined"]
    assert scrolled == []


def test_confined_escape_resets_when_leaving_five_tiles() -> None:
    import time

    board = Blackboard()
    board.world_origin = WorldOrigin(x=16, y=10)
    board.scratch["unstick_confined_origin"] = [10, 10]
    board.scratch["unstick_confined_since"] = time.time() - 13.1
    assert try_confined_escape(board) is False
    assert tuple(board.scratch["unstick_confined_origin"]) == (16, 10)


def test_confined_escape_does_not_fire_while_sticky_combat(monkeypatch) -> None:
    from app._04_decision.behaviors.mode_ticks import _maybe_confined_escape

    board = Blackboard()
    board.scratch["unstick_confined_origin"] = [10, 10]
    board.scratch["unstick_confined_since"] = 1.0
    fired: list[bool] = []

    monkeypatch.setattr(
        "app._04_decision.behaviors.combat.continue_sticky_combat",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.try_confined_escape",
        lambda *_args, **_kwargs: fired.append(True) or True,
    )
    assert _maybe_confined_escape(SimpleNamespace(), board) is None
    assert fired == []
    # Combat clears the bubble clock so fight seconds do not carry over.
    assert "unstick_confined_origin" not in board.scratch
    assert "unstick_confined_since" not in board.scratch
