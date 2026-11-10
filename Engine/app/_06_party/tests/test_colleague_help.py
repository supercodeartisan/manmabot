"""A mage hit jumps the queue. Any other hit waits until the open fight ends."""
from __future__ import annotations

from app._06_party.assist import choose_help_target


class _Mob:
    def __init__(self, tid: int, guid: str) -> None:
        self.track_id = tid
        self.memory_guid = guid
        self.memory_ent = f"e{tid}"
        self.status = None
        self.bait = False
        self.force_attacks_me = False


class _State:
    def __init__(self, mobs: list[_Mob], rows: list[dict], members: list[dict]) -> None:
        self._mobs = mobs
        self.last_print_state = {"entities": rows}
        self.last_party = {"members": members}

    def monsters(self) -> list[_Mob]:
        return list(self._mobs)


def _hit(mob: _Mob, member_guid: str) -> dict:
    return {
        "class": "Monster",
        "guid": mob.memory_guid,
        "atk": 1,
        "tgt": member_guid,
        "name": "slime",
    }


def _member(name: str, guid: str, *, mage: bool = False, leader: bool = False) -> dict:
    row = {"name": name, "guid": guid, "is_leader": leader, "cls": 3 if mage else 1}
    if mage:
        row["type"] = "마법사"
    return row


def _world(current: _Mob, hitter: _Mob, victim: dict) -> _State:
    return _State(
        [current, hitter],
        [_hit(hitter, str(victim["guid"]))],
        [
            _member("Lead", "aa", leader=True),
            _member("Me", "bb"),
            victim,
        ],
    )


def test_mage_hit_replaces_the_open_fight() -> None:
    current = _Mob(1, "101")
    hitter = _Mob(2, "102")
    mage = _member("Mage", "cc", mage=True)
    state = _world(current, hitter, mage)
    pending = _Mob(9, "109")
    chosen, src = choose_help_target(
        state,
        state.last_party,
        self_name="Me",
        current=current,
        pending=pending,
        pending_src="leader_attack",
    )
    assert chosen is hitter
    assert src == "mage_help"


def test_other_hit_waits_until_the_open_fight_ends() -> None:
    current = _Mob(1, "101")
    hitter = _Mob(2, "102")
    knight = _member("Knight", "cc")
    state = _world(current, hitter, knight)
    pending = _Mob(9, "109")
    chosen, src = choose_help_target(
        state,
        state.last_party,
        self_name="Me",
        current=current,
        pending=pending,
        pending_src="leader_attack",
    )
    assert chosen is current
    assert src == "own_finish"


def test_idle_member_helps_the_colleague_before_a_new_hunt() -> None:
    current = _Mob(1, "101")
    hitter = _Mob(2, "102")
    knight = _member("Knight", "cc")
    state = _world(current, hitter, knight)
    pending = _Mob(9, "109")
    chosen, src = choose_help_target(
        state,
        state.last_party,
        self_name="Me",
        current=None,
        pending=pending,
        pending_src="leader_attack",
    )
    assert chosen is hitter
    assert src == "member_under_attack"


def test_no_hit_keeps_the_pending_target() -> None:
    pending = _Mob(9, "109")
    state = _State(
        [pending],
        [],
        [_member("Lead", "aa", leader=True), _member("Me", "bb")],
    )
    chosen, src = choose_help_target(
        state,
        state.last_party,
        self_name="Me",
        current=_Mob(1, "101"),
        pending=pending,
        pending_src="leader_attack",
    )
    assert chosen is pending
    assert src == "leader_attack"


def test_open_lock_without_a_body_still_finishes() -> None:
    hitter = _Mob(2, "102")
    knight = _member("Knight", "cc")
    state = _world(_Mob(1, "101"), hitter, knight)
    chosen, src = choose_help_target(
        state,
        state.last_party,
        self_name="Me",
        current=None,
        fight_open=True,
    )
    assert chosen is None
    assert src == "own_finish"


if __name__ == "__main__":
    test_mage_hit_replaces_the_open_fight()
    test_other_hit_waits_until_the_open_fight_ends()
    test_idle_member_helps_the_colleague_before_a_new_hunt()
    test_no_hit_keeps_the_pending_target()
    test_open_lock_without_a_body_still_finishes()
    print("OK")
