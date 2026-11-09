"""Party-bot shell: role picker, then a leader or member menu."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui_qt.editors.party_role_picker import PartyRolePicker
from ui_qt.editors.party_tab import PartyTab
from ui_qt.i18n_overlay import tx
from ui_qt.i18n_refresh import bind_tx_keys

_LEADER_MENUS = (
    ("manage", "party_ui_menu_manage", "파티 관리"),
    ("map", "party_ui_menu_map", "사냥터 및 지도"),
    ("ops", "party_ui_menu_ops", "파티운영"),
    ("supply", "party_ui_menu_supply", "마을 및 보급"),
    ("loot", "party_ui_menu_loot", "아이템 및 루팅"),
    ("common", "party_ui_menu_common", "공통 설정"),
)
_MEMBER_MENUS = (
    ("link", "party_ui_menu_link", "파티장 연결"),
    ("follow", "party_ui_menu_follow", "따라가기"),
    ("assist", "party_ui_menu_assist", "공격 지원"),
    ("support", "party_ui_menu_support", "지원 및 보호"),
    ("personal", "party_ui_menu_personal", "개인 행동 설정"),
    ("status", "party_ui_menu_status", "파티 상태"),
)
_LEADER_ACCENT = "#3a82f6"
_MEMBER_ACCENT = _LEADER_ACCENT


class PartyWorkspace(QWidget):
    def __init__(self, tab: PartyTab, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        with bind_tx_keys():
            self._assemble(tab)

    def _assemble(self, tab: PartyTab) -> None:
        self.tab = tab
        self._locked = False
        self._confirmed = False
        self._page = "picker"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            "background: #f4e4c4; color: #8a5a00; "
            "border: 1px solid #e6d3a8; border-radius: 6px; padding: 6px 10px;"
        )
        self._banner.hide()
        root.addWidget(self._banner)

        self._header = QWidget()
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        self._back = QPushButton(tx(tab.t, "party_ui_role_back", "역할 선택"))
        self._back.clicked.connect(self.show_picker)
        self._title = QLabel(tx(tab.t, "party_ui_leader", "파티장"))
        self._title.setStyleSheet("font-weight: 700;")
        header.addWidget(self._back)
        header.addWidget(self._title)
        header.addStretch(1)
        self._header.hide()
        root.addWidget(self._header)

        self._stack = QStackedWidget()
        self._picker = PartyRolePicker(strings=tab.t)
        self._picker.roleChosen.connect(self._on_role_chosen)
        self._stack.addWidget(self._picker)
        self._leader_page, self._leader_buttons = self._build_role_page(
            _LEADER_MENUS, tab.leader_sections, _LEADER_ACCENT
        )
        self._member_page, self._member_buttons = self._build_role_page(
            _MEMBER_MENUS, tab.member_sections, _MEMBER_ACCENT
        )
        self._stack.addWidget(self._leader_page)
        self._stack.addWidget(self._member_page)
        root.addWidget(self._stack, stretch=1)
        tab.hide()
        self._paint_saved()
        self.show_picker()

    def _build_role_page(
        self,
        menus: tuple[tuple[str, str], ...],
        sections: dict,
        accent: str,
    ) -> tuple[QWidget, list[QPushButton]]:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        nav = QWidget()
        nav.setFixedWidth(112)
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(4)
        buttons: list[QPushButton] = []
        stack = QStackedWidget()
        for key, text_key, fallback in menus:
            label = tx(self.tab.t, text_key, fallback)
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(32)
            nav_lay.addWidget(button)
            buttons.append(button)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(sections[key])
            stack.addWidget(scroll)
        nav_lay.addStretch(1)

        def _select(index: int) -> None:
            stack.setCurrentIndex(index)
            for button_index, button in enumerate(buttons):
                selected = button_index == index
                button.setChecked(selected)
                if selected:
                    button.setStyleSheet(
                        f"QPushButton {{ background: {accent}; color: #ffffff; "
                        "border: 1px solid " + accent + "; border-radius: 6px; "
                        "padding: 6px 8px; font-weight: 700; text-align: center; }"
                    )
                else:
                    button.setStyleSheet(
                        "QPushButton { background: #ffffff; color: #1f2328; "
                        "border: 1px solid #d5dbe3; border-radius: 6px; "
                        "padding: 6px 8px; font-weight: 600; text-align: center; }"
                        "QPushButton:hover { background: #f4f7fb; }"
                    )

        for index, button in enumerate(buttons):
            button.clicked.connect(lambda _checked=False, i=index: _select(i))
        _select(0)
        row.addWidget(nav)
        row.addWidget(stack, stretch=1)
        return page, buttons

    def saved_role(self) -> str:
        return self.tab._role()

    def role_ready(self) -> bool:
        """True after this process confirms the saved party role."""
        return self._confirmed and self.saved_role() in ("leader", "member")

    def current_page(self) -> str:
        return self._page

    def visible_menu_labels(self) -> list[str]:
        buttons = self._leader_buttons if self._page == "leader" else (
            self._member_buttons if self._page == "member" else []
        )
        return [button.text() for button in buttons]

    def show_picker(self) -> None:
        if self._locked:
            self._show_role(self.saved_role())
            return
        self._page = "picker"
        self._stack.setCurrentWidget(self._picker)
        self._header.hide()
        self._paint_saved()

    def present(self) -> None:
        """Party mode opened. The picker is reachable only while stopped."""
        self.tab.use_party_mode()
        if self._locked:
            self._show_role(self.saved_role())
        else:
            self.show_picker()

    def set_locked(self, locked: bool, reason: str) -> None:
        self._locked = bool(locked)
        self._banner.setVisible(self._locked and bool(reason))
        self._banner.setText(reason)
        self._back.setEnabled(not self._locked)
        self._picker.set_locked(self._locked)
        if self._locked and self._page == "picker":
            self._show_role(self.saved_role())

    def _on_role_chosen(self, role: str) -> None:
        if self._locked:
            return
        if role not in ("leader", "member"):
            return
        self.tab.set_master_enabled(True)
        self.tab._apply_role(role)
        self._confirmed = True
        self._show_role(role)

    def _show_role(self, role: str) -> None:
        if role not in ("leader", "member"):
            role = "member"
        self._page = role
        leader = role == "leader"
        self._stack.setCurrentWidget(self._leader_page if leader else self._member_page)
        self._title.setText(
            tx(self.tab.t, "party_ui_leader", "파티장")
            if leader
            else tx(self.tab.t, "party_ui_member", "파티원")
        )
        self._title.setStyleSheet(
            "font-weight: 700; color: "
            + (_LEADER_ACCENT if leader else _MEMBER_ACCENT)
            + ";"
        )
        self._header.show()
        self._paint_saved()

    def _paint_saved(self) -> None:
        saved = self.saved_role()
        self._picker.set_saved(saved)
        self._picker.set_selected(saved if self._confirmed else None)
