"""Leader snapshot to a member ActionIntent. Network party only."""
from __future__ import annotations

from types import SimpleNamespace

from app._02_state.enums import ActionType
from app._06_party.leader_rally import LeaderStartRally, MEMBER_WAIT_S
from app._06_party.party_sync import LeaderSync, consider_sync, roster_has
from websocket.party_orders import MemberOrders, Rally


class _Frame:
    def __init__(self, message, peer=""):
        self.message = message
        self.peer = peer
        self.sender = message.get("from")


class _Server:
    def __init__(self, count=1):
        self.frames = []
        self.sent = []
        self.count = count
        self.dropped = []

    def drain(self):
        out = list(self.frames)
        self.frames.clear()
        return out

    def client_count(self):
        return self.count

    def take_dropped(self):
        return []

    def send_to(self, peer, body, sender=""):
        self.sent.append((peer, dict(body), sender))


class _Pose:
    def __init__(self, map_id, x, y):
        self.map_id = map_id
        self.x = x
        self.y = y


class _Nav:
    def __init__(self):
        self.calls = 0
        self.session = None
        self.kwargs = None

    def tick(self, _state, _board, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        current = self.session
        self.session = SimpleNamespace(
            reason=kwargs["reason"],
            step_i=int(getattr(current, "step_i", 0) or 0),
            phase=str(getattr(current, "phase", "") or ""),
        )
        return SimpleNamespace(
            action=ActionType.USE_TALKING_SCROLL, reason=kwargs["reason"]
        )

    def clear(self):
        self.session = None


def _sync(session, rev, phase, point=None, run="running"):
    body = {
        "type": "party_sync",
        "from": "leader",
        "session": session,
        "rev": rev,
        "run": run,
        "policy_id": "p1",
        "rally": phase,
    }
    if point is not None:
        body["map_id"], body["x"], body["y"] = point
    return body


def _policy(session, names):
    return {
        "type": "party_policy",
        "from": "leader",
        "session": session,
        "policy_id": "p1",
        "roster": [{"name": name} for name in names],
    }


def _apply(orders, body, name, policy):
    orders.ingest([_Frame(body)])
    return consider_sync(orders, name=name, on_roster=roster_has(policy, name))


def _manager(monkeypatch, pose):
    from app._06_party.manager import PartyMemberManager

    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state: pose,
    )
    manager = PartyMemberManager()
    manager._join_nav = _Nav()
    return manager


def _move(manager, orders):
    from app._06_party.comms import orders as box

    box.member_orders.gather = orders.gather
    box.member_orders.arrived = orders.arrived
    box.member_orders.leader_run = str(getattr(orders, "leader_run", "") or "")
    return manager._maybe_hunt_gather(object(), dead=False)


def test_three_start_orders_join_the_same_point(monkeypatch):
    point = (4, 80, 90)
    for order in ("leader", "member", "both"):
        orders = MemberOrders()
        manager = _manager(monkeypatch, _Pose(4, 10, 10))
        if order == "member":
            manager.runtime.network_party = True
            manager.runtime.orders_open = False
            orders.gather = _sync("s", 2, "active", point)
            orders.gather["type"] = "rally"
            orders.gather["stage"] = "start"
            assert _move(manager, orders) is None
            manager.runtime.orders_open = True
        policy = _policy("s", ["멤버"])
        if order == "both":
            assert _apply(orders, _sync("s", 2, "active", point), "멤버", None) == "held"
        orders.ingest([_Frame(policy)])
        assert _apply(orders, _sync("s", 2, "active", point), "멤버", policy) == "applied"
        intent = _move(manager, orders)
        assert intent.action is ActionType.USE_TALKING_SCROLL
        assert (manager._join_nav.kwargs["dest_map"], manager._join_nav.kwargs["dest_x"]) == (4, 80)


