"""Shared march: members walk their own slot from the leader's path."""
from types import SimpleNamespace

import pytest

from app._02_state.enums import ActionType
from app._06_party.formation import OTHER_MAP
from app._06_party.formation_march import (
    MARCH_GAP_TILES,
    MarchShare,
    accept_march,
    clip_leader_hop,
    leader_path_gap,
    member_goal,
    pace_aim,
    progress_index,
)
from app._06_party.leader import LeaderView
from app._06_party.policy import MemberKind, PolicyInput, decide_policy


class _Open:
    def is_walkable(self, x, y):
        return True


class _Door:
    """One-tile corridor through x < 7. Past that, side tiles exist."""

    def is_walkable(self, x, y):
        x, y = int(x), int(y)
        if x < 7:
            return y == 0 and 0 <= x <= 20
        return 0 <= x <= 20 and abs(y) <= 3


class _Frame:
    def __init__(self, message):
        self.message = message


def _policy(**kwargs):
    from app._06_party.config import PartyMemberConfig

    base = dict(
        paused=False,
        dead=False,
        origin_ok=True,
        leader_present=True,
        leader_dist=1,
        chasing=False,
        need_potion=False,
        self_threat=False,
        assist_ready=False,
        config=PartyMemberConfig(stop_tiles=2),
        leader_walk_dist=1,
    )
    base.update(kwargs)
    return PolicyInput(**base)


def _path_body(tiles, *, rev=1, seq=1, cursor=0, map_id=4, session="sess", clear=False):
    return {
        "type": "formation_path",
        "from": "leader",
        "session": session,
        "map_id": map_id,
        "rev": rev,
        "seq": seq,
        "cursor": cursor,
        "tiles": [[int(t[0]), int(t[1])] for t in tiles],
        "clear": clear,
    }


def _march(tiles, **kwargs):
    body = _path_body(tiles, **kwargs)
    path = accept_march(body, local_map_id=body["map_id"], session=body["session"])
    assert path is not None
    return path


@pytest.fixture
def orders():
    from app._06_party.comms.orders import member_orders

    saved = (
        member_orders.session,
        member_orders.formation_path,
        member_orders.make_way,
    )
    yield member_orders
    member_orders.session = saved[0]
    member_orders.formation_path = saved[1]
    member_orders.make_way = saved[2]


