"""Pluggable exception / noise handlers.

Add a new UI variant by registering an ExceptionRule — do not fork the
main stage switch. Handlers run before the stage body when ``match`` is true.

Example
-------
registry.register(ExceptionRule(
    id=\"purple_toast\",
    stage_ids=(\"S3\",),
    match=lambda ctx, snap: snap.get(\"has_toast\"),
    handle=_dismiss_toast,
    priority=50,
))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .context import PipelineContext
from .result import StageResult

log = logging.getLogger("pipeline.exceptions")

MatchFn = Callable[[PipelineContext, Dict[str, Any]], bool]
HandleFn = Callable[[PipelineContext, Dict[str, Any]], StageResult]


@dataclass(order=True)
class ExceptionRule:
    priority: int
    id: str = field(compare=False)
    match: MatchFn = field(compare=False)
    handle: HandleFn = field(compare=False)
    stage_ids: Optional[Tuple[str, ...]] = field(default=None, compare=False)
    # auto failure if this rule fires more than N times in a session
    max_fires: int = field(default=5, compare=False)
    description: str = field(default="", compare=False)


class ExceptionRegistry:
    def __init__(self) -> None:
        self._rules: List[ExceptionRule] = []

    def register(self, rule: ExceptionRule) -> None:
        self._rules.append(rule)
        self._rules.sort()  # lower priority value runs first
        log.info("exception rule registered: %s (priority=%s stages=%s)",
                 rule.id, rule.priority, rule.stage_ids or "*")

    def unregister(self, rule_id: str) -> None:
        self._rules = [r for r in self._rules if r.id != rule_id]

    def list_rules(self) -> Sequence[ExceptionRule]:
        return tuple(self._rules)

    def dispatch(self, ctx: PipelineContext, stage_id: str,
                 snapshot: Dict[str, Any]) -> Optional[StageResult]:
        """Return first matching handler result, or None to run the stage."""
        for rule in self._rules:
            if rule.stage_ids is not None and stage_id not in rule.stage_ids:
                continue
            try:
                if not rule.match(ctx, snapshot):
                    continue
            except Exception as e:
                log.warning("exception rule %s match failed: %r", rule.id, e)
                continue
            fires = ctx.bump_retry("exc:" + rule.id)
            if fires > rule.max_fires:
                return StageResult.failed(
                    stage_id,
                    "exception rule %s exceeded max_fires=%s" % (
                        rule.id, rule.max_fires),
                    rule=rule.id, fires=fires)
            log.info("exception rule fired: %s on %s (%s)",
                     rule.id, stage_id, rule.description or "")
            try:
                return rule.handle(ctx, snapshot)
            except Exception as e:
                log.exception("exception rule %s handle failed", rule.id)
                return StageResult.failed(
                    stage_id, "exception handler %s error: %r" % (rule.id, e),
                    rule=rule.id)


def build_default_registry() -> ExceptionRegistry:
    """Builtin noise / AUTH rules — stubs that read snapshot flags.

    Stages fill ``snapshot`` each tick; rules stay data-driven so new
    popups are one register() call away.
    """
    reg = ExceptionRegistry()

    def _match_flag(name: str):
        return lambda ctx, snap: bool(snap.get(name))

    def _block(msg: str):
        def _h(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
            sid = snap.get("stage_id") or "S?"
            return StageResult.blocked(sid, msg, after=0.5, **{k: snap.get(k)
                                    for k in ("screen", "hwnd") if k in snap})
        return _h

    def _dismiss_toast(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
        sid = snap.get("stage_id") or "S3"
        bot = ctx.bot
        dismissed = False
        fn = getattr(bot, "dismiss_launcher_toast", None)
        if callable(fn):
            try:
                dismissed = bool(fn())
            except Exception as e:
                log.warning("dismiss_launcher_toast failed: %r", e)
        ctx.extras["launcher_toast"] = False
        if not dismissed:
            # OCR false positive — do not burn max_fires; let Start proceed
            return StageResult.retry(
                sid, "toast flag cleared (no real toast)", after=0.2)
        return StageResult.handled(
            sid, "launcher toast dismissed", dismissed=True)

    def _auth_choice_cap(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
        """Fires only when AUTH appears after relaunch budget is exhausted."""
        sid = snap.get("stage_id") or "S5"
        cap = snap.get("auth_relaunch_max") or 2
        n = snap.get("auth_relaunch_count") or 0
        return StageResult.failed(
            sid,
            "AUTH_CHOICE again after %s auto relaunches — abort to avoid loop"
            % cap,
            screen=snap.get("screen"), auth_relaunch_count=n)

    def _uncover_game(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
        sid = snap.get("stage_id") or "S4"
        bot = ctx.bot
        prepare = getattr(bot, "_prepare_game_foreground", None)
        if callable(prepare):
            try:
                if prepare(attempts=2):
                    ctx.extras["game_covered"] = False
                    return StageResult.handled(
                        sid, "uncovered via prepare_game_foreground")
            except Exception as e:
                log.warning("prepare uncover failed: %r", e)
        ensure = getattr(bot, "_ensure_game_on_top", None)
        if callable(ensure):
            try:
                if ensure():
                    ctx.extras["game_covered"] = False
                    return StageResult.handled(sid, "uncovered game via ensure")
            except Exception as e:
                log.warning("uncover failed: %r", e)
        return StageResult.blocked(
            sid, "game covered by another window — restore focus", after=0.4)

    reg.register(ExceptionRule(
        priority=10, id="wrong_purple_window",
        stage_ids=("S1", "S2", "S3"),
        match=lambda ctx, snap: (
            bool(snap.get("purple_too_small"))
            and not snap.get("purple_missing")),
        handle=_block("Purple window below main-shell contract — wait/reattach"),
        max_fires=40,
        description="unusable splash/toast (below login-card size)",
    ))
    reg.register(ExceptionRule(
        priority=20, id="launcher_toast",
        stage_ids=("S3",),
        match=_match_flag("launcher_toast"),
        handle=_dismiss_toast,
        max_fires=15,
        description="profile / promo toast over card",
    ))
    reg.register(ExceptionRule(
        priority=15, id="game_covered",
        # S4 only — GameFlow re-asserts topmost every tick; firing here
        # starved S5 (SECURITY) until max_fires FAIL in the live run.
        stage_ids=("S4",),
        match=_match_flag("game_covered"),
        handle=_uncover_game,
        max_fires=40,
        description="Purple over LC center",
    ))
    reg.register(ExceptionRule(
        priority=5, id="auth_choice",
        stage_ids=("S5",),
        match=_match_flag("auth_choice"),
        handle=_auth_choice_cap,
        max_fires=2,
        description="AUTH_CHOICE after relaunch budget exhausted — fail closed",
    ))
    reg.register(ExceptionRule(
        priority=25, id="logging_in",
        stage_ids=("S2",),
        match=_match_flag("purple_logging_in"),
        handle=_block("Purple still logging in — wait"),
        max_fires=30,
        description="登录中 / logging-in splash",
    ))

    def _login_form_during_start(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
        sid = snap.get("stage_id") or "S3"
        bot = ctx.bot
        from base import Phase
        if getattr(bot, "_set_phase", None):
            try:
                bot._purple_logged_in = False
                bot._password_entered = False
                bot._set_phase(Phase.WAIT_LOGIN_FORM)
            except Exception:
                pass
        ctx.purple_logged_in = False
        return StageResult.handled(
            sid, "login form during Start — back to S2",
            next_stage_id="S2")

    def _unknown_purple_wait(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
        sid = snap.get("stage_id") or "S2"
        return StageResult.blocked(
            sid, "Purple screen unclassified — wait (no click)", after=0.45)

    reg.register(ExceptionRule(
        priority=12, id="login_form_on_start",
        stage_ids=("S3",),
        match=lambda ctx, snap: bool(snap.get("login_form")),
        handle=_login_form_during_start,
        max_fires=8,
        description="email/password form while Start Game is running",
    ))
    reg.register(ExceptionRule(
        priority=28, id="purple_unknown_screen",
        # S3 only. S2 must still run: WinOCR often returns empty on the
        # 1642x1026 email/password shell, and blocking here prevents the
        # saved-ratio login clicks from ever firing.
        stage_ids=("S3",),
        match=lambda ctx, snap: snap.get("purple_screen") == "unknown",
        handle=_unknown_purple_wait,
        max_fires=80,
        description="no positive Purple screen — do not click Start Game",
    ))

    def _match_fixed_stall(ctx: PipelineContext, snap: Dict[str, Any]) -> bool:
        if snap.get("purple_fixed_stalled"):
            return True
        bot = ctx.bot
        fn = getattr(bot, "_purple_fixed_stalled", None)
        return callable(fn) and bool(fn())

    def _fixed_to_dynamic(ctx: PipelineContext, snap: Dict[str, Any]) -> StageResult:
        sid = snap.get("stage_id") or "S2"
        bot = ctx.bot
        fn = getattr(bot, "_fallback_purple_to_dynamic", None)
        if callable(fn):
            fn(reason="exception:fixed_stall")
        ctx.extras["purple_fixed_fallback"] = True
        return StageResult.handled(
            sid, "fixed Purple stalled — switched to dynamic",
            after=0.25, purple_mode="dynamic")

    reg.register(ExceptionRule(
        priority=30, id="purple_fixed_stall",
        stage_ids=("S2", "S3"),
        match=_match_fixed_stall,
        handle=_fixed_to_dynamic,
        max_fires=2,
        description="fixed clicks no progress → dynamic OCR",
    ))
    return reg