def test_policy_and_rally_order_starts_one_move(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(1, 0, 0))
    policy = _policy("s", ["멤버"])
    active = _sync("s", 3, "active", (1, 40, 41))
    orders.ingest([_Frame(policy), _Frame(active)])
    assert consider_sync(orders, name="멤버", on_roster=True) == "applied"
    assert _move(manager, orders).action is ActionType.USE_TALKING_SCROLL
    first = manager._join_nav.calls
    assert _move(manager, orders).action is ActionType.IDLE
    assert manager._join_nav.calls == first + 1

    late = MemberOrders()
    brain = _manager(monkeypatch, _Pose(1, 0, 0))
    late.ingest([_Frame(active)])
    assert consider_sync(late, name="멤버", on_roster=None) == "held"
    late.ingest([_Frame(policy)])
    assert consider_sync(late, name="멤버", on_roster=True) == "applied"
    assert _move(brain, late).action is ActionType.USE_TALKING_SCROLL
    assert brain._join_nav.calls == 1

    outsider = MemberOrders()
    outsider.ingest([_Frame(active), _Frame(_policy("s", ["다른"]))])
    assert consider_sync(outsider, name="멤버", on_roster=False) == "dropped"
    assert outsider.gather is None


def test_pending_keeps_invite_and_done_does_not_walk_the_old_point(monkeypatch):
    orders = MemberOrders()
    policy = _policy("s", ["멤버"])
    orders.ingest([_Frame(policy), _Frame(_sync("s", 1, "pending"))])
    assert consider_sync(orders, name="멤버", on_roster=True) == "applied"
    assert orders.gather is None
    assert orders.policy["policy_id"] == "p1"
    manager = _manager(monkeypatch, _Pose(0, 1, 1))
    orders.ingest([_Frame(_sync("s", 4, "done"))])
    assert consider_sync(orders, name="멤버", on_roster=True) == "applied"
    orders.gather = {"type": "rally", "stage": "start", "session": "s", "rev": 2, "map_id": 9, "x": 1, "y": 1}
    # A member who first hears done does not keep a pin.
    fresh = MemberOrders()
    fresh.ingest([_Frame(policy), _Frame(_sync("s", 4, "done"))])
    assert consider_sync(fresh, name="멤버", on_roster=True) == "applied"
    assert fresh.gather is None
    assert _move(manager, fresh) is None


def test_replacement_hello_is_addressed_and_the_old_socket_cannot_clear_it():
    from app._06_party.comms.ingest import drain_leader_reports
    from app._06_party.sightings import book

    book.clear()
    server = _Server(count=2)
    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.state = "waiting"
    start.meet = (4, 3, 3)
    start.expected = {"법사"}
    box = LeaderSync()

    def deliver(_name, _peer):
        return [box.observe("s", "p1", start)]

    hello = {
        "type": "member_hello",
        "from": "법사",
        "client_id": "a",
        "character": {"name": "법사", "class": "MAGE", "level": 1},
    }
    server.frames = [_Frame(hello, "peer-a")]
    drain_leader_reports(server=server, start_rally=start, deliver=deliver)
    server.frames = [_Frame(dict(hello, client_id="b"), "peer-b")]
    server.count = 2
    drain_leader_reports(server=server, start_rally=start, deliver=deliver)
    peers = [row[0] for row in server.sent]
    assert peers == ["peer-a", "peer-b"]
    assert server.sent[-1][1]["rally"] == "active"
    book.note_hello("법사", "peer-b", "b")
    book.note(
        {"type": "sighting", "from": "법사", "client_id": "b", "map_id": 4, "seq": 1, "mobs": []},
        peer="peer-b",
        client_id="b",
    )
    book.drop_peer("법사", "peer-a")
    assert book._seq.get("법사") == 1
    late = {
        "type": "sighting", "from": "법사", "client_id": "a", "map_id": 4, "seq": 9,
        "mobs": [{"species": "orc", "guid": "Z", "x": 1, "y": 1}],
    }
    book.note(late, peer="peer-a", client_id="a")
    assert book._live_peer.get("법사") == "peer-b"
    assert book._seq.get("법사") == 1


