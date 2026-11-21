"""Reconnect seq, map isolation, the profile leash, and a turret hop."""
from __future__ import annotations

from types import SimpleNamespace

from app._02_state.enums import ActionType
from app._06_party.sightings import book


class _Frame:
    def __init__(self, message, peer):
        self.message = message
        self.peer = peer
        self.sender = message.get("from")


class _Server:
    def __init__(self):
        self.frames = []
        self.dropped = []

    def take_dropped(self):
        out = list(self.dropped)
        self.dropped.clear()
        return out

    def drain(self):
        out = list(self.frames)
        self.frames.clear()
        return out

    def client_count(self):
        return 1


def _hello(name, client_id):
    return {
        "type": "member_hello",
        "from": name,
        "client_id": client_id,
        "character": {"name": name, "class": "MAGE", "level": 1},
    }


def _sight(name, client_id, seq, *, victim="", hp=None, map_id=4):
    row = {
        "species": "orc",
        "guid": "A",
        "x": 12,
        "y": 10,
        "victim": victim,
        "engaged": bool(victim),
        "role": "mage",
    }
    if hp is not None:
        row["victim_hp"] = hp
    return {
        "type": "sighting",
        "from": name,
        "client_id": client_id,
        "map_id": map_id,
        "seq": seq,
        "mobs": [row],
    }


def test_a_new_hello_accepts_seq_one_and_an_old_socket_cannot_erase_it():
    from app._06_party.comms.ingest import drain_leader_reports
    from app._06_party.sync import member_states

    book.clear()
    member_states.clear()
    server = _Server()
    server.frames = [
        _Frame(_sight("법사", "old", 90, victim="법사", hp=20), "peer-old"),
    ]
    drain_leader_reports(server=server)
    assert book.rows["법사"][0]["victim"] == "법사"

    server.frames = [_Frame(_hello("법사", "new"), "peer-new")]
    drain_leader_reports(server=server)
    server.frames = [
        _Frame(_sight("법사", "new", 1, victim="법사", hp=30), "peer-new"),
    ]
    drain_leader_reports(server=server)
    assert book.rows["법사"][0]["victim_hp"] == 30

    server.frames = [
        _Frame(_sight("법사", "old", 91, victim="", hp=100), "peer-old"),
    ]
    drain_leader_reports(server=server)
    assert book.rows["법사"][0]["victim_hp"] == 30

    server.dropped = ["peer-old"]
    drain_leader_reports(server=server)
    assert book.rows["법사"][0]["victim_hp"] == 30

    server.dropped = ["peer-new"]
    drain_leader_reports(server=server)
    assert "법사" not in book.rows
    book.clear()
    member_states.clear()


def test_another_maps_danger_does_not_regroup_this_map():
    book.clear()
    book.note({
        "type": "sighting",
        "from": "법사",
        "map_id": 4,
        "mobs": [{
            "species": "orc", "guid": "A", "x": 1, "y": 1,
            "victim": "법사", "victim_hp": 20, "role": "mage",
        }],
    })
    book.note({
        "type": "sighting",
        "from": "기사",
        "map_id": 5,
        "mobs": [{
            "species": "slime", "guid": "C", "x": 8, "y": 8,
            "victim": "", "engaged": False, "role": "member",
        }],
    })
    here = book.decide(mode="turret", map_id=5)
    assert here is not None and here.map_id == 5 and here.regroup is False
    book.decide(mode="turret", map_id=0)
    assert book.order is None or int(book.order.map_id) == 0
    zero = book.note({
        "type": "sighting",
        "from": "궁수",
        "map_id": 0,
        "mobs": [{
            "species": "wolf", "guid": "Z", "x": 2, "y": 2,
            "victim": "궁수", "victim_hp": 20, "role": "member",
        }],
    })
    del zero
    on_zero = book.decide(mode="turret", map_id=0)
    assert on_zero is not None and on_zero.map_id == 0 and on_zero.regroup is True
    left = book.decide(mode="turret", map_id=5)
    assert left is None or (left.map_id == 5 and left.regroup is False)
    book.clear()


def test_profile_leash_holds_the_hop_that_leaves_support():
    from app._06_party.tests.test_make_way_pace import _Clock, _leader_controller

    book.clear()
    book.note({
        "type": "sighting",
        "from": "Knight",
        "map_id": 4,
        "mobs": [{
            "species": "orc", "guid": "A", "x": 12, "y": 10,
            "victim": "", "engaged": True, "role": "member", "who": "Knight",
        }],
    })
    clock = _Clock()
    ctl, walk = _leader_controller(clock)
    ctl._leader_turret_on = lambda: False
    ctl._profile = SimpleNamespace(party_assist_leash_tiles=7)
    world = SimpleNamespace(
        party_read_ok=False,
        last_party={"members": [{"name": "Knight", "x": 4, "y": 10}]},
    )
    board = SimpleNamespace(
        world_origin=SimpleNamespace(x=10, y=10),
        nav_path=[(10, 10), (12, 10)],
        nav_waypoint=(12, 10),
        player_mode=None,
        current_target_id=None,
    )
    click = SimpleNamespace(action=ActionType.TRAVELING, reason="patrol", priority=0.5, destination=None)
    held = walk(ctl, world, board, click, 4)
    assert held.action is ActionType.IDLE
    book.clear()


def test_turret_return_clicks_only_after_the_terrain_loads(monkeypatch):
    from app._04_decision.behaviors.party_turret import _walk_to

    class _Board:
        def __init__(self):
            self.scratch = {}
            self.world_origin = SimpleNamespace(x=0, y=10)
            self.current_goal = None
            self.emitted = []

        def emit(self, action, **kwargs):
            self.emitted.append((action, kwargs.get("destination")))

    loaded = {"on": False}

    monkeypatch.setattr(
        "app._04_decision.nav_config.get_terrain_map",
        lambda: object() if loaded["on"] else None,
    )

    def _plan(_terrain, origin, _goal):
        hop = (int(origin.x) + 1, int(origin.y))
        return ("click", [hop], hop)

    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _plan)
    board = _Board()
    _walk_to(board, (5, 10), "return")
    assert all(action is not ActionType.TRAVELING for action, _dest in board.emitted)
    loaded["on"] = True
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.TRAVELING
    assert sum(1 for action, _dest in board.emitted if action is ActionType.TRAVELING) == 1
    board.emitted.clear()
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.IDLE
