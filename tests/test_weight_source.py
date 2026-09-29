"""Bag fill comes from memory weight/maxWeight, not HUD OCR."""
from __future__ import annotations

from types import SimpleNamespace

from app._02_vision.weight_hud import WeightReading, apply_weight_reading
from app._03_world.objects import Position
from app._03_world.player import InventoryState, PlayerState, memory_weight_ready


def _player(*, max_weight: float, ratio: float = 0.2) -> PlayerState:
    return PlayerState(
        track_id=0,
        position=Position.zero(),
        weight=200.0,
        max_weight=max_weight,
        inventory=InventoryState(weight_ratio=ratio),
    )


def test_memory_weight_ready_requires_max_weight() -> None:
    assert memory_weight_ready(_player(max_weight=1000.0)) is True
    assert memory_weight_ready(_player(max_weight=0.0)) is False
    assert memory_weight_ready(None) is False


def test_hud_does_not_overwrite_memory_weight() -> None:
    player = _player(max_weight=1000.0, ratio=0.2)
    reading = WeightReading(raw="55", percent=55, confidence=0.99)
    assert apply_weight_reading(SimpleNamespace(player=player), reading) is False
    assert player.inventory.weight_ratio == 0.2


def test_hud_fills_weight_when_memory_has_no_max() -> None:
    player = _player(max_weight=0.0, ratio=0.0)
    reading = WeightReading(raw="55", percent=55, confidence=0.99)
    assert apply_weight_reading(SimpleNamespace(player=player), reading) is True
    assert player.inventory.weight_ratio == 0.55
