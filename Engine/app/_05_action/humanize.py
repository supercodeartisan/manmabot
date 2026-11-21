"""Input humanization: curved mouse paths and timing noise.

Game anti-cheat looks for metronomic timing. Helpers here turn fixed delays
into small random ranges. Aim pixel jitter is disabled (YOLO / tile bias).
Callers that need deterministic tests can disable humanize or inject a seeded
``Random``.
"""
from __future__ import annotations

import math
import random
import time
from typing import Iterable, Optional, Sequence

# Pixel aim offset around a target center. Kept at 0: YOLO detections and
# planned tile clicks already have positional bias; extra jitter hurts aim.
AIM_JITTER_PX = (0.0, 0.0)

# Curved move: number of intermediate steps (inclusive of end).
# The live path must finish inside MouseController's 0.02s budget.
MOVE_STEPS = (4, 8)
MOVE_STEP_SLEEP = (0.0003, 0.002)
MOVE_BUDGET_S = 0.02
# Control-point offset as a fraction of the move length (min 4 px).
MOVE_CURVE_FRACTION = (0.08, 0.22)

# Key press hold duration (seconds). Shared by potions, box keys, teleport.
KEY_HOLD = (0.035, 0.09)
# Mage energy-bolt F5 hold (press_delay): down, wait, up. No extra gap after.
MAGE_KEY_HOLD = (0.01, 0.03)

# Gap after heal F8 (or a self-buff key) before clicking self.
MAGE_PRE_CLICK_GAP = (0.03, 0.12)
# Pause between the two F8 taps for heal.
HEAL_DOUBLE_GAP = (0.06, 0.14)
# Seconds between mage cast loops (must be ≥ magic cooldown 0.5 s).
MAGE_CAST_INTERVAL = (0.50, 0.55)

# Former elf/knight click gap. Live attack no longer waits on this;
# the session tick is the cadence. Still loaded so action.yaml stays valid.
ELF_ATTACK_INTERVAL = (0.09, 0.14)
# Hunt/Attack ±ms widening of attack/cast gaps. Off keeps the ranges above.
ATTACK_JITTER_ENABLED = False
ATTACK_JITTER_MS = 35


def attack_gap(base: tuple[float, float], rng: Optional[random.Random] = None) -> float:
    """Sample an attack/cast interval, optionally widened by operator jitter."""
    lo = float(base[0])
    hi = float(base[1])
    if ATTACK_JITTER_ENABLED:
        pad = max(0.0, float(ATTACK_JITTER_MS) / 1000.0)
        lo = max(0.02, lo - pad)
        hi = max(lo, hi + pad)
    if rng is None:
        return (lo + hi) / 2.0
    return uniform((lo, hi), rng)

# Trial: Esc to cancel walk before the first click on a monster.
# Sticky re-clicks skip this so melee can still walk into range.
ATTACK_STOP_ENABLED = True
ATTACK_STOP_WAIT_S = 0.0

# Former loot click/F4 gap. Live pickup no longer waits on this;
# the session tick is the cadence. Still loaded so action.yaml stays valid.
LOOT_CLICK_INTERVAL = (0.15, 0.25)

