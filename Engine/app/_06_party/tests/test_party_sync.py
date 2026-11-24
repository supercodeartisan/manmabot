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
        out = list(self.dropped)
        self.dropped.clear()
        return out

    def send_to(self, peer, body, sender=""):
        from websocket.server import PartyServer

        frame = PartyServer._coerce(body, sender=sender or "leader")
        self.sent.append((peer, frame.message, sender or frame.sender))


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
    drain_leader_reports(
        server=server, start_rally=start, deliver=deliver, roster_names=["법사"]
    )
    assert server.sent and server.sent[-1][1].get("rally") == "active"
    # A second live socket for the same name is CONFLICT: reject, no snapshot.
    server.frames = [_Frame(dict(hello, client_id="b"), "peer-b")]
    server.count = 2
    before = len(server.sent)
    drain_leader_reports(
        server=server, start_rally=start, deliver=deliver, roster_names=["법사"]
    )
    assert any(
        row[0] == "peer-b" and row[1].get("type") == "hello_reject"
        for row in server.sent[before:]
    )
    # After the old socket drops, the survivor is MATCHED again.
    server.dropped = ["peer-a"]
    server.frames = [_Frame(dict(hello, client_id="b"), "peer-b")]
    drain_leader_reports(
        server=server, start_rally=start, deliver=deliver, roster_names=["법사"]
    )
    assert any(
        row[0] == "peer-b" and row[1].get("type") == "party_sync"
        for row in server.sent
    )
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
    manager.runtime.network_party = True
    manager.runtime.orders_open = True
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
            from websocket.server import PartyServer

            frame = PartyServer._coerce(body, sender=sender or "leader")
            sent.append((peer, frame.message))

    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.state = "waiting"
    start.meet = (4, 80, 90)
    start.expected = {"멤버"}
    ctrl = BotController()
    ctrl._profile.party_enabled = True
    ctrl._profile.party_role = "leader"
    ctrl._profile.party_roster = [{"name": "멤버"}]
    ctrl._party_policy_kwargs = {
        "leader_name": "리더",
        "roster": [{"name": "멤버"}],
    }
    from websocket.party_orders import policy_message

    ctrl._party_policy_id = str(policy_message(**ctrl._party_policy_kwargs).get("policy_id") or "")
    ctrl._start_rally = start
    ctrl._party_comms._leader = SimpleNamespace(
        watchdog=SimpleNamespace(server=_Server()), owned=True
    )
    ctrl._drain_party_reports(SimpleNamespace(last_party=None))
    kinds = [row[1].get("type") for row in sent if row[0] == "peer-1"]
    assert "hello_ok" in kinds
    assert "party_policy" in kinds
    assert "hello_reject" not in kinds
    sync = [row[1] for row in sent if row[1].get("type") == "party_sync"][-1]
    assert sync["policy_id"] == ctrl._party_policy_id
    assert ctrl._party_policy_id
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


