"""Party tab — member follow/assist, or this PC as the party-socket leader."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from settings.profile import normalize_party_roster
from ui_qt.editors.form_helpers import (
    add_check,
    add_spin_row,
    card,
    configure_table_fill,
    table_row_height_for_controls,
    wrap_cell_widget,
)
from ui_qt.widgets.step_spin import StepSpinBox
from ui_qt.editors.party_routine_panel import PartyRoutinePanel
from ui_qt.i18n_overlay import tx
from ui_qt.i18n_refresh import bind_tx_keys
from ui_qt.viewmodels.settings_bag import SettingsBag
from ui_qt.widgets.step_spin import StepSpinBox

_LOOT_ROLES = ("none", "responsible")
_FARM_MODES = ("party", "solo")
_PARTY_ROLES = ("member", "leader")
_ROSTER_ROLES = ("member", "mage", "shopkeeper")
_ABSENCE_ACTIONS = ("hunt", "hold", "move")


class _RosterChoiceDelegate(QStyledItemDelegate):
    """Combo editor for one roster column. Choices are ``(stored id, label)``."""

    def __init__(self, choices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._choices = choices

    def createEditor(self, parent, option, index):  # noqa: ANN001
        combo = QComboBox(parent)
        combo.setEditable(False)
        for value, label in self._choices():
            combo.addItem(str(label), value)
        combo.activated.connect(lambda _index, box=combo: self.commitData.emit(box))
        return combo

    def setEditorData(self, editor, index) -> None:  # noqa: ANN001
        if not isinstance(editor, QComboBox):
            return
        current = index.data(Qt.ItemDataRole.UserRole)
        found = editor.findData(current)
        editor.blockSignals(True)
        editor.setCurrentIndex(found if found >= 0 else 0)
        editor.blockSignals(False)
        QTimer.singleShot(0, editor.showPopup)

    def setModelData(self, editor, model, index) -> None:  # noqa: ANN001
        if not isinstance(editor, QComboBox):
            return
        value = editor.currentData()
        model.setData(index, value, Qt.ItemDataRole.UserRole)
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class _WsTestBridge(QObject):
    """Marshal WebSocket probe results back onto the UI thread."""

    finished = Signal(bool, str)


class _SupportMagicTable(QTableWidget):
    """Party support spells. Description rows grow and shrink with the width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
        self._fitting = False
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        self.setColumnWidth(0, 56)
        header.sectionResized.connect(self._on_section_resized)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.apply_description_width()
        self.refit()

    def apply_description_width(self) -> None:
        """Give the explanation column whatever width the table has left."""
        if self._fitting or self.columnCount() < 4:
            return
        used = sum(self.columnWidth(index) for index in range(3))
        leftover = self.width() - self.frameWidth() * 2 - used
        if leftover < 48:
            leftover = 48
        if self.columnWidth(3) == leftover:
            return
        self._fitting = True
        try:
            self.setColumnWidth(3, leftover)
        finally:
            self._fitting = False

    def _on_section_resized(self, index: int, _old: int, _new: int) -> None:
        if self._fitting:
            return
        if index in (1, 2):
            self.apply_description_width()
        if index in (1, 2, 3):
            self.refit()

    def refit(self) -> None:
        if self._fitting or self.columnCount() < 4:
            return
        self._fitting = True
        try:
            width = self.columnWidth(3)
            if width < 48:
                width = 360
            total = self.horizontalHeader().height() + 4
            text_width = max(48, width - 16)
            flags = int(
                Qt.TextFlag.TextWordWrap
                | Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignTop
            )
            for row in range(self.rowCount()):
                host = self.cellWidget(row, 3)
                label = host if isinstance(host, QLabel) else None
                if label is None and host is not None:
                    label = host.findChild(QLabel)
                text_height = 28
                if isinstance(label, QLabel):
                    rect = QFontMetrics(label.font()).boundingRect(
                        QRect(0, 0, text_width, 4000),
                        flags,
                        label.text(),
                    )
                    text_height = max(1, rect.height())
                    label.setMinimumHeight(text_height)
                    label.setMaximumHeight(text_height)
                height = max(36, int(text_height) + 16)
                if self.rowHeight(row) != height:
                    self.setRowHeight(row, height)
                total += height
            target = total + self.frameWidth() * 2
            if self.minimumHeight() != target or self.maximumHeight() != target:
                self.setMinimumHeight(target)
                self.setMaximumHeight(target)
        finally:
            self._fitting = False


