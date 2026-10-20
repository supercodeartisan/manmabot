"""Party tactics — standalone formation, movement, and focus-fire logic.

Pure functions over tiles and small dataclasses. Nothing here reads memory,
sends input, or imports the decision / action layers, so each module can be
tested and wired in on its own.

- ``terrain_kind``  open field vs narrow dungeon around the leader
- ``radial``        open-field fan slots, sight-line slot repair, pace
- ``trail``         dungeon single-file trail, corner hold for the leader
- ``teleport_sync`` leader jump detection and staggered regroup plans
- ``focus_fire``    target allocation with overkill prevention
- ``stagger``       per-member attack delays inside one volley
"""
from __future__ import annotations

from .focus_fire import Shooter, Target, allocate_targets
from .radial import HURRY, KEEP, WAIT, clear_line, fan_slots, pace_for_slot, resolve_slot
from .stagger import stagger_delays
from .teleport_sync import (
    JumpEvent,
    Pose,
    RandomTeleportLoop,
    RegroupPlan,
    detect_leader_jump,
    plan_regroup,
)
from .terrain_kind import NARROW, OPEN, TerrainReading, classify_area
from .trail import HoldDecision, LeaderTrail, leader_hold

__all__ = [
    "HURRY",
    "KEEP",
    "NARROW",
    "OPEN",
    "WAIT",
    "HoldDecision",
    "JumpEvent",
    "LeaderTrail",
    "Pose",
    "RandomTeleportLoop",
    "RegroupPlan",
    "Shooter",
    "Target",
    "TerrainReading",
    "allocate_targets",
    "classify_area",
    "clear_line",
    "detect_leader_jump",
    "fan_slots",
    "leader_hold",
    "pace_for_slot",
    "plan_regroup",
    "resolve_slot",
    "stagger_delays",
]
