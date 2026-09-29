"""Light is recast once per 12 minutes, not on every buff loop."""
from __future__ import annotations

import time

from app._04_decision.blackboard import Blackboard
from app._04_decision.spells import LIGHT_REUSE_S, due_buff, mark_buff_cast


def test_buff_timers_survive_blackboard_reset_and_new_manager() -> None:
    from app._04_decision.manager import DecisionManager
    from app._04_decision.spells import mark_buff_cast, restore_buff_timers

    board = Blackboard()
    mark_buff_cast(board, "light")
    stamped = float(board.buff_last_cast["light"])
    board.reset()
    assert board.buff_last_cast.get("light") == stamped

    mgr = DecisionManager()
    restore_buff_timers(mgr.blackboard)
    assert float(mgr.blackboard.buff_last_cast.get("light") or 0.0) == stamped


def test_light_is_due_again_only_after_twelve_minutes(monkeypatch) -> None:
    monkeypatch.setattr(
        "app._04_decision.spells.slot_is_enabled",
        lambda name: name == "light",
    )
    board = Blackboard()
    board.buff_session_at = time.time() - 20.0
    assert due_buff(board) == "light"
    mark_buff_cast(board, "light")
    board.buff_last_cast["light"] = board.buff_last_cast["light"] - (LIGHT_REUSE_S - 30.0)
    assert due_buff(board) is None
    board.buff_last_cast["light"] = board.buff_last_cast["light"] - 40.0
    assert due_buff(board) == "light"
    assert LIGHT_REUSE_S == 12.0 * 60.0


def test_light_not_due_when_hotbar_cell_is_heal(monkeypatch) -> None:
    from types import SimpleNamespace

    from app._04_decision.spells import due_buff
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box(
        {"light": {"box": 1, "key": "f10", "enabled": True}}
    )
    monkeypatch.setattr(
        "app._04_decision.spells.slot_is_enabled",
        lambda name: name == "light",
    )
    board = Blackboard()
    board.buff_session_at = time.time() - 20.0
    state = SimpleNamespace(
        last_hotbar={"slots": [{"slot": 5, "name": "初級治癒術"}]}
    )
    try:
        assert due_buff(board, state) is None
    finally:
        configure_spell_box()
