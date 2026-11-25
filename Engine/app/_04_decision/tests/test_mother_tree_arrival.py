"""World-tree stand: map change, then blessing, recast, or faster regen."""
from __future__ import annotations

import time
from dataclasses import replace

from app._02_state.enums import CharacterType
from app._02_state.objects import Position
from app._02_state.player import PlayerState, StatusEffect
from app._03_world import ActionType, GameState
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors.mode_ticks import (
    _note_field_vitals,
    _tick_mother_tree_retreat,
)
from app._04_decision.player_mode import PlayerMode
from app._04_decision.spells import maybe_hp_to_mp, maybe_hp_to_mp_at_tree


def _state(
    *,
    hp: int = 100,
    max_hp: int = 200,
    mp: int = 20,
    max_mp: int = 100,
    buffs: list | None = None,
) -> GameState:
    player = PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        character_type=CharacterType.ELF,
        hp=hp,
        max_hp=max_hp,
        mp=mp,
        max_mp=max_mp,
        level=40,
        buffs=list(buffs or []),
    )
    return GameState(player=player)


def _map(state: GameState, map_id: int) -> None:
    state.last_memory_snapshot = {
        "player": {"mapId": map_id, "mapIdOk": 1, "x": 33049, "y": 32340}
    }
    state.last_print_state = {"player": {"x": 33049, "y": 32340}}


def _stand(
    state: GameState,
    *,
    depart: int = 0,
    cast_age_s: float = 5.0,
) -> Blackboard:
    board = Blackboard()
    board.scratch["mother_tree_trip"] = "recharge"
    board.scratch["mother_tree_depart_pose"] = {
        "map_id": depart,
        "x": 32573,
        "y": 32946,
    }
    board.scratch["mother_tree_cast_at"] = time.time() - cast_age_s
    return board


def _set(state: GameState, **fields) -> None:
    state.set_player(replace(state.player, **fields))


def _trusted(state: GameState) -> None:
    state.last_buff = {"buffs": [{"name": "파워 업", "strId": 1}], "cache": 1}
    _set(
        state,
        buffs=[StatusEffect(name="파워 업", duration=30.0, str_id=1)],
    )


def _reason(board: Blackboard) -> str:
    intent = board.intent
    assert intent is not None
    return str(intent.reason)


def test_map_waits_until_the_settle() -> None:
    state = _state()
    _map(state, 0)
    _trusted(state)
    board = _stand(state, cast_age_s=0.2)
    assert _tick_mother_tree_retreat(state, board) is not None
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert _reason(board) == "waiting for mother tree map"


def test_same_map_retries_without_body_to_mind() -> None:
    state = _state(mp=5)
    _map(state, 0)
    _trusted(state)
    board = _stand(state)
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert _reason(board) == "waiting for mother tree mp"

    _set(state, mp=20)
    board.scratch["mother_tree_cast_at"] = time.time() - 5
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.RETURN_TO_MOTHER_TREE


