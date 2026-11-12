"""Dungeon hunt points live on the existing party patrol list.

A legacy point is exactly ``{x, y, name}``. Optional ``stay_s``,
``game_map_id``, and ``pack_id`` are kept only when they are already valid.
The leader schedule still reads tiles and ``farm_stays_s``, not these fields.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app._03_world.space.tile_world import raw_map_id_from_pack
from app._06_party.leader_schedule import PartyLeaderSchedule, hunt_marks
from session.probes import load_map_pack_safe
from settings.party_routine import dungeon_plan_from_document, normalize_party_routine


def test_explicit_type_wins_over_stay_s_when_a_flat_patrol_list_is_split() -> None:
    plan = dungeon_plan_from_document(
        {
            "patrol": [
                {"x": 1, "y": 2, "name": "mid_1"},
                {"type": "patrol", "x": 3, "y": 4, "name": "mid_2", "stay_s": 900},
                {"type": "point", "x": 5, "y": 6, "name": "stake"},
                {"x": 7, "y": 8, "name": "old_point", "stay_s": 480},
            ]
        }
    )
    assert plan[0]["type"] == "patrol"
    assert plan[0]["waypoints"] == [
        {"x": 1, "y": 2, "name": "mid_1"},
        {"x": 3, "y": 4, "name": "mid_2"},
    ]
    assert "stay_s" not in plan[0]
    assert plan[1] == {
        "type": "point",
        "x": 5,
        "y": 6,
        "name": "stake",
        "id": "point_1",
    }
    assert plan[2]["type"] == "point"
    assert plan[2]["x"] == 7 and plan[2]["stay_s"] == 480.0


def test_legacy_patrol_point_is_unchanged() -> None:
    legacy = {"x": 9, "y": 8, "name": "길"}
    rows = normalize_party_routine(
        [{"id": "a", "map_id": "mainland", "patrol": [legacy]}]
    )
    assert rows[0]["patrol"] == [legacy]
    assert rows[0]["areas"] == []
    assert "stay_s" not in rows[0]["patrol"][0]
    assert "game_map_id" not in rows[0]["patrol"][0]


def test_optional_dungeon_fields_round_trip_and_bad_ids_are_dropped() -> None:
    rows = normalize_party_routine(
        [
            {
                "id": "d",
                "map_id": "giran_dungeon_F1",
                "coords_saved": True,
                "areas": [],
                "patrol": [
                    {
                        "x": 10,
                        "y": 20,
                        "name": "point_1",
                        "stay_s": 900,
                        "game_map_id": 53,
                        "pack_id": "giran_dungeon_F1",
                    },
                    {
                        "x": 11,
                        "y": 21,
                        "name": "point_2",
                        "game_map_id": "giran_dungeon_F1",
                        "pack_id": "  ",
                    },
                ],
            }
        ]
    )
    first, second = rows[0]["patrol"]
    assert first == {
        "x": 10,
        "y": 20,
        "name": "point_1",
        "stay_s": 900.0,
        "game_map_id": 53,
        "pack_id": "giran_dungeon_F1",
    }
    assert second == {"x": 11, "y": 21, "name": "point_2"}
    assert normalize_party_routine(rows) == rows


def test_field_areas_and_stays_stay_on_the_field_row() -> None:
    rows = normalize_party_routine(
        [
            {
                "id": "field",
                "map_id": "mainland",
                "selected_farms": ["point_1"],
                "farm_stays_s": {"point_1": 600, "gone": 120},
                "areas": [
                    {
                        "name": "point_1",
                        "shape": "point",
                        "region": "mainland",
                        "x": 421,
                        "y": 1143,
                        "stay_s": 900,
                        "game_map_id": 4,
                    }
                ],
                "patrol": [],
            },
            {
                "id": "island",
                "map_id": "talking_island",
                "selected_farms": ["point_1"],
                "farm_stays_s": {"point_1": 480},
                "areas": [
                    {
                        "name": "point_1",
                        "shape": "point",
                        "x": 3,
                        "y": 4,
                    }
                ],
                "patrol": [],
            },
        ]
    )
    mainland = rows[0]
    assert mainland["areas"] == [
        {
            "name": "point_1",
            "shape": "point",
            "region": "mainland",
            "x": 421,
            "y": 1143,
        }
    ]
    assert mainland["farm_stays_s"] == {"point_1": 600.0}
    assert mainland["patrol"] == []
    assert rows[1]["farm_stays_s"] == {"point_1": 480.0}
    assert rows[1]["map_id"] == "talking_island"


def test_dungeon_plan_is_optional_and_does_not_change_the_visit_duration() -> None:
    legacy = normalize_party_routine(
        [{"id": "a", "map_id": "giran_dungeon_F1", "duration_minutes": 90, "patrol": [{"x": 1, "y": 2, "name": "mid_1"}]}]
    )
    assert "dungeon_plan" not in legacy[0]
    assert legacy[0]["duration_minutes"] == 90
    assert legacy[0]["patrol"] == [{"x": 1, "y": 2, "name": "mid_1"}]

    stored = normalize_party_routine(
        [
            {
                "id": "d",
                "map_id": "giran_dungeon_F1",
                "duration_minutes": 90,
                "coords_saved": True,
                "patrol": [{"x": 1, "y": 2, "name": "mid_1"}],
                "dungeon_plan": [
                    {
                        "type": "patrol",
                        "id": "patrol_1",
                        "duration_s": 1800,
                        "game_map_id": 53,
                        "pack_id": "giran_dungeon_F1",
                        "waypoints": [{"x": 1, "y": 2, "name": "mid_1", "stay_s": 999}],
                    },
                    {
                        "type": "point",
                        "id": "point_1",
                        "name": "point_1",
                        "x": 8,
                        "y": 9,
                        "stay_s": 480,
                        "game_map_id": "53",
                        "pack_id": "giran_dungeon_F1",
                    },
                ],
            }
        ]
    )
    row = stored[0]
    assert row["duration_minutes"] == 90
    assert row["patrol"] == [{"x": 1, "y": 2, "name": "mid_1"}]
    assert row["dungeon_plan"][0]["waypoints"] == [{"x": 1, "y": 2, "name": "mid_1"}]
    assert row["dungeon_plan"][0]["duration_s"] == 1800.0
    assert row["dungeon_plan"][0]["game_map_id"] == 53
    assert row["dungeon_plan"][1]["stay_s"] == 480.0
    assert row["dungeon_plan"][1]["game_map_id"] == 53
    assert normalize_party_routine(stored) == stored


def test_leader_schedule_reads_the_legacy_route_not_the_plan() -> None:
    raw = [
        {
            "id": "d",
            "map_id": "giran_dungeon_F1",
            "duration_minutes": 90,
            "coords_saved": True,
            "areas": [],
            "farm_stays_s": {},
            "patrol": [{"x": 3, "y": 4, "name": "mid_1"}],
            "dungeon_plan": [
                {
                    "type": "patrol",
                    "id": "patrol_1",
                    "duration_s": 1800,
                    "waypoints": [{"x": 3, "y": 4, "name": "mid_1"}],
                },
                {
                    "type": "point",
                    "id": "point_1",
                    "x": 30,
                    "y": 40,
                    "name": "point_1",
                    "stay_s": 900,
                    "game_map_id": 53,
                    "pack_id": "giran_dungeon_F1",
                },
            ],
        }
    ]
    schedule = PartyLeaderSchedule.from_routine(raw)
    assert schedule.current()["duration_minutes"] == 90
    assert hunt_marks(schedule.current()) == [
        {"name": "mid_1", "shape": "point", "x0": 3, "y0": 4, "x1": 3, "y1": 4}
    ]
    assert schedule.mark_stay_s() == 600.0
    assert schedule.goal_nav() == ("giran_dungeon_F1", 3, 4)


def test_leader_schedule_ignores_dungeon_point_metadata() -> None:
    raw = [
        {
            "id": "d",
            "map_id": "giran_dungeon_F1",
            "coords_saved": True,
            "areas": [],
            "farm_stays_s": {},
            "patrol": [
                {
                    "x": 3,
                    "y": 4,
                    "name": "point_1",
                    "stay_s": 900,
                    "game_map_id": 53,
                    "pack_id": "giran_dungeon_F1",
                }
            ],
        }
    ]
    schedule = PartyLeaderSchedule.from_routine(raw)
    assert hunt_marks(schedule.current()) == [
        {
            "name": "point_1",
            "shape": "point",
            "x0": 3,
            "y0": 4,
            "x1": 3,
            "y1": 4,
        }
    ]
    assert schedule.mark_stay_s() == 600.0
    assert schedule.goal_nav() == ("giran_dungeon_F1", 3, 4)


def test_raw_map_comes_from_the_opened_pack_folder(tmp_path: Path) -> None:
    giran = load_map_pack_safe("giran_dungeon_F1")
    island = load_map_pack_safe("talking_island")
    assert giran is not None and island is not None
    assert raw_map_id_from_pack(giran) == 53
    assert raw_map_id_from_pack(island) is None

    first = tmp_path / "cave_a"
    second = tmp_path / "cave_b"
    first.mkdir()
    second.mkdir()
    (first / "meta.yaml").write_text(
        'id: cave_a\nraw_map: "53"\norigin_x: 1\norigin_y: 2\n',
        encoding="utf-8",
    )
    (second / "meta.yaml").write_text(
        "id: cave_b\nraw_map: cave_b\norigin_x: 9\norigin_y: 8\n",
        encoding="utf-8",
    )
    assert raw_map_id_from_pack(SimpleNamespace(root=first, id="cave_a")) == 53
    assert raw_map_id_from_pack(SimpleNamespace(root=second, id="cave_b")) is None
    assert raw_map_id_from_pack(SimpleNamespace(id="cave_a")) is None
