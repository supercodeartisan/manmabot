"""Solo mage buffs and attack spells from the individual table."""
from __future__ import annotations

from app._02_state.enums import CharacterType
from app._02_state.objects import ObjectStatus, ObjectType, Position, WorldObject
from app._02_state.player import PlayerState, StatusEffect
from app._03_world import ActionType, GameState
from app._04_decision import player_mode as pm
from app._04_decision import spells
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors.mode_ticks import _maybe_support_spells
from app._04_decision.solo_mage import (
    BUFF_CAST_ATTEMPTS,
    maybe_solo_mage_buffs,
    note_solo_mage_attack_pressed,
    solo_mage_active,
    solo_mage_attack_fields,
)
from settings.auto_buffs import AutoBuff, mage_attack_plan


def _player(kind: CharacterType, *, mp: int = 100, max_mp: int = 100) -> PlayerState:
    return PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        character_type=kind,
        mp=mp,
        max_mp=max_mp,
        level=20,
    )


def _state(kind: CharacterType, *, mp: int = 100, max_mp: int = 100) -> GameState:
    state = GameState(player=_player(kind, mp=mp, max_mp=max_mp))
    state.last_buff = {"buffs": [], "cache": 0}
    state.last_hotbar = {"slots": []}
    return state


def _buff(skill_id: int, priority: int, name: str, duration_s: float = 120.0) -> AutoBuff:
    return AutoBuff(
        skill_id=skill_id,
        priority=priority,
        names=(name,),
        duration_s=duration_s,
    )


def _bar(*cells: tuple[str, str]) -> dict:
    slots = []
    for index, (name, key) in enumerate(cells):
        slots.append({"name": name, "box": 1, "key": key, "slot": index})
    return {"slots": slots}


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def test_buffs_follow_priority_and_memory_remain() -> None:
    clock = _Clock()
    spells.set_auto_buffs(
        (
            _buff(11, 2, "인챈트 웨폰"),
            _buff(2, 1, "실드"),
        )
    )
    state = _state(CharacterType.MAGE)
    state.last_hotbar = _bar(("실드", "f6"), ("인챈트 웨폰", "f5"))
    board = Blackboard()
    original = solo_mage_now()
    try:
        set_now(clock)
        assert solo_mage_active(state, board)
        first = maybe_solo_mage_buffs(state, board)
        assert first is not None
        assert board.intent is not None
        assert board.intent.action is ActionType.BUFF
        assert board.intent.reason == "buff:2"
        assert board.buff_last_cast == {}

        state.set_player(
            _player(CharacterType.MAGE)
        )
        state.player.buffs.append(StatusEffect(name="실드", duration=100.0, skill=2))
        board.intent = None
        clock.t += 4.0
        second = maybe_solo_mage_buffs(state, board)
        assert second is not None
        assert board.intent is not None
        assert board.intent.reason == "buff:11"

        state.player.buffs.append(
            StatusEffect(name="인챈트 웨폰", duration=5.0, skill=11)
        )
        board.intent = None
        clock.t += 4.0
        again = maybe_solo_mage_buffs(state, board)
        assert again is not None
        assert board.intent is not None
        assert board.intent.reason == "buff:11"
    finally:
        set_now(original)


def test_live_fight_keeps_attacking() -> None:
    spells.set_auto_buffs((_buff(2, 1, "실드"),))
    state = _state(CharacterType.MAGE)
    state.last_hotbar = _bar(("실드", "f6"))
    state.last_print_state = {"entities": []}
    state.upsert_object(
        WorldObject(
            track_id=7,
            object_type=ObjectType.MONSTER,
            status=ObjectStatus.ALIVE,
        )
    )
    board = Blackboard()
    board.current_target_id = 7
    assert maybe_solo_mage_buffs(state, board) is None
    assert board.intent is None


def test_low_mp_does_not_wait() -> None:
    spells.set_auto_buffs((_buff(2, 1, "실드"),))
    state = _state(CharacterType.MAGE, mp=10, max_mp=100)
    state.last_hotbar = _bar(("실드", "f6"))
    board = Blackboard()
    assert maybe_solo_mage_buffs(state, board) is None
    assert board.intent is None


def test_cast_failure_parks_the_skill() -> None:
    clock = _Clock()
    spells.set_auto_buffs((_buff(2, 1, "실드"),))
    state = _state(CharacterType.MAGE)
    state.last_hotbar = _bar(("실드", "f6"))
    board = Blackboard()
    original = solo_mage_now()
    presses = 0
    try:
        set_now(clock)
        for _ in range(12):
            board.intent = None
            result = maybe_solo_mage_buffs(state, board)
            if board.intent is not None and board.intent.action is ActionType.BUFF:
                presses += 1
            clock.t += 4.0
            if result is None and presses >= BUFF_CAST_ATTEMPTS:
                break
        assert presses == BUFF_CAST_ATTEMPTS
        assert maybe_solo_mage_buffs(state, board) is None
    finally:
        set_now(original)


