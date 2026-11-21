"""Smoke: shop humanize APIs + bounded waits (schedule stays flexible).

No LC / no real input. Fails if a shop wait band can run away or signatures break.
"""
from __future__ import annotations

import inspect
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app._05_action import humanize as hz  # noqa: E402
from app._05_action.mouse import MouseController  # noqa: E402
from app._04_decision import shops as shops_mod  # noqa: E402
from shop import runtime  # noqa: E402


def test_move_with_budget_accepts_shop_curves():
    sig = inspect.signature(MouseController.move_with_budget)
    assert "shop_curves" in sig.parameters


def test_stage_jitter_band_is_10_to_15_pct():
    lo, hi = float(hz.SHOP_STAGE_WAIT_JITTER[0]), float(hz.SHOP_STAGE_WAIT_JITTER[1])
    assert 0.84 <= lo <= 0.90
    assert 1.10 <= hi <= 1.16


def test_pre_confirm_fidget_wall_time_bounded():
    """Worst fidget must stay under a few seconds so SHOP_RUN does not freeze the tick forever."""
    n = int(hz.SHOP_PRE_CONFIRM_FIDGET_N[1])
    gap = float(hz.SHOP_PRE_CONFIRM_FIDGET_GAP_S[1])
    approach = float(hz.SHOP_UI_APPROACH_BUDGET_S[1])
    worst = (n - 1) * gap + approach
    assert worst < 3.0


def test_sell_settle_plus_decide_bounded():
    settle = float(shops_mod.SELL_WEIGHT_SETTLE_S[1])
    decide = float(shops_mod.SELL_DECIDE_JITTER_S[1])
    assert settle + decide < 3.0


def test_combat_move_budget_untouched():
    assert float(hz.MOVE_BUDGET_S) == 0.02


def test_stage_sleep_never_negative(monkeypatch):
    slept = []
    monkeypatch.setattr(hz.time, "sleep", lambda s: slept.append(s))
    for seed in range(30):
        hz.shop_stage_sleep(0.5, random.Random(seed), jitter=True)
    assert slept
    assert all(s >= 0.0 for s in slept)
    assert max(slept) <= 0.5 * float(hz.SHOP_STAGE_WAIT_JITTER[1]) + 1e-9


def test_runtime_helpers_wired():
    assert callable(runtime._stage_sleep)
    assert callable(runtime._pre_confirm_fidget)
