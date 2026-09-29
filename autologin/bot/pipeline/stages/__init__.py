"""Concrete stages — initially thin adapters over existing Bot APIs."""
from __future__ import annotations

from .base_stage import Stage
from .s0_preflight import PreflightStage
from .s1_window_gate import WindowGateStage
from .s2_purple_login import PurpleLoginStage
from .s3_start_game import StartGameStage
from .s4_focus import FocusStage
from .s5_game_login import GameLoginStage
from .s6_device_tag import DeviceTagStage
from .s7_done import DoneStage

DEFAULT_STAGE_ORDER = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7")


def build_default_stages() -> dict:
    stages = [
        PreflightStage(),
        WindowGateStage(),
        PurpleLoginStage(),
        StartGameStage(),
        FocusStage(),
        GameLoginStage(),
        DeviceTagStage(),
        DoneStage(),
    ]
    return {s.id: s for s in stages}


__all__ = [
    "Stage",
    "DEFAULT_STAGE_ORDER",
    "build_default_stages",
    "PreflightStage",
    "WindowGateStage",
    "PurpleLoginStage",
    "StartGameStage",
    "FocusStage",
    "GameLoginStage",
    "DeviceTagStage",
    "DoneStage",
]
