"""Turret members hunt while the leader rests, then finish before assist."""
from __future__ import annotations

from app._06_party.assist import turret_member_focus


def test_idle_leader_starts_yard_hunt() -> None:
    focus, keep = turret_member_focus(
        leader_farming=False,
        own_id=None,
        own_still_ok=False,
        yard_id=7,
    )
    assert focus == "yard"
    assert keep == 7


def test_leader_attack_finishes_the_open_mob() -> None:
    focus, keep = turret_member_focus(
        leader_farming=True,
        own_id=7,
        own_still_ok=True,
        yard_id=None,
    )
    assert focus == "own_finish"
    assert keep == 7


def test_dead_own_mob_switches_to_assist() -> None:
    focus, keep = turret_member_focus(
        leader_farming=True,
        own_id=7,
        own_still_ok=False,
        yard_id=9,
    )
    assert focus == "leader"
    assert keep is None


def test_idle_with_nothing_in_the_yard() -> None:
    focus, keep = turret_member_focus(
        leader_farming=False,
        own_id=None,
        own_still_ok=False,
        yard_id=None,
    )
    assert focus == "none"
    assert keep is None


if __name__ == "__main__":
    test_idle_leader_starts_yard_hunt()
    test_leader_attack_finishes_the_open_mob()
    test_dead_own_mob_switches_to_assist()
    test_idle_with_nothing_in_the_yard()
    print("OK")
