"""Human-like shop mouse aim for every in-shop click.

Buy/Sell tab, list row, confirm, scroll hover, and recover UI share this path:
varied curve approach → fine micro-adjust → 0.10–0.15s hold.
No cursor verification on window UVs (1–2px land error).
NPC open keeps DIALOG verify in ``npc_aim``, but uses the same curve family.
"""
from __future__ import annotations

import math
import time
from typing import Any

from app._05_action import humanize as hz


def _rng(executor: Any):
    return getattr(executor, "_rng", None) or getattr(
        getattr(executor, "mouse", None), "_rng", None
    )


def _sleep_jitter(lo_hi: tuple[float, float], rng) -> None:
    delay = hz.uniform(lo_hi, rng)
    if delay > 0.0:
        time.sleep(delay)


def land_error_px(mouse: Any, rng) -> tuple[float, float]:
    """1px on smaller screens, 2px when width >= 1600 (random direction)."""
    try:
        w = int(getattr(mouse, "screen_width", 0) or 0)
    except (TypeError, ValueError):
        w = 0
    lo, hi = hz.SHOP_UI_LAND_ERROR_PX
    err = float(hi) if w >= 1600 else float(lo)
    ang = rng.uniform(0.0, 2.0 * math.pi)
    return math.cos(ang) * err, math.sin(ang) * err


def shop_move_to(
    executor: Any,
    sx: float,
    sy: float,
    *,
    budget_s: float | None = None,
    steps: tuple[int, int] | None = None,
) -> None:
    """One shop move with a freshly rolled curve style (not combat Bezier)."""
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return
    rng = _rng(executor)
    budget = (
        float(budget_s)
        if budget_s is not None
        else hz.uniform(hz.SHOP_UI_APPROACH_BUDGET_S, rng)
    )
    step_hi = steps if steps is not None else hz.SHOP_UI_APPROACH_STEPS
    mouse.move_with_budget(
        sx,
        sy,
        budget_s=budget,
        steps=hz.randint(step_hi, rng),
        curve_fraction=hz.SHOP_APPROACH_CURVE_FRACTION,
        shop_curves=True,
    )


def approach_ui(executor: Any, sx: float, sy: float) -> None:
    """Curve toward an in-window control (shorter budget than NPC open)."""
    shop_move_to(executor, sx, sy)


def fine_adjust(executor: Any, sx: float, sy: float) -> tuple[float, float]:
    """Micro-curves around ``(sx,sy)``; return final land with 1–2px error."""
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return float(sx), float(sy)
    rng = _rng(executor)
    moves = hz.randint(hz.SHOP_UI_FINE_MOVES, rng)
    for i in range(max(1, moves)):
        radius = hz.uniform(hz.SHOP_UI_FINE_RADIUS_PX, rng)
        radius *= max(0.35, 1.0 - (i / max(1, moves)))
        ang = rng.uniform(0.0, 2.0 * math.pi)
        tx = float(sx) + math.cos(ang) * radius
        ty = float(sy) + math.sin(ang) * radius
        shop_move_to(
            executor,
            tx,
            ty,
            budget_s=hz.uniform((0.08, 0.22), rng),
            steps=(4, 10),
        )
        _sleep_jitter(hz.SHOP_UI_FINE_HOVER_S, rng)
    ox, oy = land_error_px(mouse, rng)
    fx, fy = float(sx) + ox, float(sy) + oy
    shop_move_to(
        executor,
        fx,
        fy,
        budget_s=hz.uniform((0.06, 0.16), rng),
        steps=(3, 8),
    )
    _sleep_jitter(hz.SHOP_CLICK_PRE_S, rng)
    return fx, fy


def click_hold(executor: Any, sx: float, sy: float) -> None:
    """Left-button down for 0.10–0.15s without a second approach move."""
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return
    rng = _rng(executor)
    hold = hz.uniform(hz.SHOP_UI_CLICK_HOLD_S, rng)
    mouse.hold_in_place(sx, sy, hold, button="left")


def aim_and_click(executor: Any, sx: float, sy: float) -> None:
    """Approach + fine adjust + human hold-click (no cursor gate)."""
    approach_ui(executor, sx, sy)
    fx, fy = fine_adjust(executor, sx, sy)
    click_hold(executor, fx, fy)


def type_qty_human(executor: Any, qty: int, *, backspace: int = 3) -> None:
    """After the row click: 0.2–0.3s, then keys at 5–6 characters/second."""
    rng = _rng(executor)
    _sleep_jitter(hz.SHOP_UI_TYPE_AFTER_CLICK_S, rng)
    kb = getattr(executor, "keyboard", None)
    if kb is None:
        return
    if backspace > 0:
        kb.tap(
            "backspace",
            count=int(backspace),
            interval=hz.uniform(hz.SHOP_UI_TYPE_KEY_GAP_S, rng),
        )
        _sleep_jitter(hz.SHOP_UI_TYPE_KEY_GAP_S, rng)
    digits = str(max(1, min(999, int(qty))))
    for i, digit in enumerate(digits):
        kb.press(digit)
        if i + 1 < len(digits):
            _sleep_jitter(hz.SHOP_UI_TYPE_KEY_GAP_S, rng)
