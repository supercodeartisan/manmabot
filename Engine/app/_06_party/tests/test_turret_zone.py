"""Fixed turret dot: the next fight starts where the last one ended."""
from types import SimpleNamespace

from app._03_world import ActionType
from app._04_decision.behaviors.party_turret import (
    pick_attack_stand,
    set_party_turret,
    step_party_turret_idle,
    step_party_turret_leash,
    zone_pair,
)
from app._06_party.assist import turret_member_focus
from app._06_party.farm_yard import (
    hunt_center,
    keep_current_target,
    member_zone_center,
    target_band,
)
from app._06_party.sightings import choose_focus, client_action, sighting_message


def test_neighbor_after_an_east_kill_stays_in_place() -> None:
    anchor = (10, 10)
    knight = (15, 10)
    archer = (14, 11)
    mage = (13, 10)
    monster = (16, 10)
    assert hunt_center(knight, 10, 10) == anchor
    assert target_band(monster, knight, anchor, engaged=False, can_hit=True) == "now"
    assert target_band(monster, archer, anchor, engaged=False, can_hit=True) == "now"
    assert max(abs(mage[0] - knight[0]), abs(mage[1] - knight[1])) <= 8
    assert max(abs(mage[0] - archer[0]), abs(mage[1] - archer[1])) <= 8
    assert keep_current_target("now", "step") is True

    class _Board:
        def __init__(self) -> None:
            self.scratch: dict = {}
            self.world_origin = SimpleNamespace(x=knight[0], y=knight[1])
            self.current_goal = None
            self.emitted: list = []
            self.search_hop_active = True

        def emit(self, action, **kwargs) -> None:
            self.emitted.append((action, kwargs.get("reason")))

    board = _Board()
    set_party_turret(board, True, map_id=4, anchor=anchor)
    step_party_turret_idle(object(), board, now=10.0)  # type: ignore[arg-type]
    assert board.emitted == [(ActionType.IDLE, "party turret wait on anchor")]


def test_edge_fight_continues_and_a_wall_detour_is_dropped() -> None:
    anchor = (0, 0)
    assert target_band((7, 0), (6, 0), anchor, engaged=True, can_hit=True) == "now"
    assert target_band((10, 0), (0, 0), anchor, engaged=True, can_hit=False) == "skip"
    assert target_band((4, 0), (0, 0), anchor, engaged=False, can_hit=False, path_tiles=12) == "leave"


def test_empty_zone_looks_inside_before_the_dot() -> None:
    class _Board:
        def __init__(self) -> None:
            self.scratch: dict = {}
            self.world_origin = SimpleNamespace(x=15, y=10)
            self.current_goal = None
            self.emitted: list = []
            self.search_hop_active = False

        def emit(self, action, **kwargs) -> None:
            self.emitted.append((action, kwargs.get("reason")))

    board = _Board()
    set_party_turret(board, True, map_id=4, anchor=(10, 10))
    step_party_turret_idle(object(), board, now=0.0)  # type: ignore[arg-type]
    step_party_turret_idle(object(), board, now=3.0)  # type: ignore[arg-type]
    assert board.emitted[-1][0] is ActionType.TRAVELING
    assert str(board.emitted[-1][1]).endswith("14,10")
    board.scratch["party_turret_look_i"] = 0
    board.scratch["party_turret_look_at"] = 0.0
    step_party_turret_idle(object(), board, now=3.0)  # type: ignore[arg-type]
    assert sum(1 for action, _why in board.emitted if action is ActionType.TRAVELING) == 1


class _Mob:
    def __init__(self, track_id: int, rx: int, ry: int = 0) -> None:
        self.track_id = track_id
        self.world_rx = rx
        self.world_ry = ry
        self.position = SimpleNamespace(x=0.5, y=0.5)
        self.status = None


class _State:
    def __init__(self, mobs, kind: str = "knight") -> None:
        from app._02_state.enums import CharacterType

        self.player = SimpleNamespace(
            character_type=CharacterType.ELF if kind == "elf" else CharacterType.KNIGHT
        )
        self.mobs = mobs

    def objects(self, kind):
        from app._03_world import ObjectType

        if kind is ObjectType.MONSTER:
            return list(self.mobs)
        return []

    def get_object(self, track_id: int):
        for mob in self.mobs:
            if mob.track_id == int(track_id):
                return mob
        return None


class _Hunt:
    def __init__(self, x: int, y: int) -> None:
        self.scratch: dict = {}
        self.world_origin = SimpleNamespace(x=x, y=y)
        self.current_target_id = None
        self.current_item_id = None
        self.current_goal = None
        self.emitted: list = []
        self.search_hop_active = False

    def emit(self, action, **kwargs) -> None:
        self.emitted.append((action, kwargs.get("reason"), kwargs.get("destination")))