def test_same_active_does_not_repeat_a_scroll_and_old_active_after_done_is_idle(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(0, 0, 0))
    policy = _policy("s", ["멤버"])
    active = _sync("s", 5, "active", (0, 12, 12))
    orders.ingest([_Frame(policy), _Frame(active)])
    consider_sync(orders, name="멤버", on_roster=True)
    assert _move(manager, orders).action is ActionType.USE_TALKING_SCROLL
    orders.ingest([_Frame(active)])
    consider_sync(orders, name="멤버", on_roster=True)
    assert _move(manager, orders).action is ActionType.IDLE
    orders.ingest([_Frame(_sync("s", 6, "done"))])
    consider_sync(orders, name="멤버", on_roster=True)
    assert manager.release_rally_nav() is True
    orders.ingest([_Frame(active)])
    assert orders.sync_frame["rev"] == 6
    orders.sync_frame = active
    assert consider_sync(orders, name="멤버", on_roster=True) == "stale"
    assert orders.gather is None
    assert _move(manager, orders) is None


def test_leader_pause_keeps_ten_seconds(monkeypatch):
    clock = {"t": 90.0}
    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: clock["t"])
    start.state = "await_mark"
    start.expected = {"멤버"}
    start.deadline = 100.0
    box = LeaderSync()
    box.observe("s", "p1", start)
    box.pause(start, clock["t"])
    paused = box.observe("s", "p1", start)
    assert paused["run"] == "paused"
    assert start.remaining_s() == 10
    clock["t"] = 120.0
    start.update(1, None)
    assert start.state != "done"
    assert start.remaining_s() == 10
    manager = _manager(monkeypatch, _Pose(4, 1, 1))
    orders = MemberOrders()
    orders.ingest([_Frame(_policy("s", ["멤버"])), _Frame(paused)])
    consider_sync(orders, name="멤버", on_roster=True)
    assert _move(manager, orders) is None
    box.resume(start, clock["t"])
    running = box.observe("s", "p1", start)
    assert running["run"] == "running"
    assert abs(start.remaining_s() - 10) < 0.01
    assert running["rev"] > paused["rev"]


def test_member_pause_does_not_move_the_leader_deadline(monkeypatch):
    clock = {"t": 90.0}
    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: clock["t"])
    start.state = "waiting"
    start.expected = {"멤버"}
    start._wait_started = 90.0 - (MEMBER_WAIT_S - 10.0)
    start.meet = (4, 1, 1)
    start._want = {"map_id": 4, "x": 1, "y": 1}
    # The member pause does not call freeze. Thirty seconds later the stand ends.
    clock["t"] = 120.0
    start.update(1, {"members": []})
    assert start.state == "done"
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(4, 40, 40))
    manager.runtime.sync_hold = True
    orders.gather = {"type": "rally", "stage": "start", "session": "s", "rev": 2, "map_id": 4, "x": 1, "y": 1}
    assert _move(manager, orders) is None
    manager.runtime.sync_hold = False
    orders.ingest([_Frame(_policy("s", ["멤버"])), _Frame(_sync("s", 8, "done"))])
    consider_sync(orders, name="멤버", on_roster=True)
    manager.release_rally_nav()
    assert _move(manager, orders) is None
    follow = manager._join_nav.tick(
        object(), None, dest_map=4, dest_x=40, dest_y=50, reason="party_join_leader"
    )
    assert follow.reason == "party_join_leader"
    assert (manager._join_nav.kwargs["dest_x"], manager._join_nav.kwargs["dest_y"]) == (40, 50)


def test_continuous_member_first_then_resume_follows_the_leader(monkeypatch):
    """Member first, leader connects, rally move, member pause while the leader leaves, resume to the leader."""
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(4, 10, 10))
    manager.runtime.network_party = True
    manager.runtime.orders_open = False
    orders.gather = {"type": "rally", "stage": "start", "session": "old", "rev": 1, "map_id": 9, "x": 9, "y": 9}
    assert _move(manager, orders) is None
    manager.runtime.orders_open = True
    policy = _policy("run-2", ["멤버"])
    active = _sync("run-2", 2, "active", (4, 80, 90))
    orders.ingest([_Frame(active)])
    assert consider_sync(orders, name="멤버", on_roster=None) == "held"
    orders.ingest([_Frame(policy)])
    assert consider_sync(orders, name="멤버", on_roster=True) == "applied"
    intent = _move(manager, orders)
    assert intent.action is ActionType.USE_TALKING_SCROLL
    assert manager._join_nav.kwargs["dest_x"] == 80
    manager.runtime.sync_hold = True
    orders.ingest([_Frame(_sync("run-2", 3, "done"))])
    consider_sync(orders, name="멤버", on_roster=True)
    assert _move(manager, orders) is None
    manager.runtime.sync_hold = False
    manager.release_rally_nav()
    assert orders.gather is None
    follow = manager._join_nav.tick(
        object(), None, dest_map=4, dest_x=15, dest_y=16, reason="party_join_leader"
    )
    assert follow.reason == "party_join_leader"
    assert (manager._join_nav.kwargs["dest_x"], manager._join_nav.kwargs["dest_y"]) == (15, 16)