@pytest.fixture
def march_world(monkeypatch):
    """Open ground. Hops close toward the slot up to ``max_hop``."""

    def _terrain():
        return _Open()

    def _click(terrain, origin, goal, max_hop=2, **_kwargs):
        ox, oy = int(origin.x), int(origin.y)
        gx, gy = int(goal[0]), int(goal[1])
        limit = max(1, int(max_hop))
        dx = max(-limit, min(limit, gx - ox))
        dy = max(-limit, min(limit, gy - oy))
        # Prefer a real step; never land on the origin.
        if dx == 0 and dy == 0:
            return None, None, None
        hop = (ox + dx, oy + dy)
        return hop, [hop], hop

    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", _terrain)
    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _click)
    monkeypatch.setattr(
        "app._03_world.merge.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )


def _member(monkeypatch, orders, *, tile=(10, 10), name="lead", same_map=True, map_id=4):
    from app._06_party.config import PartyMemberConfig
    from app._06_party.manager import PartyMemberManager

    monkeypatch.setattr(
        "app._06_party.manager.resolve_leader",
        lambda *args, **kwargs: LeaderView(
            name=name,
            tile=tile,
            map_id=map_id,
            same_map=same_map,
            fresh=True,
            source="test",
        ),
    )
    mgr = PartyMemberManager(
        PartyMemberConfig(leader_name="lead", stop_tiles=2, seat_index=0, party_size=4)
    )
    mgr.leader_policy = {"leader_name": "lead"}
    mgr.set_local_map_id(4)
    mgr.set_world_origin(SimpleNamespace(x=10, y=9))
    orders.session = "sess"
    return mgr


def test_open_field_decide_walks_toward_the_slot_before_the_leader_moves(
    monkeypatch, orders, march_world
):
    """Leader tile is unchanged. The first movable tick is TRAVELING toward the slot."""
    tiles = [(10 + i, 10) for i in range(8)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=0)
    mgr = _member(monkeypatch, orders)
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    intent = mgr.decide(state)
    hop = mgr.runtime.follow_hop
    assert intent.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert "march" in str(intent.reason)
    assert hop is not None and hop[0] > 10
    # The march goal is not written into slot_dist, so catch-up stays off.
    assert mgr.runtime.scratch.get("catch_up") is False


def test_corner_heal_holds_the_front_then_restarts():
    tiles = [(i, 0) for i in range(16)]
    path = _march(tiles, cursor=10)
    heading = (1, 0)
    front, _goal = member_goal(
        path,
        seat=0,
        followers=4,
        me=(8, 0),
        terrain=_Open(),
        heading=heading,
        others=[(1, 2)],
        previous_progress=8,
    )
    healer, healer_goal = member_goal(
        path,
        seat=1,
        followers=4,
        me=(2, 0),
        terrain=_Open(),
        heading=heading,
        others=[(0, 8)],
        previous_progress=2,
    )
    assert front == "pace_wait"
    assert healer == "go" and healer_goal is not None and healer_goal[0] > 2
    assert leader_path_gap(tiles, (10, 0), [(8, 0), (2, 0)]) > MARCH_GAP_TILES
    resumed, resumed_goal = member_goal(
        path,
        seat=0,
        followers=4,
        me=(8, 0),
        terrain=_Open(),
        heading=heading,
        others=[(1, 7)],
        previous_progress=8,
    )
    assert resumed == "go" and resumed_goal is not None and resumed_goal[0] >= 8
    assert leader_path_gap(tiles, (10, 0), [(8, 0), (7, 0)]) <= MARCH_GAP_TILES
    # A dropped connection is not a tail the line waits on.
    assert leader_path_gap(tiles, (10, 0), [OTHER_MAP, (8, 0)]) == 2


def _deliver(orders, body):
    """Stamp the session the way ``publish_body`` does, then use the real inbox."""
    from app._06_party.comms.ingest import ingest_member_orders

    stamped = {**body, "session": "sess"}
    orders.session = "sess"

    class _Client:
        def drain(self):
            return [_Frame(stamped)]

    ingest_member_orders(_Client())
    return orders.formation_path


def test_corridor_frame_is_received_and_the_last_member_exits(orders):
    """Leader history is on the wire. Two members never share the entrance tile."""
    from app._06_party.formation_march import head_limit, seat_back

    full = [(i, 0) for i in range(20)]
    share = MarchShare()
    body = None
    for x in range(0, 7):
        body = share.update(
            map_id=4,
            here=(x, 0),
            guide=full[x:],
            traveling=True,
            pace_idle=False,
            cancel=False,
            terrain=_Door(),
            seats=[(4, 0), (3, 0), (2, 0), (1, 0)],
        )
    assert body is not None and body["clear"] is False
    assert body["tiles"][0] != [6, 0]
    assert body["tiles"][body["cursor"]] == [6, 0]
    assert body["base"] + body["cursor"] == 6
    received = _deliver(orders, body)
    path = accept_march(received, local_map_id=4, session="sess")
    assert path is not None
    assert path_tile_behind(path, 6)

    positions = [4, 3, 2, 1]
    leader = 6
    outside = set()
    for _tick in range(40):
        limit = head_limit(
            [(at, seat_back(seat)) for seat, at in enumerate(positions)]
        )
        if limit is not None and leader < limit and leader < 19:
            leader += 1
        body = share.update(
            map_id=4,
            here=(leader, 0),
            guide=full[leader:],
            traveling=True,
            pace_idle=False,
            cancel=False,
            terrain=_Door(),
            seats=[(at, 0) for at in positions],
        )
        if body is not None:
            received = _deliver(orders, body)
        path = accept_march(orders.formation_path, local_map_id=4, session="sess")
        assert path is not None
        goals = []
        for seat, at in enumerate(positions):
            if seat in outside:
                goals.append(("out", None))
                continue
            others = [
                (other, positions[other])
                for other in range(4)
                if other != seat and other not in outside
            ]
            kind, goal = member_goal(
                path,
                seat=seat,
                followers=4,
                me=(at, 0),
                terrain=_Door(),
                heading=(1, 0),
                others=others,
                previous_progress=at,
            )
            goals.append((kind, goal))
        claimed = [goal for kind, goal in goals if kind == "go" and goal is not None]
        assert len(claimed) == len(set(claimed))
        for seat, (kind, goal) in enumerate(goals):
            if kind != "go" or goal is None:
                continue
            occupied = {(positions[other], 0) for other in range(seat) if other not in outside}
            assert goal not in occupied
            if goal[1] == 0 and goal[0] != positions[seat]:
                positions[seat] = positions[seat] + (1 if goal[0] > positions[seat] else -1)
            if positions[seat] >= 7 and goal[1] != 0:
                outside.add(seat)
        if len(outside) == 4:
            break
    assert 3 in outside


def path_tile_behind(path, leader_full):
    return any(
        path.base + i < leader_full for i in range(len(path.tiles))
    )


def test_new_path_drops_the_old_hop_and_a_late_frame_is_ignored(
    monkeypatch, orders, march_world
):
    from websocket.party_orders import MemberOrders

    east = [(10 + i, 10) for i in range(8)]
    orders.formation_path = _path_body(east, rev=1, seq=1, cursor=0)
    mgr = _member(monkeypatch, orders)
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    old_hop = mgr.runtime.follow_hop
    assert first.action is ActionType.TRAVELING and old_hop is not None and old_hop[0] > 10

    south = [(10, 10 + i) for i in range(8)]
    orders.formation_path = _path_body(south, rev=2, seq=2, cursor=0)
    mgr.runtime.follow_hop = old_hop
    second = mgr.decide(state)
    assert second.action is ActionType.TRAVELING
    assert mgr.runtime.follow_hop != old_hop
    assert mgr.runtime.follow_hop[1] > 9

    box = MemberOrders()
    box.ingest([_Frame(_path_body(south, rev=2, seq=5, cursor=0))])
    box.ingest([_Frame(_path_body(east, rev=1, seq=4, cursor=0))])
    assert int(box.formation_path["seq"]) == 5
    assert box.formation_path["tiles"][1] == [10, 11]

    orders.formation_path = _path_body(east, rev=3, seq=3, cursor=0, clear=True)
    held = mgr.decide(state)
    assert held.action is not ActionType.TRAVELING
    assert mgr.runtime.last_kind == "hold"


def test_disconnect_does_not_freeze_and_a_new_client_receives_the_path():
    tiles = [(i, 0) for i in range(12)]
    assert leader_path_gap(tiles, (8, 0), [OTHER_MAP]) is None
    assert pace_aim(10, 8, None) == 10
    share = MarchShare()
    guide = tiles
    first = share.update(
        map_id=4,
        here=(2, 0),
        guide=guide,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=1,
    )
    assert first is not None and first["clear"] is False
    rev = first["rev"]
    again = share.update(
        map_id=4,
        here=(2, 0),
        guide=guide,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=1,
    )
    assert again is None
    same_count = share.update(
        map_id=4,
        here=(2, 0),
        guide=guide,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=1,
    )
    assert same_count is None
    share.note_hello()
    resent = share.update(
        map_id=4,
        here=(2, 0),
        guide=guide,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=1,
    )
    assert resent is not None and resent["rev"] == rev and resent["seq"] > first["seq"]
    held = share.update(
        map_id=4,
        here=(3, 0),
        guide=guide,
        traveling=True,
        pace_idle=True,
        cancel=False,
        clients=2,
    )
    assert share.active
    assert held is None or held["clear"] is False
    cleared = share.update(
        map_id=4,
        here=(3, 0),
        guide=guide,
        traveling=False,
        pace_idle=False,
        cancel=True,
        clients=2,
    )
    assert cleared is not None and cleared["clear"] is True
    assert share.active is False

    from websocket.party_orders import MemberOrders

    box = MemberOrders()
    box.session = "old"
    box.formation_path = _path_body(tiles, session="old", rev=1, seq=1)
    box.ingest([_Frame(_path_body(tiles, session="new", rev=4, seq=1, cursor=2))])
    assert box.session == "new"
    assert int(box.formation_path["rev"]) == 4


def test_without_a_shared_path_follow_hold_and_join_stay(
    monkeypatch, orders, march_world
):
    orders.formation_path = None
    mgr = _member(monkeypatch, orders)
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    held = mgr.decide(state)
    assert held.action is not ActionType.TRAVELING
    assert mgr.runtime.last_kind == "hold"

    far = _member(monkeypatch, orders, tile=(10, 14))
    walked = far.decide(state)
    assert walked.action is ActionType.TRAVELING
    assert far.runtime.last_kind == "follow"
    assert "march" not in str(walked.reason)

    other = _member(monkeypatch, orders, tile=(3, 3), same_map=False, map_id=9)
    orders.formation_path = _path_body([(10 + i, 10) for i in range(6)])
    joined = other.decide(state)
    assert joined.action is not ActionType.TRAVELING
    assert other.runtime.last_kind == "join_map"

    heal = decide_policy(_policy(need_heal=True, march_advance=True))
    assert heal.kind is MemberKind.HEAL
    close = decide_policy(_policy(march_advance=False))
    assert close.kind is MemberKind.HOLD
    started = decide_policy(_policy(march_advance=True))
    assert started.kind is MemberKind.FOLLOW

    paused = _member(monkeypatch, orders)
    paused.pause()
    orders.formation_path = _path_body([(10 + i, 10) for i in range(6)])
    stopped = paused.decide(state)
    assert stopped.action is not ActionType.TRAVELING
    assert paused.runtime.last_kind == "stop"


def test_progress_does_not_jump_the_far_arm_of_a_u_turn():
    tiles = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (3, 2), (2, 2), (1, 2), (0, 2)]
    assert progress_index(tiles, (0, 2), previous=1, near=1) is None
    assert progress_index(tiles, (0, 2), previous=7, near=1) == 8


