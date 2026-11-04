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


if __name__ == "__main__":
    test_empty_party_routine_does_not_install_solo_cursor()
    test_stale_check_uses_the_saved_party_mark()
    test_matching_check_keeps_that_mark_only()
    test_row_minutes_advance_to_the_next_party_row()
    test_hold_does_not_spend_the_row()
    print("OK")
