"""Party dungeon_plan order, stage clocks, and solo patrol isolation."""
from __future__ import annotations

from types import SimpleNamespace

from app._04_decision.blackboard import Blackboard
from app._04_decision.mode_control import complete_travel_arrival
from app._04_decision.patrol import (
    get_patrol_waypoints,
    set_patrol_waypoints,
)
from app._04_decision.player_mode import PlayerMode
from app._06_party.leader_manager import PartyLeaderManager
from app._06_party.leader_schedule import (
    PartyLeaderSchedule,
    hunt_marks,
    party_plan_motion,
    yaml_patrol_allowed,
)


def _plan_row() -> dict:
    return {
        "id": "dungeon",
        "map_id": "giran_dungeon_F1",
        "kind": "battle",
        "duration_minutes": 60,
        "coords_saved": True,
        "areas": [],
        "patrol": [
            {"x": 0, "y": 0, "name": "a"},
            {"x": 10, "y": 0, "name": "b"},
            {"x": 10, "y": 10, "name": "c"},
        ],
        "dungeon_plan": [
            {
                "type": "patrol",
                "id": "patrol_1",
                "duration_s": 1500,
                "waypoints": [
                    {"x": 0, "y": 0, "name": "a"},
                    {"x": 10, "y": 0, "name": "b"},
                    {"x": 10, "y": 10, "name": "c"},
                ],
                "game_map_id": 53,
                "pack_id": "giran_dungeon_F1",
            },
            {
                "type": "point",
                "id": "point_1",
                "name": "point_1",
                "x": 30,
                "y": 40,
                "stay_s": 600,
                "game_map_id": 53,
                "pack_id": "giran_dungeon_F1",
            },
            {
                "type": "patrol",
                "id": "patrol_2",
                "duration_s": 900,
                "waypoints": [{"x": 50, "y": 50, "name": "d"}],
                "game_map_id": 53,
                "pack_id": "giran_dungeon_F1",
            },
            {
                "type": "point",
                "id": "point_2",
                "name": "point_2",
                "x": 70,
                "y": 80,
                "stay_s": 300,
                "game_map_id": 53,
                "pack_id": "giran_dungeon_F1",
            },
        ],
    }


def _schedule() -> PartyLeaderSchedule:
    return PartyLeaderSchedule.from_routine([_plan_row()])


def _ids(schedule: PartyLeaderSchedule) -> list[str]:
    plan = schedule.dungeon_plan() or []
    return [str(entry.get("id") or "") for entry in plan]


def test_saved_order_is_patrol_point_patrol_point() -> None:
    schedule = _schedule()
    assert _ids(schedule) == ["patrol_1", "point_1", "patrol_2", "point_2"]
    assert schedule.current_plan_entry()["id"] == "patrol_1"
    assert hunt_marks(schedule.current())[0]["name"] == "a"


def test_nearest_waypoint_then_saved_order_and_loop() -> None:
    schedule = _schedule()
    schedule.bind_patrol_waypoint(9, 1)
    assert schedule.patrol_waypoint_index == 1
    assert schedule.patrol_goal_xy() == (10, 0)
    schedule.note_patrol_arrival(10, 0)
    assert schedule.patrol_goal_xy() == (10, 10)
    schedule.note_patrol_arrival(10, 10)
    assert schedule.patrol_goal_xy() == (0, 0)
    schedule.note_patrol_arrival(0, 0)
    assert schedule.patrol_goal_xy() == (10, 0)
    assert schedule.stage_elapsed == 0.0
    assert schedule.plan_index == 0


def test_patrol_duration_expires_onto_the_next_entry() -> None:
    schedule = _schedule()
    schedule.bind_patrol_waypoint(0, 0)
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    schedule.note_plan_stage(1499.0, running=True, at_point=False)
    assert schedule.stage_due(1499.0) is False
    schedule.note_plan_stage(1500.0, running=True, at_point=False)
    assert schedule.stage_due(1500.0) is True
    assert schedule.advance_plan_stage()
    assert schedule.current_plan_entry()["id"] == "point_1"
    assert schedule.stage_elapsed == 0.0
    assert schedule.point_arrived is False
    assert schedule.motion_snapshot()["goal"] == (30, 40)


