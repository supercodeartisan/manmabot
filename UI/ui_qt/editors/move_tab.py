"""Move tab — routine table (battle/break maps)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from i18n.localized_names import route_point_display_name
from session.probes import list_farm_details, list_patrol_entries, list_safe_details
from settings.farm_schedule import (
    DEFAULT_FARM_STAY_S,
    MAX_FARM_STAY_MIN,
    MIN_FARM_STAY_MIN,
    stay_minutes_from_s,
    stay_s_from_minutes,
    stay_seconds_for,
)
from settings.profile import Profile, save_profile
from ui_qt.editors.form_helpers import cell_button, table_row_height_for_controls, wrap_cell_widget
from ui_qt.widgets.step_spin import StepSpinBox
from ui_qt.viewmodels.routine_vm import RoutineViewModel


class MoveTab(QWidget):
    def __init__(
        self,
        *,
        profile: Profile,
        strings: dict[str, str],
        language: str,
        on_log: Callable[[str], None] | None = None,
        on_open_map_editor: Callable[..., None] | None = None,
        on_routine_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.t = strings
        self.on_log = on_log or (lambda _m: None)
        self.on_open_map_editor = on_open_map_editor
        self.on_routine_changed = on_routine_changed
        self.vm = RoutineViewModel(language)
        self.vm.load_from_profile(profile)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        actions = QHBoxLayout()
        hint = QLabel(self.t.get("routine_hint", ""))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        actions.addWidget(hint, stretch=1)
        add_battle = QPushButton(self.t.get("routine_battle_add", "Add battle"))
        add_break = QPushButton(self.t.get("routine_break_add", "Add break"))
        add_battle.clicked.connect(lambda: self._add_row("battle"))
        add_break.clicked.connect(lambda: self._add_row("break"))
        actions.addWidget(add_break)
        actions.addWidget(add_battle)
        root.addLayout(actions)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                self.t.get("number", "#"),
                self.t.get("routine_map_name", "Map"),
                self.t.get("routine_type", "Type"),
                self.t.get("routine_duration", "Min"),
                self.t.get("routine_setting", "Setting"),
                self.t.get("delete", "Delete"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(table_row_height_for_controls())
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(3, 88)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 88)
        self.table.itemSelectionChanged.connect(self._on_select)
        root.addWidget(self.table, stretch=1)

        order = QHBoxLayout()
        up = QPushButton(self.t.get("up", "Up"))
        down = QPushButton(self.t.get("down", "Down"))
        for btn in (up, down):
            btn.setMinimumWidth(72)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        order.addWidget(up, stretch=1)
        order.addWidget(down, stretch=1)
        root.addLayout(order)

        summary_title = QLabel(self.t.get("selection_info", "Summary"))
        root.addWidget(summary_title)
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(72)
        root.addWidget(self.summary, stretch=0)

    def refresh(self) -> None:
        self.vm.invalidate_selection()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for index, entry in enumerate(self.vm.rows, start=1):
            row = index - 1
            self.table.insertRow(row)
            entry_id = str(entry["id"])
            map_id = str(entry.get("map_id") or "")
            dungeon = self.vm.is_dungeon(map_id)
            if entry.get("kind") == "break":
                kind_key = (
                    "routine_type_break_dungeon" if dungeon else "routine_type_break_general"
                )
            else:
                kind_key = (
                    "routine_type_battle_dungeon" if dungeon else "routine_type_battle_general"
                )
            ready = self.vm.setting_ready(entry)
            if dungeon:
                setting_key = "routine_patrol_set" if ready else "routine_patrol_needed"
            else:
                setting_key = "routine_area_set" if ready else "routine_area_needed"

            self.table.setItem(row, 0, QTableWidgetItem(str(index)))
            self.table.setItem(row, 1, QTableWidgetItem(self.vm.map_label(map_id)))
            self.table.setItem(row, 2, QTableWidgetItem(self.t.get(kind_key, kind_key)))

            spin = StepSpinBox(compact=True)
            spin.setRange(1, 10080)
            spin.setValue(int(entry.get("duration_minutes") or 60))
            spin.valueChanged.connect(
                lambda value, eid=entry_id: self._duration_changed(eid, value)
            )
            self.table.setCellWidget(row, 3, wrap_cell_widget(spin, hpad=3, vpad=2))

            setting_btn = cell_button(self.t.get(setting_key, setting_key))
            setting_btn.clicked.connect(lambda _=False, eid=entry_id: self._edit_setting(eid))
            self.table.setCellWidget(row, 4, wrap_cell_widget(setting_btn, hpad=3, vpad=2))

            delete_btn = cell_button(self.t.get("delete", "Delete"))
            delete_btn.clicked.connect(lambda _=False, eid=entry_id: self._delete(eid))
            self.table.setCellWidget(row, 5, wrap_cell_widget(delete_btn, hpad=3, vpad=2))
            self.table.setRowHeight(row, table_row_height_for_controls())

            for col in range(3):
                item = self.table.item(row, col)
                if item is not None:
                    item.setData(Qt.ItemDataRole.UserRole, entry_id)

            if entry_id == self.vm.selected_id:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        # Keep Setting/Delete columns readable; only shrink text columns.
        self.table.resizeColumnToContents(2)
        self.table.setColumnWidth(4, max(150, self.table.columnWidth(4)))
        self.table.setColumnWidth(5, max(88, self.table.columnWidth(5)))
        self.summary.setPlainText("\n".join(self.vm.summary_lines(self.t)))
        if callable(self.on_routine_changed):
            try:
                self.on_routine_changed()
            except Exception:
                pass

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return
        self.vm.selected_id = str(item.data(Qt.ItemDataRole.UserRole) or "") or None

    def _duration_changed(self, entry_id: str, value: int) -> None:
        self.vm.set_duration(entry_id, value)
        self.summary.setPlainText("\n".join(self.vm.summary_lines(self.t)))

    def _add_row(self, kind: str) -> None:
        self.vm.reload_catalog()
        choices = self.vm.map_choices(kind=kind)
        if not choices:
            key = "routine_break_general_only" if kind == "break" else "probe_map_missing"
            QMessageBox.information(self, self.t.get("title", "Manmabot"), self.t.get(key, key))
            return
        map_id = self._pick_map(kind, choices)
        if not map_id:
            return
        self.vm.add_row(kind, map_id)
        self.refresh()
        if self.vm.is_break_only():
            QMessageBox.warning(
                self,
                self.t.get("title", "Manmabot"),
                self.t.get("routine_break_only_warn", "Break-only routine."),
            )

    def _pick_map(self, kind: str, choices: list[tuple[str, str, bool]]) -> str:
        dialog = QDialog(self)
        title = (
            self.t.get("routine_battle_add", "Add battle")
            if kind == "battle"
            else self.t.get("routine_break_add", "Add break")
        )
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(self.t.get("routine_pick_map", "Pick map")))
        combo = QComboBox()
        id_by_index: list[str] = []
        for map_id, label, dungeon in choices:
            suffix = self.t.get("routine_patrol", "patrol") if dungeon else self.t.get(
                "routine_area", "area"
            )
            combo.addItem(f"{label}  ·  {suffix}")
            id_by_index.append(map_id)
        layout.addWidget(combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return ""
        index = combo.currentIndex()
        if index < 0 or index >= len(id_by_index):
            return ""
        return id_by_index[index]

    def _delete(self, entry_id: str) -> None:
        self.vm.selected_id = entry_id
        self.vm.delete_selected()
        self.refresh()

    def _move(self, delta: int) -> None:
        self.vm.move_selected(delta)
        self.refresh()

    def _edit_setting(self, entry_id: str) -> None:
        entry = next((row for row in self.vm.rows if row["id"] == entry_id), None)
        if entry is None:
            return
        existing = getattr(self, "_setting_dialog", None)
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                self._setting_dialog = None
        map_id = str(entry.get("map_id") or "")
        dungeon = self.vm.is_dungeon(map_id)
        rest = str(entry.get("kind") or "") == "break" and not dungeon
        area_kind = "safe" if rest else "farm"
        # Non-modal like classic Toplevel — nested QDialog.exec() crashes map edit.
        dialog = QDialog(self.window())
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        title = self.t.get("routine_setting_title", self.t.get("routine_setting", "Setting"))
        try:
            dialog.setWindowTitle(title.format(name=self.vm.map_label(map_id)))
        except Exception:
            dialog.setWindowTitle(self.t.get("routine_setting", "Setting"))
        dialog.resize(760, 520)
        dialog.setMinimumSize(640, 420)
        self._setting_dialog = dialog
        layout = QVBoxLayout(dialog)
        farm_table: QTableWidget | None = None
        patrol_table: QTableWidget | None = None
        stay_by_name: dict[str, float] = {}
        refill_list = None
        select_all_farms = None
        clear_all_farms = None
        if dungeon:
            layout.addWidget(
                QLabel(
                    self.t.get(
                        "map_setup_hint_dungeon",
                        "Dungeon mode uses patrol points. Place them on walkable tiles in the editor.",
                    )
                )
            )
            patrol_status = QLabel("")
            layout.addWidget(patrol_status)
            patrol_table = QTableWidget(0, 2)
            patrol_table.setHorizontalHeaderLabels(
                [
                    "#",
                    self.t.get("patrol_name", self.t.get("name", "Name")),
                ]
            )
            patrol_table.verticalHeader().setVisible(False)
            patrol_table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            patrol_table.setSelectionMode(
                QAbstractItemView.SelectionMode.SingleSelection
            )
            patrol_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            patrol_table.setColumnWidth(0, 48)
            patrol_table.setColumnWidth(1, 180)
            patrol_table.horizontalHeader().setStretchLastSection(True)

            def _fill_patrol() -> None:
                assert patrol_table is not None
                entries = list_patrol_entries(map_id)
                patrol_table.setRowCount(0)
                for index, (_x, _y, name) in enumerate(entries, start=1):
                    row = patrol_table.rowCount()
                    patrol_table.insertRow(row)
                    num = QTableWidgetItem(str(index))
                    num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    patrol_table.setItem(row, 0, num)
                    patrol_table.setItem(
                        row,
                        1,
                        QTableWidgetItem(
                            route_point_display_name(name, self.vm.language)
                        ),
                    )
                patrol_status.setText(
                    self.t.get(
                        "map_registered_patrol_line",
                        self.t.get("routine_patrol_line", "patrol: {n}"),
                    ).format(n=len(entries))
                )

            _fill_patrol()
            refill_list = _fill_patrol
            layout.addWidget(patrol_table, stretch=1)
        elif rest:
            layout.addWidget(
                QLabel(
                    self.t.get(
                        "map_setup_hint_rest",
                        "Rest areas are separate from combat farms. Draw them in the rest editor.",
                    )
                )
            )
            rest_status = QLabel("")
            layout.addWidget(rest_status)
            rest_table = QTableWidget(0, 2)
            rest_table.setHorizontalHeaderLabels(
                ["#", self.t.get("name", "Name")]
            )
            rest_table.verticalHeader().setVisible(False)
            rest_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            rest_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            rest_table.setColumnWidth(0, 48)
            rest_table.horizontalHeader().setStretchLastSection(True)

            def _fill_rest() -> None:
                rows, _err = list_safe_details(map_id)
                rest_table.setRowCount(0)
                for index, (name, _memo) in enumerate(rows, start=1):
                    row = rest_table.rowCount()
                    rest_table.insertRow(row)
                    num = QTableWidgetItem(str(index))
                    num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    rest_table.setItem(row, 0, num)
                    rest_table.setItem(
                        row,
                        1,
                        QTableWidgetItem(route_point_display_name(name, self.vm.language)),
                    )
                rest_status.setText(
                    self.t.get("map_registered_rest_line", "rest areas: {n}").format(
                        n=len(rows)
                    )
                )

            _fill_rest()
            refill_list = _fill_rest
            layout.addWidget(rest_table, stretch=1)
        else:
            details, _err = list_farm_details(map_id)
            layout.addWidget(
                QLabel(self.t.get("map_setup_hint", self.t.get("routine_area", "Areas")))
            )
            if not details:
                layout.addWidget(
                    QLabel(
                        self.t.get(
                            "routine_area_needed",
                            "No farm areas yet. Open the map editor to draw them.",
                        )
                    )
                )
            selected = {str(name) for name in (entry.get("selected_farms") or [])}
            stay_by_name = {
                str(k): float(v)
                for k, v in dict(entry.get("farm_stays_s") or {}).items()
            }
            yaml_names = [name for name, _memo in details]
            farm_table = QTableWidget(0, 3)
            farm_table.setHorizontalHeaderLabels(
                [
                    self.t.get("farms", "Farm"),
                    self.t.get("number", "#"),
                    self.t.get("farm_stay", "Stay"),
                ]
            )
            farm_table.verticalHeader().setVisible(False)
            farm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            farm_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            farm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            farm_table.setColumnWidth(0, 180)
            farm_table.setColumnWidth(1, 48)
            farm_table.setColumnWidth(2, 72)

            def _checked_names() -> list[str]:
                assert farm_table is not None
                names: list[str] = []
                for row in range(farm_table.rowCount()):
                    box = farm_table.cellWidget(row, 0)
                    if isinstance(box, QCheckBox) and box.isChecked():
                        names.append(str(box.property("farm_name") or ""))
                return [name for name in names if name]

            def _refresh_order_column() -> None:
                assert farm_table is not None
                checked = _checked_names()
                rank = {name: index for index, name in enumerate(checked, start=1)}
                for row in range(farm_table.rowCount()):
                    box = farm_table.cellWidget(row, 0)
                    name = str(box.property("farm_name") or "") if isinstance(box, QCheckBox) else ""
                    order_item = farm_table.item(row, 1)
                    if order_item is None:
                        order_item = QTableWidgetItem("")
                        farm_table.setItem(row, 1, order_item)
                    order_item.setText(str(rank[name]) if name in rank else "")
                    stay_item = farm_table.item(row, 2)
                    if stay_item is None:
                        stay_item = QTableWidgetItem("")
                        farm_table.setItem(row, 2, stay_item)
                    minutes = stay_minutes_from_s(
                        stay_seconds_for(name, stay_by_name, DEFAULT_FARM_STAY_S)
                    )
                    stay_item.setText(
                        f"{minutes}{self.t.get('minutes', 'min')}" if name in rank else ""
                    )

            def _fill_rows(names: list[str], checked: set[str]) -> None:
                assert farm_table is not None
                farm_table.setRowCount(0)
                for name in names:
                    row = farm_table.rowCount()
                    farm_table.insertRow(row)
                    box = QCheckBox(route_point_display_name(name, self.vm.language))
                    box.setProperty("farm_name", name)
                    box.setChecked(name in checked)
                    box.toggled.connect(lambda _=False: _refresh_order_column())
                    farm_table.setCellWidget(row, 0, box)
                    farm_table.setItem(row, 1, QTableWidgetItem(""))
                    farm_table.setItem(row, 2, QTableWidgetItem(""))
                _refresh_order_column()

            def _select_all() -> None:
                assert farm_table is not None
                for row in range(farm_table.rowCount()):
                    box = farm_table.cellWidget(row, 0)
                    if isinstance(box, QCheckBox):
                        box.setChecked(True)

            def _clear_all() -> None:
                assert farm_table is not None
                for row in range(farm_table.rowCount()):
                    box = farm_table.cellWidget(row, 0)
                    if isinstance(box, QCheckBox):
                        box.setChecked(False)

            def _edit_stay(row: int, _column: int) -> None:
                assert farm_table is not None
                if _column != 2:
                    return
                box = farm_table.cellWidget(row, 0)
                if not isinstance(box, QCheckBox):
                    return
                name = str(box.property("farm_name") or "")
                if not name:
                    return
                initial = stay_minutes_from_s(
                    stay_seconds_for(name, stay_by_name, DEFAULT_FARM_STAY_S)
                )
                value, ok = QInputDialog.getInt(
                    dialog,
                    self.t.get("farm_stay", "Stay"),
                    self.t.get("farm_stay_prompt", "Minutes"),
                    initial,
                    MIN_FARM_STAY_MIN,
                    MAX_FARM_STAY_MIN,
                )
                if not ok:
                    return
                stay_by_name[name] = stay_s_from_minutes(value)
                box.setChecked(True)
                _refresh_order_column()

            def _reload_from_yaml() -> None:
                assert farm_table is not None
                details_now, _err = list_farm_details(map_id)
                names = [name for name, _memo in details_now]
                checked = {name for name in _checked_names() if name in names}
                _fill_rows(names, checked)

            refill_list = _reload_from_yaml
            select_all_farms = _select_all
            clear_all_farms = _clear_all
            _fill_rows(yaml_names, selected)
            layout.addWidget(farm_table, stretch=1)
            farm_table.cellDoubleClicked.connect(_edit_stay)

        toolbar = QHBoxLayout()
        edit_map = QPushButton(
            self.t.get("edit_patrol", "Edit patrol")
            if dungeon
            else self.t.get("edit_rest", "Edit rest areas")
            if rest
            else self.t.get("edit", "Edit map")
        )

        def _open_editor() -> None:
            if self.on_open_map_editor is None:
                QMessageBox.information(
                    dialog,
                    self.t.get("routine_setting", "Setting"),
                    self.t.get("map_editor", "Map editor"),
                )
                return

            def _back() -> None:
                if refill_list is not None:
                    try:
                        refill_list()
                    except Exception:
                        pass
                try:
                    if dialog.isVisible():
                        dialog.raise_()
                        dialog.activateWindow()
                except RuntimeError:
                    pass

            # Parent to shell (not this dialog) — classic non-modal stack.
            self.on_open_map_editor(
                map_id, dungeon=dungeon, area_kind=area_kind, on_closed=_back
            )

        edit_map.clicked.connect(_open_editor)
        toolbar.addWidget(edit_map)
        if farm_table is not None:
            select_all = QPushButton(self.t.get("select_all", "Select all"))
            deselect = QPushButton(self.t.get("deselect_all", "Deselect all"))
            if select_all_farms is not None:
                select_all.clicked.connect(select_all_farms)
            if clear_all_farms is not None:
                deselect.clicked.connect(clear_all_farms)
            for btn in (select_all, deselect):
                toolbar.addWidget(btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(self.t.get("ok", "OK"))

        committed = {"done": False}

        def _commit() -> None:
            if committed["done"]:
                return
            committed["done"] = True
            if farm_table is not None:
                chosen: list[str] = []
                for row in range(farm_table.rowCount()):
                    box = farm_table.cellWidget(row, 0)
                    if isinstance(box, QCheckBox) and box.isChecked():
                        name = str(box.property("farm_name") or "")
                        if name:
                            chosen.append(name)
                self.vm.set_farms(entry_id, chosen, stay_by_name)

        def _commit_and_close() -> None:
            _commit()
            dialog.close()

        def _on_finished(_code: int = 0) -> None:
            _commit()  # classic closes with save
            if getattr(self, "_setting_dialog", None) is dialog:
                self._setting_dialog = None
            self.refresh()

        buttons.accepted.connect(_commit_and_close)
        dialog.finished.connect(_on_finished)
        layout.addWidget(buttons)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def apply_to_profile(self) -> None:
        self.vm.apply_to_profile(self.profile)
        save_profile(self.profile)
        self.on_log(self.t.get("saved", "Saved"))
        self.refresh()

    def reload_from_profile(self) -> None:
        self.vm.load_from_profile(self.profile)
        self.refresh()

    def load_from_move_settings(
        self, move: dict | None, *, inherit_profile: bool = True
    ) -> None:
        self.vm.load_from_move_settings(
            move, self.profile, inherit_profile=inherit_profile
        )
        self.refresh()

    def routine_payload(self) -> list:
        return self.vm.payload()