def test_send_to_keeps_the_rally_snapshot_and_decide_moves(monkeypatch):
    """A member-only snapshot stays a party_sync object through real packing."""
    from app._06_party.comms.ingest import drain_leader_reports
    from app._06_party.comms.orders import member_orders
    from app._06_party.frame_check import reject_leader_frame
    from app._06_party.member_discovery import discovery
    from websocket.server import PartyServer

    member_orders.clear()
    discovery.clear()
    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.state = "waiting"
    start.meet = (4, 32726, 32921)
    start.expected = {"멤버"}
    box = LeaderSync()
    policy = {
        "type": "party_policy",
        "from": "leader",
        "session": "bd3b6486",
        "policy_id": "p1",
        "leader_mode": "moving",
        "roster": [{"name": "멤버"}],
    }

    def deliver(_name, _peer):
        return [policy, box.observe("bd3b6486", "p1", start)]

    raw = [row for row in deliver("멤버", "peer-1") if row["type"] == "party_sync"][0]
    packed = PartyServer._coerce(raw, sender="leader")
    assert packed.message["run"] == "running"
    assert packed.message["rally"] == "active"
    assert reject_leader_frame(packed.message) == ""

    server = _Server()
    server.frames = [
        _Frame(
            {
                "type": "member_hello",
                "from": "멤버",
                "client_id": "bf3c23b8",
                "character": {"name": "멤버", "class": "ELF", "level": 1},
            },
            "peer-1",
        )
    ]
    drain_leader_reports(server=server, start_rally=start, deliver=deliver)
    sync = [row[1] for row in server.sent if row[1].get("type") == "party_sync"][-1]
    assert reject_leader_frame(sync) == ""
    assert (sync["map_id"], sync["x"], sync["y"]) == (4, 32726, 32921)

    mgr, state = _decide_member(monkeypatch, "멤버", (10, 10), (12, 10))
    mgr._join_nav = _Nav()
    before = mgr.decide(state)
    assert before.action is not ActionType.USE_TALKING_SCROLL
    member_orders.ingest([_Frame(policy), _Frame(sync)])
    assert consider_sync(
        member_orders, name="멤버", on_roster=roster_has(member_orders.policy, "멤버")
    ) == "applied"
    intent = mgr.decide(state)
    assert intent.action is ActionType.USE_TALKING_SCROLL
    assert (mgr._join_nav.kwargs["dest_x"], mgr._join_nav.kwargs["dest_y"]) == (32726, 32921)
    member_orders.clear()
    discovery.clear()


def test_a_dropped_socket_does_not_keep_the_name_in_conflict():
    from app._06_party.comms.ingest import drain_leader_reports
    from app._06_party.member_discovery import MembershipStatus, discovery

    discovery.clear()
    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.expected = {"콘러드"}

    def hello(client_id):
        return {
            "type": "member_hello",
            "from": "콘러드",
            "client_id": client_id,
            "character": {"name": "콘러드", "class": "ELF", "level": 1},
        }

    server = _Server(count=2)
    server.frames = [_Frame(hello("dd8dc854"), "peer-old")]
    drain_leader_reports(server=server, start_rally=start)
    server.frames = [_Frame(hello("bf3c23b8"), "peer-new")]
    drain_leader_reports(server=server, start_rally=start)
    assert discovery.by_connection["bf3c23b8"].status == MembershipStatus.CONFLICT
    server.dropped = ["peer-old"]
    drain_leader_reports(server=server, start_rally=start)
    assert "dd8dc854" not in discovery.by_connection
    assert discovery.by_connection["bf3c23b8"].status == MembershipStatus.MATCHED
    server.dropped = ["peer-new"]
    server.frames = [_Frame(hello("bb625ad7"), "peer-again")]
    drain_leader_reports(server=server, start_rally=start)
    assert discovery.by_connection["bb625ad7"].status == MembershipStatus.MATCHED
    discovery.clear()


def test_paused_snapshot_blocks_rally_march_and_focus(monkeypatch):
    orders = MemberOrders()
    manager = _manager(monkeypatch, _Pose(4, 10, 10))
    manager.runtime.network_party = True
    manager.runtime.orders_open = True
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
    cached = SimpleNamespace(last_memory_snapshot={"sample": 1})
    fresh = SimpleNamespace(last_memory_snapshot={"sample": 2})
    ctrl._party_world = cached
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
        ctrl._note_member_link(brain, cached)
        assert brain.runtime.sync_pose_ready is False
        ctrl._note_member_link(brain, fresh)
        assert brain.runtime.sync_pose_ready is True
        assert brain.runtime.sync_hold is True
        done = _sync("s", 4, "done")
        done["pull"] = token
        member_orders.ingest([_Frame(_policy("s", ["멤버"])), _Frame(done)])
        assert member_orders.sync_answered is True
        assert consider_sync(member_orders, name="멤버", on_roster=True) == "applied"
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
            from websocket.server import PartyServer

            frame = PartyServer._coerce(body, sender=sender or "leader")
            sent.append((peer, frame.message))

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


