"""S5 Game login — GameFlow bridge; AUTH cap synced with bot flags."""
from __future__ import annotations

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage


def _auth_max(bot, ctx: PipelineContext) -> int:
    cfg = getattr(bot, "cfg", None) or ctx.cfg or {}
    return int(cfg.get("auth_relaunch_max", 2) or 2)


def _auth_count(bot, ctx: PipelineContext) -> int:
    return int(getattr(bot, "_auth_relaunch_count", 0)
               or ctx.auth_relaunch_count or 0)


def _sync_auth_flags(bot, ctx: PipelineContext) -> None:
    n = _auth_count(bot, ctx)
    cap = _auth_max(bot, ctx)
    ctx.auth_relaunch_count = n
    # exhausted only — do not mark used after the first of two relaunches
    exhausted = n >= cap
    ctx.auth_relaunch_used = exhausted
    bot._auth_relaunch_count = n
    bot._auth_relaunch_used = exhausted


def _persist_shake_state(bot, ctx: PipelineContext) -> None:
    """Disk marker for controller process-restart of bot2."""
    if not (getattr(bot, "_shake_after_relaunch", False) or ctx.shake_armed):
        return
    try:
        from auth_relaunch_state import save_auth_relaunch_state
        save_auth_relaunch_state(bot)
    except Exception:
        pass


class GameLoginStage(Stage):
    id = "S5"

    def snapshot(self, ctx: PipelineContext):
        snap = {"stage_id": self.id}
        bot = ctx.bot
        _sync_auth_flags(bot, ctx)
        if getattr(bot, "_shake_after_relaunch", False):
            ctx.shake_armed = True

        on_top = getattr(bot, "_game_on_top", None)
        if callable(on_top):
            try:
                covered = not bool(on_top())
                snap["game_covered"] = covered
                ctx.extras["game_covered"] = covered
            except Exception:
                snap["game_covered"] = bool(ctx.extras.get("game_covered"))
        else:
            snap["game_covered"] = bool(ctx.extras.get("game_covered"))

        # Abort only when AUTH is still up AND relaunch budget is exhausted.
        snap["auth_choice"] = False
        snap["auth_relaunch_count"] = ctx.auth_relaunch_count
        snap["auth_relaunch_max"] = _auth_max(bot, ctx)
        flow = getattr(bot, "flow", None)
        if flow is not None:
            st = getattr(flow, "state", "") or ""
            snap["screen"] = st
            if st == "PURPLE_AUTH" and ctx.auth_relaunch_used:
                snap["auth_choice"] = True
            if st == "DEVICE_REG":
                snap["device_reg"] = True
            if getattr(flow, "error", None):
                snap["flow_error"] = str(flow.error)
        return snap

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        n = ctx.bump_retry(self.id)
        if n > self.goal.max_retries:
            return StageResult.failed(self.id, "game login retries exhausted")

        from base import Phase
        if getattr(bot, "phase", None) != Phase.GAME_LOGIN:
            if getattr(bot, "_set_phase", None):
                bot._set_phase(Phase.GAME_LOGIN)

        if ctx.shake_armed:
            bot._shake_after_relaunch = True
        _sync_auth_flags(bot, ctx)

        try:
            bot.tick()
        except Exception as e:
            return StageResult.failed(self.id, "tick error: %r" % e)

        _sync_auth_flags(bot, ctx)
        if getattr(bot, "_shake_after_relaunch", False):
            ctx.shake_armed = True

        if getattr(bot, "phase", None) == Phase.DONE:
            try:
                from auth_relaunch_state import clear_auth_relaunch_state
                clear_auth_relaunch_state(bot)
            except Exception:
                pass
            return StageResult.ok(self.id, "DONE")
        if getattr(bot, "phase", None) == Phase.ERROR:
            return StageResult.failed(self.id, "bot ERROR during game login")

        flow = getattr(bot, "flow", None)
        if flow is not None and getattr(flow, "error", None):
            return StageResult.failed(
                self.id, "GameFlow error: %s" % flow.error)

        if flow is not None and getattr(flow, "done", False):
            try:
                from auth_relaunch_state import clear_auth_relaunch_state
                clear_auth_relaunch_state(bot)
            except Exception:
                pass
            return StageResult.ok(self.id, "GameFlow done / INGAME")
        st = getattr(flow, "state", "") if flow else ""
        if st == "INGAME":
            try:
                from auth_relaunch_state import clear_auth_relaunch_state
                clear_auth_relaunch_state(bot)
            except Exception:
                pass
            return StageResult.ok(self.id, "INGAME")

        # GameFlow closed LC and set FIND_LINEAGE — jump Start
        if flow is None and getattr(bot, "phase", None) == Phase.FIND_LINEAGE:
            _sync_auth_flags(bot, ctx)
            ctx.shake_armed = True
            bot._shake_after_relaunch = True
            _persist_shake_state(bot, ctx)
            ctx.extras["request_game_relaunch"] = False
            return StageResult.handled(
                self.id, "GameFlow relaunched -> FIND_LINEAGE",
                next_stage_id="S3", screen=st)

        if flow is not None and getattr(flow, "restart_requested", False):
            # GameFlow._h_purple_auth already closed LC and called _restart().
            _sync_auth_flags(bot, ctx)
            ctx.shake_armed = True
            bot._shake_after_relaunch = True
            _persist_shake_state(bot, ctx)
            ctx.extras["request_game_relaunch"] = False
            try:
                flow.restart_requested = False
            except Exception:
                pass
            return StageResult.handled(
                self.id, "GameFlow AUTH close+relaunch [%s/%s] → S3" % (
                    ctx.auth_relaunch_count, _auth_max(bot, ctx)),
                next_stage_id="S3", screen=st)

        phase = getattr(bot, "phase", None)
        if phase in (Phase.FIND_LINEAGE, Phase.WAIT_GAME):
            _sync_auth_flags(bot, ctx)
            ctx.shake_armed = bool(
                getattr(bot, "_shake_after_relaunch", False)
                or ctx.shake_armed)
            if ctx.shake_armed:
                bot._shake_after_relaunch = True
                _persist_shake_state(bot, ctx)
            return StageResult.handled(
                self.id, "phase=%s after AUTH path" % phase.name,
                next_stage_id="S3")

        return StageResult.retry(
            self.id, "game login (%s)" % (st or "tick"),
            after=0.35, screen=st)
