"""Start rally meets at one static point before the farm."""
from types import SimpleNamespace

from app._06_party.leader_rally import LeaderStartRally


class _Step:
    def __init__(self, op, detail):
        self.op = op
        self.detail = detail


class _Plan:
    def __init__(self, steps, start):
        self.steps = steps
        self.meta = {"start": start}


class _Rally:
    def __init__(self):
        self.body = None
        self.stage = ""

    def clear(self):
        self.body = None
        self.stage = ""

    def arm(self, body):
        self.body = dict(body)
        self.stage = str(body.get("stage") or "")
        return True


def _rally():
    rally = _Rally()
    start = LeaderStartRally(rally, log=lambda _m: None)
    start.state = "await_plan"
    start.expected = {"콘러드"}
    return start, rally


class _Pose:
    def __init__(self, map_id, x, y):
        self.map_id = map_id
        self.x = x
        self.y = y


def test_walk_only_plan_meets_at_the_current_tile():
    start, rally = _rally()
    plan = _Plan(
        [_Step("walk", {"from": {"mapId": 0, "x": 1, "y": 2}, "to": {"mapId": 0, "x": 9, "y": 9}})],
        {"mapId": 0, "x": 1, "y": 2},
    )
    start.state = "await_mark"
    start.on_plan(plan)
    assert start.state == "await_mark"
    assert start.had_teleport is False
    assert start.hold_step == 0
    assert start.meet == (0, 1, 2)
    assert rally.body is None
    assert start.should_hold(0, None) is False
    assert start.should_hold(0, _Pose(0, 9, 9)) is False
    assert start.should_hold(0, _Pose(0, 1, 2)) is True
    assert start.state == "waiting"
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (0, 1, 2)
    assert start.should_hold(0, _Pose(0, 1, 2)) is True
    start.state = "done"
    assert start.should_hold(0, _Pose(0, 1, 2)) is False


def test_teleport_plan_stands_on_the_landing_after_the_teleport():
    start, rally = _rally()
    plan = _Plan(
        [
            _Step("walk", {"from": {"mapId": 4, "x": 10, "y": 10}, "to": {"mapId": 4, "x": 20, "y": 20}}),
            _Step(
                "npc_teleporter",
                {
                    "from": {"mapId": 4, "x": 20, "y": 20},
                    "to": {"mapId": 4, "x": 80, "y": 80},
                },
            ),
        ],
        {"mapId": 4, "x": 10, "y": 10},
    )
    start.state = "await_mark"
    start.on_plan(plan)
    assert start.had_teleport is True
    assert start.hold_step == 2
    assert start.meet == (4, 80, 80)
    assert start.stood is False
    assert start.state == "await_mark"
    assert start.should_hold(0, _Pose(4, 10, 10)) is False
    assert start.should_hold(1, _Pose(4, 20, 20)) is False
    assert start.should_hold(2, _Pose(4, 20, 20)) is True
    assert start.state == "await_mark"
    assert start.should_hold(2, _Pose(4, 83, 78)) is True
    assert start.stood is True
    assert start.state == "waiting"
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (4, 80, 80)
    start.state = "done"
    assert start.should_hold(2, _Pose(4, 83, 78)) is False


def test_scroll_then_walk_stands_before_the_walk():
    start, _rally_box = _rally()
    plan = _Plan(
        [
            _Step(
                "talking_scroll",
                {
                    "from": {"mapId": 0, "x": 1, "y": 2},
                    "to": {"mapId": 4, "x": 80, "y": 80},
                },
            ),
            _Step(
                "walk",
                {
                    "from": {"mapId": 4, "x": 80, "y": 80},
                    "to": {"mapId": 4, "x": 90, "y": 90},
                },
            ),
        ],
        {"mapId": 0, "x": 1, "y": 2},
    )
    start.state = "await_mark"
    start.on_plan(plan)
    assert start.hold_step == 1
    assert start.meet == (4, 80, 80)
    assert start.should_hold(0, _Pose(0, 1, 2)) is False
    assert start.should_hold(1, _Pose(0, 1, 2)) is True
    assert start.state == "await_mark"
    assert start.should_hold(1, _Pose(4, 84, 80)) is True
    assert start.state == "waiting"