def test_same_rev_keeps_the_hop_and_a_bad_frame_is_dropped(orders):
    from app._06_party.frame_check import reject_leader_frame
    from app._06_party.manager import PartyMemberManager
    from app._06_party.config import PartyMemberConfig

    assert reject_leader_frame(
        {"type": "formation_path", "from": "leader", "map_id": 4, "rev": 1, "seq": 1, "tiles": []}
    )
    assert reject_leader_frame(
        _path_body([(1, 1), (2, 1)], map_id=9)
    ) == ""
    assert accept_march(
        _path_body([(1, 1)], map_id=9),
        local_map_id=4,
        session="sess",
    ) is None

    mgr = PartyMemberManager(PartyMemberConfig())
    mgr.set_local_map_id(4)
    orders.session = "sess"
    orders.formation_path = _path_body([(0, 0), (1, 0)], rev=3, seq=1)
    mgr.runtime.scratch["march_rev"] = 3
    mgr.runtime.follow_hop = (1, 1)
    mgr._build_march(SimpleNamespace(x=0, y=0), SimpleNamespace(player=None), mgr.config)
    assert mgr.runtime.follow_hop == (1, 1)
    orders.formation_path = _path_body([(0, 0), (0, 1)], rev=4, seq=2)
    mgr._build_march(None, SimpleNamespace(player=None), mgr.config)
    assert mgr.runtime.follow_hop is None


