"""Party leader schedule is the party document, not the solo routine cursor."""
from __future__ import annotations

from app._06_party.leader_manager import PartyLeaderManager
from app._06_party.leader_schedule import PartyLeaderSchedule


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.player_mode = None
        self.farm_area_index = 0


class _Decision:
    def __init__(self) -> None:
        self.blackboard = _Board()
        self.calls = 0

    def decide(self, world):
        del world
        self.calls += 1
        return "leader-tick"


def test_empty_party_routine_does_not_install_solo_cursor() -> None:
    decision = _Decision()
    decision.blackboard.scratch["routine_cursor"] = ["solo"]
    manager = PartyLeaderManager(decision)
    assert manager.arm([]) == 0
    assert "routine_cursor" not in decision.blackboard.scratch
    assert "need_world_nav" not in decision.blackboard.scratch
    assert manager.decide(None) == "leader-tick"
    assert decision.calls == 1


def test_stale_check_uses_the_saved_party_mark() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "map_id": "talking_island",
                "kind": "battle",
                "duration_minutes": 30,
                "selected_farms": ["old-shared"],
                "areas": [
                    {"name": "stake", "shape": "point", "x": 7, "y": 8},
                ],
            }
        ]
    )
    assert schedule.goal_nav() == ("talking_island", 7, 8)
    assert schedule.inside_nav(7, 8)
    assert not schedule.inside_nav(1, 1)


def test_matching_check_keeps_that_mark_only() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "map_id": "talking_island",
                "duration_minutes": 1,
                "selected_farms": ["yard"],
                "areas": [
                    {
                        "name": "yard",
                        "shape": "area",
                        "x0": 10,
                        "y0": 20,
                        "x1": 30,
                        "y1": 40,
                    },
                    {"name": "stake", "shape": "point", "x": 7, "y": 8},
                ],
            }
        ]
    )
    assert schedule.goal_nav() == ("talking_island", 20, 30)
    assert schedule.inside_nav(10, 20)
    assert not schedule.inside_nav(7, 8)


def test_row_minutes_advance_to_the_next_party_row() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "map_id": "talking_island",
                "duration_minutes": 1,
                "areas": [{"name": "a", "shape": "point", "x": 1, "y": 1}],
            },
            {
                "map_id": "mainland",
                "duration_minutes": 5,
                "areas": [{"name": "b", "shape": "point", "x": 2, "y": 2}],
            },
        ]
    )
    schedule.note_inside(0.0, True)
    schedule.note_inside(59.0, True)
    assert not schedule.due(59.0)
    schedule.note_inside(60.0, True)
    assert schedule.due(60.0)
    assert schedule.advance()
    assert schedule.goal_nav() == ("mainland", 2, 2)
    assert schedule.advance() is False


def test_a_point_is_turret_and_a_rect_is_moving() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "map_id": "talking_island",
                "areas": [
                    {
                        "name": "yard",
                        "shape": "area",
                        "x0": 0,
                        "y0": 0,
                        "x1": 10,
                        "y1": 10,
                    },
                    {"name": "stake", "shape": "point", "x": 7, "y": 8},
                    {"name": "dotbox", "shape": "area", "x0": 3, "y0": 3, "x1": 3, "y1": 3},
                ],
            }
        ]
    )
    assert schedule.place_nav(7, 8) == "point"
    assert schedule.place_nav(9, 10) == "point"
    assert schedule.inside_nav(9, 10)
    assert schedule.place_nav(10, 8) == "area"
    assert not schedule.inside_nav(7, 11)
    assert schedule.place_nav(1, 1) == "area"
    assert schedule.place_nav(3, 3) == "area"
    assert schedule.place_nav(50, 50) == "none"
    assert schedule.point_nav(9, 8) == (7, 8)


def test_pinned_turret_anchor_is_the_point() -> None:
    from app._04_decision.behaviors.party_turret import (
        _ensure_anchor,
        set_party_turret,
    )

    class _Board:
        def __init__(self) -> None:
            self.scratch: dict = {}

    board = _Board()
    set_party_turret(board, True, map_id=4, anchor=(9, 8))
    set_party_turret(board, True, map_id=4, anchor=(2, 2))
    assert _ensure_anchor(board) == (2, 2)
    set_party_turret(board, False, map_id=4)
    assert board.scratch["party_turret"]["on"] is False
    assert board.scratch["party_turret"]["pinned"] is False