# Wait after F1/F2/F3 shortcut-box switch.
BOX_SWITCH_WAIT = (0.2, 0.4)
# Talking scroll: same cadence as Start Shopping Practice (box → list → click).
TALKING_SCROLL_BOX_S = 0.25
TALKING_SCROLL_KEY_S = 0.4
TALKING_SCROLL_AFTER_CLICK_S = 0.2
TALKING_SCROLL_OPEN = (0.4, 0.4)
TALKING_SCROLL_AFTER_CLICK = (0.2, 0.2)
# After a talking-scroll hop to a shop, stand still before Esc / NPC click.
TALKING_SCROLL_SHOP_WAIT_S = 2.0
# Shop window: 1s stand still on walk arrival; 2s after NPC dialog; 1s after Buy/Sell.
SHOP_ARRIVE_WAIT_S = 1.0
SHOP_AFTER_NPC_WAIT_S = 2.0
SHOP_AFTER_TAB_WAIT_S = 1.0
# Item row / qty / confirm clicks keep this shorter gap.
SHOP_BUTTON_WAIT_S = 0.5
# Multiply stage waits by this factor (±~10–15%) so cadence is not metronomic.
SHOP_STAGE_WAIT_JITTER = (0.85, 1.15)
# After rows are chosen, before Buy/Sell confirm: accidental wheel fidget.
SHOP_PRE_CONFIRM_FIDGET_N = (2, 4)
SHOP_PRE_CONFIRM_FIDGET_GAP_S = (0.30, 0.50)
SHOP_PRE_CONFIRM_FIDGET_NUDGE_PX = (8.0, 28.0)  # down-right cursor drift
# Pause after each NPC-search hover so the dialog cursor can appear.
# Used only when shop NPC human-aim is off (Practice / humanize=False).
SHOP_NPC_SEARCH_STEP_S = 0.25
SHOP_UI_GAP = (0.5, 0.5)
# Shop NPC open only — does NOT change combat ``MOVE_BUDGET_S`` (0.02s).
# Approach: long curved travel toward the stall; fine: micro-hunt for DIALOG.
SHOP_APPROACH_BUDGET_S = (0.90, 1.55)
SHOP_APPROACH_STEPS = (14, 28)
SHOP_APPROACH_CURVE_FRACTION = (0.12, 0.32)
SHOP_FINE_RADIUS_PX = (4.0, 14.0)
SHOP_FINE_MOVES = (3, 7)
SHOP_FINE_HOVER_S = (0.08, 0.28)
SHOP_FINE_EXTRA_AFTER_DIALOG = (1, 3)
SHOP_FINE_HESITATE_S = (0.05, 0.35)
SHOP_PROBE_STEP_S = (0.12, 0.42)  # irregular gap between fallback probe points
SHOP_CLICK_PRE_S = (0.04, 0.16)
# In-window buy/sell UV clicks (no cursor verify). Shorter approach than NPC open.
SHOP_UI_APPROACH_BUDGET_S = (0.35, 0.85)
SHOP_UI_APPROACH_STEPS = (8, 18)
SHOP_UI_FINE_RADIUS_PX = (3.0, 10.0)
SHOP_UI_FINE_MOVES = (2, 5)
SHOP_UI_FINE_HOVER_S = (0.05, 0.18)
SHOP_UI_CLICK_HOLD_S = (0.10, 0.15)  # human mouse-button down time
# Final land offset: 1px on smaller screens, 2px when width >= 1600.
SHOP_UI_LAND_ERROR_PX = (1, 2)
SHOP_UI_SCROLL_THINK_S = (0.50, 2.00)  # pause before wheel, like reading the list
SHOP_UI_TYPE_AFTER_CLICK_S = (0.20, 0.30)
# Inter-key gap for ~5–6 characters/second (1/6s … 1/5s).
SHOP_UI_TYPE_KEY_GAP_S = (1.0 / 6.0, 1.0 / 5.0)
# Gap between the two Esc taps that close the level-up dialog.
LEVEL_UP_ESC_GAP = (0.12, 0.28)
# Wait after teleport/escape key before the next input.
ESCAPE_WAIT = (0.35, 0.75)

# Periodic Esc to close mis-click dialogs / conversation windows.
# Used as retry gap when uidialog still shows an unexpected OPEN window.
DISMISS_UI_INTERVAL = (3.0, 5.0)
# Wait for shop/storage/teleporter/talking-scroll UI OPEN before next input.
UIDIALOG_OPEN_TIMEOUT_S = 3.0

# Action anti-spam re-click ticks.
STUCK_TICKS = (16, 26)

# Click press->release (also used by MouseController.click).
CLICK_DELAY = (0.01, 0.03)

def _rng(rng: Optional[random.Random] = None) -> random.Random:
    return rng if rng is not None else random


