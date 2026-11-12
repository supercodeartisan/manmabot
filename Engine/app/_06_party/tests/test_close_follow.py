"""Close follow: stop at 2, start at 3, stale pose is not a walk goal."""
from app._06_party.config import PartyMemberConfig
from app._06_party.follow import (
    FOLLOW_CLICK_TILES,
    follow_extend_hop,
    follow_hop_off_leader,
    follow_hop_still_closes,
    follow_kind,
    hold_follow_click,
    leader_hop_pending,
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


def test_follow_click_stays_short_until_the_walk_is_far():
    from app._06_party.follow import follow_click_limit

    assert FOLLOW_CLICK_TILES == 2
    assert follow_click_limit(5) == 2
    assert follow_click_limit(6) == 5
    assert follow_click_limit(None) == 2


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
    assert follow_extend_hop((0, 0), (3, 0), (8, 0), kind="side") is None


def test_assist_beats_follow_while_moving_or_off_seat():
    far = decide_policy(_policy(assist_ready=True, slot_dist=5, slot_arrive=0))
    assert far.kind is MemberKind.ASSIST
    moving = decide_policy(
        _policy(assist_ready=True, slot_dist=2, slot_arrive=0, leader_moving=True)
    )
    assert moving.kind is MemberKind.ASSIST
    latched = decide_policy(
        _policy(assist_ready=True, slot_dist=2, catch_up=True, leader_moving=True)
    )
    assert latched.kind is MemberKind.ASSIST
    no_target = decide_policy(
        _policy(assist_ready=False, slot_dist=5, slot_arrive=0, leader_moving=True)
    )
    assert no_target.kind is MemberKind.FOLLOW


def test_catch_up_asks_only_for_an_in_range_heal():
    from app._06_party.manager import mage_list_heal_request

    assert mage_list_heal_request(True, MemberKind.FOLLOW) == (True, True)
    assert mage_list_heal_request(False, MemberKind.FOLLOW) == (False, False)
    assert mage_list_heal_request(False, MemberKind.HOLD) == (False, False)
    assert mage_list_heal_request(True, MemberKind.POTION) is None
    assert mage_list_heal_request(True, MemberKind.DEFEND) is None
    assert mage_list_heal_request(True, MemberKind.STOP) is None


def test_catch_up_keeps_potion_heal_and_defend():
    common = dict(slot_dist=6, assist_ready=True)
    assert decide_policy(_policy(need_potion=True, **common)).kind is MemberKind.POTION
    assert decide_policy(_policy(need_heal=True, **common)).kind is MemberKind.HEAL
    assert decide_policy(_policy(self_threat=True, **common)).kind is MemberKind.DEFEND
    assert decide_policy(_policy(need_buff=True, **common)).kind is not MemberKind.BUFF


def test_a_leader_step_keeps_a_hop_that_still_closes():
    assert hold_follow_click(
        (0, 0), (5, 0), (2, 0), body_moving=True, leader_moved=False
    )
    assert hold_follow_click(
        (0, 0), (6, 0), (2, 0), body_moving=True, leader_moved=True
    )
    assert not hold_follow_click(
        (0, 0), (0, 6), (2, 0), body_moving=True, leader_moved=True
    )


def test_a_leader_hop_waits_until_the_body_steps_or_the_click_fails():
    assert leader_hop_pending((0, 0), (2, 0), click_failed=False) is True
    assert leader_hop_pending((2, 0), (2, 0), click_failed=False) is False
    assert leader_hop_pending((0, 0), (2, 0), click_failed=True) is False
    assert follow_hop_off_leader((0, 0), (5, 0), (2, 0)) == (2, 0)
    assert follow_hop_off_leader((0, 0), (5, 0), (5, 0)) is None
    assert follow_hop_off_leader((0, 0), (5, 0), (0, 0)) is None


def test_an_open_leader_hop_does_not_click_again():
    from app._06_party.intents import plan_leader_hop

    class _Origin:
        x = 0
        y = 0

    _intent, goal, detail, hop = plan_leader_hop(
        _Origin(),
        (6, 0),
        previous_hop=(2, 0),
        click_failed=False,
    )
    assert detail == "follow_in_transit"
    assert goal == (6, 0)
    assert hop == (2, 0)


def test_a_still_hop_clicks_again_after_one_second(monkeypatch):
    from app._06_party import intents
    from app._06_party.follow import FOLLOW_HOP_START_S

    class _Origin:
        x = 0
        y = 0

    def _plan(*_args, **_kwargs):
        return (1, 0), [(1, 0)], (1, 0)

    monkeypatch.setattr(intents, "_body_moving", lambda: False)
    monkeypatch.setattr(
        "app._04_decision.pathfinding.plan_travel_click",
        _plan,
    )
    monkeypatch.setattr(
        "app._04_decision.nav_config.get_terrain_map",
        lambda: object(),
    )
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (6, 0),
        previous_hop=(2, 0),
        click_failed=False,
        hop_age_s=0.5,
    )
    assert detail == "follow_in_transit"
    assert hop == (2, 0)
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (6, 0),
        previous_hop=(2, 0),
        click_failed=False,
        hop_age_s=FOLLOW_HOP_START_S,
    )
    assert hop == (1, 0)
    assert goal == (6, 0)
    assert detail == "leader hop 1,0 → 6,0"


