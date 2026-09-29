"""Loot walks to a tile beside the pile before clicking it."""
from __future__ import annotations

from types import SimpleNamespace

from app._03_world import ActionType, ObjectType
from app._03_world.objects import Identity, Position, WorldObject
from app._03_world.world_coords import WorldOrigin
from app._04_decision.blackboard import Blackboard
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.loot_hop import (
    _nudge_content_off_item,
    _standing_to_pickup,
    begin_loot_item,
    loot_stand_tile,
    tick_loot_item,
)
from app._04_decision import player_mode as pm


def test_loot_stand_none_when_already_adjacent() -> None:
    assert loot_stand_tile((10, 10), (10, 11), None) is None
    assert loot_stand_tile((10, 10), (10, 10), None) is None


def test_loot_stand_walks_onto_the_pile_when_walkable() -> None:
    terrain = SimpleNamespace(is_walkable=lambda x, y: True)
    assert loot_stand_tile((10, 10), (15, 10), terrain) == (15, 10)


def test_loot_stand_picks_closest_walkable_neighbor() -> None:
    terrain = SimpleNamespace(is_walkable=lambda x, y: (x, y) != (15, 10))
    stand = loot_stand_tile((10, 10), (15, 10), terrain)
    assert stand in {(14, 9), (14, 10), (14, 11)}


def test_pickup_range_is_two_tiles() -> None:
    assert pm.LOOT_PICKUP_TILES == 2
    assert pm.LOOT_HOP_ARRIVE_TILES == 1
    assert pm.LOOT_APPROACH_STUCK_SECONDS == 5.0
    assert pm.ATTACK_CURSOR_SEARCH_TILES == 0.2
    assert pm.LOOT_CURSOR_SEARCH_TILES == 0.0
    assert pm.LOOT_PICKUP_SETTLE_S == 0.0


def test_standing_to_pickup_uses_absolute_tiles() -> None:
    origin = WorldOrigin(x=10, y=10)
    assert _standing_to_pickup(origin, (10, 11)) is True
    assert _standing_to_pickup(origin, (15, 10)) is False


def test_nudge_moves_click_off_the_pile() -> None:
    item = WorldObject(
        track_id=1,
        object_type=ObjectType.ITEM,
        position=Position(0.62, 0.41),
    )
    nudged = _nudge_content_off_item(Position(0.62, 0.41), item)
    assert abs(nudged.x - 0.62) > 0.02 or abs(nudged.y - 0.41) > 0.02


def test_pickup_uses_memory_delta_when_origin_is_stale(monkeypatch) -> None:
    item = WorldObject(
        track_id=5,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
        world_cx=32556,
        world_cy=32993,
        world_rx=0,
        world_ry=0,
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=0, y=0)
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.get_terrain_map",
        lambda: None,
    )
    begin_loot_item(board, item.track_id)
    status = tick_loot_item(SimpleNamespace(), board, item, fresh=True)
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.PICKUP
    assert board.intent.target_id == item.track_id


def test_far_item_approaches_stand_even_if_memory_says_close(monkeypatch) -> None:
    item = WorldObject(
        track_id=5,
        object_type=ObjectType.ITEM,
        position=Position(0.72, 0.38),
        world_rx=5,
        world_ry=0,
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.object_absolute_tile",
        lambda *_a, **_k: (15, 10),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.get_terrain_map",
        lambda: None,
    )
    begin_loot_item(board, item.track_id)
    status = tick_loot_item(SimpleNamespace(), board, item, fresh=True)
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.SEARCHING
    assert board.intent.target_id == item.track_id
    dest = board.intent.destination
    assert dest is not None
    first = dest
    board.intent = None
    status = tick_loot_item(SimpleNamespace(), board, item, fresh=False)
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.SEARCHING
    assert board.intent.mid_act is True
    assert board.intent.destination is first


