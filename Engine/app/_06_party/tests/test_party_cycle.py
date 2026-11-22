"""One cycle: the leader's frame, each member's eyes, and the click that comes out.

Clicks are not movement. A hop is recorded first. The body steps on a later event.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app._02_state.enums import ActionType, CharacterType
from app._06_party.config import PartyMemberConfig
from app._06_party.formation_march import MarchShare, head_limit, seat_back
from app._06_party.leader import LeaderView
from app._06_party.manager import PartyMemberManager


class _Grid:
    """Walk grid the real pathfinder can search. Walls are the observation."""

    def __init__(self, walk, width=40, height=16):
        self._walk = walk
        self.width = width
        self.height = height

    def is_walkable(self, x, y):
        return self._walk(int(x), int(y))

    def can_step(self, cx, cy, nx, ny):
        return self.is_walkable(nx, ny)

    def tile_cost(self, x, y):
        return 1

    def dist_to_wall(self, x, y):
        return 2 if self.is_walkable(x, y) else 0


def _corridor(x, y):
    if x < 7:
        return y == 8 and 0 <= x < 40
    return 0 <= x < 40 and 6 <= y <= 10


def _open(x, y):
    return 0 <= x < 40 and 0 <= y < 16


class _Frame:
    def __init__(self, message):
        self.message = message


def _deliver(orders, body):
    from app._06_party.comms.ingest import ingest_member_orders

    orders.session = "sess"
    stamped = {**body, "session": "sess"}

    class _Client:
        def drain(self):
            return [_Frame(stamped)]

    ingest_member_orders(_Client())


def _party(rows):
    members = [{"name": "Lead", "is_leader": True, "map_id": 4, "x": rows["Lead"][0], "y": rows["Lead"][1]}]
    for name, tile in rows.items():
        if name == "Lead":
            continue
        members.append({"name": name, "map_id": 4, "x": tile[0], "y": tile[1]})
    return {"in_party": True, "members": members}


def _player(name, kind):
    return SimpleNamespace(
        identity=SimpleNamespace(name=name),
        species_name=name,
        character_type=kind,
        hp=100,
        max_hp=100,
        memory_guid="",
    )


def _state(name, kind, tile, party, objects):
    def _objects(kind_filter=None):
        return list(objects)

    return SimpleNamespace(
        player=_player(name, kind),
        last_party=party,
        last_print_state=None,
        objects=_objects,
        monsters=lambda: list(objects),
        party_read_ok=True,
    )


_GOAL = re.compile(r"(-?\d+),(-?\d+)")


def _goal(intent):
    found = _GOAL.findall(str(getattr(intent, "reason", "") or ""))
    if not found:
        return None
    x, y = found[-1]
    return int(x), int(y)


@pytest.fixture
def orders():
    from app._06_party.comms.orders import member_orders

    saved = (
        member_orders.session,
        member_orders.formation_path,
        member_orders.party_focus,
        member_orders.supply_hold,
        member_orders.supply_drop,
        int(getattr(member_orders, "need_gen", 0) or 0),
        str(getattr(member_orders, "leader_run", "") or ""),
        member_orders.gather,
    )
    member_orders.need_gen = 0
    member_orders.path_gen = 0
    member_orders.focus_gen = 0
    member_orders.leader_run = ""
    member_orders.gather = None
    member_orders.sync_frame = None
    yield member_orders
    (
        member_orders.session,
        member_orders.formation_path,
        member_orders.party_focus,
        member_orders.supply_hold,
        member_orders.supply_drop,
        member_orders.need_gen,
        member_orders.leader_run,
        member_orders.gather,
    ) = saved


@pytest.fixture
def world(monkeypatch):
    box = {"terrain": _Grid(_open), "leader": (10, 10)}

    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: box["terrain"])
    monkeypatch.setattr(
        "app._03_world.merge.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )

    def _resolve(*_a, **_k):
        return LeaderView(
            name="Lead",
            tile=box["leader"],
            map_id=4,
            same_map=True,
            fresh=True,
            source="cycle",
            farming=True,
        )

    monkeypatch.setattr("app._06_party.manager.resolve_leader", _resolve)
    return box


def _roster():
    return [
        {"name": "Knight", "role": "member", "loot": "responsible"},
        {"name": "Archer", "role": "member", "loot": "none"},
        {"name": "Mage", "role": "mage", "loot": "none"},
        {"name": "Assist", "role": "member", "loot": "none"},
    ]


def _members(orders):
    policy = {
        "leader_name": "Lead",
        "leader_mode": "moving",
        "party_size": 4,
        "roster": _roster(),
        "random_loot": False,
    }
    kinds = {
        "Knight": CharacterType.KNIGHT,
        "Archer": CharacterType.ELF,
        "Mage": CharacterType.MAGE,
        "Assist": CharacterType.KNIGHT,
    }
    out = {}
    for name in kinds:
        mgr = PartyMemberManager(PartyMemberConfig(leader_name="Lead", stop_tiles=2))
        mgr.apply_leader_policy(policy, self_name=name)
        mgr.set_local_map_id(4)
        mgr.leader_policy = policy
        out[name] = mgr
    orders.session = "sess"
    return out, policy


def _publish(share, orders, here, guide, seats, terrain):
    body = share.update(
        map_id=4,
        here=here,
        guide=guide,
        traveling=True,
        pace_idle=False,
        cancel=False,
        terrain=terrain,
        seats=seats,
    )
    if body is not None:
        _deliver(orders, body)
    return body


def test_cycle_from_the_leaders_frame_to_each_click(monkeypatch, orders, world):
    """Open ground, one-tile door, a fight, a rear threat, then the turret dot."""
    from app._03_world import ActionType as TurretAction
    from app._04_decision.behaviors.party_turret import (
        set_party_turret,
        step_party_turret_leash,
    )
    from app._06_party.sightings import book, sighting_message
    from app._06_party.tests.test_make_way_pace import _Clock, _leader_controller

    members, _policy = _members(orders)
    assert [members[name].config.seat_index for name in ("Knight", "Archer", "Mage", "Assist")] == [0, 1, 2, 3]

    # 1. Open ground. The leader has not stepped. Each member still clicks a slot.
    names = ("Knight", "Archer", "Mage", "Assist")
    spots = {"Knight": (9, 10), "Archer": (8, 10), "Mage": (8, 8), "Assist": (8, 9)}
    world["leader"] = (10, 10)
    guide = [(10 + i, 10) for i in range(12)]
    share = MarchShare()
    _publish(share, orders, (10, 10), guide, [spots[name] for name in names], world["terrain"])
    party = _party({"Lead": (10, 10), **spots})
    goals = {}
    for name in names:
        tile = spots[name]
        members[name].set_world_origin(SimpleNamespace(x=tile[0], y=tile[1]))
        intent = members[name].decide(_state(name, CharacterType.KNIGHT, tile, party, []))
        assert intent.action is ActionType.TRAVELING, (name, intent.reason)
        goals[name] = _goal(intent)
        assert members[name].runtime.follow_hop != spots[name]
    assert len(set(goals.values())) == 4
    assert (10, 10) not in goals.values()

    # 2. One-tile door. Clicks are issued before anyone moves.
    world["terrain"] = _Grid(_corridor)
    world["leader"] = (6, 8)
    line = [(i, 8) for i in range(24)]
    share = MarchShare()
    order = list(names)
    at = {name: (xs, 8) for name, xs in zip(order, (4, 3, 2, 1))}
    for x in range(0, 7):
        _publish(
            share, orders, (x, 8), line[x:],
            [at[name] for name in order], world["terrain"],
        )
    for _tick in range(48):
        party = _party({"Lead": world["leader"], **at})
        claimed = []
        clicks = {}
        for name in order:
            here = at[name]
            members[name].set_world_origin(SimpleNamespace(x=here[0], y=here[1]))
            intent = members[name].decide(
                _state(name, CharacterType.KNIGHT, here, party, [])
            )
            hop = members[name].runtime.follow_hop
            # The click is not the body moving.
            if intent.action is ActionType.TRAVELING and hop is not None and hop != here:
                claimed.append(_goal(intent) or hop)
                clicks[name] = hop
        assert len(claimed) == len(set(claimed))
        for name, hop in clicks.items():
            hx, hy = at[name]
            sx = 0 if hop[0] == hx else (1 if hop[0] > hx else -1)
            sy = 0 if hop[1] == hy else (1 if hop[1] > hy else -1)
            at[name] = (hx + sx, hy + sy)
        limit = head_limit([(at[name][0], seat_back(i)) for i, name in enumerate(order)])
        leader_x = world["leader"][0]
        if limit is not None and leader_x < limit and leader_x < 20:
            leader_x += 1
            world["leader"] = (leader_x, 8)
        _publish(
            share, orders, world["leader"], line[leader_x:],
            [at[name] for name in order], world["terrain"],
        )
        if all(pos[0] >= 7 for pos in at.values()):
            break
    assert all(pos[0] >= 7 for pos in at.values()), at

    # 3. Knight steps beside A. The click is not the drop behind him.
    #    Archer can already shoot, so the archer does not step.
    world["terrain"] = _Grid(_open)
    world["leader"] = (11, 10)
    orders.formation_path = None
    monster = SimpleNamespace(
        track_id=7,
        species_name="orc",
        species="orc",
        guid="A",
        memory_guid="A",
        memory_ent="a",
        tile=(12, 10),
        world_cx=12,
        world_cy=10,
        position=None,
        status=None,
        bait=False,
        force_attacks_me=False,
    )
    orders.party_focus = {
        "support": "Knight",
        "species": "orc",
        "guid": "A",
        "x": 12,
        "y": 10,
        "map_id": 4,
    }
    knight = members["Knight"]
    knight.set_world_origin(SimpleNamespace(x=10, y=10))
    knight._nav_blackboard = SimpleNamespace(current_item_id=3, scratch={})
    party = _party({"Lead": (11, 10), "Knight": (10, 10), "Archer": (11, 9), "Mage": (8, 10), "Assist": (9, 10)})
    knight_state = _state("Knight", CharacterType.KNIGHT, (10, 10), party, [monster])
    knight_intent = knight.decide(knight_state)
    assert knight_intent.action is ActionType.TRAVELING, knight_intent.reason
    assert "loot" not in str(knight_intent.reason)
    assert knight.runtime.follow_hop in ((11, 11), (11, 9))
    assert knight._nav_blackboard.current_item_id is None

    archer_mob = SimpleNamespace(
        track_id=7,
        species_name="orc",
        guid="A",
        memory_guid="A",
        memory_ent="a",
        world_cx=12,
        world_cy=10,
        position=SimpleNamespace(x=0.5, y=0.5),
        status=None,
        bait=False,
        force_attacks_me=False,
    )
    archer = members["Archer"]
    archer.set_world_origin(SimpleNamespace(x=11, y=9))
    archer_state = _state("Archer", CharacterType.ELF, (11, 9), party, [archer_mob])
    archer_state.last_contested_mobs = {
        "contested": [{"attacker_name": "Lead", "guid": "A", "name": "orc", "ent": "a"}]
    }
    archer_intent = archer.decide(archer_state)
    assert archer_intent.action is not ActionType.TRAVELING

    # 4. Rear B holds the corner. A stale report lets the march go again.
    book.clear()
    book.note(sighting_message(
        who="Mage", map_id=4, species="wolf", guid="B", x=8, y=10,
        victim="Mage", victim_hp=20, can_attack=False, role="mage",
    ))
    book.note(sighting_message(
        who="Assist", map_id=4, species="wolf", guid="B", x=8, y=10,
        victim="Mage", victim_hp=20, can_attack=True, role="member",
    ))
    book.decide(mode="moving")
    clock = _Clock()
    ctl, walk = _leader_controller(clock)
    calls = {"n": 0}

    def _count():
        calls["n"] += 1
        return 4

    ctl._party_comms = SimpleNamespace(server=SimpleNamespace(client_count=_count))
    ctl._leader_turret_on = lambda: False
    leader_world = SimpleNamespace(
        party_read_ok=True,
        last_party=_party({"Lead": (1, 8), "Mage": (0, 8)}),
    )
    board = SimpleNamespace(
        world_origin=SimpleNamespace(x=1, y=8),
        nav_path=[(0, 8), (1, 8), (2, 8), (2, 9)],
        nav_waypoint=(2, 9),
        player_mode=None,
        current_target_id=7,
    )
    click = SimpleNamespace(action=ActionType.TRAVELING, reason="patrol", priority=0.5, destination=None)
    held = walk(ctl, leader_world, board, click, 4)
    assert held.action is ActionType.IDLE
    assert calls["n"] >= 1
    fresh = [body for body in ctl.logs if isinstance(body, dict) and body.get("type") == "formation_path"]
    assert fresh and fresh[-1].get("clear") is not True

    for rows in book.rows.values():
        for row in rows:
            row["_at"] = 0.0
    board.current_target_id = None
    board.nav_path = [(1, 8), (2, 8), (3, 8)]
    board.nav_waypoint = (2, 8)
    # The rear member is on the leader tile, so this one-step hop is inside
    # the arrival cap. A fresh fight report would still hold it.
    leader_world.last_party = _party({"Lead": (1, 8), "Mage": (1, 8)})
    resumed = walk(ctl, leader_world, board, click, 4)
    assert resumed.action is ActionType.TRAVELING, resumed.reason

    # A dropped seat does not keep the next hop waiting.
    board.nav_waypoint = (3, 8)
    board.nav_path = [(1, 8), (2, 8), (3, 8)]
    leader_world.last_party = {
        "in_party": True,
        "members": [
            {"name": "Lead", "is_leader": True, "map_id": 4, "x": 1, "y": 8},
            {"name": "Mage", "map_id": 9, "x": 1, "y": 8},
        ],
    }
    book.clear()
    moved = walk(ctl, leader_world, board, click, 4)
    assert moved.action is ActionType.TRAVELING

    ctl._party_march.note_hello()
    before = len([row for row in ctl.logs if isinstance(row, dict)])
    walk(ctl, leader_world, board, click, 4)
    after = [row for row in ctl.logs if isinstance(row, dict) and row.get("type") == "formation_path"]
    assert len(after) > 0
    assert len(ctl.logs) > before

    # 5. Turret: east of the dot, the next monster does not click the center.
    class _Board:
        def __init__(self):
            self.scratch = {}
            self.world_origin = SimpleNamespace(x=105, y=100)
            self.current_target_id = None
            self.current_item_id = None
            self.current_goal = None
            self.emitted = []
            self.search_hop_active = False

        def emit(self, action, **kwargs):
            self.emitted.append((action, kwargs.get("reason")))

    class _Mob:
        def __init__(self, track_id, rx):
            self.track_id = track_id
            self.world_rx = rx
            self.world_ry = 0
            self.position = SimpleNamespace(x=0.5, y=0.5)
            self.status = None

    class _Seen:
        def __init__(self, mobs):
            self.player = SimpleNamespace(character_type=CharacterType.KNIGHT)
            self.mobs = mobs

        def objects(self, kind):
            from app._03_world import ObjectType

            return list(self.mobs) if kind is ObjectType.MONSTER else []

    turret = _Board()
    set_party_turret(turret, True, map_id=4, anchor=(100, 100), engage=6, chase=8)
    step_party_turret_leash(_Seen([_Mob(2, 1)]), turret)
    assert turret.emitted == []
    assert all("100,100" not in str(reason) for _action, reason in turret.emitted)
    set_party_turret(turret, True, map_id=4, anchor=(100, 100), engage=6, chase=8)
    assert turret.current_target_id is None or turret.scratch.get("party_turret", {}).get("anchor") == (100, 100)
    book.clear()
    orders.party_focus = None


def test_rear_danger_holds_then_the_march_resumes(orders, world) -> None:
    """The leader never sees the mob. The report, the knight's click, and the hop are real."""
    from app._02_state.objects import ObjectType, Position, WorldObject
    from app._06_party.sightings import book, resolve_local, sightings_from_monsters
    from app._06_party.tests.test_make_way_pace import _Clock, _leader_controller

    def _mob(track, guid, cx, cy, *, hitting=False, latch=False, uv=(0.2, 0.3)):
        return WorldObject(
            track_id=track,
            object_type=ObjectType.MONSTER,
            species_name="orc",
            position=Position(x=uv[0], y=uv[1]),
            world_cx=cx,
            world_cy=cy,
            memory_guid=guid,
            attacking_me_now=hitting,
            attacked_me=latch,
        )

    origin = SimpleNamespace(x=8, y=10)
    crowd = [_mob(i, f"idle-{i}", 20 + i, 10) for i in range(8)]
    attacker = _mob(9, "A", 12, 10, hitting=True, uv=(0.8, 0.7))
    same = sightings_from_monsters(
        crowd + [attacker], who="Mage", map_id=4, origin=origin, role="mage", self_hp=80,
    )
    other_screen = sightings_from_monsters(
        [_mob(9, "A", 12, 10, hitting=True, uv=(0.1, 0.9))],
        who="Mage", map_id=4, origin=SimpleNamespace(x=4, y=10), role="mage", self_hp=80,
    )
    assert same["mobs"][0]["guid"] == "A"
    assert (same["mobs"][0]["x"], same["mobs"][0]["y"]) == (
        other_screen["mobs"][0]["x"], other_screen["mobs"][0]["y"],
    )
    assert "track_id" not in same["mobs"][0]
    latch = sightings_from_monsters(
        [_mob(9, "A", 12, 10, hitting=False, latch=True)],
        who="Mage", map_id=4, origin=origin, role="mage", self_hp=80,
    )
    assert latch["mobs"][0]["victim"] == ""

    book.clear()
    book.note(same)
    focus = book.decide(mode="moving")
    assert focus is not None and focus.guid == "A"
    body = book.take_message()
    assert body is not None
    _deliver(orders, body)

    members, _policy = _members(orders)
    knight = members["Knight"]
    knight.set_world_origin(SimpleNamespace(x=10, y=10))
    only_b = _mob(3, "B", 13, 10, uv=(0.6, 0.6))
    party = _party({"Lead": (11, 10), "Knight": (10, 10), "Mage": (1, 10)})
    missed = knight.decide(_state("Knight", CharacterType.KNIGHT, (10, 10), party, [only_b]))
    assert knight.runtime.assist_track_id is None
    assert resolve_local({"species": "orc", "guid": "A", "x": 12, "y": 10}, [only_b]) is None
    seen_a = _mob(9, "A", 12, 10, hitting=False, uv=(0.8, 0.7))
    book.note(sightings_from_monsters(
        [only_b, seen_a], who="Knight", map_id=4, origin=SimpleNamespace(x=10, y=10), role="member",
    ))
    named = book.decide(mode="moving")
    assert named is not None and named.support == "Knight" and named.guid == "A"
    updated = book.take_message()
    assert updated is not None
    _deliver(orders, updated)
    seen = knight.decide(_state(
        "Knight", CharacterType.KNIGHT, (10, 10), party, [only_b, seen_a],
    ))
    assert knight.runtime.assist_track_id == seen_a.track_id
    assert seen is not None

    clock = _Clock()
    ctl, walk = _leader_controller(clock)
    ctl._leader_turret_on = lambda: False
    ctl._party_profile = SimpleNamespace(assist_leash_tiles=10)
    leader_world = SimpleNamespace(
        party_read_ok=False,
        party_connected=["Mage", "Knight", "Archer"],
        last_party=_party({"Lead": (10, 10), "Mage": (1, 10), "Knight": (10, 10)}),
    )
    board = SimpleNamespace(
        world_origin=SimpleNamespace(x=10, y=10),
        nav_path=[(10, 10), (12, 10), (14, 10)],
        nav_waypoint=(12, 10),
        player_mode=None,
        current_target_id=None,
    )
    click = SimpleNamespace(action=ActionType.TRAVELING, reason="patrol", priority=0.5, destination=None)
    held = walk(ctl, leader_world, board, click, 4)
    assert held.action is ActionType.IDLE
    assert board.nav_path

    ordinary = sightings_from_monsters(
        [_mob(4, "C", 30, 10)], who="Archer", map_id=4, origin=origin, role="member",
    )
    book.note(ordinary)
    leader_world.party_connected = ["Knight", "Archer"]
    board.nav_path = [(10, 10), (11, 10)]
    board.nav_waypoint = (11, 10)
    resumed = walk(ctl, leader_world, board, click, 4)
    assert resumed.action is ActionType.TRAVELING
    assert missed.action is not None
    book.clear()
    orders.party_focus = None
