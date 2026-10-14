"""Memory and action state types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import ActionType
from .objects import Position, WorldObject


@dataclass
class MemoryState:
    """Persistent memory across decision ticks."""
    action_type: ActionType = ActionType.IDLE
    enemy: WorldObject | None = None
    item: WorldObject | None = None
    position: Position = field(default_factory=lambda: Position(x=0.0, y=0.0))
    last_direction: Position = field(default_factory=lambda: Position(x=0.0, y=0.0))


@dataclass
class ActionState:
    """Current action with targets and destinations."""
    action_type: ActionType = ActionType.IDLE
    enemy_target: WorldObject | None = None
    item_target: WorldObject | None = None
    destination: Position = field(default_factory=lambda: Position(x=0.0, y=0.0))
    region_destination: Position = field(default_factory=lambda: Position(x=0.0, y=0.0))
    minimap_destination: Position = field(default_factory=lambda: Position(x=0.0, y=0.0))
    mid_act: bool = False