def test_dot_anchor_is_nav_center_of_the_box() -> None:
    decision = _Decision()
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "map_id": "talking_island",
                "areas": [{"name": "stake", "shape": "point", "x": 7, "y": 8}],
            }
        ]
    )
    manager._nav_xy = lambda pack_id, pose: (9, 8)  # type: ignore[method-assign]
    manager._apply_place({"map_id": "talking_island"}, object())
    assert manager.hunt_mode == "turret"
    assert manager.turret_anchor == (7, 8)


def test_outside_the_box_finishes_the_current_target() -> None:
    from types import SimpleNamespace

    from app._04_decision.world_nav import session as nav_session

    decision = _Decision()
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "map_id": "talking_island",
                "duration_minutes": 30,
                "areas": [{"name": "stake", "shape": "point", "x": 7, "y": 8}],
            }
        ]
    )
    walked: list[int] = []
    farmed: list[int] = []
    manager._nav_xy = lambda pack_id, pose: (10, 8)  # type: ignore[method-assign]
    manager._on_row_map = lambda row, pose: True  # type: ignore[method-assign]
    manager._mount = lambda *args, **kwargs: None  # type: ignore[method-assign]
    manager._arm_travel = lambda *args, **kwargs: walked.append(1)  # type: ignore[method-assign]
    manager._farm = lambda *args, **kwargs: farmed.append(1)  # type: ignore[method-assign]
    real_pose = nav_session.live_pose_from_state
    nav_session.live_pose_from_state = (
        lambda state, fresh=False: SimpleNamespace(map_id=0, x=1, y=1)
    )
    try:
        manager._hunt_target_alive = lambda world: True  # type: ignore[method-assign]
        manager.prepare(object(), None)
        assert manager.hunt_mode == "turret"
        assert manager.turret_anchor == (7, 8)
        assert farmed == [1]
        assert walked == []

        farmed.clear()
        manager._hunt_target_alive = lambda world: False  # type: ignore[method-assign]
        manager.prepare(object(), None)
        assert manager.hunt_mode == "moving"
        assert manager.turret_anchor is None
        assert walked == [1]
        assert farmed == []
    finally:
        nav_session.live_pose_from_state = real_pose


def test_outside_the_box_walks_back_to_the_dot() -> None:
    from types import SimpleNamespace

    from app._03_world import ObjectStatus, ObjectType
    from app._04_decision.behaviors.party_turret import (
        set_party_turret,
        step_party_turret_leash,
    )

    class _Mob:
        def __init__(self, track_id: int) -> None:
            self.track_id = track_id
            self.object_type = ObjectType.MONSTER
            self.status = ObjectStatus.ALIVE
            self.bait = False
            self.force_attacks_me = False

    class _State:
        def __init__(self) -> None:
            self.last_print_state = {"entities": []}
            self.mobs = [_Mob(5), _Mob(9)]

        def get_object(self, track_id: int):
            for mob in self.mobs:
                if mob.track_id == int(track_id):
                    return mob
            return None

        def objects(self, kind):
            if kind is ObjectType.MONSTER:
                return list(self.mobs)
            return []

        def missing_frames(self, track_id: int) -> int:
            del track_id
            return 0

    class _Board:
        def __init__(self) -> None:
            self.scratch: dict = {}
            self.world_origin = SimpleNamespace(x=13, y=10)
            self.current_target_id: int | None = 5
            self.current_item_id = None
            self.current_goal = None
            self.current_target_species = None
            self.current_target_world = None
            self.target_engage_started = 1.0
            self.emitted: list = []

        def emit(self, action, **kwargs) -> None:
            self.emitted.append(action)

    board = _Board()
    set_party_turret(board, True, map_id=4, anchor=(10, 10))
    step_party_turret_leash(_State(), board)  # type: ignore[arg-type]
    assert board.current_target_id is None
    assert 9 in board.scratch["party_turret_exclude"]
    assert 5 in board.scratch["party_turret_exclude"]
    assert board.emitted


