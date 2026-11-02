"""Party tab — member follow/assist, or this PC as the party-socket leader."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from settings.profile import normalize_party_roster
from ui_qt.editors.form_helpers import add_check, add_spin_row, card, configure_table_fill
from ui_qt.editors.party_routine_panel import PartyRoutinePanel
from ui_qt.viewmodels.settings_bag import SettingsBag

_LOOT_ROLES = ("none", "responsible")
_LOOT_PRIORITIES = ("follow", "loot")
_FARM_MODES = ("party", "solo")
_LEADER_MODES = ("turret", "moving")
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

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        scroll.setWidget(host)
        root.addWidget(scroll, stretch=1)
        body = QVBoxLayout(host)

        self.party_box = card(host, self.t.get("party_tab_title", "Party member"))
        body.addWidget(self.party_box)
        lay = self.party_box.layout()
        assert isinstance(lay, QVBoxLayout)

        # Master switch: when off, every other party control is disabled.
        self._migrate_enabled_flag()
        self.party_enable = add_check(
            lay,
            self.bag,
            "party",
            "enabled",
            self.t.get("party_enabled", "Enable party"),
            False,
            on_change=self._on_party_enabled_changed,
        )

        self.role_farm = self._add_role_combo(lay)

        self.member_panel = QWidget()
        member_lay = QVBoxLayout(self.member_panel)
        member_lay.setContentsMargins(0, 0, 0, 0)

        self.bag.set("party", "leader_name", "")

        self.member_ws_box = card(
            self.member_panel,
            self.t.get("party_ws_title", "WebSocket"),
        )
        member_lay.addWidget(self.member_ws_box)
        ws_lay = self.member_ws_box.layout()
        assert isinstance(ws_lay, QVBoxLayout)

        host_row = QHBoxLayout()
        host_row.addWidget(QLabel(self.t.get("party_leader_host", "Leader")))
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
            self.t.get("party_ws_port", "Port"),
            8765,
            1,
            65535,
        )
        test_row = QHBoxLayout()
        self.ws_test_btn = QPushButton(
            self.t.get("party_ws_test", "Test connection")
        )
        self.ws_test_btn.clicked.connect(self._test_ws_connection)
        test_row.addWidget(self.ws_test_btn)
        self.ws_status = QLabel("")
        self.ws_status.setWordWrap(True)
        test_row.addWidget(self.ws_status, stretch=1)
        ws_lay.addLayout(test_row)

        farm_hint = QLabel(
            self.t.get(
                "party_farm_hint",
                "Party: attack what the leader fights. "
                "Solo: hunt own monsters near the leader.",
            )
        )
        farm_hint.setWordWrap(True)
        member_lay.addWidget(farm_hint)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self.t.get("party_farm_mode", "Farming method")))
        self.party_farm_mode = QComboBox()
        self.party_farm_mode.addItem(self.t.get("party_farm_party", "Party"), "party")
        self.party_farm_mode.addItem(self.t.get("party_farm_solo", "Solo"), "solo")
        self._select_farm_mode()
        self.party_farm_mode.currentIndexChanged.connect(self._on_farm_mode_changed)
        mode_row.addWidget(self.party_farm_mode)
        mode_row.addStretch(1)
        member_lay.addLayout(mode_row)

        self.party_follow_tiles = add_spin_row(
            member_lay,
            self.bag,
            "party",
            "follow_tiles",
            self.t.get("party_follow_tiles", "Follow"),
            8,
            1,
            40,
            on_change=self._clamp_follow_stop,
        )
        self.party_stop_tiles = add_spin_row(
            member_lay,
            self.bag,
            "party",
            "stop_tiles",
            self.t.get("party_stop_tiles", "Stop"),
            2,
            0,
            40,
            on_change=self._clamp_follow_stop,
        )
        self.party_assist_leash = add_spin_row(
            member_lay,
            self.bag,
            "party",
            "assist_leash_tiles",
            self.t.get("party_assist_leash", "Assist"),
            10,
            1,
            40,
        )
        member_hint = QLabel(
            self.t.get(
                "party_member_policy_hint",
                "Turret / moving and loot rules come from the party leader "
                "over WebSocket. Farming method and follow / stop / assist "
                "are this bot's own.",
            )
        )
        member_hint.setWordWrap(True)
        member_lay.addWidget(member_hint)
        lay.addWidget(self.member_panel)

        self.leader_panel = QWidget()
        leader_lay = QVBoxLayout(self.leader_panel)
        leader_lay.setContentsMargins(0, 0, 0, 0)
        self._build_leader_farm(leader_lay)
        self._build_roster(leader_lay)
        self.ip_edit = self._address_row(
            leader_lay, self.t.get("party_ws_ip", "IP")
        )
        self.party_ws_port = add_spin_row(
            leader_lay,
            self.bag,
            "party",
            "ws_port",
            self.t.get("party_ws_port", "Port"),
            8765,
            1,
            65535,
            on_change=self._refresh_leader_labels,
        )

        # Same-PC client probe against this machine's WebSocket server.
        self.leader_local_test_box = card(
            self.leader_panel,
            self.t.get("party_ws_local_test_title", "Local test client"),
        )
        leader_lay.addWidget(self.leader_local_test_box)
        local_lay = self.leader_local_test_box.layout()
        assert isinstance(local_lay, QVBoxLayout)
        local_hint = QLabel(
            self.t.get(
                "party_ws_local_test_hint",
                "Start the leader bot first. Test on this PC (localhost), "
                "then via LAN IP before checking from another machine.",
            )
        )
        local_hint.setWordWrap(True)
        local_lay.addWidget(local_hint)
        local_row = QHBoxLayout()
        self.ws_local_btn = QPushButton(
            self.t.get("party_ws_test_localhost", "Test localhost")
        )
        self.ws_local_btn.clicked.connect(self._test_ws_localhost)
        local_row.addWidget(self.ws_local_btn)
        self.ws_lan_btn = QPushButton(
            self.t.get("party_ws_test_lan", "Test via LAN IP")
        )
        self.ws_lan_btn.clicked.connect(self._test_ws_lan_self)
        local_row.addWidget(self.ws_lan_btn)
        self.ws_local_status = QLabel("")
        self.ws_local_status.setWordWrap(True)
        local_row.addWidget(self.ws_local_status, stretch=1)
        local_lay.addLayout(local_row)

        lay.addWidget(self.leader_panel)

        self.role_farm.currentIndexChanged.connect(self._on_role_combo_changed)
        if self._profile is not None:
            self.routine_panel = PartyRoutinePanel(
                bag=self.bag,
                profile=self._profile,
                strings=self.t,
                language=self.language,
                on_log=self.on_log,
                can_edit_map=self._can_edit_map,
            )
            body.addWidget(self.routine_panel, stretch=1)
        else:
            body.addStretch(1)
        self._apply_role(self._role())

    def _migrate_enabled_flag(self) -> None:
        """Older bags only had ``member_enabled``; promote it to the master switch."""
        party = self.bag.section("party") or {}
        if "enabled" in party:
            return
        legacy = bool(party.get("member_enabled", False))
        self.bag.set("party", "enabled", legacy)

    def _party_on(self) -> bool:
        return bool(self.bag.get_bool("party", "enabled", False))

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

    def _build_leader_farm(self, layout: QVBoxLayout) -> None:
        """Global farm + loot knobs broadcast to members as ``party_policy``."""
        box = card(
            self.leader_panel,
            self.t.get("party_farm_title", "Party farming"),
        )
        layout.addWidget(box)
        lay = box.layout()
        assert isinstance(lay, QVBoxLayout)
        hint = QLabel(
            self.t.get(
                "party_leader_mode_hint",
                "Turret: the party holds a yard around the leader and members "
                "stay inside it. Moving: the leader roams and members follow.",
            )
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self.t.get("party_farm_mode", "Farming method")))
        self.party_leader_mode = QComboBox()
        self.party_leader_mode.addItem(
            self.t.get("party_farm_turret", "Turret"), "turret"
        )
        self.party_leader_mode.addItem(
            self.t.get("party_farm_moving", "Moving"), "moving"
        )
        self._select_leader_mode()
        self.party_leader_mode.currentIndexChanged.connect(
            self._on_leader_mode_changed
        )
        mode_row.addWidget(self.party_leader_mode)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)
        self.party_lag_tiles = add_spin_row(
            lay,
            self.bag,
            "party",
            "lag_tiles",
            self.t.get("party_lag_tiles", "Wait when behind (tiles)"),
            30,
            5,
            100,
        )
        self.party_lag_tiles.setToolTip(
            self.t.get(
                "party_lag_tiles_hint",
                "Moving: the leader waits briefly when half or more members "
                "are farther behind than this.",
            )
        )
        self._sync_lag_enabled()

        loot_hint = QLabel(
            self.t.get(
                "party_loot_hint",
                "Solo loot: every member may loot. Responsible: only roster "
                "rows marked Responsible pick up.",
            )
        )
        loot_hint.setWordWrap(True)
        lay.addWidget(loot_hint)
        self.party_random_loot = add_check(
            lay,
            self.bag,
            "party",
            "random_loot",
            self.t.get("party_random_loot", "Solo loot (everyone)"),
            False,
            on_change=self._on_loot_mode_changed,
        )
        priority_row = QHBoxLayout()
        priority_row.addWidget(
            QLabel(self.t.get("party_loot_priority", "Priority"))
        )
        self.party_loot_priority = QComboBox()
        self.party_loot_priority.addItem(
            self.t.get("party_loot_priority_follow", "Follow first"), "follow"
        )
        self.party_loot_priority.addItem(
            self.t.get("party_loot_priority_loot", "Loot first"), "loot"
        )
        self._select_loot_priority()
        self.party_loot_priority.currentIndexChanged.connect(
            self._on_loot_priority_changed
        )
        priority_row.addWidget(self.party_loot_priority)
        priority_row.addStretch(1)
        lay.addLayout(priority_row)
        # Kept for bag compatibility; responsible seats are per roster row.
        self.party_loot_role = QComboBox()
        self.party_loot_role.addItem(
            self.t.get("party_loot_role_none", "None"), "none"
        )
        self.party_loot_role.addItem(
            self.t.get("party_loot_role_responsible", "Responsible"),
            "responsible",
        )
        self.party_loot_role.hide()
        current = str(self.bag.get_str("party", "loot_role", "none") or "none")
        if current not in _LOOT_ROLES:
            current = "none"
        idx = self.party_loot_role.findData(current)
        self.party_loot_role.setCurrentIndex(max(0, idx))
        self.party_loot_role.currentIndexChanged.connect(self._on_loot_role_changed)

    def _build_roster(self, layout: QVBoxLayout) -> None:
        box = card(
            self.leader_panel,
            self.t.get("party_roster_title", "Party members"),
        )
        layout.addWidget(box)
        box_lay = box.layout()
        assert isinstance(box_lay, QVBoxLayout)

        form = QHBoxLayout()
        form.addWidget(QLabel(self.t.get("party_roster_name", "Name")))
        self.roster_name = QLineEdit()
        self.roster_name.returnPressed.connect(self._add_roster_row)
        form.addWidget(self.roster_name, stretch=1)
        form.addWidget(QLabel(self.t.get("party_roster_role", "Role")))
        self.roster_role = QComboBox()
        for role in _ROSTER_ROLES:
            self.roster_role.addItem(self._roster_role_label(role), role)
        # Default seat for new members is mage.
        mage_idx = self.roster_role.findData("mage")
        self.roster_role.setCurrentIndex(max(0, mage_idx))
        form.addWidget(self.roster_role)
        form.addWidget(QLabel(self.t.get("party_roster_loot", "Loot")))
        self.roster_loot = QComboBox()
        self.roster_loot.addItem(
            self.t.get("party_loot_role_none", "None"), "none"
        )
        self.roster_loot.addItem(
            self.t.get("party_loot_role_responsible", "Responsible"),
            "responsible",
        )
        form.addWidget(self.roster_loot)
        add_btn = QPushButton(self.t.get("add", "Add"))
        add_btn.clicked.connect(self._add_roster_row)
        form.addWidget(add_btn)
        remove_btn = QPushButton(self.t.get("delete", "Delete"))
        remove_btn.clicked.connect(self._remove_roster_row)
        form.addWidget(remove_btn)
        box_lay.addLayout(form)

        self.roster_table = QTableWidget(0, 4)
        self.roster_table.setHorizontalHeaderLabels(
            [
                self.t.get("number", "No"),
                self.t.get("party_roster_name", "Name"),
                self.t.get("party_roster_role", "Role"),
                self.t.get("party_roster_loot", "Loot"),
            ]
        )
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
        configure_table_fill(self.roster_table, 1, fixed={0: 48, 2: 100, 3: 110})
        box_lay.addWidget(self.roster_table)
        self._fill_roster_table()

    def _roster_role_label(self, role: str) -> str:
        labels = {
            "member": ("party_seat_member", "Member"),
            "mage": ("party_seat_mage", "Mage"),
            "shopkeeper": ("party_seat_shopkeeper", "Shopkeeper"),
        }
        key, fallback = labels.get(role, labels["mage"])
        return self.t.get(key, fallback)

    def _roster_loot_label(self, loot: str) -> str:
        if loot == "responsible":
            return self.t.get("party_loot_role_responsible", "Responsible")
        return self.t.get("party_loot_role_none", "None")

    def _roster_rows(self) -> list[dict[str, str]]:
        return normalize_party_roster(self.bag.get("party", "roster", []))

    def _store_roster(self, rows: list[dict[str, str]]) -> None:
        self.bag.set("party", "roster", normalize_party_roster(rows))

    def _fill_roster_table(self) -> None:
        table = getattr(self, "roster_table", None)
        if not isinstance(table, QTableWidget):
            return
        rows = self._roster_rows()
        table.setRowCount(len(rows))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
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
            for item in (number, name, role_item, loot_item):
                item.setFlags(flags)
            table.setItem(index, 0, number)
            table.setItem(index, 1, name)
            table.setItem(index, 2, role_item)
            table.setItem(index, 3, loot_item)

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
        rows.append({"name": name, "role": role, "loot": loot})
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

    def _leader_mode(self) -> str:
        mode = str(self.bag.get_str("party", "leader_mode", "turret") or "turret")
        return mode if mode in _LEADER_MODES else "turret"

    def _select_leader_mode(self) -> None:
        self.party_leader_mode.blockSignals(True)
        idx = self.party_leader_mode.findData(self._leader_mode())
        self.party_leader_mode.setCurrentIndex(max(0, idx))
        self.party_leader_mode.blockSignals(False)

    def _on_leader_mode_changed(self) -> None:
        mode = str(self.party_leader_mode.currentData() or "turret")
        if mode not in _LEADER_MODES:
            mode = "turret"
        self.bag.set("party", "leader_mode", mode)
        self._sync_lag_enabled()

    def _sync_lag_enabled(self) -> None:
        if hasattr(self, "party_lag_tiles"):
            self.party_lag_tiles.setEnabled(self._leader_mode() == "moving")

    def _role(self) -> str:
        role = str(self.bag.get_str("party", "role", "member") or "member")
        return role if role in _PARTY_ROLES else "member"

    def _select_farm_mode(self) -> None:
        self.party_farm_mode.blockSignals(True)
        idx = self.party_farm_mode.findData(self._farm_mode())
        self.party_farm_mode.setCurrentIndex(max(0, idx))
        self.party_farm_mode.blockSignals(False)

    def _on_farm_mode_changed(self) -> None:
        mode = str(self.party_farm_mode.currentData() or "party")
        if mode not in _FARM_MODES:
            mode = "party"
        self.bag.set("party", "farm_mode", mode)
        self._on_loot_mode_changed()

    def _on_loot_role_changed(self) -> None:
        data = self.party_loot_role.currentData()
        role = str(data or "none")
        if role not in _LOOT_ROLES:
            role = "none"
        self.bag.set("party", "loot_role", role)

    def _loot_priority(self) -> str:
        value = str(self.bag.get_str("party", "loot_priority", "follow") or "follow")
        return value if value in _LOOT_PRIORITIES else "follow"

    def _select_loot_priority(self) -> None:
        self.party_loot_priority.blockSignals(True)
        idx = self.party_loot_priority.findData(self._loot_priority())
        self.party_loot_priority.setCurrentIndex(max(0, idx))
        self.party_loot_priority.blockSignals(False)

    def _on_loot_priority_changed(self) -> None:
        value = str(self.party_loot_priority.currentData() or "follow")
        if value not in _LOOT_PRIORITIES:
            value = "follow"
        self.bag.set("party", "loot_priority", value)
        self._on_loot_mode_changed()

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
        combo = getattr(self, "role_farm", None)
        if combo is not None:
            combo.blockSignals(True)
            idx = combo.findData(role)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)
        leader = role == "leader"
        self.member_panel.setVisible(not leader)
        self.leader_panel.setVisible(leader)
        self.party_box.setTitle(
            self.t.get("party_leader_title", "Party leader")
            if leader
            else self.t.get("party_tab_title", "Party member")
        )
        if leader:
            self._refresh_leader_labels()
        self._refresh_enabled_state()

    def _on_loot_mode_changed(self) -> None:
        on = self._party_on() and self._role() == "leader"
        random_on = self.bag.get_bool("party", "random_loot", False)
        follow_first = self._loot_priority() == "follow"
        if hasattr(self, "party_loot_priority"):
            self.party_loot_priority.setEnabled(on)
        if hasattr(self, "party_random_loot"):
            self.party_random_loot.setEnabled(on and follow_first)
        if hasattr(self, "roster_loot"):
            self.roster_loot.setEnabled(on and follow_first and not random_on)

    def _on_party_enabled_changed(self) -> None:
        self._sync_member_enabled_flag()
        self.bag.set("party", "leader_name", "")
        self._refresh_enabled_state()

    def _refresh_enabled_state(self) -> None:
        """Enable party checkbox stays on; everything else follows the master switch."""
        on = self._party_on()
        if hasattr(self, "role_farm"):
            self.role_farm.setEnabled(on)
        # Member / leader panels: whole panel greyed when party is off.
        if hasattr(self, "member_panel"):
            self.member_panel.setEnabled(on)
        if hasattr(self, "leader_panel"):
            self.leader_panel.setEnabled(on)
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
        self._select_loot_priority()
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
        self._select_leader_mode()
        if hasattr(self, "party_lag_tiles"):
            self.party_lag_tiles.blockSignals(True)
            self.party_lag_tiles.setValue(self.bag.get_int("party", "lag_tiles", 30))
            self.party_lag_tiles.blockSignals(False)
            self._sync_lag_enabled()
        self._lan_ip = ""
        self._fill_roster_table()
        self._apply_role(self._role())
        if self.routine_panel is not None:
            self.routine_panel.load_from_bag()

    def flush_routine(self) -> None:
        if self.routine_panel is not None:
            self.routine_panel._persist_routine()