def test_pickup_when_origin_is_on_pile_even_if_memory_delta_is_stale(
    monkeypatch,
) -> None:
    item = WorldObject(
        track_id=5,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
        world_cx=15,
        world_cy=10,
        world_rx=3,
        world_ry=0,
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=15, y=10)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.object_absolute_tile",
        lambda *_a, **_k: (15, 10),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.get_terrain_map",
        lambda: None,
    )
    begin_loot_item(board, item.track_id)
    status = tick_loot_item(SimpleNamespace(), board, item, fresh=True)
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.PICKUP


def test_loot_hop_arrive_picks_up_instead_of_replanning(monkeypatch) -> None:
    from app._03_world.objects import Identity

    item = WorldObject(
        track_id=5,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
        identity=Identity("아데나", 1.0),
        world_cx=15,
        world_cy=10,
        world_rx=1,
        world_ry=0,
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=14, y=10)
    board.current_item_id = 5
    board.loot_approach_active = True
    board.loot_approach_waypoint = (15, 10)
    board.loot_approach_destination = Position(0.55, 0.50)
    monkeypatch.setattr(
        "app._03_world.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.object_absolute_tile",
        lambda *_a, **_k: (15, 10),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.get_terrain_map",
        lambda: None,
    )
    status = tick_loot_item(SimpleNamespace(), board, item, fresh=False)
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.PICKUP