def test_elf_turret_uses_the_solo_click_range() -> None:
    from types import SimpleNamespace

    from app._03_world import CharacterType, ObjectStatus, ObjectType
    from app._04_decision.behaviors.party_turret import (
        set_party_turret,
        step_party_turret_leash,
    )

    class _Mob:
        def __init__(self, track_id: int, rx: int, ry: int, on_screen: bool) -> None:
            self.track_id = track_id
            self.object_type = ObjectType.MONSTER
            self.status = ObjectStatus.ALIVE
            self.world_rx = rx
            self.world_ry = ry
            self.position = SimpleNamespace(x=0.5, y=0.5) if on_screen else None

    class _State:
        def __init__(self) -> None:
            self.player = SimpleNamespace(character_type=CharacterType.ELF)
            self.mobs = [
                _Mob(1, 9, 0, False),
                _Mob(2, 8, 0, False),
                _Mob(3, 40, 0, True),
                _Mob(4, 1, 0, True),
            ]

        def get_object(self, track_id: int):
            for mob in self.mobs:
                if mob.track_id == int(track_id):
                    return mob
            return None

        def objects(self, kind):
            if kind is ObjectType.MONSTER:
                return list(self.mobs)
            return []

    class _Board:
        def __init__(self) -> None:
            self.scratch: dict = {}
            self.world_origin = SimpleNamespace(x=10, y=10)
            self.current_target_id = None
            self.current_item_id = None
            self.current_goal = None
            self.emitted: list = []

        def emit(self, action, **kwargs) -> None:
            self.emitted.append(action)

    board = _Board()
    set_party_turret(board, True, map_id=4, anchor=(10, 10))
    step_party_turret_leash(_State(), board)  # type: ignore[arg-type]
    excluded = set(board.scratch["party_turret_exclude"])
    assert 1 in excluded
    assert 2 not in excluded
    assert 3 not in excluded
    assert 4 not in excluded
    assert board.emitted == []


def test_no_target_idles_on_the_dot() -> None:
    from types import SimpleNamespace

    from app._03_world import ActionType
    from app._04_decision.behaviors.party_turret import (
        set_party_turret,
        step_party_turret_idle,
    )

    class _Board:
        def __init__(self, x: int, y: int) -> None:
            self.scratch: dict = {}
            self.world_origin = SimpleNamespace(x=x, y=y)
            self.current_goal = None
            self.emitted: list = []
            self.search_leg_ticks = 4
            self.search_destination = (1, 1)
            self.search_waypoint = (1, 1)
            self.search_leg_goal = (1, 1)
            self.search_hop_active = True
            self.search_click_at = 1.0
            self.search_stuck_tile = None
            self.search_stuck_since_tick = 0
            self.search_stuck_since_time = 0.0
            self.search_unstick_active = False
            self.unstick_tries = 0

        def emit(self, action, **kwargs) -> None:
            self.emitted.append((action, kwargs.get("reason")))

    near = _Board(11, 10)
    set_party_turret(near, True, map_id=4, anchor=(10, 10))
    step_party_turret_idle(object(), near)  # type: ignore[arg-type]
    assert near.emitted == [(ActionType.IDLE, "party turret wait on anchor")]
    assert near.search_hop_active is False

    off = _Board(13, 10)
    set_party_turret(off, True, map_id=4, anchor=(10, 10))
    step_party_turret_idle(object(), off)  # type: ignore[arg-type]
    assert off.emitted
    assert off.emitted[0][0] is ActionType.TRAVELING

    on = _Board(10, 10)
    set_party_turret(on, True, map_id=4, anchor=(10, 10))
    step_party_turret_idle(object(), on)  # type: ignore[arg-type]
    assert on.emitted == [(ActionType.IDLE, "party turret wait on anchor")]


def test_hold_does_not_spend_the_row() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "map_id": "talking_island",
                "duration_minutes": 1,
                "areas": [{"name": "a", "shape": "point", "x": 1, "y": 1}],
            }
        ]
    )
    schedule.note_inside(0.0, True, holding=True)
    schedule.note_inside(120.0, True, holding=True)
    assert schedule.elapsed == 0.0
    assert not schedule.due(120.0)


