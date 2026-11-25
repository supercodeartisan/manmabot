"""HP idle log keeps its gate and 2s clock, and appends MP text."""
from __future__ import annotations

from types import SimpleNamespace

from app._04_decision.behaviors.mode_actions import _log_hp_idle, _mp_idle_text
from app._04_decision.blackboard import Blackboard


def _board() -> Blackboard:
    return Blackboard()


def _state(*, mp=18, max_mp=45):
    return SimpleNamespace(player=SimpleNamespace(mp=mp, max_mp=max_mp))


def _actions():
    return [{"id": "heal", "enabled": True, "hp_below": 0.70}]


def test_mp_idle_text_pair_and_unknown():
    assert _mp_idle_text(_state()) == "18/45 (0.40)"
    assert _mp_idle_text(_state(mp=0, max_mp=45)) == "0/45 (0.00)"
    assert _mp_idle_text(_state(mp=None, max_mp=45)) == "?"
    assert _mp_idle_text(_state(mp=18, max_mp=None)) == "?"
    assert _mp_idle_text(_state(mp=18, max_mp=0)) == "?"
    assert _mp_idle_text(SimpleNamespace(player=None)) == "?"
    assert _mp_idle_text(SimpleNamespace(player=SimpleNamespace(mp="x", max_mp=45))) == "?"


def test_idle_log_appends_mp_on_the_same_clock(monkeypatch):
    lines: list[str] = []

    class _Log:
        def info(self, msg, *args):
            lines.append(msg % args)

    monkeypatch.setattr(
        "app.bot_log.get_logger", lambda channel="": _Log()
    )
    board = _board()
    can = {"heal": True, "retreat": False}
    _log_hp_idle(board, _state(), 0.67, can, _actions())
    _log_hp_idle(board, _state(mp=10), 0.60, can, _actions())
    assert lines == ["hp idle ratio=0.67 mp=18/45 (0.40) can=heal"]
    assert "hp_idle_log_at" in board.scratch


def test_idle_log_stays_quiet_above_the_gate(monkeypatch):
    lines: list[str] = []

    class _Log:
        def info(self, msg, *args):
            lines.append(msg % args)

    monkeypatch.setattr(
        "app.bot_log.get_logger", lambda channel="": _Log()
    )
    board = _board()
    _log_hp_idle(board, _state(), 0.90, {"heal": True}, _actions())
    assert lines == []
    assert "hp_idle_log_at" not in board.scratch
