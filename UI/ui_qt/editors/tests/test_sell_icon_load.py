"""Sell table paints before icon files are opened."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app._03_world.catalog.game_catalog import ItemCatalogRow
from settings.profile import Profile
from ui_qt.editors import sell_icon_loader
from ui_qt.editors.equipment_tab import EquipmentTab
from ui_qt.viewmodels.settings_bag import SettingsBag

_APP = QApplication.instance() or QApplication([])


def _row(name: str, category: str = "검") -> ItemCatalogRow:
    return ItemCatalogRow(
        key=name,
        name_ko=name,
        name_zh="",
        name_zh_cn="",
        category_ko=category,
        category_zh="",
        category_zh_cn="",
        ids=(1,),
        name2="",
    )


def _tab(rows: list[ItemCatalogRow]) -> EquipmentTab:
    import app._03_world.catalog.game_catalog as catalog

    catalog.list_item_rows = lambda: tuple(rows)  # type: ignore[assignment]
    tab = EquipmentTab(bag=SettingsBag(Profile()), strings={}, language="ko")
    tab._reload_sell_owned = lambda: None  # type: ignore[method-assign]
    return tab


def test_table_shows_before_icon_resolve() -> None:
    calls: list[str] = []

    def slow(names, ids):
        calls.append(str(next(iter(names), "")))
        time.sleep(0.08)
        return None

    sell_icon_loader.resolve_sell_icon_path = slow  # type: ignore[assignment]
    sell_icon_loader._template_index = {}
    tab = _tab([_row("목검"), _row("단검"), _row("장검")])
    started = time.perf_counter()
    tab.tabs.setCurrentIndex(1)
    shown = time.perf_counter() - started
    assert tab.sell_table.rowCount() == 3
    assert shown < 1.0
    assert calls == []
    from PySide6.QtCore import Qt

    names = [tab.sell_table.item(row, 3).text() for row in range(3)]
    assert names == sorted(names, key=str.lower)
    keys = [
        str(tab.sell_table.item(row, 0).data(Qt.ItemDataRole.UserRole) or "")
        for row in range(3)
    ]
    assert set(keys) == {"목검", "단검", "장검"}
    deadline = time.perf_counter() + 3.0
    while tab._sell_icons.applied < 3 and time.perf_counter() < deadline:
        _APP.processEvents()
        time.sleep(0.01)
    assert tab._sell_icons.applied == 3
    assert len(calls) == 3


def test_keep_toggle_does_not_wait_for_icons(monkeypatch=None) -> None:
    saved: list[object] = []

    def slow(names, ids):
        time.sleep(0.2)
        return None

    sell_icon_loader.resolve_sell_icon_path = slow  # type: ignore[assignment]
    import ui_qt.editors.equipment_tab as equipment_tab

    equipment_tab.save_behaviors = lambda *_a, **_k: saved.append(True)  # type: ignore[assignment]
    tab = _tab([_row("활")])
    tab.tabs.setCurrentIndex(1)
    assert tab.sell_table.rowCount() == 1
    tab.sell_table.selectRow(0)
    tab._toggle_keep()
    assert "활" in tab._keep
    assert saved


def test_second_pass_reuses_the_pixmap_cache() -> None:
    folder = Path(tempfile.mkdtemp())
    png = folder / "ring.png"
    from PIL import Image

    Image.new("RGBA", (12, 12), (10, 20, 30, 255)).save(png)
    calls: list[int] = []

    def resolve(names, ids):
        calls.append(1)
        return png

    sell_icon_loader.resolve_sell_icon_path = resolve  # type: ignore[assignment]
    tab = _tab([_row("반지")])
    tab.tabs.setCurrentIndex(1)
    deadline = time.perf_counter() + 3.0
    while tab._sell_icons.applied < 1 and time.perf_counter() < deadline:
        _APP.processEvents()
        time.sleep(0.01)
    assert tab._sell_icons.applied == 1
    before = len(calls)
    started = time.perf_counter()
    tab._refresh_sell_rows()
    elapsed = time.perf_counter() - started
    _APP.processEvents()
    assert elapsed < 1.0
    assert len(calls) == before
    assert tab._sell_icons.cached("반지") is not None


def test_leaving_the_tab_drops_a_late_result() -> None:
    gate = {"go": False}

    def blocked(names, ids):
        while not gate["go"]:
            time.sleep(0.01)
        return None

    sell_icon_loader.resolve_sell_icon_path = blocked  # type: ignore[assignment]
    tab = _tab([_row("방패")])
    tab.tabs.setCurrentIndex(1)
    _APP.processEvents()
    tab.tabs.setCurrentIndex(0)
    gate["go"] = True
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        _APP.processEvents()
        time.sleep(0.01)
    assert tab._sell_icons.generation >= 1


if __name__ == "__main__":
    test_table_shows_before_icon_resolve()
    test_keep_toggle_does_not_wait_for_icons()
    test_second_pass_reuses_the_pixmap_cache()
    test_leaving_the_tab_drops_a_late_result()
    print("OK")
