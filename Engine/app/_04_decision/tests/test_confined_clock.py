"""A paused decide loop does not fill the 13 s confined clock."""
from __future__ import annotations

from app._02_state.geometry import WorldOrigin
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors.unstick import (
    SCRATCH_CONFINED_ORIGIN,
    SCRATCH_CONFINED_SINCE,
    SCRATCH_CONFINED_TICK,
    note_confined_progress,
)


def _board() -> Blackboard:
    board = Blackboard()
    board.world_origin = WorldOrigin(x=649, y=1185)
    board.scratch[SCRATCH_CONFINED_ORIGIN] = [648, 1187]
    return board


def test_a_pause_gap_does_not_fill_the_confined_clock(monkeypatch) -> None:
    board = _board()
    board.scratch[SCRATCH_CONFINED_SINCE] = 1000.0
    board.scratch[SCRATCH_CONFINED_TICK] = 1002.0
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.time.time", lambda: 1015.0
    )
    assert note_confined_progress(board) is False
    assert board.scratch[SCRATCH_CONFINED_SINCE] == 1013.0


def test_running_ticks_still_fill_the_confined_clock(monkeypatch) -> None:
    board = _board()
    board.scratch[SCRATCH_CONFINED_SINCE] = 1000.0
    board.scratch[SCRATCH_CONFINED_TICK] = 1012.8
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.time.time", lambda: 1013.0
    )
    assert note_confined_progress(board) is True
