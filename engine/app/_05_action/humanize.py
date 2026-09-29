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
MOVE_STEPS = (6, 14)
MOVE_STEP_SLEEP = (0.0003, 0.002)
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

# Elf/knight attack: seconds between left-clicks on the sticky target.
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

# Loot: seconds between left-clicks on the sticky item (same cadence as elf).
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
# Pause after each NPC-search hover so the dialog cursor can appear.
SHOP_NPC_SEARCH_STEP_S = 0.25
SHOP_UI_GAP = (0.5, 0.5)
# Gap between the two Esc taps that close the level-up dialog.
LEVEL_UP_ESC_GAP = (0.12, 0.28)
# Wait after teleport/escape key before the next input.
ESCAPE_WAIT = (0.35, 0.75)

# Periodic Esc to close mis-click dialogs / conversation windows.
DISMISS_UI_INTERVAL = (3.0, 5.0)

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


def bezier_points(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    steps: int,
    rng: Optional[random.Random] = None,
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
    frac = r.uniform(*MOVE_CURVE_FRACTION)
    side = 1.0 if r.random() < 0.5 else -1.0
    offset = max(4.0, length * frac) * side
    cx = (x0 + x1) / 2.0 + px * offset
    cy = (y0 + y1) / 2.0 + py * offset

    points: list[tuple[int, int]] = []
    for i in range(1, steps + 1):
        t = i / steps
        # Ease-in-out so the cursor slows near the end.
        te = t * t * (3.0 - 2.0 * t)
        u = 1.0 - te
        x = u * u * x0 + 2.0 * u * te * cx + te * te * x1
        y = u * u * y0 + 2.0 * u * te * cy + te * te * y1
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
