"""Light (spell id 1) is never an automatic buff, even when checked."""
from __future__ import annotations

from app._02_state.objects import Position
from app._02_state.player import PlayerState, StatusEffect
from app._03_world import ActionType, GameState
from app._04_decision import spells
from app._04_decision.blackboard import Blackboard
from app._04_decision.solo_mage import maybe_solo_mage_buffs
from app._04_decision.spells import due_buff, maybe_cast_buff
from app._05_action.controller import ActionExecutor
from app._05_action.spell_box import merge_slots
from settings.auto_buffs import AutoBuff, auto_buffs_for_magic


def _light() -> AutoBuff:
    return AutoBuff(skill_id=1, priority=1, names=("라이트", "日光術"), duration_s=7200.0)


def _shield() -> AutoBuff:
    return AutoBuff(skill_id=2, priority=2, names=("실드",), duration_s=1200.0)


def _state(*, effects: list | None = None) -> GameState:
    player = PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        hp=100,
        mp=80,
        max_hp=100,
        max_mp=100,
        level=40,
        buffs=list(effects or []),
    )
    state = GameState(player=player)
    state.last_buff = {
        "buffs": [{"name": "anchor", "skill": 99}],
        "cache": 1,
    }
    state.last_hotbar = {
        "slots": [
            {"name": "라이트", "box": 1, "key": "f6", "slot": 1},
            {"name": "실드", "box": 1, "key": "f8", "slot": 3},
        ]
    }
    return state


class _Keys:
    _last_magic_at = 0.0
    _world = None
    humanize = False

    def __init__(self) -> None:
        self.pressed: list[tuple[int, str]] = []

    def _press_box_skill(self, box: int, key: str) -> None:
        self.pressed.append((int(box), str(key)))

    _catalog_buff_is_double = ActionExecutor._catalog_buff_is_double


def test_checked_light_is_left_out_of_the_plan() -> None:
    plan = auto_buffs_for_magic(
        {
            "skills": {
                "elf_1": {"auto": True, "enabled": True, "auto_is_selection": True},
                "elf_2": {
                    "auto": True,
                    "enabled": True,
                    "auto_is_selection": True,
                    "priority": 1,
                },
            }
        },
        "elf",
    )
    ids = [buff.skill_id for buff in plan]
    assert 1 not in ids
    assert 2 in ids


def test_installing_a_plan_drops_light() -> None:
    saved = spells.AUTO_BUFFS
    try:
        spells.set_auto_buffs((_light(), _shield()))
        assert [buff.skill_id for buff in spells.AUTO_BUFFS] == [2]
    finally:
        spells.AUTO_BUFFS = saved


def test_light_in_auto_buffs_never_becomes_due_or_presses() -> None:
    saved = spells.AUTO_BUFFS
    try:
        spells.AUTO_BUFFS = (_light(), _shield())
        state = _state()
        board = Blackboard()
        assert due_buff(board, state) == "buff:2"
        assert maybe_cast_buff(state, board) is not None
        assert board.intent is not None
        assert board.intent.reason == "buff:2"
        keys = _Keys()
        ActionExecutor._buff(keys, "buff:1")
        ActionExecutor._buff(keys, "light")
        ActionExecutor._press_catalog_buff(keys, "buff:1", 1, "f6")
        assert keys.pressed == []
    finally:
        spells.AUTO_BUFFS = saved


def test_perpetual_or_missing_light_does_not_recast() -> None:
    saved = spells.AUTO_BUFFS
    try:
        spells.AUTO_BUFFS = (_light(),)
        missing = _state()
        assert due_buff(Blackboard(), missing) is None
        held = _state(
            effects=[
                StatusEffect(name="라이트", duration=7200.0, skill=1, perpetual=True)
            ]
        )
        assert due_buff(Blackboard(), held) is None
        assert maybe_cast_buff(held, Blackboard()) is None
    finally:
        spells.AUTO_BUFFS = saved


def test_solo_mage_path_skips_light_and_casts_shield() -> None:
    saved = spells.AUTO_BUFFS
    try:
        spells.AUTO_BUFFS = (_light(), _shield())
        state = _state()
        board = Blackboard()
        result = maybe_solo_mage_buffs(state, board)
        assert result is not None
        assert board.intent is not None
        assert board.intent.reason == "buff:2"
        assert board.intent.hotbar_key == "f8"
    finally:
        spells.AUTO_BUFFS = saved


def test_retired_light_slot_stays_off() -> None:
    forced = merge_slots(
        {"light": {"enabled": True, "box": 1, "key": "f6", "cast": "press"}}
    )
    assert forced["light"]["enabled"] is False


def test_shield_still_presses() -> None:
    saved = spells.AUTO_BUFFS
    try:
        spells.set_auto_buffs((_shield(),))
        keys = _Keys()
        ActionExecutor._press_catalog_buff(keys, "buff:2", 1, "f8")
        assert keys.pressed == [(1, "f8")]
        state = _state()
        state.player.buffs.clear()
        board = Blackboard()
        result = maybe_cast_buff(state, board)
        assert result is not None
        assert board.intent is not None
        assert board.intent.action is ActionType.BUFF
        assert board.intent.reason == "buff:2"
    finally:
        spells.AUTO_BUFFS = saved