def test_heal_holds_the_leaders_click_until_the_mage_steps():
    """The landing tile, not the current gap, is what the front may click."""
    full = [(i, 0) for i in range(31)]
    share = MarchShare()
    share.update(
        map_id=4,
        here=(0, 0),
        guide=full,
        traveling=True,
        pace_idle=False,
        cancel=False,
    )
    share.update(
        map_id=4,
        here=(20, 0),
        guide=full[20:],
        traveling=True,
        pace_idle=False,
        cancel=False,
        seats=[None, None, None, (10, 0)],
    )
    assert share.cursor_full == 20
    held = clip_leader_hop(share, (23, 0), [None, None, None, 10])
    assert held is None
    share.update(
        map_id=4,
        here=(20, 0),
        guide=full[20:],
        traveling=True,
        pace_idle=False,
        cancel=False,
        seats=[None, None, None, (11, 0)],
    )
    landed = clip_leader_hop(share, (23, 0), [None, None, None, 11])
    assert landed == (21, 0)


def test_door_wait_does_not_unstick_but_a_stuck_step_does(monkeypatch, orders, march_world):
    import time

    from app._02_state.enums import ActionType

    orders.formation_path = _path_body(
        [(i, 0) for i in range(12)],
        cursor=6,
    )
    orders.formation_path["door"] = 5
    orders.formation_path["exit"] = 9
    orders.formation_path["admit"] = 0
    mgr = _member(monkeypatch, orders, tile=(6, 0))
    from app._06_party.config import PartyMemberConfig

    mgr.config = PartyMemberConfig(
        leader_name="lead", stop_tiles=2, seat_index=1, party_size=4
    )
    mgr.set_world_origin(SimpleNamespace(x=2, y=0))
    now = time.monotonic()
    mgr.runtime.scratch["follow_stuck"] = {
        "tile": (2, 0),
        "since": now - 10,
        "last": now,
        "tried": [],
    }
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    held = mgr.decide(state)
    assert held.action is not ActionType.TRAVELING
    assert "follow_stuck" not in mgr.runtime.scratch
    assert "unstick" not in str(held.reason)

    orders.formation_path = _path_body([(10 + i, 10) for i in range(8)], rev=2, seq=2)
    walker = _member(monkeypatch, orders)
    walker.runtime.scratch["follow_stuck"] = {
        "tile": (10, 9),
        "since": now - 10,
        "last": now,
        "tried": [],
    }

    def _escape(*_args, **_kwargs):
        return (
            SimpleNamespace(action=ActionType.TRAVELING, reason="party_member:follow_unstick"),
            None,
            "unstick",
            (9, 9),
        )

    monkeypatch.setattr("app._06_party.manager.plan_follow_unstick", _escape)
    moved = walker.decide(state)
    assert "unstick" in str(getattr(moved, "reason", ""))