def test_rally_walks_to_the_mark_before_waiting() -> None:
    from types import SimpleNamespace

    from app._04_decision.world_nav import session as nav_session
    from app._06_party.leader_rally import LeaderStartRally
    from websocket.party_orders import Rally

    decision = _Decision()
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "map_id": "mainland",
                "duration_minutes": 60,
                "areas": [
                    {
                        "name": "field",
                        "shape": "area",
                        "x0": 1,
                        "y0": 1,
                        "x1": 50,
                        "y1": 50,
                    }
                ],
            }
        ]
    )
    walked: list[int] = []
    farmed: list[int] = []
    manager._arrival_point = lambda row, pose: (4, 33198, 33435)  # type: ignore[method-assign]
    manager._arm_travel = lambda *args, **kwargs: walked.append(1)  # type: ignore[method-assign]
    manager._farm = lambda *args, **kwargs: farmed.append(1)  # type: ignore[method-assign]
    manager._inside = lambda row, pose: True  # type: ignore[method-assign]
    manager._apply_place = lambda *args, **kwargs: None  # type: ignore[method-assign]
    manager._mount = lambda *args, **kwargs: None  # type: ignore[method-assign]
    manager._clear_travel = lambda *args, **kwargs: None  # type: ignore[method-assign]
    real_pose = nav_session.live_pose_from_state

    def _run(x: int, y: int, rally: LeaderStartRally) -> None:
        nav_session.live_pose_from_state = (
            lambda state, fresh=False: SimpleNamespace(map_id=4, x=x, y=y)
        )
        manager.prepare(object(), rally)

    try:
        rally = LeaderStartRally(Rally(), log=lambda _message: None)
        rally.begin({"poorboy"}, travel=False, pose=None)
        _run(33202, 33414, rally)
        assert rally.state == "await_mark"
        assert walked == [1]
        assert farmed == []

        walked.clear()
        edge = LeaderStartRally(Rally(), log=lambda _message: None)
        edge.begin({"poorboy"}, travel=False, pose=None)
        _run(33199, 33435, edge)
        assert edge.state == "waiting"
        assert walked == []
        assert farmed == []
        assert decision.blackboard.scratch.get("party_rally_wait") is True
        edge.update(
            1,
            {
                "members": [
                    {"name": "poorboy", "map_id": 4, "x": 33198, "y": 33435}
                ]
            },
        )
        assert edge.state == "done"
        _run(33199, 33435, edge)
        assert farmed == [1]
        assert decision.blackboard.scratch.get("party_rally_wait") is False
    finally:
        nav_session.live_pose_from_state = real_pose


def test_checked_marks_rotate_in_order() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "map_id": "mainland",
                "duration_minutes": 60,
                "selected_farms": ["area_2", "area_3", "point_1"],
                "farm_stays_s": {"area_2": 120.0, "area_3": 120.0, "point_1": 600.0},
                "areas": [
                    {
                        "name": "area_2",
                        "shape": "area",
                        "x0": 0,
                        "y0": 0,
                        "x1": 10,
                        "y1": 10,
                    },
                    {
                        "name": "area_3",
                        "shape": "area",
                        "x0": 100,
                        "y0": 100,
                        "x1": 120,
                        "y1": 120,
                    },
                    {"name": "point_1", "shape": "point", "x": 50, "y": 50},
                ],
            }
        ]
    )
    assert schedule.goal_nav() == ("mainland", 5, 5)
    assert schedule.inside_current_nav(1, 1)
    assert not schedule.inside_current_nav(110, 110)
    schedule.note_mark(0.0, True)
    schedule.note_mark(120.0, True)
    assert schedule.mark_due(120.0)
    assert schedule.advance_mark()
    assert schedule.goal_nav() == ("mainland", 110, 110)
    assert schedule.inside_current_nav(110, 110)
    assert not schedule.inside_current_nav(1, 1)
    schedule.mark_elapsed = 120.0
    assert schedule.advance_mark()
    assert schedule.goal_nav() == ("mainland", 50, 50)
    assert schedule.advance_mark()
    assert schedule.goal_nav() == ("mainland", 5, 5)


