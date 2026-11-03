"""Party leader arms its own routine and does not call the solo schedule."""
from __future__ import annotations

from app._04_decision.world_nav.hooks import SCRATCH_NEED_WORLD_NAV, SCRATCH_ROUTINE
from app._04_decision.world_nav.overlays import get_map_overlay
from app._06_party.leader_manager import PartyLeaderManager


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.player_mode = None


class _Decision:
    def __init__(self) -> None:
        self.blackboard = _Board()
        self.calls = 0

    def decide(self, world):
        del world
        self.calls += 1
        return "leader-tick"


def test_empty_party_routine_does_not_arm_solo_fallback() -> None:
    decision = _Decision()
    manager = PartyLeaderManager(decision)
    assert manager.arm([]) == 0
    cursor = decision.blackboard.scratch[SCRATCH_ROUTINE]
    assert list(cursor.entries) == []
    assert SCRATCH_NEED_WORLD_NAV not in decision.blackboard.scratch
    assert get_map_overlay(decision.blackboard, "talking_island") == {}


def test_party_area_and_point_become_the_leader_route() -> None:
    decision = _Decision()
    manager = PartyLeaderManager(decision)
    count = manager.arm(
        [
            {
                "map_id": "talking_island",
                "kind": "battle",
                "duration_minutes": 30,
                "selected_farms": ["yard", "stake"],
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
    assert count == 1
    cursor = decision.blackboard.scratch[SCRATCH_ROUTINE]
    assert cursor.entries[0]["selected_farms"] == ["yard", "stake"]
    assert "areas" not in cursor.entries[0]
    overlay = get_map_overlay(decision.blackboard, "talking_island")
    by_name = {item["name"]: item for item in overlay["areas"]}
    assert by_name["yard"]["x0"] == 10 and by_name["yard"]["x1"] == 30
    assert by_name["stake"] == {
        "name": "stake",
        "region": "",
        "x0": 7,
        "y0": 8,
        "x1": 7,
        "y1": 8,
    }
    assert decision.blackboard.scratch[SCRATCH_NEED_WORLD_NAV] == "party_leader"
    assert manager.decide(None) == "leader-tick"
    assert decision.calls == 1


if __name__ == "__main__":
    test_empty_party_routine_does_not_arm_solo_fallback()
    test_party_area_and_point_become_the_leader_route()
    print("OK")
