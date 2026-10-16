"""Party tab — member follow/assist + loot role (right of Item)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui_qt.editors.form_helpers import add_check, add_spin_row, card
from ui_qt.viewmodels.settings_bag import SettingsBag

_LOOT_ROLES = ("none", "responsible")


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

        box = card(host, self.t.get("party_tab_title", "Party member"))
        body.addWidget(box)
        lay = box.layout()
        assert isinstance(lay, QVBoxLayout)

        hint = QLabel(
            self.t.get(
                "party_member_hint",
                "When enabled, this bot follows the in-party leader from "
                "memory and assists instead of solo farm. Join a party first.",
            )
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.party_enable = add_check(
            lay,
            self.bag,
            "party",
            "member_enabled",
            self.t.get("party_member_enabled", "Run as party member"),
            False,
            on_change=self._on_party_member_changed,
        )
        self.bag.set("party", "leader_name", "")

        self.party_follow_tiles = add_spin_row(
            lay,
            self.bag,
            "party",
            "follow_tiles",
            self.t.get(
                "party_follow_tiles",
                "Travel leash — follow if farther (tiles)",
            ),
            8,
            1,
            40,
            on_change=self._clamp_follow_stop,
        )
        self.party_stop_tiles = add_spin_row(
            lay,
            self.bag,
            "party",
            "stop_tiles",
            self.t.get(
                "party_stop_tiles",
                "Stop settle — arrive within (tiles)",
            ),
            2,
            0,
            40,
            on_change=self._clamp_follow_stop,
        )
        self.party_assist_leash = add_spin_row(
            lay,
            self.bag,
            "party",
            "assist_leash_tiles",
            self.t.get("party_assist_leash", "Assist leash (tiles)"),
            10,
            1,
            40,
        )

        loot = card(host, self.t.get("party_loot_title", "Party loot"))
        body.addWidget(loot)
        loot_lay = loot.layout()
        assert isinstance(loot_lay, QVBoxLayout)
        loot_hint = QLabel(
            self.t.get(
                "party_loot_hint",
                "Random ON: every party member may loot any nearby drop. "
                "Random OFF: only the Responsible role approaches and picks up.",
            )
        )
        loot_hint.setWordWrap(True)
        loot_lay.addWidget(loot_hint)

        self.party_random_loot = add_check(
            loot_lay,
            self.bag,
            "party",
            "random_loot",
            self.t.get("party_random_loot", "Random loot (all members)"),
            False,
            on_change=self._on_loot_mode_changed,
        )

        role_row = QHBoxLayout()
        role_row.addWidget(
            QLabel(self.t.get("party_loot_role", "Loot role"))
        )
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
        loot_lay.addLayout(role_row)

        body.addStretch(1)
        self._on_party_member_changed()

    def _clamp_follow_stop(self) -> None:
        follow = self.bag.get_int("party", "follow_tiles", 8)
        stop = self.bag.get_int("party", "stop_tiles", 2)
        if stop > follow:
            self.bag.set("party", "stop_tiles", follow)
            if hasattr(self, "party_stop_tiles"):
                self.party_stop_tiles.blockSignals(True)
                self.party_stop_tiles.setValue(follow)
                self.party_stop_tiles.blockSignals(False)

    def _on_loot_role_changed(self) -> None:
        data = self.party_loot_role.currentData()
        role = str(data or "none")
        if role not in _LOOT_ROLES:
            role = "none"
        self.bag.set("party", "loot_role", role)

    def _on_loot_mode_changed(self) -> None:
        random_on = self.bag.get_bool("party", "random_loot", False)
        if hasattr(self, "party_loot_role"):
            self.party_loot_role.setEnabled(
                self.bag.get_bool("party", "member_enabled", False) and not random_on
            )

    def _on_party_member_changed(self) -> None:
        on = self.bag.get_bool("party", "member_enabled", False)
        self.bag.set("party", "leader_name", "")
        for spin in (
            getattr(self, "party_follow_tiles", None),
            getattr(self, "party_stop_tiles", None),
            getattr(self, "party_assist_leash", None),
        ):
            if spin is not None:
                spin.setEnabled(on)
        if hasattr(self, "party_random_loot"):
            self.party_random_loot.setEnabled(on)
        self._on_loot_mode_changed()

    def reload_from_bag(self) -> None:
        if not hasattr(self, "party_enable"):
            return
        self.party_enable.blockSignals(True)
        self.party_enable.setChecked(
            self.bag.get_bool("party", "member_enabled", False)
        )
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
        self._on_party_member_changed()