def test_attack_spell_uses_priority_then_falls_back() -> None:
    spells.set_solo_mage_attacks(
        (
            _buff(3, 1, "에너지 볼트", 0.0),
            _buff(46, 2, "선 버스트", 0.0),
        )
    )
    state = _state(CharacterType.MAGE)
    board = Blackboard()
    state.last_hotbar = _bar(("선 버스트", "f11"))
    assert solo_mage_attack_fields(state, board) == {
        "hotbar_box": 1,
        "hotbar_key": "f11",
    }
    state.last_hotbar = {"slots": []}
    assert solo_mage_attack_fields(state, board) == {}


def test_attack_spells_rotate_one_press_each() -> None:
    spells.set_solo_mage_attacks(
        (
            _buff(16, 3, "라이트닝", 0.0),
            _buff(3, 1, "에너지 볼트", 0.0),
            _buff(5, 2, "아이스 대거", 0.0),
        )
    )
    state = _state(CharacterType.MAGE)
    board = Blackboard()
    state.last_hotbar = _bar(
        ("에너지 볼트", "f5"),
        ("아이스 대거", "f6"),
        ("라이트닝", "f7"),
    )
    assert solo_mage_attack_fields(state, board)["hotbar_key"] == "f5"
    assert solo_mage_attack_fields(state, board)["hotbar_key"] == "f5"
    note_solo_mage_attack_pressed(board)
    assert solo_mage_attack_fields(state, board)["hotbar_key"] == "f6"
    note_solo_mage_attack_pressed(board)
    assert solo_mage_attack_fields(state, board)["hotbar_key"] == "f7"
    note_solo_mage_attack_pressed(board)
    assert solo_mage_attack_fields(state, board)["hotbar_key"] == "f5"


def test_other_classes_and_party_leader_stay_on_the_old_buff_path() -> None:
    spells.set_auto_buffs((_buff(2, 1, "실드"),))
    saved_mode = pm.ATTACK_MODE
    pm.ATTACK_MODE = "magic"
    try:
        elf = _state(CharacterType.ELF)
        elf.last_hotbar = _bar(("실드", "f6"))
        elf_board = Blackboard()
        assert not solo_mage_active(elf, elf_board)
        assert _maybe_support_spells(elf, elf_board, allow_buffs=True) is not None
        assert elf_board.buff_last_cast.get("buff:2", 0.0) > 0.0

        leader = _state(CharacterType.MAGE)
        leader.last_hotbar = _bar(("실드", "f6"))
        leader_board = Blackboard()
        leader_board.scratch["party_leader_no_loot"] = True
        assert not solo_mage_active(leader, leader_board)
        assert solo_mage_attack_fields(leader, leader_board) == {}
        assert _maybe_support_spells(leader, leader_board, allow_buffs=True) is not None
        assert leader_board.buff_last_cast.get("buff:2", 0.0) > 0.0
    finally:
        pm.ATTACK_MODE = saved_mode


def test_attack_plan_is_checked_mage_spells_only() -> None:
    magic = {
        "skills": {
            "mage_3": {
                "auto": True,
                "enabled": True,
                "auto_is_selection": True,
                "priority": 2,
            },
            "mage_6": {
                "auto": False,
                "enabled": False,
                "auto_is_selection": True,
                "priority": 1,
            },
        }
    }
    plan = mage_attack_plan(magic, "mage")
    assert [row.skill_id for row in plan] == [3]
    assert mage_attack_plan(magic, "elf") == ()
    assert mage_attack_plan(magic, "knight") == ()


def solo_mage_now():
    from app._04_decision import solo_mage

    return solo_mage._now


def set_now(fn) -> None:
    from app._04_decision import solo_mage

    solo_mage._now = fn


def main() -> None:
    saved_buffs = spells.AUTO_BUFFS
    saved_attacks = spells.SOLO_MAGE_ATTACKS
    try:
        test_buffs_follow_priority_and_memory_remain()
        test_live_fight_keeps_attacking()
        test_low_mp_does_not_wait()
        test_cast_failure_parks_the_skill()
        test_attack_spell_uses_priority_then_falls_back()
        test_attack_spells_rotate_one_press_each()
        test_other_classes_and_party_leader_stay_on_the_old_buff_path()
        test_attack_plan_is_checked_mage_spells_only()
    finally:
        spells.set_auto_buffs(saved_buffs)
        spells.set_solo_mage_attacks(saved_attacks)
    print("solo mage tests ok")


if __name__ == "__main__":
    main()
