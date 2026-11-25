"""Why a checked buff is chosen again. Light is not part of this path."""
from __future__ import annotations

import time

from app._02_state.objects import Position
from app._02_state.player import PlayerState, StatusEffect
from app._03_world import GameState
from app._04_decision import spells
from app._04_decision.blackboard import Blackboard
from app._04_decision.spells import due_buff
from settings.auto_buffs import AutoBuff


def _shield() -> AutoBuff:
    return AutoBuff(skill_id=2, priority=1, names=("실드",), duration_s=1200.0)


def _state(effects: list[StatusEffect]) -> GameState:
    player = PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        hp=100,
        mp=80,
        max_hp=100,
        max_mp=100,
        level=40,
        buffs=list(effects),
    )
    state = GameState(player=player)
    state.last_buff = {"buffs": [{"name": "anchor"}], "cache": 1}
    state.last_hotbar = {"slots": [{"name": "실드", "box": 1, "key": "f8", "slot": 3}]}
    return state


def _due(effects: list[StatusEffect]) -> str | None:
    saved = spells.AUTO_BUFFS
    spells.AUTO_BUFFS = (_shield(),)
    try:
        return due_buff(Blackboard(), _state(effects))
    finally:
        spells.AUTO_BUFFS = saved


def test_missing_effect_is_due_again_after_the_guard() -> None:
    saved = spells.AUTO_BUFFS
    spells.AUTO_BUFFS = (_shield(),)
    try:
        state = _state([])
        board = Blackboard()
        assert due_buff(board, state) == "buff:2"
        board.buff_last_cast["buff:2"] = time.time()
        assert due_buff(board, state) is None
        board.buff_last_cast["buff:2"] = time.time() - (spells.BUFF_CAST_GUARD_S + 0.1)
        assert due_buff(board, state) == "buff:2"
    finally:
        spells.AUTO_BUFFS = saved


def test_perpetual_effect_is_treated_as_absent() -> None:
    assert (
        _due([StatusEffect(name="실드", duration=1200.0, skill=2, perpetual=True)])
        == "buff:2"
    )


def test_same_name_matches_when_the_skill_id_differs() -> None:
    assert (
        _due([StatusEffect(name="실드", duration=500.0, skill=999)]) is None
    )


def test_different_name_and_skill_id_stay_due() -> None:
    assert (
        _due([StatusEffect(name="다른버프", duration=500.0, skill=999)]) == "buff:2"
    )


def test_active_effect_with_time_left_is_not_recast() -> None:
    assert _due([StatusEffect(name="실드", duration=500.0, skill=2)]) is None


def test_active_effect_under_ten_seconds_is_due() -> None:
    assert _due([StatusEffect(name="실드", duration=5.0, skill=2)]) == "buff:2"