def test_same_count_reconnect_repeats_the_current_path():
    from app._06_party.comms.ingest import drain_leader_reports

    full = [(i, 0) for i in range(8)]
    share = MarchShare()
    first = share.update(
        map_id=4,
        here=(1, 0),
        guide=full,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=3,
    )
    assert first is not None
    assert share.update(
        map_id=4,
        here=(1, 0),
        guide=full,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=3,
    ) is None

    class _Server:
        def client_count(self):
            return 3

        def take_dropped(self):
            return []

        def drain(self):
            return [
                _Frame(
                    {
                        "type": "member_hello",
                        "from": "mage",
                        "client_id": "c1",
                        "character": {"name": "mage"},
                    }
                )
            ]

    seen = []
    drain_leader_reports(server=_Server(), on_hello=seen.append)
    assert seen == ["mage"]
    share.note_hello()
    resent = share.update(
        map_id=4,
        here=(1, 0),
        guide=full,
        traveling=True,
        pace_idle=False,
        cancel=False,
        clients=3,
    )
    assert resent is not None and resent["rev"] == first["rev"]
    assert resent["tiles"] == first["tiles"]


def test_a_still_leader_publishes_the_path_and_the_member_steps(
    monkeypatch, orders, march_world
):
    """Leader tile stays put. The first received path is a slot step, not a hold."""
    from app._02_state.enums import ActionType

    tiles = [(10, 10), (11, 10), (12, 10), (13, 10)]
    share = MarchShare()
    body = share.update(
        map_id=4,
        here=(10, 10),
        guide=tiles,
        traveling=True,
        pace_idle=False,
        cancel=False,
        terrain=_Open(),
        seats=[(10, 9)],
    )
    assert body is not None and body.get("clear") is not True
    assert [11, 10] in body["tiles"]
    _deliver(orders, body)
    mgr = _member(monkeypatch, orders)
    intent = mgr.decide(SimpleNamespace(player=None, last_party=None, objects=[]))
    hop = mgr.runtime.follow_hop
    assert intent.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert hop is not None and (hop[0] > 10 or hop[1] != 9)


