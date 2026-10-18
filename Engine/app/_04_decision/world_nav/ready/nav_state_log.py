"""Structured world-nav state events (GUI live log + manmabot.nav when available).

States used now (Extra_data LIVE RUN) and reserved for main-bot integration:

  PLAN_OK / PLAN_FAIL
  RUN_START / RUN_STOP / RUN_DONE / RUN_FAIL
  STEP_BEGIN / STEP_OK / STEP_FAIL
  WALK_START / WALK_ARRIVE / WALK_FAIL
  SCROLL_START / SCROLL_LAND / SCROLL_SETTLE / SCROLL_FAIL
  TRANSITION_START / TRANSITION_LANDED / TRANSITION_FAIL
  FAIL_SKIP_NEXT   — routine advances after plan/exec failure (main bot)
  PAUSE_CYCLE      — one routine round all failed; retry next round (no stop)
  FIELD_NAV_FALLBACK — field same-map move failed; walk or retry, row kept
"""

from __future__ import annotations

from typing import Any, Callable, Optional

LogFn = Callable[[str], None]

# Canonical state tokens (stable for grepping session logs).
PLAN_OK = "PLAN_OK"
PLAN_FAIL = "PLAN_FAIL"
RUN_START = "RUN_START"
RUN_STOP = "RUN_STOP"
RUN_DONE = "RUN_DONE"
RUN_FAIL = "RUN_FAIL"
STEP_BEGIN = "STEP_BEGIN"
STEP_OK = "STEP_OK"
STEP_FAIL = "STEP_FAIL"
WALK_START = "WALK_START"
WALK_ARRIVE = "WALK_ARRIVE"
WALK_FAIL = "WALK_FAIL"
SCROLL_START = "SCROLL_START"
SCROLL_LAND = "SCROLL_LAND"
SCROLL_SETTLE = "SCROLL_SETTLE"
SCROLL_FAIL = "SCROLL_FAIL"
TRANSITION_START = "TRANSITION_START"
TRANSITION_LANDED = "TRANSITION_LANDED"
TRANSITION_FAIL = "TRANSITION_FAIL"
NPC_TP_START = "NPC_TP_START"
NPC_TP_LAND = "NPC_TP_LAND"
NPC_TP_FAIL = "NPC_TP_FAIL"
FAIL_SKIP_NEXT = "FAIL_SKIP_NEXT"
PAUSE_CYCLE = "PAUSE_CYCLE"
FIELD_NAV_FALLBACK = "FIELD_NAV_FALLBACK"


def format_event(state: str, **fields: Any) -> str:
    """One-line ``[world_nav] STATE=… k=v …`` (None fields omitted)."""
    parts = [f"[world_nav] STATE={state}"]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").strip()
        if not text:
            continue
        if any(ch.isspace() for ch in text):
            text = text.replace('"', "'")
            parts.append(f'{key}="{text}"')
        else:
            parts.append(f"{key}={text}")
    return " ".join(parts)


def emit(state: str, sink: Optional[LogFn] = None, **fields: Any) -> str:
    """Emit to optional sink and ``manmabot.nav`` (if bot_log is importable)."""
    line = format_event(state, **fields)
    if sink is not None:
        try:
            sink(line)
        except Exception:
            pass
    try:
        from app.bot_log import event

        event("nav", "%s", line)
    except Exception:
        pass
    return line