def test_restart_ignores_the_old_session_and_one_member_restart_is_local():
    orders = MemberOrders()
    policy = _policy("new", ["멤버"])
    orders.ingest([_Frame(policy), _Frame(_sync("new", 1, "active", (1, 2, 3)))])
    consider_sync(orders, name="멤버", on_roster=True)
    kept = dict(orders.gather)
    orders.ingest([_Frame(_sync("old", 9, "active", (8, 8, 8)))])
    # The old session is adopted only when it is not retired. A later old frame is.
    assert orders.session == "old"
    orders.session = "new"
    orders._old_sessions.add("old")
    orders.gather = kept
    orders.ingest([_Frame(_sync("old", 9, "done"))])
    assert orders.gather["map_id"] == 1
    other = {"map_id": 1}
    assert other["map_id"] == 1


def test_restart_session_rule_drops_a_previous_packet():
    orders = MemberOrders()
    orders.ingest([_Frame(_sync("first", 4, "active", (1, 1, 1)))])
    orders.ingest([_Frame(_sync("second", 1, "active", (2, 2, 2)))])
    assert orders.session == "second"
    orders.ingest([_Frame(_sync("first", 5, "done"))])
    assert orders.session == "second"
    assert orders.sync_frame["map_id"] == 2


def test_missing_ack_retries_without_moving_the_deadline():
    clock = {"t": 0.0}
    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: clock["t"])
    start.state = "waiting"
    start.meet = (0, 4, 5)
    start.expected = {"멤버"}
    start._wait_started = 0.0
    box = LeaderSync()
    body = box.observe("s", "p1", start)
    assert body["map_id"] == 0
    assert box.needs_send("멤버", "s") is True
    deadline = start._wait_started
    box.note_ack("다른", "s", body["rev"])
    assert box.needs_send("멤버", "s") is True
    assert start._wait_started == deadline
    box.note_ack("멤버", "s", body["rev"])
    assert box.needs_send("멤버", "s") is False
    again = box.observe("s", "p1", start)
    assert again["rev"] == body["rev"]


def test_late_pose_is_not_arrival_and_map_zero_is_a_real_target(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(0, 1, 1))
    policy = _policy("s", ["멤버"])
    orders.ingest([_Frame(policy), _Frame(_sync("s", 2, "active", (0, 30, 30)))])
    consider_sync(orders, name="멤버", on_roster=True)
    intent = _move(manager, orders)
    assert intent.action is ActionType.USE_TALKING_SCROLL
    assert orders.arrived is False
    assert manager._join_nav.kwargs["dest_map"] == 0
    # The click is not an arrival. A pose still one tile off the meet is not either.
    orders.arrived = False
    assert _move(manager, orders).action is ActionType.IDLE
    assert orders.arrived is False


def test_memory_follow_still_moves_and_rally_end_leaves_join_map(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(4, 1, 1))
    assert manager.runtime.orders_open is True
    assert manager.runtime.network_party is False
    orders.gather = {
        "type": "rally", "stage": "start", "session": "s", "rev": 1,
        "map_id": 4, "x": 30, "y": 30,
    }
    assert _move(manager, orders) is not None
    manager._join_nav.session = SimpleNamespace(reason="party_join_leader")
    assert manager.release_rally_nav() is False
    assert manager._join_nav.session.reason == "party_join_leader"
    manager.runtime.hold_join_map = True
    assert manager._maybe_hunt_gather(object(), dead=False) is None


