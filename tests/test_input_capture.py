"""Stop must free Interception devices so the next Start can click again."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app._05_action.mouse as mouse


@pytest.fixture(autouse=True)
def _reset_capture_flag() -> None:
    previous = mouse._captured
    yield
    mouse._captured = previous


class _FakeDevice:
    def __init__(self, handle: int) -> None:
        self.handle = handle

    def destroy(self) -> None:
        self.handle = -1


class _FakeContext:
    def __init__(self, *, handles: list[int] | None = None) -> None:
        values = handles if handles is not None else [1] * 20
        self.devices = [_FakeDevice(handle) for handle in values]
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True
        for device in self.devices:
            device.destroy()


def _patch_context(monkeypatch, bound: dict) -> None:
    monkeypatch.setattr(mouse, "_bind_inputs_context", lambda ctx: bound.__setitem__("ctx", ctx))
    monkeypatch.setattr(mouse, "_current_context", lambda: bound.get("ctx"))
    monkeypatch.setattr(mouse, "_REBIND_PAUSES_S", (0.0,))


def test_release_capture_frees_devices_without_reopen(monkeypatch) -> None:
    live = _FakeContext()
    bound = {"ctx": live}
    created: list[object] = []

    def _boom() -> object:
        created.append(object())
        raise AssertionError("release_capture must not reopen Interception")

    _patch_context(monkeypatch, bound)
    monkeypatch.setattr(mouse, "_open_context", _boom)
    mouse._captured = True

    mouse.release_capture()

    assert live.destroyed
    assert bound["ctx"] is None
    assert mouse._captured is False
    assert mouse.is_captured() is False
    assert created == []


def test_prepare_capture_reopens_after_stop(monkeypatch) -> None:
    bound: dict = {"ctx": None}
    opened: list[object] = []

    def _fresh() -> _FakeContext:
        ctx = _FakeContext()
        opened.append(ctx)
        return ctx

    fake_ix = SimpleNamespace(
        auto_capture_devices=lambda **_kwargs: opened.append("capture")
    )
    _patch_context(monkeypatch, bound)
    monkeypatch.setattr(mouse, "_open_context", _fresh)
    monkeypatch.setattr(mouse, "_get_interception", lambda: fake_ix)
    mouse._captured = False

    mouse.prepare_capture()

    assert mouse._captured is True
    assert mouse.is_captured() is True
    assert bound["ctx"] is opened[0]
    assert "capture" in opened


def test_ensure_captured_replaces_dead_context(monkeypatch) -> None:
    dead = _FakeContext(handles=[-1] * 20)
    bound = {"ctx": dead}
    opened: list[object] = []

    def _fresh() -> _FakeContext:
        ctx = _FakeContext()
        opened.append(ctx)
        return ctx

    fake_ix = SimpleNamespace(auto_capture_devices=lambda **_kwargs: None)
    _patch_context(monkeypatch, bound)
    monkeypatch.setattr(mouse, "_open_context", _fresh)
    monkeypatch.setattr(mouse, "_get_interception", lambda: fake_ix)
    mouse._captured = True

    mouse._ensure_captured()

    assert dead.destroyed
    assert bound["ctx"] is opened[0]
    assert mouse._captured is True


def test_drop_after_stop_does_not_recapture(monkeypatch) -> None:
    bound: dict = {"ctx": None}
    created: list[object] = []

    def _boom() -> object:
        created.append(object())
        raise AssertionError("drop_mouse after Stop must not reopen devices")

    _patch_context(monkeypatch, bound)
    monkeypatch.setattr(mouse, "_open_context", _boom)
    mouse._captured = False
    controller = mouse.MouseController(enabled=True, humanize=False)

    controller.release("left")

    assert created == []
    assert mouse._captured is False
