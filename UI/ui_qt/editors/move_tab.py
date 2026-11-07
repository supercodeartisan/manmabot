"""Move tab — routine table (battle/break maps)."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
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
from ui_qt.theme import tokens
from ui_qt.widgets.step_spin import StepSpinBox
from ui_qt.viewmodels.routine_vm import RoutineViewModel


def _shown_elapsed(clock: dict) -> float:
    """Elapsed seconds already sampled, plus time since that sample while inside."""
    try:
        elapsed = float(clock.get("elapsed_s") or 0.0)
    except (TypeError, ValueError):
        elapsed = 0.0
    if not clock.get("ticking"):
        return elapsed
    try:
        as_of = float(clock.get("as_of") or 0.0)
    except (TypeError, ValueError):
        as_of = 0.0
    if as_of <= 0.0:
        return elapsed
    return elapsed + max(0.0, time.monotonic() - as_of)


def _format_area_timer(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _release_cell_widgets(table: QTableWidget) -> None:
    """Drop cell hosts before the row is removed so they do not stay in the tree."""
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            host = table.cellWidget(row, column)
            if host is None:
                continue
            table.removeCellWidget(row, column)
            host.setParent(None)
            host.deleteLater()


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
        load_profile: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self.on_open_map_editor = on_open_map_editor
        self.on_routine_changed = on_routine_changed
        self.on_content_changed = None
        self.vm = self._make_vm()
        if load_profile:
            self.vm.load_from_profile(profile)
        self._farm_clock_provider: Callable[[], dict | None] | None = None
        self._farm_timer_table: QTableWidget | None = None
        self._build()
        self.refresh()

    def _make_vm(self) -> RoutineViewModel:
        return RoutineViewModel(self.language)

    def _persist_routine(self) -> None:
        """Solo rows are read from this widget at save time."""
        return

    def _snapshot_setting(self, entry_id: str) -> None:
        """Solo keeps coordinates in the shared map files."""
        return

    def _patrol_entries_for(self, map_id: str, entry: dict) -> list:
        return list_patrol_entries(map_id)

    def _farm_choice_label(self, name: str, note: str, index: int) -> str:
        return route_point_display_name(name, self.language)

    def _area_details_for(self, map_id: str, *, rest: bool, entry: dict):
        list_details = list_safe_details if rest else list_farm_details
        return list_details(map_id)

    def _launch_map_editor(
        self,
        map_id: str,
        *,
        dungeon: bool,
        area_kind: str,
        on_closed,
        entry_id: str,
        host: QWidget,
    ) -> None:
        if self.on_open_map_editor is None:
            QMessageBox.information(
                host,
                self.t.get("routine_setting", "Setting"),
                self.t.get("map_editor", "Map editor"),
            )
            return
        self.on_open_map_editor(
            map_id, dungeon=dungeon, area_kind=area_kind, on_closed=on_closed
        )

    def set_farm_clock_provider(self, provider: Callable[[], dict | None] | None) -> None:
        self._farm_clock_provider = provider

    def paint_farm_timers(self) -> None:
        """Countdown on the open area list. The active area counts down; the rest stay full."""
        table = self._farm_timer_table
        if table is None:
            return
        try:
            rows = table.rowCount()
        except RuntimeError:
            self._farm_timer_table = None
            return
        if rows <= 0:
            return
        clock = self._farm_clock_provider() if self._farm_clock_provider is not None else None
        names = [str(item) for item in (clock or {}).get("names") or []]
        limits = [float(item) for item in (clock or {}).get("limits_s") or []]
        try:
            index = int((clock or {}).get("index") or 0)
        except (TypeError, ValueError):
            index = -1
        active = names[index] if clock and 0 <= index < len(names) else ""
        navigating = bool((clock or {}).get("navigating"))
        elapsed = _shown_elapsed(clock) if clock else 0.0
        limit_by_name = {
            name: limits[i] for i, name in enumerate(names) if i < len(limits)
        }
        live = QBrush(QColor(tokens.ACCENT))
        plain = QBrush(QColor(tokens.TEXT))
        moving = self.t.get("routine_timer_moving", "Moving")
        for row in range(rows):
            box = table.cellWidget(row, 0)
            name = str(box.property("farm_name") or "") if isinstance(box, QCheckBox) else ""
            checked = isinstance(box, QCheckBox) and box.isChecked()
            stay_item = table.item(row, 2)
            configured = stay_item.text() if stay_item is not None else ""
            if not checked or not name:
                text = ""
            elif clock and name == active and navigating:
                text = moving
            elif clock and name == active and name in limit_by_name:
                text = _format_area_timer(limit_by_name[name] - elapsed)
            elif clock and name in limit_by_name:
                text = _format_area_timer(limit_by_name[name])
            else:
                text = configured
            item = table.item(row, 3)
            if item is None:
                item = QTableWidgetItem(text)
                table.setItem(row, 3, item)
            elif item.text() != text:
                item.setText(text)
            item.setForeground(live if clock and name == active else plain)

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

    def refresh(self, *, notify: bool = True) -> None:
        self.vm.invalidate_selection()
        self.table.blockSignals(True)
        _release_cell_widgets(self.table)
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
        if notify and callable(self.on_routine_changed):
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
        self._persist_routine()
        if callable(self.on_content_changed):
            try:
                self.on_content_changed()
            except Exception:
                pass

    def _add_row(self, kind: str) -> None:
        self.vm.reload_catalog()
        choices = self.vm.map_choices(kind=kind)
        if not choices:
            key = "routine_break_general_only" if kind == "break" else "probe_map_missing"
            QMessageBox.information(self, self.t.get("title", self.t.get("console_title", "ZF")), self.t.get(key, key))
            return
        map_id = self._pick_map(kind, choices)
        if not map_id:
            return
        self.vm.add_row(kind, map_id)
        self.refresh()
        if self.vm.is_break_only():
            QMessageBox.warning(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
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
                entries = self._patrol_entries_for(map_id, entry)
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
        else:
            details, _err = self._area_details_for(map_id, rest=rest, entry=entry)
            if rest:
                hint = self.t.get(
                    "map_setup_hint_rest",
                    "Check the rest areas to use and set stay minutes. "
                    "These are separate from combat farms.",
                )
            else:
                hint = self.t.get("map_setup_hint", self.t.get("routine_area", "Areas"))
            layout.addWidget(QLabel(hint))
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
            farm_table = QTableWidget(0, 4)
            farm_table.setHorizontalHeaderLabels(
                [
                    self.t.get("rest_areas", "Rest areas")
                    if rest
                    else self.t.get("farms", "Farm"),
                    self.t.get("number", "#"),
                    self.t.get("farm_stay", "Stay"),
                    self.t.get("routine_timer", "Timer"),
                ]
            )
            farm_table.verticalHeader().setVisible(False)
            farm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            farm_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            farm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            farm_table.setColumnWidth(0, 300)
            farm_table.setColumnWidth(1, 48)
            farm_table.setColumnWidth(2, 72)
            farm_table.setColumnWidth(3, 88)
            self._farm_timer_table = farm_table

            def _drop_farm_timer_table() -> None:
                if self._farm_timer_table is farm_table:
                    self._farm_timer_table = None

            dialog.destroyed.connect(lambda *_: _drop_farm_timer_table())

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

            def _fill_rows(rows: list[tuple[str, str]], checked: set[str]) -> None:
                assert farm_table is not None
                farm_table.setRowCount(0)
                for name, note in rows:
                    row = farm_table.rowCount()
                    farm_table.insertRow(row)
                    box = QCheckBox(self._farm_choice_label(name, note, row + 1))
                    box.setProperty("farm_name", name)
                    box.setChecked(name in checked)
                    box.toggled.connect(lambda _=False: _refresh_order_column())
                    farm_table.setCellWidget(row, 0, box)
                    farm_table.setItem(row, 1, QTableWidgetItem(""))
                    farm_table.setItem(row, 2, QTableWidgetItem(""))
                    farm_table.setItem(row, 3, QTableWidgetItem(""))
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
                stay_prompt = (
                    self.t.get("rest_stay_prompt", "Minutes")
                    if rest
                    else self.t.get("farm_stay_prompt", "Minutes")
                )
                value, ok = QInputDialog.getInt(
                    dialog,
                    self.t.get("farm_stay", "Stay"),
                    stay_prompt,
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
                details_now, _err = self._area_details_for(
                    map_id, rest=rest, entry=entry
                )
                names = [name for name, _memo in details_now]
                checked = {name for name in _checked_names() if name in names}
                _fill_rows(details_now, checked)

            refill_list = _reload_from_yaml
            select_all_farms = _select_all
            clear_all_farms = _clear_all
            _fill_rows(details, selected)
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
            self._launch_map_editor(
                map_id,
                dungeon=dungeon,
                area_kind=area_kind,
                on_closed=_back,
                entry_id=entry_id,
                host=dialog,
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
            self._snapshot_setting(entry_id)

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