class PartyTab(QWidget):
    def __init__(
        self,
        *,
        bag: SettingsBag,
        strings: dict[str, str],
        language: str = "en",
        on_log: Callable[[str], None] | None = None,
        profile=None,
        can_edit_map: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bag = bag
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self._profile = profile
        self._can_edit_map = can_edit_map
        self.routine_panel: PartyRoutinePanel | None = None
        self._lan_ip = ""
        self._ws_testing = False
        self._ws_status_target: QLabel | None = None
        self._ws_bridge = _WsTestBridge(self)
        self._ws_bridge.finished.connect(self._on_ws_test_finished)
        self._build()

    def _tx(self, key: str, fallback: str) -> str:
        return tx(self.t, key, fallback)

    def _section(self) -> tuple[QWidget, QVBoxLayout]:
        host = QWidget(self)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        return host, lay

    def _build(self) -> None:
        """Build role sections. The workspace places them on separate menus."""
        with bind_tx_keys():
            self._build_sections()

    def _build_sections(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._migrate_enabled_flag()
        self.bag.set("party", "leader_name", "")

        self.enable_host = QWidget(self)
        enable_lay = QVBoxLayout(self.enable_host)
        enable_lay.setContentsMargins(0, 0, 0, 0)
        self.party_enable = add_check(
            enable_lay,
            self.bag,
            "party",
            "enabled",
            self.t.get("party_enabled", "파티 사용"),
            False,
            on_change=self._on_party_enabled_changed,
        )
        self.party_enable.setText(self.t.get("party_enabled", "파티 사용"))
        self.enable_host.hide()

        self.member_sections = {
            "link": self._build_member_link(),
            "follow": self._build_member_follow(),
            "assist": self._build_member_assist(),
            "support": self._build_member_support(),
            "personal": self._build_member_personal(),
            "status": self._build_member_status(),
        }
        self.leader_sections = {
            "manage": self._build_leader_manage(),
            "ops": self._build_leader_ops(),
            "map": self._build_leader_map(),
            "supply": self._build_leader_supply(),
            "loot": self._build_leader_loot(),
            "common": self._build_leader_common(),
        }
        self._refresh_successor_choices()
        self._apply_role(self._role())

    def _build_member_link(self) -> QWidget:
        host, lay = self._section()
        self.member_ws_box = card(host, self._tx("party_ui_menu_link", "파티장 연결"))
        lay.addWidget(self.member_ws_box)
        ws_lay = self.member_ws_box.layout()
        assert isinstance(ws_lay, QVBoxLayout)

        host_row = QHBoxLayout()
        host_row.addWidget(QLabel(self._tx("party_ui_leader_ip", "파티장 IP")))
        self.leader_host = QLineEdit(
            str(self.bag.get_str("party", "leader_host", "") or "")
        )
        self.leader_host.setPlaceholderText("10.0.0.2")
        self.leader_host.textChanged.connect(self._on_leader_host_changed)
        host_row.addWidget(self.leader_host, stretch=1)
        ws_lay.addLayout(host_row)
        self.member_ws_port = add_spin_row(
            ws_lay,
            self.bag,
            "party",
            "ws_port",
            self._tx("party_ui_port", "포트"),
            8765,
            1,
            65535,
            on_change=self._refresh_member_summary,
        )
        test_row = QHBoxLayout()
        self.ws_test_btn = QPushButton(self._tx("party_ui_test", "연결 테스트"))
        self.ws_test_btn.clicked.connect(self._test_ws_connection)
        test_row.addWidget(self.ws_test_btn)
        self.ws_status = QLabel(self._tx("party_ui_status_untested", "연결 상태: 아직 테스트하지 않음"))
        self.ws_status.setWordWrap(True)
        test_row.addWidget(self.ws_status, stretch=1)
        ws_lay.addLayout(test_row)
        self.leader_info = QLabel("")
        self.leader_info.setWordWrap(True)
        ws_lay.addWidget(self.leader_info)
        lay.addStretch(1)
        self._refresh_member_summary()
        return host

    def _build_member_follow(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_follow_title", "따라가기"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        self.party_follow_tiles = add_spin_row(
            inner,
            self.bag,
            "party",
            "follow_tiles",
            self._tx("party_ui_follow_distance", "따라가기 거리"),
            8,
            1,
            40,
            on_change=self._clamp_follow_stop,
        )
        self.party_stop_tiles = add_spin_row(
            inner,
            self.bag,
            "party",
            "stop_tiles",
            self._tx("party_ui_stop_distance", "정지 거리"),
            2,
            0,
            40,
            on_change=self._clamp_follow_stop,
        )
        self.follow_motion = QLabel(self._tx("party_ui_motion_idle", "이동 상태: 정지"))
        self.follow_motion.setWordWrap(True)
        inner.addWidget(self.follow_motion)
        note = QLabel(
            self._tx(
                "party_ui_follow_note",
                "이동 상태는 프로그램 상태만 표시합니다. "
                "따라가는 중의 칸 거리는 실행 중 파티 동작이 처리하며, "
                "이 화면은 그 값을 새로 만들지 않습니다.",
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        lay.addStretch(1)
        return host

    def _build_member_assist(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_assist_title", "공격 지원"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        farm_hint = QLabel(
            self._tx(
                "party_ui_assist_hint",
                "파티: 파티장이 공격하는 대상을 따라 공격합니다. "
                "단독: 파티장 근처에서 자기 대상을 공격합니다.",
            )
        )
        farm_hint.setWordWrap(True)
        inner.addWidget(farm_hint)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self._tx("party_ui_assist_label", "파티장 공격 대상 추종")))
        self.party_farm_mode = QComboBox()
        self.party_farm_mode.addItem(self._tx("party_ui_assist_follow", "추종"), "party")
        self.party_farm_mode.addItem(self._tx("party_ui_assist_own", "주변 대상 단독 공격"), "solo")
        self._select_farm_mode()
        self.party_farm_mode.currentIndexChanged.connect(self._on_farm_mode_changed)
        self.party_farm_mode.setEnabled(False)
        mode_row.addWidget(self.party_farm_mode)
        mode_row.addStretch(1)
        inner.addLayout(mode_row)
        self.party_assist_leash = add_spin_row(
            inner,
            self.bag,
            "party",
            "assist_leash_tiles",
            self._tx("party_ui_assist_distance", "어시스트 거리"),
            10,
            1,
            40,
        )
        self._add_attack_target_box(host, lay, editable=False)
        lay.addStretch(1)
        return host

    def _build_member_support(self) -> QWidget:
        """F05 display and saved choices. Combat does not read these yet."""
        host, lay = self._section()
        hit = card(host, self._tx("party_ui_hit_title", "파티원 피격 시 지원"))
        lay.addWidget(hit)
        hit_lay = hit.layout()
        assert isinstance(hit_lay, QVBoxLayout)
        self.member_hit_group = QButtonGroup(host)
        self.member_hit_group.setExclusive(True)
        mode = str(self.bag.get_str("party", "hit_support", "immediate") or "immediate")
        if mode not in ("immediate", "finish"):
            mode = "immediate"
        options = (
            (
                "immediate",
                "party_ui_hit_now",
                "즉시 지원",
                "party_ui_hit_now_note",
                "파티원이 몬스터에게 공격받으면 현재 공격 중인 몬스터를 중단하고 "
                "해당 파티원을 공격하는 몬스터를 즉시 공격한다.",
            ),
            (
                "finish",
                "party_ui_hit_after",
                "현재 공격하던 몬스터 처치 후 지원",
                "party_ui_hit_after_note",
                "현재 공격 중인 몬스터를 먼저 처치한 다음 "
                "해당 파티원을 공격하는 몬스터를 공격한다.",
            ),
        )
        self.member_hit_buttons: dict[str, QRadioButton] = {}
        for value, title_key, title_fallback, note_key, note_fallback in options:
            button = QRadioButton(self._tx(title_key, title_fallback))
            button.setChecked(mode == value)
            self.member_hit_group.addButton(button)
            hit_lay.addWidget(button)
            note = QLabel(self._tx(note_key, note_fallback))
            note.setWordWrap(True)
            hit_lay.addWidget(note)
            self.member_hit_buttons[value] = button
            button.toggled.connect(
                lambda checked, chosen=value: self._on_hit_support(chosen, checked)
            )
        if not any(button.isChecked() for button in self.member_hit_buttons.values()):
            self.member_hit_buttons["immediate"].setChecked(True)

        self._build_member_support_magic(host, lay)
        lay.addStretch(1)
        return host

    def _on_hit_support(self, mode: str, checked: bool) -> None:
        if checked:
            self.bag.set("party", "hit_support", mode)

    def _build_member_support_magic(self, host: QWidget, lay: QVBoxLayout) -> None:
        """Mage party support spells, including heal. Solo magic table stays separate."""
        box = card(host, self._tx("party_ui_support_magic_title", "파티 지원 마법"))
        self.member_support_magic_box = box
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        note = QLabel(
            self._tx(
                "party_ui_support_magic_note",
                "마법사 캐릭터의 파티원 화면에서만 고릅니다. "
                "체크한 마법은 파티 설정에만 저장되고, 솔로 개별 마법 표는 바꾸지 않습니다.",
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        table = _SupportMagicTable()
        table.setHorizontalHeaderLabels(
            [
                self._tx("party_ui_support_magic_use", "사용"),
                self._tx("party_ui_support_magic_group", "구분"),
                self._tx("party_ui_support_magic_name", "마법"),
                self._tx("party_ui_support_magic_detail", "설명"),
            ]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.member_support_magic_table = table
        inner.addWidget(table)
        self._fill_support_magic_table()

    def note_local_character(self, name: str) -> None:
        """This PC's roster name. Successor choices skip this character."""
        self._local_character_name = str(name or "").strip()
        self._refresh_party_heal()
        self._refresh_successor_choices()

    def _local_character_name_text(self) -> str:
        return str(getattr(self, "_local_character_name", "") or "").strip()

    def _refresh_party_heal(self) -> None:
        self._fill_support_magic_table()

    def _mage_character(self) -> bool:
        return self.bag.get_str("magic", "class", "") == "mage"

    def _support_magic_saved(self) -> dict[str, bool]:
        raw = self.bag.get("party", "mage_support_skills", {})
        if not isinstance(raw, dict):
            return {}
        saved: dict[str, bool] = {}
        for key, value in raw.items():
            text = str(key or "").strip()
            if text:
                saved[text] = bool(value)
        return saved

    def _support_magic_checked(self, setting_key: str, saved: dict[str, bool]) -> bool:
        """Heal starts on. A saved choice, including turning heal off, wins."""
        if setting_key in saved:
            return bool(saved[setting_key])
        return setting_key == "mage_0"

    def _write_support_magic(self, setting_key: str, checked: bool) -> None:
        saved = self._support_magic_saved()
        saved[str(setting_key)] = bool(checked)
        self.bag.set("party", "mage_support_skills", saved)

    def _support_group_label(self, group: str) -> str:
        if group == "recovery":
            return self._tx("party_ui_support_magic_recovery", "회복")
        return self._tx("party_ui_support_magic_buff", "강화")

    def _fill_support_magic_table(self) -> None:
        box = getattr(self, "member_support_magic_box", None)
        table = getattr(self, "member_support_magic_table", None)
        if box is None or table is None:
            return
        mage = self._mage_character()
        box.setVisible(mage)
        if not mage:
            return
        from settings.party_mage_support import party_mage_support_rows

        rows = party_mage_support_rows(self.language)
        saved = self._support_magic_saved()
        self._release_table_widgets(table)
        table.blockSignals(True)
        for index, row in enumerate(rows):
            key = str(row["setting_key"])
            table.insertRow(index)
            check = QCheckBox()
            check.blockSignals(True)
            check.setChecked(self._support_magic_checked(key, saved))
            check.blockSignals(False)
            check.toggled.connect(
                lambda checked, setting_key=key: self._write_support_magic(
                    setting_key, bool(checked)
                )
            )
            table.setCellWidget(index, 0, wrap_cell_widget(check))
            group = QTableWidgetItem(self._support_group_label(str(row["group"])))
            group.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(index, 1, group)
            name = QTableWidgetItem(str(row["name"]))
            name.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(index, 2, name)
            detail = QLabel(str(row["detail"]))
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            detail.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            detail.setStyleSheet("background: transparent;")
            host = QWidget()
            host.setStyleSheet("background: transparent;")
            column = QVBoxLayout(host)
            column.setContentsMargins(4, 0, 4, 0)
            column.setSpacing(0)
            column.addStretch(1)
            column.addWidget(detail)
            column.addStretch(1)
            table.setCellWidget(index, 3, host)
        table.blockSignals(False)
        if isinstance(table, _SupportMagicTable):
            table.refit()

    def _release_table_widgets(self, table: QTableWidget) -> None:
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                widget = table.cellWidget(row, col)
                if widget is None:
                    continue
                table.removeCellWidget(row, col)
                widget.setParent(None)
                widget.deleteLater()
        table.setRowCount(0)

    def _build_member_personal(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_personal_title", "개인 행동 설정"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        hint = QLabel(
            self._tx(
                "party_ui_personal_hint",
                "따라가기, 정지, 어시스트, 사냥 방식은 이 봇의 개인 설정입니다. "
                "루팅 규칙은 파티장에게서 받습니다.",
            )
        )
        hint.setWordWrap(True)
        inner.addWidget(hint)
        self.personal_summary = QLabel("")
        self.personal_summary.setWordWrap(True)
        inner.addWidget(self.personal_summary)
        self.policy_summary_host = QWidget()
        policy_lay = QVBoxLayout(self.policy_summary_host)
        policy_lay.setContentsMargins(0, 8, 0, 0)
        future = QLabel(self._tx("party_ui_policy_title", "파티장 정책 요약"))
        future.setObjectName("muted")
        policy_lay.addWidget(future)
        reserved = QLabel(
            self._tx(
                "party_ui_policy_reserved",
                "파티장이 보낸 정책은 이후 이 자리에 읽기 전용으로 표시합니다.",
            )
        )
        reserved.setWordWrap(True)
        policy_lay.addWidget(reserved)
        inner.addWidget(self.policy_summary_host)
        lay.addStretch(1)
        self._refresh_personal_summary()
        return host

    def _build_member_status(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_status_title", "파티 상태"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        self.status_connection = QLabel(self._tx("party_ui_status_untested", "연결 상태: 아직 테스트하지 않음"))
        self.status_connection.setWordWrap(True)
        inner.addWidget(self.status_connection)
        self.status_leader = QLabel(self._tx("party_ui_leader_unknown", "파티장 상태: 미입력"))
        self.status_leader.setWordWrap(True)
        inner.addWidget(self.status_leader)
        join = QLabel(
            self._tx(
                "party_ui_join_note",
                "파티 참여 상태는 실행 중 파티 메모리로 확인합니다. "
                "이 화면은 참여 여부를 새로 판단하지 않습니다.",
            )
        )
        join.setWordWrap(True)
        inner.addWidget(join)
        lay.addStretch(1)
        return host

    def _build_leader_manage(self) -> QWidget:
        host, lay = self._section()
        self._build_roster(lay)
        self._build_leader_succession(host, lay)
        lay.addStretch(1)
        return host

    def _build_leader_succession(self, host: QWidget, lay: QVBoxLayout) -> None:
        """F08 settings. Transfer result stays blank until the engine reports it."""
        box = card(host, self._tx("party_ui_succession_title", "파티장 자동 인계"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        self.succession_enable = add_check(
            inner,
            self.bag,
            "party",
            "succession_enabled",
            self._tx("party_ui_succession_enable", "파티장 자동 인계 사용"),
            False,
            on_change=self._refresh_succession_warning,
        )
        note = QLabel(
            self._tx(
                "party_ui_succession_note",
                "파티장이 마을로 이동하면 지정된 차기 파티원에게 파티장 권한을 인계합니다.",
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel(self._tx("party_ui_successor", "차기 파티장")))
        self.succession_combo = QComboBox()
        self.succession_combo.setMinimumWidth(160)
        self.succession_combo.currentIndexChanged.connect(self._on_successor_changed)
        row.addWidget(self.succession_combo)
        row.addStretch(1)
        inner.addLayout(row)
        self.succession_warning = QLabel(
            self._tx(
                "party_ui_succession_need",
                "자동 인계를 사용하려면 차기 파티장을 한 명 지정하세요.",
            )
        )
        self.succession_warning.setWordWrap(True)
        self.succession_warning.setObjectName("muted")
        inner.addWidget(self.succession_warning)
        self.succession_state = QLabel("")
        self.succession_state.setWordWrap(True)
        inner.addWidget(self.succession_state)
        self.succession_reason = QLabel("")
        self.succession_reason.setWordWrap(True)
        inner.addWidget(self.succession_reason)
        self._refresh_successor_choices()
        self._show_succession_result("", "")

    def _build_leader_ops(self) -> QWidget:
        host, lay = self._section()
        self._leader_ops_host = host
        self._build_leader_absence(host, lay)
        self._add_attack_target_box(host, lay, editable=True)
        self._build_leader_mage_heal(host, lay)
        lay.addStretch(1)
        host.installEventFilter(self)
        return host

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is getattr(self, "_leader_ops_host", None)
            and event.type() == QEvent.Type.Show
        ):
            self._fill_absence_places()
        return super().eventFilter(watched, event)

    def _build_leader_absence(self, host: QWidget, lay: QVBoxLayout) -> None:
        """F09 settings. Live action state stays blank until the engine reports it."""
        box = card(host, self._tx("party_ui_absence_title", "파티장 부재 시 파티원 행동"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        note = QLabel(
            self._tx(
                "party_ui_absence_note",
                "파티장이 마을로 이동하고 파티장 인계가 진행되는 동안 "
                "나머지 파티원들이 수행할 행동을 설정합니다.",
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        self.absence_group = QButtonGroup(host)
        self.absence_group.setExclusive(True)
        self.absence_buttons: dict[str, QRadioButton] = {}
        options = (
            ("hunt", "party_ui_absence_hunt", "기존 사냥 계속하기"),
            ("hold", "party_ui_absence_hold", "현재 위치에서 대기하기"),
            ("move", "party_ui_absence_move", "지정 장소로 이동하기"),
        )
        current = self._absence_action()
        for key, text_key, fallback in options:
            button = QRadioButton(self._tx(text_key, fallback))
            self.absence_group.addButton(button)
            self.absence_buttons[key] = button
            inner.addWidget(button)
        for key, button in self.absence_buttons.items():
            button.setChecked(key == current)
            button.toggled.connect(
                lambda checked, chosen=key: self._on_absence_action(chosen, checked)
            )
        place_row = QHBoxLayout()
        place_row.addWidget(QLabel(self._tx("party_ui_absence_place", "지정 장소")))
        self.absence_place = QComboBox()
        self.absence_place.setMinimumWidth(220)
        self.absence_place.currentIndexChanged.connect(self._on_absence_place)
        place_row.addWidget(self.absence_place, stretch=1)
        inner.addLayout(place_row)
        self.absence_place_pending = QLabel(
            self._tx("party_ui_absence_place_pending", "추후 연결 필요")
        )
        self.absence_place_pending.setWordWrap(True)
        self.absence_place_pending.setObjectName("muted")
        inner.addWidget(self.absence_place_pending)
        self.absence_place_warning = QLabel(
            self._tx(
                "party_ui_absence_place_missing",
                "지정한 장소를 현재 사냥터 데이터에서 찾지 못했습니다.",
            )
        )
        self.absence_place_warning.setWordWrap(True)
        self.absence_place_warning.setObjectName("muted")
        inner.addWidget(self.absence_place_warning)
        self.absence_state = QLabel("")
        self.absence_state.setWordWrap(True)
        inner.addWidget(self.absence_state)
        self.absence_reason = QLabel("")
        self.absence_reason.setWordWrap(True)
        inner.addWidget(self.absence_reason)
        self._fill_absence_places()
        self._show_absence_result("", "")

    def _add_attack_target_box(
        self,
        host: QWidget,
        layout: QVBoxLayout,
        *,
        editable: bool,
    ) -> None:
        box = card(host, self._tx("party_ui_target_title", "공격 대상 선택"))
        layout.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        group = QButtonGroup(box)
        group.setExclusive(True)
        buttons: dict[str, QRadioButton] = {}
        options = (
            (
                "party",
                self._tx("party_ui_target_follow", "파티장 공격 대상 따라가기"),
                self._tx(
                    "party_ui_target_follow_note",
                    "파티장이 공격하는 몬스터를 파티원도 같이 공격합니다.",
                ),
            ),
            (
                "solo",
                self._tx("party_ui_target_random", "랜덤 공격"),
                self._tx(
                    "party_ui_target_random_note",
                    "각 파티원이 주변의 공격 가능한 몬스터를 따로 고릅니다.",
                ),
            ),
        )
        for mode, title, detail in options:
            button = QRadioButton(title)
            button.setEnabled(editable)
            group.addButton(button)
            inner.addWidget(button)
            note = QLabel(detail)
            note.setWordWrap(True)
            inner.addWidget(note)
            buttons[mode] = button
            if editable:
                button.toggled.connect(
                    lambda checked, picked=mode: self._on_attack_target_toggled(
                        picked, checked
                    )
                )
        status = QLabel(
            self._tx("party_ui_target_saved", "설정 저장 가능 · 파티원 전달은 엔진 연결 전")
            if editable
            else self._tx(
                "party_ui_target_readonly",
                "읽기 전용 · 엔진 연결 전. 다른 PC의 파티장 선택은 아직 수신되지 않습니다.",
            )
        )
        status.setWordWrap(True)
        status.setObjectName("muted")
        inner.addWidget(status)
        if editable:
            self.ops_attack_buttons = buttons
            self.ops_attack_status = status
        else:
            self.member_attack_buttons = buttons
            self.member_attack_status = status
        self._select_attack_target()

    def _select_attack_target(self) -> None:
        mode = self._farm_mode()
        groups = (
            getattr(self, "ops_attack_buttons", None),
            getattr(self, "member_attack_buttons", None),
        )
        for buttons in groups:
            if not isinstance(buttons, dict):
                continue
            button = buttons.get(mode)
            if not isinstance(button, QRadioButton) or button.isChecked():
                continue
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)

    def _on_attack_target_toggled(self, mode: str, checked: bool) -> None:
        if not checked:
            return
        if mode not in _FARM_MODES:
            mode = "party"
        if mode == self._farm_mode():
            self._select_attack_target()
            return
        self.bag.set("party", "farm_mode", mode)
        self._select_farm_mode()
        self._refresh_personal_summary()

    def _build_leader_map(self) -> QWidget:
        host, lay = self._section()
        if self._profile is not None:
            self.routine_panel = PartyRoutinePanel(
                bag=self.bag,
                profile=self._profile,
                strings=self.t,
                language=self.language,
                on_log=self.on_log,
                can_edit_map=self._can_edit_map,
            )
            lay.addWidget(self.routine_panel, stretch=1)
        else:
            self.routine_panel = None
            pending = QLabel(
                self._tx(
                    "party_ui_map_pending",
                    "프로필이 연결되면 기존 파티 지도 편집기가 이 자리에 열립니다.",
                )
            )
            pending.setWordWrap(True)
            lay.addWidget(pending)
            lay.addStretch(1)
        return host

    def _build_leader_mage_heal(self, host: QWidget, lay: QVBoxLayout) -> None:
        """Other-member heal line. Self heal, potions, and retreat stay on solo."""
        box = card(host, self._tx("party_ui_care_mage", "마법사가 다른 파티원을 힐"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        note = QLabel(
            self._tx(
                "party_ui_care_mage_note",
                "다른 파티원의 체력이 이 값보다 낮으면 마법사가 파티 목록에서 힐합니다. "
                "본인 힐, 물약, 후퇴, 어머니 숲, 말하는 두루마리, 안전지대는 "
                "각 캐릭터의 솔로 설정을 씁니다.",
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        self.party_mage_heal_pct = add_spin_row(
            inner,
            self.bag,
            "party",
            "mage_heal_pct",
            self._tx("party_ui_care_mage", "마법사가 다른 파티원을 힐"),
            80,
            1,
            100,
            "%",
        )

    def _build_leader_supply(self) -> QWidget:
        host, lay = self._section()
        self_box = card(host, self._tx("party_ui_supply_self_title", "본인이 사는 것"))
        lay.addWidget(self_box)
        self_inner = self_box.layout()
        assert isinstance(self_inner, QVBoxLayout)
        self_note = QLabel(
            self._tx(
                "party_ui_supply_self_note",
                "상점 담당 자신의 가방입니다. "
                "가진 수가 담당 유지보다 적으면 상점에 가서 사는 수만큼 삽니다. "
                "아데나가 부족하면 그 가격으로 살 수 있는 개수만 삽니다. "
                "한 개 값도 안 되면 그 물건은 건너뜁니다. "
                "체력, 해독, 은화살 순으로 이어서 사고, "
                "더 살 곳이 없으면 파티장에게 돌아옵니다. "
                "마나 물약은 상점이 없어서 사지 않습니다.",
            )
        )
        self_note.setWordWrap(True)
        self_inner.addWidget(self_note)
        self.supply_self_table = self._build_supply_self_table()
        self_inner.addWidget(self.supply_self_table)

        other_box = card(
            host, self._tx("party_ui_supply_others_title", "다른 파티원에게 주는 것")
        )
        lay.addWidget(other_box)
        other_inner = other_box.layout()
        assert isinstance(other_inner, QVBoxLayout)
        other_note = QLabel(
            self._tx(
                "party_ui_supply_others_note",
                "다른 파티원 가방이 미만이면 줌보다 적으면, "
                "그 옆에 주는 수만큼 떨어뜨립니다. "
                "담당 유지보다 적게 주지는 않습니다. "
                "여분이 없으면 사는 수만큼 삽니다. "
                "아데나가 부족하면 그 가격으로 살 수 있는 개수만 삽니다. "
                "체력 다음에 해독, 그 다음에 은화살을 이어서 사고 "
                "더 갈 상점이 없으면 파티장에게 돌아옵니다.",
            )
        )
        other_note.setWordWrap(True)
        other_inner.addWidget(other_note)
        self.supply_others_table = self._build_supply_others_table()
        other_inner.addWidget(self.supply_others_table)
        lay.addStretch(1)
        return host

    def _supply_table_rows(self) -> tuple[tuple, ...]:
        """Item, who receives it, then member min / keeper keep / give / buy."""
        return (
            (
                self._tx("party_ui_supply_hp", "체력 물약"),
                self._tx("party_ui_supply_all_but_keeper", "전원 (담당 제외)"),
                ("party_member_hp_min", "member_hp_min", 10, 0, 9999),
                ("party_shopkeeper_hp_min", "shopkeeper_hp_min", 20, 0, 9999),
                ("party_member_hp_give", "member_hp_give", 10, 1, 9999),
                ("party_shopkeeper_hp_buy", "shopkeeper_hp_buy", 20, 1, 999),
            ),
            (
                self._tx("party_ui_supply_cure", "해독 물약"),
                self._tx("party_ui_supply_all_but_keeper", "전원 (담당 제외)"),
                ("party_member_depoison_min", "member_depoison_min", 1, 0, 9999),
                ("party_shopkeeper_depoison_min", "shopkeeper_depoison_min", 2, 0, 9999),
                ("party_member_depoison_give", "member_depoison_give", 1, 1, 9999),
                ("party_shopkeeper_depoison_buy", "shopkeeper_depoison_buy", 5, 1, 999),
            ),
            (
                self._tx("party_ui_supply_mp", "마나 물약"),
                self._tx("party_ui_supply_mage_only", "마법사만"),
                ("party_member_mp_min", "member_mp_min", 5, 0, 9999),
                ("party_shopkeeper_mp_min", "shopkeeper_mp_min", 10, 0, 9999),
                ("party_member_mp_give", "member_mp_give", 5, 1, 9999),
                None,
            ),
            (
                self._tx("party_ui_supply_arrow", "은화살"),
                self._tx("party_ui_supply_not_mage", "마법사 제외"),
                ("party_member_arrow_min", "member_arrow_min", 300, 0, 9999),
                ("party_shopkeeper_arrow_min", "shopkeeper_arrow_min", 300, 0, 9999),
                ("party_member_arrow_give", "member_arrow_give", 100, 1, 9999),
                ("party_shopkeeper_arrow_buy", "shopkeeper_arrow_buy", 200, 1, 999),
            ),
        )

    def _new_supply_table(self, headers: list[str], tips: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        for index, tip in enumerate(tips):
            item = table.horizontalHeaderItem(index)
            if item is not None and tip:
                item.setToolTip(tip)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return table

    def _fit_supply_table(self, table: QTableWidget) -> None:
        row_h = table_row_height_for_controls()
        for row in range(table.rowCount()):
            table.setRowHeight(row, row_h)
        height = (
            row_h * table.rowCount()
            + table.horizontalHeader().height()
            + table.frameWidth() * 2
            + 6
        )
        table.setMinimumHeight(height)
        table.setMaximumHeight(height)

    def _place_supply_field(self, table: QTableWidget, row: int, col: int, field) -> None:
        if field is None:
            self._supply_text_cell(table, row, col, self._tx("party_ui_supply_none", "없음"))
            cell = table.item(row, col)
            if cell is not None:
                cell.setToolTip(
                    self._tx(
                        "party_ui_supply_no_shop",
                        "마나 물약 상점은 없습니다. 가방에 있는 것만 줍니다.",
                    )
                )
            return
        attr, bag_key, default, low, high = field
        spin = self._supply_spin(bag_key, default, low, high)
        setattr(self, attr, spin)
        table.setCellWidget(row, col, wrap_cell_widget(spin))

    def _build_supply_self_table(self) -> QTableWidget:
        table = self._new_supply_table(
            [
                self._tx("party_ui_supply_item", "물건"),
                self._tx("party_ui_supply_keep", "담당 유지"),
                self._tx("party_ui_supply_buy", "사는 수"),
            ],
            [
                "",
                self._tx(
                    "party_ui_supply_keep_tip",
                    "상점 담당이 자기 가방에 남기는 수입니다. 그보다 적으면 상점으로 갑니다.",
                ),
                self._tx(
                    "party_ui_supply_buy_tip",
                    "상점에서 한 번에 사는 개수입니다.",
                ),
            ],
        )
        for row_i, spec in enumerate(self._supply_table_rows()):
            name, _who, _member_min, keeper_min, _give, buy = spec
            table.insertRow(row_i)
            self._supply_text_cell(table, row_i, 0, name)
            self._place_supply_field(table, row_i, 1, keeper_min)
            self._place_supply_field(table, row_i, 2, buy)
        configure_table_fill(table, 0, fixed={1: 120, 2: 110})
        self._fit_supply_table(table)
        return table

    def _build_supply_others_table(self) -> QTableWidget:
        table = self._new_supply_table(
            [
                self._tx("party_ui_supply_item", "물건"),
                self._tx("party_ui_supply_who", "받는 사람"),
                self._tx("party_ui_supply_member", "미만이면 줌"),
                self._tx("party_ui_supply_give", "주는 수"),
            ],
            [
                "",
                self._tx("party_ui_supply_who_tip", "이 물건을 받을 자리입니다."),
                self._tx(
                    "party_ui_supply_member_tip",
                    "그 가방이 이 수보다 적으면 보급합니다.",
                ),
                self._tx(
                    "party_ui_supply_give_tip",
                    "한 번에 떨어뜨리는 개수입니다. 남은 여유가 더 적으면 그 여유만 줍니다.",
                ),
            ],
        )
        for row_i, spec in enumerate(self._supply_table_rows()):
            name, who, member_min, _keeper_min, give, _buy = spec
            table.insertRow(row_i)
            self._supply_text_cell(table, row_i, 0, name)
            self._supply_text_cell(table, row_i, 1, who)
            self._place_supply_field(table, row_i, 2, member_min)
            self._place_supply_field(table, row_i, 3, give)
        configure_table_fill(table, 1, fixed={0: 92, 2: 120, 3: 110})
        self._fit_supply_table(table)
        return table

    def _supply_text_cell(self, table: QTableWidget, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        table.setItem(row, col, item)

    def _supply_spin(self, bag_key: str, default: int, low: int, high: int) -> StepSpinBox:
        spin = StepSpinBox(compact=True)
        spin.setRange(low, high)
        spin.setValue(self.bag.get_int("party", bag_key, default))

        def _sync(value: int, key: str = bag_key) -> None:
            self.bag.set("party", key, int(value))

        spin.valueChanged.connect(_sync)
        spin.editingFinished.connect(lambda key=bag_key, box=spin: self.bag.set("party", key, int(box.value())))
        return spin

    def _build_leader_loot(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_loot_title", "아이템 및 루팅"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        loot_hint = QLabel(
            self._tx(
                "party_ui_loot_hint",
                "무작위 루팅: 파티장과 마법사를 제외하고 가장 가까운 파티원이 "
                "파티 드랍을 줍습니다. 끄면 명단에서 담당으로 표시된 줄만 "
                "자기 드랍을 줍습니다. 파티장이 이동 중일 때 파티원은 줍지 않습니다.",
            )
        )
        loot_hint.setWordWrap(True)
        inner.addWidget(loot_hint)
        self.party_random_loot = add_check(
            inner,
            self.bag,
            "party",
            "random_loot",
            self._tx("party_ui_random_loot", "무작위 루팅"),
            False,
            on_change=self._on_loot_mode_changed,
        )
        self.party_loot_pickup = QComboBox(host)
        self.party_loot_pickup.addItem(
            self._tx("party_ui_loot_all", "아이템과 아데나"), "all"
        )
        self.party_loot_pickup.addItem(
            self._tx("party_ui_loot_adena", "아데나만"), "adena"
        )
        pickup = str(self.bag.get_str("party", "loot_pickup", "all") or "all")
        if pickup not in ("all", "adena"):
            pickup = "all"
        self.party_loot_pickup.setCurrentIndex(0 if pickup == "all" else 1)
        self.party_loot_pickup.currentIndexChanged.connect(self._on_loot_pickup_changed)
        inner.addWidget(self.party_loot_pickup)
        self.party_loot_weight_pct = add_spin_row(
            inner,
            self.bag,
            "party",
            "loot_weight_pct",
            self._tx("party_ui_loot_weight", "아데나 전환 무게"),
            30,
            1,
            100,
            "%",
        )
        self.party_loot_role = QComboBox(host)
        self.party_loot_role.addItem(self._tx("party_ui_loot_none", "없음"), "none")
        self.party_loot_role.addItem(self._tx("party_ui_loot_owner", "담당"), "responsible")
        self.party_loot_role.hide()
        current = str(self.bag.get_str("party", "loot_role", "none") or "none")
        if current not in _LOOT_ROLES:
            current = "none"
        idx = self.party_loot_role.findData(current)
        self.party_loot_role.setCurrentIndex(max(0, idx))
        self.party_loot_role.currentIndexChanged.connect(self._on_loot_role_changed)
        lay.addStretch(1)
        return host

    def _build_leader_common(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_common_title", "공통 설정"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        self.ip_edit = self._address_row(inner, self._tx("party_ui_lan_ip", "내부 IP"))
        self.party_ws_port = add_spin_row(
            inner,
            self.bag,
            "party",
            "ws_port",
            self._tx("party_ui_port", "포트"),
            8765,
            1,
            65535,
            on_change=self._refresh_leader_labels,
        )
        self.leader_local_test_box = card(host, self._tx("party_ui_local_test", "로컬 연결 테스트"))
        lay.addWidget(self.leader_local_test_box)
        local_lay = self.leader_local_test_box.layout()
        assert isinstance(local_lay, QVBoxLayout)
        local_hint = QLabel(
            self._tx(
                "party_ui_local_hint",
                "파티장 봇을 먼저 시작하세요. 이 PC에서 localhost로 확인한 뒤 "
                "LAN IP로 확인합니다.",
            )
        )
        local_hint.setWordWrap(True)
        local_lay.addWidget(local_hint)
        local_row = QHBoxLayout()
        self.ws_local_btn = QPushButton(self._tx("party_ui_test_localhost", "localhost 테스트"))
        self.ws_local_btn.clicked.connect(self._test_ws_localhost)
        local_row.addWidget(self.ws_local_btn)
        self.ws_lan_btn = QPushButton(self._tx("party_ui_test_lan", "LAN IP 테스트"))
        self.ws_lan_btn.clicked.connect(self._test_ws_lan_self)
        local_row.addWidget(self.ws_lan_btn)
        self.ws_local_status = QLabel("")
        self.ws_local_status.setWordWrap(True)
        local_row.addWidget(self.ws_local_status, stretch=1)
        local_lay.addLayout(local_row)
        lay.addStretch(1)
        return host

    def _migrate_enabled_flag(self) -> None:
        """Older bags only had ``member_enabled``; promote it to the master switch."""
        party = self.bag.section("party") or {}
        if "enabled" in party:
            return
        legacy = bool(party.get("member_enabled", False))
        self.bag.set("party", "enabled", legacy)

    def _party_on(self) -> bool:
        return bool(self.bag.get_bool("party", "enabled", False))

    def use_party_mode(self) -> None:
        """Show the party screens. The switch stays off until a role is chosen."""
        self._refresh_enabled_state()

    def set_master_enabled(self, on: bool) -> None:
        """솔로봇 turns this off. Choosing 파티장 or 파티원 turns it on."""
        enabled = bool(on)
        if hasattr(self, "party_enable"):
            if self.party_enable.isChecked() == enabled:
                if self._party_on() != enabled:
                    self.bag.set("party", "enabled", enabled)
                    self._on_party_enabled_changed()
                return
            self.party_enable.setChecked(enabled)
            return
        self.bag.set("party", "enabled", enabled)
        self._on_party_enabled_changed()

    def _sync_member_enabled_flag(self) -> None:
        """Runtime member-follow flag follows master + role (leader never follows)."""
        on = self._party_on() and self._role() == "member"
        self.bag.set("party", "member_enabled", on)

    def _add_role_combo(self, layout: QVBoxLayout) -> QComboBox:
        row = QHBoxLayout()
        combo = QComboBox()
        combo.blockSignals(True)
        combo.addItem(self.t.get("party_role_member", "Party member"), "member")
        combo.addItem(self.t.get("party_role_leader", "Party leader"), "leader")
        combo.blockSignals(False)
        row.addWidget(combo)
        row.addStretch(1)
        layout.addLayout(row)
        return combo

    def _build_roster(self, layout: QVBoxLayout) -> None:
        box = card(layout.parentWidget(), self._tx("party_ui_roster_title", "파티 관리"))
        layout.addWidget(box)
        box_lay = box.layout()
        assert isinstance(box_lay, QVBoxLayout)

        form = QHBoxLayout()
        form.addWidget(QLabel(self._tx("party_ui_name", "이름")))
        self.roster_name = QLineEdit()
        self.roster_name.returnPressed.connect(self._add_roster_row)
        form.addWidget(self.roster_name, stretch=1)
        form.addWidget(QLabel(self._tx("party_ui_role", "역할")))
        self.roster_role = QComboBox()
        for role in _ROSTER_ROLES:
            self.roster_role.addItem(self._roster_role_label(role), role)
        # Default seat for new members is mage.
        mage_idx = self.roster_role.findData("mage")
        self.roster_role.setCurrentIndex(max(0, mage_idx))
        form.addWidget(self.roster_role)
        form.addWidget(QLabel(self._tx("party_ui_loot_col", "루팅")))
        self.roster_loot = QComboBox()
        self.roster_loot.addItem(self._tx("party_ui_loot_none", "없음"), "none")
        self.roster_loot.addItem(self._tx("party_ui_loot_owner", "담당"), "responsible")
        form.addWidget(self.roster_loot)
        add_btn = QPushButton(self._tx("party_ui_add", "추가"))
        add_btn.clicked.connect(self._add_roster_row)
        form.addWidget(add_btn)
        remove_btn = QPushButton(self._tx("party_ui_delete", "삭제"))
        remove_btn.clicked.connect(self._remove_roster_row)
        form.addWidget(remove_btn)
        box_lay.addLayout(form)

        self.roster_table = QTableWidget(0, 7)
        self.roster_table.setHorizontalHeaderLabels(
            [
                self._tx("party_ui_col_select", "선택"),
                self._tx("party_ui_col_number", "번호"),
                self._tx("party_ui_name", "이름"),
                self._tx("party_ui_role", "역할"),
                self._tx("party_ui_loot_col", "루팅"),
                self._tx("party_ui_col_use", "사용"),
                self._tx("party_ui_col_wait", "대기"),
            ]
        )
        self.roster_table.itemChanged.connect(self._on_roster_flag)
        self.roster_table.verticalHeader().setVisible(False)
        self.roster_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.roster_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.roster_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.roster_table.setItemDelegateForColumn(
            3, _RosterChoiceDelegate(self._roster_role_choices, self.roster_table)
        )
        self.roster_table.setItemDelegateForColumn(
            4, _RosterChoiceDelegate(self._roster_loot_choices, self.roster_table)
        )
        self.roster_table.setMinimumHeight(160)
        configure_table_fill(
            self.roster_table,
            2,
            fixed={0: 34, 1: 45, 3: 100, 4: 100, 5: 55, 6: 55},
        )
        box_lay.addWidget(self.roster_table)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.roster_invite_btn = QPushButton(self._tx("party_ui_invite", "파티 초대"))
        self.roster_invite_btn.clicked.connect(self._invite_selected)
        self.roster_kick_btn = QPushButton(self._tx("party_ui_kick", "파티 추방"))
        self.roster_kick_btn.clicked.connect(self._kick_selected)
        actions.addWidget(self.roster_invite_btn)
        actions.addWidget(self.roster_kick_btn)
        actions.addStretch(1)
        box_lay.addLayout(actions)

        self.roster_result = QTableWidget(0, 5)
        self.roster_result.setHorizontalHeaderLabels(
            [
                self._tx("party_ui_name", "이름"),
                self._tx("party_ui_col_job", "작업"),
                self._tx("party_ui_col_status", "상태"),
                self._tx("party_ui_col_result", "결과"),
                self._tx("party_ui_col_reason", "사유"),
            ]
        )
        self.roster_result.verticalHeader().setVisible(False)
        self.roster_result.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.roster_result.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.roster_result.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.roster_result.setMinimumHeight(96)
        configure_table_fill(
            self.roster_result, 0, fixed={1: 72, 2: 110, 3: 72, 4: 180}
        )
        box_lay.addWidget(self.roster_result)
        self._fill_roster_table()

    def _roster_role_choices(self) -> list[tuple[str, str]]:
        return [(role, self._roster_role_label(role)) for role in _ROSTER_ROLES]

    def _roster_loot_choices(self) -> list[tuple[str, str]]:
        return [(loot, self._roster_loot_label(loot)) for loot in _LOOT_ROLES]

    def _roster_role_label(self, role: str) -> str:
        return {
            "member": self._tx("party_ui_seat_member", "파티원"),
            "mage": self._tx("party_ui_seat_mage", "마법사"),
            "shopkeeper": self._tx("party_ui_seat_shop", "상점"),
        }.get(role, self._tx("party_ui_seat_mage", "마법사"))

    def _roster_loot_label(self, loot: str) -> str:
        if loot == "responsible":
            return self._tx("party_ui_loot_owner", "담당")
        return self._tx("party_ui_loot_none", "없음")

    def _roster_rows(self) -> list[dict[str, str]]:
        return normalize_party_roster(self.bag.get("party", "roster", []))

    def _store_roster(self, rows: list[dict[str, str]]) -> None:
        self.bag.set("party", "roster", normalize_party_roster(rows))
        self._refresh_successor_choices()
        self._refresh_party_heal()

    def _successor_candidates(self) -> list[str]:
        leader = self._local_character_name_text().casefold()
        names: list[str] = []
        seen: set[str] = set()
        for row in self._roster_rows():
            name = str(row.get("name") or "").strip()
            key = name.casefold()
            if not name or key in seen or (leader and key == leader):
                continue
            seen.add(key)
            names.append(name)
        return names

    def _refresh_successor_choices(self) -> None:
        combo = getattr(self, "succession_combo", None)
        if not isinstance(combo, QComboBox):
            return
        saved = str(self.bag.get_str("party", "successor_name", "") or "").strip()
        names = self._successor_candidates()
        valid = ""
        for name in names:
            if name.casefold() == saved.casefold():
                valid = name
                break
        if saved and not valid:
            self.bag.set("party", "successor_name", "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._tx("party_ui_successor_none", "선택 안 함"), "")
        for name in names:
            combo.addItem(name, name)
        index = combo.findData(valid)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self._refresh_succession_warning()

    def _on_successor_changed(self) -> None:
        combo = getattr(self, "succession_combo", None)
        if not isinstance(combo, QComboBox):
            return
        self.bag.set("party", "successor_name", str(combo.currentData() or ""))
        self._refresh_succession_warning()

    def _refresh_succession_warning(self) -> None:
        label = getattr(self, "succession_warning", None)
        if label is None:
            return
        enabled = self.bag.get_bool("party", "succession_enabled", False)
        name = str(self.bag.get_str("party", "successor_name", "") or "").strip()
        known = {item.casefold() for item in self._successor_candidates()}
        label.setVisible(bool(enabled and (not name or name.casefold() not in known)))

    def _succession_state_label(self, code: str) -> str:
        labels = {
            "wait": ("party_ui_succession_wait", "인계 대기"),
            "running": ("party_ui_succession_running", "인계 진행 중"),
            "ok": ("party_ui_succession_ok", "인계 성공"),
            "fail": ("party_ui_succession_fail", "인계 실패"),
        }.get(str(code or "").strip())
        if labels is None:
            return self.t.get("value_empty", "—")
        return self._tx(labels[0], labels[1])

    def _show_succession_result(self, code: str, reason: str) -> None:
        self._succession_shown = (str(code or ""), str(reason or ""))
        state = getattr(self, "succession_state", None)
        reason_label = getattr(self, "succession_reason", None)
        if state is not None:
            state.setText(
                self._tx("party_ui_succession_state", "인계 상태")
                + ": "
                + self._succession_state_label(code)
            )
        if reason_label is not None:
            text = str(reason or "").strip()
            reason_label.setText(
                self._tx("party_ui_fail_reason", "실패 사유")
                + ": "
                + (text if code == "fail" and text else self.t.get("value_empty", "—"))
            )

    def refresh_status_lines(self) -> None:
        """Rewrite composed status lines in the current language."""
        code, reason = getattr(self, "_succession_shown", ("", ""))
        self._show_succession_result(code, reason)
        code, reason = getattr(self, "_absence_shown", ("", ""))
        self._show_absence_result(code, reason)

    def _absence_action(self) -> str:
        mode = str(self.bag.get_str("party", "absence_action", "hunt") or "hunt")
        return mode if mode in _ABSENCE_ACTIONS else "hunt"

    def _on_absence_action(self, mode: str, checked: bool) -> None:
        if not checked:
            return
        if mode not in _ABSENCE_ACTIONS:
            mode = "hunt"
        self.bag.set("party", "absence_action", mode)
        self._fill_absence_places()

    def _place_key(self, map_id: str, area: dict) -> str:
        name = str(area.get("name") or "").strip()
        shape = str(area.get("shape") or "")
        if not map_id or not name:
            return ""
        if shape == "point":
            ident = f"{area.get('x')},{area.get('y')}"
        elif shape == "area":
            ident = f"{area.get('x0')},{area.get('y0')},{area.get('x1')},{area.get('y1')}"
        else:
            return ""
        return f"{map_id}|{shape}|{name}|{ident}"

    def _party_places(self) -> list[tuple[str, str]]:
        raw = self.bag.get("party", "routine", None)
        if not isinstance(raw, list):
            return []
        from settings.party_routine import normalize_party_routine

        places: list[tuple[str, str]] = []
        seen: set[str] = set()
        for row in normalize_party_routine(raw):
            map_id = str(row.get("map_id") or "")
            for area in row.get("areas") or []:
                if not isinstance(area, dict):
                    continue
                key = self._place_key(map_id, area)
                if not key or key in seen:
                    continue
                seen.add(key)
                label = f"{area.get('name')} ({map_id})"
                places.append((key, label))
        return places

    def _fill_absence_places(self) -> None:
        combo = getattr(self, "absence_place", None)
        if not isinstance(combo, QComboBox):
            return
        places = self._party_places()
        saved = str(self.bag.get_str("party", "absence_place", "") or "")
        valid = saved if any(key == saved for key, _label in places) else ""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._tx("party_ui_successor_none", "선택 안 함"), "")
        for key, label in places:
            combo.addItem(label, key)
        index = combo.findData(valid)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self._apply_absence_place_enabled(places)

    def _apply_absence_place_enabled(self, places: list[tuple[str, str]] | None = None) -> None:
        combo = getattr(self, "absence_place", None)
        pending = getattr(self, "absence_place_pending", None)
        warning = getattr(self, "absence_place_warning", None)
        if combo is None or pending is None or warning is None:
            return
        if places is None:
            places = self._party_places()
        move = self._absence_action() == "move"
        combo.setEnabled(bool(move and places))
        pending.setVisible(bool(move and not places))
        saved = str(self.bag.get_str("party", "absence_place", "") or "")
        known = any(key == saved for key, _label in places)
        warning.setVisible(bool(move and saved and not known and places))

    def _on_absence_place(self) -> None:
        combo = getattr(self, "absence_place", None)
        if not isinstance(combo, QComboBox):
            return
        chosen = str(combo.currentData() or "")
        if chosen and chosen not in {key for key, _label in self._party_places()}:
            return
        self.bag.set("party", "absence_place", chosen)
        self._apply_absence_place_enabled()

    def _absence_state_label(self, code: str) -> str:
        labels = {
            "hunt": ("party_ui_absence_state_hunt", "사냥 계속 중"),
            "hold": ("party_ui_absence_state_hold", "제자리 대기 중"),
            "move": ("party_ui_absence_state_move", "지정 장소 이동 중"),
            "fail": ("party_ui_absence_state_fail", "행동 전환 실패"),
        }.get(str(code or "").strip())
        if labels is None:
            return self.t.get("value_empty", "—")
        return self._tx(labels[0], labels[1])

    def _show_absence_result(self, code: str, reason: str) -> None:
        self._absence_shown = (str(code or ""), str(reason or ""))
        state = getattr(self, "absence_state", None)
        reason_label = getattr(self, "absence_reason", None)
        if state is not None:
            state.setText(
                self._tx("party_ui_absence_state", "행동 상태")
                + ": "
                + self._absence_state_label(code)
            )
        if reason_label is not None:
            text = str(reason or "").strip()
            reason_label.setText(
                self._tx("party_ui_fail_reason", "실패 사유")
                + ": "
                + (text if code == "fail" and text else self.t.get("value_empty", "—"))
            )

    def _sync_leader_handover_forms(self) -> None:
        box = getattr(self, "succession_enable", None)
        if isinstance(box, QCheckBox):
            box.blockSignals(True)
            box.setChecked(self.bag.get_bool("party", "succession_enabled", False))
            box.blockSignals(False)
        buttons = getattr(self, "absence_buttons", None)
        if isinstance(buttons, dict):
            mode = self._absence_action()
            for key, button in buttons.items():
                button.blockSignals(True)
                button.setChecked(key == mode)
                button.blockSignals(False)
        self._refresh_successor_choices()
        self._fill_absence_places()

    def _fill_roster_table(self) -> None:
        table = getattr(self, "roster_table", None)
        if not isinstance(table, QTableWidget):
            return
        rows = self._roster_rows()
        table.blockSignals(True)
        table.setRowCount(len(rows))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        check_flags = flags | Qt.ItemFlag.ItemIsUserCheckable
        for index, row in enumerate(rows):
            number = QTableWidgetItem(str(index + 1))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QTableWidgetItem(row["name"])
            role = str(row.get("role") or "mage")
            role_item = QTableWidgetItem(self._roster_role_label(role))
            role_item.setData(Qt.ItemDataRole.UserRole, role)
            loot = str(row.get("loot") or "none")
            loot_item = QTableWidgetItem(self._roster_loot_label(loot))
            loot_item.setData(Qt.ItemDataRole.UserRole, loot)
            enabled = QTableWidgetItem("")
            enabled.setFlags(check_flags)
            enabled.setCheckState(
                Qt.CheckState.Checked
                if str(row.get("enabled", "1")) != "0"
                else Qt.CheckState.Unchecked
            )
            required = QTableWidgetItem("")
            required.setFlags(check_flags)
            required.setCheckState(
                Qt.CheckState.Checked
                if str(row.get("required", "1")) != "0"
                else Qt.CheckState.Unchecked
            )
            number.setFlags(flags)
            edit_flags = flags | Qt.ItemFlag.ItemIsEditable
            for item in (name, role_item, loot_item):
                item.setFlags(edit_flags)
            table.setCellWidget(index, 0, self._roster_select_box())
            table.setItem(index, 1, number)
            table.setItem(index, 2, name)
            table.setItem(index, 3, role_item)
            table.setItem(index, 4, loot_item)
            table.setItem(index, 5, enabled)
            table.setItem(index, 6, required)
        table.blockSignals(False)

    def _roster_select_box(self) -> QWidget:
        box = QCheckBox()
        box.setText("")
        host = QWidget()
        host.setObjectName("cellHost")
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(box)
        return host

    def _roster_select_box_at(self, row: int) -> QCheckBox | None:
        table = getattr(self, "roster_table", None)
        if not isinstance(table, QTableWidget):
            return None
        host = table.cellWidget(row, 0)
        if host is None:
            return None
        box = host.findChild(QCheckBox)
        return box if isinstance(box, QCheckBox) else None

    def _checked_roster_names(self) -> list[str]:
        table = getattr(self, "roster_table", None)
        if not isinstance(table, QTableWidget):
            return []
        names: list[str] = []
        for row in range(table.rowCount()):
            box = self._roster_select_box_at(row)
            if box is None or not box.isChecked():
                continue
            item = table.item(row, 2)
            name = str(item.text() if item is not None else "").strip()
            if name:
                names.append(name)
        return names

    def _party_controller(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None
        for widget in app.allWidgets():
            bridge = getattr(widget, "bridge", None)
            controller = getattr(bridge, "controller", None) if bridge is not None else None
            if controller is not None and hasattr(controller, "submit_party_chat"):
                return controller
        return None

    def _party_chat_submit(self):
        controller = self._party_controller()
        submit = getattr(controller, "submit_party_chat", None)
        return submit if callable(submit) else None

    def _party_kick_submit(self):
        """Existing expel entry point only. There is no invented kick call."""
        controller = self._party_controller()
        submit = getattr(controller, "submit_party_kick", None)
        return submit if callable(submit) else None

    def _confirmed_party_names(self) -> set[str]:
        controller = self._party_controller()
        snap_fn = getattr(controller, "party_monitor_snapshot", None)
        if not callable(snap_fn):
            return set()
        try:
            snap = snap_fn()
        except Exception:
            return set()
        session = snap.get("session") if isinstance(snap, dict) else None
        roster = session.get("roster") if isinstance(session, dict) else None
        if not isinstance(roster, list):
            return set()
        return {
            str(row.get("name") or "").strip().casefold()
            for row in roster
            if isinstance(row, dict)
            and row.get("in_party") is True
            and str(row.get("name") or "").strip()
        }

    def _invite_selected(self) -> list[str]:
        names = self._checked_roster_names()
        if not names:
            return []
        submit = self._party_chat_submit()
        if submit is None:
            return []
        for name in names:
            reply = str(submit("invite", name) or "")
            self._append_party_action_result(name, "invite", reply)
        return list(names)

    def _kick_targets(self) -> list[str]:
        confirmed = self._confirmed_party_names()
        return [
            name
            for name in self._checked_roster_names()
            if name.casefold() in confirmed
        ]

    def _kick_selected(self) -> list[str]:
        targets = self._kick_targets()
        if not targets:
            return []
        submit = self._party_kick_submit()
        if submit is None:
            return []
        for name in targets:
            reply = str(submit(name) or "")
            self._append_party_action_result(name, "kick", reply)
        return list(targets)

    def _append_party_action_result(self, name: str, action: str, reply: str) -> None:
        table = getattr(self, "roster_result", None)
        if not isinstance(table, QTableWidget):
            return
        status, outcome, reason = self._party_action_fields(action, reply)
        shown = (
            self._tx("party_ui_job_invite", "초대")
            if action == "invite"
            else self._tx("party_ui_job_kick", "추방")
            if action == "kick"
            else action
        )
        row = table.rowCount()
        table.insertRow(row)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for column, text in enumerate((name, shown, status, outcome, reason)):
            item = QTableWidgetItem(text)
            item.setFlags(flags)
            table.setItem(row, column, item)
        table.scrollToBottom()

    def _party_action_fields(self, action: str, reply: str) -> tuple[str, str, str]:
        """Show the engine reply. Queued is not success, and no reason is invented."""
        text = str(reply or "").strip()
        lowered = text.casefold()
        invite = action == "invite"
        if lowered.startswith("queued"):
            status = (
                self._tx("party_ui_invite_busy", "초대 진행 중")
                if invite
                else self._tx("party_ui_busy", "진행 중")
            )
            extra = "" if lowered == "queued" else text
            return status, "", extra
        if lowered.startswith("rejected") or lowered.startswith("enter"):
            status = (
                self._tx("party_ui_invite_fail", "초대 실패")
                if invite
                else self._tx("party_ui_kick_fail", "추방 실패")
            )
            return status, self._tx("party_ui_result_fail", "실패"), text
        return text, "", ""

    def _on_roster_flag(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_roster_edit_guard", False):
            return
        column = item.column()
        if column == 2:
            self._commit_roster_name(item)
            return
        if column == 3:
            self._commit_roster_choice(item, "role", _ROSTER_ROLES, "mage")
            return
        if column == 4:
            self._commit_roster_choice(item, "loot", _LOOT_ROLES, "none")
            return
        if column not in (5, 6):
            return
        rows = self._roster_rows()
        index = item.row()
        if index < 0 or index >= len(rows):
            return
        key = "enabled" if column == 5 else "required"
        rows[index][key] = (
            "1" if item.checkState() == Qt.CheckState.Checked else "0"
        )
        self._store_roster(rows)

    def _restore_roster_text(self, item: QTableWidgetItem, text: str) -> None:
        table = getattr(self, "roster_table", None)
        self._roster_edit_guard = True
        if isinstance(table, QTableWidget):
            table.blockSignals(True)
        item.setText(text)
        if isinstance(table, QTableWidget):
            table.blockSignals(False)
        self._roster_edit_guard = False

    def _commit_roster_name(self, item: QTableWidgetItem) -> None:
        rows = self._roster_rows()
        index = item.row()
        if index < 0 or index >= len(rows):
            return
        old = str(rows[index].get("name") or "")
        new = str(item.text() or "").strip()
        if not new:
            self._restore_roster_text(item, old)
            return
        if any(
            other != index and str(row.get("name") or "").casefold() == new.casefold()
            for other, row in enumerate(rows)
        ):
            self.on_log(
                self.t.get(
                    "party_roster_duplicate",
                    "That name is already in the party list.",
                )
            )
            self._restore_roster_text(item, old)
            return
        if new == old:
            if item.text() != old:
                self._restore_roster_text(item, old)
            return
        self._rename_roster_links(old, new)
        rows[index]["name"] = new
        if item.text() != new:
            self._restore_roster_text(item, new)
        self._store_roster(rows)

    def _rename_roster_links(self, old: str, new: str) -> None:
        """Point existing name keys at the renamed character. No new settings."""
        saved = str(self.bag.get_str("party", "successor_name", "") or "").strip()
        if saved and saved.casefold() == old.casefold():
            self.bag.set("party", "successor_name", new)
        raw = self.bag.get("party", "heal_targets", {})
        if not isinstance(raw, dict):
            return
        match = next(
            (
                key
                for key in raw
                if str(key).strip().casefold() == old.casefold()
            ),
            None,
        )
        if match is None or str(match) == new:
            return
        updated = dict(raw)
        payload = updated.pop(match)
        if new not in updated:
            updated[new] = payload
        self.bag.set("party", "heal_targets", updated)

    def _commit_roster_choice(
        self,
        item: QTableWidgetItem,
        field: str,
        allowed: tuple[str, ...],
        default: str,
    ) -> None:
        rows = self._roster_rows()
        index = item.row()
        if index < 0 or index >= len(rows):
            return
        value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip().lower()
        if value not in allowed:
            value = str(rows[index].get(field) or default)
        label = (
            self._roster_role_label(value)
            if field == "role"
            else self._roster_loot_label(value)
        )
        if item.text() != label:
            self._restore_roster_text(item, label)
        if str(rows[index].get(field) or "") == value:
            return
        rows[index][field] = value
        self._store_roster(rows)

    def _add_roster_row(self) -> None:
        name = str(self.roster_name.text() or "").strip()
        if not name:
            self.on_log(
                self.t.get("party_roster_need_name", "Enter a character name.")
            )
            return
        rows = self._roster_rows()
        if any(row["name"].casefold() == name.casefold() for row in rows):
            self.on_log(
                self.t.get(
                    "party_roster_duplicate",
                    "That name is already in the party list.",
                )
            )
            return
        role = str(self.roster_role.currentData() or "mage")
        if role not in _ROSTER_ROLES:
            role = "mage"
        loot = str(self.roster_loot.currentData() or "none")
        if loot not in _LOOT_ROLES:
            loot = "none"
        rows.append({
            "name": name,
            "role": role,
            "loot": loot,
            "enabled": "1",
            "required": "1",
        })
        self._store_roster(rows)
        self.roster_name.clear()
        self._fill_roster_table()
        if self.roster_table.rowCount():
            self.roster_table.selectRow(self.roster_table.rowCount() - 1)

    def _remove_roster_row(self) -> None:
        row = self.roster_table.currentRow()
        if row < 0:
            return
        rows = self._roster_rows()
        if row >= len(rows):
            return
        del rows[row]
        self._store_roster(rows)
        self._fill_roster_table()
        if self.roster_table.rowCount():
            self.roster_table.selectRow(min(row, self.roster_table.rowCount() - 1))

    def _address_row(self, layout: QVBoxLayout, label: str) -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        field = QLineEdit()
        field.setReadOnly(True)
        field.setMinimumWidth(180)
        row.addWidget(field, stretch=1)
        layout.addLayout(row)
        return field

    def _on_leader_host_changed(self, text: str) -> None:
        self.bag.set("party", "leader_host", str(text or "").strip())
        self._refresh_member_summary()

    def set_motion_text(self, text: str) -> None:
        """Show the existing program state. Does not read follow distance."""
        label = getattr(self, "follow_motion", None)
        if isinstance(label, QLabel):
            label.setText(self._tx("party_ui_motion", "이동 상태: {text}").format(text=text))

    def _refresh_member_summary(self) -> None:
        host = str(self.bag.get_str("party", "leader_host", "") or "").strip()
        port = self._ws_port() if hasattr(self, "member_ws_port") else 8765
        shown = host or self._tx("party_ui_blank", "미입력")
        info = self._tx(
            "party_ui_leader_info", "파티장 정보: {shown} · 포트 {port}"
        ).format(shown=shown, port=port)
        if hasattr(self, "leader_info"):
            self.leader_info.setText(info)
        if hasattr(self, "status_leader"):
            self.status_leader.setText(
                self._tx(
                    "party_ui_leader_state", "파티장 상태: {shown} · 포트 {port}"
                ).format(shown=shown, port=port)
            )
        if hasattr(self, "status_connection") and hasattr(self, "ws_status"):
            self.status_connection.setText(self.ws_status.text())
        self._refresh_personal_summary()

    def _refresh_personal_summary(self) -> None:
        label = getattr(self, "personal_summary", None)
        if not isinstance(label, QLabel):
            return
        mode = (
            self._tx("party_ui_assist_follow", "추종")
            if self._farm_mode() == "party"
            else self._tx("party_ui_assist_own", "주변 대상 단독 공격")
        )
        label.setText(
            self._tx(
                "party_ui_personal_now",
                "현재 개인 설정 · 따라가기 {follow}칸, 정지 {stop}칸, "
                "어시스트 {assist}칸, 공격 {mode}",
            ).format(
                follow=self.bag.get_int("party", "follow_tiles", 8),
                stop=self.bag.get_int("party", "stop_tiles", 2),
                assist=self.bag.get_int("party", "assist_leash_tiles", 10),
                mode=mode,
            )
        )

    @staticmethod
    def _ensure_engine_path() -> None:
        """So ``websocket.*`` imports work before the member bot is Started."""
        import sys
        from pathlib import Path

        here = Path(__file__).resolve()
        # UI/ui_qt/editors/party_tab.py → repo root → Engine
        root = here.parents[3]
        engine = root / "Engine"
        for path in (engine, root):
            text = str(path)
            if path.is_dir() and text not in sys.path:
                sys.path.insert(0, text)

    def _ws_port(self) -> int:
        try:
            return max(1, min(65535, int(self.bag.get_int("party", "ws_port", 8765) or 8765)))
        except (TypeError, ValueError):
            return 8765

    def _begin_ws_probe(self, host: str, *, status_label: QLabel, buttons: list) -> None:
        """One-shot client probe against ``host:ws_port`` (leader must be listening)."""
        if self._ws_testing:
            return
        host = str(host or "").strip()
        port = self._ws_port()
        if not host:
            msg = self.t.get(
                "party_ws_need_host",
                "Enter the leader IP first.",
            )
            status_label.setText(msg)
            self.on_log(msg)
            return
        self._ws_testing = True
        self._ws_status_target = status_label
        for btn in buttons:
            btn.setEnabled(False)
        status_label.setText(self.t.get("party_ws_testing", "Testing…"))

        def work() -> None:
            try:
                self._ensure_engine_path()
                from websocket.probe import probe_party_leader

                uri = probe_party_leader(host, port, timeout=3.0)
                self._ws_bridge.finished.emit(
                    True,
                    self.t.get("party_ws_ok", "Connected to {uri}").format(uri=uri),
                )
            except Exception as exc:
                self._ws_bridge.finished.emit(
                    False,
                    self.t.get(
                        "party_ws_fail",
                        "Connection failed: {error}",
                    ).format(error=exc),
                )

        threading.Thread(
            target=work,
            name="party-ws-test",
            daemon=True,
        ).start()

    def _test_ws_connection(self) -> None:
        """Member page: probe the configured leader host (no member Start needed)."""
        host = str(self.bag.get_str("party", "leader_host", "") or "").strip()
        buttons = [self.ws_test_btn]
        if hasattr(self, "ws_local_btn"):
            buttons.extend([self.ws_local_btn, self.ws_lan_btn])
        self._begin_ws_probe(host, status_label=self.ws_status, buttons=buttons)

    def _test_ws_localhost(self) -> None:
        """Leader page: same-PC loopback against the current WebSocket server."""
        buttons = [self.ws_local_btn, self.ws_lan_btn]
        if hasattr(self, "ws_test_btn"):
            buttons.append(self.ws_test_btn)
        self._begin_ws_probe(
            "127.0.0.1",
            status_label=self.ws_local_status,
            buttons=buttons,
        )

    def _test_ws_lan_self(self) -> None:
        """Leader page: same PC via advertised LAN IP (before other LAN machines)."""
        lan = self._lan_ip_text()
        if not lan or lan in ("127.0.0.1", "0.0.0.0"):
            msg = self.t.get(
                "party_ws_need_lan",
                "No LAN IP detected. Check the network adapter, then retry.",
            )
            self.ws_local_status.setText(msg)
            self.on_log(msg)
            return
        buttons = [self.ws_local_btn, self.ws_lan_btn]
        if hasattr(self, "ws_test_btn"):
            buttons.append(self.ws_test_btn)
        self._begin_ws_probe(
            lan,
            status_label=self.ws_local_status,
            buttons=buttons,
        )

    def _on_ws_test_finished(self, ok: bool, detail: str) -> None:
        self._ws_testing = False
        short = (
            self.t.get("party_ws_ok_short", "OK")
            if ok
            else self.t.get("party_ws_fail_short", "Failed")
        )
        target = getattr(self, "_ws_status_target", None)
        if isinstance(target, QLabel):
            target.setText(short)
        elif self._role() == "leader" and hasattr(self, "ws_local_status"):
            self.ws_local_status.setText(short)
        elif hasattr(self, "ws_status"):
            self.ws_status.setText(short)
        self._refresh_enabled_state()
        self._refresh_member_summary()
        self.on_log(str(detail or ""))

    def _lan_ip_text(self) -> str:
        """Prefer the LAN NIC, not the VPN default-route address."""
        try:
            self._ensure_engine_path()
            from websocket.netinfo import local_ipv4

            self._lan_ip = local_ipv4()
        except Exception:
            if not self._lan_ip:
                self._lan_ip = "127.0.0.1"
        return self._lan_ip

    def _refresh_leader_labels(self) -> None:
        if getattr(self, "ip_edit", None) is not None:
            self.ip_edit.setText(self._lan_ip_text())

    def _clamp_follow_stop(self) -> None:
        follow = self.bag.get_int("party", "follow_tiles", 8)
        stop = self.bag.get_int("party", "stop_tiles", 2)
        if stop > follow:
            self.bag.set("party", "stop_tiles", follow)
            if hasattr(self, "party_stop_tiles"):
                self.party_stop_tiles.blockSignals(True)
                self.party_stop_tiles.setValue(follow)
                self.party_stop_tiles.blockSignals(False)

    def _farm_mode(self) -> str:
        mode = str(self.bag.get_str("party", "farm_mode", "party") or "party")
        return mode if mode in _FARM_MODES else "party"

    def _role(self) -> str:
        role = str(self.bag.get_str("party", "role", "member") or "member")
        return role if role in _PARTY_ROLES else "member"

    def _select_farm_mode(self) -> None:
        self.party_farm_mode.blockSignals(True)
        idx = self.party_farm_mode.findData(self._farm_mode())
        self.party_farm_mode.setCurrentIndex(max(0, idx))
        self.party_farm_mode.blockSignals(False)
        self._select_attack_target()

    def _on_farm_mode_changed(self) -> None:
        mode = str(self.party_farm_mode.currentData() or "party")
        if mode not in _FARM_MODES:
            mode = "party"
        self.bag.set("party", "farm_mode", mode)
        self._select_attack_target()
        self._refresh_personal_summary()
        self._on_loot_mode_changed()

    def _on_loot_pickup_changed(self) -> None:
        if not hasattr(self, "party_loot_pickup"):
            return
        mode = str(self.party_loot_pickup.currentData() or "all")
        if mode not in ("all", "adena"):
            mode = "all"
        self.bag.set("party", "loot_pickup", mode)

    def _on_loot_role_changed(self) -> None:
        data = self.party_loot_role.currentData()
        role = str(data or "none")
        if role not in _LOOT_ROLES:
            role = "none"
        self.bag.set("party", "loot_role", role)

    def _on_role_combo_changed(self) -> None:
        combo = self.sender()
        if not isinstance(combo, QComboBox):
            return
        role = str(combo.currentData() or "member")
        if role not in _PARTY_ROLES:
            role = "member"
        self._apply_role(role)

    def _apply_role(self, role: str) -> None:
        if role not in _PARTY_ROLES:
            role = "member"
        self.bag.set("party", "role", role)
        self._sync_member_enabled_flag()
        if role == "leader":
            self._refresh_leader_labels()
        self._refresh_member_summary()
        self._refresh_enabled_state()

    def _on_loot_mode_changed(self) -> None:
        on = self._party_on() and self._role() == "leader"
        random_on = self.bag.get_bool("party", "random_loot", False)
        if hasattr(self, "party_random_loot"):
            self.party_random_loot.setEnabled(on)
        if hasattr(self, "roster_loot"):
            self.roster_loot.setEnabled(on and not random_on)

    def _on_party_enabled_changed(self) -> None:
        self._sync_member_enabled_flag()
        self.bag.set("party", "leader_name", "")
        self._refresh_enabled_state()

    def _refresh_enabled_state(self) -> None:
        """Enable party checkbox stays on; everything else follows the master switch."""
        on = self._party_on()
        gated = []
        gated.extend(getattr(self, "member_sections", {}).values())
        for key, widget in getattr(self, "leader_sections", {}).items():
            if key == "map":
                continue
            gated.append(widget)
        for widget in gated:
            widget.setEnabled(on)
        for button in getattr(self, "member_attack_buttons", {}).values():
            button.setEnabled(False)
        if hasattr(self, "party_farm_mode"):
            self.party_farm_mode.setEnabled(False)
        # Connection probes stay usable without requiring Start on the probing side.
        # Leader local tests still need the leader bot already listening.
        busy = bool(self._ws_testing)
        if hasattr(self, "ws_test_btn"):
            self.ws_test_btn.setEnabled(
                bool(on and self._role() == "member" and not busy)
            )
        can_local = bool(on and self._role() == "leader" and not busy)
        if hasattr(self, "ws_local_btn"):
            self.ws_local_btn.setEnabled(can_local)
        if hasattr(self, "ws_lan_btn"):
            self.ws_lan_btn.setEnabled(can_local)
        if on and self._role() == "leader":
            self._on_loot_mode_changed()

    def reload_from_bag(self) -> None:
        if not hasattr(self, "party_enable"):
            return
        self._migrate_enabled_flag()
        self.party_enable.blockSignals(True)
        self.party_enable.setChecked(self._party_on())
        self.party_enable.blockSignals(False)
        self.bag.set("party", "leader_name", "")
        party = self.bag.section("party") or {}
        if "follow_tiles" not in party:
            legacy = self.bag.get_int("party", "follow_start_tiles", 8)
            self.bag.set("party", "follow_tiles", max(1, int(legacy)))
        if "stop_tiles" not in party:
            legacy_stop = self.bag.get_int("party", "follow_stop_tiles", 2)
            self.bag.set("party", "stop_tiles", max(0, int(legacy_stop)))
        self.party_follow_tiles.blockSignals(True)
        self.party_follow_tiles.setValue(
            self.bag.get_int("party", "follow_tiles", 8)
        )
        self.party_follow_tiles.blockSignals(False)
        self.party_stop_tiles.blockSignals(True)
        self.party_stop_tiles.setValue(
            self.bag.get_int("party", "stop_tiles", 2)
        )
        self.party_stop_tiles.blockSignals(False)
        self._clamp_follow_stop()
        self.party_assist_leash.blockSignals(True)
        self.party_assist_leash.setValue(
            self.bag.get_int("party", "assist_leash_tiles", 10)
        )
        self.party_assist_leash.blockSignals(False)
        self.party_random_loot.blockSignals(True)
        self.party_random_loot.setChecked(
            self.bag.get_bool("party", "random_loot", False)
        )
        self.party_random_loot.blockSignals(False)
        role = str(self.bag.get_str("party", "loot_role", "none") or "none")
        if role not in _LOOT_ROLES:
            role = "none"
        self.party_loot_role.blockSignals(True)
        idx = self.party_loot_role.findData(role)
        self.party_loot_role.setCurrentIndex(max(0, idx))
        self.party_loot_role.blockSignals(False)
        if hasattr(self, "party_loot_pickup"):
            pickup = str(self.bag.get_str("party", "loot_pickup", "all") or "all")
            self.party_loot_pickup.blockSignals(True)
            self.party_loot_pickup.setCurrentIndex(0 if pickup != "adena" else 1)
            self.party_loot_pickup.blockSignals(False)
        if hasattr(self, "party_member_arrow_min"):
            self.party_member_arrow_min.blockSignals(True)
            self.party_member_arrow_min.setValue(
                self.bag.get_int("party", "member_arrow_min", 300)
            )
            self.party_member_arrow_min.blockSignals(False)
        if hasattr(self, "party_shopkeeper_arrow_min"):
            self.party_shopkeeper_arrow_min.blockSignals(True)
            self.party_shopkeeper_arrow_min.setValue(
                self.bag.get_int("party", "shopkeeper_arrow_min", 300)
            )
            self.party_shopkeeper_arrow_min.blockSignals(False)
        if hasattr(self, "party_member_arrow_give"):
            self.party_member_arrow_give.blockSignals(True)
            self.party_member_arrow_give.setValue(
                self.bag.get_int("party", "member_arrow_give", 100)
            )
            self.party_member_arrow_give.blockSignals(False)
        if hasattr(self, "party_shopkeeper_arrow_buy"):
            self.party_shopkeeper_arrow_buy.blockSignals(True)
            self.party_shopkeeper_arrow_buy.setValue(
                self.bag.get_int("party", "shopkeeper_arrow_buy", 200)
            )
            self.party_shopkeeper_arrow_buy.blockSignals(False)
        for attr, bag_key, default in (
            ("party_member_hp_min", "member_hp_min", 10),
            ("party_shopkeeper_hp_min", "shopkeeper_hp_min", 20),
            ("party_member_hp_give", "member_hp_give", 10),
            ("party_shopkeeper_hp_buy", "shopkeeper_hp_buy", 20),
            ("party_member_depoison_min", "member_depoison_min", 1),
            ("party_shopkeeper_depoison_min", "shopkeeper_depoison_min", 2),
            ("party_member_depoison_give", "member_depoison_give", 1),
            ("party_shopkeeper_depoison_buy", "shopkeeper_depoison_buy", 5),
            ("party_member_mp_min", "member_mp_min", 5),
            ("party_shopkeeper_mp_min", "shopkeeper_mp_min", 10),
            ("party_member_mp_give", "member_mp_give", 5),
            ("party_shopkeeper_mp_buy", "shopkeeper_mp_buy", 10),
        ):
            spin = getattr(self, attr, None)
            if spin is None:
                continue
            spin.blockSignals(True)
            spin.setValue(self.bag.get_int("party", bag_key, default))
            spin.blockSignals(False)
        for attr, bag_key, default in (
            ("party_member_heal_pct", "member_heal_pct", 70),
            ("party_member_potion_pct", "member_potion_pct", 50),
            ("party_mage_heal_pct", "mage_heal_pct", 80),
            ("party_retreat_pct", "retreat_pct", 30),
            ("party_tree_hp_to_mp_hp", "tree_hp_to_mp_hp", 85),
            ("party_tree_hp_to_mp_mp", "tree_hp_to_mp_mp", 80),
            ("party_tree_heal_hp", "tree_heal_hp", 40),
            ("party_tree_heal_mp", "tree_heal_mp", 80),
        ):
            spin = getattr(self, attr, None)
            if spin is None:
                continue
            spin.blockSignals(True)
            spin.setValue(self.bag.get_int("party", bag_key, default))
            spin.blockSignals(False)
        for attr, bag_key, default in (
            ("party_mother_tree", "mother_tree", True),
            ("party_talking_scroll", "talking_scroll", True),
            ("party_safe_zone", "safe_zone", True),
            ("party_tree_hp_to_mp", "tree_hp_to_mp", True),
            ("party_tree_heal", "tree_heal", True),
        ):
            box = getattr(self, attr, None)
            if box is None:
                continue
            box.blockSignals(True)
            box.setChecked(self.bag.get_bool("party", bag_key, default))
            box.blockSignals(False)
        if hasattr(self, "party_loot_weight_pct"):
            self.party_loot_weight_pct.blockSignals(True)
            self.party_loot_weight_pct.setValue(
                self.bag.get_int("party", "loot_weight_pct", 30)
            )
            self.party_loot_weight_pct.blockSignals(False)
        if hasattr(self, "party_ws_port"):
            self.party_ws_port.blockSignals(True)
            self.party_ws_port.setValue(self.bag.get_int("party", "ws_port", 8765))
            self.party_ws_port.blockSignals(False)
        if hasattr(self, "member_ws_port"):
            self.member_ws_port.blockSignals(True)
            self.member_ws_port.setValue(self.bag.get_int("party", "ws_port", 8765))
            self.member_ws_port.blockSignals(False)
        if hasattr(self, "leader_host"):
            self.leader_host.blockSignals(True)
            self.leader_host.setText(
                str(self.bag.get_str("party", "leader_host", "") or "")
            )
            self.leader_host.blockSignals(False)
        self._select_farm_mode()
        self._sync_leader_handover_forms()
        self._lan_ip = ""
        self._fill_roster_table()
        self._apply_role(self._role())
        if self.routine_panel is not None:
            self.routine_panel.load_from_bag()
        self._refresh_party_heal()

    def flush_routine(self) -> None:
        if self.routine_panel is not None:
            self.routine_panel._persist_routine()