def test_duplicate_hello_on_the_same_peer_keeps_the_report_seq():
    from app._06_party.sightings import book

    book.clear()
    book.note_hello("법사", "peer-a", "a")
    body = {
        "type": "sighting", "from": "법사", "client_id": "a", "map_id": 4,
        "seq": 5, "mobs": [],
    }
    book.note(body, peer="peer-a", client_id="a")
    book.note_hello("법사", "peer-a", "a")
    replay = dict(body)
    replay["seq"] = 1
    book.note(replay, peer="peer-a", client_id="a")
    assert book._seq.get("법사") == 5


def test_controller_hello_returns_policy_and_the_member_clicks_once(monkeypatch):
    """The real controller builds the hello reply. The member's first intent uses it."""
    from types import SimpleNamespace

    from app._06_party.leader_rally import LeaderStartRally
    from app._06_party.sync import member_states
    from session.bot_controller import BotController
    from websocket.party_orders import Rally, member_orders

    member_states.clear()
    member_orders.clear()
    sent = []

    class _Server:
        def drain(self):
            return [
                _Frame(
                    {
                        "type": "member_hello",
                        "from": "멤버",
                        "client_id": "m1",
                        "character": {"name": "멤버", "class": "KNIGHT", "level": 1},
                    },
                    "peer-1",
                )
            ]

        def client_count(self):
            return 1

        def take_dropped(self):
            return []

        def send_to(self, peer, body, sender=""):
            sent.append((peer, dict(body)))

    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.state = "waiting"
    start.meet = (4, 80, 90)
    start.expected = {"멤버"}
    ctrl = BotController()
    ctrl._profile.party_enabled = True
    ctrl._profile.party_role = "leader"
    ctrl._party_policy_id = "policy-live"
    ctrl._party_policy_kwargs = {
        "leader_name": "리더",
        "roster": [{"name": "멤버"}],
    }
    ctrl._start_rally = start
    ctrl._party_comms._leader = SimpleNamespace(
        watchdog=SimpleNamespace(server=_Server()), owned=True
    )
    ctrl._drain_party_reports(SimpleNamespace(last_party=None))
    kinds = [row[1].get("type") for row in sent if row[0] == "peer-1"]
    assert "party_policy" in kinds
    sync = [row[1] for row in sent if row[1].get("type") == "party_sync"][-1]
    assert sync["policy_id"] == "policy-live"
    assert sync["rally"] == "active"
    assert (sync["map_id"], sync["x"], sync["y"]) == (4, 80, 90)
    assert not callable(ctrl._party_policy_id)

    orders = MemberOrders()
    orders.ingest([_Frame(row[1]) for row in sent if row[0] == "peer-1"])
    assert consider_sync(orders, name="멤버", on_roster=roster_has(orders.policy, "멤버")) == "applied"
    manager = _manager(monkeypatch, _Pose(4, 10, 10))
    intent = _move(manager, orders)
    assert intent.action is ActionType.USE_TALKING_SCROLL
    assert (manager._join_nav.kwargs["dest_x"], manager._join_nav.kwargs["dest_y"]) == (80, 90)
    member_orders.clear()
    member_states.clear()


def test_paused_snapshot_blocks_rally_march_and_focus(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(4, 10, 10))
    policy = _policy("s", ["멤버"])
    paused = _sync("s", 2, "active", (4, 80, 90), run="paused")
    orders.ingest([_Frame(policy), _Frame(paused)])
    assert consider_sync(orders, name="멤버", on_roster=True) == "applied"
    assert orders.leader_run == "paused"
    assert orders.gather["x"] == 80
    assert _move(manager, orders) is None
    seen = []
    monkeypatch.setattr(
        "app._06_party.formation_march.accept_march",
        lambda *args, **kwargs: seen.append(1),
    )
    assert manager._build_march(None, None, manager.config) is None
    assert seen == []
    orders.party_focus = {"support": "멤버"}
    assert manager._leader_orders_paused() is True
    from app._06_party.comms.orders import member_orders as live_orders

    live_orders.leader_run = "running"
    assert manager._build_march(None, None, manager.config) is None
    assert seen == [1]