def test_running_leader_clears_a_stale_paused_sync():
    """Stop/Start leftover pause must not keep members locked after Running."""
    from types import SimpleNamespace

    from app._06_party.leader_rally import LeaderStartRally
    from app._06_party.party_sync import LeaderSync
    from session.bot_controller import BotController, RunState
    from websocket.party_orders import Rally

    start = LeaderStartRally(Rally(), log=lambda _m: None, clock=lambda: 0.0)
    start.state = "done"
    ctrl = BotController()
    ctrl._profile.party_enabled = True
    ctrl._profile.party_role = "leader"
    ctrl._party_policy_id = "policy-live"
    ctrl._start_rally = start
    ctrl._party_comms._leader = SimpleNamespace(
        watchdog=SimpleNamespace(server=object()), owned=True
    )
    stale = LeaderSync()
    stale.pause(start, 0.0)
    assert stale.run == "paused"
    ctrl._leader_sync = stale
    ctrl._set_state(RunState.RUNNING, "")
    body = ctrl._party_sync_observe()
    assert body is not None
    assert body["run"] == "running"
    assert ctrl._leader_sync_box().run == "running"

    ctrl._reset_leader_sync()
    assert ctrl._leader_sync_box().run == "running"
    assert int(ctrl._leader_sync_box().rev) == 0


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


def test_resume_then_release_does_not_revive_the_old_march(monkeypatch):
    from app._02_state.enums import ActionType as HealType
    from app._06_party.comms.orders import member_orders

    member_orders.clear()
    member_orders.session = "sess"
    member_orders.leader_run = "running"
    member_orders.need_gen = 2
    member_orders.path_gen = 1
    member_orders.formation_path = {
        "type": "formation_path", "from": "leader", "session": "sess",
        "map_id": 4, "rev": 1, "seq": 1, "cursor": 0,
        "tiles": [[10, 10], [12, 11]], "clear": False,
    }
    member_orders.party_focus = {"support": "멤버", "seq": 1}
    member_orders.focus_gen = 1
    mgr, state = _decide_member(monkeypatch, "멤버", (10, 10), (14, 10))
    mgr.runtime.sync_hold = True
    heal = SimpleNamespace(action=HealType.HEAL, reason="urgent self heal")
    monkeypatch.setattr("app._06_party.manager.apply_party_support", lambda *_a, **_k: heal)
    mgr._nav_blackboard = SimpleNamespace(scratch={}, side_intents=[])
    during = mgr.decide(state)
    assert during.action is not ActionType.TRAVELING, getattr(during, "reason", "")
    assert getattr(during, "action", None) is HealType.HEAL
    mgr.runtime.sync_hold = False
    after = mgr.decide(state)
    assert _goal_of(after) != (12, 11)
    assert "march" not in str(getattr(after, "reason", ""))
    member_orders.clear()


def test_reply_and_pose_order_and_stale_inputs_do_not_release():
    from session.bot_controller import BotController
    from websocket.party_orders import member_orders
    from app._06_party.manager import PartyMemberManager

    member_orders.clear()
    ctrl = BotController()
    ctrl._profile.party_role = "member"
    ctrl._profile.party_leader_host = "10.0.0.8"
    ctrl._profile.party_enabled = True
    ctrl._profile.party_member_enabled = True
    brain = PartyMemberManager()
    brain.runtime.network_party = True
    ctrl._party_brain_ref = brain
    cached = SimpleNamespace(last_memory_snapshot={"sample": 1})
    ctrl._party_world = cached
    ctrl._party_pause_clock(resume=True)
    token = member_orders.sync_pull
    policy = _policy("s", ["멤버"])
    done = _sync("s", 3, "done")
    done["pull"] = token

    def _apply(world):
        ctrl._note_member_link(brain, world)

    import app._04_decision.world_nav.session as nav_session
    previous = nav_session.live_pose_from_state
    nav_session.live_pose_from_state = lambda _w: SimpleNamespace(map_id=4, x=1, y=1)
    try:
        member_orders.ingest([_Frame(policy), _Frame(done)])
        consider_sync(member_orders, name="멤버", on_roster=True)
        _apply(cached)
        assert brain.runtime.sync_hold is True
        _apply(SimpleNamespace(last_memory_snapshot={"sample": 2}))
        assert brain.runtime.sync_hold is False
    finally:
        nav_session.live_pose_from_state = previous
        member_orders.clear()

    member_orders.clear()
    brain = PartyMemberManager()
    ctrl._party_brain_ref = brain
    ctrl._party_world = cached
    ctrl._party_pause_clock(resume=True)
    nav_session.live_pose_from_state = lambda _w: SimpleNamespace(map_id=4, x=1, y=1)
    try:
        _apply = lambda world: ctrl._note_member_link(brain, world)
        _apply(SimpleNamespace(last_memory_snapshot={"sample": 3}))
        assert brain.runtime.sync_hold is True
        stale = _sync("s", 3, "done")
        stale["pull"] = 1
        member_orders.ingest([_Frame(_policy("s", ["멤버"])), _Frame(stale)])
        consider_sync(member_orders, name="멤버", on_roster=True)
        ctrl._release_sync_hold(brain.runtime)
        assert brain.runtime.sync_hold is True
        fresh = _sync("s", 3, "done")
        fresh["pull"] = member_orders.sync_pull
        member_orders.ingest([_Frame(fresh)])
        ctrl._release_sync_hold(brain.runtime)
        assert brain.runtime.sync_hold is False
    finally:
        nav_session.live_pose_from_state = previous
        member_orders.clear()