def uniform(lo_hi: Sequence[float], rng: Optional[random.Random] = None) -> float:
    lo, hi = lo_hi
    return _rng(rng).uniform(lo, hi)


def randint(lo_hi: Sequence[int], rng: Optional[random.Random] = None) -> int:
    lo, hi = lo_hi
    return _rng(rng).randint(lo, hi)


def sleep_range(lo_hi: Sequence[float], rng: Optional[random.Random] = None) -> None:
    time.sleep(uniform(lo_hi, rng))


def shop_stage_sleep(
    base_s: float, rng: Optional[random.Random] = None, *, jitter: bool = True
) -> None:
    """Sleep a shop stage wait, optionally ±10–15% (`SHOP_STAGE_WAIT_JITTER`)."""
    base = max(0.0, float(base_s))
    if base <= 0.0:
        return
    if not jitter:
        time.sleep(base)
        return
    factor = uniform(SHOP_STAGE_WAIT_JITTER, rng)
    time.sleep(base * max(0.0, float(factor)))


def aim_jitter(
    x: float,
    y: float,
    radius_px: Sequence[float] = AIM_JITTER_PX,
    rng: Optional[random.Random] = None,
) -> tuple[int, int]:
    """Offset a pixel aim point by a small random disk (no-op when radius is 0)."""
    lo = float(radius_px[0]) if radius_px else 0.0
    hi = float(radius_px[1]) if len(radius_px) > 1 else lo
    if hi <= 0.0:
        return int(round(x)), int(round(y))
    r = _rng(rng)
    radius = r.uniform(lo, hi)
    angle = r.uniform(0.0, 2.0 * math.pi)
    return int(round(x + math.cos(angle) * radius)), int(round(y + math.sin(angle) * radius))


def _ease_t(t: float, kind: str) -> float:
    t = max(0.0, min(1.0, float(t)))
    if kind == "linear":
        return t
    if kind == "ease_in":
        return t * t
    if kind == "ease_out":
        u = 1.0 - t
        return 1.0 - u * u
    # smoothstep (default)
    return t * t * (3.0 - 2.0 * t)


def bezier_points(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    steps: int,
    rng: Optional[random.Random] = None,
    *,
    curve_fraction: Sequence[float] | None = None,
) -> list[tuple[int, int]]:
    """Quadratic Bezier path from (x0,y0) to (x1,y1) with a jittered control point."""
    r = _rng(rng)
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1.0 or steps <= 1:
        return [(int(round(x1)), int(round(y1)))]

    # Perpendicular unit vector for a slight arc.
    px, py = -dy / length, dx / length
    frac_lo_hi = curve_fraction if curve_fraction is not None else MOVE_CURVE_FRACTION
    frac = r.uniform(float(frac_lo_hi[0]), float(frac_lo_hi[1]))
    side = 1.0 if r.random() < 0.5 else -1.0
    offset = max(4.0, length * frac) * side
    cx = (x0 + x1) / 2.0 + px * offset
    cy = (y0 + y1) / 2.0 + py * offset

    points: list[tuple[int, int]] = []
    for i in range(1, steps + 1):
        t = i / steps
        te = _ease_t(t, "smooth")
        u = 1.0 - te
        x = u * u * x0 + 2.0 * u * te * cx + te * te * x1
        y = u * u * y0 + 2.0 * u * te * cy + te * te * y1
        points.append((int(round(x)), int(round(y))))
    return points


# Shop-only path families. Combat keeps ``bezier_points`` / MOVE_BUDGET_S.
SHOP_CURVE_STYLES = (
    "arc",       # single quadratic bulge (classic)
    "s_curve",   # cubic S (two opposite bulges)
    "lead_in",   # bend early, then straighten
    "late_bend", # nearly straight, bend near the end
    "shallow",   # tiny wobble
    "via",       # two-segment through a random mid waypoint
)


