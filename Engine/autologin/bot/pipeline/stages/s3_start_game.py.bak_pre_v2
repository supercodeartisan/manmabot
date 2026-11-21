"""S3 Start Game — process alone is not success; need real LC hwnd."""
from __future__ import annotations

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage


class StartGameStage(Stage):
    id = "S3"

    def snapshot(self, ctx: PipelineContext):
        snap = {"stage_id": self.id}
        bot = ctx.bot
        if bot and getattr(bot, "purple", None) and bot.purple.valid:
            from .s1_window_gate import purple_unusable
            snap["purple_too_small"] = purple_unusable(
                bot.purple.rect.width, bot.purple.rect.height)
            probe = getattr(bot, "has_launcher_toast", None)
            if callable(probe):
                try:
                    toast = bool(probe())
                    snap["launcher_toast"] = toast
                    ctx.extras["launcher_toast"] = toast
                except Exception:
                    snap["launcher_toast"] = bool(
                        ctx.extras.get("launcher_toast"))
            else:
                snap["launcher_toast"] = bool(
                    ctx.extras.get("launcher_toast"))
            stall = getattr(bot, "_purple_fixed_stalled", None)
            if callable(stall):
                try:
                    snap["purple_fixed_stalled"] = bool(stall())
                except Exception:
                    pass
            watch = getattr(bot, "_read_purple_view", None)
            if callable(watch):
                try:
                    view = watch()
                    snap["purple_screen"] = getattr(
                        getattr(view, "screen", None), "value", "")
                    snap["login_form"] = snap["purple_screen"] in (
                        "login_email", "login_password")
                except Exception:
                    pass
        else:
            snap["launcher_toast"] = bool(ctx.extras.get("launcher_toast"))
        if ctx.extras.get("request_game_relaunch"):
            snap["relaunch_requested"] = True
        return snap

    def _hwnd_ready(self, bot) -> bool:
        ready = getattr(bot, "_game_window_ready", None)
        if callable(ready):
            try:
                return bool(ready())
            except Exception:
                pass
        game = getattr(bot, "game", None)
        return bool(game is not None and getattr(game, "valid", False))

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        from base import Phase

        if ctx.extras.get("request_game_relaunch"):
            ctx.extras.pop("request_game_relaunch", None)
            try:
                if getattr(bot, "_game_process_alive", lambda: False)():
                    closer = getattr(bot, "_close_game", None)
                    if callable(closer):
                        closer(wait=1.5)
                restart = getattr(bot, "_restart", None)
                if callable(restart):
                    restart()
            except Exception as e:
                return StageResult.failed(
                    self.id, "relaunch after AUTH failed: %r" % e)
            if ctx.shake_armed:
                bot._shake_after_relaunch = True
                try:
                    from auth_relaunch_state import save_auth_relaunch_state
                    save_auth_relaunch_state(bot)
                except Exception:
                    pass
            return StageResult.retry(
                self.id, "AUTH relaunch -> FIND_LINEAGE", after=1.0)

        phase = getattr(bot, "phase", None)
        # Gate: real hwnd required (process-only is NOT enough).
        if phase == Phase.GAME_LOGIN and self._hwnd_ready(bot):
            return StageResult.ok(self.id, "GAME_LOGIN + real hwnd")
        if self._hwnd_ready(bot) and phase in (
                Phase.GAME_LOGIN, Phase.WAIT_GAME, Phase.FIND_LINEAGE):
            if phase != Phase.GAME_LOGIN and getattr(bot, "_set_phase", None):
                bot._set_phase(Phase.GAME_LOGIN)
            return StageResult.ok(self.id, "real game hwnd attached")

        n = ctx.bump_retry(self.id)
        if n > self.goal.max_retries:
            return StageResult.failed(self.id, "Start Game retries exhausted")

        if phase not in (Phase.FIND_LINEAGE, Phase.WAIT_GAME, Phase.GAME_LOGIN):
            if getattr(bot, "_set_phase", None):
                bot._set_phase(Phase.FIND_LINEAGE)

        try:
            bot._maybe_fallback_purple_dynamic(reason="s3")
        except Exception:
            pass
        try:
            bot.tick()
        except Exception as e:
            return StageResult.failed(self.id, "tick error: %r" % e)

        phase = getattr(bot, "phase", None)
        if phase == Phase.GAME_LOGIN and self._hwnd_ready(bot):
            return StageResult.ok(self.id, "entered GAME_LOGIN")
        if self._hwnd_ready(bot):
            return StageResult.ok(self.id, "game window attached")
        if phase == Phase.WAIT_GAME or getattr(
                bot, "_game_process_alive", lambda: False)():
            return StageResult.retry(
                self.id, "WAIT_GAME — waiting for real game hwnd", after=0.6)
        if phase == Phase.ERROR:
            return StageResult.failed(self.id, "bot entered ERROR during Start")
        return StageResult.retry(
            self.id, "waiting for LC / Start ready",
            after=0.5, phase=getattr(phase, "name", ""))