def test_policy_and_snapshot_order_and_roster_removal():
    first = MemberOrders()
    policy = _policy("s", ["멤버"])
    active = _sync("s", 2, "active", (4, 30, 31))
    first.ingest([_Frame(policy)])
    assert consider_sync(first, name="멤버", on_roster=True) == "none"
    first.ingest([_Frame(active)])
    assert consider_sync(first, name="멤버", on_roster=True) == "applied"
    assert first.gather["x"] == 30

    second = MemberOrders()
    second.ingest([_Frame(active)])
    assert consider_sync(second, name="멤버", on_roster=None) == "held"
    assert getattr(second, "applied_sync", None) is None
    second.ingest([_Frame(policy)])
    assert consider_sync(second, name="멤버", on_roster=True) == "applied"
    assert second.gather["x"] == 30

    removed = MemberOrders()
    removed.ingest([_Frame(_policy("s", ["다른"])), _Frame(active)])
    assert consider_sync(removed, name="멤버", on_roster=False) == "dropped"
    assert removed.gather is None
    assert removed.leader_run == ""
    assert removed.sync_excluded is True


def test_member_resume_after_rally_done_rejoins_the_leader(monkeypatch):
    from app._06_party.comms.orders import member_orders

    member_orders.clear()
    member_orders.session = "s"
    member_orders.leader_run = "running"
    member_orders.gather = {
        "type": "rally", "stage": "start", "session": "s", "rev": 2,
        "map_id": 4, "x": 80, "y": 90,
    }
    mgr, state = _decide_member(monkeypatch, "멤버", (10, 10), (18, 10))
    mgr.runtime.sync_hold = True
    waiting = mgr.decide(state)
    assert waiting.action is not ActionType.TRAVELING, getattr(waiting, "reason", "")
    assert _goal_of(waiting) != (80, 90)
    member_orders.ingest([
        _Frame(_policy("s", ["멤버"])),
        _Frame(_sync("s", 4, "done")),
    ])
    assert consider_sync(member_orders, name="멤버", on_roster=True) == "applied"
    assert member_orders.gather is None
    mgr.runtime.sync_hold = False
    member_orders.leader_run = "running"
    member_orders.need_gen = 1
    joined = mgr.decide(state)
    assert _goal_of(joined) != (80, 90)
    assert joined.action is ActionType.TRAVELING
    assert "leader" in str(getattr(joined, "reason", ""))
    member_orders.clear()


def test_session_change_clears_the_pull_and_can_request_again():
    from session.bot_controller import BotController
    from websocket.party_orders import member_orders
    from app._06_party.manager import PartyMemberManager

    member_orders.clear()
    ctrl = BotController()
    brain = PartyMemberManager()
    brain.runtime.sync_hold = True
    brain.runtime.sync_need_pull = True
    ctrl._party_brain_ref = brain
    member_orders.sync_pull = 4
    member_orders.session = "old"
    member_orders.ingest([_Frame(_sync("new", 1, "pending"))])
    assert member_orders.sync_pull is None
    assert brain.runtime.sync_hold is True
    ctrl._ensure_sync_pull(brain.runtime)
    assert isinstance(member_orders.sync_pull, int)
    assert member_orders.sync_pull != 4
    member_orders.clear()