def test_confirmed_pickup_retries_until_memory_drops() -> None:
    """Await: re-click in range; do not return None (roam) while pile listed."""
    from app._04_decision.behaviors.loot_hop import (
        loot_awaiting_memory_gone,
        mark_loot_clicked,
    )
    from app._04_decision.behaviors.mode_actions import (
        continue_or_start_loot,
        farm_loot_or_combat,
    )

    item = WorldObject(
        track_id=8,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
        identity=Identity("아데나", 1.0),
        species_name="아데나",
        world_rx=0,
        world_ry=0,
    )
    board = Blackboard()
    mark_loot_clicked(board, item.track_id)

    class _StillThere:
        last_print_state = {"entities": [{"ent": "x"}]}
        player = None

        def monsters(self):
            return []

        def items(self):
            return [item]

        def get_object(self, _tid: int):
            return item

        def missing_frames(self, _tid: int) -> int:
            return 0

    still = _StillThere()
    assert loot_awaiting_memory_gone(still, board) is True
    result = farm_loot_or_combat(still, board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.PICKUP
    assert board.intent.reason == "pickup retry"
    assert board.loot_await_gone_id == item.track_id
    assert continue_or_start_loot(still, board, screen_only=False) is Status.SUCCESS

    class _Gone:
        last_print_state = {"entities": []}
        player = None

        def monsters(self):
            return []

        def items(self):
            return []

        def get_object(self, _tid: int):
            return None

        def missing_frames(self, _tid: int) -> int:
            return 1

    gone = _Gone()
    assert loot_awaiting_memory_gone(gone, board) is False
    assert farm_loot_or_combat(gone, board) is None
    assert board.loot_await_gone_id is None


def test_pending_pickup_reapproaches_when_walked_off(monkeypatch) -> None:
    from app._04_decision.behaviors import loot_hop
    from app._04_decision.behaviors.loot_hop import (
        mark_loot_clicked,
        try_finish_pending_pickup,
    )
    from app._04_decision.behavior_tree import Status as St

    item = WorldObject(
        track_id=8,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
        identity=Identity("아데나", 1.0),
        species_name="아데나",
        world_rx=5,
        world_ry=0,
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(100, 100)
    mark_loot_clicked(board, item.track_id)
    monkeypatch.setattr(loot_hop, "_in_pickup_range", lambda *_a, **_k: False)

    def _walk(*_a, **_k):
        board.emit(
            ActionType.SEARCHING,
            destination=Position(0.6, 0.5),
            target_id=8,
            priority=0.3,
            reason="walk onto item",
            mid_act=False,
        )
        return St.SUCCESS

    monkeypatch.setattr(loot_hop, "tick_loot_item", _walk)

    class _World:
        last_print_state = {"entities": [{"ent": "x"}]}
        player = SimpleNamespace(
            position=Position(0.5, 0.5),
            inventory=SimpleNamespace(weight_ratio=0.0),
        )

        def get_object(self, _tid: int):
            return item

        def missing_frames(self, _tid: int) -> int:
            return 0

    result = try_finish_pending_pickup(_World(), board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.SEARCHING
    assert board.loot_await_gone_id == item.track_id

def test_pickup_memory_wait_gives_up_after_timeout() -> None:
    import time

    from app._04_decision.behaviors.loot_hop import (
        loot_awaiting_memory_gone,
        mark_loot_clicked,
    )
    from app._04_decision import player_mode as pm

    item = WorldObject(
        track_id=8,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
    )
    board = Blackboard()
    mark_loot_clicked(board, item.track_id)
    board.loot_await_gone_since = time.time() - (pm.LOOT_AWAIT_GONE_S + 0.1)

    class _StillThere:
        last_print_state = {"entities": [{"ent": "x"}]}

        def get_object(self, _tid: int):
            return item

        def missing_frames(self, _tid: int) -> int:
            return 0

    assert loot_awaiting_memory_gone(_StillThere(), board) is False
    assert board.loot_await_gone_id is None


def test_loot_cursor_fails_abandon_unlootable_pile() -> None:
    from app._04_decision.attack_feedback import (
        CURSOR_VERIFY_FAIL_GIVE_UP,
        note_cursor_verify_fail,
    )

    board = Blackboard()
    board.current_item_id = 8
    for _ in range(CURSOR_VERIFY_FAIL_GIVE_UP - 1):
        assert note_cursor_verify_fail(board, 8, is_item=True) is False
        assert board.current_item_id == 8
    assert note_cursor_verify_fail(board, 8, is_item=True) is True
    assert board.current_item_id is None
    assert 8 in board.loot_clicked_ids
    assert 8 not in board.given_up_target_ids

def test_clicked_pile_is_not_reclicked_while_ghost_remains() -> None:
    from app._04_decision.behaviors.loot_hop import mark_loot_clicked, recently_clicked_loot
    from app._04_decision.behaviors.mode_actions import continue_or_start_loot

    item = WorldObject(
        track_id=8,
        object_type=ObjectType.ITEM,
        position=Position(0.5, 0.5),
        identity=Identity("아데나", 1.0),
        species_name="아데나",
        world_rx=0,
        world_ry=0,
    )
    board = Blackboard()
    board.tick_count = 10
    board.current_item_id = item.track_id
    mark_loot_clicked(board, item.track_id)
    board.loot_pickup_until = 0.0
    board.loot_await_gone_id = None
    board.loot_await_gone_since = 0.0
    assert recently_clicked_loot(board, item.track_id) is True
    assert board.current_item_id is None

    class _World:
        last_print_state = {"entities": [{"ent": "x"}]}
        player = SimpleNamespace(
            position=Position(0.5, 0.5),
            inventory=SimpleNamespace(weight_ratio=0.0),
        )

        def get_object(self, _tid: int):
            return item

        def items(self):
            return [item]

        def missing_frames(self, _tid: int) -> int:
            return 0

    assert continue_or_start_loot(_World(), board, screen_only=False) is None


def test_two_tile_memory_distance_picks_up(monkeypatch) -> None:
    item = WorldObject(
        track_id=8,
        object_type=ObjectType.ITEM,
        position=Position(0.58, 0.44),
        world_cx=32558,
        world_cy=32993,
        world_rx=2,
        world_ry=0,
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    monkeypatch.setattr(
        "app._04_decision.behaviors.loot_hop.get_terrain_map",
        lambda: None,
    )
    begin_loot_item(board, item.track_id)
    status = tick_loot_item(SimpleNamespace(), board, item, fresh=True)
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.PICKUP
