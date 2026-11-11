"""Start rally meets at one static point before the farm."""
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


def test_teleport_plan_meets_at_the_departure_tile():
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
    assert start.hold_step == 1
    assert start.meet == (4, 20, 20)
    assert start.state == "await_mark"
    assert start.should_hold(0, _Pose(4, 10, 10)) is False
    assert start.should_hold(1, _Pose(4, 80, 80)) is False
    assert start.should_hold(1, _Pose(4, 20, 20)) is True
    assert start.state == "waiting"
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (4, 20, 20)


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


def test_rally_point_is_not_sent_to_members():
    from websocket.party_orders import MemberOrders, Rally, rally_message

    rally = Rally()
    body = rally_message(stage="start", map_id=1, x=2, y=3)
    assert rally.arm(body) is True
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (1, 2, 3)
    assert rally.repeat_if_members_joined(4) is False
    member = MemberOrders()

    class _Frame:
        message = body

    member.ingest([_Frame()])
    assert member.gather is None


if __name__ == "__main__":
    test_walk_only_plan_meets_at_the_current_tile()
    test_teleport_plan_meets_at_the_departure_tile()
    test_everyone_at_the_mark_leaves_immediately()
    test_a_missing_member_holds_the_stand_for_three_minutes()
    test_rally_wait_stands_before_the_hunt_walk()
    test_rally_point_is_not_sent_to_members()
    print("OK")
