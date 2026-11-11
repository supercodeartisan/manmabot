"""A hunt click can be interrupted without forgetting the coverage goal."""

from app._04_decision.behaviors.search_hop import (
    clear_search_hop,
    emit_search_hop,
    suspend_search_click,
)


class _Origin:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


class _Farm:
    def contains(self, x: int, y: int) -> bool:
        return True


class _Board:
    def __init__(self) -> None:
        self.world_origin = _Origin(10, 10)
        self.scratch: dict = {}
        self.intent = None
        self.search_leg_goal = (30, 30)
        self.search_waypoint = (12, 12)
        self.search_hop_active = True
        self.search_destination = (12, 12)
        self.search_leg_ticks = 4
        self.search_click_at = 1.0
        self.search_stuck_tile = None
        self.search_stuck_since_tick = 0
        self.search_stuck_since_time = 0.0
        self.search_unstick_active = False
        self.last_search_tick = 1
        self.tick_count = 1
        self.farm_area_index = 0

    def emit(self, *_args, **_kwargs) -> None:
        return None


def test_suspend_keeps_the_goal_and_clear_drops_it() -> None:
    board = _Board()
    suspend_search_click(board)
    assert board.search_leg_goal == (30, 30)
    assert board.search_waypoint is None
    assert board.search_hop_active is False
    clear_search_hop(board)
    assert board.search_leg_goal is None


def test_a_tick_gap_walks_toward_the_same_goal(monkeypatch) -> None:
    board = _Board()
    board.tick_count = 8
    seen: dict = {}

    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop.get_active_farm",
        lambda _index: _Farm(),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop.get_terrain_map",
        lambda: object(),
    )

    def _hop(blackboard, **kwargs):
        seen["goal"] = kwargs["goal"]
        blackboard.intent = object()
        return True

    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop._emit_body_hop",
        _hop,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop._start_leg",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("new leg")),
    )
    assert emit_search_hop(
        board, reason="search area", priority=0.2, max_leg_ticks=60
    )
    assert seen["goal"] == (30, 30)
    assert board.search_leg_goal == (30, 30)
    assert board.search_leg_ticks == 0


def test_sixty_ticks_still_starts_a_new_leg(monkeypatch) -> None:
    board = _Board()
    board.search_leg_ticks = 59
    board.search_waypoint = (80, 80)
    board.last_search_tick = board.tick_count
    seen: dict = {}

    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop.get_active_farm",
        lambda _index: _Farm(),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop.get_terrain_map",
        lambda: object(),
    )

    def _start(blackboard, **kwargs):
        seen["reason"] = kwargs["reason"]
        return True

    monkeypatch.setattr(
        "app._04_decision.behaviors.search_hop._start_leg",
        _start,
    )
    emit_search_hop(board, reason="search area", priority=0.2, max_leg_ticks=60)
    assert seen["reason"] == "stuck, jumping elsewhere"
