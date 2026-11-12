"""A live pile holds the world-nav route click."""
from __future__ import annotations

from types import SimpleNamespace

from app._02_state.enums import CharacterType
from app._02_state.geometry import WorldOrigin
from app._02_state.objects import ObjectStatus, ObjectType, Position, WorldObject
from app._02_state.player import PlayerState
from app._03_world import ActionType, GameState
from app._04_decision.blackboard import Blackboard
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.mode_actions import (
    continue_or_start_loot,
    farm_loot_or_combat,
)
from app._04_decision.behaviors.mode_ticks import _drive_world_nav


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


def _adena(track_id: int) -> WorldObject:
    return WorldObject(
        track_id=track_id,
        object_type=ObjectType.ITEM,
        position=Position(x=0.4, y=0.4),
        species_name="아데나",
        world_cx=320,
        world_cy=448,
        world_rx=5,
        world_ry=0,
        memory_guid=f"0x{track_id:X}",
        status=ObjectStatus.ALIVE,
    )


def _arm(state: GameState, obj: WorldObject) -> None:
    state.upsert_object(obj)
    state._missed_frames[obj.track_id] = 0


def _board() -> Blackboard:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=310, y=448)
    board.nav_goal = (382, 478)
    board.travel_purpose = "world_nav"
    board.travel_hop_active = True
    board.travel_unstick_active = True
    board.nav_waypoint = (383, 478)
    board.travel_destination = Position(x=0.2, y=0.2)
    board.search_hop_active = True
    board.search_waypoint = (300, 400)
    board.scratch["world_nav_session"] = SimpleNamespace(phase="walk", token="stay")
    return board


def test_loot_start_drops_the_route_hop(monkeypatch) -> None:
    state = _state()
    _arm(state, _adena(195))
    board = _board()

    def _tick(state, blackboard, item, *, fresh):
        del state, blackboard, item, fresh
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.tick_loot_item",
        _tick,
    )

    result = continue_or_start_loot(state, board, restrict_to_farm=False)

    assert result is Status.SUCCESS
    assert board.current_item_id == 195
    assert board.travel_hop_active is False
    assert board.travel_unstick_active is False
    assert board.nav_waypoint is None
    assert board.travel_destination is None
    assert board.search_hop_active is False
    assert board.nav_goal == (382, 478)
    assert board.travel_purpose == "world_nav"
    assert board.scratch["world_nav_session"].token == "stay"


def test_live_pile_holds_the_route_when_loot_emits_nothing(monkeypatch) -> None:
    state = _state()
    _arm(state, _adena(195))
    board = _board()
    board.current_item_id = 195
    ran: list[str] = []

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.hold_fire_outside_hunt",
        lambda state, blackboard: False,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.farm_loot_or_combat",
        lambda state, blackboard, *, restrict_to_farm=True: None,
    )

    def _nav(state, blackboard):
        del state, blackboard
        ran.append("nav")
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.world_nav.tick_world_nav",
        _nav,
    )

    result = _drive_world_nav(state, board)

    assert result is Status.SUCCESS
    assert ran == []
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert board.intent.reason == "loot before route"
    assert board.travel_hop_active is False
    assert board.nav_waypoint is None
    assert board.nav_goal == (382, 478)
    assert board.scratch["world_nav_session"].token == "stay"


def test_route_walks_when_the_pile_is_gone(monkeypatch) -> None:
    state = _state()
    board = _board()
    board.current_item_id = 195
    ran: list[str] = []

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.hold_fire_outside_hunt",
        lambda state, blackboard: False,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_ticks.farm_loot_or_combat",
        lambda state, blackboard, *, restrict_to_farm=True: None,
    )

    def _nav(state, blackboard):
        del state, blackboard
        ran.append("nav")
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.world_nav.tick_world_nav",
        _nav,
    )

    result = _drive_world_nav(state, board)

    assert result is Status.SUCCESS
    assert ran == ["nav"]
    assert board.nav_goal == (382, 478)


def test_confirmed_pile_stays_past_the_leader_radius(monkeypatch) -> None:
    state = _state()
    far = _adena(195)
    far.world_rx = 20
    far.world_ry = 0
    _arm(state, far)
    board = _board()
    board.current_item_id = 195
    board.scratch["party_leader_no_loot"] = True
    seen: list[int] = []

    def _tick(state, blackboard, item, *, fresh):
        del state, blackboard, fresh
        seen.append(int(item.track_id))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.tick_loot_item",
        _tick,
    )

    result = continue_or_start_loot(state, board, restrict_to_farm=False)

    assert result is Status.SUCCESS
    assert seen == [195]
    assert board.current_item_id == 195
    assert board.travel_hop_active is False
    assert board.nav_goal == (382, 478)


def test_a_second_pile_does_not_replace_the_confirmed_one(monkeypatch) -> None:
    state = _state()
    held = _adena(195)
    held.species_name = "철퇴"
    nearer = _adena(196)
    nearer.world_rx = 1
    nearer.world_ry = 0
    _arm(state, held)
    _arm(state, nearer)
    board = _board()
    board.current_item_id = 195
    seen: list[int] = []

    def _tick(state, blackboard, item, *, fresh):
        del state, blackboard, fresh
        seen.append(int(item.track_id))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.tick_loot_item",
        _tick,
    )

    result = continue_or_start_loot(state, board, restrict_to_farm=False)

    assert result is Status.SUCCESS
    assert seen == [195]
    assert board.current_item_id == 195


def test_an_open_pile_is_not_handed_to_a_new_monster(monkeypatch) -> None:
    state = _state()
    _arm(state, _adena(195))
    board = _board()
    board.current_item_id = 195
    hunted: list[str] = []

    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.continue_or_start_loot",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.nearest_attackable",
        lambda *args, **kwargs: hunted.append("hunt") or SimpleNamespace(track_id=9),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.nearest_attacks_me_force",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.rebind_sticky_target",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.continue_sticky_combat",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.prefer_attacked_me_sticky",
        lambda *args, **kwargs: False,
    )

    result = farm_loot_or_combat(state, board, restrict_to_farm=False)

    assert result is Status.SUCCESS
    assert hunted == []
    assert board.current_item_id == 195
    assert board.intent is not None
    assert board.intent.reason == "loot until pickup"
