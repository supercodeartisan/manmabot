"""An open invite is answered from the popup, not from leftover party memory."""
from app._06_party.accept import InviteAccepter
from app._06_party.join_map import (
    memory_leader_confirmed,
    suppress_join_while_invite,
    suppress_unconfirmed_leader,
)
from app._06_party.policy import MemberKind, PolicyResult


def _popup(name: str) -> dict:
    return {"inviter": name, "msg": "invite", "ask": 954}


def _accepter():
    presses = []

    def press() -> str:
        presses.append("y")
        return ""

    acc = InviteAccepter(press=press, send_ack=lambda _body: False, log=lambda _m: None)
    return acc, presses


def test_open_popup_presses_y_while_memory_names_someone_else():
    acc, presses = _accepter()
    pressed = acc.tick(
        _popup("Boss"),
        leader_name="Boss",
        in_party=True,
        memory_leader="Old",
    )
    assert pressed is True
    assert presses == ["y"]
    assert acc.phase == "pressed"
    assert acc.blocks_join_map("Old") is True
    assert acc.tick(
        _popup("Boss"),
        leader_name="Boss",
        in_party=True,
        memory_leader="Old",
    ) is False
    assert acc.phase == "pressed"


def test_join_waits_until_memory_leader_is_the_inviter():
    acc, _presses = _accepter()
    acc.tick(_popup("Boss"), leader_name="Boss", in_party=True, memory_leader="Old")
    acc.tick(None, leader_name="Boss", in_party=True, memory_leader="Old")
    assert acc.phase == "waiting_memory"
    assert acc.blocks_join_map("Old") is True
    acc.tick(None, leader_name="Boss", in_party=True, memory_leader="Boss")
    assert acc.phase == "joined"
    assert acc.blocks_join_map("Boss") is False


def test_matching_memory_still_presses_y_while_the_popup_is_open():
    acc, presses = _accepter()
    acc.tick(_popup("Boss"), leader_name="Boss", in_party=True, memory_leader="Boss")
    assert presses == ["y"]
    assert acc.phase == "pressed"
    assert acc.blocks_join_map("Boss") is True


def test_other_inviter_does_not_press_y():
    acc, presses = _accepter()
    acc.tick(_popup("Other"), leader_name="Boss", in_party=True, memory_leader="Old")
    assert presses == []
    assert acc.phase == "skipped"
    assert "Other" in acc.skipped
    assert acc.blocks_join_map("Old") is True


def test_idle_member_is_not_held():
    acc, _presses = _accepter()
    assert acc.blocks_join_map("Old") is False


class _Nav:
    def __init__(self) -> None:
        self.active = True
        self.cleared = False

    def clear(self) -> None:
        self.active = False
        self.cleared = True


def test_hold_clears_an_in_flight_join():
    nav = _Nav()
    result = suppress_join_while_invite(
        PolicyResult(MemberKind.JOIN_MAP, False, "leader_other_map"),
        nav,
        hold=True,
    )
    assert nav.cleared is True
    assert result.kind is MemberKind.WAIT
    assert result.reason == "invite_before_join"
    kept = suppress_join_while_invite(
        PolicyResult(MemberKind.JOIN_MAP, False, "leader_other_map"),
        _Nav(),
        hold=False,
    )
    assert kept.kind is MemberKind.JOIN_MAP
    walking = _Nav()
    held = suppress_join_while_invite(
        PolicyResult(MemberKind.FOLLOW, True, "follow_far"),
        walking,
        hold=True,
    )
    assert walking.cleared is True
    assert held.kind is MemberKind.WAIT
    assert held.reason == "invite_before_join"


def test_leftover_party_row_is_not_a_walk_goal():
    assert memory_leader_confirmed("", "Old") is False
    assert memory_leader_confirmed("Boss", "Old") is False
    assert memory_leader_confirmed("Boss", "Boss") is True
    nav = _Nav()
    result = suppress_unconfirmed_leader(
        PolicyResult(MemberKind.JOIN_MAP, False, "leader_other_map"),
        nav,
        confirmed=False,
    )
    assert nav.cleared is True
    assert result.kind is MemberKind.WAIT
    assert result.reason == "party_leader_unconfirmed"
    follow = suppress_unconfirmed_leader(
        PolicyResult(MemberKind.FOLLOW, True, "follow_far"),
        _Nav(),
        confirmed=False,
    )
    assert follow.kind is MemberKind.WAIT
    kept = suppress_unconfirmed_leader(
        PolicyResult(MemberKind.JOIN_MAP, False, "leader_other_map"),
        _Nav(),
        confirmed=True,
    )
    assert kept.kind is MemberKind.JOIN_MAP


if __name__ == "__main__":
    test_open_popup_presses_y_while_memory_names_someone_else()
    test_join_waits_until_memory_leader_is_the_inviter()
    test_matching_memory_still_presses_y_while_the_popup_is_open()
    test_other_inviter_does_not_press_y()
    test_idle_member_is_not_held()
    test_hold_clears_an_in_flight_join()
    test_leftover_party_row_is_not_a_walk_goal()
    print("ok")