def test_a_moving_hop_that_still_aims_at_the_leader_is_not_clicked_again(monkeypatch):
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    monkeypatch.setattr(intents, "_body_moving", lambda: True)
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (8, 0),
        previous_hop=(2, 0),
        click_failed=False,
        hop_age_s=2.0,
        walk_steps=8,
    )
    assert detail == "follow_in_transit"
    assert hop == (2, 0)
    assert goal == (8, 0)


def test_a_turn_clicks_once_at_the_live_distance(monkeypatch):
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    seen = {}

    def _plan(*_args, **kwargs):
        seen["max_hop"] = kwargs.get("max_hop")
        return (0, 5), [(0, 5)], (0, 5)

    monkeypatch.setattr(intents, "_body_moving", lambda: True)
    monkeypatch.setattr(intents, "_follow_hop_clickable", lambda *_a, **_k: True)
    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _plan)
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: object())
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (0, 8),
        previous_hop=(2, 0),
        click_failed=False,
        walk_steps=8,
    )
    assert seen["max_hop"] == 5
    assert hop == (0, 5)
    assert goal == (0, 8)
    assert detail == "leader hop 0,5 → 0,8"


def test_a_near_walk_clicks_two_tiles(monkeypatch):
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    seen = {}

    def _plan(*_args, **kwargs):
        seen["max_hop"] = kwargs.get("max_hop")
        return (2, 0), [(2, 0)], (2, 0)

    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _plan)
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: object())
    _intent, _goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (5, 0),
        previous_hop=None,
        click_failed=False,
        walk_steps=5,
    )
    assert seen["max_hop"] == 2
    assert hop == (2, 0)
    assert detail == "leader hop 2,0 → 5,0"


def test_a_moving_hop_does_not_click_the_leader_tile(monkeypatch):
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    monkeypatch.setattr(intents, "_body_moving", lambda: True)
    monkeypatch.setattr(intents, "_follow_hop_clickable", lambda *_a, **_k: True)
    _intent, _goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (3, 0),
        previous_hop=(2, 0),
        click_failed=False,
    )
    assert detail == "follow_in_transit"
    assert hop == (2, 0)


def test_a_repeated_still_hop_steps_closer_when_the_walk_is_far(monkeypatch):
    from app._06_party import intents
    from app._06_party.follow import FOLLOW_HOP_START_S

    class _Origin:
        x = 0
        y = 0

    class _Open:
        def is_walkable(self, _x, _y):
            return True

        def can_step(self, _x1, _y1, _x2, _y2):
            return True

    def _plan(*_args, **_kwargs):
        return (2, 0), [(2, 0)], (2, 0)

    monkeypatch.setattr(intents, "_body_moving", lambda: False)
    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _plan)
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: _Open())
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (8, 0),
        previous_hop=(2, 0),
        click_failed=False,
        hop_age_s=FOLLOW_HOP_START_S,
        walk_steps=8,
    )
    assert goal == (8, 0)
    assert hop == (5, 0)
    assert detail == "leader hop 5,0 → 8,0"


def test_a_player_on_the_hop_is_stepped_around(monkeypatch):
    from app._02_state.objects import ObjectStatus, ObjectType, Relationship
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    class _Open:
        def is_walkable(self, _x, _y):
            return True

        def can_step(self, _x1, _y1, _x2, _y2):
            return True

    class _Player:
        object_type = ObjectType.PLAYER
        status = ObjectStatus.ALIVE
        relationship = Relationship.NEUTRAL
        track_id = 1
        world_cx = 2
        world_cy = 0
        memory_class = "player"

    class _State:
        def __init__(self):
            self.objects = self

        def all_objects(self):
            return [_Player()]

    def _plan(*_args, **_kwargs):
        return (2, 0), [(2, 0)], (2, 0)

    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _plan)
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: _Open())
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (8, 0),
        previous_hop=None,
        click_failed=False,
        walk_steps=8,
        state=_State(),
    )
    assert goal == (8, 0)
    assert hop is not None and hop != (2, 0)
    assert "player_beside" not in detail
    assert max(abs(hop[0]), abs(hop[1])) <= 5
    assert hop[0] >= 0


def test_same_delta_keeps_the_hop_and_a_turn_does_not():
    assert follow_hop_still_closes((0, 0), (5, 0), (2, 0)) is True
    assert follow_hop_still_closes((0, 0), (1, 0), (2, 0)) is False
    assert follow_hop_still_closes((0, 0), (5, 1), (2, 0)) is False
    assert follow_hop_still_closes((0, 0), (5, 0), None) is False


if __name__ == "__main__":
    test_walk_starts_one_tile_outside_the_stop_band()
    test_follow_click_stays_short_until_the_walk_is_far()
    test_offscreen_fresh_pose_uses_the_same_band()
    test_out_of_hunt_range_follows_instead_of_closing_in()
    test_stale_pose_does_not_follow()
    test_a_leader_step_keeps_a_hop_that_still_closes()
    test_a_leader_hop_waits_until_the_body_steps_or_the_click_fails()
    test_an_open_leader_hop_does_not_click_again()
    test_same_delta_keeps_the_hop_and_a_turn_does_not()
    test_straight_line_chains_one_tile_and_a_trail_does_not()
    test_assist_beats_follow_while_moving_or_off_seat()
    test_catch_up_keeps_potion_heal_and_defend()
    print("OK")
