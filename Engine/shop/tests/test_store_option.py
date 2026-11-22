"""Warehouse deposit-line click. No LC, no mouse driver."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shop import runtime  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


def _bind_clock(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime.time, "time", clock.time)
    monkeypatch.setattr(runtime.time, "sleep", clock.sleep)


def test_store_option_nudges_until_deposit(monkeypatch):
    clicks: list[float] = []

    def click(executor, bounds, uv, *, dy_px):
        del executor, bounds, uv
        clicks.append(float(dy_px))

    def capture():
        if len(clicks) >= 2:
            return {"open": 1, "mode": "deposit"}
        return {"open": 0, "mode": "closed"}

    _bind_clock(monkeypatch)
    monkeypatch.setattr(runtime, "_click_store_option_exact", click)
    monkeypatch.setattr(runtime, "_log_store_option", lambda *a, **k: None)
    monkeypatch.setattr(
        "app._01_perception.storewin_reader.capture_store", capture
    )

    opened = runtime.open_store_deposit_tab(SimpleNamespace(), SimpleNamespace(), (0.1, 0.2))
    assert opened == "deposit"
    assert clicks == [0.0, 4.0]


def test_store_option_stops_on_retrieve(monkeypatch):
    clicks: list[float] = []

    def click(executor, bounds, uv, *, dy_px):
        del executor, bounds, uv
        clicks.append(float(dy_px))

    def capture():
        if clicks:
            return {"open": 1, "mode": "retrieve"}
        return {"open": 0, "mode": "closed"}

    _bind_clock(monkeypatch)
    monkeypatch.setattr(runtime, "_click_store_option_exact", click)
    monkeypatch.setattr(runtime, "_log_store_option", lambda *a, **k: None)
    monkeypatch.setattr(
        "app._01_perception.storewin_reader.capture_store", capture
    )

    opened = runtime.open_store_deposit_tab(SimpleNamespace(), SimpleNamespace(), (0.1, 0.2))
    assert opened == "retrieve"
    assert clicks == [0.0]


def test_store_deposit_ready_rejects_retrieve():
    assert runtime.store_deposit_ready({"open": 1, "mode": "deposit"}) is True
    assert runtime.store_deposit_ready({"open": 1}) is True
    assert runtime.store_deposit_ready({"open": 1, "mode": "retrieve"}) is False
    assert runtime.store_deposit_ready({"open": 0, "mode": "closed"}) is False
    assert runtime.store_list_is_retrieve({"open": 1, "mode": "retrieve"}) is True