def test_point_dwell_starts_after_arrival_and_ignores_travel() -> None:
    schedule = _schedule()
    schedule.advance_plan_stage()
    assert schedule.current_plan_entry()["id"] == "point_1"
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    schedule.note_plan_stage(500.0, running=True, at_point=False)
    assert schedule.point_arrived is False
    assert schedule.stage_elapsed == 0.0
    assert schedule.stage_due(500.0) is False
    schedule.note_plan_stage(500.0, running=True, at_point=True)
    assert schedule.point_arrived is True
    assert schedule.stage_elapsed == 0.0
    schedule.note_plan_stage(1099.0, running=True, at_point=False)
    assert schedule.stage_due(1099.0) is False
    schedule.note_plan_stage(1100.0, running=True, at_point=False)
    assert schedule.stage_due(1100.0) is True


def test_combat_does_not_reset_or_extend_the_stage() -> None:
    schedule = _schedule()
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    schedule.note_plan_stage(100.0, running=True, at_point=False)
    assert schedule.stage_elapsed == 100.0
    assert schedule.plan_index == 0
    schedule.note_plan_stage(1500.0, running=True, at_point=False)
    assert schedule.stage_due(1500.0) is True
    before = schedule.motion_snapshot()["goal"]
    schedule.advance_plan_stage()
    assert schedule.current_plan_entry()["id"] == "point_1"
    assert schedule.motion_snapshot()["goal"] != before
    assert schedule.motion_snapshot()["generation"] == 1


def test_pause_keeps_remaining_stage_time() -> None:
    schedule = _schedule()
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    schedule.note_plan_stage(100.0, running=True, at_point=False)
    schedule.note_plan_stage(100.0, running=False, at_point=False)
    schedule.note_plan_stage(400.0, running=False, at_point=False)
    assert schedule.stage_elapsed == 100.0
    assert schedule.plan_index == 0
    assert schedule.stage_state == "paused"
    schedule.note_plan_stage(400.0, running=True, at_point=False)
    schedule.note_plan_stage(450.0, running=True, at_point=False)
    assert schedule.stage_elapsed == 150.0
    assert schedule.current_plan_entry()["id"] == "patrol_1"


def test_overall_duration_overrides_the_stage() -> None:
    schedule = _schedule()
    schedule.rows.append(
        {
            "id": "next",
            "map_id": "talking_island",
            "kind": "battle",
            "duration_minutes": 30,
            "areas": [{"name": "yard", "shape": "point", "x": 1, "y": 2}],
            "patrol": [],
        }
    )
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    schedule.note_inside(0.0, True)
    schedule.note_inside(3600.0, True)
    assert schedule.due(3600.0) is True
    assert schedule.stage_due(10.0) is False
    assert schedule.advance()
    assert schedule.current()["id"] == "next"
    assert schedule.dungeon_plan() is None
    assert schedule.plan_index == 0
    assert schedule.stage_elapsed == 0.0
    assert schedule.goal_nav() == ("talking_island", 1, 2)


def test_zero_and_negative_patrol_durations_skip_without_looping() -> None:
    schedule = PartyLeaderSchedule(
        [
            {
                "id": "d",
                "map_id": "giran_dungeon_F1",
                "duration_minutes": 30,
                "areas": [],
                "patrol": [],
                "dungeon_plan": [
                    {
                        "type": "patrol",
                        "id": "zero",
                        "duration_s": 0,
                        "waypoints": [{"x": 1, "y": 1, "name": "a"}],
                    },
                    {
                        "type": "patrol",
                        "id": "negative",
                        "duration_s": -5,
                        "waypoints": [{"x": 2, "y": 2, "name": "b"}],
                    },
                ],
            }
        ]
    )
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    assert schedule.plan_invalid is True
    assert len(schedule.plan_errors) == 2
    schedule.note_plan_stage(10.0, running=True, at_point=False)
    assert len(schedule.plan_errors) == 2
    assert schedule.plan_index == 0


def test_missing_patrol_duration_is_reported_and_does_not_block() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "id": "d",
                "map_id": "giran_dungeon_F1",
                "duration_minutes": 30,
                "coords_saved": True,
                "areas": [],
                "patrol": [{"x": 1, "y": 2, "name": "mid_1"}],
                "dungeon_plan": [
                    {
                        "type": "patrol",
                        "id": "patrol_1",
                        "waypoints": [{"x": 1, "y": 2, "name": "mid_1"}],
                    },
                    {
                        "type": "point",
                        "id": "point_1",
                        "x": 3,
                        "y": 4,
                        "name": "point_1",
                        "stay_s": 120,
                    },
                ],
            }
        ]
    )
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    assert schedule.plan_errors
    assert "no positive duration_s" in schedule.plan_errors[0]
    assert schedule.current_plan_entry()["id"] == "point_1"
    assert schedule.plan_invalid is False