def test_prepare_walks_to_the_next_mark_when_the_stay_ends() -> None:
    from types import SimpleNamespace

    from app._04_decision.world_nav import session as nav_session

    decision = _Decision()
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "map_id": "mainland",
                "duration_minutes": 60,
                "selected_farms": ["area_2", "area_3"],
                "farm_stays_s": {"area_2": 120.0, "area_3": 120.0},
                "areas": [
                    {
                        "name": "area_2",
                        "shape": "area",
                        "x0": 0,
                        "y0": 0,
                        "x1": 10,
                        "y1": 10,
                    },
                    {
                        "name": "area_3",
                        "shape": "area",
                        "x0": 100,
                        "y0": 100,
                        "x1": 120,
                        "y1": 120,
                    },
                ],
            }
        ]
    )
    manager.schedule.mark_elapsed = 120.0
    walked: list[int] = []
    farmed: list[int] = []
    manager._nav_xy = lambda pack_id, pose: (1, 1)  # type: ignore[method-assign]
    manager._on_row_map = lambda row, pose: True  # type: ignore[method-assign]
    manager._mount = lambda *args, **kwargs: None  # type: ignore[method-assign]
    manager._arm_travel = lambda *args, **kwargs: walked.append(1)  # type: ignore[method-assign]
    manager._farm = lambda *args, **kwargs: farmed.append(1)  # type: ignore[method-assign]
    real_pose = nav_session.live_pose_from_state
    nav_session.live_pose_from_state = (
        lambda state, fresh=False: SimpleNamespace(map_id=4, x=1, y=1)
    )
    try:
        manager.prepare(object(), None)
        assert walked == [1]
        assert farmed == []
        assert manager.schedule.goal_nav() == ("mainland", 110, 110)
    finally:
        nav_session.live_pose_from_state = real_pose


def _point_leader():
    decision = _Decision()
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "map_id": "mainland",
                "areas": [
                    {
                        "name": "area_2",
                        "shape": "area",
                        "x0": 700,
                        "y0": 1200,
                        "x1": 800,
                        "y1": 1400,
                    },
                    {"name": "point_1", "shape": "point", "x": 966, "y": 366},
                ],
                "selected_farms": ["area_2", "point_1"],
            }
        ]
    )
    return manager


def test_point_arrival_arms_turret_inside_the_box() -> None:
    from types import SimpleNamespace

    from app._04_decision.behaviors.party_turret import (
        party_turret_active,
        turret_anchor,
        turret_routine_held,
    )
    from app._04_decision.world_nav import pack_ids

    manager = _point_leader()
    manager.schedule.mark_index = 1
    board = manager.decision.blackboard
    board.world_origin = SimpleNamespace(x=965, y=367)
    real = pack_ids.pack_id_to_map_id
    pack_ids.pack_id_to_map_id = lambda key: 4 if key == "mainland" else None
    try:
        assert manager._on_point_arrival(board, "party_schedule") is True
    finally:
        pack_ids.pack_id_to_map_id = real
    assert manager.hunt_mode == "turret"
    assert manager.turret_anchor == (966, 366)
    assert party_turret_active(board)
    assert turret_anchor(board) == (966, 366)
    assert turret_routine_held(board)


def test_point_arrival_stays_off_outside_the_box() -> None:
    from types import SimpleNamespace

    from app._04_decision.behaviors.party_turret import (
        party_turret_active,
        turret_routine_held,
    )

    manager = _point_leader()
    manager.schedule.mark_index = 1
    board = manager.decision.blackboard
    board.world_origin = SimpleNamespace(x=970, y=372)
    assert manager._on_point_arrival(board, "party_schedule") is False
    assert manager.hunt_mode == "moving"
    assert not party_turret_active(board)
    assert not turret_routine_held(board)


def test_arrived_point_stays_on_turret_outside_the_box() -> None:
    from types import SimpleNamespace

    from app._04_decision.behaviors.party_turret import hold_turret_routine
    from app._04_decision.world_nav import session as nav_session

    decision = _Decision()
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "map_id": "talking_island",
                "duration_minutes": 30,
                "areas": [{"name": "stake", "shape": "point", "x": 7, "y": 8}],
            }
        ]
    )
    hold_turret_routine(decision.blackboard)
    decision.blackboard.scratch["world_nav_session"] = object()
    decision.blackboard.scratch["need_world_nav"] = True
    walked: list[int] = []
    farmed: list[int] = []
    manager._nav_xy = lambda pack_id, pose: (10, 8)  # type: ignore[method-assign]
    manager._on_row_map = lambda row, pose: True  # type: ignore[method-assign]
    manager._mount = lambda *args, **kwargs: None  # type: ignore[method-assign]
    manager._arm_travel = lambda *args, **kwargs: walked.append(1)  # type: ignore[method-assign]
    manager._farm = lambda *args, **kwargs: farmed.append(1)  # type: ignore[method-assign]
    manager._hunt_target_alive = lambda world: False  # type: ignore[method-assign]
    real_pose = nav_session.live_pose_from_state
    nav_session.live_pose_from_state = (
        lambda state, fresh=False: SimpleNamespace(map_id=0, x=1, y=1)
    )
    try:
        manager.prepare(object(), None)
    finally:
        nav_session.live_pose_from_state = real_pose
    assert manager.hunt_mode == "turret"
    assert manager.turret_anchor == (7, 8)
    assert walked == []
    assert farmed == [1]
    assert "world_nav_session" not in decision.blackboard.scratch
    assert "need_world_nav" not in decision.blackboard.scratch


