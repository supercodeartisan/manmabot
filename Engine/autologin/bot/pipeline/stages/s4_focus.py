"""S4 Focus — wait for real hwnd, minimize Purple, verify game on top."""
from __future__ import annotations

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage


class FocusStage(Stage):
    id = "S4"

    def snapshot(self, ctx: PipelineContext):
        snap = {"stage_id": self.id}
        bot = ctx.bot
        covered = False
        ready = getattr(bot, "_game_window_ready", None)
        hwnd_ok = False
        if callable(ready):
            try:
                hwnd_ok = bool(ready())
            except Exception:
                hwnd_ok = False
        game = getattr(bot, "game", None) if bot else None
        if hwnd_ok and game is not None:
            on_top = getattr(bot, "_game_on_top", None)
            if callable(on_top):
                try:
                    covered = not bool(on_top())
                except Exception:
                    covered = bool(ctx.extras.get("game_covered"))
        snap["game_covered"] = covered
        snap["hwnd_ready"] = hwnd_ok
        ctx.extras["game_covered"] = covered
        return snap

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        from base import Phase

        ready_fn = getattr(bot, "_game_window_ready", None)

        def hwnd_ready() -> bool:
            if callable(ready_fn):
                try:
                    return bool(ready_fn())
                except Exception:
                    return False
            g = getattr(bot, "game", None)
            return bool(g is not None and getattr(g, "valid", False))

        if not hwnd_ready():
            phase = getattr(bot, "phase", None)
            alive = getattr(bot, "_game_process_alive", lambda: False)()
            if phase == Phase.WAIT_GAME or alive or phase == Phase.GAME_LOGIN:
                try:
                    bot.tick()
                except Exception as e:
                    return StageResult.retry(
                        self.id, "WAIT_GAME tick error: %r" % e, after=0.5)
                if hwnd_ready():
                    pass
                else:
                    n = ctx.bump_retry(self.id)
                    if n > self.goal.max_retries:
                        return StageResult.failed(
                            self.id,
                            "game window never appeared for focus "
                            "(process alive=%s)" % alive)
                    return StageResult.blocked(
                        self.id,
                        "waiting for real GLFW game hwnd",
                        after=0.8)
            else:
                find = getattr(bot, "find_game", None)
                if callable(find):
                    find()
                n = ctx.bump_retry(self.id)
                if n > self.goal.max_retries:
                    return StageResult.failed(
                        self.id, "game window never appeared for focus")
                return StageResult.blocked(
                    self.id, "game window not ready", after=0.5)

        if getattr(bot, "phase", None) == Phase.WAIT_GAME:
            if getattr(bot, "_set_phase", None):
                bot._set_phase(Phase.GAME_LOGIN)

        # Minimize Purple + raise game + verify (retry loop inside helper).
        prepare = getattr(bot, "_prepare_game_foreground", None)
        if callable(prepare):
            try:
                if prepare(attempts=5):
                    ctx.extras["game_covered"] = False
                    return StageResult.ok(
                        self.id, "Purple minimized; game on top (verified)")
            except Exception as e:
                return StageResult.retry(
                    self.id, "prepare foreground failed: %r" % e, after=0.4)
            # Not verified — stay on S4 while process/window still exist
            n = ctx.bump_retry(self.id + ":focus")
            if n > 12:
                # Soft pass: hwnd exists; GameFlow will keep re-asserting topmost
                ctx.extras["game_covered"] = True
                return StageResult.ok(
                    self.id,
                    "hwnd ready but on-top unverified — continue to S5",
                    focus_soft=True)
            ctx.extras["game_covered"] = True
            return StageResult.blocked(
                self.id, "game still covered — retry minimize/on-top",
                after=0.5)

        # Fallback path without helper
        mini = getattr(bot, "_minimize_purple_for_game", None)
        if callable(mini):
            try:
                mini()
            except Exception:
                pass
        ensure = getattr(bot, "_ensure_game_on_top", None)
        if callable(ensure) and ensure():
            ctx.extras["game_covered"] = False
            return StageResult.ok(self.id, "game on top (ensure fallback)")

        ctx.extras["game_covered"] = True
        return StageResult.blocked(
            self.id, "focus fallback failed", after=0.5)
