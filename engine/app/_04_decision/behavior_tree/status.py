"""Behavior tree node statuses."""
from __future__ import annotations

from enum import Enum


class Status(Enum):
    """Result of ticking a behavior tree node.

    SUCCESS  - the node's goal was fulfilled this tick.
    FAILURE  - the node could not fulfill its goal (try the next sibling).
    RUNNING  - the node is in progress and will continue next tick.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


__all__ = ["Status"]
