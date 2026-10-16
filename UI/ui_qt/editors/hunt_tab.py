"""Hunt tab — attack / monsters / items (lazy heavy tables)."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n.localized_names import species_display_name_ui, species_search_names
from ui_qt.editors.form_helpers import (
    add_check,
    add_check_spin,
    add_spin_row,
    bind_gate,
    card,
    configure_select_rows,
    configure_table_fill,
)
from ui_qt.facade.qt_bridge import QtBridge
from ui_qt.icon_helpers import HUNT_ICON_SIZE, hunt_icon
from ui_qt.theme import tokens
from ui_qt.theme.apply import mark_accent
from ui_qt.viewmodels.settings_bag import SettingsBag


class _HotbarWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            from hotbar.inspect import inspect_hotbars

            detected = inspect_hotbars()
            self.finished_ok.emit(detected.to_profile_dict())
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class HuntTab(QWidget):
    def __init__(
        self,
        *,
        bag: SettingsBag,
        strings: dict[str, str],
        language: str,
        bridge: QtBridge | None = None,
        on_log: Callable[[str], None] | None = None,
        get_primary_map_id: Callable[[], str] | None = None,
        get_map_label: Callable[[str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bag = bag
        self.bridge = bridge
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self.get_primary_map_id = get_primary_map_id or (lambda: "")
        self.get_map_label = get_map_label or (lambda mid: mid)
        self._haste_hotbar_raw: list[dict] = []
        self._haste_hotbar_stamp: object | None = None
        self._haste_hotbar_worker: _HotbarWorker | None = None
        self._monsters_built = False
        self._items_built = False
        self._species_region_user_set = False
        self._species_order: list[str] = []
        self._species_allowed: dict[str, bool] = {}
        self._species_level: dict[str, int] = {}
        self._species_labels: dict[str, str] = {}
        self._species_search: dict[str, str] = {}
        self._species_region_text: dict[str, str] = {}
        self._species_region_values: dict[str, tuple[str, ...]] = {}
        self._species_on_mainland: dict[str, bool] = {}
        self._mainland_label = ""
        self._item_order: list[str] = []
        self._item_allowed: dict[str, bool] = {}
        self._item_labels: dict[str, str] = {}
        self._item_search: dict[str, str] = {}
        self._item_categories: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        self.tabs = tabs
        self.attack_page = QWidget()
        self.monsters_page = QWidget()
        self.items_page = QWidget()
        tabs.addTab(self.attack_page, self.t.get("attack", "Attack"))
        tabs.addTab(self.monsters_page, self.t.get("monsters", "Monsters"))
        tabs.addTab(self.items_page, self.t.get("hunt_items", "Items"))
        tabs.currentChanged.connect(self._on_tab)
        root.addWidget(tabs)
        self._build_attack(self.attack_page)
        placeholder = QVBoxLayout(self.monsters_page)
        placeholder.addWidget(QLabel(self.t.get("filter_search", "…")))
        placeholder.addStretch(1)
        placeholder2 = QVBoxLayout(self.items_page)
        placeholder2.addWidget(QLabel(self.t.get("filter_search", "…")))
        placeholder2.addStretch(1)

    def _on_tab(self, index: int) -> None:
        if index == 1 and not self._monsters_built:
            self._clear_page(self.monsters_page)
            self._build_monsters(self.monsters_page)
            self._monsters_built = True
            self._load_species()
        elif index == 2 and not self._items_built:
            self._clear_page(self.items_page)
            self._build_items(self.items_page)
            self._items_built = True
            self._load_items()

    def reload_from_bag(self) -> None:
        """Refresh catalogs after the settings bag was replaced (task load)."""
        if self._monsters_built and hasattr(self, "species_table"):
            self._load_species()
        if self._items_built and hasattr(self, "item_table"):
            self._load_items()
        self._reload_potion_assist_widgets()

    def _clear_page(self, page: QWidget) -> None:
        layout = page.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif child is not None:
                while child.count():
                    nested = child.takeAt(0)
                    nested_widget = nested.widget()
                    if nested_widget is not None:
                        nested_widget.setParent(None)
                        nested_widget.deleteLater()

    def _build_attack(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        scroll.setWidget(host)
        outer.addWidget(scroll, stretch=1)
        body = QVBoxLayout(host)

        cols = QHBoxLayout()
        body.addLayout(cols, stretch=1)
        left = QVBoxLayout()
        mid = QVBoxLayout()
        right = QVBoxLayout()
        cols.addLayout(left, 1)
        cols.addLayout(mid, 1)
        cols.addLayout(right, 1)

        combat = card(host, self.t.get("attack_method", "Attack"))
        left.addWidget(combat)
        combat_l = combat.layout()
        assert isinstance(combat_l, QVBoxLayout)
        modes = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        mode = self.bag.get_str("hunt", "attack_mode", "ranged")
        for value, label_key in (
            ("ranged", "ranged"),
            ("magic", "magic_attack"),
            ("melee", "melee"),
        ):
            radio = QRadioButton(self.t.get(label_key, value))
            radio.setChecked(mode == value)
            self._mode_group.addButton(radio)
            radio.toggled.connect(
                lambda checked, v=value: checked and self._set_mode(v)
            )
            modes.addWidget(radio)
        modes.addStretch(1)
        combat_l.addLayout(modes)
        add_spin_row(
            combat_l, self.bag, "hunt", "attack_range",
            self.t.get("attack_range", "Range"), 16, 1, 30, on_change=self._refresh_attack_summary,
        )
        add_check(
            combat_l, self.bag, "hunt", "close_attack",
            self.t.get("close_attack_allow", "Close attack"), False, self._refresh_attack_summary,
        )
        add_check_spin(
            combat_l, self.bag, "keep_distance", True, self.t.get("keep_distance", "Keep distance"),
            "keep_distance_tiles", 3, 0, 20, self.t.get("tiles", "tiles"),
            on_change=self._refresh_attack_summary,
        )

        assist = card(host, self.t.get("combat_assist", "Assist"))
        left.addWidget(assist)
        assist_l = assist.layout()
        assert isinstance(assist_l, QVBoxLayout)
        add_check_spin(
            assist_l, self.bag, "attack_jitter", False, self.t.get("attack_jitter", "Jitter"),
            "attack_jitter_ms", 35, 10, 50, self.t.get("ms_unit", "ms"),
            on_change=self._refresh_attack_summary,
        )
        jitter_hint = QLabel(self.t.get("attack_jitter_hint", ""))
        jitter_hint.setWordWrap(True)
        jitter_hint.setObjectName("muted")
        assist_l.addWidget(jitter_hint)
        delay_check = add_check(
            assist_l, self.bag, "hunt", "target_delay",
            self.t.get("target_delay", "Target delay"), False, self._refresh_attack_summary,
        )
        delay_spins: dict[str, object] = {}

        def _on_delay_spin() -> None:
            mn = delay_spins.get("min")
            mx = delay_spins.get("max")
            if mn is None or mx is None:
                self._refresh_attack_summary()
                return
            if mn.value() > mx.value():
                mx.blockSignals(True)
                mx.setValue(mn.value())
                mx.blockSignals(False)
                self.bag.set("hunt", "target_delay_max_ms", int(mn.value()))
            self._refresh_attack_summary()

        delay_min = add_spin_row(
            assist_l, self.bag, "hunt", "target_delay_min_ms",
            self.t.get("delay_min", "min"), 20, 10, 50, self.t.get("ms_unit", "ms"), _on_delay_spin,
        )
        delay_max = add_spin_row(
            assist_l, self.bag, "hunt", "target_delay_max_ms",
            self.t.get("delay_max", "max"), 50, 10, 50, self.t.get("ms_unit", "ms"), _on_delay_spin,
        )
        delay_spins["min"] = delay_min
        delay_spins["max"] = delay_max
        delay_hint = QLabel(self.t.get("target_delay_hint", ""))
        delay_hint.setWordWrap(True)
        delay_hint.setObjectName("muted")
        assist_l.addWidget(delay_hint)
        bind_gate(delay_check, delay_min, delay_max, delay_hint)
        self._build_haste_potion_assist(assist_l)
        left.addStretch(1)

        magic = card(host, self.t.get("magic_use", "Magic use"))
        mid.addWidget(magic)
        magic_l = magic.layout()
        assert isinstance(magic_l, QVBoxLayout)
        add_spin_row(
            magic_l, self.bag, "hunt", "mp_spell_above",
            self.t.get("mp_above", "MP >"), 80, 0, 100, "%", self._refresh_attack_summary,
        )
        add_spin_row(
            magic_l, self.bag, "hunt", "spell_count",
            self.t.get("spell_count", "Spells"), 1, 1, 99,
            f"[{self.t.get('times', 'x')}]", self._refresh_attack_summary,
        )
        add_spin_row(
            magic_l, self.bag, "hunt", "ranged_count",
            self.t.get("basic_attack_count", "Basic"), 1, 1, 99,
            f"[{self.t.get('times', 'x')}]", self._refresh_attack_summary,
        )
        add_check_spin(
            magic_l, self.bag, "fallback_melee", False, self.t.get("fallback", "Fallback melee"),
            "fallback_mp_below", 20, 0, 100, "%", on_change=self._refresh_attack_summary,
        )

        priority = card(host, self.t.get("target_priority", "Priority"))
        mid.addWidget(priority)
        pri_l = priority.layout()
        assert isinstance(pri_l, QVBoxLayout)
        for key, name, default in (
            ("prefer_nearest", "hunt.prefer_nearest", True),
            ("prefer_aggressor", "hunt.prefer_aggressor", True),
            ("prefer_strong", "hunt.prefer_strong", False),
            ("prefer_caster", "hunt.prefer_caster", True),
            ("exclude_busy", "hunt.exclude_busy", True),
            ("stick_target", "hunt.stick_target", True),
        ):
            field = name.split(".", 1)[1]
            add_check(
                pri_l, self.bag, "hunt", field, self.t.get(key, key), default,
                self._refresh_attack_summary,
            )

        area = card(host, self.t.get("area_switch", "Area"))
        mid.addWidget(area)
        area_l = area.layout()
        assert isinstance(area_l, QVBoxLayout)
        add_check_spin(
            area_l, self.bag, "area_empty", False, self.t.get("area_empty_suffix", "empty"),
            "area_empty_seconds", 60, 1, 600, self.t.get("seconds", "s"),
            on_change=self._refresh_attack_summary,
        )
        add_check(
            area_l, self.bag, "hunt", "area_low_yield",
            self.t.get("area_low_yield", "Low yield"), False, self._refresh_attack_summary,
        )
        add_spin_row(
            area_l, self.bag, "hunt", "area_low_yield_adena",
            self.t.get("area_low_yield_adena", "Adena"), 1000, 1, 10_000_000,
            self.t.get("area_low_yield_adena_unit", ""), self._refresh_attack_summary,
        )
        add_spin_row(
            area_l, self.bag, "hunt", "area_low_yield_seconds",
            self.t.get("area_low_yield_time", "Time"), 180, 1, 600,
            self.t.get("seconds", "s"), self._refresh_attack_summary,
        )
        add_check_spin(
            area_l, self.bag, "area_players", False,
            self.t.get("area_players_prefix", "Players"),
            "area_player_count", 3, 1, 20, self.t.get("area_players_suffix", ""),
            on_change=self._refresh_attack_summary,
        )
        mid.addStretch(1)

        summary = card(host, self.t.get("settings_summary", "Summary"))
        right.addWidget(summary)
        sum_l = summary.layout()
        assert isinstance(sum_l, QVBoxLayout)
        self.attack_summary = QTextEdit()
        self.attack_summary.setReadOnly(True)
        sum_l.addWidget(self.attack_summary)
        self._refresh_attack_summary()

    def _build_haste_potion_assist(self, assist_l: QVBoxLayout) -> None:
        self.haste_check = haste_check = add_check(
            assist_l,
            self.bag,
            "hunt",
            "use_haste_potion",
            self.t.get("use_haste_potion", "Use haste potion"),
            False,
            self._on_haste_toggle,
        )
        haste_hint = QLabel(self.t.get("use_haste_potion_hint", ""))
        haste_hint.setWordWrap(True)
        haste_hint.setObjectName("muted")
        assist_l.addWidget(haste_hint)

        self.haste_item_label = QLabel(self._haste_item_summary_text())
        self.haste_item_label.setWordWrap(True)
        assist_l.addWidget(self.haste_item_label)
        self.haste_hotbar_label = QLabel(self._haste_hotbar_text())
        self.haste_hotbar_label.setObjectName("muted")
        assist_l.addWidget(self.haste_hotbar_label)

        self.antidote_check = antidote_check = add_check(
            assist_l,
            self.bag,
            "hunt",
            "use_antidote_potion",
            self.t.get("use_antidote_potion", "Use antidote"),
            False,
            self._on_antidote_toggle,
        )
        antidote_hint = QLabel(self.t.get("use_antidote_potion_hint", ""))
        antidote_hint.setWordWrap(True)
        antidote_hint.setObjectName("muted")
        assist_l.addWidget(antidote_hint)
        self.antidote_item_label = QLabel(self._antidote_item_summary_text())
        self.antidote_item_label.setWordWrap(True)
        assist_l.addWidget(self.antidote_item_label)
        self.antidote_hotbar_label = QLabel(self._antidote_hotbar_text())
        self.antidote_hotbar_label.setObjectName("muted")
        assist_l.addWidget(self.antidote_hotbar_label)

        btn_row = QHBoxLayout()
        self.haste_assign_btn = QPushButton(
            self.t.get("haste_potion_assign", "Assign from hotbar")
        )
        self.haste_assign_btn.clicked.connect(self._assign_haste_from_hotbar)
        btn_row.addWidget(self.haste_assign_btn)
        self.haste_clear_btn = QPushButton(self.t.get("haste_potion_clear", "Clear"))
        self.haste_clear_btn.clicked.connect(self._clear_haste_potion_item)
        btn_row.addWidget(self.haste_clear_btn)
        self.antidote_assign_btn = QPushButton(
            self.t.get("antidote_potion_assign", "Assign as antidote")
        )
        self.antidote_assign_btn.clicked.connect(self._assign_antidote_from_hotbar)
        btn_row.addWidget(self.antidote_assign_btn)
        self.antidote_clear_btn = QPushButton(self.t.get("antidote_potion_clear", "Clear"))
        self.antidote_clear_btn.clicked.connect(self._clear_antidote_potion_item)
        btn_row.addWidget(self.antidote_clear_btn)
        btn_row.addStretch(1)
        assist_l.addLayout(btn_row)

        self.haste_hotbar_status = QLabel(self.t.get("inventory_empty", ""))
        self.haste_hotbar_status.setWordWrap(True)
        self.haste_hotbar_status.setObjectName("muted")
        assist_l.addWidget(self.haste_hotbar_status)

        refresh_row = QHBoxLayout()
        self.haste_hotbar_refresh_btn = QPushButton(
            self.t.get("hotbar_refresh", self.t.get("inventory_refresh", "Refresh"))
        )
        mark_accent(self.haste_hotbar_refresh_btn)
        self.haste_hotbar_refresh_btn.clicked.connect(self._on_haste_hotbar_refresh)
        refresh_row.addWidget(self.haste_hotbar_refresh_btn)
        refresh_row.addStretch(1)
        assist_l.addLayout(refresh_row)

        self.haste_hotbar_table = QTableWidget(0, 3)
        self.haste_hotbar_table.setHorizontalHeaderLabels(
            [
                self.t.get("slot", "Slot"),
                self.t.get("name", "Name"),
                self.t.get("count", "Qty"),
            ]
        )
        self.haste_hotbar_table.verticalHeader().setVisible(False)
        self.haste_hotbar_table.horizontalHeader().setStretchLastSection(False)
        self.haste_hotbar_table.horizontalHeader().setSectionResizeMode(
            1, self.haste_hotbar_table.horizontalHeader().ResizeMode.Stretch
        )
        self.haste_hotbar_table.setColumnWidth(0, 64)
        self.haste_hotbar_table.setColumnWidth(2, 56)
        self.haste_hotbar_table.setMaximumHeight(160)
        configure_select_rows(self.haste_hotbar_table)
        self.haste_hotbar_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.haste_hotbar_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.haste_hotbar_table.doubleClicked.connect(
            lambda _idx: self._assign_haste_from_hotbar()
        )
        assist_l.addWidget(self.haste_hotbar_table)
        bind_gate(
            haste_check,
            self.haste_item_label,
            self.haste_hotbar_label,
            self.haste_assign_btn,
            self.haste_clear_btn,
            haste_hint,
        )
        bind_gate(
            antidote_check,
            self.antidote_item_label,
            self.antidote_hotbar_label,
            self.antidote_assign_btn,
            self.antidote_clear_btn,
            antidote_hint,
        )
        shared = (
            self.haste_hotbar_status,
            self.haste_hotbar_refresh_btn,
            self.haste_hotbar_table,
        )

        def _gate_shared(*_args: object) -> None:
            on = haste_check.isChecked() or antidote_check.isChecked()
            for widget in shared:
                widget.setEnabled(on)

        haste_check.toggled.connect(_gate_shared)
        antidote_check.toggled.connect(_gate_shared)
        _gate_shared()
        self._paint_haste_hotbar(force=True)

    def _haste_item_summary_text(self) -> str:
        key = self.bag.get_str("hunt", "haste_potion_item", "")
        if not key:
            return self.t.get("haste_potion_none", "No potion selected")
        return self.t.get("haste_potion_selected", "Potion: {name}").format(name=key)

    def _haste_hotbar_layout(self) -> dict:
        layout = self.bag.get("magic", "hotbar_layout", {}) or {}
        return layout if isinstance(layout, dict) else {}

    def _haste_hotbar_text(self) -> str:
        none = self.t.get("hp_action_hotbar_none", "Not on hotbar")
        try:
            from app._04_decision.hp_actions import format_hotbar_binding
            from settings.haste_potion import assigned_haste_slot
        except Exception:
            return none
        slot = assigned_haste_slot(
            self.bag.get("magic", "spell_slots", {}) or {},
            item_key=self.bag.get_str("hunt", "haste_potion_item", ""),
            box=self.bag.get_int("hunt", "haste_potion_box", 0),
            key=self.bag.get_str("hunt", "haste_potion_key", ""),
        )
        shown = format_hotbar_binding(slot)
        if shown:
            return self.t.get("haste_potion_hotbar", "Hotbar: {slot}").format(slot=shown)
        return none

    def _sync_haste_spell_slot(self) -> None:
        from settings.haste_potion import apply_haste_potion_to_spell_slots

        use = self.bag.get_bool("hunt", "use_haste_potion", False)
        previous = self.bag.get("magic", "spell_slots", {}) or {}
        if not isinstance(previous, dict):
            previous = {}
        synced = apply_haste_potion_to_spell_slots(
            previous,
            use=use,
            item_key=self.bag.get_str("hunt", "haste_potion_item", ""),
            box=self.bag.get_int("hunt", "haste_potion_box", 0),
            key=self.bag.get_str("hunt", "haste_potion_key", ""),
            layout=self._haste_hotbar_layout(),
        )
        self.bag.set("magic", "spell_slots", synced)

    def _refresh_haste_labels(self) -> None:
        if hasattr(self, "haste_item_label"):
            self.haste_item_label.setText(self._haste_item_summary_text())
        if hasattr(self, "haste_hotbar_label"):
            self.haste_hotbar_label.setText(self._haste_hotbar_text())
        if hasattr(self, "antidote_item_label"):
            self.antidote_item_label.setText(self._antidote_item_summary_text())
        if hasattr(self, "antidote_hotbar_label"):
            self.antidote_hotbar_label.setText(self._antidote_hotbar_text())
        self._refresh_attack_summary()

    def _reload_potion_assist_widgets(self) -> None:
        """Push hunt potion fields back into the checkboxes after a task reload."""
        if hasattr(self, "haste_check"):
            self.haste_check.setChecked(
                self.bag.get_bool("hunt", "use_haste_potion", False)
            )
        if hasattr(self, "antidote_check"):
            self.antidote_check.setChecked(
                self.bag.get_bool("hunt", "use_antidote_potion", False)
            )
        self._refresh_haste_labels()

    def flush_potion_assist_to_bag(self) -> None:
        """Write the visible potion checkboxes into the bag before a schedule save."""
        if hasattr(self, "haste_check"):
            self.bag.set(
                "hunt", "use_haste_potion", bool(self.haste_check.isChecked())
            )
        if hasattr(self, "antidote_check"):
            self.bag.set(
                "hunt",
                "use_antidote_potion",
                bool(self.antidote_check.isChecked()),
            )
        if hasattr(self, "haste_check"):
            self._sync_haste_spell_slot()
        if hasattr(self, "antidote_check"):
            self._sync_antidote_spell_slot()

    def _on_haste_toggle(self) -> None:
        self._sync_haste_spell_slot()
        self._refresh_haste_labels()

    def _clear_haste_potion_item(self) -> None:
        self.bag.set("hunt", "haste_potion_item", "")
        self.bag.set("hunt", "haste_potion_box", 0)
        self.bag.set("hunt", "haste_potion_key", "")
        self._sync_haste_spell_slot()
        self._refresh_haste_labels()

    def _assign_haste_from_hotbar(self) -> None:
        cell = self._selected_haste_hotbar_cell()
        if cell is None:
            self.haste_hotbar_status.setText(
                self.t.get("haste_potion_select_slot", "Select a hotbar cell")
            )
            return
        name = str(cell.get("name") or "").strip()
        if not name:
            self.haste_hotbar_status.setText(
                self.t.get("haste_potion_empty_cell", "That hotbar cell is empty.")
            )
            return
        box = int(cell.get("box") or 0)
        key = str(cell.get("key") or "").strip().lower()
        self.bag.set("hunt", "haste_potion_item", name)
        self.bag.set("hunt", "haste_potion_box", box)
        self.bag.set("hunt", "haste_potion_key", key)
        self._drop_antidote_if_same_cell(box, key)
        self._sync_haste_spell_slot()
        self._sync_antidote_spell_slot()
        self._refresh_haste_labels()
        msg = self.t.get("haste_potion_assigned", "Assigned: {name}").format(name=name)
        self.haste_hotbar_status.setText(msg)
        self.on_log(msg)

    def _antidote_item_summary_text(self) -> str:
        key = self.bag.get_str("hunt", "antidote_potion_item", "")
        if not key:
            return self.t.get("antidote_potion_none", "No potion selected")
        return self.t.get("antidote_potion_selected", "Potion: {name}").format(name=key)

    def _antidote_hotbar_text(self) -> str:
        none = self.t.get("hp_action_hotbar_none", "Not on hotbar")
        try:
            from app._04_decision.hp_actions import format_hotbar_binding
            from settings.antidote_potion import assigned_antidote_slot
        except Exception:
            return none
        slot = assigned_antidote_slot(
            self.bag.get("magic", "spell_slots", {}) or {},
            item_key=self.bag.get_str("hunt", "antidote_potion_item", ""),
            box=self.bag.get_int("hunt", "antidote_potion_box", 0),
            key=self.bag.get_str("hunt", "antidote_potion_key", ""),
        )
        shown = format_hotbar_binding(slot)
        if shown:
            return self.t.get("antidote_potion_hotbar", "Hotbar: {slot}").format(
                slot=shown
            )
        return none

    def _sync_antidote_spell_slot(self) -> None:
        from settings.antidote_potion import apply_antidote_potion_to_spell_slots

        use = self.bag.get_bool("hunt", "use_antidote_potion", False)
        previous = self.bag.get("magic", "spell_slots", {}) or {}
        if not isinstance(previous, dict):
            previous = {}
        synced = apply_antidote_potion_to_spell_slots(
            previous,
            use=use,
            item_key=self.bag.get_str("hunt", "antidote_potion_item", ""),
            box=self.bag.get_int("hunt", "antidote_potion_box", 0),
            key=self.bag.get_str("hunt", "antidote_potion_key", ""),
            layout=self._haste_hotbar_layout(),
        )
        self.bag.set("magic", "spell_slots", synced)

    def _on_antidote_toggle(self) -> None:
        self._sync_antidote_spell_slot()
        self._refresh_haste_labels()

    def _drop_haste_if_same_cell(self, box: int, key: str) -> None:
        from settings.antidote_potion import same_hotbar_cell

        if not same_hotbar_cell(
            box,
            key,
            self.bag.get_int("hunt", "haste_potion_box", 0),
            self.bag.get_str("hunt", "haste_potion_key", ""),
        ):
            return
        self.bag.set("hunt", "haste_potion_item", "")
        self.bag.set("hunt", "haste_potion_box", 0)
        self.bag.set("hunt", "haste_potion_key", "")
        self._sync_haste_spell_slot()

    def _drop_antidote_if_same_cell(self, box: int, key: str) -> None:
        from settings.antidote_potion import same_hotbar_cell

        if not same_hotbar_cell(
            box,
            key,
            self.bag.get_int("hunt", "antidote_potion_box", 0),
            self.bag.get_str("hunt", "antidote_potion_key", ""),
        ):
            return
        self.bag.set("hunt", "antidote_potion_item", "")
        self.bag.set("hunt", "antidote_potion_box", 0)
        self.bag.set("hunt", "antidote_potion_key", "")

    def _clear_antidote_potion_item(self) -> None:
        self.bag.set("hunt", "antidote_potion_item", "")
        self.bag.set("hunt", "antidote_potion_box", 0)
        self.bag.set("hunt", "antidote_potion_key", "")
        self._sync_antidote_spell_slot()
        self._refresh_haste_labels()

    def _assign_antidote_from_hotbar(self) -> None:
        cell = self._selected_haste_hotbar_cell()
        if cell is None:
            self.haste_hotbar_status.setText(
                self.t.get("antidote_potion_select_slot", "Select a hotbar cell")
            )
            return
        name = str(cell.get("name") or "").strip()
        if not name:
            self.haste_hotbar_status.setText(
                self.t.get("antidote_potion_empty_cell", "That hotbar cell is empty.")
            )
            return
        box = int(cell.get("box") or 0)
        key = str(cell.get("key") or "").strip().lower()
        self._drop_haste_if_same_cell(box, key)
        self.bag.set("hunt", "antidote_potion_item", name)
        self.bag.set("hunt", "antidote_potion_box", box)
        self.bag.set("hunt", "antidote_potion_key", key)
        self._sync_antidote_spell_slot()
        self._refresh_haste_labels()
        msg = self.t.get("antidote_potion_assigned", "Assigned: {name}").format(name=name)
        self.haste_hotbar_status.setText(msg)
        self.on_log(msg)

    def _selected_haste_hotbar_cell(self) -> dict | None:
        if not hasattr(self, "haste_hotbar_table"):
            return None
        rows = self.haste_hotbar_table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if index < 0 or index >= len(self._haste_hotbar_raw):
            return None
        item = self._haste_hotbar_raw[index]
        return item if isinstance(item, dict) else None

    def _on_haste_hotbar_refresh(self) -> None:
        if self._haste_hotbar_worker is not None and self._haste_hotbar_worker.isRunning():
            return
        self.haste_hotbar_refresh_btn.setEnabled(False)
        self.haste_hotbar_status.setText(
            self.t.get("hotbar_refreshing", self.t.get("inventory_refreshing", "Refreshing…"))
        )
        self._haste_hotbar_worker = _HotbarWorker(self)
        self._haste_hotbar_worker.finished_ok.connect(self._finish_haste_hotbar_ok)
        self._haste_hotbar_worker.failed.connect(self._finish_haste_hotbar_fail)
        self._haste_hotbar_worker.finished.connect(
            lambda: self.haste_hotbar_refresh_btn.setEnabled(True)
        )
        self._haste_hotbar_worker.start()

    def _finish_haste_hotbar_ok(self, layout: object) -> None:
        if isinstance(layout, dict):
            self.bag.set("magic", "hotbar_layout", dict(layout))
            self._paint_haste_hotbar(force=True)
            self._sync_haste_spell_slot()
            self._sync_antidote_spell_slot()
            self._refresh_haste_labels()
            return
        self._finish_haste_hotbar_fail(self.t.get("inventory_empty", "—"))

    def _finish_haste_hotbar_fail(self, message: str) -> None:
        self._paint_haste_hotbar(force=True)
        self.haste_hotbar_status.setText(
            self.t.get("hotbar_refresh_failed", "Failed: {error}").format(
                error=message or "—"
            )
        )

    def _paint_haste_hotbar(self, *, force: bool = False) -> None:
        from settings.haste_potion import hotbar_picker_rows

        if not hasattr(self, "haste_hotbar_table"):
            return
        items = hotbar_picker_rows(self._haste_hotbar_layout())
        self._haste_hotbar_raw = list(items)

        def cell(value: object) -> str:
            if value is None or value == "":
                return "—"
            return str(value)

        rows: list[tuple[str, str, str]] = [
            (cell(item.get("slot")), cell(item.get("name")), cell(item.get("count")))
            for item in items
        ]
        stamp = tuple(rows)
        if not force and stamp == self._haste_hotbar_stamp:
            return
        self._haste_hotbar_stamp = stamp
        selected = self.haste_hotbar_table.currentRow()
        self.haste_hotbar_table.setRowCount(0)
        for index, row in enumerate(rows):
            self.haste_hotbar_table.insertRow(index)
            for col, text in enumerate(row):
                cell_item = QTableWidgetItem(text)
                if col != 1:
                    cell_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.haste_hotbar_table.setItem(index, col, cell_item)
        if 0 <= selected < self.haste_hotbar_table.rowCount():
            self.haste_hotbar_table.selectRow(selected)
        filled = sum(1 for item in items if str(item.get("name") or "").strip())
        self.haste_hotbar_status.setText(
            self.t.get("hotbar_total_slots", "Slots: {count}").format(count=f"{filled}/24")
        )

    def _set_mode(self, value: str) -> None:
        self.bag.set("hunt", "attack_mode", value)
        self._refresh_attack_summary()

    def _refresh_attack_summary(self) -> None:
        if not hasattr(self, "attack_summary"):
            return
        mode = self.bag.get_str("hunt", "attack_mode", "ranged")
        mode_label = {
            "ranged": self.t.get("ranged", mode),
            "magic": self.t.get("magic_attack", mode),
            "melee": self.t.get("melee", mode),
        }.get(mode, mode)
        lines = [
            f"{self.t.get('attack_method', 'Attack')}: {mode_label}",
            f"{self.t.get('attack_range', 'Range')}: {self.bag.get_int('hunt', 'attack_range', 16)}",
        ]
        if self.bag.get_bool("hunt", "close_attack"):
            lines.append(
                f"{self.t.get('close_attack_allow', 'Close')}: {self.t.get('summary_on', 'ON')}"
            )
        if self.bag.get_bool("hunt", "keep_distance", True):
            lines.append(
                f"{self.t.get('keep_distance', 'Keep')}: "
                f"{self.bag.get_int('hunt', 'keep_distance_tiles', 3)} {self.t.get('tiles', '')}"
            )
        if self.bag.get_bool("hunt", "use_haste_potion"):
            haste_name = self.bag.get_str("hunt", "haste_potion_item", "") or "—"
            lines.append(
                f"{self.t.get('use_haste_potion', 'Haste potion')}: {haste_name}"
            )
        if self.bag.get_bool("hunt", "use_antidote_potion"):
            antidote_name = self.bag.get_str("hunt", "antidote_potion_item", "") or "—"
            lines.append(
                f"{self.t.get('use_antidote_potion', 'Antidote')}: {antidote_name}"
            )
        lines.append(
            f"{self.t.get('mp_above', 'MP')}: {self.bag.get_int('hunt', 'mp_spell_above', 80)}%"
        )
        lines.append(
            f"{self.t.get('spell_count', 'Spells')}: "
            f"{self.bag.get_int('hunt', 'spell_count', 1)}{self.t.get('times', '')}"
        )
        lines.append(
            f"{self.t.get('basic_attack_count', 'Basic')}: "
            f"{self.bag.get_int('hunt', 'ranged_count', 1)}{self.t.get('times', '')}"
        )
        priorities = [
            self.t.get(key, key)
            for key, field in (
                ("prefer_nearest", "prefer_nearest"),
                ("prefer_aggressor", "prefer_aggressor"),
                ("prefer_strong", "prefer_strong"),
                ("prefer_caster", "prefer_caster"),
                ("exclude_busy", "exclude_busy"),
                ("stick_target", "stick_target"),
            )
            if self.bag.get_bool("hunt", field)
        ]
        if priorities:
            lines.append(f"{self.t.get('target_priority', 'Priority')}: {', '.join(priorities)}")
        self.attack_summary.setPlainText("\n".join(f"• {line}" for line in lines))

    def apply_to_profile(self) -> None:
        if self._monsters_built:
            self._write_species_to_bag()
        if self._items_built:
            self._write_items_to_bag()
        self.bag.apply_to_profile()
        self.on_log(self.t.get("saved", "Saved"))

    def _build_monsters(self, page: QWidget) -> None:
        # Reuse the page layout — QWidget rejects a second setLayout, which used
        # to orphan the whole monsters UI after the placeholder was cleared.
        layout = page.layout() or QVBoxLayout(page)
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split)
        left = QWidget()
        right = QWidget()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        col = QVBoxLayout(left)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(self.t.get("filter_search", "Search")))
        self.species_search = QLineEdit()
        self.species_search.textChanged.connect(self._refresh_species_rows)
        search_row.addWidget(self.species_search, stretch=1)
        col.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(self.t.get("sort", "Sort")))
        self.species_sort = QComboBox()
        self.species_sort.addItem(self.t.get("sort_name", "Name"), "name")
        self.species_sort.addItem(self.t.get("sort_level", "Level"), "level")
        current_sort = self.bag.get_str("hunt", "species_sort", "name")
        self.species_sort.setCurrentIndex(0 if current_sort != "level" else 1)
        self.species_sort.currentIndexChanged.connect(lambda _i: self._load_species())
        filter_row.addWidget(self.species_sort)
        filter_row.addWidget(QLabel(self.t.get("filter_show", "Show")))
        self.species_show = QComboBox()
        for label, code in (
            (self.t.get("filter_all", "All"), "all"),
            (self.t.get("filter_allowed", "Allowed"), "allowed"),
            (self.t.get("filter_unallowed", "Blocked"), "unallowed"),
        ):
            self.species_show.addItem(label, code)
        self.species_show.currentIndexChanged.connect(lambda _i: self._refresh_species_rows())
        filter_row.addWidget(self.species_show)
        filter_row.addWidget(QLabel(self.t.get("filter_region", "Region")))
        self.species_region = QComboBox()
        self.species_region.addItem(self.t.get("filter_all", "All"))
        self.species_region.currentIndexChanged.connect(self._on_species_region_selected)
        filter_row.addWidget(self.species_region, stretch=1)
        col.addLayout(filter_row)

        mode_row = QHBoxLayout()
        self._species_mode = QButtonGroup(self)
        mode = self.bag.get_str("hunt", "species_filter_mode", "blacklist")
        for value, label_key in (
            ("blacklist", "filter_blacklist"),
            ("whitelist", "filter_whitelist"),
        ):
            radio = QRadioButton(self.t.get(label_key, value))
            radio.setChecked(mode == value)
            self._species_mode.addButton(radio)
            radio.toggled.connect(
                lambda checked, v=value: checked and self._set_species_mode(v)
            )
            mode_row.addWidget(radio)
        mode_row.addStretch(1)
        col.addLayout(mode_row)
        hint = QLabel(self.t.get("species_filter_hint", ""))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        col.addWidget(hint)

        self.species_table = QTableWidget(0, 5)
        self.species_table.setHorizontalHeaderLabels(
            [
                "",
                self.t.get("species_name", "Name"),
                self.t.get("species_level", "Lv"),
                self.t.get("allowed", "Allow"),
                self.t.get("species_regions", "Region"),
            ]
        )
        self.species_table.verticalHeader().setVisible(False)
        self.species_table.setIconSize(QSize(HUNT_ICON_SIZE, HUNT_ICON_SIZE))
        self.species_table.verticalHeader().setDefaultSectionSize(HUNT_ICON_SIZE + 6)
        configure_select_rows(self.species_table)
        # Stretch Region (last col) so the grid meets the pane edge. Name alone
        # was starved when Region used ResizeToContents on long multi-region text.
        configure_table_fill(
            self.species_table,
            stretch_col=4,
            fixed={0: HUNT_ICON_SIZE + 8, 2: 48, 3: 56},
        )
        self.species_table.setColumnWidth(1, 200)
        self.species_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.species_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.species_table.doubleClicked.connect(self._on_species_double_clicked)
        col.addWidget(self.species_table, stretch=1)
        toggle = QPushButton(self.t.get("toggle", "Toggle"))
        toggle.clicked.connect(self._toggle_species)
        col.addWidget(toggle)

        rcol = QVBoxLayout(right)
        rcol.addWidget(QLabel(self.t.get("settings_summary", "Summary")))
        self.monsters_summary = QTextEdit()
        self.monsters_summary.setReadOnly(True)
        rcol.addWidget(self.monsters_summary)
        split.setSizes([640, 220])

    def _set_species_mode(self, mode: str) -> None:
        self.bag.set("hunt", "species_filter_mode", mode)
        self._load_species()

    def _load_species(self) -> None:
        levels = dict(self.bag.get("hunt", "species_levels", {}) or {})
        blocked = set(self.bag.get("hunt", "species_blacklist", []) or [])
        wanted = set(self.bag.get("hunt", "species_whitelist", []) or [])
        mode = self.bag.get_str("hunt", "species_filter_mode", "blacklist")
        sort_id = str(self.species_sort.currentData() or "name")
        self.bag.set("hunt", "species_sort", sort_id)
        try:
            from app._03_world.constants import list_species_catalog
            from app._03_world.catalog.game_catalog import (
                is_mainland_region,
                list_monster_rows,
                mainland_filter_label,
                monster_region_labels,
            )

            rows = list(list_species_catalog())
            catalog = {item.key: item for item in list_monster_rows()}
            mainland_label = mainland_filter_label(self.language)
            self._mainland_label = mainland_label
            region_names = [
                name for name in monster_region_labels(self.language) if name != mainland_label
            ]
            region_values = [self.t.get("filter_all", "All"), mainland_label, *region_names]
            self.species_region.blockSignals(True)
            self.species_region.clear()
            for name in region_values:
                self.species_region.addItem(name)
            chosen = self._species_region_choice(region_values)
            idx = self.species_region.findText(chosen)
            self.species_region.setCurrentIndex(max(0, idx))
            self.species_region.blockSignals(False)
        except Exception:
            rows = sorted((key, int(value)) for key, value in levels.items())
            catalog = {}
        if sort_id == "level":
            rows = sorted(rows, key=lambda item: (item[1], item[0]))
        else:
            rows = sorted(
                rows,
                key=lambda item: (
                    catalog[item[0]].display_name(self.language).lower()
                    if item[0] in catalog
                    else item[0]
                ),
            )
        self._species_order = []
        self._species_allowed = {}
        self._species_level = {}
        self._species_labels = {}
        self._species_search = {}
        self._species_region_text = {}
        self._species_region_values = {}
        self._species_on_mainland = {}
        self._species_icons: dict[str, object] = {}
        for key, default in rows:
            allowed = key in wanted if mode == "whitelist" else key not in blocked
            self._species_order.append(key)
            self._species_allowed[key] = allowed
            self._species_level[key] = int(default)
            self._species_labels[key] = species_display_name_ui(key, self.language)
            row = catalog.get(key)
            self._species_search[key] = " ".join(species_search_names(key, row=row)).lower()
            if row is not None:
                regions = row.display_regions(self.language)
                self._species_region_text[key] = row.region_text(self.language)
                self._species_region_values[key] = regions
                self._species_on_mainland[key] = any(is_mainland_region(name) for name in regions)
                try:
                    self._species_icons[key] = row.image_path()
                except Exception:
                    self._species_icons[key] = None
            else:
                self._species_region_text[key] = ""
                self._species_region_values[key] = ()
                self._species_on_mainland[key] = False
                self._species_icons[key] = None
        self._refresh_species_rows()

    def _on_species_region_selected(self, _index: int = 0) -> None:
        self._species_region_user_set = True
        self._refresh_species_rows()
        if hasattr(self, "_refresh_monsters_summary"):
            self._refresh_monsters_summary()

    def _matching_map_region(self, region_values: list[str] | tuple[str, ...]) -> str:
        from i18n.localized_names import monster_region_candidates

        map_id = str(self.get_primary_map_id() or "")
        selected = self.get_map_label(map_id) if map_id else ""
        known = {str(value) for value in region_values}
        all_label = self.t.get("filter_all", "All")
        for name in monster_region_candidates(map_id, self.language):
            if name in known and name != all_label:
                return name
        if selected in known and selected != all_label:
            return selected
        return ""

    def _species_region_choice(self, region_values: list[str]) -> str:
        label = self._matching_map_region(region_values)
        if not self._species_region_user_set and label:
            return label
        current = self.species_region.currentText().strip()
        if current in region_values:
            return current
        if label:
            return label
        return self.t.get("filter_all", "All")

    def sync_species_region_to_map(self) -> None:
        """Point the monster region filter at the first battle map in the routine."""
        if not hasattr(self, "species_region"):
            return
        self._species_region_user_set = False
        values = [
            self.species_region.itemText(i) for i in range(self.species_region.count())
        ]
        if len(values) <= 1:
            return
        label = self._matching_map_region(values)
        chosen = label or self.t.get("filter_all", "All")
        if self.species_region.currentText() != chosen:
            idx = self.species_region.findText(chosen)
            if idx >= 0:
                self.species_region.blockSignals(True)
                self.species_region.setCurrentIndex(idx)
                self.species_region.blockSignals(False)
        if self._monsters_built:
            self._refresh_species_rows()
            if hasattr(self, "_refresh_monsters_summary"):
                self._refresh_monsters_summary()

    def _refresh_species_rows(self) -> None:
        if not hasattr(self, "species_table"):
            return
        show = str(self.species_show.currentData() or "all")
        region = self.species_region.currentText().strip()
        needle = self.species_search.text().strip().lower()
        all_label = self.t.get("filter_all", "All")
        self.species_table.setRowCount(0)
        shown = 0
        allowed_count = 0
        for key in self._species_order:
            allowed = bool(self._species_allowed.get(key, True))
            if allowed:
                allowed_count += 1
            if show == "allowed" and not allowed:
                continue
            if show == "unallowed" and allowed:
                continue
            if region and region != all_label:
                if region == self._mainland_label:
                    if not self._species_on_mainland.get(key, False):
                        continue
                elif region not in (self._species_region_values.get(key) or ()):
                    continue
            if needle and needle not in self._species_search.get(key, "") and needle not in self._species_labels.get(key, "").lower():
                continue
            row = self.species_table.rowCount()
            self.species_table.insertRow(row)
            icon_item = QTableWidgetItem()
            icon_item.setIcon(
                QIcon(
                    hunt_icon(
                        self._species_icons.get(key),
                        enabled=allowed,
                    )
                )
            )
            icon_item.setData(Qt.ItemDataRole.UserRole, key)
            icon_item.setFlags(icon_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.species_table.setItem(row, 0, icon_item)
            name_item = QTableWidgetItem(self._species_labels.get(key, key))
            name_item.setData(Qt.ItemDataRole.UserRole, key)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.species_table.setItem(row, 1, name_item)
            level_item = QTableWidgetItem(str(self._species_level.get(key, 0)))
            level_item.setData(Qt.ItemDataRole.UserRole, key)
            level_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            level_item.setFlags(level_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.species_table.setItem(row, 2, level_item)
            allow_item = QTableWidgetItem(
                self.t.get("yes", "Y") if allowed else self.t.get("no", "N")
            )
            allow_item.setFlags(allow_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.species_table.setItem(row, 3, allow_item)
            region_item = QTableWidgetItem(self._species_region_text.get(key, ""))
            region_item.setFlags(region_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.species_table.setItem(row, 4, region_item)
            shown += 1
        from ui_qt.editors.form_helpers import fit_table_columns

        fit_table_columns(self.species_table, stretch_last=True, min_width=48)
        self.species_table.setColumnWidth(0, HUNT_ICON_SIZE + 8)
        self.species_table.horizontalHeader().setSectionResizeMode(
            0, self.species_table.horizontalHeader().ResizeMode.Fixed
        )
        mode = self.bag.get_str("hunt", "species_filter_mode", "blacklist")
        self.monsters_summary.setPlainText(
            "\n".join(
                [
                    f"{self.t.get('filter_show', 'Show')}: {shown}",
                    f"{self.t.get('filter_allowed', 'Allowed')}: {allowed_count}",
                    f"{self.t.get('filter_unallowed', 'Blocked')}: {len(self._species_order) - allowed_count}",
                    f"mode: {mode}",
                ]
            )
        )

    def _on_species_double_clicked(self, index) -> None:
        if index.column() == 2:
            self._edit_species_level(index.row())
            return
        self._toggle_species()

    def _edit_species_level(self, row: int) -> None:
        item = self.species_table.item(row, 2) or self.species_table.item(row, 1)
        if item is None:
            return
        key = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not key:
            return
        current = int(self._species_level.get(key, 1) or 1)
        value, ok = QInputDialog.getInt(
            self,
            self.t.get("species_level", "Lv"),
            self._species_labels.get(key, key),
            current,
            1,
            99,
        )
        if not ok:
            return
        self._species_level[key] = int(value)
        level_item = self.species_table.item(row, 2)
        if level_item is not None:
            level_item.setText(str(int(value)))
        else:
            self._refresh_species_rows()

    def _toggle_species(self) -> None:
        rows = self.species_table.selectionModel().selectedRows()
        for model_index in rows:
            item = self.species_table.item(model_index.row(), 1) or self.species_table.item(
                model_index.row(), 0
            )
            if item is None:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not key:
                continue
            self._species_allowed[key] = not bool(self._species_allowed.get(key, True))
        self._refresh_species_rows()

    def _write_species_to_bag(self) -> None:
        mode = self.bag.get_str("hunt", "species_filter_mode", "blacklist")
        wanted, blocked = [], []
        for key in self._species_order:
            if self._species_allowed.get(key, True):
                wanted.append(key)
            else:
                blocked.append(key)
        if mode == "whitelist":
            self.bag.set("hunt", "species_whitelist", wanted)
            self.bag.set("hunt", "species_blacklist", [])
        else:
            self.bag.set("hunt", "species_blacklist", blocked)
            self.bag.set("hunt", "species_whitelist", [])
        self.bag.set("hunt", "species_levels", dict(self._species_level))

    def _build_items(self, page: QWidget) -> None:
        layout = page.layout() or QVBoxLayout(page)
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split)
        left = QWidget()
        right = QWidget()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        col = QVBoxLayout(left)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(self.t.get("filter_search", "Search")))
        self.item_search = QLineEdit()
        self.item_search.textChanged.connect(self._refresh_item_rows)
        search_row.addWidget(self.item_search, stretch=1)
        col.addLayout(search_row)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(self.t.get("filter_show", "Show")))
        self.item_show = QComboBox()
        for label, code in (
            (self.t.get("filter_all", "All"), "all"),
            (self.t.get("filter_allowed", "Allowed"), "allowed"),
            (self.t.get("filter_unallowed", "Blocked"), "unallowed"),
        ):
            self.item_show.addItem(label, code)
        self.item_show.currentIndexChanged.connect(lambda _i: self._refresh_item_rows())
        filter_row.addWidget(self.item_show)
        filter_row.addWidget(QLabel(self.t.get("filter_category", "Category")))
        self.item_category = QComboBox()
        self.item_category.addItem(self.t.get("filter_all", "All"))
        self.item_category.currentIndexChanged.connect(lambda _i: self._refresh_item_rows())
        filter_row.addWidget(self.item_category, stretch=1)
        col.addLayout(filter_row)
        mode_row = QHBoxLayout()
        self._item_mode = QButtonGroup(self)
        mode = self.bag.get_str("other", "item_pickup_mode", "blacklist")
        for value, label_key in (
            ("blacklist", "filter_blacklist"),
            ("whitelist", "filter_whitelist"),
        ):
            radio = QRadioButton(self.t.get(label_key, value))
            radio.setChecked(mode == value)
            self._item_mode.addButton(radio)
            radio.toggled.connect(
                lambda checked, v=value: checked and self._set_item_mode(v)
            )
            mode_row.addWidget(radio)
        mode_row.addStretch(1)
        col.addLayout(mode_row)
        hint = QLabel(self.t.get("item_filter_hint", self.t.get("species_filter_hint", "")))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        col.addWidget(hint)
        self.item_table = QTableWidget(0, 4)
        self.item_table.setHorizontalHeaderLabels(
            [
                "",
                self.t.get("col_name", "Name"),
                self.t.get("allowed", "Allow"),
                self.t.get("filter_category", "Category"),
            ]
        )
        self.item_table.verticalHeader().setVisible(False)
        self.item_table.setIconSize(QSize(HUNT_ICON_SIZE, HUNT_ICON_SIZE))
        self.item_table.verticalHeader().setDefaultSectionSize(HUNT_ICON_SIZE + 6)
        configure_select_rows(self.item_table)
        configure_table_fill(
            self.item_table, stretch_col=1, fixed={0: HUNT_ICON_SIZE + 8}
        )
        self.item_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.item_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.doubleClicked.connect(self._toggle_items)
        col.addWidget(self.item_table, stretch=1)
        toggle = QPushButton(self.t.get("toggle", "Toggle"))
        toggle.clicked.connect(self._toggle_items)
        col.addWidget(toggle)
        rcol = QVBoxLayout(right)
        rcol.addWidget(QLabel(self.t.get("settings_summary", "Summary")))
        self.items_summary = QTextEdit()
        self.items_summary.setReadOnly(True)
        rcol.addWidget(self.items_summary)
        split.setSizes([640, 220])

    def _set_item_mode(self, mode: str) -> None:
        self.bag.set("other", "item_pickup_mode", mode)
        self._load_items()

    def _load_items(self) -> None:
        selected = set(str(x) for x in (self.bag.get("other", "item_pickup_names", []) or []))
        mode = self.bag.get_str("other", "item_pickup_mode", "blacklist")
        try:
            from app._03_world.catalog.game_catalog import (
                item_category_labels,
                list_item_rows,
                resolve_item_key,
            )
            from i18n.localized_names import (
                item_catalog_display_name,
                item_category_display_name,
                item_search_names,
            )

            selected_keys = {resolve_item_key(name) or name for name in selected}
            entries = list(list_item_rows())
            language = self.language
            entries.sort(
                key=lambda entry: (
                    item_catalog_display_name(entry.name_ko, language) or entry.name_ko
                ).lower()
            )
            categories = [
                self.t.get("filter_all", "All"),
                *sorted(
                    {
                        item_category_display_name(name, language)
                        for name in item_category_labels(language)
                        if name
                    }
                ),
            ]
            self.item_category.blockSignals(True)
            self.item_category.clear()
            for name in categories:
                self.item_category.addItem(name)
            self.item_category.blockSignals(False)
        except Exception:
            entries = []
            selected_keys = selected
            item_catalog_display_name = lambda name, _lang: name  # noqa: E731
            item_search_names = lambda name, row=None: (name,)  # noqa: E731
            item_category_display_name = lambda name, _lang: name  # noqa: E731
            language = self.language

        self._item_order = []
        self._item_allowed = {}
        self._item_labels = {}
        self._item_search = {}
        self._item_categories = {}
        self._item_icons: dict[str, object] = {}
        for entry in entries:
            if mode == "whitelist":
                allowed = entry.key in selected_keys
            else:
                allowed = entry.key not in selected_keys
            self._item_order.append(entry.key)
            self._item_allowed[entry.key] = allowed
            self._item_labels[entry.key] = item_catalog_display_name(
                entry.name_ko, language
            ) or entry.display_name(language)
            self._item_search[entry.key] = " ".join(
                item_search_names(entry.name_ko, row=entry)
            ).lower()
            self._item_categories[entry.key] = (
                item_category_display_name(entry.category_ko, language)
                or entry.display_category(language)
            )
            try:
                self._item_icons[entry.key] = entry.image_path()
            except Exception:
                self._item_icons[entry.key] = None
        self._refresh_item_rows()

    def _refresh_item_rows(self) -> None:
        if not hasattr(self, "item_table"):
            return
        show = str(self.item_show.currentData() or "all")
        category = self.item_category.currentText().strip()
        needle = self.item_search.text().strip().lower()
        all_label = self.t.get("filter_all", "All")
        self.item_table.setRowCount(0)
        shown = allowed_count = 0
        for key in self._item_order:
            allowed = bool(self._item_allowed.get(key, True))
            if allowed:
                allowed_count += 1
            if show == "allowed" and not allowed:
                continue
            if show == "unallowed" and allowed:
                continue
            item_cat = self._item_categories.get(key, "")
            if category and category != all_label and item_cat != category:
                continue
            if needle and needle not in self._item_search.get(key, "") and needle not in self._item_labels.get(key, "").lower():
                continue
            row = self.item_table.rowCount()
            self.item_table.insertRow(row)
            icon_item = QTableWidgetItem()
            icon_item.setIcon(
                QIcon(hunt_icon(self._item_icons.get(key), enabled=allowed))
            )
            icon_item.setData(Qt.ItemDataRole.UserRole, key)
            self.item_table.setItem(row, 0, icon_item)
            name_item = QTableWidgetItem(self._item_labels.get(key, key))
            name_item.setData(Qt.ItemDataRole.UserRole, key)
            self.item_table.setItem(row, 1, name_item)
            self.item_table.setItem(
                row, 2, QTableWidgetItem(self.t.get("yes", "Y") if allowed else self.t.get("no", "N"))
            )
            self.item_table.setItem(row, 3, QTableWidgetItem(item_cat))
            shown += 1
        from ui_qt.editors.form_helpers import fit_table_columns

        fit_table_columns(self.item_table, stretch_last=False, min_width=48)
        # Name column absorbs leftover width.
        self.item_table.horizontalHeader().setSectionResizeMode(
            1, self.item_table.horizontalHeader().ResizeMode.Stretch
        )
        self.item_table.setColumnWidth(0, HUNT_ICON_SIZE + 8)
        self.item_table.horizontalHeader().setSectionResizeMode(
            0, self.item_table.horizontalHeader().ResizeMode.Fixed
        )
        self.items_summary.setPlainText(
            f"{self.t.get('filter_show', 'Show')}: {shown}\n"
            f"{self.t.get('filter_allowed', 'Allowed')}: {allowed_count}"
        )

    def _toggle_items(self) -> None:
        rows = self.item_table.selectionModel().selectedRows()
        for model_index in rows:
            item = self.item_table.item(model_index.row(), 1) or self.item_table.item(
                model_index.row(), 0
            )
            if item is None:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if key:
                self._item_allowed[key] = not bool(self._item_allowed.get(key, True))
        self._refresh_item_rows()

    def _write_items_to_bag(self) -> None:
        mode = self.bag.get_str("other", "item_pickup_mode", "blacklist")
        names = [
            key
            for key in self._item_order
            if (
                bool(self._item_allowed.get(key, True))
                if mode == "whitelist"
                else not bool(self._item_allowed.get(key, True))
            )
        ]
        self.bag.set("other", "item_pickup_mode", mode)
        self.bag.set("other", "item_pickup_names", names)
