"""Moving farm: step to an attack tile, and hold the march only for a real fight."""
from types import SimpleNamespace

from app._04_decision.player_mode import ATTACK_CLICK_TILES
from app._06_party.config import PartyMemberConfig
from app._06_party.moving_fight import REPORT_FRESH_S, combat_step, march_hold_reason
from app._06_party.policy import MemberKind, PolicyInput, decide_policy
from app._06_party.sightings import (
    ASSIST_FOCUS_ID,
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


# Tile gaps follow the party settings and the attack click range.
# A default change moves this fixture with it.
_PARTY = PartyMemberConfig(leader_name="Lead")
MAP_ID = 4
LANE_Y = 10
MEMBER = (10, LANE_Y)
LEADER_CLOSE = (MEMBER[0] + 1, LANE_Y)
MONSTER_CLOSE = (MEMBER[0] + _PARTY.approach_tiles, LANE_Y)
IN_CLICK = 1
OUT_CLICK = ATTACK_CLICK_TILES + 1
# Outside the assist leash, and inside the 15–30 tile catch-up the fight uses.
_REAR_GAP = _PARTY.assist_leash_tiles + _PARTY.follow_tiles
MEMBER_REAR = (0, LANE_Y)
LEADER_AHEAD = (_REAR_GAP, LANE_Y)
MONSTER_OLD = (LEADER_AHEAD[0] + _PARTY.assist_leash_tiles, LANE_Y)
MEMBER_READY = (LEADER_AHEAD[0] + 1, LANE_Y)
MONSTER_READY = (MEMBER_READY[0] + _PARTY.approach_tiles, LANE_Y)
# Past the stop band, still inside the leash, so a cleared focus can march.
LEADER_MARCH = (
    MEMBER[0] + _PARTY.stop_tiles + _PARTY.approach_tiles + _PARTY.stop_tiles,
    LANE_Y,
)
MONSTER_OTHER = (MEMBER[0], LANE_Y + _PARTY.approach_tiles)
OTHER_GUID = "B"
TRACK_A = 7
TRACK_B = 8
STALE_GEN = 1
_PATH_STEPS = 4
_SPAN = (
    max(
        MONSTER_OLD[0],
        MEMBER[0] + (_PATH_STEPS - 1) * _PARTY.follow_tiles,
        MONSTER_OTHER[1],
    )
    + _PARTY.assist_leash_tiles
)


def _formation_tiles(start):
    step = _PARTY.follow_tiles
    return [[start[0] + i * step, start[1]] for i in range(_PATH_STEPS)]


def _fight_grid(monkeypatch):
    import sys
    import types

    sys.modules.setdefault("cv2", types.ModuleType("cv2"))

    class _Grid:
        width = _SPAN
        height = _SPAN
        has_edge_fences = False
        walkable = {(x, y) for x in range(_SPAN) for y in range(_SPAN)}

        def is_walkable(self, x, y):
            return (int(x), int(y)) in self.walkable

        def can_step(self, cx, cy, nx, ny):
            return self.is_walkable(nx, ny)

        def tile_cost(self, x, y):
            return 1

        def dist_to_wall(self, x, y):
            return 2

    monkeypatch.setattr(
        "app._04_decision.nav_config.get_terrain_map", lambda: _Grid()
    )
    monkeypatch.setattr(
        "app._03_world.merge.memory_sync.game_to_nav",
        lambda x, y: (int(x), int(y)),
    )


class _Body(SimpleNamespace):
    def __getattr__(self, name):
        return None


def _mob(cx, cy, *, guid="A", on_screen=False, rx=OUT_CLICK, status=None, track=TRACK_A):
    from app._02_state.objects import ObjectType

    return _Body(
        track_id=track,
        object_type=ObjectType.MONSTER,
        species_name="orc",
        species="orc",
        guid=guid,
        memory_guid=guid,
        memory_ent=guid.lower() or "a",
        tile=(cx, cy),
        world_cx=cx,
        world_cy=cy,
        world_rx=rx,
        world_ry=0,
        position=SimpleNamespace(x=0.5, y=0.5) if on_screen else None,
        status=status,
        bait=False,
        force_attacks_me=False,
        detail_classification="",
        level=1,
    )


def _focus(mob, support="멤버"):
    return {
        "support": support,
        "species": "orc",
        "guid": getattr(mob, "guid", "") or "",
        "x": int(mob.world_cx),
        "y": int(mob.world_cy),
        "map_id": MAP_ID,
    }


class _FightMember:
    """One member brain, a formation path, and successive decide() ticks."""

    def __init__(self, monkeypatch):
        from app._04_decision.blackboard import Blackboard
        from app._06_party.comms.orders import member_orders
        from app._06_party.manager import PartyMemberManager

        _fight_grid(monkeypatch)
        member_orders.clear()
        member_orders.session = "sess"
        member_orders.leader_run = "running"
        member_orders.need_gen = 0
        member_orders.focus_gen = 0
        member_orders.formation_path = {
            "type": "formation_path",
            "from": "leader",
            "session": "sess",
            "map_id": MAP_ID,
            "rev": 1,
            "seq": 1,
            "cursor": 0,
            "tiles": _formation_tiles(MEMBER),
            "clear": False,
        }
        self.orders = member_orders
        self.mgr = PartyMemberManager(_PARTY)
        self.mgr.apply_leader_policy(
            {
                "leader_name": "Lead",
                "leader_mode": "moving",
                "roster": [{"name": "멤버"}],
            },
            self_name="멤버",
        )
        self.mgr.set_local_map_id(MAP_ID)
        self.mgr.runtime.network_party = True
        self.mgr.runtime.orders_open = True
        self.board = Blackboard()
        self.mgr._nav_blackboard = self.board
        self._leader_view = None
        monkeypatch.setattr(
            "app._06_party.manager.resolve_leader",
            lambda *_a, **_k: self._leader_view,
        )

    def tick(self, here, leader, mobs, *, farming=True, focus="auto"):
        from app._02_state.enums import CharacterType
        from app._06_party.leader import LeaderView

        self._leader_view = LeaderView(
            name="Lead",
            tile=leader,
            map_id=MAP_ID,
            same_map=True,
            fresh=True,
            source="sync",
            farming=farming,
        )
        self.mgr.set_world_origin(SimpleNamespace(x=here[0], y=here[1]))
        self.board.world_origin = SimpleNamespace(x=here[0], y=here[1])
        if focus == "auto":
            body = mobs[0] if mobs else SimpleNamespace(guid="A", world_cx=here[0], world_cy=here[1])
            self.orders.party_focus = _focus(body)
        else:
            self.orders.party_focus = focus
        party = {
            "in_party": True,
            "members": [
                {
                    "name": "Lead",
                    "is_leader": True,
                    "map_id": MAP_ID,
                    "x": leader[0],
                    "y": leader[1],
                },
                {"name": "멤버", "map_id": MAP_ID, "x": here[0], "y": here[1]},
            ],
        }
        state = SimpleNamespace(
            player=SimpleNamespace(
                identity=SimpleNamespace(name="멤버"),
                species_name="멤버",
                character_type=CharacterType.ELF,
                hp=100,
                max_hp=100,
                hp_ratio=1.0,
                level=40,
                memory_guid="",
            ),
            last_party=party,
            last_print_state=None,
            objects=lambda *_a, **_k: list(mobs),
            monsters=lambda: list(mobs),
            get_object=lambda tid: next(
                (m for m in mobs if int(getattr(m, "track_id", 0) or 0) == int(tid)),
                None,
            ),
            party_read_ok=True,
            missing_frames=lambda _tid: 0,
        )
        intent = self.mgr.decide(state)
        return intent

    def close(self):
        self.orders.clear()


def _why(intent):
    return str(getattr(intent, "reason", "") or "")


def test_attack_approach_attack_does_not_take_a_formation_hop(monkeypatch):
    from app._02_state.enums import ActionType

    brain = _FightMember(monkeypatch)
    seen = _mob(*MONSTER_CLOSE, on_screen=True, rx=IN_CLICK)
    hidden = _mob(*MONSTER_CLOSE, on_screen=False)
    first = brain.tick(MEMBER, LEADER_CLOSE, [seen])
    second = brain.tick(MEMBER, LEADER_CLOSE, [hidden])
    third = brain.tick(MEMBER, LEADER_CLOSE, [seen])
    assert first.action is ActionType.ATTACK, _why(first)
    assert second.action is ActionType.TRAVELING, _why(second)
    assert "combat_approach" in _why(second)
    assert "march" not in _why(second)
    assert third.action is ActionType.ATTACK, _why(third)
    brain.close()


def test_a_missing_approach_hop_does_not_march_and_retries(monkeypatch):
    from app._02_state.enums import ActionType
    import app._06_party.intents as intents

    brain = _FightMember(monkeypatch)
    real = intents.plan_slot_hop
    calls = {"n": 0}

    def _once(*args, **kwargs):
        if kwargs.get("kind") == "combat_approach" and calls["n"] == 0:
            calls["n"] = 1
            raise RuntimeError("no hop")
        return real(*args, **kwargs)

    monkeypatch.setattr(intents, "plan_slot_hop", _once)
    hidden = _mob(*MONSTER_CLOSE, on_screen=False)
    missed = brain.tick(MEMBER, LEADER_CLOSE, [hidden])
    retried = brain.tick(MEMBER, LEADER_CLOSE, [hidden])
    assert missed.action is not ActionType.TRAVELING, _why(missed)
    assert "march" not in _why(missed)
    assert "combat_approach" in _why(missed)
    assert retried.action is ActionType.TRAVELING, _why(retried)
    assert "combat_approach" in _why(retried)
    assert "march" not in _why(retried)
    brain.close()


def test_a_member_behind_catches_the_leader_before_the_monster(monkeypatch):
    from app._02_state.enums import ActionType

    brain = _FightMember(monkeypatch)
    far_mob = _mob(*MONSTER_OLD, on_screen=False, rx=MONSTER_OLD[0])
    catching = brain.tick(MEMBER_REAR, LEADER_AHEAD, [far_mob])
    assert catching.action is ActionType.TRAVELING, _why(catching)
    assert "march" not in _why(catching)
    hop = brain.mgr.runtime.follow_hop
    assert hop is not None and MEMBER_REAR[0] < hop[0] < LEADER_AHEAD[0], hop
    beside = brain.tick(MEMBER_READY, LEADER_AHEAD, [_mob(*MONSTER_READY, on_screen=False)])
    assert "combat_approach" in _why(beside) or beside.action is ActionType.ATTACK
    assert "march" not in _why(beside)
    shot = brain.tick(MEMBER_READY, LEADER_AHEAD, [_mob(*MONSTER_READY, on_screen=True, rx=IN_CLICK)])
    assert shot.action is ActionType.ATTACK, _why(shot)
    brain.close()


def test_a_missed_or_ambiguous_sighting_does_not_attack_blind(monkeypatch):
    from app._02_state.enums import ActionType

    brain = _FightMember(monkeypatch)
    seen = _mob(*MONSTER_CLOSE, on_screen=True, rx=IN_CLICK)
    assert brain.tick(MEMBER, LEADER_CLOSE, [seen]).action is ActionType.ATTACK
    missed = brain.tick(MEMBER, LEADER_CLOSE, [])
    assert missed.action is not ActionType.ATTACK, _why(missed)
    assert "march" not in _why(missed)
    pair = [
        _mob(*MONSTER_CLOSE, guid="", on_screen=True, rx=IN_CLICK, track=TRACK_A),
        _mob(MONSTER_CLOSE[0], LANE_Y + 1, guid="", on_screen=True, rx=IN_CLICK, track=TRACK_B),
    ]
    ambiguous = brain.tick(MEMBER, LEADER_CLOSE, pair, focus=_focus(pair[0]))
    assert ambiguous.action is not ActionType.ATTACK, _why(ambiguous)
    again = brain.tick(MEMBER, LEADER_CLOSE, [seen])
    assert again.action is ActionType.ATTACK, _why(again)
    brain.close()


def test_focus_end_releases_the_approach_and_march_can_resume(monkeypatch):
    from app._02_state.enums import ActionType
    from app._02_state.objects import ObjectStatus

    brain = _FightMember(monkeypatch)
    hidden = _mob(*MONSTER_CLOSE, on_screen=False)
    stepped = brain.tick(MEMBER, LEADER_MARCH, [hidden])
    assert "combat_approach" in _why(stepped), _why(stepped)
    cleared = brain.tick(MEMBER, LEADER_MARCH, [hidden], focus={"clear": True})
    assert "combat_approach" not in _why(cleared)
    assert "march" in _why(cleared)
    assert cleared.action is ActionType.TRAVELING

    other = _mob(*MONSTER_OTHER, guid=OTHER_GUID, on_screen=False)
    changed = brain.tick(MEMBER, LEADER_CLOSE, [other])
    assert "combat_approach" in _why(changed) or changed.action is ActionType.ATTACK
    assert brain.mgr.runtime.scratch.get(ASSIST_FOCUS_ID, ("",))[0] == OTHER_GUID

    dead = _mob(*MONSTER_CLOSE, on_screen=False, status=ObjectStatus.DEAD)
    released = brain.tick(MEMBER, LEADER_MARCH, [dead])
    assert "combat_approach" not in _why(released)
    assert "march" in _why(released)

    brain.orders.need_gen = STALE_GEN
    brain.orders.path_gen = STALE_GEN
    brain.orders.focus_gen = 0
    expired = brain.tick(MEMBER, LEADER_MARCH, [hidden])
    assert "combat_approach" not in _why(expired)
    assert "march" in _why(expired)
    brain.close()


def test_heal_and_retreat_win_over_the_approach(monkeypatch):
    from app._02_state.enums import ActionType
    from app._04_decision.types import ActionIntent

    brain = _FightMember(monkeypatch)
    hidden = _mob(*MONSTER_CLOSE, on_screen=False)

    def _heal(*_a, **_k):
        return ActionIntent(action=ActionType.HEAL, reason="self heal")

    monkeypatch.setattr("app._06_party.manager.apply_party_support", _heal)
    healed = brain.tick(MEMBER, LEADER_CLOSE, [hidden])
    assert healed.action is ActionType.HEAL, _why(healed)
    assert "march" not in _why(healed)
    assert "combat_approach" not in _why(healed)

    def _retreat(*_a, **_k):
        return ActionIntent(action=ActionType.TRAVELING, reason="critical retreat")

    monkeypatch.setattr("app._06_party.support.party_critical_escape", _retreat)
    monkeypatch.setattr(
        "app._06_party.manager.apply_party_support", lambda *_a, **_k: None
    )
    left = brain.tick(MEMBER, LEADER_CLOSE, [hidden])
    assert "critical retreat" in _why(left)
    assert "combat_approach" not in _why(left)
    assert "march" not in _why(left)
    brain.close()