def test_legacy_patrol_only_row_is_unchanged() -> None:
    schedule = PartyLeaderSchedule.from_routine(
        [
            {
                "id": "old",
                "map_id": "giran_dungeon_F1",
                "duration_minutes": 45,
                "coords_saved": True,
                "areas": [],
                "patrol": [
                    {"x": 3, "y": 4, "name": "mid_1"},
                    {"x": 8, "y": 9, "name": "mid_2"},
                ],
            }
        ]
    )
    assert schedule.dungeon_plan() is None
    assert schedule.motion_snapshot() is None
    assert yaml_patrol_allowed({}) is True
    assert hunt_marks(schedule.current())[1]["x0"] == 8
    assert schedule.mark_stay_s() == 600.0
    assert schedule.mark_index == 0
    assert schedule.current_mark()["name"] == "mid_1"
    assert schedule.advance_mark() is True
    assert schedule.mark_index == 1
    assert schedule.current_mark()["name"] == "mid_2"
    assert [mark["name"] for mark in schedule.marks()] == ["mid_1", "mid_2"]


def test_cycle_returns_to_patrol_1_with_a_fresh_clock() -> None:
    schedule = _schedule()
    seen = []
    for _ in range(4):
        seen.append(schedule.current_plan_entry()["id"])
        schedule.advance_plan_stage()
    assert seen == ["patrol_1", "point_1", "patrol_2", "point_2"]
    assert schedule.current_plan_entry()["id"] == "patrol_1"
    assert schedule.plan_index == 0
    assert schedule.patrol_waypoint_index is None
    assert schedule.stage_elapsed == 0.0
    assert schedule.point_arrived is False
    schedule.bind_patrol_waypoint(9, 1)
    assert schedule.patrol_waypoint_index == 1


def test_solo_patrol_list_is_not_replaced_or_advanced() -> None:
    set_patrol_waypoints([(9, 9), (8, 8)])
    schedule = _schedule()
    schedule.bind_patrol_waypoint(9, 1)
    schedule.note_patrol_arrival(10, 0)
    schedule.note_plan_stage(0.0, running=True, at_point=False)
    schedule.advance_plan_stage()
    assert get_patrol_waypoints() == [(9, 9), (8, 8)]
    board = Blackboard()
    board.scratch["patrol_ready"] = True
    board.patrol_index = 0
    board.nav_goal = (9, 9)
    board.travel_purpose = "patrol"
    complete_travel_arrival(board)
    assert board.patrol_index == 1
    owned = Blackboard()
    owned.scratch["patrol_ready"] = True
    owned.scratch["party_dungeon_plan"] = {
        "active": True,
        "kind": "patrol",
        "goal": (10, 0),
        "generation": 0,
        "id": "patrol_1",
    }
    owned.patrol_index = 0
    owned.nav_goal = (10, 0)
    owned.travel_purpose = "patrol"
    complete_travel_arrival(owned)
    assert owned.patrol_index == 0
    assert get_patrol_waypoints() == [(9, 9), (8, 8)]
    assert yaml_patrol_allowed(owned.scratch) is False
    assert party_plan_motion(owned.scratch)["id"] == "patrol_1"
    set_patrol_waypoints([])


class _PlanManager(PartyLeaderManager):
    def _on_row_map(self, row, pose):
        del row, pose
        return True

    def _nav_xy(self, pack_id, pose):
        del pack_id
        return int(pose.x), int(pose.y)

    def _hunt_target_alive(self, world):
        return bool(getattr(world, "combat", False))

    def _arm_travel(self, blackboard, world, pose):
        del world, pose
        blackboard.scratch["armed"] = self.schedule.plan_point_goal_nav()

    def _install_plan_farms(self, blackboard, row, rects):
        del row
        blackboard.scratch["farms"] = list(rects)

    def _hold_plan_turret(self, blackboard, row, anchor):
        del row
        blackboard.scratch["turret"] = anchor

    def _release_turret_routine(self, blackboard):
        blackboard.scratch["turret"] = None

    def _plan_clock_paused(self, world, row, pose):
        del row, pose
        return bool(getattr(world, "paused", False))


