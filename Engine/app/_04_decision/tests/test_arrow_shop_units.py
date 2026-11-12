"""Shop dialog digits for arrow buys. Profile counts stay in arrows."""
from __future__ import annotations

from app._04_decision import shops


def test_arrow_bundles_match_the_shop_field() -> None:
    assert shops.arrow_shop_units("buy_silver_arrows_mainland", 200) == 40
    assert shops.arrow_shop_units("buy_normal_arrows_talking", 200) == 20
    assert shops.arrow_shop_units("buy_silver_arrows_ch_mainland", 203) == 40
    assert shops.arrow_shop_units("buy_normal_arrows_ch_talking", 19) == 1
    assert shops.arrow_shop_units("buy_silver_arrows_mainland", 3) == 1
    assert shops.arrow_shop_units("buy_hp_potions_mainland", 10) is None


def test_buy_qty_types_bundles_and_leaves_potions() -> None:
    old_silver = shops.SILVER_ARROW_BUY_QTY
    old_normal = shops.ARROW_BUY_QTY
    old_hp = shops.HP_POTION_BUY_QTY
    try:
        shops.SILVER_ARROW_BUY_QTY = 200
        shops.ARROW_BUY_QTY = 200
        shops.HP_POTION_BUY_QTY = 10
        assert shops.buy_qty_for_behavior("buy_silver_arrows_mainland") == 40
        assert shops.buy_qty_for_behavior("buy_normal_arrows_talking") == 20
        assert shops.buy_qty_for_behavior("buy_hp_potions_talking") == 10
        assert shops.buy_qty_for_behavior("buy_depoison_potions") is not None
    finally:
        shops.SILVER_ARROW_BUY_QTY = old_silver
        shops.ARROW_BUY_QTY = old_normal
        shops.HP_POTION_BUY_QTY = old_hp
