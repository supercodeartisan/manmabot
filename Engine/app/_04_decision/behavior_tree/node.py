"""Behavior tree node primitives."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .status import Status

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


class Node:
    """Base class for all behavior tree nodes.

    A node reads the game state and blackboard and returns a
    :class:`Status`. It never touches the game directly; decisions are
    emitted through the blackboard's ``intent``.
    """

    name: str = "node"

    def __init__(self, name: str | None = None) -> None:
        if name is not None:
            self.name = name

    def tick(self, state: "GameState", blackboard: "Blackboard") -> Status:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{type(self).__name__} {self.name}>"


class ConditionNode(Node):
    """Leaf that succeeds or fails based on a predicate."""

    def __init__(
        self,
        predicate: Callable[["GameState", "Blackboard"], bool],
        name: str = "condition",
    ) -> None:
        super().__init__(name)
        self.predicate = predicate

    def tick(self, state: "GameState", blackboard: "Blackboard") -> Status:
        return Status.SUCCESS if self.predicate(state, blackboard) else Status.FAILURE


class ActionNode(Node):
    """Leaf that performs an action and returns its resulting status."""

    def __init__(
        self,
        action: Callable[["GameState", "Blackboard"], Status],
        name: str = "action",
    ) -> None:
        super().__init__(name)
        self.action = action

    def tick(self, state: "GameState", blackboard: "Blackboard") -> Status:
        return self.action(state, blackboard)


__all__ = ["Node", "ConditionNode", "ActionNode"]
