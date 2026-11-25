"""Display-name sort key for Korean dictionary (jamo) order.

Hangul syllables are decomposed with NFKD so 가/각/나 sort by choseong→jungseong→jongseong,
matching typical Korean UI lists. Latin and digits fall through normally.
"""

from __future__ import annotations

import unicodedata
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def hangul_sort_key(text: object) -> tuple[str, str]:
    raw = str(text or "")
    return (unicodedata.normalize("NFKD", raw).casefold(), raw.casefold())


# Battle-map picker pins these packs above the jamo list, in this order.
_PINNED_MAP_IDS = (
    "talking_island",
    "mainland",
    "polluted_land_of_blessing_fairy",
    "polluted_land_of_blessing_human",
    "polluted_land_of_blessing_orch",
    "polluted_land_of_blessing_spirit",
    "corrupted_land_of_blessing_spring_fairy",
    "corrupted_land_of_blessing_spring_human",
    "corrupted_land_of_blessing_spring_orch",
    "corrupted_land_of_blessing_spring_spirit",
    "corrupted_land_of_blessing_summer_fairy",
    "corrupted_land_of_blessing_summer_human",
    "corrupted_land_of_blessing_summer_orch",
    "corrupted_land_of_blessing_summer_spirit",
    "corrupted_land_of_blessing_autumn_fairy",
    "corrupted_land_of_blessing_autumn_human",
    "corrupted_land_of_blessing_autumn_orch",
    "corrupted_land_of_blessing_autumn_spirit",
    "corrupted_land_of_blessing_winter_fairy",
    "corrupted_land_of_blessing_winter_human",
    "corrupted_land_of_blessing_winter_orch",
    "corrupted_land_of_blessing_winter_spirit",
)


def map_choice_sort_key(item: tuple) -> tuple:
    """Talking Island, Mainland, blessing lands, then the rest in jamo order."""
    map_id = str(item[0] if item else "")
    label = item[1] if len(item) > 1 else ""
    try:
        pin = _PINNED_MAP_IDS.index(map_id)
    except ValueError:
        pin = len(_PINNED_MAP_IDS)
    return (pin, *hangul_sort_key(label))


def sorted_by_hangul(
    items: Iterable[T],
    *,
    key: Callable[[T], object],
) -> list[T]:
    return sorted(items, key=lambda item: hangul_sort_key(key(item)))
