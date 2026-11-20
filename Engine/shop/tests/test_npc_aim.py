"""Shop NPC human-aim helpers (no LC / no real mouse driver)."""
from __future__ import annotations

import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app._05_action import humanize as hz  # noqa: E402
from app._05_action.humanize import bezier_points, shop_curve_points  # noqa: E402


def test_combat_move_budget_unchanged():
    assert float(hz.MOVE_BUDGET_S) == 0.02
    assert float(hz.SHOP_APPROACH_BUDGET_S[0]) >= 0.8


def test_bezier_accepts_shop_curve_fraction():
    rng = random.Random(0)
    pts = bezier_points(
        0.0,
        0.0,
        200.0,
        100.0,
        12,
        rng,
        curve_fraction=hz.SHOP_APPROACH_CURVE_FRACTION,
    )
    assert len(pts) == 12
    assert pts[-1] == (200, 100)


def test_shop_curve_styles_vary():
    ends = set()
    styles_seen = []
    for seed in range(40):
        rng = random.Random(seed)
        # Force style by sampling many seeds; paths must end on target.
        pts = shop_curve_points(0.0, 0.0, 200.0, 100.0, 16, rng)
        assert pts[-1] == (200, 100)
        ends.add(tuple(pts[len(pts) // 2]))
    # Midpoints should not all collapse to one mechanical arc.
    assert len(ends) >= 5


def test_approach_uses_move_with_budget(monkeypatch):
    from shop import npc_aim

    calls = []

    class FakeMouse:
        humanize_move = True

        def move_with_budget(self, x, y, *, budget_s, steps=None, curve_fraction=None, shop_curves=False):
            calls.append(
                {
                    "xy": (x, y),
                    "budget_s": budget_s,
                    "steps": steps,
                    "curve_fraction": curve_fraction,
                    "shop_curves": shop_curves,
                }
            )

        def move(self, *a, **k):
            pass

        def hold_in_place(self, *a, **k):
            pass

    ex = SimpleNamespace(humanize=True, mouse=FakeMouse(), _rng=random.Random(1))
    npc_aim.approach_npc(ex, 100.0, 200.0)
    assert len(calls) == 1
    assert calls[0]["budget_s"] >= 0.8
    assert calls[0]["curve_fraction"] == hz.SHOP_APPROACH_CURVE_FRACTION
    assert calls[0]["shop_curves"] is True


def test_fine_confirm_clicks_after_dialog(monkeypatch):
    from shop import npc_aim

    holds = []

    class FakeMouse:
        def move(self, x, y, snap=False):
            pass

        def move_with_budget(self, *a, **k):
            pass

        def hold_in_place(self, x, y, duration, button="left"):
            holds.append((x, y, duration, button))

    states = iter([False, False, True, True])

    def fake_dialog():
        try:
            return next(states)
        except StopIteration:
            return True

    monkeypatch.setattr(npc_aim, "cursor_shows_dialog", fake_dialog)
    monkeypatch.setattr(npc_aim.hz, "SHOP_FINE_MOVES", (4, 4))
    monkeypatch.setattr(npc_aim.hz, "SHOP_FINE_EXTRA_AFTER_DIALOG", (1, 1))
    monkeypatch.setattr(npc_aim.hz, "SHOP_FINE_HOVER_S", (0.0, 0.0))
    monkeypatch.setattr(npc_aim.hz, "SHOP_FINE_HESITATE_S", (0.0, 0.0))
    monkeypatch.setattr(npc_aim.hz, "SHOP_CLICK_PRE_S", (0.0, 0.0))
    monkeypatch.setattr(npc_aim.hz, "SHOP_FINE_RADIUS_PX", (5.0, 5.0))
    monkeypatch.setattr(npc_aim.hz, "SHOP_UI_CLICK_HOLD_S", (0.12, 0.12))

    ex = SimpleNamespace(humanize=True, mouse=FakeMouse(), _rng=random.Random(2))
    assert npc_aim.fine_confirm_dialog_click(ex, 50.0, 60.0) is True
    assert holds
