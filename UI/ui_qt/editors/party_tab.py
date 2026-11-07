"""Party tab — member follow/assist, or this PC as the party-socket leader."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from settings.profile import normalize_party_roster
from ui_qt.editors.form_helpers import add_check, add_spin_row, card, configure_table_fill
from ui_qt.editors.party_routine_panel import PartyRoutinePanel
from ui_qt.i18n_overlay import tx
from ui_qt.i18n_refresh import bind_tx_keys
from ui_qt.viewmodels.settings_bag import SettingsBag

_LOOT_ROLES = ("none", "responsible")
_FARM_MODES = ("party", "solo")
_PARTY_ROLES = ("member", "leader")
_ROSTER_ROLES = ("member", "mage", "shopkeeper")


class _WsTestBridge(QObject):
    """Marshal WebSocket probe results back onto the UI thread."""

    finished = Signal(bool, str)


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
            "personal": self._build_member_personal(),
            "status": self._build_member_status(),
        }
        self.leader_sections = {
            "manage": self._build_leader_manage(),
            "ops": self._build_leader_ops(),
            "map": self._build_leader_map(),
            "support": self._build_leader_support(),
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
        lay.addStretch(1)
        return host

    def _build_leader_ops(self) -> QWidget:
        host, lay = self._section()
        absent = card(host, self._tx("party_ui_absent_title", "파티장 부재 시 운영"))
        lay.addWidget(absent)
        absent_lay = absent.layout()
        assert isinstance(absent_lay, QVBoxLayout)
        absent_note = QLabel(
            self._tx(
                "party_ui_absent_note",
                "화면 구성만 되어 있습니다. 선택값은 저장되지 않고 실행되지도 않습니다.",
            )
        )
        absent_note.setWordWrap(True)
        absent_lay.addWidget(absent_note)
        absent_lay.addWidget(QLabel(self._tx("party_ui_absent_action", "파티장 부재 시 행동")))
        self.ops_absent_group = QButtonGroup(host)
        self.ops_absent_group.setExclusive(True)
        for key, fallback in (
            ("party_ui_keep_hunting", "계속 사냥"),
            ("party_ui_hold", "제자리 대기"),
            ("party_ui_move_spot", "지정 장소로 이동"),
        ):
            button = QRadioButton(self._tx(key, fallback))
            self.ops_absent_group.addButton(button)
            absent_lay.addWidget(button)
        self.ops_handover = QCheckBox(self._tx("party_ui_handover", "파티장 인계 사용"))
        absent_lay.addWidget(self.ops_handover)
        hand = QHBoxLayout()
        hand.addWidget(QLabel(self._tx("party_ui_successor", "차기 파티장")))
        self.ops_successor = QComboBox()
        self.ops_successor.setMinimumWidth(160)
        hand.addWidget(self.ops_successor)
        hand.addStretch(1)
        absent_lay.addLayout(hand)
        self._add_attack_target_box(host, lay, editable=True)
        lay.addStretch(1)
        return host

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

    def _build_leader_support(self) -> QWidget:
        host, lay = self._section()
        lay.addStretch(1)
        return host

    def _build_leader_supply(self) -> QWidget:
        host, lay = self._section()
        box = card(host, self._tx("party_ui_supply_title", "마을 및 보급"))
        lay.addWidget(box)
        inner = box.layout()
        assert isinstance(inner, QVBoxLayout)
        note = QLabel(
            self._tx(
                "party_ui_supply_note",
                "보급 담당은 파티 관리의 자리 역할에서 상점 역할로 지정합니다. "
                "별도 보급 화면은 아직 없고, 기존 파티원 명단은 그대로 유지됩니다.",
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        lay.addStretch(1)
        return host

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
        """Opening 파티봇 is the party switch. The header checkbox stays hidden."""
        if self._party_on():
            self._refresh_enabled_state()
            return
        if hasattr(self, "party_enable"):
            self.party_enable.setChecked(True)
            return
        self.bag.set("party", "enabled", True)
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
            QAbstractItemView.EditTrigger.NoEditTriggers
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

    def _refresh_successor_choices(self) -> None:
        combo = getattr(self, "ops_successor", None)
        if not isinstance(combo, QComboBox):
            return
        current = str(combo.currentData() or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._tx("party_ui_successor_none", "선택 안 함"), "")
        seen: set[str] = set()
        for row in self._roster_rows():
            name = str(row.get("name") or "").strip()
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            combo.addItem(name, name)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

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
            for item in (number, name, role_item, loot_item):
                item.setFlags(flags)
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
        column = item.column()
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
        self._refresh_successor_choices()
        self._lan_ip = ""
        self._fill_roster_table()
        self._apply_role(self._role())
        if self.routine_panel is not None:
            self.routine_panel.load_from_bag()

    def flush_routine(self) -> None:
        if self.routine_panel is not None:
            self.routine_panel._persist_routine()
