"""The party wait ends when the companions are back, not when a timer ends."""
from app._06_party.formation import (
    BLOCKED,
    READY,
    FormationLagWatch,
    SeatSample,
    hop_widens_gap,
)


def test_ten_seconds_does_not_leave_the_member():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 10)], 0.0).hold
    still = watch.update([SeatSample("a", 10)], 10.0)
    assert still.hold and still.reason.startswith("recover")
    assert watch.update([SeatSample("a", 1)], 11.0).reason == "together"


def test_one_arrival_does_not_release_the_party():
    watch = FormationLagWatch()
    assert watch.update(
        [SeatSample("a", 8), SeatSample("b", 8), SeatSample("c", 8)], 0.0
    ).hold
    mid = watch.update(
        [SeatSample("a", 1), SeatSample("b", 8), SeatSample("c", 8)], 3.0
    )
    assert mid.hold and mid.behind == 2
    done = watch.update(
        [SeatSample("a", 1), SeatSample("b", 1), SeatSample("c", 1)], 4.0
    )
    assert not done.hold and done.reason == "together"


def test_a_dropped_pose_stays_in_the_wait():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 10)], 0.0).hold
    assert watch.update([SeatSample("a")], 1.0).hold
    missed = watch.update([], 4.0)
    assert missed.hold
    assert watch.member_state("a") != READY


def test_a_new_member_does_not_extend_this_wait():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 8)], 0.0).hold
    released = watch.update([SeatSample("a", 1), SeatSample("b", 9)], 3.0)
    assert not released.hold and released.reason == "together"
    nxt = watch.update([SeatSample("b", 9)], 4.0)
    assert nxt.hold and nxt.reason == "depart:b"
    assert "b" in watch.session_names
    assert nxt.behind == 1


def test_blocked_recovery_starts_before_the_budget_ends():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 10)], 0.0).hold
    blocked = watch.update([SeatSample("a", 10)], 2.0)
    assert blocked.hold and watch.member_state("a") == BLOCKED
    assert watch.reform_pending and not watch.action_needed
    watch.consume_reform(2.0)
    assert watch.update([SeatSample("a", 10)], 4.0).hold
    watch.consume_reform(4.0)
    hand = watch.update([SeatSample("a", 10)], 6.0)
    assert hand.hold and hand.reason.startswith("action_needed")
    assert watch.update([SeatSample("a", 1)], 7.0).reason == "together"


def test_someone_still_closing_is_kept_past_ten_seconds():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 10)], 0.0).hold
    assert watch.update([SeatSample("a", 8)], 3.0).hold
    assert watch.update([SeatSample("a", 6)], 6.0).hold
    assert watch.update([SeatSample("a", 4)], 9.0).hold
    later = watch.update([SeatSample("a", 4)], 10.0)
    assert later.hold and later.reason.startswith("recover")
    assert not watch.action_needed
    assert watch.update([SeatSample("a", 1)], 11.0).reason == "together"


def test_four_tiles_yields_the_next_hop_before_the_stop():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 1, (1, 0))], 0.0).reason == "in_slot"
    closing = watch.update([SeatSample("a", 4, (5, 0))], 1.0)
    assert not closing.hold and closing.reason == "closing"
    assert watch.yield_tiles() == [(5, 0)]
    assert not watch.update([SeatSample("a", 6, (7, 0))], 2.0).hold
    assert watch.update([SeatSample("a", 6, (7, 0))], 2.4).hold


def test_a_seat_flicker_does_not_drop_a_member_who_arrived():
    watch = FormationLagWatch()
    assert watch.update([SeatSample("a", 8), SeatSample("b", 8)], 0.0).hold
    assert watch.update([SeatSample("a", 8), SeatSample("b", 1)], 1.0).hold
    assert watch.member_state("b") == READY
    assert watch.update([SeatSample("a", 8), SeatSample("b", 2)], 1.5).hold
    assert watch.member_state("b") == READY
    assert watch.update([SeatSample("a", 8), SeatSample("b", 3)], 2.0).hold
    assert watch.member_state("b") != READY


def test_shop_and_empty_party_do_not_wait():
    watch = FormationLagWatch()
    quiet = watch.update([], 0.0)
    assert not quiet.hold and quiet.reason == "no_members"
    assert watch.update([SeatSample("a", 10)], 1.0).hold
    left = watch.update([SeatSample("a", excluded=True)], 2.0)
    assert not left.hold and left.reason == "excluded"


def test_hop_that_increases_a_gap_is_withheld():
    assert hop_widens_gap((0, 0), (5, 0), [(-3, 0)])
    assert not hop_widens_gap((0, 0), (-1, 0), [(-3, 0)])


if __name__ == "__main__":
    test_ten_seconds_does_not_leave_the_member()
    test_one_arrival_does_not_release_the_party()
    test_a_dropped_pose_stays_in_the_wait()
    test_a_new_member_does_not_extend_this_wait()
    test_blocked_recovery_starts_before_the_budget_ends()
    test_someone_still_closing_is_kept_past_ten_seconds()
    test_four_tiles_yields_the_next_hop_before_the_stop()
    test_a_seat_flicker_does_not_drop_a_member_who_arrived()
    test_shop_and_empty_party_do_not_wait()
    test_hop_that_increases_a_gap_is_withheld()
    print("OK")
