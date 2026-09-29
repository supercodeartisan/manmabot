"""S2 Purple cold login — classify login form vs launcher before skipping."""
from __future__ import annotations

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage

_POST_LOGIN = ("FIND_LINEAGE", "WAIT_GAME", "GAME_LOGIN", "DONE")


class PurpleLoginStage(Stage):
    id = "S2"

    def snapshot(self, ctx: PipelineContext):
        snap = {"stage_id": self.id}
        bot = ctx.bot
        if bot and getattr(bot, "purple", None) and bot.purple.valid:
            w = bot.purple.rect.width
            h = bot.purple.rect.height
            snap["purple_w"] = w
            snap["purple_h"] = h
            from .s1_window_gate import purple_unusable
            snap["purple_too_small"] = purple_unusable(w, h)
            if getattr(bot, "_logging_in_screen", None):
                try:
                    snap["purple_logging_in"] = bool(bot._logging_in_screen())
                except Exception:
                    pass
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
                    snap["purple_logging_in"] = (
                        snap["purple_screen"] == "logging_in")
                except Exception:
                    pass
            store = getattr(bot, "positions", None)
            if store is not None:
                snap["purple_mode"] = getattr(store, "purple_mode", None)
        if getattr(bot, "_purple_logged_in", False) or ctx.purple_logged_in:
            snap["already_logged_in"] = True
        return snap

    def _phase_name(self, bot) -> str:
        phase = getattr(bot, "phase", None)
        return getattr(phase, "name", str(phase) if phase is not None else "")

    def _fixed_ready(self, bot) -> bool:
        store = getattr(bot, "positions", None)
        if store is None:
            return False
        return bool(store.lookup("purple", "purple_id_field"))

    def _verify_not_login_form(self, bot) -> bool:
        """False when the attached shell still shows email/password UI."""
        fn = getattr(bot, "_is_purple_login_screen", None)
        if not callable(fn):
            return True
        try:
            return not bool(fn())
        except Exception:
            return True

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        from base import Phase

        # Never trust the logged-in flag while the login form is visible.
        if not self._verify_not_login_form(bot):
            bot._purple_logged_in = False
            ctx.purple_logged_in = False
            if getattr(bot, "_set_phase", None):
                bot._set_phase(Phase.WAIT_LOGIN_FORM)
            log_msg = "login form visible — clearing logged-in skip"
        else:
            log_msg = None

        if (getattr(bot, "_purple_logged_in", False) or ctx.purple_logged_in) \
                and self._verify_not_login_form(bot):
            classify = getattr(bot, "_classify_attached_purple", None)
            if callable(classify):
                decision = classify()
                if decision == "FIND_LINEAGE":
                    ctx.purple_logged_in = True
                    return StageResult.skip(
                        self.id, "Purple already logged in (classified)")
                if decision == "WAIT_LOGIN_FORM":
                    bot._purple_logged_in = False
                    ctx.purple_logged_in = False
                    if getattr(bot, "_set_phase", None):
                        bot._set_phase(Phase.WAIT_LOGIN_FORM)
                    log_msg = "classified login form — not skipping S2"
                else:
                    log_msg = (log_msg + "; " if log_msg else "") + (
                        "logged-in flag ignored until launcher confirmed")
            else:
                return StageResult.skip(self.id, "Purple already logged in")

        phase_name = self._phase_name(bot)
        if phase_name in _POST_LOGIN and self._verify_not_login_form(bot):
            # Double-check via classifier when possible
            classify = getattr(bot, "_classify_attached_purple", None)
            if callable(classify):
                decision = classify()
                if decision == "WAIT_LOGIN_FORM":
                    bot._purple_logged_in = False
                    ctx.purple_logged_in = False
                    bot._set_phase(Phase.WAIT_LOGIN_FORM)
                    phase_name = "WAIT_LOGIN_FORM"
                elif decision == "FIND_LINEAGE":
                    ctx.purple_logged_in = True
                    return StageResult.ok(
                        self.id, "launcher past login (classified)")
            else:
                ctx.purple_logged_in = True
                return StageResult.ok(
                    self.id, "launcher past login (%s)" % phase_name)

        n = ctx.bump_retry(self.id)
        if n > self.goal.max_retries:
            return StageResult.failed(
                self.id, "Purple login exceeded retries", phase=phase_name)

        # Familiar fixed shell (1642x1026) → replay saved credential clicks.
        # If fixed makes no progress for purple_fixed_timeout_sec → dynamic.
        bot._maybe_fallback_purple_dynamic(reason="s2")
        store = getattr(bot, "positions", None)
        prefer_fixed = bool(
            store and getattr(store, "is_fixed_purple", False)
            and store.lookup("purple", "purple_id_field"))
        if prefer_fixed and bot.purple and bot.purple.valid:
            try:
                bot._normalize_purple_shell_size(reason="s2_before_fixed")
            except Exception:
                pass
            try:
                bot._arm_purple_fixed_watch()
            except Exception:
                pass

        # Promote FIND_PURPLE → classify, or drive credentials
        if phase_name in ("", "FIND_PURPLE", "None"):
            try:
                bot.tick()
            except Exception as e:
                return StageResult.failed(self.id, "tick error: %r" % e)
            phase_name = self._phase_name(bot)

        if prefer_fixed and phase_name in (
                "ENTER_CREDENTIALS", "WAIT_LOGIN_FORM"):
            if phase_name == "WAIT_LOGIN_FORM":
                try:
                    bot.tick()
                except Exception as e:
                    return StageResult.failed(self.id, "tick error: %r" % e)
                phase_name = self._phase_name(bot)
            if getattr(bot, "phase", None) == Phase.ENTER_CREDENTIALS or (
                    phase_name == "ENTER_CREDENTIALS"):
                try:
                    bot._fixed_purple_login()
                except Exception as e:
                    return StageResult.failed(
                        self.id, "fixed purple login error: %r" % e)
            else:
                try:
                    bot.tick()
                except Exception as e:
                    return StageResult.failed(self.id, "tick error: %r" % e)
        else:
            tick = getattr(bot, "tick", None)
            if not callable(tick):
                return StageResult.failed(self.id, "bot.tick missing")
            try:
                tick()
            except Exception as e:
                return StageResult.failed(self.id, "tick error: %r" % e)

        if getattr(bot, "_purple_logged_in", False) and self._verify_not_login_form(bot):
            ctx.purple_logged_in = True
            return StageResult.ok(
                self.id,
                "Purple logged in%s" % (" (fixed)" if prefer_fixed else ""))
        phase_name = self._phase_name(bot)
        if phase_name in _POST_LOGIN and self._verify_not_login_form(bot):
            ctx.purple_logged_in = True
            return StageResult.ok(self.id, "reached %s" % phase_name)
        return StageResult.retry(
            self.id,
            (log_msg + "; " if log_msg else "")
            + "login in progress (%s)" % phase_name,
            after=0.35, phase=phase_name, fixed=prefer_fixed)
