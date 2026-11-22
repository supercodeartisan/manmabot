"""Rear-monster reports: the tile, the guid, the cap, the hold, the walk."""
from __future__ import annotations

from types import SimpleNamespace

from app._02_state.enums import ActionType
from app._02_state.objects import ObjectType, Position, WorldObject
from app._06_party.moving_fight import combat_step
from app._06_party.sightings import book, resolve_local, sightings_from_monsters


def _mob(track, guid, cx, cy, *, hitting=False, latch=False, finish=False, uv=(0.5, 0.5)):
    return WorldObject(
        track_id=track,
        object_type=ObjectType.MONSTER,
        species_name="orc",
        position=Position(x=uv[0], y=uv[1]),
        world_cx=cx,
        world_cy=cy,
        memory_guid=guid or None,
        attacking_me_now=hitting,
        attacked_me=latch,
        finish_kill_until_dead=finish,
    )


def test_memory_guid_picks_one_body_and_the_tile_is_absolute():
    origin = SimpleNamespace(x=10, y=10)
    a = _mob(1, "A", 40, 50, uv=(0.5, 0.5))
    b = _mob(2, "B", 41, 50, uv=(0.1, 0.2))
    spec = {"species": "orc", "guid": "A", "x": 40, "y": 50}
    assert resolve_local(spec, [b]) is None
    found = resolve_local(spec, [a, b])
    assert found is a
    left = sightings_from_monsters([a], who="Knight", map_id=4, origin=origin)
    right = sightings_from_monsters(
        [_mob(9, "A", 40, 50, uv=(0.9, 0.1))],
        who="Mage", map_id=4, origin=SimpleNamespace(x=1, y=1),
    )
    assert (left["mobs"][0]["x"], left["mobs"][0]["y"]) == (
        right["mobs"][0]["x"], right["mobs"][0]["y"],
    )
    bare = WorldObject(
        track_id=3,
        object_type=ObjectType.MONSTER,
        species_name="orc",
        position=Position(x=0.5, y=0.5),
    )
    assert sightings_from_monsters([bare], who="Knight", map_id=4, origin=None)["mobs"] == []


def test_the_ninth_attacker_is_reported_and_a_latch_is_not_a_new_hit():
    origin = SimpleNamespace(x=8, y=10)
    crowd = [_mob(i, f"n{i}", 20 + i, 10) for i in range(8)]
    hitting = _mob(99, "A", 12, 10, hitting=True)
    body = sightings_from_monsters(
        crowd + [hitting], who="Mage", map_id=4, origin=origin, role="mage", self_hp=55,
    )
    assert body["mobs"][0]["guid"] == "A"
    assert body["mobs"][0]["victim"] == "Mage"
    later = sightings_from_monsters(
        [_mob(99, "A", 12, 10, hitting=False, latch=True)],
        who="Mage", map_id=4, origin=origin, role="mage", self_hp=55,
    )
    assert later["mobs"][0]["victim"] == ""
    assert later["mobs"][0]["engaged"] is False


def test_one_reporter_expiring_does_not_keep_the_danger(monkeypatch):
    from app._06_party.tests.test_make_way_pace import _Clock, _leader_controller

    book.clear()
    book.note({
        "type": "sighting",
        "from": "Mage",
        "map_id": 4,
        "seq": 2,
        "mobs": [{
            "species": "orc", "guid": "A", "x": 12, "y": 10,
            "victim": "Mage", "victim_hp": 80, "engaged": True, "role": "mage",
        }],
    })
    book.note({
        "type": "sighting",
        "from": "Mage",
        "map_id": 4,
        "seq": 1,
        "mobs": [{
            "species": "orc", "guid": "A", "x": 12, "y": 10,
            "victim": "", "engaged": False, "role": "mage",
        }],
    })
    assert book.rows["mage"][0]["victim"] == "Mage"
    for row in book.rows["mage"]:
        row["_at"] = 0.0
    book.note({
        "type": "sighting",
        "from": "Archer",
        "map_id": 4,
        "mobs": [{
            "species": "orc", "guid": "C", "x": 30, "y": 10,
            "victim": "", "engaged": False, "role": "member",
        }],
    })
    clock = _Clock()
    ctl, walk = _leader_controller(clock)
    ctl._leader_turret_on = lambda: False
    ctl._party_profile = SimpleNamespace(assist_leash_tiles=10)
    world = SimpleNamespace(
        party_read_ok=False,
        party_connected=["Mage", "Archer"],
        last_party={"members": [
            {"name": "Mage", "x": 1, "y": 10},
            {"name": "Archer", "x": 10, "y": 10},
        ]},
    )
    board = SimpleNamespace(
        world_origin=SimpleNamespace(x=10, y=10),
        nav_path=[(10, 10), (11, 10)],
        nav_waypoint=(11, 10),
        player_mode=None,
        current_target_id=None,
    )
    click = SimpleNamespace(action=ActionType.TRAVELING, reason="patrol", priority=0.5, destination=None)
    resumed = walk(ctl, world, board, click, 4)
    assert resumed.action is ActionType.TRAVELING
    assert board.nav_path == [(10, 10), (11, 10)]
    book.clear()


