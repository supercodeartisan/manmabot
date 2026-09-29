"""Stage goals — product success criteria per remodel phase.

These are the contract for each stage. Implementation can lag the goal text;
smoke tests and release gates should eventually assert the success_criteria.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class StageGoal:
    id: str
    title: str
    objective: str
    success_criteria: Tuple[str, ...]
    noise_gates: Tuple[str, ...]
    max_retries: int = 8


STAGE_GOALS: List[StageGoal] = [
    StageGoal(
        id="S0",
        title="Preflight",
        objective="Refuse unsupported environments before any click",
        success_criteria=(
            "Interception available (or explicit fallback allowed)",
            "DPI / resolution within support matrix (or warned)",
            "Account credentials present",
        ),
        noise_gates=("missing driver", "missing account"),
        max_retries=0,
    ),
    StageGoal(
        id="S1",
        title="Window gate",
        objective="Attach only to valid Purple main shell / real LC window",
        success_criteria=(
            "Purple main shell width >= 900 when acting on launcher",
            "Game window class GLFW30 (not GameGuard dummy)",
            "Never launch a second Purple while one is running",
        ),
        noise_gates=("popup 450x773", "hidden tiny shell", "GameGuard dummy"),
        max_retries=20,
    ),
    StageGoal(
        id="S2",
        title="Purple cold login",
        objective="Language-invariant credential entry without OCR locate",
        success_criteria=(
            "Clicks only after positive screen classify (email/password/launcher)",
            "Password never pasted while LOGIN_EMAIL is still showing",
            "Template locate first; saved ratios last-resort after confirm",
            "No runtime position_dict writes in operate mode",
            "Main launcher ready (logged in) before leaving stage",
        ),
        noise_gates=("logging-in splash", "wrong locale labels as click targets"),
        max_retries=15,
    ),
    StageGoal(
        id="S3",
        title="Start game",
        objective="Click Start only when launcher ready signals are met",
        success_criteria=(
            "Nav + card ready (template or OCR) before Start",
            "Start clicked only on START_READY (运行游戏 visible)",
            "LC process appears within budget",
            "No blind Start retry loops beyond max_retries",
        ),
        noise_gates=("toast / profile banner", "card grid not settled"),
        max_retries=100,
    ),
    StageGoal(
        id="S4",
        title="Focus / uncover",
        objective="Ensure game receives input; Purple does not cover center",
        success_criteria=(
            "Game topmost or foreground after launch",
            "Purple minimized or moved when covering",
        ),
        noise_gates=("Purple HwndWrapper over game"),
        max_retries=60,
    ),
    StageGoal(
        id="S5",
        title="Game login",
        objective="Fixed/ratio game flow with bounded AUTH safety net",
        success_criteria=(
            "agree -> page -> server -> ok_right -> char -> INGAME",
            "퍼플간편인증 alone: close+relaunch (max 2/session); "
            "shake once after post-restart normalize + screen change",
            "OCR used for detect/verify only, not primary click locate",
        ),
        noise_gates=("AUTH_CHOICE", "DEVICE_REG", "security splash", "popups"),
        max_retries=30,
    ),
    StageGoal(
        id="S6",
        title="deviceTag persist",
        objective="Poll and backup deviceTag after INGAME for next runs",
        success_criteria=(
            "Non-empty tag written to backup when available",
            "Restore before next cold/hot session when live empty",
            "Never block the 5s character-handoff to the farm bot",
        ),
        noise_gates=("empty tag at launcher-only time"),
        max_retries=0,
    ),
    StageGoal(
        id="S7",
        title="Done / release gate",
        objective="Mark success only on INGAME + clean shutdown hooks",
        success_criteria=(
            "Phase DONE after INGAME",
            "No unbounded restart loops",
        ),
        noise_gates=(),
        max_retries=0,
    ),
]


def goal_by_id(stage_id: str) -> StageGoal:
    for g in STAGE_GOALS:
        if g.id == stage_id:
            return g
    raise KeyError(stage_id)
