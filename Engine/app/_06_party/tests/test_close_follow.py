"""Close follow: stop at 2, start at 3, stale pose is not a walk goal."""
from app._06_party.config import PartyMemberConfig
from app._06_party.follow import (
    FOLLOW_CLICK_TILES,
    follow_extend_hop,
    follow_hop_still_closes,
    follow_kind,
)
from app._06_party.policy import MemberKind, PolicyInput, decide_policy


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


def test_walk_starts_one_tile_outside_the_stop_band():
    near, chasing = follow_kind(2, follow_tiles=8, stop_tiles=2, chasing=True)
    assert near == "near" and chasing is False
    band, chasing = follow_kind(
        3, follow_tiles=8, stop_tiles=2, leader_stopped=False, chasing=False
    )
    assert band == "follow" and chasing is True
    band, _chasing = follow_kind(6, follow_tiles=8, stop_tiles=2, chasing=False)
    assert band == "follow"


def test_follow_click_is_four_tiles():
    assert FOLLOW_CLICK_TILES == 4


def test_offscreen_fresh_pose_uses_the_same_band():
    hold = decide_policy(
        _policy(leader_in_ui=False, leader_dist=2, leader_walk_dist=2)
    )
    assert hold.kind is MemberKind.HOLD
    follow = decide_policy(
        _policy(leader_in_ui=False, leader_dist=4, leader_walk_dist=4)
    )
    assert follow.kind is MemberKind.FOLLOW
    assert "follow_travel" in follow.reason


def test_out_of_hunt_range_follows_instead_of_closing_in():
    result = decide_policy(
        _policy(assist_ready=True, need_combat_step=True, leader_dist=6, leader_walk_dist=6)
    )
    assert result.kind is MemberKind.FOLLOW


def test_stale_pose_does_not_follow():
    stale = decide_policy(
        _policy(leader_pose_stale=True, leader_in_ui=False, leader_dist=4)
    )
    assert stale.kind is MemberKind.WAIT
    assert stale.reason.startswith("leader_pose_stale")
    assist = decide_policy(
        _policy(leader_pose_stale=True, assist_ready=True, leader_dist=4)
    )
    assert assist.kind is MemberKind.ASSIST


def test_straight_line_chains_one_tile_and_a_trail_does_not():
    assert follow_extend_hop((0, 0), (2, 0), (8, 0), kind="side") == (3, 0)
    assert follow_extend_hop((0, 0), (2, 0), (8, 0), kind="trail") is None
    assert follow_extend_hop((0, 0), (2, 0), (2, 1), kind="side") is None
    assert follow_extend_hop((0, 0), (3, 0), (8, 0), kind="side") == (4, 0)
    assert follow_extend_hop((0, 0), (4, 0), (8, 0), kind="side") is None


def test_catch_up_defers_a_new_hunt_until_the_seat():
    far = decide_policy(_policy(assist_ready=True, slot_dist=5, slot_arrive=0))
    assert far.kind is MemberKind.FOLLOW
    moving = decide_policy(
        _policy(assist_ready=True, slot_dist=2, slot_arrive=0, leader_moving=True)
    )
    assert moving.kind is MemberKind.FOLLOW
    stopped = decide_policy(
        _policy(assist_ready=True, slot_dist=2, slot_arrive=0, leader_moving=False)
    )
    assert stopped.kind is MemberKind.ASSIST
    latched = decide_policy(
        _policy(assist_ready=True, slot_dist=2, catch_up=True, leader_moving=False)
    )
    assert latched.kind is MemberKind.FOLLOW
    back = decide_policy(
        _policy(assist_ready=True, slot_dist=1, catch_up=True, leader_moving=False)
    )
    assert back.kind is MemberKind.ASSIST


def test_catch_up_keeps_potion_heal_and_defend():
    common = dict(slot_dist=6, assist_ready=True)
    assert decide_policy(_policy(need_potion=True, **common)).kind is MemberKind.POTION
    assert decide_policy(_policy(need_heal=True, **common)).kind is MemberKind.HEAL
    assert decide_policy(_policy(self_threat=True, **common)).kind is MemberKind.DEFEND
    assert decide_policy(_policy(need_buff=True, **common)).kind is not MemberKind.BUFF


def test_same_delta_keeps_the_hop_and_a_turn_does_not():
    assert follow_hop_still_closes((0, 0), (5, 0), (2, 0)) is True
    assert follow_hop_still_closes((0, 0), (1, 0), (2, 0)) is False
    assert follow_hop_still_closes((0, 0), (5, 1), (2, 0)) is False
    assert follow_hop_still_closes((0, 0), (5, 0), None) is False


if __name__ == "__main__":
    test_walk_starts_one_tile_outside_the_stop_band()
    test_follow_click_stays_short()
    test_offscreen_fresh_pose_uses_the_same_band()
    test_out_of_hunt_range_follows_instead_of_closing_in()
    test_stale_pose_does_not_follow()
    test_same_delta_keeps_the_hop_and_a_turn_does_not()
    test_straight_line_chains_one_tile_and_a_trail_does_not()
    test_catch_up_defers_a_new_hunt_until_the_seat()
    test_catch_up_keeps_potion_heal_and_defend()
    print("OK")
