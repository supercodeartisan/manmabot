"""Blocked leader asks for room, the member steps off; the leader paces a lagging party."""
from __future__ import annotations

from app._06_party.frame_check import reject_leader_frame
from app._06_party.leader_pace import (
    PACE_COOLDOWN_S,
    PACE_HOLD_S,
    PACE_IGNORE_TILES,
    LeaderPace,
    pace_gap,
)
from app._06_party.make_way import (
    MAKE_WAY_BLOCKED_S,
    MAKE_WAY_RESEND_S,
    LeaderBlockWatch,
    guide_ahead,
    line_gap,
    make_way_message,
    parse_make_way,
    plan_make_way,
)
from websocket.party_orders import MemberOrders


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_the_leader_asks_after_three_seconds_and_not_again_for_five() -> None:
    clock = _Clock()
    watch = LeaderBlockWatch(clock=clock)
    assert watch.note(True) is False
    clock.t += MAKE_WAY_BLOCKED_S - 0.1
    assert watch.note(True) is False
    clock.t += 0.2
    assert watch.note(True) is True
    clock.t += 1.0
    assert watch.note(True) is False
    clock.t += MAKE_WAY_RESEND_S
    assert watch.note(True) is True


def test_a_click_resets_the_blocked_clock() -> None:
    clock = _Clock()
    watch = LeaderBlockWatch(clock=clock)
    watch.note(True)
    clock.t += 2.0
    assert watch.note(False) is False
    clock.t += 2.0
    assert watch.note(True) is False


