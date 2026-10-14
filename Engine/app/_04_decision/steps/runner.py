"""Run a named step column (first Status wins)."""
from __future__ import annotations

from typing import Any, Callable, Optional

from app._04_decision.behavior_tree import Status

StepFn = Callable[[Any, Any], Optional[Status]]


def run_column(
    step_ids: tuple[str, ...],
    handlers: dict[str, StepFn],
    state: Any,
    blackboard: Any,
    *,
    require_terminal: bool = True,
    scratch_key: str = "winning_step",
) -> Optional[Status]:
    """Execute handlers in order. ``None`` from a step means continue.

    When a step returns a ``Status``, it wins the tick: optional scratch
    records the step id for debug / change-log addresses.
    """
    for step_id in step_ids:
        fn = handlers.get(step_id)
        if fn is None:
            raise KeyError(f"no handler for step {step_id!r}")
        result = fn(state, blackboard)
        if result is None:
            continue
        try:
            blackboard.scratch[scratch_key] = step_id
        except Exception:
            pass
        return result
    if require_terminal:
        try:
            blackboard.scratch[scratch_key] = None
        except Exception:
            pass
        return Status.FAILURE
    return None


__all__ = ["StepFn", "run_column"]