def test_support_hold_uses_the_hop_and_a_plain_sighting_does_not(monkeypatch):
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
    ctl._party_profile = SimpleNamespace(assist_leash_tiles=10)
    world = SimpleNamespace(
        party_read_ok=False,
        last_party={"members": [{"name": "Knight", "x": 1, "y": 10}]},
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
    book.rows["knight"][0]["engaged"] = False
    book.rows["knight"][0]["_at"] = book.rows["knight"][0]["_at"]
    plain = walk(ctl, world, board, click, 4)
    assert plain.action is ActionType.TRAVELING
    book.clear()


def test_approach_follows_the_real_path():
    me = (10, 10)
    monster = (12, 10)

    def _one(_me, stand):
        if stand == (11, 10):
            return [_me, stand]
        return None

    kind, tile = combat_step(
        me, monster, can_hit=False, approach_tiles=2,
        support_from=(10, 10), support_tiles=10, path_for=_one,
    )
    assert kind == "approach" and tile == (11, 10)

    def _wall(_me, stand):
        return [_me, (10, 11), (11, 11), stand]

    assert combat_step(
        me, monster, can_hit=False, approach_tiles=2,
        support_from=(10, 10), support_tiles=10, path_for=_wall,
    ) == ("rejoin", None)
    assert combat_step(
        me, monster, can_hit=False, approach_tiles=2,
        support_from=(10, 10), support_tiles=10, path_for=lambda *_a: None,
    ) == ("rejoin", None)

    def _bulge(_me, stand):
        return [_me, (10, 30), stand]

    assert combat_step(
        me, monster, can_hit=False, approach_tiles=4,
        support_from=(10, 10), support_tiles=10, path_for=_bulge,
    ) == ("rejoin", None)


def test_turret_return_waits_on_the_body(monkeypatch):
    from app._04_decision.behaviors.party_turret import _walk_to

    class _Board:
        def __init__(self, x, y):
            self.scratch = {}
            self.world_origin = SimpleNamespace(x=x, y=y)
            self.current_goal = None
            self.emitted = []

        def emit(self, action, **kwargs):
            self.emitted.append((action, kwargs.get("reason"), kwargs.get("destination")))

    def _plan(_terrain, origin, _goal, **_kwargs):
        hop = (int(origin.x) + 1, int(origin.y))
        return ("click", [hop], hop)

    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: object())
    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _plan)
    board = _Board(0, 10)
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.TRAVELING
    board.emitted.clear()
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.IDLE
    board.world_origin = SimpleNamespace(x=1, y=10)
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.TRAVELING
    board.emitted.clear()
    board.world_origin = SimpleNamespace(x=1, y=10)
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.IDLE
    board.scratch["party_turret_stuck_at"] = 0.0
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.TRAVELING
    board.world_origin = SimpleNamespace(x=5, y=10)
    board.emitted.clear()
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][1] == "party turret arrived"

    def _fail(*_a, **_k):
        return None, None, None

    monkeypatch.setattr("app._04_decision.pathfinding.plan_travel_click", _fail)
    board.world_origin = SimpleNamespace(x=0, y=10)
    board.scratch.clear()
    board.emitted.clear()
    _walk_to(board, (5, 10), "return")
    assert board.emitted[-1][0] is ActionType.IDLE
    assert board.emitted[-1][2] is None