def test_guide_ahead_starts_after_the_leader_tile() -> None:
    guide = [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert guide_ahead(guide, (1, 0), 2) == [(2, 0), (3, 0)]
    assert guide_ahead(guide, (9, 9), 2) == [(0, 0), (1, 0)]


def _open_except(walls):
    blocked = set(walls)
    return lambda tile: tile not in blocked


def test_a_member_beside_the_line_steps_two_tiles_off_it_behind_the_leader() -> None:
    leader = (10, 10)
    guide = [(11, 10), (12, 10), (13, 10)]
    tile = plan_make_way((9, 10), leader, guide, open_tile=lambda _t: True)
    assert tile is not None
    assert line_gap(tile, [leader] + guide) >= 2
    assert tile[0] < leader[0]


def test_a_member_already_clear_of_the_line_does_not_move() -> None:
    leader = (10, 10)
    guide = [(11, 10), (12, 10)]
    assert plan_make_way((10, 13), leader, guide, open_tile=lambda _t: True) is None


def test_a_one_wide_corridor_backs_the_member_two_tiles_from_the_leader() -> None:
    # Corridor y=10 only. A member behind the leader backs up along it.
    leader = (10, 10)
    guide = [(11, 10), (12, 10)]

    def corridor(tile):
        return tile[1] == 10

    assert plan_make_way((9, 10), leader, guide, open_tile=corridor) == (8, 10)


def test_a_member_ahead_in_a_one_wide_corridor_walks_on_ahead() -> None:
    # Behind the leader is open too, but that walk would cross his tile.
    leader = (10, 10)
    guide = [(11, 10), (12, 10)]

    def corridor(tile):
        return tile[1] == 10

    tile = plan_make_way((11, 10), leader, guide, open_tile=corridor)
    assert tile == (14, 10)


def test_no_step_off_tile_and_no_room_on_the_line_returns_none() -> None:
    leader = (10, 10)
    guide = [(11, 10)]
    assert plan_make_way((9, 10), leader, guide, open_tile=lambda _t: False) is None


def test_make_way_frame_is_accepted_and_taken_once() -> None:
    body = make_way_message(map_id=4, x=10, y=10, guide=[(11, 10)])
    assert reject_leader_frame(body) == ""

    class _Frame:
        def __init__(self, message):
            self.message = message

    orders = MemberOrders()
    orders.ingest([_Frame(body)])
    taken = orders.take_make_way()
    assert taken is not None and "_at" in taken
    assert parse_make_way(taken) == (4, (10, 10), [(11, 10)])
    assert orders.take_make_way() is None


def test_pace_holds_at_most_one_second_then_walks_two() -> None:
    clock = _Clock()
    pace = LeaderPace(clock=clock)
    assert pace.check(behind=True) is True
    clock.t += PACE_HOLD_S - 0.1
    assert pace.check(behind=True) is True
    clock.t += 0.2
    assert pace.check(behind=True) is False
    clock.t += PACE_COOLDOWN_S - 0.1
    assert pace.check(behind=True) is False
    clock.t += 0.2
    assert pace.check(behind=True) is True


def test_a_caught_up_member_releases_the_pace() -> None:
    clock = _Clock()
    pace = LeaderPace(clock=clock)
    assert pace.check(behind=True) is True
    clock.t += 0.3
    assert pace.check(behind=False) is False
    assert pace.holding is False


def test_pace_gap_is_the_farthest_member_not_lost() -> None:
    leader = (0, 0)
    assert pace_gap(leader, [(2, 0), (5, 0)]) == 5
    assert pace_gap(leader, [(2, 0), (PACE_IGNORE_TILES + 1, 0)]) == 2
    assert pace_gap(leader, ["other_map"]) is None
    assert pace_gap(leader, []) is None


def _leader_controller(clock):
    from types import SimpleNamespace

    from session.bot_controller import BotController

    ctl = SimpleNamespace(
        _party_leader_on=lambda: True,
        _start_rally=SimpleNamespace(state="done"),
        _party_block_watch=LeaderBlockWatch(clock=clock),
        _party_pace=LeaderPace(clock=clock),
        logs=[],
    )
    ctl.log = ctl.logs.append
    ctl._party_comms_publish_body = lambda body: ctl.logs.append(body) or 2
    return ctl, BotController._leader_walk_party


def test_leader_travel_click_waits_for_a_lagging_member(monkeypatch) -> None:
    from types import SimpleNamespace

    from app._02_state.enums import ActionType
    from app._06_party.types import ActionIntent

    clock = _Clock()
    ctl, walk = _leader_controller(clock)
    monkeypatch.setattr(
        "app._06_party.formation.followers_from_party",
        lambda *_a, **_k: [(15, 10)],
    )
    world = SimpleNamespace(party_read_ok=True, last_party={})
    board = SimpleNamespace(world_origin=SimpleNamespace(x=10, y=10), nav_path=[], player_mode=None)
    click = ActionIntent(action=ActionType.TRAVELING, reason="patrol waypoint 2")
    held = walk(ctl, world, board, click, 4)
    assert held.action is ActionType.IDLE
    assert held.reason.startswith("party pace wait gap=5")
    unstick = ActionIntent(action=ActionType.TRAVELING, reason="unstick nearby")
    assert walk(ctl, world, board, unstick, 4) is unstick


def test_leader_blocked_three_seconds_sends_make_way(monkeypatch) -> None:
    from types import SimpleNamespace

    from app._02_state.enums import ActionType
    from app._06_party.types import ActionIntent

    clock = _Clock()
    ctl, walk = _leader_controller(clock)
    world = SimpleNamespace(party_read_ok=False, last_party={})
    board = SimpleNamespace(
        world_origin=SimpleNamespace(x=85, y=88),
        nav_path=[(85, 88), (86, 88), (87, 88)],
        player_mode=None,
    )
    stuck = ActionIntent(action=ActionType.IDLE, reason="window has no safe click")
    walk(ctl, world, board, stuck, 1)
    clock.t += MAKE_WAY_BLOCKED_S + 0.1
    walk(ctl, world, board, stuck, 1)
    sent = [row for row in ctl.logs if isinstance(row, dict)]
    assert len(sent) == 1
    assert sent[0]["type"] == "make_way"
    assert (sent[0]["x"], sent[0]["y"]) == (85, 88)
    assert sent[0]["guide"] == [[86, 88], [87, 88]]


def test_a_turned_leader_clicks_a_fresh_hop_instead_of_walking_out(monkeypatch) -> None:
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    monkeypatch.setattr(intents, "_body_moving", lambda: True)
    monkeypatch.setattr(intents, "_leader_extend", lambda *_a, **_k: None)
    monkeypatch.setattr(
        intents, "_fresh_leader_hop", lambda *_a, **_k: ((2, 1), "")
    )
    _intent, goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (6, 3),
        previous_hop=(2, 0),
        click_failed=False,
    )
    assert hop == (2, 1)
    assert goal == (6, 3)
    assert detail == "leader hop 2,1 → 6,3"


def test_a_fresh_hop_that_does_not_close_keeps_the_walk(monkeypatch) -> None:
    from app._06_party import intents

    class _Origin:
        x = 0
        y = 0

    monkeypatch.setattr(intents, "_body_moving", lambda: True)
    monkeypatch.setattr(intents, "_leader_extend", lambda *_a, **_k: None)
    monkeypatch.setattr(
        intents, "_fresh_leader_hop", lambda *_a, **_k: ((1, 0), "")
    )
    _intent, _goal, detail, hop = intents.plan_leader_hop(
        _Origin(),
        (8, 0),
        previous_hop=(3, 0),
        click_failed=False,
    )
    assert detail == "follow_in_transit"
    assert hop == (3, 0)