def test_everyone_at_the_mark_leaves_immediately():
    from websocket.party_orders import Rally

    clock = {"t": 10.0}
    rally = Rally()
    start = LeaderStartRally(rally, log=lambda _m: None, clock=lambda: clock["t"])
    start.begin({"a", "b"}, travel=False, pose=None)
    start.note_arrived((4, 10, 20))
    assert start.state == "waiting"
    start.update(
        2,
        {
            "members": [
                {"name": "a", "map_id": 4, "x": 10, "y": 20},
                {"name": "b", "map_id": 4, "x": 12, "y": 20},
            ]
        },
    )
    assert start.state == "done"
    assert clock["t"] == 10.0


def test_a_missing_member_holds_the_stand_for_three_minutes():
    from app._06_party.leader_rally import MEMBER_WAIT_S
    from websocket.party_orders import Rally

    clock = {"t": 100.0}
    rally = Rally()
    start = LeaderStartRally(rally, log=lambda _m: None, clock=lambda: clock["t"])
    start.begin({"a", "b"}, travel=False, pose=None, deadline=101.0)
    start.note_arrived((4, 10, 20))
    here = {"members": [{"name": "a", "map_id": 4, "x": 10, "y": 20}]}
    start.update(1, here)
    assert start.state == "waiting"
    clock["t"] = 100.0 + MEMBER_WAIT_S - 1
    start.update(1, here)
    assert start.state == "waiting"
    clock["t"] = 100.0 + MEMBER_WAIT_S
    start.update(1, here)
    assert start.state == "done"
    assert start.left_behind == ["b"]


def test_no_socket_keeps_the_leader_on_the_rally_tile():
    from websocket.party_orders import Rally

    clock = {"t": 100.0}
    rally = Rally()
    start = LeaderStartRally(rally, log=lambda _m: None, clock=lambda: clock["t"])
    start.begin({"콘러드"}, travel=True, pose=None, deadline=100.0 + 600.0)
    start.note_arrived((4, 80, 80))
    here = {"members": []}
    clock["t"] = 100.0 + 180.0
    start.update(0, here)
    assert start.state == "waiting"
    clock["t"] = 100.0 + 600.0
    start.update(0, here)
    assert start.state == "done"
    assert start.left_behind == ["콘러드"]


def test_rally_wait_stands_before_the_hunt_walk():
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors.mode_ticks import _step_party_rally_wait
    from app._04_decision.steps import FARMING_DUNGEON, FARMING_ISLAND, WORLD_NAV

    assert WORLD_NAV.index("party.rally_wait") < WORLD_NAV.index("world_nav.drive")
    assert FARMING_ISLAND.index("party.rally_wait") < FARMING_ISLAND.index("nav.world")
    assert FARMING_DUNGEON.index("party.rally_wait") < FARMING_DUNGEON.index("nav.world")

    class _Board:
        def __init__(self):
            self.scratch = {}
            self.current_goal = ""
            self.emitted = []

        def emit(self, kind, priority, reason):
            self.emitted.append((kind, priority, reason))

    quiet = _Board()
    assert _step_party_rally_wait(object(), quiet) is None
    standing = _Board()
    standing.scratch["party_rally_wait"] = True
    assert _step_party_rally_wait(object(), standing) is Status.SUCCESS
    assert standing.emitted == [(ActionType.IDLE, 0.45, "party rally wait")]


