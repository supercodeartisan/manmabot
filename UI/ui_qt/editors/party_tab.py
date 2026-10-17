"""Party tab — member follow/assist, or this PC as the party-socket leader."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui_qt.editors.form_helpers import add_check, add_spin_row, card
from ui_qt.viewmodels.settings_bag import SettingsBag

_LOOT_ROLES = ("none", "responsible")
_FARM_MODES = ("party", "solo")
_PARTY_ROLES = ("member", "leader")


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bag = bag
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self._lan_ip = ""
        self._ws_testing = False
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

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self.t.get("party_farm_mode", "Farming method")))
        self.party_farm_mode = QComboBox()
        self.party_farm_mode.addItem(
            self.t.get("party_farm_party", "Party farm"),
            "party",
        )
        self.party_farm_mode.addItem(
            self.t.get("party_farm_solo", "Solo farm"),
            "solo",
        )
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
        self.party_random_loot = add_check(
            member_lay,
            self.bag,
            "party",
            "random_loot",
            self.t.get("party_random_loot", "Random"),
            False,
            on_change=self._on_loot_mode_changed,
        )
        role_row = QHBoxLayout()
        role_row.addWidget(QLabel(self.t.get("party_loot_role", "Role")))
        self.party_loot_role = QComboBox()
        self.party_loot_role.addItem(
            self.t.get("party_loot_role_none", "None"), "none"
        )
        self.party_loot_role.addItem(
            self.t.get("party_loot_role_responsible", "Responsible"),
            "responsible",
        )
        current = str(self.bag.get_str("party", "loot_role", "none") or "none")
        if current not in _LOOT_ROLES:
            current = "none"
        idx = self.party_loot_role.findData(current)
        self.party_loot_role.setCurrentIndex(max(0, idx))
        self.party_loot_role.currentIndexChanged.connect(self._on_loot_role_changed)
        role_row.addWidget(self.party_loot_role)
        role_row.addStretch(1)
        member_lay.addLayout(role_row)
        lay.addWidget(self.member_panel)

        self.leader_panel = QWidget()
        leader_lay = QVBoxLayout(self.leader_panel)
        leader_lay.setContentsMargins(0, 0, 0, 0)
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
        lay.addWidget(self.leader_panel)

        self.role_farm.currentIndexChanged.connect(self._on_role_combo_changed)
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

    def _test_ws_connection(self) -> None:
        """Probe the leader party socket once (member WebSocket settings)."""
        if self._ws_testing:
            return
        host = str(self.bag.get_str("party", "leader_host", "") or "").strip()
        port = int(self.bag.get_int("party", "ws_port", 8765) or 8765)
        if not host:
            msg = self.t.get(
                "party_ws_need_host",
                "Enter the leader IP first.",
            )
            self.ws_status.setText(msg)
            self.on_log(msg)
            return
        self._ws_testing = True
        self.ws_test_btn.setEnabled(False)
        self.ws_status.setText(self.t.get("party_ws_testing", "Testing…"))
        uri = f"ws://{host}:{port}/"
        hint = self.t.get(
            "party_ws_need_leader_start",
            "Start the leader bot first (Party enabled + Party leader + Start).",
        )

        def work() -> None:
            import socket as _socket

            try:
                # TCP first — clearer than a WebSocket timeout when nothing listens.
                with _socket.create_connection((host, port), timeout=2.0):
                    pass
            except OSError as exc:
                self._ws_bridge.finished.emit(
                    False,
                    self.t.get(
                        "party_ws_tcp_fail",
                        "No server at {uri} ({error}). {hint}",
                    ).format(uri=uri, error=exc, hint=hint),
                )
                return
            try:
                from websocket.client import PartyClient

                client = PartyClient(
                    host,
                    port,
                    reconnect=False,
                    sender="party-ui-test",
                )
                try:
                    client.connect(timeout=3.0, wait=True)
                finally:
                    client.close(timeout=2.0)
                self._ws_bridge.finished.emit(
                    True,
                    self.t.get("party_ws_ok", "Connected to {uri}").format(uri=uri),
                )
            except Exception as exc:
                self._ws_bridge.finished.emit(
                    False,
                    self.t.get(
                        "party_ws_fail",
                        "Connection failed ({uri}): {error}. {hint}",
                    ).format(uri=uri, error=exc, hint=hint),
                )

        threading.Thread(
            target=work,
            name="party-ws-test",
            daemon=True,
        ).start()

    def _on_ws_test_finished(self, ok: bool, detail: str) -> None:
        self._ws_testing = False
        on = self._party_on() and self._role() == "member"
        if hasattr(self, "ws_test_btn"):
            self.ws_test_btn.setEnabled(on)
        if hasattr(self, "ws_status"):
            self.ws_status.setText(
                self.t.get("party_ws_ok_short", "OK")
                if ok
                else self.t.get("party_ws_fail_short", "Failed")
            )
        self.on_log(str(detail or ""))

    def _lan_ip_text(self) -> str:
        """Prefer the LAN NIC, not the VPN default-route address."""
        try:
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
        on = self._party_on() and self._role() == "member"
        party_loot = on and self._farm_mode() == "party"
        random_on = self.bag.get_bool("party", "random_loot", False)
        if hasattr(self, "party_random_loot"):
            self.party_random_loot.setEnabled(party_loot)
        if hasattr(self, "party_loot_role"):
            self.party_loot_role.setEnabled(party_loot and not random_on)

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
        # Test button stays off while a probe is in flight.
        if hasattr(self, "ws_test_btn") and self._ws_testing:
            self.ws_test_btn.setEnabled(False)
        # Within the member panel, loot still depends on farm mode.
        if on and self._role() == "member":
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
        self._lan_ip = ""
        self._apply_role(self._role())
