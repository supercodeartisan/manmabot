"""Sell/store keep filter: Korean keep_list must protect Chinese live names."""
from __future__ import annotations

from shop.behaviors import (
    item_passes_sell_filter,
    load_sell_filters,
)


def test_chinese_catalog_names_respect_korean_keep_list() -> None:
    filters = load_sell_filters()
    assert filters.keep_list
    # Catalog ZH for keep entry ``맑은 물약``.
    assert (
        item_passes_sell_filter(
            "白色藥水",
            sell_mode="sell_except_keep",
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
        )
        is False
    )
    assert (
        item_passes_sell_filter(
            "白色药水",
            sell_mode="sell_except_keep",
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
        )
        is False
    )
    # Catalog ZH for keep entry ``마력의 돌``.
    assert (
        item_passes_sell_filter(
            "魔法寶石",
            sell_mode="sell_except_keep",
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
        )
        is False
    )


def test_adena_never_passes_in_any_locale() -> None:
    filters = load_sell_filters()
    for name, item_id in (
        ("아데나", 0),
        ("Adena", 0),
        ("金幣", 0),
        ("金币", 0),
        ("", 5),
        ("", 7),
        ("junk", 7),
    ):
        assert (
            item_passes_sell_filter(
                name,
                sell_mode="sell_except_keep",
                garbage_list=filters.garbage_list,
                keep_list=filters.keep_list,
                item_id=item_id,
            )
            is False
        ), (name, item_id)


def test_keep_by_catalog_id_when_name_empty() -> None:
    filters = load_sell_filters()
    # ``맑은 물약`` catalog id 130 — empty name must still keep.
    assert (
        item_passes_sell_filter(
            "",
            sell_mode="sell_except_keep",
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
            item_id=130,
        )
        is False
    )
    # Unknown id with no name is not sold/stored.
    assert (
        item_passes_sell_filter(
            "",
            sell_mode="sell_except_keep",
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
            item_id=0,
        )
        is False
    )


def test_non_keep_chinese_name_still_sells() -> None:
    filters = load_sell_filters()
    # Name that is not on the keep list and not Adena.
    assert (
        item_passes_sell_filter(
            "未知垃圾物",
            sell_mode="sell_except_keep",
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
        )
        is True
    )


def test_talking_scroll_zh_and_ids_kept() -> None:
    """Scroll is keep-listed in Korean but absent from game_catalog."""
    filters = load_sell_filters()
    assert "말하는 두루마리" in filters.keep_list
    for name in (
        "說話的卷軸",
        "说话的卷轴",
        "說話卷軸",
        "说话卷轴",
        "Talking Scroll",
    ):
        assert (
            item_passes_sell_filter(
                name,
                sell_mode="sell_except_keep",
                garbage_list=filters.garbage_list,
                keep_list=filters.keep_list,
            )
            is False
        ), name
    for item_id in (16673, 16222, 16977):
        assert (
            item_passes_sell_filter(
                "",
                sell_mode="sell_except_keep",
                garbage_list=filters.garbage_list,
                keep_list=filters.keep_list,
                item_id=item_id,
            )
            is False
        ), item_id
