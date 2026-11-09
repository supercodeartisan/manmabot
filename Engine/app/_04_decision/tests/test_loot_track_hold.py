"""A blinked ground pile keeps its loot walk instead of handing the tick to search."""
from __future__ import annotations

import time

from app._02_state.enums import CharacterType
from app._02_state.geometry import WorldOrigin
from app._02_state.objects import ObjectStatus, ObjectType, Position, WorldObject
from app._02_state.player import InventoryItem, PlayerState
from app._03_world import ActionType, GameState
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors.mode_actions import continue_or_start_loot
from app._04_decision.behaviors.unstick import SCRATCH_TRIED
from app._04_decision.behavior_tree import Status

GUID = "0xC41F48F"
CELL = (406, 421)
KIND = "철퇴"


def _state() -> GameState:
    player = PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        character_type=CharacterType.ELF,
        level=9,
    )
    state = GameState(player=player)
    state.last_print_state = {"entities": []}
    return state


def _pile(
    track_id: int,
    *,
    guid: str = GUID,
    kind: str = KIND,
    cell: tuple[int, int] = CELL,
    missed: int = 0,
) -> WorldObject:
    obj = WorldObject(
        track_id=track_id,
        object_type=ObjectType.ITEM,
        position=Position(x=0.34, y=0.05),
        species_name=kind,
        world_cx=cell[0],
        world_cy=cell[1],
        memory_guid=guid,
        status=ObjectStatus.ALIVE,
    )
    return obj


def _board() -> Blackboard:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=400, y=431)
    board.current_item_id = 93
    board.loot_approach_active = True
    board.loot_approach_waypoint = (406, 425)
    board.loot_approach_destination = (0.4, 0.1)
    board.search_hop_active = True
    board.search_waypoint = (396, 435)
    board.scratch[SCRATCH_TRIED] = [[1, 0]]
    return board


def _arm(state: GameState, track_id: int, **kwargs) -> WorldObject:
    obj = _pile(track_id, **kwargs)
    state.upsert_object(obj)
    state._missed_frames[track_id] = int(kwargs.get("missed", 0))
    return obj


def test_same_guid_rebinds_id_and_keeps_approach(monkeypatch) -> None:
    state = _state()
    _arm(state, 93, missed=1)
    _arm(state, 100, missed=0)
    board = _board()
    seen: list[tuple[int, bool]] = []

    def _tick(state, blackboard, item, *, fresh):
        del state, blackboard
        seen.append((int(item.track_id), bool(fresh)))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.tick_loot_item",
        _tick,
    )
    result = continue_or_start_loot(state, board, restrict_to_farm=False)
    assert result is Status.SUCCESS
    assert board.current_item_id == 100
    assert seen == [(100, False)]
    assert board.loot_approach_active is True
    assert board.loot_approach_waypoint == (406, 425)
    assert board.search_hop_active is False
    assert board.search_waypoint is None
    assert board.scratch[SCRATCH_TRIED] == [[1, 0]]


def test_gap_under_two_seconds_does_not_search() -> None:
    state = _state()
    _arm(state, 93, missed=1)
    board = _board()
    board.scratch["loot_track_since"] = time.time() - 1.4
    result = continue_or_start_loot(state, board, restrict_to_farm=False)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert board.intent.reason == "loot track hold"
    assert board.current_item_id == 93
    assert board.loot_approach_active is True
    assert board.loot_approach_waypoint == (406, 425)
    assert board.search_hop_active is False
    assert board.search_waypoint is None
    assert board.scratch[SCRATCH_TRIED] == [[1, 0]]


def test_gap_past_two_seconds_releases_for_search() -> None:
    state = _state()
    _arm(state, 93, missed=1)
    board = _board()
    board.scratch["loot_track_guid"] = GUID
    board.scratch["loot_track_kind"] = KIND
    board.scratch["loot_track_cell"] = CELL
    board.scratch["loot_track_since"] = time.time() - 2.01
    result = continue_or_start_loot(state, board, restrict_to_farm=False)
    assert result is None
    assert board.intent is None
    assert board.current_item_id is None
    assert board.loot_approach_active is False


def test_bag_gain_does_not_wait() -> None:
    state = _state()
    _arm(state, 93, missed=1)
    bag = state.player.inventory
    bag.bag_ready = True
    bag.items.append(InventoryItem(name=KIND, quantity=2))
    board = _board()
    board.scratch["_loot_bag_base"] = (93, 1)
    board.scratch["loot_track_since"] = time.time()
    result = continue_or_start_loot(state, board, restrict_to_farm=False)
    assert result is None
    assert board.current_item_id is None
    assert board.intent is None


def test_dead_pile_does_not_wait() -> None:
    state = _state()
    obj = _arm(state, 93, missed=0)
    obj.status = ObjectStatus.DEAD
    board = _board()
    board.scratch["loot_track_since"] = time.time()
    result = continue_or_start_loot(state, board, restrict_to_farm=False)
    assert result is None
    assert board.current_item_id is None


def test_deleted_pile_without_a_twin_does_not_wait() -> None:
    state = _state()
    board = _board()
    board.scratch["loot_track_guid"] = GUID
    board.scratch["loot_track_kind"] = KIND
    board.scratch["loot_track_cell"] = CELL
    board.scratch["loot_track_since"] = time.time()
    result = continue_or_start_loot(state, board, restrict_to_farm=False)
    assert result is None
    assert board.current_item_id is None


def test_different_cell_kind_or_guid_does_not_rebind(monkeypatch) -> None:
    calls: list[int] = []

    def _tick(state, blackboard, item, *, fresh):
        del state, blackboard, fresh
        calls.append(int(item.track_id))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.tick_loot_item",
        _tick,
    )
    twins = (
        _pile(101, cell=(410, 421)),
        _pile(102, kind="단검"),
        _pile(103, guid="0xOTHER"),
    )
    for twin in twins:
        state = _state()
        _arm(state, 93, missed=1)
        state.upsert_object(twin)
        state._missed_frames[twin.track_id] = 0
        board = _board()
        result = continue_or_start_loot(state, board, restrict_to_farm=False)
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.reason == "loot track hold"
        assert board.current_item_id == 93
        assert board.loot_approach_waypoint == (406, 425)
    assert calls == []
