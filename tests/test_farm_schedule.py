from __future__ import annotations

from types import SimpleNamespace

from app._04_decision.blackboard import Blackboard
from app._04_decision.farm_area import FarmRect
from app._04_decision.farm_time import (
    FARM_DURATION_LIMIT,
    farm_time_exceeded,
)
from app._04_decision import farm_time as farm_time_mod
from app._04_decision.farm_tour import advance_farm_tour, ensure_farm_tour
from app._03_world.world_coords import WorldOrigin
from manmabot_v1.farm_schedule import (
    farm_rects_in_selection_order,
    normalize_farm_stays_s,
    stay_seconds_for,
)
from manmabot_v1.profile import Profile
from manmabot_v1.schedule import ScheduleStore
from manmabot_v1.task_runtime import apply_runtime_settings


def test_farm_rects_follow_selected_order():
    areas = [
        {"name": "area_1", "x0": 0},
        {"name": "area_2", "x0": 1},
        {"name": "area_3", "x0": 2},
    ]
    ordered = farm_rects_in_selection_order(areas, ["area_3", "missing", "area_1"])
    assert [row["name"] for row in ordered] == ["area_3", "area_1"]


def test_farm_stays_normalize_and_fallback():
    stays = normalize_farm_stays_s({"area_3": 900, "bad": "x", "": 120})
    assert stays["area_3"] == 900.0
    assert "bad" not in stays
    assert stay_seconds_for("area_3", stays, 600.0) == 900.0
    assert stay_seconds_for("area_2", stays, 600.0) == 600.0


def test_runtime_applies_farm_order_and_stays():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["move"]["selected_farms"] = ["area_3", "area_2"]
    task.settings["move"]["farm_stays_s"] = {"area_3": 1800, "area_2": 300}
    task.settings["move"]["farm_rotate_s"] = 600.0
    apply_runtime_settings(task, profile)
    assert profile.selected_farms == ["area_3", "area_2"]
    assert profile.farm_stays_s["area_3"] == 1800.0
    assert profile.farm_stays_s["area_2"] == 300.0
    assert profile.farm_rotate_s == 600.0


def test_ensure_farm_tour_uses_list_order(monkeypatch):
    farms = [
        FarmRect(0, 0, 2, 2, name="a"),
        FarmRect(40, 40, 42, 42, name="b"),
        FarmRect(10, 0, 12, 2, name="c"),
    ]
    monkeypatch.setattr("app._04_decision.farm_tour.get_farm_areas", lambda: farms)
    board = Blackboard()
    board.world_origin = WorldOrigin(x=100, y=100)
    ensure_farm_tour(board)
    assert board.farm_tour == [0, 1, 2]
    assert board.farm_area_index == 0
    assert advance_farm_tour(board) == 1
    assert advance_farm_tour(board) == 2
    assert advance_farm_tour(board) == 0


def test_ensure_farm_tour_resumes_inside_scheduled_area(monkeypatch):
    farms = [
        FarmRect(0, 0, 2, 2, name="a"),
        FarmRect(40, 40, 42, 42, name="b"),
    ]
    monkeypatch.setattr("app._04_decision.farm_tour.get_farm_areas", lambda: farms)
    board = Blackboard()
    board.world_origin = WorldOrigin(x=41, y=41)
    ensure_farm_tour(board)
    assert board.farm_tour == [0, 1]
    assert board.farm_tour_pos == 1
    assert board.farm_area_index == 1


def test_farm_time_uses_per_area_limit():
    board = SimpleNamespace(farm_elapsed_seconds=400.0, farm_time_inside=False, farm_time_last_sample=0.0)
    board.farm_area_index = 1
    previous = list(farm_time_mod.FARM_DURATION_LIMITS)
    farm_time_mod.FARM_DURATION_LIMITS = [600.0, 300.0]
    try:
        assert farm_time_exceeded(board) is True
        board.farm_area_index = 0
        assert farm_time_exceeded(board) is False
        assert FARM_DURATION_LIMIT == 600.0
    finally:
        farm_time_mod.FARM_DURATION_LIMITS = previous