def shop_curve_points(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    steps: int,
    rng: Optional[random.Random] = None,
    *,
    curve_fraction: Sequence[float] | None = None,
) -> list[tuple[int, int]]:
    """Shop mouse path: randomly combine style + easing + side so arcs vary.

    Combat must not call this — only shop UI / NPC open approaches.
    """
    r = _rng(rng)
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1.0 or steps <= 1:
        return [(int(round(x1)), int(round(y1)))]

    style = r.choice(SHOP_CURVE_STYLES)
    ease = r.choice(("smooth", "linear", "ease_in", "ease_out"))
    frac_lo_hi = curve_fraction if curve_fraction is not None else SHOP_APPROACH_CURVE_FRACTION
    frac = r.uniform(float(frac_lo_hi[0]), float(frac_lo_hi[1]))
    if style == "shallow":
        frac *= r.uniform(0.25, 0.55)
    side = 1.0 if r.random() < 0.5 else -1.0
    nx, ny = -dy / length, dx / length  # unit perpendicular

    def _sample(te: float, cx: float, cy: float, c2x: float | None = None, c2y: float | None = None) -> tuple[float, float]:
        u = 1.0 - te
        if c2x is None or c2y is None:
            x = u * u * x0 + 2.0 * u * te * cx + te * te * x1
            y = u * u * y0 + 2.0 * u * te * cy + te * te * y1
        else:
            # Cubic Bezier
            x = (
                u * u * u * x0
                + 3.0 * u * u * te * cx
                + 3.0 * u * te * te * c2x
                + te * te * te * x1
            )
            y = (
                u * u * u * y0
                + 3.0 * u * u * te * cy
                + 3.0 * u * te * te * c2y
                + te * te * te * y1
            )
        return x, y

    points: list[tuple[int, int]] = []

    if style == "via":
        # Mid waypoint offset, then two quadratic legs (no recursive via).
        mid_t = r.uniform(0.35, 0.65)
        mid_off = max(6.0, length * frac) * side
        mx = x0 + dx * mid_t + nx * mid_off
        my = y0 + dy * mid_t + ny * mid_off
        n1 = max(2, int(round(steps * mid_t)))
        n2 = max(2, steps - n1)
        leg1 = bezier_points(x0, y0, mx, my, n1, r, curve_fraction=curve_fraction)
        leg2 = bezier_points(mx, my, x1, y1, n2, r, curve_fraction=curve_fraction)
        return leg1 + leg2

    if style == "s_curve":
        off = max(4.0, length * frac)
        c1x = x0 + dx * 0.33 + nx * off * side
        c1y = y0 + dy * 0.33 + ny * off * side
        c2x = x0 + dx * 0.66 - nx * off * side
        c2y = y0 + dy * 0.66 - ny * off * side
        for i in range(1, steps + 1):
            te = _ease_t(i / steps, ease)
            x, y = _sample(te, c1x, c1y, c2x, c2y)
            points.append((int(round(x)), int(round(y))))
        return points

    # Quadratic families: arc / lead_in / late_bend / shallow
    along = 0.5
    if style == "lead_in":
        along = r.uniform(0.22, 0.40)
    elif style == "late_bend":
        along = r.uniform(0.60, 0.82)
    offset = max(4.0, length * frac) * side
    cx = x0 + dx * along + nx * offset
    cy = y0 + dy * along + ny * offset
    for i in range(1, steps + 1):
        te = _ease_t(i / steps, ease)
        x, y = _sample(te, cx, cy)
        points.append((int(round(x)), int(round(y))))
    return points


def path_delays(
    n: int,
    lo_hi: Sequence[float] = MOVE_STEP_SLEEP,
    rng: Optional[random.Random] = None,
) -> Iterable[float]:
    """Per-step sleeps for a mouse path (no sleep after the final point)."""
    r = _rng(rng)
    for i in range(n):
        if i + 1 >= n:
            yield 0.0
        else:
            yield r.uniform(lo_hi[0], lo_hi[1])
