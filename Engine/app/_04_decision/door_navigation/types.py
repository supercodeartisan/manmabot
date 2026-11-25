"""Door-navigation types shared by the module and its callers."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DoorState(str, Enum):
    CLOSED = "close"
    OPEN = "open"
    UNKNOWN = "unknown"
    NOT_PERMITTED = "not_permitted"
    NOT_FOUND = "not_found"


class DoorNavStatus(str, Enum):
    """What the movement engine must do this tick."""

    NONE = "none"
    OPEN_NOW = "open_now"
    WAIT_OPEN = "wait_open"
    PASS_NOW = "pass_now"
    WAIT_CROSS = "wait_cross"
    CROSSED = "crossed"
    SEALED = "sealed"
    BLOCKED_BODY = "blocked_body"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    FAILED = "failed"


class DoorPhase(str, Enum):
    IDLE = "idle"
    OPENING = "opening"
    CROSSING = "crossing"
    RECOVERING = "recovering"


# Registry-aligned memory facts (LC930_REGISTRY.txt, 2026-10-29).
DOOR_STATE_OFF = 0xE0
DOOR_STATE_OPEN = 0x1C
DOOR_STATE_CLOSED = 0x1D
DOOR_GFX_OFF = 0x38
# 0x8009 is a common model id, not a lock. Sentinel never matches live gfx.
DOOR_GFX_LOCKED = 0xFFFFFFFF

UNKNOWN_WAIT_S = 2.0
OPEN_WAIT_S = 1.5
CROSS_WAIT_S = 2.5
MATCH_RADIUS = 1
MAX_OPEN_CLICKS = 2
MAX_PASS_CLICKS = 4
MAX_RECOVERIES = 3


@dataclass
class DoorRecord:
    """One live door in absolute nav tiles."""

    tile: tuple[int, int]
    state: DoorState
    world: tuple[int, int]
    ent: str = ""
    name: str = "Door"
    species: int = 8
    gfx: Optional[int] = None
    frame: Optional[int] = None


@dataclass
class DoorNavSession:
    """Per-character crossing state. Solo and party share one session each."""

    phase: DoorPhase = DoorPhase.IDLE
    door_tile: Optional[tuple[int, int]] = None
    door_ent: str = ""
    pass_tile: Optional[tuple[int, int]] = None
    opened_by_us: bool = False
    open_clicks: int = 0
    pass_clicks: int = 0
    recoveries: int = 0
    phase_since: float = 0.0
    last_state: DoorState = DoorState.NOT_FOUND
    last_player: Optional[tuple[int, int]] = None
    stuck_clicks: int = 0
    map_id: Optional[int] = None

    def clear(self) -> None:
        self.phase = DoorPhase.IDLE
        self.door_tile = None
        self.door_ent = ""
        self.pass_tile = None
        self.opened_by_us = False
        self.open_clicks = 0
        self.pass_clicks = 0
        self.recoveries = 0
        self.phase_since = 0.0
        self.last_state = DoorState.NOT_FOUND
        self.last_player = None
        self.stuck_clicks = 0


@dataclass
class DoorNavRequest:
    snapshot: Optional[dict[str, Any]]
    guide: list[tuple[int, int]]
    start: tuple[int, int]
    planned_click: Optional[tuple[int, int]]
    session: DoorNavSession
    now: float
    map_id: Optional[int] = None
    max_hop: Optional[int] = None
    event: str = "plan"
    """``plan`` (pick click), ``act`` (before mouse), ``note_open`` / ``note_pass``."""
    opened: Optional[bool] = None
    passed_pose: Optional[tuple[int, int]] = None


@dataclass
class DoorNavResult:
    status: DoorNavStatus
    door_tile: Optional[tuple[int, int]] = None
    pass_tile: Optional[tuple[int, int]] = None
    door_state: DoorState = DoorState.NOT_FOUND
    seal_tiles: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    reason: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    replace_click: bool = False
    """True when ``pass_tile`` / None replaces the planned hop click."""
