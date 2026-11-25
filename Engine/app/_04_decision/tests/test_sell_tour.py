"""Sell tour: random merchant order + early stop by weight."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app._04_decision import shops as shops_mod  # noqa: E402
from app._04_decision.shop_trip import (  # noqa: E402
    GIVE_GOODS_CH_ID,
    GIVE_GOODS_ID,
    SCRATCH_SELL_QUEUE,
    SCRATCH_SHOP_BEHAVIOR,
    SCRATCH_SHOP_TRIP,
    _shuffled_sell_ids,
    advance_sell_trip,
    sell_tour_weight_done,
    store_after_sell_weight_ok,
)
from app._04_decision.shops import (  # noqa: E402
    is_store_behavior,
    resolve_store_behavior_id,
)


def _board(**scratch):
    from app._04_decision.player_mode import PlayerMode

    return SimpleNamespace(
        scratch=dict(scratch),
        player_mode=PlayerMode.SHOPPING,
    )


def _state(weight: float, *, bag_ready: bool = True, items=None):
    inv = SimpleNamespace(
        weight_ratio=weight,
        bag_ready=bag_ready,
        items=list(items or []),
    )
    return SimpleNamespace(player=SimpleNamespace(inventory=inv))


def _leftover_item():
    return SimpleNamespace(name="Junk Ore", item_id=999001)


def test_shuffled_sell_ids_is_permutation_of_four():
    ids = list(shops_mod.resolve_sell_behavior_ids())
    with mock.patch("app._04_decision.shop_trip.random.sample", side_effect=lambda xs, k: list(reversed(xs))):
        out = _shuffled_sell_ids()
    assert sorted(out) == sorted(ids)
    assert out == list(reversed(ids))


def test_sell_tour_weight_done_at_35():
    shops_mod.SELL_STOP_BELOW_RATIO = 0.35
    assert sell_tour_weight_done(_state(0.34)) is True
    assert sell_tour_weight_done(_state(0.35)) is False
    assert sell_tour_weight_done(_state(0.70)) is False


def test_advance_skips_remaining_when_weight_light():
    shops_mod.SELL_STOP_BELOW_RATIO = 0.35
    shops_mod.STORE_AFTER_SELL = False
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep",
            SCRATCH_SELL_QUEUE: ["sell_except_keep_weapon", "sell_except_keep_mainland"],
        }
    )
    nxt = advance_sell_trip(board, _state(0.20))
    assert nxt is None
    assert SCRATCH_SHOP_TRIP not in board.scratch or not board.scratch.get(SCRATCH_SHOP_TRIP)
    assert board.scratch.get(SCRATCH_SELL_QUEUE) in (None, [])


def test_advance_continues_when_weight_still_heavy():
    shops_mod.SELL_STOP_BELOW_RATIO = 0.35
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep",
            SCRATCH_SELL_QUEUE: ["sell_except_keep_weapon", "sell_except_keep_mainland"],
        }
    )
    nxt = advance_sell_trip(board, _state(0.55))
    assert nxt == "sell_except_keep_weapon"
    assert board.scratch[SCRATCH_SHOP_BEHAVIOR] == "sell_except_keep_weapon"
    assert board.scratch[SCRATCH_SELL_QUEUE] == ["sell_except_keep_mainland"]


def test_schedule_sell_weight_settle_defers_advance():
    from app._04_decision.shop_trip import (
        SCRATCH_SELL_ADVANCE_PENDING,
        SCRATCH_SELL_DECIDE_PENDING,
        finish_sell_weight_settle,
        schedule_sell_weight_settle,
    )

    shops_mod.SELL_WEIGHT_SETTLE_S = (0.05, 0.05)
    shops_mod.SELL_DECIDE_JITTER_S = (0.05, 0.05)
    shops_mod.SELL_STOP_BELOW_RATIO = 0.35
    shops_mod.STORE_AFTER_SELL = False
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep",
            SCRATCH_SELL_QUEUE: ["sell_except_keep_weapon"],
        }
    )
    schedule_sell_weight_settle(board)
    assert board.scratch.get(SCRATCH_SELL_ADVANCE_PENDING) is True
    assert finish_sell_weight_settle(board, _state(0.20)) is True
    import time

    time.sleep(0.06)
    # Settle elapsed → decide jitter armed; still holding.
    assert finish_sell_weight_settle(board, _state(0.20)) is True
    assert board.scratch.get(SCRATCH_SELL_ADVANCE_PENDING) in (None, False)
    assert board.scratch.get(SCRATCH_SELL_DECIDE_PENDING) is True
    time.sleep(0.06)
    assert finish_sell_weight_settle(board, _state(0.20)) is False
    assert board.scratch.get(SCRATCH_SELL_DECIDE_PENDING) in (None, False)
    assert not board.scratch.get(SCRATCH_SHOP_TRIP)


def test_store_after_sell_weight_ok_at_40():
    shops_mod.STORE_AFTER_SELL_MIN_RATIO = 0.40
    assert store_after_sell_weight_ok(_state(0.39)) is False
    assert store_after_sell_weight_ok(_state(0.40)) is True
    assert store_after_sell_weight_ok(_state(0.40, bag_ready=False)) is False


def test_resolve_store_behavior_id_by_locale():
    prev = shops_mod.SHOP_LOCALE
    try:
        shops_mod.SHOP_LOCALE = "ko"
        assert resolve_store_behavior_id() == GIVE_GOODS_ID
        shops_mod.SHOP_LOCALE = "zh"
        assert resolve_store_behavior_id() == GIVE_GOODS_CH_ID
    finally:
        shops_mod.SHOP_LOCALE = prev
    assert is_store_behavior(GIVE_GOODS_ID)
    assert is_store_behavior(GIVE_GOODS_CH_ID)
    assert not is_store_behavior("sell_except_keep_ch")


def test_advance_give_goods_when_heavy_with_leftovers():
    shops_mod.STORE_AFTER_SELL = True
    shops_mod.STORE_AFTER_SELL_MIN_RATIO = 0.40
    shops_mod.SELL_STOP_BELOW_RATIO = 0.35
    shops_mod.SHOP_LOCALE = "ko"
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep",
            SCRATCH_SELL_QUEUE: [],
        }
    )
    with mock.patch(
        "app._04_decision.shop_trip._bag_needs_give_goods", return_value=True
    ):
        nxt = advance_sell_trip(board, _state(0.50, items=[_leftover_item()]))
    assert nxt == GIVE_GOODS_ID
    assert board.scratch[SCRATCH_SHOP_BEHAVIOR] == GIVE_GOODS_ID


def test_advance_give_goods_ch_when_locale_zh():
    shops_mod.STORE_AFTER_SELL = True
    shops_mod.STORE_AFTER_SELL_MIN_RATIO = 0.40
    shops_mod.SELL_STOP_BELOW_RATIO = 0.35
    prev = shops_mod.SHOP_LOCALE
    shops_mod.SHOP_LOCALE = "zh"
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep_ch",
            SCRATCH_SELL_QUEUE: [],
        }
    )
    try:
        with mock.patch(
            "app._04_decision.shop_trip._bag_needs_give_goods", return_value=True
        ):
            nxt = advance_sell_trip(board, _state(0.50, items=[_leftover_item()]))
    finally:
        shops_mod.SHOP_LOCALE = prev
    assert nxt == GIVE_GOODS_CH_ID
    assert board.scratch[SCRATCH_SHOP_BEHAVIOR] == GIVE_GOODS_CH_ID


def test_advance_skips_give_goods_when_weight_under_40():
    shops_mod.STORE_AFTER_SELL = True
    shops_mod.STORE_AFTER_SELL_MIN_RATIO = 0.40
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep",
            SCRATCH_SELL_QUEUE: [],
        }
    )
    with mock.patch(
        "app._04_decision.shop_trip._bag_needs_give_goods", return_value=True
    ):
        nxt = advance_sell_trip(board, _state(0.20, items=[_leftover_item()]))
    assert nxt is None
    assert not board.scratch.get(SCRATCH_SHOP_TRIP)


def test_advance_skips_give_goods_when_bag_unread():
    shops_mod.STORE_AFTER_SELL = True
    shops_mod.STORE_AFTER_SELL_MIN_RATIO = 0.40
    board = _board(
        **{
            SCRATCH_SHOP_TRIP: True,
            SCRATCH_SHOP_BEHAVIOR: "sell_except_keep",
            SCRATCH_SELL_QUEUE: [],
        }
    )
    nxt = advance_sell_trip(board, _state(0.55, bag_ready=False, items=[_leftover_item()]))
    assert nxt is None
    assert not board.scratch.get(SCRATCH_SHOP_TRIP)
