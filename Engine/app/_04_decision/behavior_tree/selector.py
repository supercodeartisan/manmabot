"""Selector composite: first succeeding child wins."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .node import Node
from .status import Status

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


class Selector(Node):
    """Run children in order until one returns SUCCESS or RUNNING.

    Used for priority selection: the first child that reports it handled
    the tick stops the selector. FAILURE on a child means "not applicable,
    try the next priority".
    """

    def __init__(self, children: list[Node], name: str = "selector") -> None:
        super().__init__(name)
        self.children = children
        self.last_status: Status | None = None

    def tick(self, state: "GameState", blackboard: "Blackboard") -> Status:
        for child in self.children:
            status = child.tick(state, blackboard)
            if status is Status.RUNNING:
                self.last_status = status
                return status
            if status is Status.SUCCESS:
                self.last_status = status
                return status
        self.last_status = Status.FAILURE
        return Status.FAILURE


__all__ = ["Selector"]
