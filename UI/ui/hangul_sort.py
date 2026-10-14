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


def sorted_by_hangul(
    items: Iterable[T],
    *,
    key: Callable[[T], object],
) -> list[T]:
    return sorted(items, key=lambda item: hangul_sort_key(key(item)))