def test_stored_radii_are_6_and_8_not_clamped_to_4() -> None:
    board = _Hunt(105, 100)
    set_party_turret(board, True, map_id=4, anchor=(100, 100), engage=6, chase=8)
    assert zone_pair(board) == (6, 8)
    assert board.scratch["party_turret"]["engage"] == 6
    assert board.scratch["party_turret"]["chase"] == 8


def test_next_monster_does_not_walk_back_to_the_dot() -> None:
    board = _Hunt(105, 100)
    set_party_turret(board, True, map_id=4, anchor=(100, 100), engage=6, chase=8)
    step_party_turret_leash(_State([_Mob(2, 1)]), board)  # type: ignore[arg-type]
    assert 2 not in set(board.scratch["party_turret_exclude"])
    assert board.emitted == []
    assert member_zone_center(100, 100, 4, 4) == (100, 100)
    assert member_zone_center(100, 100, 4, None) is None
    assert hunt_center((105, 100), 100, 100) == (100, 100)


def test_chase_stops_past_8_and_an_archer_does_not_step() -> None:
    knight = _Hunt(100, 100)
    set_party_turret(knight, True, map_id=4, anchor=(100, 100), engage=6, chase=8)
    knight.current_target_id = 8
    step_party_turret_leash(_State([_Mob(8, 10)]), knight)  # type: ignore[arg-type]
    assert 8 in set(knight.scratch["party_turret_exclude"])
    assert knight.emitted == []

    archer = _Hunt(105, 100)
    set_party_turret(archer, True, map_id=4, anchor=(100, 100), engage=6, chase=8)
    step_party_turret_leash(_State([_Mob(3, 4)], kind="elf"), archer)  # type: ignore[arg-type]
    assert 3 not in set(archer.scratch["party_turret_exclude"])
    assert archer.emitted == []


def test_a_path_that_leaves_the_zone_issues_no_click() -> None:
    board = _Hunt(104, 100)
    set_party_turret(board, True, map_id=4, anchor=(100, 100), engage=6, chase=8)

    def _out(me, stand):
        del me, stand
        return (100, 120), [(100, 120), (105, 100)]

    board.scratch["party_turret_path_for"] = _out
    step_party_turret_leash(_State([_Mob(2, 2)]), board)  # type: ignore[arg-type]
    assert 2 in set(board.scratch["party_turret_exclude"])
    assert board.emitted == []
    assert pick_attack_stand(
        (106, 100),
        (104, 100),
        (100, 100),
        ranged=False,
        can_hit=False,
        engaged=False,
        engage=6,
        chase=8,
        path_for=_out,
    ) is None


def test_same_dot_keeps_the_fight_and_a_new_dot_drops_it() -> None:
    board = _Hunt(105, 100)
    set_party_turret(board, True, map_id=4, anchor=(100, 100))
    board.current_target_id = 2
    set_party_turret(board, True, map_id=4, anchor=(100, 100))
    assert board.current_target_id == 2
    set_party_turret(board, True, map_id=4, anchor=(180, 100))
    assert board.current_target_id is None
    fresh = _Hunt(105, 100)
    set_party_turret(fresh, True, map_id=4, anchor=(100, 100))
    fresh.current_target_id = 2
    set_party_turret(fresh, True, map_id=9, anchor=(100, 100))
    assert fresh.current_target_id is None


def test_member_keeps_own_fight_and_one_fighter_helps_the_mage() -> None:
    assert turret_member_focus(
        leader_farming=True, own_id=2, own_still_ok=True, yard_id=9
    ) == ("own_finish", 2)
    assert turret_member_focus(
        leader_farming=True, own_id=None, own_still_ok=False, yard_id=None
    ) == ("leader", None)
    rows = [
        sighting_message(
            who="Knight", map_id=4, species="wolf", guid="B", x=106, y=100,
            victim="Mage", victim_hp=20, can_attack=True, role="member",
        ),
        sighting_message(
            who="Archer", map_id=4, species="orc", guid="A", x=104, y=100,
            engaged=True, can_attack=True, role="member",
        ),
    ]
    focus = choose_focus(
        rows,
        mode="turret",
        current={"map_id": 4, "species": "orc", "guid": "A", "x": 104, "y": 100},
    )
    assert focus is not None and focus.support == "Knight" and focus.leader_guid == "A"
    kind, mob = client_action(
        role="leader",
        name="Leader",
        focus=focus,
        local=[SimpleNamespace(species="orc", tile=(104, 100), guid="A")],
        attacked=False,
    )
    assert kind == "attack" and mob.guid == "A"
    assert client_action(
        role="leader",
        name="Leader",
        focus=focus,
        local=[],
        attacked=False,
    )[0] == "ignore"
