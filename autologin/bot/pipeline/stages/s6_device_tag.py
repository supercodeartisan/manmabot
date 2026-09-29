"""S6 deviceTag persist — one shot; never delay the farm-bot hand-off."""
from __future__ import annotations

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage


class DeviceTagStage(Stage):
    id = "S6"

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        try:
            from devicetag import (
                backup_device_tag, read_device_tag, restore_device_tag,
            )
        except ImportError:
            from bot.devicetag import (
                backup_device_tag, read_device_tag, restore_device_tag,
            )

        base = getattr(bot, "session_backup_dir", None)
        # World-load wait already happened in S5 (CHAR_HANDOFF_SECONDS).
        # Do not poll here — Manmabot must start immediately after that.
        tag = ""
        try:
            tag = read_device_tag() or ""
        except Exception:
            tag = ""
        if tag:
            written = backup_device_tag(base)
            ctx.extras["device_tag_len"] = len(tag)
            return StageResult.ok(
                self.id, "deviceTag backed up",
                tag_len=len(tag), backed_up=bool(written))

        try:
            restored = restore_device_tag(base)
        except Exception:
            restored = ""
        if restored:
            ctx.extras["device_tag_restored"] = True
            return StageResult.ok(
                self.id, "live empty; previous backup retained/restored",
                tag_len=len(restored), restored=True)

        return StageResult.ok(
            self.id, "deviceTag still empty — continue to farm bot",
            tag_empty=True)