def test_march_hop_asks_for_one_shortest_path(monkeypatch):
    from app._06_party.formation_march import MARCH_CLICK_TILES
    from app._06_party.follow import FOLLOW_CLICK_TILES
    from app._06_party.intents import plan_slot_hop

    seen = {}

    def _click(terrain, origin, goal, max_hop=2, **kwargs):
        seen["diverse"] = kwargs.get("diverse", True)
        seen["max_hop"] = max_hop
        ox, oy = int(origin.x), int(origin.y)
        hop = (ox + 1, oy)
        return hop, [hop], hop

    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: _Open())
    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _click)
    origin = SimpleNamespace(x=0, y=0)
    plan_slot_hop(origin, (4, 0), previous_goal=None, previous_hop=None, kind="march")
    assert seen["diverse"] is False
    assert int(seen["max_hop"]) == int(MARCH_CLICK_TILES)
    plan_slot_hop(origin, (4, 0), previous_goal=None, previous_hop=None, kind="stand")
    assert seen["diverse"] is True
    assert int(seen["max_hop"]) == int(FOLLOW_CLICK_TILES)


def test_loot_window_keeps_only_the_designated_seat_after_a_refight():
    from app._06_party.config import PartyMemberConfig
    from app._06_party.loot import (
        PARTY_LOOT_WINDOW_S,
        note_party_loot_window,
        party_designated_keeps_loot,
        party_loot_window_open,
        release_party_loot_window,
    )

    scratch = {}
    plain = PartyMemberConfig(loot_role="none")
    named = PartyMemberConfig(loot_role="responsible")
    note_party_loot_window(scratch, fighting=True, now=0.0)
    note_party_loot_window(scratch, fighting=False, now=1.0)
    assert party_loot_window_open(scratch, 1.0)
    assert not party_designated_keeps_loot(plain, scratch, fighting=True, now=3.0)
    assert party_designated_keeps_loot(named, scratch, fighting=True, now=3.0)
    assert not party_loot_window_open(scratch, 1.0 + PARTY_LOOT_WINDOW_S)
    note_party_loot_window(scratch, fighting=True, now=10.0)
    note_party_loot_window(scratch, fighting=False, now=11.0)
    release_party_loot_window(scratch)
    assert not party_designated_keeps_loot(named, scratch, fighting=True, now=12.0)


def test_sync_hold_and_a_paused_leader_do_not_walk_an_old_order(
    monkeypatch, orders, march_world
):
    """A held sync does not step. After it opens, the live leader tile does."""
    from app._02_state.enums import ActionType

    orders.leader_run = ""
    orders.formation_path = _path_body([(10 + i, 10) for i in range(6)])
    mgr = _member(monkeypatch, orders, tile=(10, 20))
    mgr.set_world_origin(SimpleNamespace(x=10, y=9))
    mgr.runtime.network_party = True
    mgr.runtime.orders_open = True
    mgr.runtime.sync_hold = True
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    waiting = mgr.decide(state)
    assert waiting.action is not ActionType.TRAVELING
    assert mgr.runtime.last_reason == "party_orders_held"

    orders.leader_run = "paused"
    mgr.runtime.sync_hold = False
    paused = mgr.decide(state)
    assert paused.action is not ActionType.TRAVELING
    assert mgr.runtime.last_reason == "party_orders_held"

    orders.leader_run = "running"
    orders.formation_path = None
    joined = mgr.decide(state)
    assert joined.action is ActionType.TRAVELING
    assert "leader" in str(joined.reason)
    orders.leader_run = ""


def test_shop_duty_returns_to_the_latest_slot(monkeypatch, orders, march_world):
    from app._02_state.enums import ActionType

    calls = {"n": 0}

    def _duty(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            from app._06_party.types import ActionIntent

            return ActionIntent(action=ActionType.IDLE, reason="shop")
        return None

    monkeypatch.setattr("app._06_party.arrow_duty.tick_shopkeeper_duty", _duty)
    monkeypatch.setattr(
        "app._06_party.manager.PartyMemberManager._opening_shopkeeper_heal",
        lambda *a, **k: None,
    )
    east = [(10 + i, 10) for i in range(6)]
    orders.formation_path = _path_body(east, rev=1, seq=1)
    mgr = _member(monkeypatch, orders)
    mgr._nav_blackboard = SimpleNamespace(scratch={}, current_item_id=None)
    mgr.config.seat_role = "shopkeeper"
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    assert first.reason == "shop"
    south = [(10, 10 + i) for i in range(6)]
    orders.formation_path = _path_body(south, rev=2, seq=2)
    second = mgr.decide(state)
    assert second.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert mgr.runtime.follow_hop is not None and mgr.runtime.follow_hop[1] > 9


def test_one_tick_hop_miss_keeps_the_march_goal_not_a_leader_hop(
    monkeypatch, orders, march_world
):
    """A missing hop this tick does not click the leader tile behind the slot."""
    from app._02_state.enums import ActionType

    tiles = [(10 + i, 10) for i in range(8)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=0)
    mgr = _member(monkeypatch, orders, tile=(10, 10))
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    assert first.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert "march" in str(first.reason)
    slot = mgr.runtime.scratch.get("march_goal")
    assert isinstance(slot, tuple) and slot[0] > 10

    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: None)
    missed = mgr.decide(state)
    assert "leader" not in str(missed.reason)
    assert mgr.runtime.last_kind == "march"
    assert mgr.runtime.scratch.get("march_goal") == slot

    # Terrain returns: same shared path, same slot direction.
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: _Open())
    recovered = mgr.decide(state)
    assert recovered.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert "march" in str(recovered.reason)
    hop = mgr.runtime.follow_hop
    assert hop is not None and hop[0] > 10


