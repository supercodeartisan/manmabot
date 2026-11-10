"""Left-pane schedule list: timing, task table, reorder, routine preview."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QButtonGroup,
)

from settings.accounts import AccountStore
from settings.farm_schedule import normalize_routine
from settings.schedule import ScheduleStore, ScheduleTask
from settings.server_list import display_server_name
from session.probes import list_map_choices
from ui_qt.theme import tokens
from ui_qt.widgets.step_spin import StepSpinBox
from ui_qt.widgets.time_field import TimeField

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Classic ``_SCHEDULE_COLUMNS`` widths (stretch=False).
_SCHEDULE_COLUMN_WIDTHS = (64, 110, 136, 100, 72, 80, 72)
# Both languages share this width. Offscreen, with the live theme, the Chinese
# weekday row makes the left column's minimum 350px and Korean stays at 313.
# The sash used to follow that minimum, so Simplified Chinese sat ~36px wider.
_PANE_WIDTH = 350


def _shown_elapsed(clock: dict) -> float:
    """Elapsed seconds already sampled, plus time since that sample while running."""
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


def _format_routine_timer(seconds: float) -> str:
    """Clock text for a routine stay. Hours appear only past 60 minutes."""
    whole = max(0, int(seconds))
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class ScheduleListPane(QWidget):
    """Owns schedule store rows and emits selection / mutation signals."""

    taskSelected = Signal(object)  # ScheduleTask | None
    tasksChanged = Signal()
    newRequested = Signal()
    editRequested = Signal()

    def __init__(
        self,
        *,
        store: ScheduleStore,
        tasks: list[ScheduleTask],
        strings: dict[str, str],
        language: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.tasks = tasks
        self.t = strings
        self.language = language
        self._accounts_by_id: dict[str, object] = {}
        self._map_labels: dict[str, str] = {}
        self._suppress_select = False
        self._repeat_guard = False
        self._editing_id: str | None = None
        self._routine_list_seconds: list[int] = []
        self._routine_entry_ids: list[str] = []
        self._get_live_clock: Callable[[], dict | None] | None = None
        self._build()
        self.refresh_accounts()
        self.refresh(select=0 if tasks else None)
        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start()
        self._align_tries = 0
        QTimer.singleShot(0, self._align_account_to_time)

    def set_live_clock_provider(self, provider: Callable[[], dict | None] | None) -> None:
        self._get_live_clock = provider

    def routine_entry_ids(self) -> list[str]:
        return list(self._routine_entry_ids)

    def preferred_pane_width(self) -> int:
        """Fixed left-pane width. Language text must not move the sash."""
        return _PANE_WIDTH

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._align_tries = 0
        QTimer.singleShot(0, self._align_account_to_time)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._align_tries = 0
        QTimer.singleShot(0, self._align_account_to_time)

    def _align_account_to_time(self) -> None:
        """Keep account combo at least as wide as the start~end time row."""
        row = getattr(self, "_time_window_host", None)
        combo = getattr(self, "account_combo", None)
        if row is None or combo is None:
            return
        for field in (getattr(self, "start_time", None), getattr(self, "end_time", None)):
            if field is not None and hasattr(field, "_fit_spins"):
                try:
                    field._fit_spins()
                except Exception:
                    pass
        # sizeHint tracks the time spins. The laid-out width includes leftover
        # stretch, and using it as a minimum froze the pane wider than the fields.
        width = max(40, int(row.sizeHint().width()))
        if width < 80:
            # Classic retries until the time row has a real layout width.
            self._align_tries = int(getattr(self, "_align_tries", 0)) + 1
            if self._align_tries < 8:
                QTimer.singleShot(50, self._align_account_to_time)
            return
        combo.setMinimumWidth(width)
        combo.setMaximumWidth(16777215)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox(self.t.get("master_schedules", "Schedules"))
        root.addWidget(box)
        col = QVBoxLayout(box)

        timing = QGridLayout()
        col.addLayout(timing)
        timing.addWidget(QLabel(self.t.get("account", "Account")), 0, 0)
        self.account_combo = QComboBox()
        timing.addWidget(self.account_combo, 0, 1)

        self.mode_group = QButtonGroup(self)
        self.mode_window = QRadioButton(self.t.get("time_choice", "Time window"))
        self.mode_duration = QRadioButton(self.t.get("duration_choice", "Duration"))
        self.mode_window.setChecked(True)
        self.mode_group.addButton(self.mode_window)
        self.mode_group.addButton(self.mode_duration)
        timing.addWidget(self.mode_window, 1, 0)
        self._time_window_host = QWidget()
        window = QHBoxLayout(self._time_window_host)
        window.setContentsMargins(0, 0, 0, 0)
        window.setSpacing(6)
        self.start_time = TimeField("00:00:00")
        self.end_time = TimeField("23:59:59")
        window.addWidget(self.start_time)
        tilde = QLabel("~")
        tilde.setAlignment(Qt.AlignmentFlag.AlignCenter)
        window.addWidget(tilde)
        window.addWidget(self.end_time)
        window.addStretch(1)
        timing.addWidget(self._time_window_host, 1, 1)
        timing.addWidget(self.mode_duration, 2, 0)
        duration = QHBoxLayout()
        self.duration_spin = StepSpinBox()
        self.duration_spin.setRange(1, 10080)
        self.duration_spin.setValue(90)
        duration.addWidget(self.duration_spin)
        duration.addWidget(QLabel(self.t.get("minutes", "min")))
        timing.addLayout(duration, 2, 1)

        timing.addWidget(QLabel(self.t.get("current_time", "Now")), 3, 0)
        clock_row = QHBoxLayout()
        self.clock_label = QLabel(datetime.now().strftime("%H:%M:%S"))
        font = self.clock_label.font()
        font.setBold(True)
        self.clock_label.setFont(font)
        clock_row.addWidget(self.clock_label)
        self.randomize = QCheckBox(self.t.get("randomize", "Randomize ± minutes"))
        self.random_minutes = StepSpinBox()
        self.random_minutes.setRange(0, 120)
        self.random_minutes.setValue(int(self.store.randomize_minutes or 0))
        # Three digits plus the stepper. The default hint was wider than this row needs.
        self.random_minutes.setFixedWidth(66)
        self.randomize.setChecked(bool(self.store.randomize_enabled))
        self.randomize.toggled.connect(self._save_randomize)
        self.random_minutes.valueChanged.connect(self._save_randomize)
        clock_row.addWidget(self.randomize)
        clock_row.addWidget(self.random_minutes)
        clock_row.addStretch(1)
        timing.addLayout(clock_row, 3, 1)

        # Classic: Daily on its own row, weekdays on the next.
        daily_row = QHBoxLayout()
        self.repeat_daily = QCheckBox(self.t.get("repeat_daily", "Daily"))
        self.repeat_daily.setChecked(True)
        self.repeat_daily.toggled.connect(self._on_repeat_daily)
        daily_row.addWidget(self.repeat_daily)
        daily_row.addStretch(1)
        col.addLayout(daily_row)
        weekdays = QHBoxLayout()
        self.weekday_checks: list[QCheckBox] = []
        for key in _WEEKDAY_KEYS:
            box_day = QCheckBox(self.t.get(key, key))
            box_day.setChecked(True)
            box_day.toggled.connect(self._on_weekday_toggled)
            self.weekday_checks.append(box_day)
            weekdays.addWidget(box_day)
        weekdays.addStretch(1)
        col.addLayout(weekdays)

        add_btn = QPushButton(self.t.get("add", "Add"))
        add_btn.clicked.connect(self.newRequested.emit)
        col.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                self.t.get("enabled", "On"),
                self.t.get("account", "Account"),
                self.t.get("time_choice", "When"),
                self.t.get("weekdays", "Days"),
                self.t.get("character_order", "Slot"),
                self.t.get("character_type", "Class"),
                self.t.get("server", "Server"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        from ui_qt.editors.form_helpers import configure_select_rows

        configure_select_rows(self.table)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for index, width in enumerate(_SCHEDULE_COLUMN_WIDTHS):
            self.table.setColumnWidth(index, width)
            if index == 0:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellDoubleClicked.connect(lambda *_: self.editRequested.emit())
        self.table.cellClicked.connect(self._on_cell_clicked)
        col.addWidget(self.table, stretch=3)

        toolbar = QHBoxLayout()
        up = QPushButton("▲")
        down = QPushButton("▼")
        up.setFixedWidth(36)
        down.setFixedWidth(36)
        up.clicked.connect(lambda: self.move_selected(-1))
        down.clicked.connect(lambda: self.move_selected(1))
        toolbar.addWidget(up)
        toolbar.addWidget(down)
        edit = QPushButton(self.t.get("edit", "Edit"))
        dup = QPushButton(self.t.get("duplicate", "Duplicate"))
        delete = QPushButton(self.t.get("delete", "Delete"))
        edit.clicked.connect(self.editRequested.emit)
        dup.clicked.connect(self.duplicate_selected)
        delete.clicked.connect(self.delete_selected)
        for btn in (edit, dup, delete):
            btn.setMinimumWidth(max(48, btn.sizeHint().width()))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            toolbar.addWidget(btn, stretch=1)
        col.addLayout(toolbar)

        routine_box = QGroupBox(self.t.get("routine_of_schedule", "Routine"))
        self.routine_box = routine_box
        col.addWidget(routine_box, stretch=2)
        rcol = QVBoxLayout(routine_box)
        self.routine_table = QTableWidget(0, 3)
        self.routine_table.setHorizontalHeaderLabels(
            [
                self.t.get("routine_map_name", "Map"),
                self.t.get("routine_duration", "Min"),
                self.t.get("routine_timer", "Timer"),
            ]
        )
        self.routine_table.verticalHeader().setVisible(False)
        self.routine_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.routine_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.routine_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        rheader = self.routine_table.horizontalHeader()
        rheader.setStretchLastSection(False)
        rheader.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        rheader.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        rheader.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.routine_table.setColumnWidth(1, 72)
        self.routine_table.setColumnWidth(2, 72)
        rcol.addWidget(self.routine_table)
        self.routine_hint = QLabel(self.t.get("routine_list_empty", ""))
        self.routine_hint.setObjectName("muted")
        self.routine_hint.setWordWrap(True)
        rcol.addWidget(self.routine_hint)

        self.mode_window.toggled.connect(self._sync_timing_enabled)
        self._sync_timing_enabled()

    def _sync_timing_enabled(self) -> None:
        window = self.mode_window.isChecked()
        self.start_time.setEnabled(window)
        self.end_time.setEnabled(window)
        self.duration_spin.setEnabled(not window)

    def _tick_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))
        self.paint_routine_timers()

    def _on_repeat_daily(self, checked: bool) -> None:
        if self._repeat_guard:
            return
        self._repeat_guard = True
        try:
            for box in self.weekday_checks:
                box.setChecked(bool(checked))
        finally:
            self._repeat_guard = False

    def _on_weekday_toggled(self, _checked: bool = False) -> None:
        if self._repeat_guard:
            return
        self._align_repeat_daily_checkbox()

    def _align_repeat_daily_checkbox(self) -> None:
        all_on = all(box.isChecked() for box in self.weekday_checks)
        if self.repeat_daily.isChecked() == all_on:
            return
        self._repeat_guard = True
        try:
            self.repeat_daily.setChecked(all_on)
        finally:
            self._repeat_guard = False

    def _save_randomize(self) -> None:
        self.store.randomize_enabled = bool(self.randomize.isChecked())
        self.store.randomize_minutes = int(self.random_minutes.value())
        try:
            self.store.save(self.tasks)
        except Exception:
            pass

    def refresh_accounts(self) -> None:
        try:
            accounts = AccountStore().load()
        except Exception:
            accounts = []
        self._accounts_by_id = {account.account_id: account for account in accounts}
        current = self.account_combo.currentData()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem(self.t.get("value_empty", "—"), None)
        for account in accounts:
            label = account.display_name or account.username
            self.account_combo.addItem(label, account.account_id)
        if current:
            index = self.account_combo.findData(current)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.account_combo.blockSignals(False)
        self._map_labels = {
            map_id: label for map_id, label, _dungeon in list_map_choices(self.language)
        }

    def refresh(
        self,
        select: int | None = None,
        *,
        reload_accounts: bool = True,
        announce: bool = True,
    ) -> None:
        if reload_accounts:
            self.refresh_accounts()
        self._suppress_select = True
        for row in range(self.table.rowCount()):
            host = self.table.cellWidget(row, 0)
            if host is not None:
                self.table.removeCellWidget(row, 0)
                host.setParent(None)
                host.deleteLater()
        self.table.setRowCount(0)
        for index, task in enumerate(self.tasks):
            self.table.insertRow(index)
            enabled = QCheckBox()
            enabled.setText("")
            enabled.setStyleSheet("background: transparent; border: none;")
            enabled.blockSignals(True)
            enabled.setChecked(bool(task.enabled))
            enabled.blockSignals(False)
            enabled.toggled.connect(
                lambda checked, row=index: self._set_enabled_at(row, checked)
            )
            # Transparent host so only the checkbox shows (no gray/white plate).
            wrap = QWidget()
            wrap.setObjectName("cellHost")
            wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            wrap_layout = QHBoxLayout(wrap)
            wrap_layout.setContentsMargins(0, 0, 0, 0)
            wrap_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrap_layout.addWidget(enabled)
            # Do not setItem on col 0 — that replaces the checkbox cell widget.
            self.table.setCellWidget(index, 0, wrap)
            account = self._accounts_by_id.get(task.account_id or "")
            account_label = (
                (account.display_name or account.username)
                if account is not None
                else self.t.get("value_empty", "—")
            )
            account_item = QTableWidgetItem(account_label)
            account_item.setData(Qt.ItemDataRole.UserRole, task.id)
            self.table.setItem(index, 1, account_item)
            if task.time_mode == "duration":
                when = f"{task.duration_minutes} {self.t.get('minutes', 'min')}"
            else:
                when = f"{str(task.start_time)[:5]}~{str(task.end_time)[:5]}"
            self.table.setItem(index, 2, QTableWidgetItem(when))
            days = " ".join(
                self.t.get(_WEEKDAY_KEYS[day], str(day))
                for day in task.weekdays
                if 0 <= day < 7
            )
            self.table.setItem(index, 3, QTableWidgetItem(days))
            self.table.setItem(index, 4, QTableWidgetItem(str(task.character_slot)))
            self.table.setItem(
                index, 5, QTableWidgetItem(self.t.get(task.character, task.character))
            )
            self.table.setItem(
                index,
                6,
                QTableWidgetItem(
                    display_server_name(task.server or "", self.language) or ""
                ),
            )
        from ui_qt.editors.form_helpers import fit_table_columns

        fit_table_columns(self.table, stretch_last=True, min_width=56)
        # Keep the On checkbox column compact.
        self.table.setColumnWidth(0, _SCHEDULE_COLUMN_WIDTHS[0])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        if self.tasks:
            index = select if select is not None and 0 <= select < len(self.tasks) else 0
            if not announce:
                self._suppress_select = True
            else:
                self._suppress_select = False
            self.table.selectRow(index)
            if not announce:
                self._suppress_select = False
                self._paint_routine(self.selected_task())
        else:
            self._suppress_select = False
            if announce:
                self.taskSelected.emit(None)
            self._paint_routine(None)
        self.tasksChanged.emit()

    def selected_index(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return int(rows[0].row())

    def clear_selection(self) -> None:
        """Drop the highlighted row and its routine preview."""
        self._suppress_select = True
        self.table.clearSelection()
        self._suppress_select = False
        self._paint_routine(None)

    def selected_task(self) -> ScheduleTask | None:
        index = self.selected_index()
        if index is None or index < 0 or index >= len(self.tasks):
            return None
        return self.tasks[index]

    def _on_select(self) -> None:
        if self._suppress_select:
            return
        task = self.selected_task()
        self._paint_routine(task)
        self.taskSelected.emit(task)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        # Enabled is a real checkbox cell widget; ignore text-cell toggles.
        _ = (row, column)

    def _set_enabled_at(self, row: int, checked: bool) -> None:
        if row < 0 or row >= len(self.tasks):
            return
        if bool(self.tasks[row].enabled) == bool(checked):
            return
        self.tasks[row].enabled = bool(checked)
        self.persist(select=row)

    def toggle_enabled_at(self, row: int) -> None:
        if row < 0 or row >= len(self.tasks):
            return
        self._set_enabled_at(row, not bool(self.tasks[row].enabled))

    def persist(self, select: int | None = None) -> None:
        self.store.randomize_enabled = bool(self.randomize.isChecked())
        self.store.randomize_minutes = int(self.random_minutes.value())
        self.store.save(self.tasks)
        self.refresh(select=select, reload_accounts=False)

    def move_selected(self, delta: int) -> None:
        index = self.selected_index()
        if index is None:
            return
        target = index + int(delta)
        if target < 0 or target >= len(self.tasks):
            return
        self.tasks[index], self.tasks[target] = self.tasks[target], self.tasks[index]
        self.persist(select=target)

    def duplicate_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        self.tasks.insert(index + 1, self.store.duplicate(self.tasks[index]))
        self.persist(select=index + 1)

    def delete_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        if QMessageBox.question(
            self,
            self.t.get("title", self.t.get("console_title", "ZF")),
            self.t.get("confirm_delete", "Delete?"),
        ) != QMessageBox.StandardButton.Yes:
            return
        del self.tasks[index]
        select = min(index, len(self.tasks) - 1) if self.tasks else None
        self.persist(select=select)

    def read_timing_into(self, task: ScheduleTask) -> None:
        task.account_id = self.account_combo.currentData()
        task.time_mode = "window" if self.mode_window.isChecked() else "duration"
        task.start_time = self.start_time.text() or "00:00:00"
        task.end_time = self.end_time.text() or "23:59:59"
        task.duration_minutes = int(self.duration_spin.value())
        task.repeat_daily = bool(self.repeat_daily.isChecked())
        task.weekdays = [i for i, box in enumerate(self.weekday_checks) if box.isChecked()]
        account = self._accounts_by_id.get(task.account_id or "")
        if account is not None:
            task.server = str(getattr(account, "server", "") or "")
            task.character_slot = int(getattr(account, "character_number", 1) or 1)
            character = str(getattr(account, "character_type", "") or task.character)
            if character in ("elf", "mage", "knight", "royal"):
                task.character = character
            label = account.display_name or account.username
            if label:
                task.name = str(label)[:80]

    def show_timing_from(self, task: ScheduleTask | None) -> None:
        if task is None:
            return
        index = self.account_combo.findData(task.account_id)
        self.account_combo.setCurrentIndex(max(0, index))
        if task.time_mode == "duration":
            self.mode_duration.setChecked(True)
        else:
            self.mode_window.setChecked(True)
        self.start_time.setText(str(task.start_time or "00:00:00"))
        self.end_time.setText(str(task.end_time or "23:59:59"))
        self.duration_spin.setValue(int(task.duration_minutes or 90))
        self._repeat_guard = True
        try:
            for day, box in enumerate(self.weekday_checks):
                box.setChecked(day in (task.weekdays or []))
            self.repeat_daily.setChecked(bool(task.repeat_daily))
            self._align_repeat_daily_checkbox()
        finally:
            self._repeat_guard = False
        self._sync_timing_enabled()

    def _paint_routine(self, task: ScheduleTask | None) -> None:
        self.routine_table.setRowCount(0)
        self._routine_list_seconds = []
        self._routine_entry_ids = []
        if task is None:
            self.routine_hint.setText(self.t.get("routine_list_empty", ""))
            return
        routine = normalize_routine((task.settings.get("move") or {}).get("routine"))
        if not routine:
            self.routine_hint.setText(self.t.get("routine_list_empty", ""))
            return
        self.routine_hint.setText("")
        used_ids: set[str] = set()
        for row_index, entry in enumerate(routine):
            row = self.routine_table.rowCount()
            self.routine_table.insertRow(row)
            map_id = str(entry.get("map_id") or "")
            minutes = int(entry.get("duration_minutes") or 60)
            seconds = minutes * 60
            entry_id = str(entry.get("id") or "").strip() or f"routine-{row_index}"
            if entry_id in used_ids:
                entry_id = f"routine-{row_index}"
            used_ids.add(entry_id)
            self._routine_list_seconds.append(seconds)
            self._routine_entry_ids.append(entry_id)
            self.routine_table.setItem(
                row, 0, QTableWidgetItem(self._map_labels.get(map_id, map_id))
            )
            self.routine_table.setItem(
                row, 1, QTableWidgetItem(f"{minutes} {self.t.get('minutes', 'min')}")
            )
            self.routine_table.setItem(
                row, 2, QTableWidgetItem(_format_routine_timer(seconds))
            )
        self.paint_routine_timers()

    def paint_routine_timers(self) -> None:
        """Refresh the timer column. The running map counts down; the rest stay full."""
        rows = self.routine_table.rowCount()
        if rows <= 0:
            return
        planned = list(self._routine_list_seconds)
        children = list(self._routine_entry_ids)
        if len(children) != rows:
            return
        clock = self._get_live_clock() if self._get_live_clock is not None else None
        active_iid = ""
        navigating = False
        remaining: int | None = None
        if clock is not None:
            ids = [str(item) for item in clock.get("ids") or []]
            durations = [int(item) for item in clock.get("durations_s") or []]
            try:
                slot = int(clock.get("index"))
            except (TypeError, ValueError):
                slot = -1
            if ids == children and 0 <= slot < len(children):
                active_iid = children[slot]
                slot_s = durations[slot] if slot < len(durations) else 0
            elif len(ids) == len(children) and 0 <= slot < len(children):
                active_iid = children[slot]
                slot_s = (
                    durations[slot]
                    if slot < len(durations)
                    else (planned[slot] if slot < len(planned) else 0)
                )
            else:
                slot_s = 0
            if active_iid:
                navigating = bool(clock.get("navigating"))
                kind = str(clock.get("kind") or "").strip().lower()
                # Break rest always counts down (never stuck on Moving).
                if kind == "break":
                    navigating = False
                if not navigating:
                    remaining = int(slot_s - _shown_elapsed(clock))
        live_brush = QBrush(QColor(tokens.ACCENT))
        normal_brush = QBrush(QColor(tokens.TEXT))
        for row, iid in enumerate(children):
            if iid == active_iid and navigating:
                text = self.t.get("routine_timer_moving", "Moving")
            elif iid == active_iid and remaining is not None:
                text = _format_routine_timer(remaining)
            else:
                seconds = planned[row] if row < len(planned) else 0
                text = _format_routine_timer(seconds)
            item = self.routine_table.item(row, 2)
            if item is None:
                item = QTableWidgetItem(text)
                self.routine_table.setItem(row, 2, item)
            elif item.text() != text:
                item.setText(text)
            # Classic ``live`` tag: accent foreground on the active routine row.
            brush = live_brush if iid == active_iid else normal_brush
            for col in range(self.routine_table.columnCount()):
                cell = self.routine_table.item(row, col)
                if cell is not None:
                    cell.setForeground(brush)
