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
# Exact catalog names. Greater Heal / Mass Teleport stay user-toggleable.
_LOCKED_SKILL_KO = frozenset({"힐", "텔레포트"})


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
        self._skill_guard = False
        self._skills_ready = False
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
        self.skill_table = QTableWidget(0, 4)
        self.skill_table.setHorizontalHeaderLabels(
            [
                self.t.get("col_auto", "Auto"),
                "",
                self.t.get("col_magic_name", "Name"),
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
        self._ensure_skill_model()
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

    def _locked_skill(self, skill) -> bool:
        return str(getattr(skill, "ko", "") or "") in _LOCKED_SKILL_KO

    def _class_skills(self, ui_class: str):
        rows = []
        for category in _MAGIC_CATEGORIES:
            rows.extend(self._catalog.for_filter(ui_class, category))
        return rows

    def _is_auto(self, skill) -> bool:
        if self._locked_skill(skill):
            return True
        return bool(self.bag.skill_state(skill.setting_key).get("auto"))

    def _checked_skills(self, ui_class: str):
        return [skill for skill in self._class_skills(ui_class) if self._is_auto(skill)]

    def _ranked_skills(self, ui_class: str):
        """Checked skills that take a priority. Heal and Teleport stay outside."""
        return [skill for skill in self._checked_skills(ui_class) if not self._locked_skill(skill)]

    def _locked_skills(self, ui_class: str):
        return [skill for skill in self._class_skills(ui_class) if self._locked_skill(skill)]

    def _ensure_skill_model(self) -> None:
        """Keep Heal/Teleport on, and give checked skills unique priorities."""
        if self._skills_ready:
            return
        for skill in self._catalog.skills:
            state = self.bag.skill_state(skill.setting_key)
            if not state.get("auto_is_selection"):
                # The removed On column was the old selection. Auto used to default on.
                selected = bool(state.get("enabled")) or self._locked_skill(skill)
                self.bag.set_skill_state(
                    skill.setting_key,
                    auto=selected,
                    enabled=selected,
                    auto_is_selection=True,
                )
            elif self._locked_skill(skill) and not state.get("auto"):
                self.bag.set_skill_state(
                    skill.setting_key, auto=True, enabled=True
                )
        for ui_class in ("elf", "mage", "knight", "royal"):
            self._assign_priorities(ui_class, reset_order=False)
        self._skills_ready = True

    def _priorities_valid(self, checked) -> bool:
        found = []
        for skill in checked:
            try:
                found.append(int(self.bag.skill_state(skill.setting_key).get("priority") or 0))
            except (TypeError, ValueError):
                return False
        return sorted(found) == list(range(1, len(checked) + 1))

    def _assign_priorities(self, ui_class: str, *, reset_order: bool) -> None:
        checked = self._ranked_skills(ui_class)
        if not checked:
            return
        if not reset_order and self._priorities_valid(checked):
            return
        for index, skill in enumerate(checked, start=1):
            self.bag.set_skill_state(
                skill.setting_key, auto=True, enabled=True, priority=index
            )

    def _set_auto(self, key: str, checked: bool) -> None:
        if self._skill_guard:
            return
        skill = next(
            (row for row in self._class_skills(self._ui_class) if row.setting_key == key),
            None,
        )
        if skill is None or self._locked_skill(skill):
            return
        self._skill_guard = True
        try:
            self.bag.set_skill_state(key, auto=bool(checked), enabled=bool(checked))
            self._assign_priorities(self._ui_class, reset_order=True)
        finally:
            self._skill_guard = False
        self._refresh_skills()

    def _set_priority(self, key: str, value: int) -> None:
        if self._skill_guard:
            return
        checked = self._ranked_skills(self._ui_class)
        count = len(checked)
        if count <= 0:
            return
        target = max(1, min(count, int(value)))
        try:
            current = int(self.bag.skill_state(key).get("priority") or 1)
        except (TypeError, ValueError):
            current = 1
        if target == current:
            return
        self._skill_guard = True
        try:
            for skill in checked:
                if skill.setting_key == key:
                    continue
                other = int(self.bag.skill_state(skill.setting_key).get("priority") or 0)
                if other == target:
                    self.bag.set_skill_state(skill.setting_key, priority=current)
                    break
            self.bag.set_skill_state(key, priority=target)
        finally:
            self._skill_guard = False
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
            selected = self._is_auto(skill)
            if show == "enabled" and not selected:
                continue
            if show == "disabled" and selected:
                continue
            if needle and needle not in label.lower() and needle not in skill.setting_key.lower():
                continue
            out.append(skill)
        return out

    def _summary_lines(self) -> list[str]:
        selected = []
        for skill in self._ranked_skills(self._ui_class):
            priority = int(self.bag.skill_state(skill.setting_key).get("priority") or 0)
            selected.append((priority, skill.label(self.language)))
        selected.sort(key=lambda item: (item[0], item[1]))
        lines = [
            f"{self.t.get('summary_class', 'Class')}: {self.t.get(self._ui_class, self._ui_class)}",
            f"{self.t.get('selected_magic', 'Selected')}: "
            f"{self.t.get('magic_selected_count', '{count}').format(count=len(selected))}",
            "",
            *[f"{priority}. {name}" for priority, name in selected],
        ]
        locked = [skill.label(self.language) for skill in self._locked_skills(self._ui_class)]
        if locked:
            if selected:
                lines.append("")
            lines.extend(locked)
        return lines

    def _refresh_skills(self) -> None:
        if not hasattr(self, "skill_table"):
            return
        self._ensure_skill_model()
        checked_count = len(self._ranked_skills(self._ui_class))
        self._skill_guard = True
        try:
            self.skill_table.setRowCount(0)
            for skill in self._visible_skills():
                state = self.bag.skill_state(skill.setting_key)
                locked = self._locked_skill(skill)
                selected = True if locked else bool(state.get("auto"))
                row = self.skill_table.rowCount()
                self.skill_table.insertRow(row)
                auto = QCheckBox()
                auto.setChecked(selected)
                if locked:
                    auto.setEnabled(False)
                else:
                    auto.toggled.connect(
                        lambda checked, key=skill.setting_key: self._set_auto(key, checked)
                    )
                self.skill_table.setCellWidget(row, 0, auto)
                icon_item = QTableWidgetItem()
                icon_item.setIcon(QIcon(magic_icon(getattr(skill, "icon", None))))
                self.skill_table.setItem(row, 1, icon_item)
                name_item = QTableWidgetItem(skill.label(self.language))
                name_item.setData(Qt.ItemDataRole.UserRole, skill.setting_key)
                self.skill_table.setItem(row, 2, name_item)
                spin = StepSpinBox(compact=True)
                spin.blockSignals(True)
                if locked or not selected or checked_count <= 0:
                    spin.setRange(0, 0)
                    spin.setValue(0)
                    spin._spin.setSpecialValueText("—")
                    spin.setEnabled(False)
                else:
                    spin.setRange(1, checked_count)
                    spin.setValue(int(state.get("priority") or 1))
                    spin.setEnabled(True)
                spin.blockSignals(False)
                if selected and not locked:
                    spin.valueChanged.connect(
                        lambda value, key=skill.setting_key: self._set_priority(key, value)
                    )
                self.skill_table.setCellWidget(row, 3, wrap_cell_widget(spin, hpad=3, vpad=2))
                self.skill_table.setRowHeight(row, table_row_height_for_controls())
        finally:
            self._skill_guard = False
        from ui_qt.editors.form_helpers import sync_row_widget_selection

        sync_row_widget_selection(self.skill_table)
        self.pick_summary.setPlainText("\n".join(self._summary_lines()))

    def _set_visible(self, enabled: bool) -> None:
        self._ensure_skill_model()
        self._skill_guard = True
        try:
            for skill in self._visible_skills():
                if self._locked_skill(skill):
                    self.bag.set_skill_state(
                        skill.setting_key, auto=True, enabled=True
                    )
                    continue
                self.bag.set_skill_state(
                    skill.setting_key, auto=bool(enabled), enabled=bool(enabled)
                )
            self._assign_priorities(self._ui_class, reset_order=True)
        finally:
            self._skill_guard = False
        self._refresh_skills()

    def _reset_visible(self) -> None:
        self._ensure_skill_model()
        self._skill_guard = True
        try:
            for skill in self._visible_skills():
                if self._locked_skill(skill):
                    self.bag.set_skill_state(
                        skill.setting_key, auto=True, enabled=True, hotkey=""
                    )
                    continue
                self.bag.set_skill_state(
                    skill.setting_key,
                    auto=False,
                    enabled=False,
                    priority=1,
                    hotkey="",
                )
            self._assign_priorities(self._ui_class, reset_order=True)
        finally:
            self._skill_guard = False
        self._refresh_skills()

    def apply_to_profile(self) -> None:
        self.bag.apply_to_profile()
        self.on_log(self.t.get("saved", "Saved"))
