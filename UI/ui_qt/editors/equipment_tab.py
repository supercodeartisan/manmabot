"""Equipment tab — buy / sell keep-list / routing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n.localized_names import (
    item_catalog_display_name,
    item_category_display_name,
    memory_name_for_ui,
    scroll_label_display,
)
from shop.behaviors import ShoppingSellFilters, load_behaviors, load_sell_filters, save_behaviors
from ui_qt.editors.form_helpers import (
    add_check,
    add_check_spin,
    add_spin_row,
    bind_gate,
    card,
    configure_select_rows,
    configure_table_fill,
)
from ui_qt.editors.sell_icon_loader import SellIconLoader
from ui_qt.icon_helpers import HUNT_ICON_SIZE
from ui_qt.theme import tokens
from ui_qt.viewmodels.settings_bag import SettingsBag


@dataclass
class _SellRow:
    key: str
    name: str
    category: str
    is_own: bool
    icon: Path | None = None
    source_category: str = ""
    icon_names: tuple[str, ...] = ()
    icon_ids: tuple[int, ...] = ()


class _SellInventoryWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            from app._01_perception.inventory_listen_reader import shared_inventory

            reader = shared_inventory()
            if not reader.dll_loaded:
                self.failed.emit("inventory_listen.dll missing")
                return
            snap = reader.snapshot()
            if snap is None:
                self.failed.emit("empty snapshot (is LC.exe running?)")
                return
            self.finished_ok.emit(snap)
        except Exception as exc:
            self.failed.emit(str(exc))


class EquipmentTab(QWidget):
    def __init__(
        self,
        *,
        bag: SettingsBag,
        strings: dict[str, str],
        language: str,
        on_log: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bag = bag
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self._sell_built = False
        self._keep: set[str] = set()
        self._catalog_rows: list[_SellRow] = []
        self._owned_rows: list[_SellRow] = []
        self._owned_keys: set[str] = set()
        self._sell_worker: _SellInventoryWorker | None = None
        self._sell_icons = SellIconLoader(self)
        self._sell_icons.updated.connect(self._apply_sell_icon)
        self._sell_icon_rows: dict[str, list[int]] = {}
        self._sell_filling = False
        self.destroyed.connect(self._sell_icons.shutdown)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        self.tabs = tabs
        self.buy_page = QWidget()
        self.sell_page = QWidget()
        self.routing_page = QWidget()
        tabs.addTab(self.buy_page, self.t.get("buy", "Buy"))
        tabs.addTab(self.sell_page, self.t.get("sell", "Sell"))
        tabs.addTab(self.routing_page, self.t.get("routing", "Routing"))
        tabs.currentChanged.connect(self._on_tab)
        root.addWidget(tabs)
        self._build_buy(self.buy_page)
        self._build_routing(self.routing_page)
        layout = QVBoxLayout(self.sell_page)
        layout.addWidget(QLabel(self.t.get("sell_items", "Sell items")))
        layout.addStretch(1)

    def _on_tab(self, index: int) -> None:
        if index == 1 and not self._sell_built:
            layout = self.sell_page.layout()
            if layout is not None:
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
            self._build_sell(self.sell_page)
            self._sell_built = True
            self._reload_sell_owned()
            return
        if self._sell_built and index != 1:
            self._sell_icons.cancel()
            return
        if self._sell_built and index == 1:
            QTimer.singleShot(0, self._queue_visible_sell_icons)

    def _build_buy(self, page: QWidget) -> None:
        body = QHBoxLayout(page)
        left = QVBoxLayout()
        right = QVBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(right, 1)

        arrows = card(page, self.t.get("buy_arrows", "Arrows"))
        left.addWidget(arrows)
        a = arrows.layout()
        assert isinstance(a, QVBoxLayout)
        self._buy_arrows = add_check(
            a, self.bag, "equipment", "buy_arrows",
            self.t.get("buy_arrows", "Buy arrows"), True, self._sync_buy_arrow_gates,
        )
        kind_row = QHBoxLayout()
        self._arrow_group = QButtonGroup(self)
        self._arrow_radios: list[QRadioButton] = []
        silver = self.bag.get_bool("equipment", "buy_silver_arrows", True)
        for value, label_key in (
            ("normal", "buy_normal_arrows"),
            ("silver", "buy_silver_arrows"),
        ):
            radio = QRadioButton(self.t.get(label_key, value))
            radio.setChecked((value == "silver") if silver else (value == "normal"))
            self._arrow_group.addButton(radio)
            self._arrow_radios.append(radio)
            radio.toggled.connect(
                lambda checked, v=value: checked and self._set_arrow_kind(v)
            )
            kind_row.addWidget(radio)
        kind_row.addStretch(1)
        a.addLayout(kind_row)
        self._arrow_qty = add_spin_row(
            a, self.bag, "equipment", "arrow_quantity",
            self.t.get("normal_arrow_qty", "Normal qty"), 200, 1, 999,
            on_change=self._refresh_buy_summary,
        )
        self._silver_qty = add_spin_row(
            a, self.bag, "equipment", "silver_arrow_quantity",
            self.t.get("silver_arrow_qty", "Silver qty"), 200, 1, 999,
            on_change=self._refresh_buy_summary,
        )

        potions = card(page, self.t.get("buy_portion", "Potions"))
        left.addWidget(potions)
        p = potions.layout()
        assert isinstance(p, QVBoxLayout)
        restock = add_check(
            p, self.bag, "equipment", "restock_potions",
            self.t.get("restock", "Restock"), True, self._refresh_buy_summary,
        )
        potion_qty = add_spin_row(
            p, self.bag, "equipment", "buy_portion",
            self.t.get("hp_potion_buy_qty", "HP qty"), 10, 1, 999,
            on_change=self._refresh_buy_summary,
        )
        depoison = add_check(
            p, self.bag, "equipment", "buy_depoison",
            self.t.get("buy_depoison", "Depoison"), False, self._refresh_buy_summary,
        )
        depoison_qty = add_spin_row(
            p, self.bag, "equipment", "depoison_quantity",
            self.t.get("depoison_qty", "Depoison qty"), 1, 1, 999,
            on_change=self._refresh_buy_summary,
        )
        self._restock = restock
        self._potion_qty = potion_qty
        self._depoison = depoison
        self._depoison_qty = depoison_qty
        bind_gate(restock, potion_qty)
        bind_gate(depoison, depoison_qty)
        npc_row = QHBoxLayout()
        npc_row.addWidget(QLabel(self.t.get("return_potion_npc", "NPC")))
        self.npc_edit = QLineEdit(self.bag.get_str("equipment", "hp_potion_npc", ""))
        self.npc_edit.textChanged.connect(self._on_npc_changed)
        npc_row.addWidget(self.npc_edit, stretch=1)
        pick = QPushButton("...")
        pick.setFixedWidth(36)
        pick.clicked.connect(self._pick_npc)
        npc_row.addWidget(pick)
        p.addLayout(npc_row)
        left.addStretch(1)

        summary = card(page, self.t.get("settings_summary", "Summary"))
        right.addWidget(summary)
        s = summary.layout()
        assert isinstance(s, QVBoxLayout)
        self.buy_summary = QTextEdit()
        self.buy_summary.setReadOnly(True)
        s.addWidget(self.buy_summary)
        self._set_arrow_kind("silver" if silver else "normal")
        self._sync_buy_arrow_gates()
        self._refresh_buy_summary()

    def reload_from_bag(self) -> None:
        """Push the saved bag back into the buy controls after a task load."""
        if not hasattr(self, "_buy_arrows"):
            return
        silver = self.bag.get_bool("equipment", "buy_silver_arrows", True)
        widgets = [
            self._buy_arrows,
            self._arrow_qty,
            self._silver_qty,
            self._restock,
            self._potion_qty,
            self._depoison,
            self._depoison_qty,
            self.npc_edit,
            *self._arrow_radios,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self._buy_arrows.setChecked(self.bag.get_bool("equipment", "buy_arrows", True))
            for radio, value in zip(self._arrow_radios, ("normal", "silver")):
                radio.setChecked(value == ("silver" if silver else "normal"))
            self._arrow_qty.setValue(self.bag.get_int("equipment", "arrow_quantity", 200))
            self._silver_qty.setValue(
                self.bag.get_int("equipment", "silver_arrow_quantity", 200)
            )
            restock_on = self.bag.get_bool("equipment", "restock_potions", True)
            self._restock.setChecked(restock_on)
            self._potion_qty.setValue(self.bag.get_int("equipment", "buy_portion", 10))
            self._potion_qty.setEnabled(restock_on)
            depoison_on = self.bag.get_bool("equipment", "buy_depoison", False)
            self._depoison.setChecked(depoison_on)
            self._depoison_qty.setValue(self.bag.get_int("equipment", "depoison_quantity", 1))
            self._depoison_qty.setEnabled(depoison_on)
            self.npc_edit.setText(self.bag.get_str("equipment", "hp_potion_npc", ""))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self._sync_buy_arrow_gates()

    def _sync_buy_arrow_gates(self) -> None:
        on = bool(self._buy_arrows.isChecked())
        for radio in getattr(self, "_arrow_radios", []):
            radio.setEnabled(on)
        silver = self.bag.get_bool("equipment", "buy_silver_arrows", True)
        if hasattr(self, "_arrow_qty"):
            self._arrow_qty.setEnabled(on and not silver)
        if hasattr(self, "_silver_qty"):
            self._silver_qty.setEnabled(on and silver)
        self._refresh_buy_summary()

    def _set_arrow_kind(self, kind: str) -> None:
        self.bag.set("equipment", "buy_normal_arrows", kind != "silver")
        self.bag.set("equipment", "buy_silver_arrows", kind == "silver")
        self._sync_buy_arrow_gates()

    def _on_npc_changed(self, text: str) -> None:
        self.bag.set("equipment", "hp_potion_npc", text)
        self.bag.set("hunt", "return_potion_npc", text)
        self._refresh_buy_summary()

    def _npc_choices(self) -> list[str]:
        try:
            from app._04_decision.talking_scroll import ROWS
        except Exception:
            return []
        region = ""
        choices: list[str] = []
        for spot in ROWS:
            kind = spot.get("kind")
            if kind == "header" and spot.get("region") not in ("title", "favorites"):
                region = scroll_label_display(str(spot.get("label") or ""), self.language)
                continue
            if kind != "spot" or "shop" not in (spot.get("roles") or ()):
                continue
            label = scroll_label_display(str(spot.get("label") or ""), self.language)
            choices.append(f"{region} / {label}" if region else label)
        return choices

    def _pick_npc(self) -> None:
        choices = self._npc_choices()
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t.get("pick_npc", "Pick NPC"))
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for item in choices:
            listing.addItem(item)
        current = self.npc_edit.text().strip()
        if current in choices:
            listing.setCurrentRow(choices.index(current))
        layout.addWidget(listing)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        listing.itemDoubleClicked.connect(lambda _item: dialog.accept())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row = listing.currentRow()
        if row < 0 or row >= len(choices):
            return
        self.npc_edit.setText(choices[row])

    def _refresh_buy_summary(self) -> None:
        if not hasattr(self, "buy_summary"):
            return

        def state(key: str) -> str:
            return (
                self.t.get("summary_on", "ON")
                if self.bag.get_bool("equipment", key)
                else self.t.get("summary_off", "OFF")
            )

        lines = [f"{self.t.get('buy_arrows', 'Arrows')}: {state('buy_arrows')}"]
        if self.bag.get_bool("equipment", "buy_arrows", True):
            if self.bag.get_bool("equipment", "buy_silver_arrows", True):
                lines.append(
                    f"{self.t.get('buy_silver_arrows', 'Silver')}: "
                    f"{self.bag.get_int('equipment', 'silver_arrow_quantity', 200)}"
                )
            else:
                lines.append(
                    f"{self.t.get('buy_normal_arrows', 'Normal')}: "
                    f"{self.bag.get_int('equipment', 'arrow_quantity', 200)}"
                )
        lines.append(f"{self.t.get('restock', 'Restock')}: {state('restock_potions')}")
        if self.bag.get_bool("equipment", "restock_potions", True):
            lines.append(
                f"{self.t.get('hp_potion_buy_qty', 'HP')}: "
                f"{self.bag.get_int('equipment', 'buy_portion', 10)}"
            )
        lines.append(f"{self.t.get('buy_depoison', 'Depoison')}: {state('buy_depoison')}")
        npc = self.bag.get_str("equipment", "hp_potion_npc", "")
        if npc:
            lines.append(f"{self.t.get('return_potion_npc', 'NPC')}: {npc}")
        self.buy_summary.setPlainText("\n".join(f"• {line}" for line in lines))

    def _own_label(self) -> str:
        return str(self.t.get("filter_own", "Own"))

    @staticmethod
    def _icon_names(entry: object) -> tuple[str, ...]:
        names: list[str] = []
        for attr in ("name_ko", "name2", "name_zh", "name_zh_cn"):
            text = str(getattr(entry, attr, "") or "").strip()
            if text and text not in names:
                names.append(text)
        return tuple(names)

    @staticmethod
    def _icon_ids(entry: object) -> tuple[int, ...]:
        found: list[int] = []
        for raw in getattr(entry, "ids", ()) or ():
            try:
                found.append(int(raw))
            except (TypeError, ValueError):
                continue
        return tuple(found)

    def _build_sell(self, page: QWidget) -> None:
        layout = page.layout() or QVBoxLayout(page)
        settings = card(page, self.t.get("sell_settings", "Sell"))
        layout.addWidget(settings)
        s = settings.layout()
        assert isinstance(s, QVBoxLayout)
        mode_note = QLabel(self.t.get("sell_except_keep", "Sell except keep"))
        mode_note.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        s.addWidget(mode_note)
        self.bag.set("equipment", "sell_mode", "sell_except_keep")
        add_check(
            s, self.bag, "equipment", "store_after_sell",
            self.t.get("store_after_sell", "Store after sell"), True,
            self._refresh_sell_summary,
        )

        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, stretch=1)
        left = QWidget()
        right = QWidget()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        col = QVBoxLayout(left)

        hint = QLabel(self.t.get("sell_logic_hint", self.t.get("sell_filter_hint", "")))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        col.addWidget(hint)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(self.t.get("filter_search", "Search")))
        self.sell_search = QLineEdit()
        self.sell_search.textChanged.connect(self._refresh_sell_rows)
        bar.addWidget(self.sell_search, stretch=1)
        bar.addWidget(QLabel(self.t.get("filter_category", "Category")))
        self.sell_category = QComboBox()
        self.sell_category.currentIndexChanged.connect(lambda _i: self._refresh_sell_rows())
        bar.addWidget(self.sell_category)
        bar.addWidget(QLabel(self.t.get("filter_show", "Show")))
        self.sell_show = QComboBox()
        own_label = self._own_label()
        for label, key in (
            (self.t.get("filter_all", "All"), "all"),
            (own_label, "own"),
            (self.t.get("filter_save", self.t.get("filter_keep", "Keep")), "keep"),
            (self.t.get("filter_unmarked", "Unmarked"), "unmarked"),
        ):
            self.sell_show.addItem(label, key)
        self.sell_show.currentIndexChanged.connect(lambda _i: self._refresh_sell_rows())
        bar.addWidget(self.sell_show)
        self.sell_reload_btn = QPushButton(
            self.t.get("sell_reload_inventory", self.t.get("inventory_refresh", "Reload"))
        )
        self.sell_reload_btn.clicked.connect(self._reload_sell_owned)
        bar.addWidget(self.sell_reload_btn)
        self.sell_count = QLabel("")
        self.sell_count.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        bar.addWidget(self.sell_count)
        col.addLayout(bar)

        self.sell_table = QTableWidget(0, 4)
        self.sell_table.setHorizontalHeaderLabels(
            [
                "",
                self.t.get("filter_keep", "Keep"),
                self.t.get("filter_category", "Category"),
                self.t.get("col_name", "Name"),
            ]
        )
        self.sell_table.verticalHeader().setVisible(False)
        self.sell_table.setIconSize(QSize(HUNT_ICON_SIZE, HUNT_ICON_SIZE))
        self.sell_table.verticalHeader().setDefaultSectionSize(HUNT_ICON_SIZE + 6)
        configure_select_rows(self.sell_table)
        configure_table_fill(
            self.sell_table, stretch_col=3, fixed={0: HUNT_ICON_SIZE + 8}
        )
        self.sell_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sell_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sell_table.doubleClicked.connect(self._toggle_keep)
        sell_bar = self.sell_table.verticalScrollBar()
        sell_bar.valueChanged.connect(self._on_sell_scroll)
        sell_bar.rangeChanged.connect(lambda _lo, _hi: self._on_sell_scroll())
        col.addWidget(self.sell_table, stretch=1)

        actions = QHBoxLayout()
        toggle = QPushButton(self.t.get("toggle", "Toggle keep"))
        toggle.clicked.connect(self._toggle_keep)
        save = QPushButton(self.t.get("filter_saved", "Save keep list"))
        save.clicked.connect(self._persist_sell)
        self.sell_status = QLabel("")
        self.sell_status.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        actions.addWidget(toggle)
        actions.addWidget(save)
        actions.addStretch(1)
        actions.addWidget(self.sell_status)
        col.addLayout(actions)

        rcol = QVBoxLayout(right)
        rcol.addWidget(QLabel(self.t.get("settings_summary", "Summary")))
        self.sell_summary = QTextEdit()
        self.sell_summary.setReadOnly(True)
        rcol.addWidget(self.sell_summary)
        split.setSizes([640, 220])
        self._load_sell_data()

    def _load_sell_data(self) -> None:
        try:
            filters = load_sell_filters()
            self._keep = {str(name).strip() for name in (filters.keep_list or ()) if str(name).strip()}
        except Exception:
            self._keep = set()
        self._catalog_rows = []
        try:
            from app._03_world.catalog.game_catalog import list_item_rows

            for entry in list_item_rows():
                label = item_catalog_display_name(entry.name_ko, self.language) or entry.key
                category = (
                    item_category_display_name(
                        entry.display_category(self.language), self.language
                    )
                    or entry.display_category(self.language)
                )
                self._catalog_rows.append(
                    _SellRow(
                        key=entry.key,
                        name=label,
                        category=category,
                        is_own=False,
                        source_category=category,
                        icon_names=self._icon_names(entry),
                        icon_ids=self._icon_ids(entry),
                    )
                )
        except Exception:
            pass
        self._catalog_rows.sort(key=lambda row: row.name.lower())
        self._rebuild_sell_categories()
        self._refresh_sell_rows()

    def _rebuild_sell_categories(self) -> None:
        if not hasattr(self, "sell_category"):
            return
        current = self.sell_category.currentData()
        own = self._own_label()
        cats = [self.t.get("filter_all", "All"), own]
        seen = {own}
        for row in self._catalog_rows:
            if row.category and row.category not in seen:
                seen.add(row.category)
                cats.append(row.category)
        self.sell_category.blockSignals(True)
        self.sell_category.clear()
        for cat in cats:
            self.sell_category.addItem(cat, cat)
        idx = self.sell_category.findData(current)
        self.sell_category.setCurrentIndex(max(0, idx))
        self.sell_category.blockSignals(False)

    def _visible_sell_rows(self) -> list[_SellRow]:
        needle = self.sell_search.text().strip().lower() if hasattr(self, "sell_search") else ""
        category = (
            str(self.sell_category.currentData() or "")
            if hasattr(self, "sell_category")
            else ""
        )
        show = (
            str(self.sell_show.currentData() or "all")
            if hasattr(self, "sell_show")
            else "all"
        )
        all_label = self.t.get("filter_all", "All")
        own_label = self._own_label()

        def wanted(key: str, *, is_own: bool) -> bool:
            kept = key in self._keep
            if show == "own":
                return is_own
            if show == "keep":
                return kept
            if show == "unmarked":
                return not kept
            return True

        def name_ok(text: str, *extra: str) -> bool:
            if not needle:
                return True
            return needle in " ".join((text, *extra)).lower()

        rows: list[_SellRow] = []
        for row in self._owned_rows:
            if category not in ("", all_label, own_label):
                if row.source_category != category:
                    continue
            if wanted(row.key, is_own=True) and name_ok(row.name, row.key):
                rows.append(row)
        if category == own_label or show == "own":
            return rows
        for row in self._catalog_rows:
            if row.key in self._owned_keys:
                continue
            if category not in ("", all_label) and row.category != category:
                continue
            if not wanted(row.key, is_own=False):
                continue
            if not name_ok(row.name, row.key, row.category):
                continue
            rows.append(row)
        return rows

    def _refresh_sell_rows(self) -> None:
        if not hasattr(self, "sell_table"):
            return
        rows = self._visible_sell_rows()
        self._sell_filling = True
        self._sell_icons.cancel()
        self._sell_icon_rows = {}
        self.sell_table.setRowCount(0)
        keep_label = self.t.get("filter_save", self.t.get("filter_keep", "Keep"))
        placeholder = QIcon(self._sell_icons.placeholder())
        try:
            for row in rows:
                kept = row.key in self._keep or row.name in self._keep
                index = self.sell_table.rowCount()
                self.sell_table.insertRow(index)
                self._sell_icons.remember(row.key, row.icon_names, row.icon_ids)
                icon_item = QTableWidgetItem()
                cached = self._sell_icons.cached(row.key)
                icon_item.setIcon(QIcon(cached) if cached is not None else placeholder)
                icon_item.setData(Qt.ItemDataRole.UserRole, row.key)
                self.sell_table.setItem(index, 0, icon_item)
                self._sell_icon_rows.setdefault(row.key, []).append(index)
                self.sell_table.setItem(
                    index, 1, QTableWidgetItem(keep_label if kept else "—")
                )
                self.sell_table.setItem(index, 2, QTableWidgetItem(row.category))
                name_item = QTableWidgetItem(row.name)
                name_item.setData(Qt.ItemDataRole.UserRole, row.key)
                self.sell_table.setItem(index, 3, name_item)
        finally:
            self._sell_filling = False
        from ui_qt.editors.form_helpers import fit_table_columns

        fit_table_columns(self.sell_table, stretch_last=True, min_width=48)
        self.sell_table.setColumnWidth(0, HUNT_ICON_SIZE + 8)
        self.sell_table.horizontalHeader().setSectionResizeMode(
            0, self.sell_table.horizontalHeader().ResizeMode.Fixed
        )
        fmt = self.t.get(
            "filter_count_keep",
            self.t.get("filter_count", "{shown} shown · keep {keep}"),
        )
        try:
            self.sell_count.setText(
                fmt.format(
                    shown=len(rows),
                    keep=len(self._keep),
                    garbage=0,
                    own=len(self._owned_rows),
                )
            )
        except (KeyError, ValueError, IndexError):
            self.sell_count.setText(
                f"{len(rows)} / keep {len(self._keep)} / own {len(self._owned_rows)}"
            )
        self._refresh_sell_summary()
        QTimer.singleShot(0, self._queue_visible_sell_icons)

    def _on_sell_scroll(self, *_args: object) -> None:
        if self._sell_filling or not hasattr(self, "sell_table"):
            return
        self._queue_visible_sell_icons()

    def _visible_sell_keys(self) -> list[str]:
        table = self.sell_table
        count = table.rowCount()
        if count <= 0:
            return []
        height = table.viewport().height()
        top = table.rowAt(0)
        if top < 0:
            top = 0
        if height <= 0:
            bottom = min(count - 1, top + 24)
        else:
            bottom = table.rowAt(max(0, height - 1))
            if bottom < 0:
                row_h = table.rowHeight(top) or (HUNT_ICON_SIZE + 6)
                bottom = min(count - 1, top + max(1, height // max(1, row_h)) + 2)
        top = max(0, top - 4)
        bottom = min(count - 1, bottom + 8)
        keys: list[str] = []
        for row in range(top, bottom + 1):
            item = table.item(row, 0)
            if item is None:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if key:
                keys.append(key)
        return keys

    def _queue_visible_sell_icons(self) -> None:
        if not hasattr(self, "sell_table"):
            return
        visible = self._visible_sell_keys()
        self._sell_icons.enqueue(visible, front=True)
        if self._sell_icons.rest_queued:
            return
        visible_set = set(visible)
        rest = [key for key in self._sell_icon_rows if key not in visible_set]
        self._sell_icons.enqueue(rest, front=False)
        self._sell_icons.rest_queued = True

    def _apply_sell_icon(self, key: str, pixmap: QPixmap) -> None:
        if not hasattr(self, "sell_table"):
            return
        icon = QIcon(pixmap)
        for row in self._sell_icon_rows.get(str(key), ()):
            item = self.sell_table.item(row, 0)
            if item is None:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "") != str(key):
                continue
            item.setIcon(icon)

    def _refresh_sell_summary(self) -> None:
        if not hasattr(self, "sell_summary"):
            return
        store = (
            self.t.get("summary_on", "ON")
            if self.bag.get_bool("equipment", "store_after_sell", True)
            else self.t.get("summary_off", "OFF")
        )
        lines = [
            f"{self.t.get('sell_except_keep', 'Sell except keep')}",
            f"{self.t.get('store_after_sell', 'Store after sell')}: {store}",
            f"{self.t.get('filter_keep', 'Keep')}: {len(self._keep)}",
            f"{self.t.get('filter_own', 'Own')}: {len(self._owned_rows)}",
            f"{self.t.get('filter_show', 'Shown')}: "
            f"{self.sell_table.rowCount() if hasattr(self, 'sell_table') else 0}",
        ]
        self.sell_summary.setPlainText("\n".join(f"• {line}" for line in lines))

    def _toggle_keep(self) -> None:
        rows = self.sell_table.selectionModel().selectedRows()
        for model_index in rows:
            item = self.sell_table.item(model_index.row(), 0)
            if item is None:
                item = self.sell_table.item(model_index.row(), 3)
            if item is None:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not key:
                continue
            if key in self._keep:
                self._keep.discard(key)
            else:
                self._keep.add(key)
        self._persist_sell()
        self._refresh_sell_rows()

    def _persist_sell(self) -> None:
        filters = ShoppingSellFilters(
            garbage_list=(),
            keep_list=tuple(sorted(self._keep)),
        )
        try:
            save_behaviors(load_behaviors(), sell_filters=filters)
            self.sell_status.setText(self.t.get("filter_saved", "Saved"))
            self.on_log(self.t.get("filter_saved", "Saved"))
        except Exception as exc:
            self.sell_status.setText(str(exc))

    def _reload_sell_owned(self) -> None:
        if self._sell_worker is not None and self._sell_worker.isRunning():
            return
        if hasattr(self, "sell_reload_btn"):
            self.sell_reload_btn.setEnabled(False)
        self.sell_status.setText(self.t.get("inventory_refreshing", "Reading the current bag…"))
        self._sell_worker = _SellInventoryWorker(self)
        self._sell_worker.finished_ok.connect(self._finish_sell_owned_ok)
        self._sell_worker.failed.connect(self._finish_sell_owned_fail)
        self._sell_worker.finished.connect(
            lambda: self.sell_reload_btn.setEnabled(True)
            if hasattr(self, "sell_reload_btn")
            else None
        )
        self._sell_worker.start()

    def _finish_sell_owned_ok(self, snap: object) -> None:
        self._apply_owned_snapshot(snap, "")

    def _finish_sell_owned_fail(self, message: str) -> None:
        self._apply_owned_snapshot(None, message or "no snapshot")

    def _apply_owned_snapshot(self, snap: object, error: str) -> None:
        items = snap.get("items") if isinstance(snap, dict) else None
        if error or not isinstance(snap, dict) or not isinstance(items, list):
            msg = self.t.get(
                "inventory_refresh_failed",
                "Could not read inventory. {error}",
            )
            try:
                self.sell_status.setText(msg.format(error=error or "no snapshot"))
            except (KeyError, ValueError, IndexError):
                self.sell_status.setText(str(error or "no snapshot"))
            self._owned_rows = []
            self._owned_keys = set()
            self._refresh_sell_rows()
            return
        self._owned_rows = self._owned_from_snapshot(snap)
        self._owned_keys = {row.key for row in self._owned_rows}
        if hasattr(self, "sell_category"):
            current = str(self.sell_category.currentData() or "")
            own = self._own_label()
            all_label = self.t.get("filter_all", "All")
            if current not in (all_label, own):
                idx = self.sell_category.findData(all_label)
                if idx >= 0:
                    self.sell_category.setCurrentIndex(idx)
        self.sell_status.setText("")
        self._refresh_sell_rows()

    def _owned_from_snapshot(self, snap: dict) -> list[_SellRow]:
        from app._03_world.catalog.game_catalog import (
            item_by_key,
            list_item_rows,
            resolve_item_key,
        )
        from app._03_world.merge.memory_inventory import ADENA_IDS, ADENA_NAMES

        raw = snap.get("items") if isinstance(snap, dict) else None
        if not isinstance(raw, list):
            return []
        catalog = list(list_item_rows()) if self._catalog_rows else []
        by_id: dict[int, object] = {}
        for entry in catalog:
            for sid in getattr(entry, "ids", ()) or ():
                try:
                    by_id[int(sid)] = entry
                except (TypeError, ValueError):
                    continue
        adena = {str(n).strip().lower() for n in ADENA_NAMES if str(n).strip()}
        adena.add("아데나")
        own_label = self._own_label()
        rows: list[_SellRow] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                item_id = int(item.get("id") or 0)
            except (TypeError, ValueError):
                item_id = 0
            name = str(
                item.get("name")
                or item.get("name_tw")
                or item.get("name_cn")
                or item.get("name_en")
                or ""
            ).strip()
            if item_id in ADENA_IDS or name.lower() in adena:
                continue
            key = resolve_item_key(name) or ""
            entry = item_by_key(key) if key else None
            if entry is None and item_id:
                entry = by_id.get(item_id)
                if entry is not None:
                    key = entry.key
            if not key:
                key = name or (f"id:{item_id}" if item_id else "")
            if not key or key in seen:
                continue
            if key.lower() in adena:
                continue
            seen.add(key)
            source_cat = ""
            icon_names: tuple[str, ...] = ()
            icon_ids: tuple[int, ...] = ()
            if entry is not None:
                shown = item_catalog_display_name(entry.name_ko, self.language) or entry.name_ko
                icon_names = self._icon_names(entry)
                icon_ids = self._icon_ids(entry)
                source_cat = (
                    item_category_display_name(
                        entry.display_category(self.language), self.language
                    )
                    or entry.display_category(self.language)
                    or ""
                )
            else:
                shown = memory_name_for_ui(name or key, self.language) or key
                icon_names = tuple(
                    text for text in (name, shown, key) if str(text or "").strip()
                )
                icon_ids = (item_id,) if item_id else ()
            rows.append(
                _SellRow(
                    key=key,
                    name=shown,
                    category=own_label,
                    is_own=True,
                    source_category=source_cat,
                    icon_names=icon_names,
                    icon_ids=icon_ids,
                )
            )
        rows.sort(key=lambda row: row.name.lower())
        return rows

    def _build_routing(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        box = card(page, self.t.get("routing", "Routing"))
        layout.addWidget(box)
        b = box.layout()
        assert isinstance(b, QVBoxLayout)
        mode = self.bag.get_str("other", "loot_mode", "all_items")
        self._loot_group = QButtonGroup(self)
        for value, label_key in (
            ("all_items", "loot_all_adena"),
            ("adena_only", "loot_adena_only_pick"),
        ):
            radio = QRadioButton(self.t.get(label_key, value))
            radio.setChecked(mode == value)
            self._loot_group.addButton(radio)
            radio.toggled.connect(
                lambda checked, v=value: checked and self._set_loot_mode(v)
            )
            b.addWidget(radio)
        self._adena_weight = add_spin_row(
            b, self.bag, "other", "loot_adena_weight_pct",
            self.t.get("adena_weight", "Adena weight"), 70, 1, 95, "%",
        )
        add_check_spin(
            b,
            self.bag,
            "ignore_small_adena",
            False,
            self.t.get("ignore_small_adena_qty", "수량이"),
            "ignore_small_adena_qty",
            10,
            1,
            99999,
            self.t.get("ignore_small_adena_suffix", "이하인 아데나 무시"),
            section="other",
        )
        add_check(
            b, self.bag, "equipment", "use_potion_on_pickup",
            self.t.get("use_potion_on_pickup", "Potion on pickup"), True,
        )
        add_check(
            b, self.bag, "equipment", "minimize_combat_during_loot",
            self.t.get("minimize_combat_loot", "Minimize combat loot"), True,
        )
        self._sync_adena_weight_gate()
        layout.addStretch(1)

    def _set_loot_mode(self, mode: str) -> None:
        self.bag.set("other", "loot_mode", mode)
        self._sync_adena_weight_gate()

    def _sync_adena_weight_gate(self) -> None:
        spin = getattr(self, "_adena_weight", None)
        if spin is None:
            return
        # Classic: weight spin disabled when loot mode is adena-only.
        spin.setEnabled(self.bag.get_str("other", "loot_mode", "all_items") != "adena_only")

    def apply_to_profile(self) -> None:
        if self._sell_built:
            self._persist_sell()
        self.bag.apply_to_profile()
        self.on_log(self.t.get("saved", "Saved"))
