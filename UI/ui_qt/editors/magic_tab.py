"""Magic tab — general settings + individual skills (lazy)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from settings.skill_catalog import load_skill_catalog
from ui_qt.editors.form_helpers import (
    add_check,
    add_check_spin,
    add_spin_row,
    bind_gate,
    card,
    configure_select_rows,
    configure_table_fill,
    table_row_height_for_controls,
    wrap_cell_widget,
)
from ui_qt.icon_helpers import MAGIC_ICON_SIZE, magic_icon
from ui_qt.theme import tokens
from ui_qt.viewmodels.settings_bag import SettingsBag
from ui_qt.widgets.step_spin import StepSpinBox

_MAGIC_CATEGORIES = (
    "attack_buff",
    "defense_buff",
    "vision",
    "recovery",
    "mp",
    "attack_magic",
    "utility",
)


class MagicTab(QWidget):
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
        self._individual_built = False
        self._catalog = load_skill_catalog()
        self._ui_class = "elf"
        self._category = "attack_buff"
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        self.tabs = tabs
        self.general_page = QWidget()
        self.individual_page = QWidget()
        tabs.addTab(self.general_page, self.t.get("general", "General"))
        tabs.addTab(self.individual_page, self.t.get("individual", "Individual"))
        tabs.currentChanged.connect(self._on_tab)
        root.addWidget(tabs)
        self._build_general(self.general_page)
        layout = QVBoxLayout(self.individual_page)
        layout.addWidget(QLabel(self.t.get("individual_magic", "Individual magic")))
        layout.addStretch(1)

    def _on_tab(self, index: int) -> None:
        if index == 1 and not self._individual_built:
            layout = self.individual_page.layout()
            if layout is not None:
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
            self._build_individual(self.individual_page)
            self._individual_built = True
            self._refresh_skills()

    def _build_general(self, page: QWidget) -> None:
        body = QHBoxLayout(page)
        left = QVBoxLayout()
        right = QVBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 1)

        general = card(page, self.t.get("magic_general_settings", "General"))
        left.addWidget(general)
        g = general.layout()
        assert isinstance(g, QVBoxLayout)
        add_spin_row(
            g, self.bag, "magic", "heal_until_hp_pct",
            self.t.get("heal_until", "Heal until"), 50, 0, 100, "%",
            self._refresh_magic_summary,
        )
        add_spin_row(
            g, self.bag, "magic", "spell_reserve_pct",
            self.t.get("reserve_mp", "Reserve MP"), 20, 0, 100, "%",
            self._refresh_magic_summary,
        )
        add_check(
            g, self.bag, "magic", "disable_in_combat",
            self.t.get("disable_combat", "Disable in combat"), False,
            self._refresh_magic_summary,
        )
        add_check_spin(
            g, self.bag, "stop_below_mp", False, self.t.get("stop_mp", "Stop below MP"),
            "stop_below_mp_pct", 20, 0, 100, "%",
            section="magic", on_change=self._refresh_magic_summary,
        )

        extra = card(page, self.t.get("magic_extra", "Extra"))
        left.addWidget(extra)
        e = extra.layout()
        assert isinstance(e, QVBoxLayout)
        add_check(
            e, self.bag, "magic", "buff_after_death",
            self.t.get("buff_after_death", "Buff after death"), True,
            self._refresh_magic_summary,
        )
        # Classic: checkbox + min spin ~ max spin + ms (no English "min"/"max" labels).
        cast_row = QHBoxLayout()
        cast_delay = QCheckBox(self.t.get("magic_cast_delay", "Cast delay"))
        cast_delay.setChecked(self.bag.get_bool("magic", "cast_delay", True))
        cast_min = StepSpinBox()
        cast_min.setRange(0, 5000)
        cast_min.setValue(self.bag.get_int("magic", "cast_delay_min_ms", 80))
        cast_max = StepSpinBox()
        cast_max.setRange(0, 5000)
        cast_max.setValue(self.bag.get_int("magic", "cast_delay_max_ms", 180))
        ms = QLabel(self.t.get("ms_unit", "ms"))

        def _sync_cast(_value: object = None) -> None:
            self.bag.set("magic", "cast_delay", bool(cast_delay.isChecked()))
            self.bag.set("magic", "cast_delay_min_ms", int(cast_min.value()))
            self.bag.set("magic", "cast_delay_max_ms", int(cast_max.value()))
            self._refresh_magic_summary()

        cast_delay.toggled.connect(_sync_cast)
        cast_min.valueChanged.connect(_sync_cast)
        cast_max.valueChanged.connect(_sync_cast)
        cast_row.addWidget(cast_delay)
        cast_row.addWidget(cast_min)
        cast_row.addWidget(QLabel("~"))
        cast_row.addWidget(cast_max)
        cast_row.addWidget(ms)
        cast_row.addStretch(1)
        e.addLayout(cast_row)
        bind_gate(cast_delay, cast_min, cast_max)
        add_check(
            e, self.bag, "magic", "buff_after_combat",
            self.t.get("buff_after_combat", "Buff after combat"), True,
            self._refresh_magic_summary,
        )
        add_check(
            e, self.bag, "magic", "town_general_only",
            self.t.get("town_general_only", "Town general only"), True,
            self._refresh_magic_summary,
        )
        left.addStretch(1)

        summary = card(page, self.t.get("settings_summary", "Summary"))
        right.addWidget(summary)
        s = summary.layout()
        assert isinstance(s, QVBoxLayout)
        self.magic_summary = QTextEdit()
        self.magic_summary.setReadOnly(True)
        s.addWidget(self.magic_summary)
        self._refresh_magic_summary()

    def _refresh_magic_summary(self) -> None:
        if not hasattr(self, "magic_summary"):
            return

        def state(name: str) -> str:
            return (
                self.t.get("summary_on", "ON")
                if self.bag.get_bool("magic", name)
                else self.t.get("summary_off", "OFF")
            )

        hp = self.bag.get_int("magic", "heal_until_hp_pct", 50)
        reserve = self.bag.get_int("magic", "spell_reserve_pct", 20)
        stop_pct = self.bag.get_int("magic", "stop_below_mp_pct", 20)
        low = self.bag.get_int("magic", "cast_delay_min_ms", 80)
        high = self.bag.get_int("magic", "cast_delay_max_ms", 180)
        lines = [
            f"{self.t.get('heal_until', 'Heal')}: {hp}%",
            f"{self.t.get('reserve_mp', 'Reserve')}: {reserve}%",
            f"{self.t.get('disable_combat', 'Disable')}: {state('disable_in_combat')}",
            f"{self.t.get('stop_mp_summary', 'Stop MP < {pct}%').format(pct=stop_pct)}: "
            f"{state('stop_below_mp')}",
            f"{self.t.get('buff_after_death', 'Buff death')}: {state('buff_after_death')}",
            (
                f"{self.t.get('magic_delay_summary', 'Delay')}: {low} ~ {high} "
                f"{self.t.get('ms_unit', 'ms')}"
                if self.bag.get_bool("magic", "cast_delay", True)
                else f"{self.t.get('magic_delay_summary', 'Delay')}: {self.t.get('summary_off', 'OFF')}"
            ),
            f"{self.t.get('buff_after_combat', 'Buff combat')}: {state('buff_after_combat')}",
            f"{self.t.get('town_general_only', 'Town')}: {state('town_general_only')}",
        ]
        self.magic_summary.setPlainText("\n".join(f"• {line}" for line in lines))

    def _build_individual(self, page: QWidget) -> None:
        layout = page.layout() or QVBoxLayout(page)
        title = QLabel(self.t.get("individual_magic", "Individual magic"))
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        picker = QHBoxLayout()
        picker.addWidget(QLabel(self.t.get("magic_class", "Class")))
        self.class_combo = QComboBox()
        for name in ("elf", "mage", "knight", "royal"):
            self.class_combo.addItem(self.t.get(name, name), name)
        character = self.bag.get_str("magic", "class", "elf")
        if character not in ("elf", "mage", "knight", "royal"):
            character = "elf"
        self._ui_class = character
        index = self.class_combo.findData(character)
        if index >= 0:
            self.class_combo.setCurrentIndex(index)
        self.class_combo.currentIndexChanged.connect(self._on_class)
        picker.addWidget(self.class_combo)
        class_hint = QLabel(self.t.get("class_magic_hint", ""))
        class_hint.setWordWrap(True)
        class_hint.setObjectName("muted")
        picker.addWidget(class_hint, stretch=1)
        layout.addLayout(picker)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(self.t.get("filter_search", "Search")))
        self.skill_search = QLineEdit()
        self.skill_search.setPlaceholderText(self.t.get("filter_search", "Search"))
        self.skill_search.textChanged.connect(lambda _t: self._refresh_skills())
        filter_row.addWidget(self.skill_search, stretch=1)
        filter_row.addWidget(QLabel(self.t.get("filter_show", "Show")))
        self.skill_show = QComboBox()
        for label, code in (
            (self.t.get("filter_all", "All"), "all"),
            (self.t.get("filter_allowed", "Enabled"), "enabled"),
            (self.t.get("filter_unallowed", "Disabled"), "disabled"),
        ):
            self.skill_show.addItem(label, code)
        self.skill_show.currentIndexChanged.connect(lambda _i: self._refresh_skills())
        filter_row.addWidget(self.skill_show)
        layout.addLayout(filter_row)

        from ui_qt.widgets.flow_layout import FlowLayout

        cats_host = QWidget()
        cats = FlowLayout(cats_host, margin=0, spacing=4)
        self._category_buttons: list[tuple[str, QPushButton]] = []
        for key in _MAGIC_CATEGORIES:
            btn = QPushButton(self._catalog.category_label(key, self.language))
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, name=key: self._select_category(name))
            self._category_buttons.append((key, btn))
            cats.addWidget(btn)
        layout.addWidget(cats_host)

        body = QHBoxLayout()
        layout.addLayout(body, stretch=1)
        left = QVBoxLayout()
        body.addLayout(left, stretch=4)
        self.skill_table = QTableWidget(0, 5)
        self.skill_table.setHorizontalHeaderLabels(
            [
                self.t.get("enabled", "On"),
                "",
                self.t.get("col_magic_name", "Name"),
                self.t.get("col_auto", "Auto"),
                self.t.get("col_priority", "Priority"),
            ]
        )
        self.skill_table.verticalHeader().setVisible(False)
        self.skill_table.setIconSize(QSize(MAGIC_ICON_SIZE, MAGIC_ICON_SIZE))
        self.skill_table.verticalHeader().setDefaultSectionSize(MAGIC_ICON_SIZE + 8)
        configure_select_rows(self.skill_table)
        configure_table_fill(
            self.skill_table, stretch_col=2, fixed={1: MAGIC_ICON_SIZE + 8}
        )
        self.skill_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        left.addWidget(self.skill_table, stretch=1)
        tools = QHBoxLayout()
        enable_all = QPushButton(self.t.get("select_all", "Select all"))
        disable_all = QPushButton(self.t.get("deselect_all", "Deselect all"))
        reset = QPushButton(self.t.get("reset_magic", "Reset"))
        enable_all.clicked.connect(lambda: self._set_visible(True))
        disable_all.clicked.connect(lambda: self._set_visible(False))
        reset.clicked.connect(self._reset_visible)
        tools.addWidget(enable_all)
        tools.addWidget(disable_all)
        tools.addWidget(reset)
        tools.addStretch(1)
        left.addLayout(tools)

        side = QVBoxLayout()
        body.addLayout(side, stretch=1)
        side.addWidget(QLabel(self.t.get("settings_summary", "Summary")))
        self.pick_summary = QTextEdit()
        self.pick_summary.setReadOnly(True)
        side.addWidget(self.pick_summary)
        self._select_category(self._category)

    def _on_class(self) -> None:
        self._ui_class = str(self.class_combo.currentData() or "elf")
        self.bag.set("magic", "class", self._ui_class)
        self._refresh_skills()

    def _select_category(self, key: str) -> None:
        self._category = key
        for name, btn in getattr(self, "_category_buttons", []):
            btn.setChecked(name == key)
        self._refresh_skills()

    def _visible_skills(self):
        skills = list(self._catalog.for_filter(self._ui_class, self._category))
        needle = ""
        if hasattr(self, "skill_search"):
            needle = self.skill_search.text().strip().lower()
        show = "all"
        if hasattr(self, "skill_show"):
            show = str(self.skill_show.currentData() or "all")
        out = []
        for skill in skills:
            label = skill.label(self.language)
            state = self.bag.skill_state(skill.setting_key)
            enabled = bool(state.get("enabled"))
            if show == "enabled" and not enabled:
                continue
            if show == "disabled" and enabled:
                continue
            if needle and needle not in label.lower() and needle not in skill.setting_key.lower():
                continue
            out.append(skill)
        return out

    def _refresh_skills(self) -> None:
        if not hasattr(self, "skill_table"):
            return
        self.skill_table.setRowCount(0)
        selected_names: list[str] = []
        # Summary lists all enabled in category (not only filtered view).
        for skill in self._catalog.for_filter(self._ui_class, self._category):
            state = self.bag.skill_state(skill.setting_key)
            if state.get("enabled"):
                selected_names.append(skill.label(self.language))
        for skill in self._visible_skills():
            state = self.bag.skill_state(skill.setting_key)
            row = self.skill_table.rowCount()
            self.skill_table.insertRow(row)
            enabled = QCheckBox()
            enabled.setChecked(bool(state.get("enabled")))
            enabled.toggled.connect(
                lambda checked, key=skill.setting_key: self._skill_changed(key, enabled=checked)
            )
            self.skill_table.setCellWidget(row, 0, enabled)
            icon_item = QTableWidgetItem()
            icon_item.setIcon(QIcon(magic_icon(getattr(skill, "icon", None))))
            self.skill_table.setItem(row, 1, icon_item)
            name_item = QTableWidgetItem(skill.label(self.language))
            name_item.setData(Qt.ItemDataRole.UserRole, skill.setting_key)
            self.skill_table.setItem(row, 2, name_item)
            auto = QCheckBox()
            auto.setChecked(bool(state.get("auto", True)))
            auto.toggled.connect(
                lambda checked, key=skill.setting_key: self._skill_changed(key, auto=checked)
            )
            self.skill_table.setCellWidget(row, 3, auto)
            spin = StepSpinBox(compact=True)
            spin.setRange(1, 99)
            spin.setValue(int(state.get("priority") or 1))
            spin.valueChanged.connect(
                lambda value, key=skill.setting_key: self._skill_changed(key, priority=value)
            )
            self.skill_table.setCellWidget(row, 4, wrap_cell_widget(spin, hpad=3, vpad=2))
            self.skill_table.setRowHeight(row, table_row_height_for_controls())
        from ui_qt.editors.form_helpers import sync_row_widget_selection

        sync_row_widget_selection(self.skill_table)
        self.pick_summary.setPlainText(
            "\n".join(
                [
                    f"{self.t.get('summary_class', 'Class')}: {self.t.get(self._ui_class, self._ui_class)}",
                    f"{self.t.get('summary_category', 'Category')}: "
                    f"{self._catalog.category_label(self._category, self.language)}",
                    f"{self.t.get('selected_magic', 'Selected')}: "
                    f"{self.t.get('magic_selected_count', '{count}').format(count=len(selected_names))}",
                    "",
                    *[f"• {name}" for name in selected_names],
                ]
            )
        )

    def _skill_changed(self, key: str, **fields) -> None:
        self.bag.set_skill_state(key, **fields)
        # Light summary refresh without rebuilding every checkbox.
        selected = []
        for skill in self._visible_skills():
            if self.bag.skill_state(skill.setting_key).get("enabled"):
                selected.append(skill.label(self.language))
        self.pick_summary.setPlainText(
            "\n".join(
                [
                    f"{self.t.get('summary_class', 'Class')}: {self.t.get(self._ui_class, self._ui_class)}",
                    f"{self.t.get('summary_category', 'Category')}: "
                    f"{self._catalog.category_label(self._category, self.language)}",
                    f"{self.t.get('selected_magic', 'Selected')}: "
                    f"{self.t.get('magic_selected_count', '{count}').format(count=len(selected))}",
                    "",
                    *[f"• {name}" for name in selected],
                ]
            )
        )

    def _set_visible(self, enabled: bool) -> None:
        for skill in self._visible_skills():
            self.bag.set_skill_state(skill.setting_key, enabled=enabled)
        self._refresh_skills()

    def _reset_visible(self) -> None:
        for skill in self._visible_skills():
            self.bag.set_skill_state(
                skill.setting_key, enabled=False, auto=True, priority=1, hotkey=""
            )
        self._refresh_skills()

    def apply_to_profile(self) -> None:
        self.bag.apply_to_profile()
        self.on_log(self.t.get("saved", "Saved"))