def test_expired_patrol_does_not_keep_its_navigation_goal() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = _PlanManager(decision)
    manager.arm([_plan_row()])
    board = decision.blackboard
    pose = SimpleNamespace(x=9, y=1, map_id=53)
    world = SimpleNamespace(combat=True, paused=False, player=None)
    manager._drive_dungeon_plan(world, manager.schedule.current(), pose, 0.0)
    assert board.scratch["party_dungeon_plan"]["goal"] == (10, 0)
    board.nav_goal = (10, 0)
    board.travel_purpose = "patrol"
    board.player_mode = PlayerMode.TRAVELING
    manager._drive_dungeon_plan(world, manager.schedule.current(), pose, 1500.0)
    snap = board.scratch["party_dungeon_plan"]
    assert snap["id"] == "point_1"
    assert snap["goal"] == (30, 40)
    assert board.nav_goal is None
    assert board.travel_purpose is None
    assert board.scratch.get("armed") is None
    assert manager.schedule.stage_state == "transition"


def test_post_retreat_walk_yields_to_the_active_plan() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = _PlanManager(decision)
    manager.arm([_plan_row()])
    board = decision.blackboard
    board.player_mode = PlayerMode.WORLD_NAV
    board.scratch["world_nav_session"] = SimpleNamespace(
        reason="post_retreat", phase="walk", plan=None
    )
    world = SimpleNamespace(
        combat=False,
        paused=False,
        player=None,
        last_memory_snapshot={"player": {"x": 9, "y": 1, "mapId": 53}},
        last_print_state=None,
    )
    manager.prepare(world, rally=None)
    assert board.scratch.get("world_nav_session") is None
    assert board.scratch["party_dungeon_plan"]["id"] == "patrol_1"
    assert board.scratch["party_dungeon_plan"]["goal"] == (10, 0)
    assert board.player_mode is PlayerMode.FARMING


def test_legacy_row_keeps_its_active_walk() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = PartyLeaderManager(decision)
    manager.arm(
        [
            {
                "id": "old",
                "map_id": "giran_dungeon_F1",
                "duration_minutes": 45,
                "coords_saved": True,
                "areas": [],
                "patrol": [
                    {"x": 3, "y": 4, "name": "mid_1"},
                    {"x": 8, "y": 9, "name": "mid_2"},
                ],
            }
        ]
    )
    session = SimpleNamespace(reason="party_schedule", phase="walk", plan=None)
    decision.blackboard.scratch["world_nav_session"] = session
    decision.blackboard.scratch["need_world_nav"] = "post_retreat"
    world = SimpleNamespace(
        player=None,
        last_memory_snapshot={"player": {"x": 3, "y": 4, "mapId": 53}},
        last_print_state=None,
    )
    manager.prepare(world, rally=None)
    assert decision.blackboard.scratch.get("world_nav_session") is session
    assert decision.blackboard.scratch.get("need_world_nav") == "post_retreat"
    assert "party_dungeon_plan" not in decision.blackboard.scratch


def test_overall_timeout_clears_the_plan_before_the_next_row() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = _PlanManager(decision)
    manager.arm([_plan_row()])
    manager.schedule.rows.append(
        {
            "id": "next",
            "map_id": "talking_island",
            "kind": "battle",
            "duration_minutes": 30,
            "areas": [{"name": "yard", "shape": "point", "x": 1, "y": 2}],
            "patrol": [],
        }
    )
    pose = SimpleNamespace(x=0, y=0, map_id=53)
    world = SimpleNamespace(combat=False, paused=False, player=None)
    manager._drive_dungeon_plan(world, manager.schedule.current(), pose, 0.0)
    board = decision.blackboard
    board.nav_goal = (10, 0)
    board.travel_purpose = "patrol"
    board.player_mode = PlayerMode.TRAVELING
    board.scratch["world_nav_session"] = SimpleNamespace(
        reason="post_retreat", phase="walk", plan=None
    )
    manager._drive_dungeon_plan(world, manager.schedule.current(), pose, 3600.0)
    assert manager.schedule.current()["id"] == "next"
    assert "party_dungeon_plan" not in board.scratch
    assert board.scratch.get("world_nav_session") is None
    assert board.nav_goal is None
    assert "armed" in board.scratch


