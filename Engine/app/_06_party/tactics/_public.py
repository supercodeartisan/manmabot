"""Party tactics — pure tile / allocation logic.

Nothing here reads memory, sends input, or imports the decision / action
layers, so each module can be tested and wired in on its own.

- ``terrain_kind``  open field vs narrow dungeon around the leader
- ``radial``        fan / ring slots, sight-line slot repair, pace
- ``trail``         single-file trail behind the leader, corner / lag hold
- ``focus_fire``    target allocation with overkill prevention (library only)

The session-facing compositions live one level up:
``turret_seat`` (radial ring) and ``formation`` (terrain kind + trail).
"""
from __future__ import annotations

from .focus_fire import Shooter, Target, allocate_targets
from .radial import HURRY, KEEP, WAIT, clear_line, fan_slots, pace_for_slot, resolve_slot
from .terrain_kind import NARROW, OPEN, TerrainReading, classify_area
from .trail import HoldDecision, LeaderTrail, leader_hold

__all__ = [
    "HURRY",
    "KEEP",
    "NARROW",
    "OPEN",
    "WAIT",
    "HoldDecision",
    "LeaderTrail",
    "Shooter",
    "Target",
    "TerrainReading",
    "allocate_targets",
    "classify_area",
    "clear_line",
    "fan_slots",
    "leader_hold",
    "pace_for_slot",
    "resolve_slot",
]
