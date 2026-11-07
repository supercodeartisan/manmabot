"""Task editor notebook — load/collect ScheduleTask + ported tabs."""

from __future__ import annotations

import copy
import json
from typing import Callable

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from settings.accounts import AccountStore
from settings.farm_schedule import normalize_routine
from settings.profile import Profile
from settings.schedule import ScheduleTask
from settings.server_list import display_server_name
from ui_qt.i18n_overlay import tx
from ui_qt.editors.equipment_tab import EquipmentTab
from ui_qt.shell.live_income_bar import LiveIncomeBar
from ui_qt.editors.hunt_tab import HuntTab
from ui_qt.editors.magic_tab import MagicTab
from ui_qt.editors.move_tab import MoveTab
from ui_qt.editors.other_tab import OtherTab
from ui_qt.editors.party_tab import PartyTab
from ui_qt.editors.party_workspace import PartyWorkspace
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
        self._suppress_dirty = 0
        self._baseline: str | None = None
        self._timing_reader: Callable[[ScheduleTask], None] | None = None
        self._watched: set[int] = set()
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setSingleShot(True)
        self._update_check_timer.setInterval(80)
        self._update_check_timer.timeout.connect(self._apply_update_button)
        self.move_tab: MoveTab | None = None
        self.hunt_tab: HuntTab | None = None
        self.recovery_tab: RecoveryTab | None = None
        self.magic_tab: MagicTab | None = None
        self.equipment_tab: EquipmentTab | None = None
        self.party_tab: PartyTab | None = None
        self.other_tab: OtherTab | None = None
        self._build()

    def set_settings_mode(self, mode: str) -> None:
        """Show the solo notebook or the party role workspace."""
        party = str(mode or "") == "party"
        stack = getattr(self, "_settings_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(1 if party else 0)
        if party and self.party_tab is not None:
            self.party_tab.reload_from_bag()
            workspace = getattr(self, "party_workspace", None)
            if workspace is not None:
                workspace.present()

    def party_role_change_allowed(self) -> bool:
        """Reuse RunState plus the existing arming flag. There is no ARMING state."""
        try:
            from session.bot_controller import RunState
        except Exception:
            return True
        if bool(getattr(self.bridge, "arming", False)):
            return False
        controller = getattr(self.bridge, "controller", None)
        if controller is None:
            return True
        if controller.state != RunState.STOPPED:
            return False
        return bool(controller.worker_stopped())

    def party_lock_reason(self) -> str:
        try:
            from session.bot_controller import RunState
        except Exception:
            return ""
        if bool(getattr(self.bridge, "arming", False)):
            return tx(self.t, "party_ui_lock_arming", "실행 준비 중에는 역할을 바꿀 수 없습니다.")
        controller = getattr(self.bridge, "controller", None)
        if controller is None:
            return ""
        if controller.state == RunState.RUNNING:
            return tx(self.t, "party_ui_lock_running", "실행 중에는 역할을 바꿀 수 없습니다.")
        if controller.state == RunState.PAUSED:
            return tx(self.t, "party_ui_lock_paused", "일시정지 중에는 역할을 바꿀 수 없습니다.")
        if controller.state == RunState.STOPPED and not controller.worker_stopped():
            return tx(
                self.t,
                "party_ui_lock_stopping",
                "종료 중입니다. 마우스 입력이 해제된 뒤에 역할을 바꿀 수 없습니다.",
            )
        return ""

    def sync_party_role_lock(self) -> None:
        workspace = getattr(self, "party_workspace", None)
        if workspace is None:
            return
        reason = self.party_lock_reason()
        workspace.set_locked(bool(reason), reason)

    def party_start_block_message(self) -> str | None:
        workspace = getattr(self, "party_workspace", None)
        if workspace is None or workspace.role_ready():
            return None
        return tx(self.t, "party_ui_start_need_role", "역할을 선택한 뒤 파티봇을 시작할 수 없습니다.")

    def set_party_motion(self, text: str) -> None:
        tab = getattr(self, "party_tab", None)
        if tab is not None:
            tab.set_motion_text(text)

    def _maps_editable(self) -> bool:
        try:
            from session.bot_controller import RunState

            return self.bridge.controller.state == RunState.STOPPED
        except Exception:
            return True

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

        self.party_tab = PartyTab(
            bag=self.bag,
            strings=self.t,
            language=self.language,
            on_log=self.on_log,
            profile=self.profile,
            can_edit_map=self._maps_editable,
        )
        self.party_workspace = PartyWorkspace(self.party_tab)

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

        # Solo tabs stay on the routine/hunt notebook. Party settings open
        # from the shell mode switch and fill this same area.
        self._settings_stack = QStackedWidget()
        self._settings_stack.addWidget(tabs)
        self._settings_stack.addWidget(self.party_workspace)
        layout.addWidget(self._settings_stack, stretch=1)
        self.move_tab.on_content_changed = self.schedule_content_touched
        if self.party_tab.routine_panel is not None:
            self.party_tab.routine_panel.on_content_changed = self.schedule_content_touched
        self.bag.on_changed = self.schedule_content_touched

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
        self._watch_widget(self)

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
        self.schedule_content_touched()

    def _show_account_details(self) -> None:
        empty = self.t.get("value_empty", "—")
        account = self._accounts_by_id.get(self.account_combo.currentData() or "")
        if account is None:
            self.server_value.setText(empty)
            self.order_value.setText(empty)
            self.type_value.setText(empty)
            note = getattr(getattr(self, "party_tab", None), "note_local_character", None)
            if callable(note):
                note("")
            return
        self.server_value.setText(
            display_server_name(
                str(getattr(account, "server", "") or ""),
                self.language,
                str(getattr(account, "locale", "") or ""),
            )
            or empty
        )
        self.order_value.setText(str(getattr(account, "character_number", empty)))
        note_name = getattr(self, "party_tab", None)
        note = getattr(note_name, "note_local_character", None)
        if callable(note):
            note(str(getattr(account, "display_name", "") or ""))
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
        self.schedule_content_touched()

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
        if not self._editing:
            self._baseline = None
            self.update_btn.setEnabled(False)
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

    def set_timing_reader(self, reader: Callable[[ScheduleTask], None] | None) -> None:
        """Apply the schedule-list clock and account onto a collected task."""
        self._timing_reader = reader

    def schedule_content_touched(self, *_args) -> None:
        if self._suppress_dirty or not self._editing:
            return
        self._update_check_timer.start()

    def _watch_widget(self, widget: QWidget) -> None:
        for item in (widget, *widget.findChildren(QWidget)):
            if id(item) in self._watched:
                continue
            item.installEventFilter(self)
            self._watched.add(id(item))

    def eventFilter(self, watched, event):  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                self._watch_widget(child)
        elif kind in (
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.KeyRelease,
            QEvent.Type.Wheel,
        ):
            self.schedule_content_touched()
        return super().eventFilter(watched, event)

    def _fingerprint(self) -> str | None:
        """Same payload the update button would save."""
        self._suppress_dirty += 1
        try:
            task = self.collect_task()
            if self._timing_reader is not None:
                self._timing_reader(task)
            return json.dumps(
                task.to_dict(),
                sort_keys=True,
                default=str,
                ensure_ascii=False,
            )
        except Exception:
            return None
        finally:
            self._suppress_dirty -= 1

    def has_unsaved_changes(self) -> bool:
        """True when the open edit differs from the last loaded or saved snapshot."""
        if not self._editing or self._baseline is None:
            return False
        current = self._fingerprint()
        if current is None:
            return self.update_btn.isEnabled()
        return current != self._baseline

    def _apply_update_button(self) -> None:
        if not self._editing or self._baseline is None:
            self.update_btn.setEnabled(False)
            return
        current = self._fingerprint()
        if current is None:
            return
        self.update_btn.setEnabled(current != self._baseline)

    def load_task(
        self,
        task: ScheduleTask,
        *,
        editing: bool,
        inherit_profile_routine: bool = True,
    ) -> None:
        self._suppress_dirty += 1
        try:
            self._load_task_body(
                task,
                editing=editing,
                inherit_profile_routine=inherit_profile_routine,
            )
            if self._editing:
                self._baseline = self._fingerprint()
            else:
                self._baseline = None
        finally:
            self._suppress_dirty -= 1
        self._apply_update_button()

    def _load_task_body(
        self,
        task: ScheduleTask,
        *,
        editing: bool,
        inherit_profile_routine: bool = True,
    ) -> None:
        self.task = copy.deepcopy(task)
        self.bag.load_task(self.task)
        if self.recovery_tab is not None:
            self.recovery_tab.reload_from_bag()
        if self.party_tab is not None:
            self.party_tab.reload_from_bag()
        if self.move_tab is not None:
            self.move_tab.load_from_move_settings(
                self.task.settings.get("move"),
                inherit_profile=inherit_profile_routine,
            )
        self._invalidate_lazy_tabs()
        self.set_commit_mode(editing)
        self.refresh_accounts(select_id=self.task.account_id)
        if self.hunt_tab is not None and hasattr(self.hunt_tab, "_refresh_attack_summary"):
            self.hunt_tab._refresh_attack_summary()
        if self.magic_tab is not None and hasattr(self.magic_tab, "_refresh_magic_summary"):
            self.magic_tab._refresh_magic_summary()
        if self.recovery_tab is not None and hasattr(self.recovery_tab, "_refresh_summary"):
            self.recovery_tab._refresh_summary()
        if self.equipment_tab is not None and hasattr(self.equipment_tab, "reload_from_bag"):
            self.equipment_tab.reload_from_bag()

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
        if self.party_tab is not None:
            self.party_tab.flush_routine()
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
