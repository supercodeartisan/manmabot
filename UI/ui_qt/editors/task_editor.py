"""Task editor notebook — load/collect ScheduleTask + ported tabs."""

from __future__ import annotations

import copy
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from settings.accounts import AccountStore
from settings.farm_schedule import normalize_routine
from settings.profile import Profile
from settings.schedule import ScheduleTask
from ui_qt.editors.equipment_tab import EquipmentTab
from ui_qt.shell.live_income_bar import LiveIncomeBar
from ui_qt.editors.hunt_tab import HuntTab
from ui_qt.editors.magic_tab import MagicTab
from ui_qt.editors.move_tab import MoveTab
from ui_qt.editors.other_tab import OtherTab
from ui_qt.editors.recovery_tab import RecoveryTab
from ui_qt.facade.qt_bridge import QtBridge
from ui_qt.theme import tokens
from ui_qt.theme.apply import mark_accent
from ui_qt.viewmodels.settings_bag import SettingsBag


class TaskEditor(QWidget):
    """Editor chrome matches classic: identity row + tabs + bottom Add/Update."""

    accountChanged = Signal(object)  # account_id | None

    def __init__(
        self,
        *,
        profile: Profile,
        bridge: QtBridge,
        strings: dict[str, str],
        language: str,
        on_log: Callable[[str], None] | None = None,
        on_commit: Callable[[], None] | None = None,
        on_update: Callable[[], None] | None = None,
        on_add: Callable[[], None] | None = None,
        on_apply: Callable[[], None] | None = None,
        on_open_map_editor: Callable[..., None] | None = None,
        on_run_setup: Callable[[], None] | None = None,
        on_start_driver: Callable[[], None] | None = None,
        on_profile_reloaded: Callable[[], None] | None = None,
        get_log_lines: Callable[[], list[str]] | None = None,
        clear_shell_logs: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.bridge = bridge
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self.on_commit = on_commit or (lambda: None)
        self.on_update = on_update or self.on_commit
        self.on_add = on_add or self.on_commit
        self.on_apply = on_apply or (lambda: None)
        self._editing = False
        self.on_open_map_editor = on_open_map_editor
        self.on_run_setup = on_run_setup
        self.on_start_driver = on_start_driver
        self.on_profile_reloaded = on_profile_reloaded
        self.get_log_lines = get_log_lines
        self.clear_shell_logs = clear_shell_logs
        self.bag = SettingsBag(profile)
        self.task: ScheduleTask | None = None
        self._accounts_by_id: dict[str, object] = {}
        self._suppress_account = False
        self.move_tab: MoveTab | None = None
        self.hunt_tab: HuntTab | None = None
        self.recovery_tab: RecoveryTab | None = None
        self.magic_tab: MagicTab | None = None
        self.equipment_tab: EquipmentTab | None = None
        self.other_tab: OtherTab | None = None
        self._build()

    def _project_running(self) -> bool:
        try:
            from session.bot_controller import RunState

            return self.bridge.controller.state == RunState.RUNNING
        except Exception:
            return False

    def _purchase_open(self) -> bool:
        try:
            return bool(self.bridge.controller.purchase_in_progress())
        except Exception:
            return False

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.income_bar = LiveIncomeBar(
            self,
            language=self.language,
            running=self._project_running,
            buying=self._purchase_open,
        )
        layout.addWidget(self.income_bar)

        self.identity_box = QGroupBox(self.t.get("task_details", "Task"))
        id_row = QHBoxLayout(self.identity_box)
        id_row.setContentsMargins(8, 6, 8, 6)
        id_row.setSpacing(8)
        id_row.addWidget(QLabel(self.t.get("account", "Account")))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(160)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        id_row.addWidget(self.account_combo)
        id_row.addSpacing(16)
        self.server_value = self._fact(id_row, self.t.get("server", "Server"))
        id_row.addSpacing(16)
        self.order_value = self._fact(
            id_row, self.t.get("character_order", "Slot")
        )
        id_row.addSpacing(16)
        self.type_value = self._fact(
            id_row, self.t.get("character_type", "Class")
        )
        id_row.addStretch(1)
        layout.addWidget(self.identity_box)

        tabs = QTabWidget()
        self.tabs = tabs

        self.move_tab = MoveTab(
            profile=self.profile,
            strings=self.t,
            language=self.language,
            on_log=self.on_log,
            on_open_map_editor=self.on_open_map_editor,
        )
        tabs.addTab(self.move_tab, self.t.get("move", "move"))

        self.hunt_tab = HuntTab(
            bag=self.bag,
            strings=self.t,
            language=self.language,
            bridge=self.bridge,
            on_log=self.on_log,
            get_primary_map_id=self._primary_battle_map_id,
            get_map_label=self._map_label,
        )
        tabs.addTab(self.hunt_tab, self.t.get("hunt", "hunt"))
        self.move_tab.on_routine_changed = self._on_routine_changed

        self.recovery_tab = RecoveryTab(
            bag=self.bag,
            bridge=self.bridge,
            strings=self.t,
            language=self.language,
            on_log=self.on_log,
        )
        tabs.addTab(self.recovery_tab, self.t.get("recovery", "recovery"))

        self.magic_tab = MagicTab(
            bag=self.bag,
            strings=self.t,
            language=self.language,
            on_log=self.on_log,
        )
        tabs.addTab(self.magic_tab, self.t.get("magic", "magic"))

        self.equipment_tab = EquipmentTab(
            bag=self.bag,
            strings=self.t,
            language=self.language,
            on_log=self.on_log,
        )
        tabs.addTab(self.equipment_tab, self.t.get("equipment", "equipment"))

        self.other_tab = OtherTab(
            profile=self.profile,
            bridge=self.bridge,
            bag=self.bag,
            strings=self.t,
            language=self.language,
            on_log=self.on_log,
            on_run_setup=self.on_run_setup,
            on_start_driver=self.on_start_driver,
            on_profile_reloaded=self.on_profile_reloaded,
            on_hotbar_applied=self._on_hotbar_applied,
            get_log_lines=self.get_log_lines,
            clear_shell_logs=self.clear_shell_logs,
        )
        tabs.addTab(self.other_tab, self.t.get("other", "other"))
        layout.addWidget(tabs, stretch=1)

        commit_bar = QHBoxLayout()
        commit_bar.addStretch(1)
        self.update_btn = QPushButton(
            self.t.get("update_schedule", "Update current")
        )
        self.update_btn.clicked.connect(self.on_update)
        self.update_btn.setEnabled(False)
        commit_bar.addWidget(self.update_btn)
        self.commit_btn = QPushButton(self.t.get("add_schedule", "Add schedule"))
        self.commit_btn.clicked.connect(self.on_add)
        mark_accent(self.commit_btn)
        commit_bar.addWidget(self.commit_btn)
        commit_bar.addStretch(1)
        layout.addLayout(commit_bar)

        self.refresh_accounts()

    def _fact(self, row: QHBoxLayout, label: str) -> QLabel:
        row.addWidget(QLabel(label))
        value = QLabel(self.t.get("value_empty", "—"))
        value.setStyleSheet(f"color: {tokens.TEXT}; font-weight: 700;")
        row.addWidget(value)
        return value

    def refresh_accounts(self, select_id: str | None = None) -> None:
        try:
            accounts = AccountStore().load()
        except Exception:
            accounts = []
        self._accounts_by_id = {account.account_id: account for account in accounts}
        prefer = select_id
        if prefer is None and not self._suppress_account:
            prefer = self.account_combo.currentData()
        self._suppress_account = True
        self.account_combo.clear()
        self.account_combo.addItem(self.t.get("value_empty", "—"), None)
        for account in accounts:
            label = account.display_name or account.username
            self.account_combo.addItem(label, account.account_id)
        if prefer:
            index = self.account_combo.findData(prefer)
            self.account_combo.setCurrentIndex(max(0, index))
        else:
            self.account_combo.setCurrentIndex(0)
        self._suppress_account = False
        self._show_account_details()

    def set_account_id(self, account_id: str | None) -> None:
        """Sync from schedule-list combo without re-emitting."""
        self._suppress_account = True
        index = self.account_combo.findData(account_id)
        self.account_combo.setCurrentIndex(max(0, index))
        self._suppress_account = False
        self._show_account_details()

    def _on_account_changed(self) -> None:
        if self._suppress_account:
            return
        self._show_account_details()
        account_id = self.account_combo.currentData()
        if self.task is not None:
            self.task.account_id = account_id
            account = self._accounts_by_id.get(account_id or "")
            if account is not None:
                self.task.server = str(getattr(account, "server", "") or "")
                self.task.character_slot = int(
                    getattr(account, "character_number", 1) or 1
                )
                character = str(getattr(account, "character_type", "") or "")
                if character in ("elf", "mage", "knight", "royal"):
                    self.task.character = character
        self.accountChanged.emit(account_id)

    def _show_account_details(self) -> None:
        empty = self.t.get("value_empty", "—")
        account = self._accounts_by_id.get(self.account_combo.currentData() or "")
        if account is None:
            self.server_value.setText(empty)
            self.order_value.setText(empty)
            self.type_value.setText(empty)
            return
        self.server_value.setText(str(getattr(account, "server", "") or empty))
        self.order_value.setText(str(getattr(account, "character_number", empty)))
        character = str(getattr(account, "character_type", "") or "")
        self.type_value.setText(self.t.get(character, character) or empty)

    def _primary_battle_map_id(self) -> str:
        if self.move_tab is None:
            return ""
        for row in self.move_tab.vm.rows:
            if row.get("kind") == "battle":
                return str(row.get("map_id") or "")
        if self.move_tab.vm.rows:
            return str(self.move_tab.vm.rows[0].get("map_id") or "")
        return ""

    def _map_label(self, map_id: str) -> str:
        if self.move_tab is None:
            return str(map_id or "")
        return self.move_tab.vm.map_label(map_id)

    def _on_routine_changed(self) -> None:
        if self.hunt_tab is not None and hasattr(self.hunt_tab, "sync_species_region_to_map"):
            try:
                self.hunt_tab.sync_species_region_to_map()
            except Exception:
                pass

    def _on_hotbar_applied(self) -> None:
        if self.magic_tab is not None and hasattr(self.magic_tab, "_refresh_magic_summary"):
            try:
                self.magic_tab._refresh_magic_summary()
            except Exception:
                pass
        if self.recovery_tab is not None and hasattr(self.recovery_tab, "_refresh_summary"):
            try:
                self.recovery_tab._refresh_summary()
            except Exception:
                pass
        if self.recovery_tab is not None and hasattr(
            self.recovery_tab, "refresh_hp_hotbar_keys"
        ):
            try:
                self.recovery_tab.refresh_hp_hotbar_keys()
            except Exception:
                pass

    def reload_move_areas(self) -> None:
        if self.move_tab is not None:
            self.move_tab.refresh()

    def set_commit_mode(self, editing: bool) -> None:
        self._editing = bool(editing)
        self.identity_box.setTitle(
            self.t.get("edit_schedule", "Edit")
            if editing
            else self.t.get("task_details", "Task")
        )
        self.update_btn.setEnabled(bool(editing))
        self.commit_btn.setText(
            self.t.get("save_as_new_schedule", self.t.get("add_schedule", "Add schedule"))
            if editing
            else self.t.get("add_schedule", "Add schedule")
        )

    def _invalidate_lazy_tabs(self) -> None:
        # Hunt catalogs stay mounted; refresh rows from the new bag instead of
        # flipping built flags (that left the user on an empty page until re-entry).
        if self.hunt_tab is not None and hasattr(self.hunt_tab, "reload_from_bag"):
            self.hunt_tab.reload_from_bag()
        for tab in (self.magic_tab, self.recovery_tab, self.equipment_tab):
            if tab is None:
                continue
            for attr in (
                "_individual_built",
                "_hp_built",
                "_sell_built",
            ):
                if hasattr(tab, attr):
                    setattr(tab, attr, False)

    def load_task(self, task: ScheduleTask, *, editing: bool) -> None:
        self.task = copy.deepcopy(task)
        self.bag.load_task(self.task)
        if self.recovery_tab is not None:
            self.recovery_tab.reload_from_bag()
        if self.move_tab is not None:
            self.move_tab.load_from_move_settings(self.task.settings.get("move"))
        self._invalidate_lazy_tabs()
        self.set_commit_mode(editing)
        self.refresh_accounts(select_id=self.task.account_id)
        if self.hunt_tab is not None and hasattr(self.hunt_tab, "_refresh_attack_summary"):
            self.hunt_tab._refresh_attack_summary()
        if self.magic_tab is not None and hasattr(self.magic_tab, "_refresh_magic_summary"):
            self.magic_tab._refresh_magic_summary()
        if self.recovery_tab is not None and hasattr(self.recovery_tab, "_refresh_summary"):
            self.recovery_tab._refresh_summary()
        if self.equipment_tab is not None and hasattr(
            self.equipment_tab, "_refresh_buy_summary"
        ):
            self.equipment_tab._refresh_buy_summary()

    def collect_settings(self) -> dict:
        if self.hunt_tab is not None and hasattr(
            self.hunt_tab, "flush_potion_assist_to_bag"
        ):
            self.hunt_tab.flush_potion_assist_to_bag()
        if self.hunt_tab is not None and getattr(self.hunt_tab, "_monsters_built", False):
            self.hunt_tab._write_species_to_bag()
        if self.hunt_tab is not None and getattr(self.hunt_tab, "_items_built", False):
            self.hunt_tab._write_items_to_bag()
        if self.recovery_tab is not None and getattr(self.recovery_tab, "_hp_built", False):
            self.recovery_tab._write_hp_to_bag()
        if self.equipment_tab is not None and getattr(self.equipment_tab, "_sell_built", False):
            self.equipment_tab._persist_sell()
        if self.recovery_tab is not None:
            self.recovery_tab.flush_options_to_bag()
        data = copy.deepcopy(self.bag.data)
        if self.move_tab is not None:
            routine = normalize_routine(self.move_tab.routine_payload())
            move = data.setdefault("move", {})
            move["routine"] = routine
            primary = next((row for row in routine if row.get("kind") == "battle"), None)
            if primary is None and routine:
                primary = routine[0]
            if primary is not None:
                move["map_id"] = str(primary.get("map_id") or "")
                move["selected_farms"] = list(primary.get("selected_farms") or [])
                move["farm_stays_s"] = dict(primary.get("farm_stays_s") or {})
        return data

    def collect_task(self, base: ScheduleTask | None = None) -> ScheduleTask:
        source = base or self.task or ScheduleTask()
        result = ScheduleTask.from_dict(source.to_dict())
        result.settings = self.collect_settings()
        account_id = self.account_combo.currentData()
        result.account_id = account_id
        account = self._accounts_by_id.get(account_id or "")
        if account is not None:
            result.server = str(getattr(account, "server", "") or "")
            result.character_slot = int(getattr(account, "character_number", 1) or 1)
            character = str(getattr(account, "character_type", "") or "")
            if character in ("elf", "mage", "knight", "royal"):
                result.character = character
            label = account.display_name or account.username
            if label:
                result.name = str(label)[:80]
        return result

    def append_log_row(self, stamp: str, message: str) -> None:
        if self.other_tab is not None:
            self.other_tab.append_log_row(stamp, message)

    def show_status(self, game, memory, map_probe) -> None:
        if self.other_tab is not None:
            self.other_tab.show_status(game, memory, map_probe)
