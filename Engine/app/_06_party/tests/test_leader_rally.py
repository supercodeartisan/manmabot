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


def test_walk_only_waits_at_the_start_tile():
    start, rally = _rally()
    plan = _Plan(
        [_Step("walk", {"from": {"mapId": 0, "x": 1, "y": 2}, "to": {"mapId": 0, "x": 9, "y": 9}})],
        {"mapId": 0, "x": 1, "y": 2},
    )
    start.on_plan(plan)
    assert start.hold_step == 0
    assert rally.body["stage"] == "start"
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (0, 1, 2)
    assert start.should_hold(0, None) is True


def test_first_teleport_departure_is_the_meet_point():
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
            _Step(
                "talking_scroll",
                {
                    "from": {"mapId": 4, "x": 80, "y": 80},
                    "to": {"mapId": 0, "x": 300, "y": 300},
                },
            ),
        ],
        {"mapId": 4, "x": 10, "y": 10},
    )
    start.on_plan(plan)
    assert start.hold_step == 1
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (4, 20, 20)
    assert start.should_hold(0, None) is False
    assert start.state == "hold_at"
    assert start.should_hold(1, None) is True
    assert start.state == "waiting"
    assert (rally.body["map_id"], rally.body["x"], rally.body["y"]) == (4, 20, 20)


if __name__ == "__main__":
    test_walk_only_waits_at_the_start_tile()
    test_first_teleport_departure_is_the_meet_point()
    print("OK")
