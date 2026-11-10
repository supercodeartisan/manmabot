"""Each member keeps their own seat-wait tries."""
from app._06_party.formation import FormationLagWatch


def test_one_member_is_waited_for_ten_seconds():
    watch = FormationLagWatch()
    first = watch.update([("a", 10)], 0.0)
    assert first.hold and first.reason == "depart:a"
    assert watch.update([("a", 1)], 2.0).reason == "in_slot"

    fresh = FormationLagWatch()
    assert fresh.update([("a", 4)], 0.0).hold
    assert fresh.update([("a", 4)], 9.0).hold
    done = fresh.update([("a", 4)], 10.0)
    assert not done.hold and done.reason == "degraded"
    assert not fresh.update([("a", 4)], 12.0).hold


def test_a_spent_member_does_not_block_the_next():
    watch = FormationLagWatch()
    assert watch.update([("a", 1), ("b", 1)], 0.0).reason == "in_slot"
    assert not watch.update([("a", 6)], 1.0).hold
    assert watch.update([("a", 6)], 1.3).hold
    done = watch.update([("a", 6)], 11.3)
    assert not done.hold and done.reason == "degraded"
    assert not watch.update([("a", 8)], 20.0).hold
    other = watch.update([("a", 8), ("b", 6)], 30.0)
    assert not other.hold
    assert watch.update([("a", 8), ("b", 6)], 30.4).reason == "slot_behind:b"


def test_no_readable_member_does_not_wait():
    watch = FormationLagWatch()
    quiet = watch.update([], 0.0)
    assert not quiet.hold and quiet.reason == "no_members"


if __name__ == "__main__":
    test_one_member_is_waited_for_ten_seconds()
    test_a_spent_member_does_not_block_the_next()
    test_no_readable_member_does_not_wait()
    print("OK")
