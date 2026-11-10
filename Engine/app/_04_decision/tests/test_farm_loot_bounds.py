"""Hunt loot uses the active farm rect on every area."""
from __future__ import annotations

from app._02_state.enums import CharacterType
from app._02_state.geometry import WorldOrigin
from app._02_state.objects import ObjectStatus, ObjectType, Position, WorldObject
from app._02_state.player import PlayerState
from app._03_world import GameState
from app._04_decision.blackboard import Blackboard
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.mode_actions import continue_or_start_loot
from app._04_decision.behaviors.mode_ticks import (
    _enter_farm_if_needed,
    _step_farm_engage,
    _step_travel_engage,
)
from app._04_decision.dungeon_floor_route import PURPOSE_DUNGEON_FLOOR
from app._04_decision.farm_area import FarmRect
from app._04_decision.mode_control import PURPOSE_ENTER_FARM

FARM = FarmRect(305, 400, 367, 480, name="south")


def _state() -> GameState:
    player = PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        character_type=CharacterType.ELF,
        level=18,
    )
    state = GameState(player=player)
    state.last_print_state = {"entities": []}
    return state


def _adena(track_id: int, cell: tuple[int, int], rel: tuple[int, int]) -> WorldObject:
    return WorldObject(
        track_id=track_id,
        object_type=ObjectType.ITEM,
        position=Position(x=0.4, y=0.4),
        species_name="아데나",
        world_cx=cell[0],
        world_cy=cell[1],
        world_rx=rel[0],
        world_ry=rel[1],
        memory_guid=f"0x{track_id:X}",
        status=ObjectStatus.ALIVE,
    )


def _arm(state: GameState, obj: WorldObject) -> None:
    state.upsert_object(obj)
    state._missed_frames[obj.track_id] = 0


def _board() -> Blackboard:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=310, y=448)
    return board


def test_outside_adena_is_not_started(monkeypatch) -> None:
    state = _state()
    _arm(state, _adena(34, (297, 448), (-8, 0)))
    board = _board()
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.get_active_farm",
        lambda index: FARM,
    )

    result = continue_or_start_loot(state, board, restrict_to_farm=True)

    assert result is None
    assert board.current_item_id is None


def test_adena_inside_the_active_farm_is_started(monkeypatch) -> None:
    state = _state()
    _arm(state, _adena(30, (320, 448), (5, 0)))
    board = _board()
    seen: list[int] = []
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.get_active_farm",
        lambda index: FARM,
    )

    def _tick(state, blackboard, item, *, fresh):
        del state, blackboard, fresh
        seen.append(int(item.track_id))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.tick_loot_item",
        _tick,
    )

    result = continue_or_start_loot(state, board, restrict_to_farm=True)

    assert result is Status.SUCCESS
    assert seen == [30]
    assert board.current_item_id == 30


def test_sticky_outside_pile_is_dropped(monkeypatch) -> None:
    state = _state()
    _arm(state, _adena(34, (297, 448), (-8, 0)))
    board = _board()
    board.current_item_id = 34
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.get_active_farm",
        lambda index: FARM,
    )

    result = continue_or_start_loot(state, board, restrict_to_farm=True)

    assert result is None
    assert board.current_item_id is None


def test_farm_engage_uses_the_active_farm(monkeypatch) -> None:
    seen: dict[str, bool] = {}

    def _loot(state, blackboard, *, restrict_to_farm=True):
        del state, blackboard
        seen["restrict"] = restrict_to_farm
        return None

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.farm_loot_or_combat",
        _loot,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.hold_fire_outside_hunt",
        lambda state, blackboard: False,
    )

    assert _step_farm_engage(object(), Blackboard()) is None
    assert seen["restrict"] is True


def test_enter_farm_does_not_open_loot(monkeypatch) -> None:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=304, y=448)
    seen: dict[str, bool] = {}

    def _loot(state, blackboard, *, allow_new=True, restrict_to_farm=True, screen_only=True):
        del state, blackboard, allow_new, screen_only
        seen["restrict"] = restrict_to_farm
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.get_active_farm",
        lambda index: FARM,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.get_terrain_map",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.party_turret_active",
        lambda blackboard: False,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks._maybe_scroll_to_hunt_map",
        lambda state, blackboard: None,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.hold_fire_outside_hunt",
        lambda state, blackboard: False,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.continue_or_start_loot",
        _loot,
    )

    assert _enter_farm_if_needed(object(), board) is Status.SUCCESS
    assert seen["restrict"] is True


def test_enter_farm_travel_stays_in_the_rect(monkeypatch) -> None:
    seen: dict[str, bool] = {}

    def _loot(state, blackboard, *, restrict_to_farm=True):
        del state, blackboard
        seen["restrict"] = restrict_to_farm
        return None

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.farm_loot_or_combat",
        _loot,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.hold_fire_outside_hunt",
        lambda state, blackboard: False,
    )
    board = Blackboard()
    board.travel_purpose = PURPOSE_ENTER_FARM

    assert _step_travel_engage(object(), board) is None
    assert seen["restrict"] is True

    seen.clear()
    board.travel_purpose = PURPOSE_DUNGEON_FLOOR
    assert _step_travel_engage(object(), board) is None
    assert seen["restrict"] is False
