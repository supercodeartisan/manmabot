"""In-window shop UI aim (no LC / no real mouse driver)."""
from __future__ import annotations

import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app._05_action import humanize as hz  # noqa: E402
from shop import ui_aim  # noqa: E402


def test_ui_hold_and_scroll_constants():
    assert float(hz.SHOP_UI_CLICK_HOLD_S[0]) >= 0.10
    assert float(hz.SHOP_UI_CLICK_HOLD_S[1]) <= 0.15
    assert float(hz.SHOP_UI_SCROLL_THINK_S[0]) >= 0.5
    assert float(hz.SHOP_UI_SCROLL_THINK_S[1]) <= 2.0
    assert float(hz.SHOP_UI_TYPE_AFTER_CLICK_S[0]) >= 0.2
    # 5–6 characters/second → gap in [1/6, 1/5]
    assert abs(float(hz.SHOP_UI_TYPE_KEY_GAP_S[0]) - (1.0 / 6.0)) < 1e-9
    assert abs(float(hz.SHOP_UI_TYPE_KEY_GAP_S[1]) - (1.0 / 5.0)) < 1e-9
    assert float(hz.SHOP_STAGE_WAIT_JITTER[0]) <= 0.90
    assert float(hz.SHOP_STAGE_WAIT_JITTER[1]) >= 1.10
    assert hz.SHOP_PRE_CONFIRM_FIDGET_N == (2, 4)


def test_shop_stage_sleep_applies_jitter(monkeypatch):
    slept = []

    monkeypatch.setattr(hz.time, "sleep", lambda s: slept.append(s))
    hz.shop_stage_sleep(1.0, random.Random(0), jitter=True)
    assert slept and 0.85 <= slept[0] <= 1.15
    slept.clear()
    hz.shop_stage_sleep(1.0, random.Random(0), jitter=False)
    assert slept == [1.0]


def test_land_error_scales_with_width():
    rng = random.Random(0)
    small = SimpleNamespace(screen_width=1280)
    large = SimpleNamespace(screen_width=1920)
    ox, oy = ui_aim.land_error_px(small, rng)
    assert abs(ox) ** 2 + abs(oy) ** 2 <= 1.01**2
    ox2, oy2 = ui_aim.land_error_px(large, random.Random(1))
    assert abs(ox2) ** 2 + abs(oy2) ** 2 <= 2.01**2


def test_aim_and_click_uses_budget_and_hold(monkeypatch):
    calls = []

    class FakeMouse:
        screen_width = 1920
        humanize_move = True

        def move_with_budget(
            self, x, y, *, budget_s, steps=None, curve_fraction=None, shop_curves=False
        ):
            calls.append(("approach", x, y, budget_s, shop_curves))

        def move(self, x, y, *, snap=False):
            calls.append(("move", x, y))

        def hold_in_place(self, x, y, duration, button="left"):
            calls.append(("hold", x, y, duration, button))

    monkeypatch.setattr(hz, "SHOP_UI_APPROACH_BUDGET_S", (0.4, 0.4))
    monkeypatch.setattr(hz, "SHOP_UI_APPROACH_STEPS", (4, 4))
    monkeypatch.setattr(hz, "SHOP_UI_FINE_MOVES", (2, 2))
    monkeypatch.setattr(hz, "SHOP_UI_FINE_HOVER_S", (0.0, 0.0))
    monkeypatch.setattr(hz, "SHOP_CLICK_PRE_S", (0.0, 0.0))
    monkeypatch.setattr(hz, "SHOP_UI_CLICK_HOLD_S", (0.12, 0.12))

    ex = SimpleNamespace(humanize=True, mouse=FakeMouse(), _rng=random.Random(3))
    ui_aim.aim_and_click(ex, 100.0, 200.0)
    kinds = [c[0] for c in calls]
    assert "approach" in kinds
    assert "hold" in kinds
    hold = [c for c in calls if c[0] == "hold"][0]
    assert hold[3] == 0.12


def test_aim_and_click_exact_holds_the_pixel(monkeypatch):
    calls = []

    class FakeMouse:
        screen_width = 1920

        def move_with_budget(
            self, x, y, *, budget_s, steps=None, curve_fraction=None, shop_curves=False
        ):
            calls.append(("approach", x, y))

        def hold_in_place(self, x, y, duration, button="left"):
            calls.append(("hold", x, y, duration, button))

    monkeypatch.setattr(hz, "SHOP_UI_APPROACH_BUDGET_S", (0.4, 0.4))
    monkeypatch.setattr(hz, "SHOP_UI_APPROACH_STEPS", (4, 4))
    monkeypatch.setattr(hz, "SHOP_UI_CLICK_HOLD_S", (0.12, 0.12))
    monkeypatch.setattr(hz.time, "sleep", lambda s: calls.append(("sleep", s)))

    ex = SimpleNamespace(humanize=True, mouse=FakeMouse(), _rng=random.Random(3))
    ui_aim.aim_and_click_exact(ex, 100.0, 200.0, hover_s=0.25)
    assert ("sleep", 0.25) in calls
    hold = [c for c in calls if c[0] == "hold"][0]
    assert hold[1] == 100.0 and hold[2] == 200.0
    assert not any(c[0] == "approach" and (c[1], c[2]) != (100.0, 200.0) for c in calls)


def test_click_uv_human_vs_snap(monkeypatch):
    from shop import runtime
    import app._05_action.coordinates as coords

    aimed = []
    snapped = []

    class FakeMouse:
        def move_and_click(self, x, y, snap=True):
            snapped.append((x, y, snap))

    monkeypatch.setattr(
        coords, "game_to_screen", lambda u, v, bounds: (50.0, 60.0)
    )
    monkeypatch.setattr(
        ui_aim, "aim_and_click", lambda ex, sx, sy: aimed.append((sx, sy))
    )

    bounds = SimpleNamespace()
    human_ex = SimpleNamespace(humanize=True, mouse=FakeMouse(), _rng=random.Random(0))
    runtime._click_uv(human_ex, bounds, (0.5, 0.5), wait_s=0.0)
    assert aimed == [(50.0, 60.0)]
    assert snapped == []

    practice = SimpleNamespace(humanize=False, mouse=FakeMouse(), _rng=random.Random(0))
    runtime._click_uv(practice, bounds, (0.5, 0.5), wait_s=0.0)
    assert snapped and snapped[0][2] is True
