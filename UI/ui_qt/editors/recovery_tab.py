"""Recovery tab — options + HP action order + live hotbar assign (lazy)."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from settings.hp_actions import (
    hotbar_binding_from_row,
    is_item_action,
    item_key_from_action,
    normalize_hp_actions,
)
from settings.profile import (
    DEFAULT_RETURN_WEIGHT_ABOVE,
    RETURN_WEIGHT_PCT_CHOICES,
    snap_return_weight_above,
)
from ui_qt.editors.form_helpers import (
    add_check,
    add_check_spin,
    add_spin_row,
    bind_gate,
    card,
    configure_select_rows,
    table_row_height_for_controls,
    wrap_cell_widget,
)
from ui_qt.facade.qt_bridge import QtBridge
from ui_qt.theme import tokens
from ui_qt.theme.apply import mark_accent
from ui_qt.viewmodels.settings_bag import SettingsBag
from ui_qt.widgets.step_spin import StepSpinBox


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


class RecoveryTab(QWidget):
    def __init__(
        self,
        *,
        bag: SettingsBag,
        strings: dict[str, str],
        language: str,
        bridge: QtBridge | None = None,
        on_log: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bag = bag
        self.bridge = bridge
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self._hp_built = False
        self._hp_actions: list[dict[str, Any]] = []
        self._hotbar_raw: list[dict] = []
        self._hotbar_stamp: object | None = None
        self._hotbar_worker: _HotbarWorker | None = None
        # section, check_key, spin_key, check, spin, check_default, spin_default
        self._fix_meters: list[
            tuple[str, str, str, QCheckBox, StepSpinBox, bool, int]
        ] = []
        self._weight_check: QCheckBox | None = None
        self._weight_combo: QComboBox | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        self.tabs = tabs
        self.options_page = QWidget()
        self.hp_page = QWidget()
        tabs.addTab(self.options_page, self.t.get("fix_options", "Options"))
        tabs.addTab(self.hp_page, self.t.get("hp_and_inventory", "HP / Hotbar"))
        tabs.currentChanged.connect(self._on_tab)
        root.addWidget(tabs)
        self._build_options(self.options_page)
        layout = QVBoxLayout(self.hp_page)
        layout.addWidget(QLabel(self.t.get("hp_action_order", "HP order")))
        layout.addStretch(1)

    def _on_tab(self, index: int) -> None:
        if index == 1 and not self._hp_built:
            layout = self.hp_page.layout()
            if layout is not None:
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
            self._build_hp(self.hp_page)
            self._hp_built = True

    def _build_options(self, page: QWidget) -> None:
        # Keep legacy keys present in the bag.
        for key, default, kind in (
            ("hp_recover_enabled", True, bool),
            ("hp_potion_below", 50, int),
            ("use_hp_potion", True, bool),
            ("use_heal", True, bool),
            ("escape_hp_below", 30, int),
        ):
            if self.bag.get("recovery", key, None) is None:
                self.bag.set("recovery", key, default if kind is bool else default)

        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        scroll.setWidget(host)
        outer.addWidget(scroll)
        body = QHBoxLayout(host)
        left = QVBoxLayout()
        mid = QVBoxLayout()
        right = QVBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(mid, 1)
        body.addLayout(right, 1)

        session = card(page, self.t.get("form_recovery", "Recovery"))
        left.addWidget(session)
        s = session.layout()
        assert isinstance(s, QVBoxLayout)
        mp_check, _mp_spin = add_check_spin(
            s, self.bag, "mp_recover_enabled", False,
            self.t.get("mp_recover", "MP"),
            "mp_potion_below", 30, 0, 100, self.t.get("pct_or_less", "%"),
            section="recovery", on_change=self._refresh_summary,
        )
        use_mp = add_check(
            s, self.bag, "recovery", "use_mp_potion",
            self.t.get("use_mp_potion", "Use MP potion"), False, self._refresh_summary,
        )
        bind_gate(mp_check, use_mp)
        add_check(
            s, self.bag, "recovery", "resurrect_if_dead",
            self.t.get("resurrect", "Resurrect"), True, self._refresh_summary,
        )
        add_check(
            s, self.bag, "recovery", "resume_after_relogin",
            self.t.get("resume_login", "Resume after login"), True, self._refresh_summary,
        )
        add_spin_row(
            s, self.bag, "recovery", "max_retries",
            self.t.get("retries", "Retries"), 3, 0, 999, on_change=self._refresh_summary,
        )

        returning = card(page, self.t.get("form_return", "Return"))
        left.addWidget(returning)
        r = returning.layout()
        assert isinstance(r, QVBoxLayout)
        self._bind_fix_meter(
            r, "return_mp_enabled", True, self.t.get("return_mp", "Return MP"),
            "return_mp_below", 15, 0, 100, self.t.get("pct_or_less", "%"),
        )
        self._bind_fix_meter(
            r, "return_idle_enabled", False, self.t.get("return_idle", "Idle"),
            "return_idle_seconds", 60, 1, 3600, self.t.get("seconds", "s"),
        )

        mother = card(page, self.t.get("fix_mother_tree", "Mother tree recovery"))
        left.addWidget(mother)
        mlay = mother.layout()
        assert isinstance(mlay, QVBoxLayout)
        self._bind_band(
            mlay,
            "mother_tree_hp_to_mp_enabled",
            self.t.get("mother_tree_hp_to_mp", "Use Body to Mind"),
            "mother_tree_hp_to_mp_hp",
            85,
            self.t.get("hp_ge", "HP ≥"),
            "mother_tree_hp_to_mp_mp",
            80,
            self.t.get("mp_le", "MP ≤"),
        )
        self._bind_band(
            mlay,
            "mother_tree_heal_enabled",
            self.t.get("mother_tree_heal", "Use heal"),
            "mother_tree_heal_hp",
            40,
            self.t.get("hp_le", "HP ≤"),
            "mother_tree_heal_mp",
            80,
            self.t.get("mp_ge", "MP ≥"),
        )
        left.addStretch(1)

        teleport = card(page, self.t.get("form_teleport", "Teleport"))
        mid.addWidget(teleport)
        tlay = teleport.layout()
        assert isinstance(tlay, QVBoxLayout)
        teleport_note = str(self.t.get("form_teleport_note", "") or "").strip()
        if teleport_note:
            note = QLabel(teleport_note)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
            tlay.addWidget(note)
        teleport_master = add_check(
            tlay, self.bag, "recovery", "random_teleport_enabled",
            self.t.get("random_teleport", "Teleport"), False, self._refresh_summary,
        )
        teleport_player = add_check(
            tlay, self.bag, "recovery", "teleport_on_player",
            self.t.get("teleport_player", "On player"), False, self._refresh_summary,
        )
        surround_check, surround_spin = add_check_spin(
            tlay, self.bag, "teleport_when_surrounded", False,
            self.t.get("teleport_surrounded", "Surrounded"),
            "teleport_surround_count", 10, 2, 20,
            self.t.get("teleport_surround_count_suffix", ""),
            section="recovery", on_change=self._refresh_summary,
        )
        bind_gate(teleport_master, teleport_player, surround_check, surround_spin)

        supplies = card(page, self.t.get("form_return_supplies", "Supplies"))
        mid.addWidget(supplies)
        sl = supplies.layout()
        assert isinstance(sl, QVBoxLayout)
        self._bind_fix_meter(
            sl, "return_potion_enabled", True,
            self.t.get("return_potion_count", "Potions"),
            "return_potion_count", 0, 0, 999, self.t.get("count_or_fewer", ""),
        )
        self._bind_fix_meter(
            sl, "return_arrow_enabled", True,
            self.t.get("return_arrow_count", "Arrows"),
            "return_arrow_count", 300, 0, 9999, self.t.get("count_or_fewer", ""),
        )
        self._bind_fix_meter(
            sl, "return_depoison_enabled", True,
            self.t.get("return_depoison_count", "Depoison"),
            "return_depoison_count", 1, 0, 999, self.t.get("count_or_fewer", ""),
        )
        self._bind_fix_meter(
            sl, "return_satiety_enabled", True,
            self.t.get("return_satiety", "Satiety"),
            "return_satiety_below", 25, 0, 100, self.t.get("pct_or_less", "%"),
        )
        self._bind_weight_meter(sl)
        add_check(
            sl, self.bag, "hunt", "return_no_supplies",
            self.t.get("return_supplies", "No supplies"), True, self._refresh_summary,
        )
        mid.addStretch(1)

        summary = card(page, self.t.get("settings_summary", "Summary"))
        right.addWidget(summary)
        sum_l = summary.layout()
        assert isinstance(sum_l, QVBoxLayout)
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        sum_l.addWidget(self.summary)
        self._refresh_summary()

    def _bind_fix_meter(
        self,
        layout: QVBoxLayout,
        check_key: str,
        check_default: bool,
        check_label: str,
        spin_key: str,
        spin_default: int,
        low: int,
        high: int,
        suffix: str = "",
        *,
        section: str = "hunt",
    ) -> tuple[QCheckBox, StepSpinBox]:
        check, spin = add_check_spin(
            layout,
            self.bag,
            check_key,
            check_default,
            check_label,
            spin_key,
            spin_default,
            low,
            high,
            suffix,
            section=section,
            on_change=self._refresh_summary,
        )
        self._fix_meters.append(
            (section, check_key, spin_key, check, spin, check_default, spin_default)
        )
        return check, spin

    def _bind_weight_meter(self, layout: QVBoxLayout) -> None:
        """Weight return gate: checkbox + fixed 50/60/70% list (no free spin)."""
        row = QHBoxLayout()
        check = QCheckBox(self.t.get("weight_gauge", "Weight"))
        check.setChecked(self.bag.get_bool("hunt", "return_weight_enabled", True))
        combo = QComboBox()
        for pct in RETURN_WEIGHT_PCT_CHOICES:
            combo.addItem(f"{pct}%", pct)
        current = snap_return_weight_above(
            self.bag.get_int(
                "hunt", "return_weight_above", DEFAULT_RETURN_WEIGHT_ABOVE
            )
        )
        self.bag.set("hunt", "return_weight_above", current)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.setEnabled(check.isChecked())

        def _sync_check(checked: bool) -> None:
            self.bag.set("hunt", "return_weight_enabled", bool(checked))
            combo.setEnabled(bool(checked))
            self._refresh_summary()

        def _sync_combo(_index: int = 0) -> None:
            data = combo.currentData()
            pct = snap_return_weight_above(
                data if data is not None else DEFAULT_RETURN_WEIGHT_ABOVE
            )
            self.bag.set("hunt", "return_weight_above", pct)
            self._refresh_summary()

        check.toggled.connect(_sync_check)
        combo.currentIndexChanged.connect(_sync_combo)
        row.addWidget(check)
        row.addWidget(combo)
        suffix = self.t.get("pct_or_more", "%")
        if suffix and suffix != "%":
            row.addWidget(QLabel(suffix))
        row.addStretch(1)
        layout.addLayout(row)
        self._weight_check = check
        self._weight_combo = combo

    def reload_from_bag(self) -> None:
        """Resync Fix/Return meters after load_task replaces bag.data."""
        for (
            section,
            check_key,
            spin_key,
            check,
            spin,
            check_default,
            spin_default,
        ) in self._fix_meters:
            check.blockSignals(True)
            spin.blockSignals(True)
            try:
                checked = self.bag.get_bool(section, check_key, check_default)
                check.setChecked(checked)
                spin.setValue(self.bag.get_int(section, spin_key, spin_default))
                spin.setEnabled(bool(checked))
            finally:
                spin.blockSignals(False)
                check.blockSignals(False)
        weight_check = self._weight_check
        weight_combo = self._weight_combo
        if weight_check is not None and weight_combo is not None:
            weight_check.blockSignals(True)
            weight_combo.blockSignals(True)
            try:
                checked = self.bag.get_bool("hunt", "return_weight_enabled", True)
                weight_check.setChecked(checked)
                pct = snap_return_weight_above(
                    self.bag.get_int(
                        "hunt", "return_weight_above", DEFAULT_RETURN_WEIGHT_ABOVE
                    )
                )
                self.bag.set("hunt", "return_weight_above", pct)
                index = weight_combo.findData(pct)
                weight_combo.setCurrentIndex(index if index >= 0 else 0)
                weight_combo.setEnabled(bool(checked))
            finally:
                weight_combo.blockSignals(False)
                weight_check.blockSignals(False)
        self._refresh_summary()

    def flush_options_to_bag(self) -> None:
        """Write Fix/Return check+spin widgets into the bag before save."""
        for section, check_key, spin_key, check, spin, _check_default, _spin_default in (
            self._fix_meters
        ):
            inner = getattr(spin, "_spin", None)
            if inner is not None and hasattr(inner, "interpretText"):
                inner.interpretText()
            self.bag.set(section, check_key, bool(check.isChecked()))
            self.bag.set(section, spin_key, int(spin.value()))
        if self._weight_check is not None and self._weight_combo is not None:
            self.bag.set(
                "hunt", "return_weight_enabled", bool(self._weight_check.isChecked())
            )
            data = self._weight_combo.currentData()
            self.bag.set(
                "hunt",
                "return_weight_above",
                snap_return_weight_above(
                    data if data is not None else DEFAULT_RETURN_WEIGHT_ABOVE
                ),
            )

    def _bind_band(
        self,
        layout: QVBoxLayout,
        gate: str,
        label: str,
        left_key: str,
        left_default: int,
        left_mark: str,
        right_key: str,
        right_default: int,
        right_mark: str,
    ) -> None:
        block = QVBoxLayout()
        block.setSpacing(2)
        check = QCheckBox(label)
        check.setChecked(self.bag.get_bool("recovery", gate, True))

        def _spin(key: str, default: int) -> StepSpinBox:
            spin = StepSpinBox()
            spin.setRange(0, 100)
            spin.setValue(self.bag.get_int("recovery", key, default))

            def _sync(value: int, name: str = key) -> None:
                self.bag.set("recovery", name, int(value))
                self._refresh_summary()

            spin.valueChanged.connect(_sync)
            return spin

        left = _spin(left_key, left_default)
        right = _spin(right_key, right_default)

        def _toggle(checked: bool) -> None:
            self.bag.set("recovery", gate, bool(checked))
            left.setEnabled(bool(checked))
            right.setEnabled(bool(checked))
            self._refresh_summary()

        check.toggled.connect(_toggle)
        left.setEnabled(check.isChecked())
        right.setEnabled(check.isChecked())
        block.addWidget(check)
        values = QHBoxLayout()
        values.setContentsMargins(22, 0, 0, 0)
        values.addWidget(QLabel(left_mark))
        values.addWidget(left)
        values.addWidget(QLabel("%"))
        values.addSpacing(10)
        values.addWidget(QLabel(right_mark))
        values.addWidget(right)
        values.addWidget(QLabel("%"))
        values.addStretch(1)
        block.addLayout(values)
        layout.addLayout(block)

    def _refresh_summary(self) -> None:
        if not hasattr(self, "summary"):
            return

        def on(section: str, key: str) -> str:
            return (
                self.t.get("summary_on", "ON")
                if self.bag.get_bool(section, key)
                else self.t.get("summary_off", "OFF")
            )

        lines = [
            f"{self.t.get('mp_recover', 'MP')}: {on('recovery', 'mp_recover_enabled')}",
            f"{self.t.get('resurrect', 'Resurrect')}: {on('recovery', 'resurrect_if_dead')}",
            f"{self.t.get('resume_login', 'Resume')}: {on('recovery', 'resume_after_relogin')}",
            f"{self.t.get('retries', 'Retries')}: {self.bag.get_int('recovery', 'max_retries', 3)}",
            f"{self.t.get('random_teleport', 'Teleport')}: {on('recovery', 'random_teleport_enabled')}",
            f"{self.t.get('return_mp', 'Return MP')}: {on('hunt', 'return_mp_enabled')}",
            (
                f"{self.t.get('mother_tree_hp_to_mp', 'Body to Mind')}: "
                f"{on('recovery', 'mother_tree_hp_to_mp_enabled')} "
                f"{self.t.get('hp_ge', 'HP ≥')} "
                f"{self.bag.get_int('recovery', 'mother_tree_hp_to_mp_hp', 85)}% "
                f"{self.t.get('mp_le', 'MP ≤')} "
                f"{self.bag.get_int('recovery', 'mother_tree_hp_to_mp_mp', 80)}%"
            ),
            (
                f"{self.t.get('mother_tree_heal', 'Heal')}: "
                f"{on('recovery', 'mother_tree_heal_enabled')} "
                f"{self.t.get('hp_le', 'HP ≤')} "
                f"{self.bag.get_int('recovery', 'mother_tree_heal_hp', 40)}% "
                f"{self.t.get('mp_ge', 'MP ≥')} "
                f"{self.bag.get_int('recovery', 'mother_tree_heal_mp', 80)}%"
            ),
            f"{self.t.get('return_supplies', 'Supplies')}: {on('hunt', 'return_no_supplies')}",
        ]
        self.summary.setPlainText("\n".join(f"• {line}" for line in lines))

    def _build_hp(self, page: QWidget) -> None:
        layout = page.layout() or QVBoxLayout(page)
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split)
        left = QWidget()
        right = QWidget()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)

        lcol = QVBoxLayout(left)
        order_card = card(left, self.t.get("hp_action_order", "HP order"))
        o = order_card.layout()
        assert isinstance(o, QVBoxLayout)
        note = QLabel(self.t.get("hp_action_note", ""))
        note.setWordWrap(True)
        note.setObjectName("muted")
        o.addWidget(note)
        self.hp_table = QTableWidget(0, 4)
        self.hp_table.setHorizontalHeaderLabels(
            [
                self.t.get("enabled", "On"),
                self.t.get("col_name", "Action"),
                self.t.get("hotbar_key", "Hotbar"),
                self.t.get("pct_or_less", "%"),
            ]
        )
        self.hp_table.verticalHeader().setVisible(False)
        self.hp_table.verticalHeader().setDefaultSectionSize(table_row_height_for_controls())
        configure_select_rows(self.hp_table)
        self.hp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.hp_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.Fixed)
        self.hp_table.setColumnWidth(0, 40)
        self.hp_table.setColumnWidth(3, 88)
        o.addWidget(self.hp_table, stretch=1)
        lcol.addWidget(order_card)

        rcol = QVBoxLayout(right)
        inv_card = card(
            right,
            self.t.get("fix_inventory", self.t.get("form_inventory", "Hotbar")),
        )
        inv = inv_card.layout()
        assert isinstance(inv, QVBoxLayout)
        live_note = QLabel(self.t.get("inventory_live_note", ""))
        live_note.setWordWrap(True)
        live_note.setObjectName("muted")
        inv.addWidget(live_note)
        hp_hint = QLabel(self.t.get("inventory_hp_hint", ""))
        hp_hint.setWordWrap(True)
        hp_hint.setObjectName("muted")
        inv.addWidget(hp_hint)
        self.inventory_status = QLabel(self.t.get("inventory_empty", ""))
        self.inventory_status.setWordWrap(True)
        self.inventory_status.setObjectName("muted")
        inv.addWidget(self.inventory_status)

        btn_row = QHBoxLayout()
        self.hp_hotbar_assign_btn = QPushButton(
            self.t.get("hp_hotbar_assign", "Assign to selected row")
        )
        self.hp_hotbar_assign_btn.clicked.connect(self._assign_hp_from_hotbar)
        btn_row.addWidget(self.hp_hotbar_assign_btn)
        self.hp_hotbar_clear_btn = QPushButton(
            self.t.get("hp_hotbar_clear", "Clear assignment")
        )
        self.hp_hotbar_clear_btn.clicked.connect(self._clear_hp_hotbar_assignment)
        btn_row.addWidget(self.hp_hotbar_clear_btn)
        btn_row.addStretch(1)
        inv.addLayout(btn_row)

        refresh_row = QHBoxLayout()
        self.inventory_refresh_btn = QPushButton(
            self.t.get("hotbar_refresh", self.t.get("inventory_refresh", "Refresh"))
        )
        mark_accent(self.inventory_refresh_btn)
        self.inventory_refresh_btn.clicked.connect(self._on_hotbar_refresh)
        refresh_row.addWidget(self.inventory_refresh_btn)
        refresh_row.addStretch(1)
        inv.addLayout(refresh_row)

        self.inventory_table = QTableWidget(0, 3)
        self.inventory_table.setHorizontalHeaderLabels(
            [
                self.t.get("slot", self.t.get("debug_slot", "Slot")),
                self.t.get("name", self.t.get("debug_name", "Name")),
                self.t.get("count", self.t.get("debug_count", "Qty")),
            ]
        )
        self.inventory_table.verticalHeader().setVisible(False)
        self.inventory_table.horizontalHeader().setStretchLastSection(False)
        self.inventory_table.horizontalHeader().setSectionResizeMode(
            1, self.inventory_table.horizontalHeader().ResizeMode.Stretch
        )
        self.inventory_table.setColumnWidth(0, 64)
        self.inventory_table.setColumnWidth(2, 56)
        configure_select_rows(self.inventory_table)
        self.inventory_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.inventory_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.inventory_table.doubleClicked.connect(
            lambda _idx: self._assign_hp_from_hotbar()
        )
        inv.addWidget(self.inventory_table, stretch=1)
        rcol.addWidget(inv_card)

        raw = self.bag.get("recovery", "hp_actions", None)
        self._hp_actions = normalize_hp_actions(
            raw,
            potion_pct=self.bag.get_int("recovery", "hp_potion_below", 50),
            heal_pct=70,
            escape_pct=self.bag.get_int("recovery", "escape_hp_below", 30),
            use_heal=self.bag.get_bool("recovery", "use_heal", True),
            use_potion=self.bag.get_bool("recovery", "use_hp_potion", True),
        )
        self._rebuild_hp_rows()
        self._paint_hp_hotbar(force=True)

    def _hp_label(self, action_id: str) -> str:
        key = str(action_id or "")
        mapping = {
            "heal": "hp_action_heal",
            "retreat": "hp_action_retreat",
            "hp_potion": "hp_action_hp_potion",
        }
        if key in mapping:
            return self.t.get(mapping[key], key)
        if is_item_action(key):
            return item_key_from_action(key) or key
        return key

    def _hp_action_hotbar_text(self, action_id: str) -> str:
        none = self.t.get("hp_action_hotbar_none", "Auto (from hotbar)")
        if action_id == "retreat":
            return "—"
        try:
            from app._04_decision.hp_actions import (
                find_hp_restore_hotbar,
                format_hotbar_binding,
            )
        except Exception:
            return none
        row = next(
            (r for r in self._hp_actions if str(r.get("id") or "") == action_id),
            None,
        )
        assigned = hotbar_binding_from_row(row)
        if assigned is not None:
            shown = format_hotbar_binding(assigned)
            item = str((row or {}).get("item") or "").strip()
            return f"{shown}" + (f" · {item}" if item else "")
        layout = self.bag.get("magic", "hotbar_layout", {}) or {}
        if not isinstance(layout, dict):
            layout = {}
        world = None
        snap = None
        if self.bridge is not None:
            try:
                tables = self.bridge.coordinator.controller.debug_snapshot().get("tables") or {}
                hotbar = tables.get("hotbar") if isinstance(tables, dict) else None
                if isinstance(hotbar, list) and hotbar:
                    slots = [row for row in hotbar if isinstance(row, dict)]
                    snap = {"slots": slots}
                    world = type("HotbarWorld", (), {"last_hotbar": snap})()
            except Exception:
                world = None
        if world is None and layout:
            world = type("HotbarWorld", (), {"last_hotbar": None})()
        slot = None
        extra = ""
        if is_item_action(action_id) or action_id == "hp_potion":
            item_key = item_key_from_action(action_id) if is_item_action(action_id) else "빨간 물약"
            slot = find_hp_restore_hotbar(world, item_key, layout=layout)
            if slot is not None and isinstance(snap, dict):
                for raw in snap.get("slots") or []:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        box = int(raw.get("box") or 0)
                    except (TypeError, ValueError):
                        box = 0
                    key = str(raw.get("key") or "").strip().lower()
                    if (box, key) != slot:
                        continue
                    count = raw.get("count")
                    try:
                        count_i = int(count) if count is not None else None
                    except (TypeError, ValueError):
                        count_i = None
                    if count_i is not None:
                        extra = f" ×{count_i}"
                    break
        elif action_id == "heal" and isinstance(snap, dict):
            try:
                from hotbar.inspect import find_role_on_hotbar

                slot = find_role_on_hotbar(snap, "heal")
            except Exception:
                slot = None
        shown = format_hotbar_binding(slot)
        if shown:
            return f"{shown}{extra}"
        return none

    def _rebuild_hp_rows(self) -> None:
        """Fill HP order table: enable · name · hotbar · % threshold."""
        if not hasattr(self, "hp_table"):
            return
        selected = self.hp_table.currentRow()
        self.hp_table.setRowCount(0)
        for index, row in enumerate(self._hp_actions):
            action_id = str(row.get("id") or "")
            self.hp_table.insertRow(index)

            enabled = QCheckBox()
            enabled.setChecked(bool(row.get("enabled", True)))
            enabled.toggled.connect(
                lambda checked, i=index: self._on_hp_row_enabled(i, checked)
            )
            self.hp_table.setCellWidget(
                index, 0, wrap_cell_widget(enabled, hpad=6, vpad=2)
            )

            name_item = QTableWidgetItem(self._hp_label(action_id))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.hp_table.setItem(index, 1, name_item)

            hot_item = QTableWidgetItem(self._hp_action_hotbar_text(action_id))
            hot_item.setFlags(hot_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.hp_table.setItem(index, 2, hot_item)

            spin = StepSpinBox(compact=True)
            spin.setRange(5, 95)
            try:
                pct = int(row.get("hp_below") or 30)
            except (TypeError, ValueError):
                pct = 30
            spin.setValue(max(5, min(95, pct)))
            spin.valueChanged.connect(
                lambda value, i=index: self._on_hp_row_pct(i, int(value))
            )
            self.hp_table.setCellWidget(
                index, 3, wrap_cell_widget(spin, hpad=3, vpad=2)
            )
            self.hp_table.setRowHeight(index, table_row_height_for_controls())

        from ui_qt.editors.form_helpers import sync_row_widget_selection

        sync_row_widget_selection(self.hp_table)
        if 0 <= selected < self.hp_table.rowCount():
            self.hp_table.selectRow(selected)

    def _on_hp_row_enabled(self, index: int, checked: bool) -> None:
        if index < 0 or index >= len(self._hp_actions):
            return
        updated = dict(self._hp_actions[index])
        updated["enabled"] = bool(checked)
        self._hp_actions[index] = updated
        self._write_hp_to_bag()

    def _on_hp_row_pct(self, index: int, value: int) -> None:
        if index < 0 or index >= len(self._hp_actions):
            return
        updated = dict(self._hp_actions[index])
        updated["hp_below"] = max(5, min(95, int(value)))
        self._hp_actions[index] = updated
        self._write_hp_to_bag()

    def refresh_hp_hotbar_keys(self) -> None:
        """Refresh the Hotbar column after a live scan (names may change)."""
        if not hasattr(self, "hp_table"):
            return
        for index, row in enumerate(self._hp_actions):
            if index >= self.hp_table.rowCount():
                break
            action_id = str(row.get("id") or "")
            text = self._hp_action_hotbar_text(action_id)
            item = self.hp_table.item(index, 2)
            if item is None:
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.hp_table.setItem(index, 2, item)
            else:
                item.setText(text)

    def _hotbar_layout(self) -> dict:
        layout = self.bag.get("magic", "hotbar_layout", {}) or {}
        return layout if isinstance(layout, dict) else {}

    def _sync_hp_spell_slots(self) -> None:
        from settings.hp_actions import apply_recovery_to_spell_slots

        previous = self.bag.get("magic", "spell_slots", {}) or {}
        if not isinstance(previous, dict):
            previous = {}
        synced = apply_recovery_to_spell_slots(previous, self._hp_actions)
        self.bag.set("magic", "spell_slots", synced)

    def _selected_hp_action_index(self) -> int:
        if not hasattr(self, "hp_table"):
            return -1
        rows = self.hp_table.selectionModel().selectedRows()
        if not rows:
            return -1
        return int(rows[0].row())

    def _selected_hotbar_cell(self) -> dict | None:
        if not hasattr(self, "inventory_table"):
            return None
        rows = self.inventory_table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if index < 0 or index >= len(self._hotbar_raw):
            return None
        item = self._hotbar_raw[index]
        return item if isinstance(item, dict) else None

    def _assign_hp_from_hotbar(self) -> None:
        index = self._selected_hp_action_index()
        if index < 0 or index >= len(self._hp_actions):
            self.inventory_status.setText(
                self.t.get("hp_hotbar_select_row", "Select HP potion or heal first.")
            )
            return
        action_id = str(self._hp_actions[index].get("id") or "")
        if action_id == "retreat":
            self.inventory_status.setText(
                self.t.get("hp_hotbar_retreat_no", "Safe-zone move has no hotbar cell.")
            )
            return
        if action_id not in ("heal", "hp_potion") and not is_item_action(action_id):
            self.inventory_status.setText(
                self.t.get("hp_hotbar_select_row", "Select HP potion or heal first.")
            )
            return
        cell = self._selected_hotbar_cell()
        if cell is None:
            self.inventory_status.setText(
                self.t.get("hp_hotbar_select_slot", "Select a hotbar cell first.")
            )
            return
        name = str(cell.get("name") or "").strip()
        if not name:
            self.inventory_status.setText(
                self.t.get("hp_hotbar_empty_cell", "That hotbar cell is empty.")
            )
            return
        try:
            box = int(cell.get("box") or 0)
        except (TypeError, ValueError):
            box = 0
        key = str(cell.get("key") or "").strip().lower()
        row = dict(self._hp_actions[index])
        row["box"] = box
        row["key"] = key
        if action_id == "hp_potion" or is_item_action(action_id):
            row["item"] = name
            row["id"] = "hp_potion"
        self._hp_actions[index] = row
        self._hp_actions = normalize_hp_actions(self._hp_actions)
        self._write_hp_to_bag()
        self._sync_hp_spell_slots()
        self._rebuild_hp_rows()
        if 0 <= index < self.hp_table.rowCount():
            self.hp_table.selectRow(index)
        from app._04_decision.hp_actions import format_hotbar_binding

        slot = format_hotbar_binding((box, key)) or f"F{box}-{key.upper()}"
        msg = self.t.get("hp_hotbar_assigned", "Assigned {action}: {slot}").format(
            action=self._hp_label(action_id),
            slot=slot,
        )
        self.inventory_status.setText(msg)
        self.on_log(msg)

    def _clear_hp_hotbar_assignment(self) -> None:
        index = self._selected_hp_action_index()
        if index < 0 or index >= len(self._hp_actions):
            self.inventory_status.setText(
                self.t.get("hp_hotbar_select_row", "Select HP potion or heal first.")
            )
            return
        action_id = str(self._hp_actions[index].get("id") or "")
        if action_id == "retreat":
            self.inventory_status.setText(
                self.t.get("hp_hotbar_retreat_no", "Safe-zone move has no hotbar cell.")
            )
            return
        row = dict(self._hp_actions[index])
        row.pop("box", None)
        row.pop("key", None)
        row.pop("item", None)
        self._hp_actions[index] = row
        self._hp_actions = normalize_hp_actions(self._hp_actions)
        self._write_hp_to_bag()
        self._sync_hp_spell_slots()
        self._rebuild_hp_rows()
        if 0 <= index < self.hp_table.rowCount():
            self.hp_table.selectRow(index)
        msg = self.t.get("hp_hotbar_cleared", "Cleared — auto from hotbar.")
        self.inventory_status.setText(msg)
        self.on_log(msg)

    def _on_hotbar_refresh(self) -> None:
        if self._hotbar_worker is not None and self._hotbar_worker.isRunning():
            return
        self.inventory_refresh_btn.setEnabled(False)
        self.inventory_status.setText(
            self.t.get("hotbar_refreshing", self.t.get("inventory_refreshing", "Refreshing…"))
        )
        self._hotbar_worker = _HotbarWorker(self)
        self._hotbar_worker.finished_ok.connect(self._finish_hotbar_ok)
        self._hotbar_worker.failed.connect(self._finish_hotbar_fail)
        self._hotbar_worker.finished.connect(
            lambda: self.inventory_refresh_btn.setEnabled(True)
        )
        self._hotbar_worker.start()

    def _finish_hotbar_ok(self, layout: object) -> None:
        if isinstance(layout, dict):
            self.bag.set("magic", "hotbar_layout", dict(layout))
            self._paint_hp_hotbar(force=True)
            self.refresh_hp_hotbar_keys()
            return
        self._finish_hotbar_fail(self.t.get("inventory_empty", "—"))

    def _finish_hotbar_fail(self, message: str) -> None:
        self._paint_hp_hotbar(force=True)
        self.inventory_status.setText(
            self.t.get("hotbar_refresh_failed", "Failed: {error}").format(
                error=message or "—"
            )
        )

    def _paint_hp_hotbar(self, *, force: bool = False) -> None:
        from settings.haste_potion import hotbar_picker_rows

        if not hasattr(self, "inventory_table"):
            return
        items = hotbar_picker_rows(self._hotbar_layout())
        self._hotbar_raw = list(items)

        def cell(value: object) -> str:
            if value is None or value == "":
                return "—"
            return str(value)

        rows: list[tuple[str, str, str]] = [
            (cell(item.get("slot")), cell(item.get("name")), cell(item.get("count")))
            for item in items
        ]
        stamp = tuple(rows)
        if not force and stamp == self._hotbar_stamp:
            return
        self._hotbar_stamp = stamp
        selected = self.inventory_table.currentRow()
        self.inventory_table.setRowCount(0)
        for index, row in enumerate(rows):
            self.inventory_table.insertRow(index)
            for col, text in enumerate(row):
                cell_item = QTableWidgetItem(text)
                if col != 1:
                    cell_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.inventory_table.setItem(index, col, cell_item)
        if 0 <= selected < self.inventory_table.rowCount():
            self.inventory_table.selectRow(selected)
        filled = sum(1 for item in items if str(item.get("name") or "").strip())
        self.inventory_status.setText(
            self.t.get("hotbar_total_slots", "Slots: {count}").format(
                count=f"{filled}/24"
            )
        )

    def _write_hp_to_bag(self) -> None:
        from settings.hp_actions import sync_legacy_from_actions

        self.bag.set("recovery", "hp_actions", list(self._hp_actions))
        for key, value in sync_legacy_from_actions(self._hp_actions).items():
            self.bag.set("recovery", key, value)
        self._sync_hp_spell_slots()

    def apply_to_profile(self) -> None:
        if self._hp_built:
            self._write_hp_to_bag()
        self.bag.apply_to_profile()
        self.on_log(self.t.get("saved", "Saved"))
