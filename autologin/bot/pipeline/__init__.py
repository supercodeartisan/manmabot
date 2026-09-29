"""Login pipeline: staged goals, pluggable exception handlers.

Design (product constraints):
  - fully automatic (no human in the hot path)
  - minimize time-to-INGAME
  - always gate noise (wrong window / toast / unknown screen)

Stages are thin wrappers around existing bot/gameflow logic at first.
New UI variants are added as ExceptionRule entries without rewriting the
whole state machine.
"""
from .context import PipelineContext
from .exceptions_reg import ExceptionRegistry, ExceptionRule
from .goals import STAGE_GOALS, StageGoal
from .result import StageResult, StageStatus
from .runner import PipelineRunner

__all__ = [
    "PipelineContext",
    "PipelineRunner",
    "StageResult",
    "StageStatus",
    "ExceptionRegistry",
    "ExceptionRule",
    "STAGE_GOALS",
    "StageGoal",
]
