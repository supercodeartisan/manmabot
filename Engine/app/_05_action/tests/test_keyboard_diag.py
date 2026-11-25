"""Diagnostic lines around a key press do not change the down/up order."""
from __future__ import annotations

from app._05_action import keyboard as kb


def _patch(monkeypatch):
    calls: list[str] = []
    lines: list[str] = []

    monkeypatch.setattr(kb.ib, "ensure_open", lambda: calls.append("open"))
    monkeypatch.setattr(kb.ib, "key_down", lambda key: calls.append(f"down:{key}"))
    monkeypatch.setattr(kb.ib, "key_up", lambda key: calls.append(f"up:{key}"))
    monkeypatch.setattr(kb.ib, "expected_key_scan", lambda key: f"scan={key}")
    monkeypatch.setattr(kb.ib, "input_diag", lambda: "kind=test kb=0")

    def _event(channel, msg, *args):
        lines.append(args[0] if args else msg)

    monkeypatch.setattr("app.bot_log.event", _event)
    return calls, lines


def test_disabled_press_does_not_send(monkeypatch):
    calls, lines = _patch(monkeypatch)
    board = kb.KeyboardController(enabled=False, humanize=False)
    board.press("f4")
    assert calls == []
    assert any("request" in line and "enabled=0" in line and "key=f4" in line for line in lines)


def test_press_orders_down_then_up(monkeypatch):
    calls, lines = _patch(monkeypatch)
    board = kb.KeyboardController(enabled=True, humanize=False)
    board.press("f4", duration=0)
    assert calls == ["open", "down:f4", "up:f4"]
    text = "\n".join(lines)
    assert "key request" in text and "enabled=1" in text
    assert "key down" in text and "ok=1" in text and "kind=test kb=0" in text
    assert "key up" in text and "missing_down=0" in text
    assert text.index("key down") < text.index("key up")


def test_down_failure_does_not_send_up(monkeypatch):
    calls, lines = _patch(monkeypatch)

    def _boom(key):
        calls.append(f"down:{key}")
        raise RuntimeError("driver")

    monkeypatch.setattr(kb.ib, "key_down", _boom)
    board = kb.KeyboardController(enabled=True, humanize=False)
    try:
        board.press("f9", duration=0)
    except RuntimeError as exc:
        assert str(exc) == "driver"
    else:
        raise AssertionError("expected driver error")
    assert calls == ["open", "down:f9"]
    assert any("key down" in line and "ok=0" in line for line in lines)
    assert not any(line.startswith("key up") for line in lines)