def test_changed_map_without_blessing_converts_until_fifteen_mp() -> None:
    state = _state(hp=100, mp=5)
    _map(state, 4)
    _trusted(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.HP_TO_MP
    assert _reason(board) == "body to mind for mother tree"
    assert board.scratch.get("mother_tree_map_changed") is True


def test_changed_map_with_mana_recasts() -> None:
    state = _state(hp=100, mp=20)
    _map(state, 4)
    _trusted(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.RETURN_TO_MOTHER_TREE


def test_blessing_recovers_in_place() -> None:
    state = _state(hp=180, mp=90)
    _map(state, 4)
    state.last_buff = {
        "buffs": [{"name": "세계수의 가호", "strId": 993}],
        "cache": 1,
    }
    _set(
        state,
        buffs=[
            StatusEffect(
                name="세계수의 가호",
                duration=0.0,
                str_id=993,
                perpetual=True,
            )
        ],
    )
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert _reason(board) == "recharging at mother tree"
    assert board.scratch.get("mother_tree_zone") == "blessing"


def test_unread_buffs_recover_when_vitals_rise_faster(monkeypatch) -> None:
    clock = {"t": 1_000.0}
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    state = _state(hp=100, mp=40)
    _map(state, 4)
    state.last_buff = None
    board = _stand(state, depart=0)
    board.scratch["mother_tree_cast_at"] = clock["t"] - 5
    _tick_mother_tree_retreat(state, board)
    assert _reason(board) == "watching mother tree regen"

    clock["t"] = 1_002.0
    _set(state, hp=110, mp=48)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_zone") == "regen"
    assert _reason(board) == "recharging at mother tree"


def test_blessing_on_the_hunt_map_does_not_start_recovery() -> None:
    state = _state(hp=180, mp=20)
    _map(state, 0)
    state.last_buff = {
        "buffs": [{"name": "세계수의 가호", "strId": 993}],
        "cache": 1,
    }
    _set(
        state,
        buffs=[
            StatusEffect(
                name="세계수의 가호",
                duration=0.0,
                str_id=993,
                perpetual=True,
            )
        ],
    )
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.RETURN_TO_MOTHER_TREE
    assert board.scratch.get("mother_tree_zone") != "blessing"


def test_potion_sized_jump_is_not_the_aura(monkeypatch) -> None:
    clock = {"t": 2_000.0}
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    state = _state(hp=100, mp=40)
    _map(state, 4)
    state.last_buff = None
    board = _stand(state, depart=0)
    board.scratch["mother_tree_cast_at"] = clock["t"] - 5
    _tick_mother_tree_retreat(state, board)
    clock["t"] = 2_002.0
    _set(state, hp=160, mp=70)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_zone") != "regen"
    assert _reason(board) == "watching mother tree regen"


def test_low_hp_does_not_convert_for_the_recast() -> None:
    state = _state(hp=30, max_hp=200, mp=5)
    _map(state, 4)
    _trusted(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert _reason(board) == "waiting for hp to convert"


def test_field_body_to_mind_still_needs_the_blessing() -> None:
    state = _state(hp=180, mp=40)
    _trusted(state)
    board = Blackboard()
    assert maybe_hp_to_mp(state, board) is None
    board.scratch["mother_tree_zone"] = "regen"
    board.scratch["mother_tree_trip"] = "recharge"
    result = maybe_hp_to_mp_at_tree(state, board)
    assert result is not None
    assert board.intent is not None
    assert board.intent.action is ActionType.HP_TO_MP
    assert _reason(board) == "hp to mp at mother tree"


def _blessing(state: GameState) -> None:
    state.last_buff = {
        "buffs": [{"name": "세계수의 가호", "strId": 993}],
        "cache": 1,
    }
    _set(
        state,
        buffs=[
            StatusEffect(
                name="세계수의 가호",
                duration=0.0,
                str_id=993,
                perpetual=True,
            )
        ],
    )


def test_both_bars_almost_full_starts_the_return() -> None:
    state = _state(hp=190, max_hp=200, mp=95, max_mp=100)
    _map(state, 4)
    state.last_buff = None
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_trip") is None


def test_full_hp_and_low_mp_stays_to_convert() -> None:
    state = _state(hp=190, max_hp=200, mp=40, max_mp=100)
    _map(state, 4)
    _blessing(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_trip") == "recharge"
    assert board.intent is not None
    assert board.intent.action is ActionType.HP_TO_MP
    assert _reason(board) == "hp to mp at mother tree"


def test_full_hp_and_unknown_mp_does_not_leave() -> None:
    state = _state(hp=190, max_hp=200)
    _set(state, mp=None, max_mp=None)
    _map(state, 4)
    _blessing(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_trip") == "recharge"


def test_hp_under_the_line_does_not_leave_with_full_mp() -> None:
    state = _state(hp=189, max_hp=200, mp=100, max_mp=100)
    _map(state, 4)
    _blessing(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_trip") == "recharge"
    assert _reason(board) == "recharging at mother tree"


def test_full_hp_after_map_change_does_not_recast() -> None:
    state = _state(hp=190, max_hp=200, mp=40, max_mp=100)
    _map(state, 4)
    _trusted(state)
    board = _stand(state, depart=0)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_trip") == "recharge"
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert _reason(board) == "recharging at mother tree"


def test_full_hp_on_the_same_map_without_aura_still_recasts() -> None:
    state = _state(hp=190, max_hp=200, mp=40, max_mp=100)
    _map(state, 4)
    _trusted(state)
    board = _stand(state, depart=4)
    _tick_mother_tree_retreat(state, board)
    assert board.scratch.get("mother_tree_trip") == "recharge"
    assert board.intent is not None
    assert board.intent.action is ActionType.RETURN_TO_MOTHER_TREE


def test_field_baseline_ignores_large_jumps() -> None:
    state = _state(hp=100, mp=50)
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    _note_field_vitals(state, board, now=10.0)
    _set(state, hp=102, mp=51)
    _note_field_vitals(state, board, now=11.0)
    _set(state, hp=160, mp=90)
    _note_field_vitals(state, board, now=12.0)
    base = board.scratch["field_regen_baseline"]
    assert base["hp_per_s"] == 2.0
    assert base["mp_per_s"] == 1.0
