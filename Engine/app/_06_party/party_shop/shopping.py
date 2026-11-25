"""ShoppingManager — pin behavior, drive shop_trip, buy qty chain."""
from __future__ import annotations

from .duty import (
    note_supply_shop_finished,
    release_finished_party_shop,
    shops_arrow_id,
    supply_shop_id,
)

# Private buy/join ticks stay on duty; facade calls tick_shopkeeper_duty.
from .duty import _tick_buy, _tick_join  # noqa: F401

__all__ = [
    "note_supply_shop_finished",
    "release_finished_party_shop",
    "shops_arrow_id",
    "supply_shop_id",
]