def test_party_member_attack_is_not_a_claim() -> None:
    from app._03_world.merge.memory_entities import contested_monster_guids

    snapshot = {
        "entities": [
            {"class": "MyPlayer", "guid": "0x10"},
            {"class": "Player", "guid": "0x20", "name": "포보이", "atk": 1, "tgt": "0x99"},
            {"class": "Player", "guid": "0x30", "name": "남", "atk": 1, "tgt": "0x98"},
            {"class": "Monster", "guid": "0x99"},
            {"class": "Monster", "guid": "0x98"},
        ]
    }
    claimed = contested_monster_guids(snapshot, ignore_names={"포보이"})
    assert 0x99 not in claimed
    assert 0x98 in claimed


def test_arrived_point_routine_skips_the_confined_escape() -> None:
    import time

    from app._02_state.enums import CharacterType
    from app._02_state.objects import Position
    from app._02_state.player import PlayerState
    from app._03_world import GameState
    from app._04_decision.behaviors.mode_ticks import _maybe_confined_escape
    from app._04_decision.behaviors.party_turret import (
        SCRATCH_TURRET_ROUTINE,
        hold_turret_routine,
    )
    from app._04_decision.behaviors.unstick import (
        SCRATCH_CONFINED_ORIGIN,
        SCRATCH_CONFINED_SINCE,
    )
    from app._04_decision.blackboard import Blackboard

    board = Blackboard()
    hold_turret_routine(board)
    board.scratch[SCRATCH_CONFINED_ORIGIN] = [969, 369]
    board.scratch[SCRATCH_CONFINED_SINCE] = time.time() - 20.0
    state = GameState(
        player=PlayerState(
            track_id=1,
            position=Position(x=0.5, y=0.5),
            character_type=CharacterType.ELF,
            level=19,
        )
    )
    assert _maybe_confined_escape(state, board) is None
    assert SCRATCH_CONFINED_ORIGIN not in board.scratch
    assert SCRATCH_CONFINED_SINCE not in board.scratch
    assert board.scratch.get(SCRATCH_TURRET_ROUTINE) is True


def test_area_arrival_does_not_arm_turret() -> None:
    from types import SimpleNamespace

    manager = _point_leader()
    board = manager.decision.blackboard
    board.world_origin = SimpleNamespace(x=750, y=1307)
    assert manager._on_point_arrival(board, "party_schedule") is False
    assert manager.hunt_mode == "moving"


def test_other_nav_reasons_do_not_arm_turret() -> None:
    from types import SimpleNamespace

    manager = _point_leader()
    manager.schedule.mark_index = 1
    board = manager.decision.blackboard
    board.world_origin = SimpleNamespace(x=966, y=366)
    assert manager._on_point_arrival(board, "unstick_return") is False
    assert manager.hunt_mode == "moving"


if __name__ == "__main__":
    test_empty_party_routine_does_not_install_solo_cursor()
    test_stale_check_uses_the_saved_party_mark()
    test_matching_check_keeps_that_mark_only()
    test_a_point_is_turret_and_a_rect_is_moving()
    test_dot_anchor_is_nav_center_of_the_box()
    test_outside_the_box_finishes_the_current_target()
    test_outside_the_box_walks_back_to_the_dot()
    test_elf_turret_uses_the_solo_click_range()
    test_pinned_turret_anchor_is_the_point()
    test_no_target_idles_on_the_dot()
    test_row_minutes_advance_to_the_next_party_row()
    test_hold_does_not_spend_the_row()
    test_rally_walks_to_the_mark_before_waiting()
    test_checked_marks_rotate_in_order()
    test_prepare_walks_to_the_next_mark_when_the_stay_ends()
    test_arrived_point_stays_on_turret_outside_the_box()
    test_party_member_attack_is_not_a_claim()
    test_point_arrival_arms_turret_inside_the_box()
    test_point_arrival_stays_off_outside_the_box()
    test_area_arrival_does_not_arm_turret()
    test_other_nav_reasons_do_not_arm_turret()
    print("OK")
