"""Close follow: stop at 2, start at 3, stale pose is not a walk goal."""
from app._06_party.config import PartyMemberConfig
from app._06_party.follow import FOLLOW_CLICK_TILES, follow_kind
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


def test_follow_click_stays_short():
    assert FOLLOW_CLICK_TILES == 2


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


if __name__ == "__main__":
    test_walk_starts_one_tile_outside_the_stop_band()
    test_follow_click_stays_short()
    test_offscreen_fresh_pose_uses_the_same_band()
    test_stale_pose_does_not_follow()
    print("OK")
