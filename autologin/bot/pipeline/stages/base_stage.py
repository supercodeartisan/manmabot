"""Stage protocol and shared helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..goals import StageGoal, goal_by_id
from ..context import PipelineContext
from ..result import StageResult


class Stage(ABC):
    id: str

    @property
    def goal(self) -> StageGoal:
        return goal_by_id(self.id)

    def snapshot(self, ctx: PipelineContext) -> Dict[str, Any]:
        """Lightweight observations for exception matching. Override per stage."""
        return {"stage_id": self.id}

    @abstractmethod
    def run(self, ctx: PipelineContext) -> StageResult:
        ...
