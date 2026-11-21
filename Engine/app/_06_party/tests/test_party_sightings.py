"""Member-only sightings become one shared order. Clicks stay local."""
from __future__ import annotations

from app._06_party.comms.ingest import drain_leader_reports, ingest_member_orders
from app._06_party.comms.orders import member_orders
from app._06_party.frame_check import reject_leader_frame, reject_member_frame
from app._06_party.sightings import (
    book,
    choose_focus,
    client_action,
    focus_message,
    resolve_local,
    sighting_message,
    sightings_from_monsters,
)


class _Mob:
    def __init__(self, species, x, y, guid="", track_id=0):
        self.species = species
        self.tile = (x, y)
        self.guid = guid
        self.track_id = track_id


class _Frame:
    def __init__(self, message):
        self.message = message
        self.peer = "p1"


class _Server:
    def __init__(self, frames):
        self._frames = frames

    def client_count(self):
        return 2

    def take_dropped(self):
        return []

    def drain(self):
        return list(self._frames)


class _Client:
    def __init__(self, frames):
        self._frames = frames

    def drain(self):
        return list(self._frames)


def _scene(victim_hp):
    """Leader sees A. Archer sees A and B. Mage sees B, and B is hitting the mage."""
    current = {"map_id": 4, "species": "orc", "guid": "A", "x": 10, "y": 10, "role": "leader"}
    rows = [
        sighting_message(
            who="Archer", map_id=4, species="orc", guid="A", x=10, y=10,
            can_attack=True, role="member",
        ),
        sighting_message(
            who="Archer", map_id=4, species="wolf", guid="B", x=8, y=12,
            victim="Mage", victim_hp=victim_hp, can_attack=True, role="member",
        ),
        sighting_message(
            who="Mage", map_id=4, species="wolf", guid="B", x=8, y=12,
            victim="Mage", victim_hp=victim_hp, can_attack=False, role="mage",
        ),
    ]
    return current, rows


def test_split_sight_archer_supports_and_leader_does_not_click_unseen():
    book.clear()
    current, rows = _scene(30)
    focus = choose_focus(rows, mode="moving", current=current)
    assert focus is not None
    assert focus.species == "wolf" and focus.guid == "B"
    assert focus.support == "Archer"
    assert focus.leader_guid == "A"
    assert focus.hold_advance is True
    assert focus.regroup is False
    assert "track_id" not in sighting_message(
        who="Archer", map_id=4, species="wolf", x=8, y=12
    )

    leader_screen = [_Mob("orc", 10, 10, "A", track_id=1)]
    archer_screen = [_Mob("orc", 10, 10, "A", 2), _Mob("wolf", 8, 12, "B", 9)]
    mage_screen = [_Mob("wolf", 8, 12, "B", 3)]

    assert client_action(
        role="mage", name="Mage", focus=focus, local=mage_screen, attacked=True
    )[0] == "heal"
    kind, mob = client_action(
        role="member", name="Archer", focus=focus, local=archer_screen, attacked=False
    )
    assert kind == "attack" and mob.guid == "B"
    assert resolve_local(
        {"species": "wolf", "guid": "B", "x": 8, "y": 12, "map_id": 4},
        leader_screen,
    ) is None
    kind, mob = client_action(
        role="leader", name="Leader", focus=focus, local=leader_screen, attacked=False
    )
    assert kind == "attack" and mob.guid == "A"

    stable = choose_focus(_scene(90)[1], mode="moving", current=current)
    assert stable is not None and stable.hold_advance is False and stable.leader_guid == "A"
    stake = choose_focus(rows, mode="turret", current=current)
    assert stake is not None and stake.hold_advance is False and stake.regroup is True


def test_sighting_and_focus_use_the_real_frames():
    book.clear()
    member_orders._drop_orders()
    _current, rows = _scene(30)
    archer = rows[1]
    assert reject_member_frame(archer) == ""
    drain_leader_reports(server=_Server([_Frame(archer)]))
    focus = book.decide(mode="moving", current=_scene(30)[0])
    body = focus_message(focus)
    body["session"] = "sess"
    assert reject_leader_frame(body) == ""
    ingest_member_orders(_Client([_Frame(body)]))
    stored = member_orders.party_focus
    assert stored is not None and stored["guid"] == "B" and stored["support"] == "Archer"
    assert "track_id" not in stored
    book.clear()
    member_orders._drop_orders()


def test_same_species_overlap_is_not_clicked_and_a_fresh_mob_does_not_steal():
    a = _Mob("wolf", 5, 5)
    b = _Mob("wolf", 6, 5)
    assert resolve_local({"species": "wolf", "x": 5, "y": 5}, [a, b]) is None
    engaged = sighting_message(
        who="Knight", map_id=4, species="orc", guid="A", x=10, y=10,
        engaged=True, can_attack=True,
    )
    fresh = sighting_message(
        who="Archer", map_id=4, species="wolf", guid="C", x=9, y=10, detour=False,
    )
    behind = sighting_message(
        who="Mage", map_id=4, species="slime", guid="D", x=1, y=1, detour=True,
    )
    focus = choose_focus([engaged, fresh, behind], mode="moving")
    assert focus is not None and focus.guid == "A"
    again = choose_focus(
        [fresh, engaged],
        mode="moving",
        current={"map_id": 4, "species": "orc", "guid": "A", "x": 10, "y": 10},
    )
    assert again is not None and again.guid == "A"


def test_screen_report_uses_world_tile_and_drops_the_local_track_id():
    class _Seen:
        species_name = "wolf"
        world_cx = 8
        world_cy = 12
        memory_guid = "B"
        track_id = 44
        attacked_me = True
        attacking_me_now = True

    origin = type("P", (), {"x": 8, "y": 12})()
    body = sightings_from_monsters(
        [_Seen()], who="Mage", map_id=4, origin=origin, role="mage", self_hp=30
    )
    assert reject_member_frame(body) == ""
    assert body["mobs"][0]["victim"] == "Mage"
    assert body["mobs"][0]["guid"] == "B"
    assert "track_id" not in body["mobs"][0]
    book.clear()
    book.note(body)
    focus = book.decide(mode="moving")
    assert focus is not None and focus.guid == "B" and focus.hold_advance is True
    book.clear()
