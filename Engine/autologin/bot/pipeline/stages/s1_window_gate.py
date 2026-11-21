"""S1 Window gate — attach / restore / single launch; never dual Purple."""
from __future__ import annotations

import time

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage

_MIN_SHELL_W = 900
# Email/password card is a portrait window (~450x773). That is S2, not a
# "wrong" popup. Only splash / toast shells below this are unusable.
_MIN_LOGIN_W = 300
_MIN_LOGIN_H = 400


def purple_unusable(width: int, height: int = 0) -> bool:
    """True for splash/toast shells that cannot host login or the main UI."""
    return int(width or 0) < _MIN_LOGIN_W or int(height or 0) < _MIN_LOGIN_H


class WindowGateStage(Stage):
    id = "S1"

    def snapshot(self, ctx: PipelineContext):
        snap = {"stage_id": self.id}
        bot = ctx.bot
        purple = getattr(bot, "purple", None) if bot else None
        if purple is not None and getattr(purple, "valid", False):
            w = purple.rect.width
            h = purple.rect.height
            snap["purple_w"] = w
            snap["purple_h"] = h
            # Missing must not trip wrong_purple_window (blocked launch).
            # Login cards are usable even when narrower than the main shell.
            snap["purple_too_small"] = purple_unusable(w, h)
            snap["purple_missing"] = False
        else:
            snap["purple_missing"] = True
            snap["purple_too_small"] = False
        return snap

    def _ok_attached(self, ctx: PipelineContext, bot) -> StageResult:
        w = bot.purple.rect.width
        h = bot.purple.rect.height
        ctx.purple_logged_in = bool(getattr(bot, "_purple_logged_in", False))
        kind = "main shell" if w >= _MIN_SHELL_W else "login card"
        return StageResult.ok(
            self.id, "attached Purple %dx%d (%s)" % (w, h, kind), width=w)

    def _hwnd_ready(self, bot) -> bool:
        ready = getattr(bot, "_game_window_ready", None)
        if callable(ready):
            try:
                return bool(ready())
            except Exception:
                pass
        game = getattr(bot, "game", None)
        return bool(game is not None and getattr(game, "valid", False))

    def _shake_armed(self, ctx: PipelineContext, bot) -> bool:
        return bool(
            getattr(bot, "_shake_after_relaunch", False) or ctx.shake_armed)

    def _keep_shake_armed(self, ctx: PipelineContext, bot) -> None:
        """AUTH relaunch marker must survive Purple handoff into S5."""
        bot._shake_after_relaunch = True
        ctx.shake_armed = True

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        # v2 engine: run the whole Purple path (launch -> login -> game card
        # -> Play -> game-ready) here, then hand off to S4. No legacy
        # fallback — if the engine fails, the pipeline fails loudly.
        try:
            from purple.facade import engine_enabled, ensure_launched, run_v2_engine
        except Exception:
            engine_enabled = None
        if engine_enabled is not None and engine_enabled(ctx.cfg or {}):
            try:
                shake = self._shake_armed(ctx, bot)
                # After AUTH close+relaunch the boot-status UI is already
                # racing. If GLFW is up, skip a full Purple login cycle and
                # hand off so S5 can hunt/shake immediately.
                if shake and self._hwnd_ready(bot):
                    from purple.handoff import apply_handoff
                    apply_handoff(bot, ctx, engine=None)
                    self._keep_shake_armed(ctx, bot)
                    return StageResult.ok(
                        self.id, "AUTH relaunch: existing game hwnd → S5")
                if not ensure_launched(bot):
                    return StageResult.failed(
                        self.id, "v2: Purple launch/attach failed")
                from purple.handoff import engine_succeeded
                # AUTH relaunch only needs Play→hwnd, not a long post-ready wait.
                eng = run_v2_engine(
                    bot, ctx, timeout=180.0 if shake else 360.0)
                if not engine_succeeded(eng):
                    detail = getattr(eng, "last_error", "") or getattr(eng, "state", "")
                    return StageResult.failed(
                        self.id, "v2 engine did not reach game-ready: %s" % detail)
                if shake:
                    self._keep_shake_armed(ctx, bot)
                return StageResult.ok(
                    self.id, "v2 engine finished state=%s" % getattr(eng, "state", "?"))
            except Exception as e:
                return StageResult.failed(
                    self.id, "v2 engine failed: %r" % e)

        # ---- legacy window gate (unchanged) ----
        n = ctx.bump_retry(self.id)
        if n > self.goal.max_retries:
            return StageResult.failed(
                self.id, "window gate retries exhausted — no valid Purple")

        attach = getattr(bot, "_try_attach_running_purple", None)
        if callable(attach) and attach():
            w = bot.purple.rect.width
            h = bot.purple.rect.height
            if not purple_unusable(w, h):
                return self._ok_attached(ctx, bot)
            # Tiny splash — try restore then wait (no second launch).
            restore = getattr(bot, "_restore_hidden_purple", None)
            if callable(restore):
                restore()
            if (getattr(bot, "purple", None)
                    and bot.purple.valid
                    and not purple_unusable(
                        bot.purple.rect.width, bot.purple.rect.height)):
                return self._ok_attached(ctx, bot)
            return StageResult.blocked(
                self.id,
                "Purple attached but unusable %dx%d (splash?)" % (w, h),
                after=0.6, width=w)

        running = False
        proc = getattr(bot, "_purple_process_running", None)
        any_win = getattr(bot, "_any_purple_window_exists", None)
        if callable(proc) and proc():
            running = True
        if callable(any_win) and any_win():
            running = True

        if running:
            # Process up but not attachable yet — restore/find, never relaunch.
            restore = getattr(bot, "_restore_hidden_purple", None)
            if callable(restore) and restore():
                if not purple_unusable(
                        bot.purple.rect.width, bot.purple.rect.height):
                    return self._ok_attached(ctx, bot)
            find = getattr(bot, "find_purple", None)
            # find_purple also launches when nothing runs; only call if still
            # missing after restore — but process IS running so find must not
            # spawn a second client (base.find_purple already guards).
            if callable(find):
                find()
            return StageResult.blocked(
                self.id,
                "Purple process present — waiting for usable window (>=%sx%s)" % (
                    _MIN_LOGIN_W, _MIN_LOGIN_H),
                after=0.8)

        # Nothing running: single launch attempt (cooldown in extras).
        last = float(ctx.extras.get("purple_launch_at") or 0.0)
        if time.time() - last < 8.0:
            return StageResult.blocked(
                self.id, "waiting after Purple launch", after=1.0)

        launch = getattr(bot, "launch_purple", None)
        find = getattr(bot, "find_purple", None)
        ctx.extras["purple_launch_at"] = time.time()
        try:
            if callable(launch):
                launch()
            elif callable(find):
                find()  # launches when nothing running
            else:
                return StageResult.failed(
                    self.id, "bot has no launch_purple/find_purple")
        except Exception as e:
            return StageResult.failed(self.id, "Purple launch error: %r" % e)

        return StageResult.blocked(
            self.id, "Purple launch requested — waiting for window", after=1.2)
