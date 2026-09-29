from __future__ import annotations

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage


class DoneStage(Stage):
    id = "S7"

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        from base import Phase
        if getattr(bot, "phase", None) != Phase.DONE:
            if getattr(bot, "_set_phase", None):
                bot._set_phase(Phase.DONE)
        return StageResult.ok(self.id, "pipeline complete")