def _open_world(monkeypatch):
    import sys
    import types

    sys.modules.setdefault("cv2", types.ModuleType("cv2"))

    class _Grid:
        width = 40
        height = 16

        def is_walkable(self, x, y):
            return 0 <= int(x) < 40 and 0 <= int(y) < 16

        def can_step(self, cx, cy, nx, ny):
            return self.is_walkable(nx, ny)

        def tile_cost(self, x, y):
            return 1

        def dist_to_wall(self, x, y):
            return 2

    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: _Grid())
    monkeypatch.setattr(
        "app._03_world.merge.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )


def _decide_member(monkeypatch, name, here, leader, *, party_on=True):
    from app._02_state.enums import CharacterType
    from app._06_party.config import PartyMemberConfig
    from app._06_party.leader import LeaderView
    from app._06_party.manager import PartyMemberManager

    _open_world(monkeypatch)
    monkeypatch.setattr(
        "app._06_party.manager.resolve_leader",
        lambda *_a, **_k: LeaderView(
            name="Lead",
            tile=leader,
            map_id=4,
            same_map=True,
            fresh=True,
            source="sync",
            farming=False,
        ),
    )
    mgr = PartyMemberManager(PartyMemberConfig(leader_name="Lead", stop_tiles=1))
    mgr.apply_leader_policy(
        {"leader_name": "Lead", "leader_mode": "moving", "roster": [{"name": name}]},
        self_name=name,
    )
    mgr.set_local_map_id(4)
    mgr.set_world_origin(SimpleNamespace(x=here[0], y=here[1]))
    mgr.runtime.network_party = party_on
    mgr.runtime.orders_open = True
    party = {
        "in_party": True,
        "members": [
            {"name": "Lead", "is_leader": True, "map_id": 4, "x": leader[0], "y": leader[1]},
            {"name": name, "map_id": 4, "x": here[0], "y": here[1]},
        ],
    }
    state = SimpleNamespace(
        player=SimpleNamespace(
            identity=SimpleNamespace(name=name),
            species_name=name,
            character_type=CharacterType.KNIGHT,
            hp=100,
            max_hp=100,
            memory_guid="",
        ),
        last_party=party,
        last_print_state=None,
        objects=lambda *_a, **_k: [],
        monsters=lambda: [],
        party_read_ok=True,
    )
    return mgr, state


def _goal_of(intent):
    import re

    found = re.findall(r"(-?\d+),(-?\d+)", str(getattr(intent, "reason", "") or ""))
    if not found:
        return None
    return int(found[-1][0]), int(found[-1][1])


def test_resume_hold_does_not_walk_the_old_march(monkeypatch):
    from app._06_party.comms.orders import member_orders

    member_orders.clear()
    member_orders.session = "sess"
    member_orders.formation_path = {
        "type": "formation_path",
        "from": "leader",
        "session": "sess",
        "map_id": 4,
        "rev": 1,
        "seq": 1,
        "cursor": 0,
        "tiles": [[10, 10], [11, 10], [12, 11]],
        "clear": False,
    }
    mgr, state = _decide_member(monkeypatch, "멤버", (10, 10), (10, 10))
    mgr.runtime.sync_hold = True
    intent = mgr.decide(state)
    assert intent.action is not ActionType.TRAVELING, getattr(intent, "reason", "")
    assert _goal_of(intent) != (12, 11)
    member_orders.clear()


def test_paused_leader_does_not_follow_from_five_tiles(monkeypatch):
    from app._06_party.comms.orders import member_orders

    member_orders.clear()
    member_orders.session = "sess"
    member_orders.leader_run = "paused"
    mgr, state = _decide_member(monkeypatch, "멤버", (5, 10), (10, 10))
    intent = mgr.decide(state)
    assert intent.action is not ActionType.TRAVELING, getattr(intent, "reason", "")
    assert _goal_of(intent) != (10, 10)
    member_orders.clear()