def test_post_retreat_request_does_not_arm_over_the_plan() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = _PlanManager(decision)
    manager.arm([_plan_row()])
    board = decision.blackboard
    board.player_mode = PlayerMode.WORLD_NAV
    board.scratch["need_world_nav"] = "post_retreat"
    world = SimpleNamespace(
        combat=False,
        paused=False,
        player=None,
        last_memory_snapshot={"player": {"x": 9, "y": 1, "mapId": 53}},
        last_print_state=None,
    )
    manager.prepare(world, rally=None)
    assert "need_world_nav" not in board.scratch
    assert board.scratch.get("world_nav_session") is None
    assert board.scratch["party_dungeon_plan"]["goal"] == (10, 0)
    assert board.player_mode is PlayerMode.FARMING


def test_point_walk_is_kept_when_a_return_request_is_dropped() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = _PlanManager(decision)
    manager.arm([_plan_row()])
    manager.schedule.advance_plan_stage()
    board = decision.blackboard
    session = SimpleNamespace(reason="party_schedule", phase="walk", plan=None)
    board.scratch["world_nav_session"] = session
    board.scratch["need_world_nav"] = "post_retreat"
    pose = SimpleNamespace(x=0, y=0, map_id=53)
    world = SimpleNamespace(combat=False, paused=False, player=None)
    manager._drive_dungeon_plan(world, manager.schedule.current(), pose, 0.0)
    assert board.scratch.get("world_nav_session") is session
    assert "need_world_nav" not in board.scratch
    assert board.scratch.get("armed") == ("giran_dungeon_F1", 30, 40)


def test_live_map_selects_the_row_pack_origin() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = PartyLeaderManager(decision)
    manager.arm([_plan_row()])
    row = manager.schedule.current()
    pose = SimpleNamespace(x=32649, y=32641, map_id=53)
    world = SimpleNamespace(player=None)
    assert manager._on_row_map(row, pose) is True
    manager._drive_dungeon_plan(world, row, pose, 0.0)
    assert decision.blackboard.scratch["party_dungeon_plan"]["goal"] == (10, 0)
    assert manager.schedule.stage_state == "hunting"

    other = PartyLeaderManager(SimpleNamespace(blackboard=Blackboard()))
    other.arm([_plan_row()])
    other.schedule.advance_plan_stage()
    away = SimpleNamespace(x=32670, y=32680, map_id=4)
    other._drive_dungeon_plan(world, other.schedule.current(), away, 0.0)
    assert other.schedule.point_arrived is False
    assert other.schedule.stage_state == "paused"
    assert other.decision.blackboard.scratch["party_dungeon_plan"]["goal"] is None

    mismatched = _plan_row()
    mismatched["dungeon_plan"][1]["game_map_id"] = 11
    bad = PartyLeaderManager(SimpleNamespace(blackboard=Blackboard()))
    bad.arm([mismatched])
    bad.schedule.advance_plan_stage()
    bad._drive_dungeon_plan(
        world,
        bad.schedule.current(),
        SimpleNamespace(x=32670, y=32680, map_id=53),
        0.0,
    )
    assert bad.schedule.point_arrived is False
    assert bad.schedule.stage_state == "paused"
    assert bad.decision.blackboard.scratch["party_dungeon_plan"]["goal"] is None
    assert any(
        "does not match" in message for message in bad.schedule._reported_plan_errors
    )


def test_point_stage_hunts_inside_the_box_without_a_patrol_goal() -> None:
    decision = SimpleNamespace(blackboard=Blackboard())
    manager = _PlanManager(decision)
    manager.arm([_plan_row()])
    manager.schedule.advance_plan_stage()
    pose = SimpleNamespace(x=30, y=40, map_id=53)
    world = SimpleNamespace(combat=False, paused=False, player=None)
    manager._drive_dungeon_plan(world, manager.schedule.current(), pose, 0.0)
    assert decision.blackboard.scratch["turret"] == (30, 40)
    assert decision.blackboard.scratch["party_dungeon_plan"]["kind"] == "point"
    assert decision.blackboard.scratch["party_dungeon_plan"]["arrived"] is True
    assert yaml_patrol_allowed(decision.blackboard.scratch) is False
