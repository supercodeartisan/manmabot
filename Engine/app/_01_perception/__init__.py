"""Perception: memory sensors that feed the world apply layer.

Sensors write :class:`PerceptionBuffer`. ``_03_world`` fills ``_02_state``
types (via ``GameState``). Click geometry lives under ``app._05_action``.

Public API is :class:`PerceptionSensors` / :func:`shared_sensors` only.
Reader/monitor constructors stay in their modules for sensors internals.
"""
from __future__ import annotations

from app._01_perception.buffer import PerceptionBuffer
from app._01_perception.sensors import (
    PerceptionSensors,
    clear_shared_sensors,
    set_shared_sensors,
    shared_sensors,
)

__all__ = [
    "PerceptionBuffer",
    "PerceptionSensors",
    "clear_shared_sensors",
    "set_shared_sensors",
    "shared_sensors",
]