def test_leader_within_stop_tiles_still_marches_to_a_slot_ahead(
    monkeypatch, orders, march_world
):
    """walk=1 to the leader does not hold when the shared slot is six tiles out."""
    from app._02_state.enums import ActionType

    tiles = [(10 + i, 10) for i in range(10)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=0)
    mgr = _member(monkeypatch, orders, tile=(10, 10))
    mgr.set_world_origin(SimpleNamespace(x=10, y=9))
    intent = mgr.decide(SimpleNamespace(player=None, last_party=None, objects=[]))
    assert intent.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert "hold dist=" not in str(mgr.runtime.last_reason)
    hop = mgr.runtime.follow_hop
    assert hop is not None and hop[0] > 10


def test_in_transit_keeps_the_march_hop_without_a_new_click(
    monkeypatch, orders, march_world
):
    from app._02_state.enums import ActionType

    tiles = [(10 + i, 10) for i in range(8)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=0)
    mgr = _member(monkeypatch, orders)
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    assert first.action is ActionType.TRAVELING
    slot = mgr.runtime.scratch.get("march_goal")
    assert isinstance(slot, tuple)
    from app._06_party.follow import unit8

    step = unit8((int(slot[0]) - 10, int(slot[1]) - 9))
    assert step != (0, 0)
    # Pending hop more than one tile out on the slot bearing.
    pending = (10 + 2 * step[0], 9 + 2 * step[1])
    mgr.runtime.follow_hop = pending
    mgr.runtime.approach_goal = slot

    monkeypatch.setattr(
        "app._06_party.intents._body_moving", lambda: True
    )
    held = mgr.decide(state)
    assert held.action is not ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert mgr.runtime.last_reason == "follow_in_transit"
    assert mgr.runtime.follow_hop == pending
    assert "leader" not in str(held.reason)


def test_door_wait_does_not_fall_through_to_leader_follow(
    monkeypatch, orders, march_world
):
    from app._02_state.enums import ActionType
    from app._06_party.config import PartyMemberConfig

    orders.formation_path = _path_body([(i, 0) for i in range(12)], cursor=6)
    orders.formation_path["door"] = 5
    orders.formation_path["exit"] = 9
    orders.formation_path["admit"] = 0
    mgr = _member(monkeypatch, orders, tile=(6, 0))
    mgr.config = PartyMemberConfig(
        leader_name="lead", stop_tiles=2, seat_index=1, party_size=4
    )
    mgr.set_world_origin(SimpleNamespace(x=2, y=0))
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    waiting = mgr.decide(state)
    assert waiting.action is not ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    assert "leader" not in str(waiting.reason)
    assert "door_wait" in str(mgr.runtime.last_reason) or "door_wait" in str(
        waiting.reason
    )


def test_cleared_path_releases_to_ordinary_follow(monkeypatch, orders, march_world):
    from app._02_state.enums import ActionType

    tiles = [(10 + i, 10) for i in range(8)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=0)
    mgr = _member(monkeypatch, orders, tile=(10, 14))
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    assert first.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"

    orders.formation_path = _path_body(tiles, rev=2, seq=2, cursor=0, clear=True)
    released = mgr.decide(state)
    assert released.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "follow"
    assert "leader" in str(released.reason)
    assert mgr.runtime.scratch.get("march_goal") is None


