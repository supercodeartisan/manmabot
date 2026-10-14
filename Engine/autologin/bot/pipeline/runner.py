"""Runs stages in order; dispatches exception rules each tick."""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Sequence

from .context import PipelineContext
from .exceptions_reg import ExceptionRegistry, build_default_registry
from .goals import STAGE_GOALS, StageGoal
from .result import StageResult, StageStatus
from .stages import DEFAULT_STAGE_ORDER, Stage, build_default_stages

log = logging.getLogger("pipeline")


class PipelineRunner:
    def __init__(self, ctx: PipelineContext,
                 stages: Optional[Dict[str, Stage]] = None,
                 order: Optional[Sequence[str]] = None,
                 registry: Optional[ExceptionRegistry] = None):
        self.ctx = ctx
        self.stages = stages or build_default_stages()
        self.order: List[str] = list(order or DEFAULT_STAGE_ORDER)
        self.registry = registry or build_default_registry()
        self.index = 0
        self.last_result: Optional[StageResult] = None
        self.finished = False
        self.failed = False

    @property
    def current_id(self) -> Optional[str]:
        if self.index < 0 or self.index >= len(self.order):
            return None
        return self.order[self.index]

    def goal(self, stage_id: str) -> StageGoal:
        for g in STAGE_GOALS:
            if g.id == stage_id:
                return g
        raise KeyError(stage_id)

    def tick(self) -> StageResult:
        if self.finished or self.failed:
            sid = self.current_id or "S7"
            st = StageStatus.FAILED if self.failed else StageStatus.OK
            return StageResult(st, sid, "pipeline already stopped")

        sid = self.current_id
        if sid is None:
            self.finished = True
            return StageResult.ok("S7", "no more stages")

        stage = self.stages[sid]
        snap = stage.snapshot(self.ctx)
        snap["stage_id"] = sid

        handled = self.registry.dispatch(self.ctx, sid, snap)
        if handled is not None:
            self.last_result = handled
            self._apply(handled)
            return handled

        result = stage.run(self.ctx)
        self.last_result = result
        self._apply(result)
        return result

    def _apply(self, result: StageResult) -> None:
        log.info("pipeline %s -> %s: %s",
                 result.stage_id, result.status.name, result.message)
        if result.retry_after_sec > 0 and result.status in (
                StageStatus.RETRY, StageStatus.BLOCKED):
            time.sleep(result.retry_after_sec)

        if result.status == StageStatus.FAILED:
            self.failed = True
            return
        if result.status == StageStatus.OK or result.status == StageStatus.SKIP:
            self._advance(result.next_stage_id)
            return
        if result.status == StageStatus.HANDLED:
            if result.next_stage_id:
                self._jump(result.next_stage_id)
            return
        # RETRY / BLOCKED: stay on stage

    def _advance(self, override: Optional[str] = None) -> None:
        if override:
            self._jump(override)
            return
        self.index += 1
        if self.index >= len(self.order):
            self.finished = True

    def _jump(self, stage_id: str) -> None:
        if stage_id not in self.order:
            log.warning("jump to unknown stage %s — ignore", stage_id)
            return
        target = self.order.index(stage_id)
        if target <= self.index:
            # A bounded recovery path is a fresh attempt through these stages.
            # Separate recovery caps (for example AUTH relaunch count) remain
            # in the context and still prevent an infinite loop.
            for sid in self.order[target:self.index + 1]:
                self.ctx.retries.pop(sid, None)
        self.index = target
