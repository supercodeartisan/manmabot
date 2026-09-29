"""Sequence composite: all children must succeed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .node import Node
from .status import Status

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


class Sequence(Node):
    """Run children in order; first FAILURE or RUNNING stops the sequence.

    All children must return SUCCESS for the sequence to succeed.
    """

    def __init__(self, children: list[Node], name: str = "sequence") -> None:
        super().__init__(name)
        self.children = children
        self.last_status: Status | None = None

    def tick(self, state: "GameState", blackboard: "Blackboard") -> Status:
        for child in self.children:
            status = child.tick(state, blackboard)
            if status is Status.FAILURE:
                self.last_status = status
                return status
            if status is Status.RUNNING:
                self.last_status = status
                return status
        self.last_status = Status.SUCCESS
        return Status.SUCCESS


__all__ = ["Sequence"]
