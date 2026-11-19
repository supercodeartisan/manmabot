"""v2 execution facade — drives the PurpleEngine from the S1/S2/S3 stages.

Only used when the config enables the new engine (`purple_engine=v2`). It is
the single place that decides launch/run/handoff for the three stages and
defines the no-silent-fallback behavior: on failure it returns a diagnostic
and the stage reports FAILED immediately (no legacy fallback).
"""
from __future__ import annotations

import time

from .contract import PurpleContract
from .engine import PurpleEngine
from .handoff import engine_succeeded


def engine_enabled(cfg: dict) -> bool:
    return str(cfg.get("purple_engine", "")).lower() in ("v2", "2", "new")


def build_engine(cfg: dict, email: str, password: str) -> PurpleEngine:
    contract = PurpleContract.load()
    return PurpleEngine(contract, email=email, password=password)


def _credentials(bot) -> tuple[str, str]:
    email = getattr(bot, "username", "") or ""
    password = getattr(bot, "password", "") or ""
    return email, password


def ensure_launched(bot) -> bool:
    """Launch Purple if nothing is running. Returns True when a window is up."""
    from purple_probe import sampleable_windows, enumerate_purple_windows

    if sampleable_windows(enumerate_purple_windows()):
        return True
    launch = getattr(bot, "launch_purple", None)
    if callable(launch):
        try:
            launch()
        except Exception:
            pass
    deadline = time.time() + 35
    while time.time() < deadline:
        if sampleable_windows(enumerate_purple_windows()):
            return True
        time.sleep(0.5)
    return False


def run_v2_engine(bot, ctx, timeout: float = 360.0) -> PurpleEngine:
    """Run the full engine. On success apply handoff. Returns the engine."""
    email, password = _credentials(bot)
    if not email or not password:
        # Defer to the pipeline's existing "need credentials" behavior.
        raise RuntimeError("purple_engine=v2 requires userID/password in config")
    eng = build_engine(ctx.cfg or getattr(bot, "cfg", {}) or {}, email, password)
    state = eng.run(timeout_total=timeout)
    if engine_succeeded(eng):
        from .handoff import apply_handoff
        apply_handoff(bot, ctx, eng)
    return eng
