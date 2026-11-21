"""Moving farm: step to an attack tile, and hold the march only for a real fight."""
from types import SimpleNamespace

from app._06_party.config import PartyMemberConfig
from app._06_party.moving_fight import REPORT_FRESH_S, combat_step, march_hold_reason
from app._06_party.policy import MemberKind, PolicyInput, decide_policy
from app._06_party.sightings import (
    choose_focus,
    client_action,
    sighting_message,
    sightings_from_monsters,
)


def _policy(**kwargs):
    base = dict(
        paused=False,
        dead=False,
        origin_ok=True,
        leader_present=True,
        leader_dist=1,
        chasing=False,
        need_potion=False,
        self_threat=False,
        assist_ready=True,
        config=PartyMemberConfig(stop_tiles=2, approach_tiles=2),
        leader_walk_dist=1,
        leader_farming=True,
        need_combat_step=True,
    )
    base.update(kwargs)
    return PolicyInput(**base)


def test_one_tile_beside_the_leader_is_an_attack_step_not_a_hold():
    kind, tile = combat_step(
        (10, 10),
        (12, 10),
        can_hit=False,
        approach_tiles=2,
        support_from=(11, 10),
        support_tiles=10,
        blocked=((11, 10),),
    )
    assert kind == "approach" and tile in ((11, 11), (11, 9))
    assert max(abs(tile[0] - 12), abs(tile[1] - 10)) == 1
    stepped = decide_policy(_policy(combat_approach=True))
    assert stepped.kind is MemberKind.FOLLOW
    assert stepped.reason.startswith("combat_approach")
    held = decide_policy(_policy(combat_approach=False))
    assert held.kind is MemberKind.HOLD
    shooting = decide_policy(_policy(need_combat_step=False, combat_approach=False))
    assert shooting.kind is MemberKind.ASSIST
    healing = decide_policy(_policy(need_heal=True, combat_approach=True))
    assert healing.kind is MemberKind.HEAL


def test_a_long_wall_path_rejoins_and_a_shot_does_not_step():
    def _long(_me, _stand):
        return [(0, i) for i in range(12)]

    assert combat_step(
        (10, 10),
        (12, 10),
        can_hit=False,
        approach_tiles=2,
        support_from=(11, 10),
        support_tiles=10,
        path_for=_long,
    ) == ("rejoin", None)
    assert combat_step(
        (10, 10),
        (14, 10),
        can_hit=True,
        approach_tiles=2,
        support_from=(11, 10),
        support_tiles=10,
    ) == ("attack", (10, 10))


def test_rear_threat_holds_the_corner_and_a_miss_does_not_clear_it():
    guide = [(0, 0), (1, 0), (2, 0), (2, 1)]
    held = march_hold_reason(
        leader_fighting=False,
        rear_hot=True,
        report_age=0.4,
        here=(1, 0),
        hop=(2, 1),
        guide=guide,
    )
    assert held == "rear"
    assert march_hold_reason(
        leader_fighting=False,
        rear_hot=True,
        report_age=0.4,
        here=(0, 0),
        hop=(2, 0),
        guide=guide,
    ) == "rear"
    assert march_hold_reason(
        leader_fighting=True,
        rear_hot=False,
        report_age=None,
        here=(1, 0),
        hop=(2, 0),
        guide=guide,
    ) == "fight"
    assert march_hold_reason(
        leader_fighting=False,
        rear_hot=True,
        report_age=REPORT_FRESH_S + 1,
        here=(1, 0),
        hop=(2, 1),
        guide=guide,
    ) == ""
    assert march_hold_reason(
        leader_fighting=False,
        rear_hot=True,
        report_age=0.4,
        disconnected=True,
        here=(1, 0),
        hop=(2, 1),
        guide=guide,
    ) == ""
    assert march_hold_reason(
        leader_fighting=False,
        rear_hot=True,
        report_age=0.4,
        other_map=True,
        here=(1, 0),
        hop=(2, 1),
        guide=guide,
    ) == ""
    assert march_hold_reason(
        leader_fighting=False,
        rear_hot=False,
        report_age=0.4,
        here=(1, 0),
        hop=(2, 1),
        guide=guide,
    ) == ""


def test_a_monster_behind_the_march_does_not_stop_the_party():
    origin = SimpleNamespace(x=10, y=10)

    class _Seen:
        species_name = "wolf"
        world_cx = 8
        world_cy = 10
        guid = "C"

    body = sightings_from_monsters(
        [_Seen()], who="Archer", map_id=4, origin=origin, heading=(1, 0)
    )
    assert body["mobs"][0]["detour"] is True
    focus = choose_focus(body["mobs"], mode="moving")
    assert focus is None
    assert march_hold_reason(
        leader_fighting=False, rear_hot=False, report_age=None
    ) == ""


def test_the_rear_knight_supports_b_and_the_leader_does_not_click_it():
    rows = [
        sighting_message(
            who="Leader", map_id=4, species="orc", guid="A", x=12, y=10,
            engaged=True, can_attack=True, role="leader",
        ),
        sighting_message(
            who="Archer", map_id=4, species="orc", guid="A", x=12, y=10,
            can_attack=True, role="member",
        ),
        sighting_message(
            who="Knight", map_id=4, species="wolf", guid="B", x=8, y=10,
            victim="Mage", victim_hp=20, can_attack=True, role="member",
        ),
        sighting_message(
            who="Mage", map_id=4, species="wolf", guid="B", x=8, y=10,
            victim="Mage", victim_hp=20, can_attack=False, role="mage",
        ),
    ]
    focus = choose_focus(
        rows,
        mode="moving",
        current={"map_id": 4, "species": "orc", "guid": "A", "x": 12, "y": 10, "role": "leader"},
    )
    assert focus is not None
    assert focus.support == "Knight"
    assert focus.leader_guid == "A"
    assert focus.hold_advance is True
    heal, _mob = client_action(
        role="mage", name="Mage", focus=focus, local=[], attacked=True
    )
    assert heal == "heal"
    kind, mob = client_action(
        role="leader",
        name="Leader",
        focus=focus,
        local=[SimpleNamespace(species="orc", tile=(12, 10), guid="A")],
        attacked=False,
    )
    assert kind == "attack" and mob.guid == "A"
