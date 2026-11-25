"""Public status and context types for the party shop module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ShopStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ShopResult:
    status: ShopStatus
    intent: Any = None
    reason: str = ""
    phase: str = "follow"
    publish: Optional[dict[str, Any]] = None


@dataclass
class ShopContext:
    """Host-provided view for one shop-module tick. No manager import cycles."""

    state: Any = None
    blackboard: Any = None
    runtime: Any = None
    manager: Any = None
    config: Any = None
    self_name: str = ""
    self_guid: str = ""
    roster: Any = None
    role: str = "member"  # keeper | recipient | leader | member
    leaving: bool = False
    origin: Any = None
    map_id: Any = None
    hold: Any = None
    claim: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = ["ShopContext", "ShopResult", "ShopStatus"]
