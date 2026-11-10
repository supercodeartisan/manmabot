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


def test_plan_does_not_start_the_wait():
    start, rally = _rally()
    plan = _Plan(
        [_Step("walk", {"from": {"mapId": 0, "x": 1, "y": 2}, "to": {"mapId": 0, "x": 9, "y": 9}})],
        {"mapId": 0, "x": 1, "y": 2},
    )
    start.state = "await_mark"
    start.on_plan(plan)
    assert start.state == "await_mark"
    assert rally.body is None
    assert start.should_hold(0, None) is False
    start.note_arrived((0, 9, 9))
    assert start.state == "done"
    assert rally.body is None
    assert start.should_hold(0, None) is False


def test_teleport_plan_does_not_move_the_wait():
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
    assert start.hold_step is None
    assert start.state == "await_mark"
    start.note_arrived((0, 3, 4))
    assert start.state == "done"
    assert rally.body is None


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
    test_plan_does_not_start_the_wait()
    test_teleport_plan_does_not_move_the_wait()
    test_rally_point_is_not_sent_to_members()
    print("OK")
