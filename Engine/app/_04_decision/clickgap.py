"""Lines that show why the next click was late.

Channel ``clickgap``. Recording only: callers keep their own decisions.
``since`` is seconds since the last real click (attack, travel, or loot F4).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.bot_log import event

if TYPE_CHECKING:
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

_last_mouse = 0.0
_hold_key: str | None = None


def since_mouse() -> float:
    if _last_mouse <= 0.0:
        return 0.0
    return time.time() - _last_mouse


def format_progress(state: object | None) -> str:
    """``lv`` / ``exp`` from the monitor snapshot, or ``-`` when unread."""
    if state is None:
        return "lv=- exp=-"
    from app._04_decision.behaviors.combat import _kill_progress_pair

    pair = _kill_progress_pair(state)  # type: ignore[arg-type]
    if pair is None:
        return "lv=- exp=-"
    _source, level_i, exp_f = pair
    return f"lv={level_i} exp={exp_f:.4f}"


def note_plan(detail: str) -> None:
    """A click was requested. Does not reset the mouse clock."""
    event("clickgap", "plan %s since=%.3f", detail, since_mouse())


def note_mouse(detail: str) -> None:
    """A click or loot F4 reached the action layer."""
    global _last_mouse, _hold_key
    event("clickgap", "mouse %s since=%.3f", detail, since_mouse())
    _last_mouse = time.time()
    _hold_key = None


def note_skip(detail: str) -> None:
    """This tick wanted an action and did not click."""
    event("clickgap", "skip %s since=%.3f", detail, since_mouse())


def note_hold(key: str, detail: str) -> None:
    """First tick of a no-click hold. Repeats of ``key`` stay quiet."""
    global _hold_key
    if _hold_key == key:
        return
    _hold_key = key
    event("clickgap", "hold %s since=%.3f", detail, since_mouse())


def log_sticky_release(
    state: "GameState | None",
    blackboard: "Blackboard",
    reason: str,
) -> None:
    """Call before the lock fields are cleared."""
    tid = blackboard.current_target_id
    species = blackboard.current_target_species or "-"
    started = float(blackboard.target_engage_started or 0.0)
    engage_s = time.time() - started if started > 0.0 else -1.0
    event(
        "clickgap",
        "sticky release id=%s species=%s reason=%s engage_s=%.2f %s since=%.3f",
        tid if tid is not None else "-",
        species,
        reason,
        engage_s,
        format_progress(state),
        since_mouse(),
    )
