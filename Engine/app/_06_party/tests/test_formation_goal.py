"""Side line, corridor trail, and standing grid."""
import time

from app._06_party.config import PartyMemberConfig
from app._06_party.formation_goal import (
    advance_heading,
    choose_formation_goal,
    nearer_lateral,
    primary_lateral,
    stand_radius,
)
from app._06_party.manager import FORMATION_STAND_SETTLE_S, PartyMemberManager
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
        leader_walk_dist=None,
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


def test_leader_distance_holds_inside_two_tiles():
    near = decide_policy(_policy(leader_dist=1, slot_dist=1))
    assert near.kind is MemberKind.HOLD
    assert near.reason.startswith("hold dist=")
    edge = decide_policy(_policy(leader_dist=2, slot_dist=2, slot_arrive=0))
    assert edge.kind is MemberKind.HOLD
    stand = decide_policy(_policy(leader_dist=1, slot_dist=1, slot_arrive=1))
    assert stand.kind is MemberKind.HOLD
    outside = decide_policy(_policy(leader_dist=3, slot_dist=2, slot_arrive=1))
    assert outside.kind is MemberKind.FOLLOW


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


def test_a_backward_hop_keeps_the_side_slot_until_the_leader_has_stopped():
    from app._06_party.formation_goal import FormationGoal, closing_slot

    chosen = FormationGoal("side", (11, 9), "side+1")
    kept = closing_slot(
        held=False,
        previous=(10, 11),
        previous_kind="side",
        chosen=chosen,
        origin=(10, 12),
        hop=(10, 13),
        leader=(10, 8),
    )
    assert kept.tile == (10, 11)
    assert kept.reason == "keep_closing"
    stand = closing_slot(
        held=True,
        previous=(10, 11),
        previous_kind="side",
        chosen=chosen,
        origin=(10, 12),
        hop=(10, 13),
        leader=(10, 8),
    )
    assert stand.tile == (11, 9)
    closer = closing_slot(
        held=False,
        previous=(10, 11),
        previous_kind="side",
        chosen=chosen,
        origin=(10, 12),
        hop=(10, 11),
        leader=(10, 8),
    )
    assert closer.tile == (11, 9)


def test_the_stand_grid_waits_two_seconds():
    mgr = PartyMemberManager.__new__(PartyMemberManager)
    mgr.runtime = MemberRuntime()
    assert (
        mgr._leader_looks_stopped(
            leader_tile=(3, 4), settle_sec=FORMATION_STAND_SETTLE_S
        )
        is False
    )
    mgr.runtime.scratch["leader_tile_seen_at"] = time.monotonic() - 1.0
    assert mgr._leader_looks_stopped(leader_tile=(3, 4)) is True
    assert (
        mgr._leader_looks_stopped(
            leader_tile=(3, 4), settle_sec=FORMATION_STAND_SETTLE_S
        )
        is False
    )
    mgr.runtime.scratch["leader_tile_seen_at"] = time.monotonic() - 2.0
    assert (
        mgr._leader_looks_stopped(
            leader_tile=(3, 4), settle_sec=FORMATION_STAND_SETTLE_S
        )
        is True
    )


def test_one_strafe_keeps_the_side_and_two_tiles_turn_it():
    heading, pending, run, committed = advance_heading(None, None, 0, (1, 0))
    assert heading == (1, 0) and committed is True
    heading, pending, run, committed = advance_heading(heading, pending, run, (0, -1))
    assert heading == (1, 0) and committed is False and pending == (0, -1) and run == 1
    kept = choose_formation_goal(
        (10, 9),
        forward=heading,
        seat=0,
        followers=1,
        stopped=False,
        trail_tile=None,
        lateral=1,
    )
    assert kept.tile == (10, 10)
    turned, pending, run, committed = advance_heading(heading, pending, run, (0, -1))
    assert turned == (0, -1) and committed is True
    flipped = nearer_lateral((10, 10), (-1, 0), 1, (10, 12))
    assert flipped == -1


def test_a_stop_keeps_the_latched_side():
    held = choose_formation_goal(
        (20, 20),
        forward=(1, 0),
        seat=0,
        followers=5,
        stopped=True,
        trail_tile=None,
        lateral=1,
        previous=(20, 21),
    )
    assert held.kind == "side"
    assert held.tile == (20, 21)


def test_a_rejected_player_hop_tries_another_closing_tile():
    from app._06_party.intents import _closing_hop_off_player

    origin = type("O", (), {"x": 0, "y": 0})()
    alt = _closing_hop_off_player(origin, (4, 0), (2, 0), None)
    assert alt is not None and alt != (2, 0)
    assert alt[0] > 0
    assert max(abs(4 - alt[0]), abs(alt[1])) < 4


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
    test_leader_distance_holds_inside_two_tiles()
    test_one_leader_step_moves_the_side_slot()
    test_a_backward_hop_keeps_the_side_slot_until_the_leader_has_stopped()
    test_the_stand_grid_waits_two_seconds()
    test_one_strafe_keeps_the_side_and_two_tiles_turn_it()
    test_a_stop_keeps_the_latched_side()
    test_a_rejected_player_hop_tries_another_closing_tile()
    test_standing_fight_stays_stopped()
    print("ok")