def test_resume_keeps_the_hold_until_the_pull_reply_and_a_pose():
    from session.bot_controller import BotController
    from websocket.party_orders import member_orders

    member_orders.clear()
    ctrl = BotController()
    ctrl._profile.party_role = "member"
    ctrl._profile.party_leader_host = "10.0.0.8"
    ctrl._profile.party_enabled = True
    ctrl._profile.party_member_enabled = True
    from app._06_party.manager import PartyMemberManager

    brain = PartyMemberManager()
    ctrl._party_brain_ref = brain
    ctrl._party_pause_clock(resume=True)
    assert brain.runtime.sync_hold is True
    token = member_orders.sync_pull
    assert isinstance(token, int)
    ctrl._note_member_link(brain, SimpleNamespace())
    assert brain.runtime.sync_hold is True

    class _PoseBox:
        map_id = 4
        x = 3
        y = 4

    import app._04_decision.world_nav.session as nav_session

    previous_pose = nav_session.live_pose_from_state
    nav_session.live_pose_from_state = lambda _world: _PoseBox()
    try:
        ctrl._note_member_link(brain, SimpleNamespace())
        assert brain.runtime.sync_pose_ready is True
        assert brain.runtime.sync_hold is True
        member_orders.ingest([_Frame(_sync("s", 4, "done"))])
        assert brain.runtime.sync_hold is True
        done = _sync("s", 4, "done")
        done["pull"] = token
        member_orders.session = "s"
        member_orders.ingest([_Frame(done)])
        assert member_orders.sync_answered is True
        ctrl._release_sync_hold(brain.runtime)
        assert brain.runtime.sync_hold is False
    finally:
        nav_session.live_pose_from_state = previous_pose
        member_orders.clear()


def test_same_rev_pull_and_a_missing_rev_are_retransmitted():
    from types import SimpleNamespace

    from app._06_party.leader_rally import LeaderStartRally
    from session.bot_controller import BotController
    from websocket.party_orders import Rally

    sent = []

    class _Server:
        def send_to(self, peer, body, sender=""):
            sent.append((peer, dict(body)))

    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.state = "waiting"
    start.meet = (0, 4, 5)
    start.expected = {"멤버"}
    ctrl = BotController()
    ctrl._profile.party_enabled = True
    ctrl._profile.party_role = "leader"
    ctrl._party_policy_id = "policy-live"
    ctrl._start_rally = start
    ctrl._party_comms._leader = SimpleNamespace(
        watchdog=SimpleNamespace(server=_Server()), owned=True
    )
    body = ctrl._party_sync_observe()
    sent.clear()
    ctrl._party_sync_ack("멤버", body["session"], body["rev"], "peer-1")
    assert sent == []
    ctrl._party_sync_ack("멤버", body["session"], None, "peer-1")
    assert sent and sent[-1][1]["rev"] == body["rev"]
    sent.clear()
    ctrl._party_sync_ack("멤버", body["session"], body["rev"], "peer-1", pull=7)
    assert sent[-1][1]["pull"] == 7
    assert sent[-1][1]["rev"] == body["rev"]


def test_a_failed_step_may_retry_and_a_rev_change_does_not(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(4, 1, 1))
    policy = _policy("s", ["멤버"])
    active = _sync("s", 3, "active", (4, 40, 41))
    orders.ingest([_Frame(policy), _Frame(active)])
    consider_sync(orders, name="멤버", on_roster=True)
    assert _move(manager, orders).action is ActionType.USE_TALKING_SCROLL
    later = _sync("s", 9, "active", (4, 40, 41))
    orders.ingest([_Frame(later)])
    consider_sync(orders, name="멤버", on_roster=True)
    assert _move(manager, orders).action is ActionType.IDLE
    manager._join_nav.session.phase = "fail"
    assert _move(manager, orders).action is ActionType.USE_TALKING_SCROLL
    manager._join_nav.session.phase = ""
    manager._join_nav.session.step_i = 1
    assert _move(manager, orders).action is ActionType.USE_TALKING_SCROLL
    assert _move(manager, orders).action is ActionType.IDLE