def test_same_map_goal_at_the_gate_keeps_the_dungeon_teleport():
    from app._04_decision.world_nav.npc_teleporters import (
        NpcTeleporterLink,
        filter_teleporter_links_for_goal,
    )

    gate = NpcTeleporterLink(
        behavior_id="teleport_gludin",
        name="글루딘",
        map_id=4,
        npc_x=32727,
        npc_y=32931,
        adena_cost=220,
        teleport_kind="dungeon_gate",
        destination_dungeon=7,
        land_map_id=4,
        land_x=32727,
        land_y=32931,
    )
    near = filter_teleporter_links_for_goal(
        [gate], [], goal_map=4, same_map=True, goal_x=32726, goal_y=32921
    )
    assert [link.behavior_id for link in near] == ["teleport_gludin"]
    far = filter_teleporter_links_for_goal(
        [gate], [], goal_map=4, same_map=True, goal_x=33000, goal_y=33000
    )
    assert far == []


def test_rally_wait_fights_a_mob_on_the_leader(monkeypatch):
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.behaviors.mode_ticks import _step_party_rally_wait

    def hit(state, blackboard):
        del state, blackboard
        return Status.SUCCESS

    monkeypatch.setattr(mode_actions, "approach_counterattack", hit)

    class _State:
        def monsters(self):
            return []

    class _Board:
        def __init__(self):
            self.scratch = {"party_rally_wait": True}
            self.current_goal = ""
            self.emitted = []

        def emit(self, kind, priority, reason):
            self.emitted.append((kind, reason))

    board = _Board()
    assert _step_party_rally_wait(_State(), board) is Status.SUCCESS
    assert board.emitted == []


def test_rally_point_is_sent_to_members(monkeypatch):
    from websocket import party_orders
    from websocket.party_orders import MemberOrders, Rally, rally_message

    sent = []
    monkeypatch.setattr(party_orders, "_publish", lambda body: sent.append(dict(body)) or 0)
    rally = Rally()
    body = rally_message(stage="start", map_id=1, x=2, y=3)
    assert rally.arm(body) is True
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (1, 2, 3)
    assert sent and sent[0]["map_id"] == 1
    assert rally.repeat_if_members_joined(0) is False
    assert rally.repeat_if_members_joined(1) is True
    member = MemberOrders()

    class _Frame:
        message = body

    member.ingest([_Frame()])
    assert (member.gather["map_id"], member.gather["x"], member.gather["y"]) == (1, 2, 3)


def test_member_rally_plans_scroll_or_teleport_to_the_meet_tile(monkeypatch):
    from app._02_state.enums import ActionType
    from app._06_party.comms.orders import member_orders, rally_message
    from app._06_party.manager import PartyMemberManager

    class _Pose:
        map_id = 4
        x = 10
        y = 10

    class _Nav:
        def tick(self, _state, _board, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(action=ActionType.USE_TALKING_SCROLL, reason=kwargs["reason"])

    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state: _Pose(),
    )
    member_orders.clear()
    member_orders.gather = rally_message(stage="start", map_id=7, x=80, y=90)
    manager = PartyMemberManager()
    nav = _Nav()
    manager._join_nav = nav
    intent = manager._maybe_hunt_gather(object(), dead=False)
    assert intent.action is ActionType.USE_TALKING_SCROLL
    assert nav.kwargs["dest_map"] == 7
    assert (nav.kwargs["dest_x"], nav.kwargs["dest_y"]) == (80, 90)
    assert nav.kwargs["reason"] == "party_rally_start"
    manager.runtime.leader_same_map = True
    manager.runtime.leader_dist = 6
    manager.runtime.leader_farming = True
    assert manager._maybe_hunt_gather(object(), dead=False) is None
    member_orders.clear()


if __name__ == "__main__":
    test_walk_only_plan_meets_at_the_current_tile()
    test_teleport_plan_stands_on_the_landing_after_the_teleport()
    test_scroll_then_walk_stands_before_the_walk()
    test_everyone_at_the_mark_leaves_immediately()
    test_a_missing_member_holds_the_stand_for_three_minutes()
    test_rally_wait_stands_before_the_hunt_walk()
    print("OK")