def test_cursor_advance_moves_slot_off_the_departure_stand():
    """Error 1: after assembly the slot tracks cursor+lookahead, not the start."""
    tiles = [(10 + i, 10) for i in range(12)]
    path0 = _march(tiles, cursor=0)
    kind0, goal0 = member_goal(
        path0,
        seat=0,
        followers=4,
        me=(10, 9),
        terrain=_Open(),
        heading=(1, 0),
        others=[],
        previous_progress=None,
        previous_goal=None,
    )
    assert kind0 == "go" and goal0 is not None
    path4 = _march(tiles, cursor=4)
    kind4, goal4 = member_goal(
        path4,
        seat=0,
        followers=4,
        me=(10, 9),
        terrain=_Open(),
        heading=(1, 0),
        others=[],
        previous_progress=None,
        previous_goal=goal0,
    )
    assert kind4 == "go" and goal4 is not None
    # Cursor moved four tiles; sticky must not keep the departure-side slot.
    assert goal4[0] > goal0[0]
    assert goal4[0] >= 14


def test_no_path_tick_keeps_march_ownership_without_backward_leader_click(
    monkeypatch, orders, march_world
):
    """Error 2: temporary hop miss stays on the march slot, never the leader."""
    from app._02_state.enums import ActionType

    tiles = [(10 + i, 10) for i in range(10)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=3)
    mgr = _member(monkeypatch, orders, tile=(10, 10))
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    assert first.action is ActionType.TRAVELING
    assert mgr.runtime.last_kind == "march"
    slot = mgr.runtime.scratch.get("march_goal")
    assert isinstance(slot, tuple) and slot[0] > 10
    hop = mgr.runtime.follow_hop
    assert hop is not None and hop[0] > 10

    def _miss(*_a, **_k):
        return None, None, None

    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _miss)
    missed = mgr.decide(state)
    assert mgr.runtime.last_kind == "march"
    assert "leader" not in str(missed.reason)
    assert mgr.runtime.scratch.get("march_goal") == slot
    # No replacement click onto the leader tile behind the body.
    if missed.action is ActionType.TRAVELING:
        assert missed.destination is None or (
            int(getattr(missed.destination, "x", missed.destination[0])) >= 10
        )


def test_march_extends_hop_when_slot_is_ahead_while_moving(
    monkeypatch, orders, march_world
):
    """Error 3: moving with a short pending hop replans when the slot pulls away."""
    from app._02_state.enums import ActionType
    from app._06_party.formation_march import MARCH_CLICK_TILES

    tiles = [(10 + i, 10) for i in range(14)]
    orders.formation_path = _path_body(tiles, rev=1, seq=1, cursor=8)
    mgr = _member(monkeypatch, orders, tile=(10, 10))
    state = SimpleNamespace(player=None, last_party=None, objects=[])
    first = mgr.decide(state)
    assert first.action is ActionType.TRAVELING
    slot = mgr.runtime.scratch.get("march_goal")
    assert isinstance(slot, tuple) and slot[0] >= 16
    # Short hop still in flight while the slot is far ahead.
    mgr.runtime.follow_hop = (12, 9)
    mgr.runtime.approach_goal = slot
    mgr.runtime.follow_hop_at = 0.0

    seen = {}

    def _click(terrain, origin, goal, max_hop=2, **_kwargs):
        seen["max_hop"] = max_hop
        ox, oy = int(origin.x), int(origin.y)
        gx, gy = int(goal[0]), int(goal[1])
        limit = max(1, int(max_hop))
        dx = max(-limit, min(limit, gx - ox))
        dy = max(-limit, min(limit, gy - oy))
        hop = (ox + dx, oy + dy)
        return hop, [hop], hop

    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _click)
    monkeypatch.setattr("app._06_party.intents._body_moving", lambda: True)
    extended = mgr.decide(state)
    assert mgr.runtime.last_kind == "march"
    assert extended.action is ActionType.TRAVELING
    assert int(seen.get("max_hop", 0)) == int(MARCH_CLICK_TILES)
    hop = mgr.runtime.follow_hop
    assert hop is not None
    # Continuation past the short two-tile pending hop.
    assert max(abs(hop[0] - 10), abs(hop[1] - 9)) > 2
