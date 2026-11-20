"""Human-like shop NPC aim (varied curve approach + fine DIALOG confirm).

Combat / travel keep ``MouseController.move`` → ``MOVE_BUDGET_S`` (0.02s).
Shop NPC open uses ``shop_curves`` path families shared with ``ui_aim``.

When ``executor.humanize`` is false (Practice / tests), callers should use the
fast mechanical path in ``open_shop_npc`` instead of this module.
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable

from app._05_action import humanize as hz
from app._05_action.cursor_catalog import DIALOG_OK_CATEGORIES
from app._05_action.cursor_verify import verify_cursor
from shop.ui_aim import click_hold, shop_move_to


def _rng(executor: Any):
    return getattr(executor, "_rng", None) or getattr(
        getattr(executor, "mouse", None), "_rng", None
    )


def _sleep_jitter(lo_hi: tuple[float, float], rng) -> None:
    delay = hz.uniform(lo_hi, rng)
    if delay > 0.0:
        time.sleep(delay)


def cursor_shows_dialog() -> bool:
    ok, _match = verify_cursor(categories=DIALOG_OK_CATEGORIES)
    return bool(ok)


def approach_npc(executor: Any, sx: float, sy: float) -> None:
    """Spend ~1s on a varied shop curve toward the stall."""
    rng = _rng(executor)
    shop_move_to(
        executor,
        sx,
        sy,
        budget_s=hz.uniform(hz.SHOP_APPROACH_BUDGET_S, rng),
        steps=hz.SHOP_APPROACH_STEPS,
    )


def fine_confirm_dialog_click(executor: Any, sx: float, sy: float) -> bool:
    """Micro-hunt around ``(sx,sy)``, then hold-click only when DIALOG is up.

    Final click uses the same 0.10–0.15s hold as shop UI (no snap re-aim).
    """
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return False
    rng = _rng(executor)
    moves = hz.randint(hz.SHOP_FINE_MOVES, rng)
    saw_dialog = False
    extra_left = 0
    last_xy = (float(sx), float(sy))
    for i in range(max(1, moves)):
        radius = hz.uniform(hz.SHOP_FINE_RADIUS_PX, rng)
        radius *= max(0.35, 1.0 - (i / max(1, moves)))
        ang = rng.uniform(0.0, 2.0 * math.pi)
        tx = float(sx) + math.cos(ang) * radius
        ty = float(sy) + math.sin(ang) * radius
        last_xy = (tx, ty)
        shop_move_to(
            executor,
            tx,
            ty,
            budget_s=hz.uniform((0.10, 0.28), rng),
            steps=(5, 12),
        )
        _sleep_jitter(hz.SHOP_FINE_HOVER_S, rng)
        if cursor_shows_dialog():
            if not saw_dialog:
                saw_dialog = True
                extra_left = hz.randint(hz.SHOP_FINE_EXTRA_AFTER_DIALOG, rng)
            elif extra_left > 0:
                extra_left -= 1
            if saw_dialog and extra_left <= 0:
                _sleep_jitter(hz.SHOP_FINE_HESITATE_S, rng)
                _sleep_jitter(hz.SHOP_CLICK_PRE_S, rng)
                if cursor_shows_dialog():
                    click_hold(executor, tx, ty)
                    return True
    shop_move_to(
        executor,
        sx,
        sy,
        budget_s=hz.uniform((0.08, 0.20), rng),
        steps=(4, 10),
    )
    _sleep_jitter(hz.SHOP_FINE_HESITATE_S, rng)
    _sleep_jitter(hz.SHOP_CLICK_PRE_S, rng)
    if cursor_shows_dialog():
        click_hold(executor, sx, sy)
        return True
    if cursor_shows_dialog():
        click_hold(executor, last_xy[0], last_xy[1])
        return True
    return False


def open_npc_human(executor: Any, sx: float, sy: float) -> bool:
    """Approach + fine confirm for one screen point."""
    approach_npc(executor, sx, sy)
    return fine_confirm_dialog_click(executor, sx, sy)


def probe_destinations_human(
    executor: Any,
    dests,
    screen_xy: Callable[[float, float], tuple[float, float]],
) -> bool:
    """Try catalog / tile UVs with irregular gaps and varied curves."""
    rng = _rng(executor)
    for dest in dests:
        sx, sy = screen_xy(dest.x, dest.y)
        shop_move_to(
            executor,
            sx,
            sy,
            budget_s=hz.uniform((0.35, 0.85), rng),
            steps=(8, 16),
        )
        _sleep_jitter(hz.SHOP_PROBE_STEP_S, rng)
        if fine_confirm_dialog_click(executor, sx, sy):
            return True
    return False


def probe_ring_human(
    executor: Any,
    dest,
    screen_xy: Callable[[float, float], tuple[float, float]],
    *,
    radius_px: float,
) -> bool:
    """Fallback ring with shuffled order, varied curves, jittered pauses."""
    from app._05_action.cursor_verify import npc_search_screen_points

    rng = _rng(executor)
    cx, cy = screen_xy(dest.x, dest.y)
    points = npc_search_screen_points(cx, cy, radius_px)
    if len(points) > 1:
        rest = list(points[1:])
        rng.shuffle(rest)
        points = [points[0]] + rest
    for i, (x, y) in enumerate(points):
        budget = (
            hz.uniform((0.25, 0.70), rng)
            if i == 0
            else hz.uniform((0.12, 0.40), rng)
        )
        shop_move_to(
            executor,
            x,
            y,
            budget_s=budget,
            steps=(6, 14),
        )
        _sleep_jitter(hz.SHOP_PROBE_STEP_S, rng)
        if fine_confirm_dialog_click(executor, x, y):
            return True
    return False
