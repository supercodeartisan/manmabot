"""Side line, corridor trail, and standing grid."""
import time

from app._06_party.config import PartyMemberConfig
from app._06_party.formation_goal import (
    choose_formation_goal,
    primary_lateral,
    stand_radius,
)
from app._06_party.manager import PartyMemberManager
from app._06_party.policy import MemberKind, PolicyInput, decide_policy
from app._06_party.state import MemberRuntime


class _Terrain:
    def __init__(self, blocked):
        self.blocked = set(blocked)

    def is_walkable(self, x, y):
        return (int(x), int(y)) not in self.blocked


def _policy(**kwargs):
    base = dict(
        paused=False,
        dead=False,
        origin_ok=True,
        leader_present=True,
        leader_dist=4,
        chasing=False,
        need_potion=False,
        self_threat=False,
        assist_ready=False,
        config=PartyMemberConfig(),
        leader_walk_dist=4,
    )
    base.update(kwargs)
    return PolicyInput(**base)


def test_side_line_is_abreast_and_exclusive():
    leader = (10, 10)
    east = (1, 0)
    a = choose_formation_goal(
        leader, forward=east, seat=0, followers=2, stopped=False, trail_tile=None
    )
    b = choose_formation_goal(
        leader, forward=east, seat=1, followers=2, stopped=False, trail_tile=None
    )
    assert a.kind == "side" and b.kind == "side"
    assert a.tile == (10, 11)
    assert b.tile == (10, 9)
    assert a.tile != b.tile
    assert primary_lateral(0) == 1 and primary_lateral(1) == -1


def test_blocked_side_steps_out_without_taking_the_other_seat():
    leader = (10, 10)
    nudged = choose_formation_goal(
        leader,
        forward=(0, -1),
        seat=0,
        followers=2,
        stopped=False,
        trail_tile=None,
        terrain=_Terrain({(11, 10)}),
    )
    assert nudged.tile == (11, 9)
    closed = choose_formation_goal(
        leader,
        forward=(0, -1),
        seat=0,
        followers=2,
        stopped=False,
        trail_tile=None,
        terrain=_Terrain({(11, 10), (11, 9), (11, 11)}),
    )
    assert closed.tile is None


def test_side_line_wins_while_a_trail_tile_exists():
    goal = choose_formation_goal(
        (10, 10),
        forward=(1, 0),
        seat=0,
        followers=2,
        stopped=False,
        trail_tile=(4, 4),
    )
    assert goal.kind == "side"
    assert goal.tile == (10, 11)


def test_trail_is_used_only_when_the_side_is_blocked():
    closed = _Terrain({(11, 10), (11, 9), (11, 11)})
    goal = choose_formation_goal(
        (10, 10),
        forward=(0, -1),
        seat=0,
        followers=2,
        stopped=False,
        trail_tile=(4, 4),
        terrain=closed,
    )
    assert goal.kind == "trail"
    assert goal.tile == (4, 4)


def test_stopped_grid_excludes_the_leader():
    assert stand_radius(5) == 2
    assert stand_radius(6) == 3
    leader = (20, 20)
    seats = [
        choose_formation_goal(
            leader, forward=(1, 0), seat=i, followers=5, stopped=True, trail_tile=None
        ).tile
        for i in range(5)
    ]
    assert all(tile is not None and tile != leader for tile in seats)
    assert len(set(seats)) == 5
    assert all(max(abs(t[0] - 20), abs(t[1] - 20)) <= 2 for t in seats)
    wide = choose_formation_goal(
        leader, forward=(1, 0), seat=0, followers=6, stopped=True, trail_tile=None
    )
    assert wide.kind == "stand"
    assert max(abs(wide.tile[0] - 20), abs(wide.tile[1] - 20)) <= 3


def test_slot_distance_replaces_the_leader_band():
    hold = decide_policy(_policy(leader_dist=1, slot_dist=0))
    assert hold.kind is MemberKind.HOLD
    assert hold.reason.startswith("hold_slot")
    follow = decide_policy(_policy(leader_dist=1, slot_dist=1))
    assert follow.kind is MemberKind.FOLLOW
    assert follow.reason.startswith("follow_slot")


def test_one_leader_step_moves_the_side_slot():
    leader = (10, 10)
    first = choose_formation_goal(
        leader, forward=(1, 0), seat=0, followers=2, stopped=False, trail_tile=None
    )
    nxt = choose_formation_goal(
        (11, 10),
        forward=(1, 0),
        seat=0,
        followers=2,
        stopped=False,
        trail_tile=None,
        previous=first.tile,
        previous_leader=leader,
    )
    assert first.tile == (10, 11)
    assert nxt.kind == "side"
    assert nxt.tile == (11, 11)


def test_standing_fight_stays_stopped():
    mgr = PartyMemberManager.__new__(PartyMemberManager)
    mgr.runtime = MemberRuntime()
    assert mgr._leader_looks_stopped(leader_tile=(3, 4)) is False
    mgr.runtime.scratch["leader_tile_seen_at"] = time.monotonic() - 1.0
    assert mgr._leader_looks_stopped(leader_tile=(3, 4)) is True


if __name__ == "__main__":
    test_side_line_is_abreast_and_exclusive()
    test_blocked_side_steps_out_without_taking_the_other_seat()
    test_side_line_wins_while_a_trail_tile_exists()
    test_trail_is_used_only_when_the_side_is_blocked()
    test_stopped_grid_excludes_the_leader()
    test_slot_distance_replaces_the_leader_band()
    test_one_leader_step_moves_the_side_slot()
    test_standing_fight_stays_stopped()
    print("ok")
