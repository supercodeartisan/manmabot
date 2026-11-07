"""Party role picker and separate leader/member menus. No game client."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[4]
for _path in (_ROOT / "UI", _ROOT / "Engine"):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QRadioButton

from settings.profile import Profile
from ui_qt.editors.move_tab import MoveTab
from ui_qt.editors.party_routine_panel import PartyRoutinePanel
from ui_qt.editors.party_tab import PartyTab
from ui_qt.editors.party_workspace import PartyWorkspace
from ui_qt.viewmodels.settings_bag import SettingsBag


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _workspace(role: str = "member") -> PartyWorkspace:
    _app()
    profile = Profile()
    bag = SettingsBag(profile)
    bag.set("party", "role", role)
    tab = PartyTab(
        bag=bag,
        strings={},
        language="ko",
        profile=None,
    )
    return PartyWorkspace(tab)


def test_picker_blocks_start_until_a_card_is_chosen() -> None:
    workspace = _workspace("leader")
    assert workspace.current_page() == "picker"
    assert workspace.role_ready() is False
    assert workspace._picker.leader_card._saved is not None
    assert workspace._picker.leader_card._saved.isHidden() is False
    workspace._on_role_chosen("leader")
    assert workspace.role_ready() is True
    assert workspace.current_page() == "leader"
    assert workspace.tab._role() == "leader"


def test_leader_and_member_menus_do_not_overlap() -> None:
    workspace = _workspace()
    workspace._on_role_chosen("leader")
    leader_labels = workspace.visible_menu_labels()
    assert leader_labels == [
        "파티 관리",
        "사냥터 및 지도",
        "사냥 운영",
        "지원 및 보호",
        "마을 및 보급",
        "아이템 및 루팅",
        "공통 설정",
    ]
    assert "파티 관리" in leader_labels
    assert "사냥터 및 지도" in leader_labels
    assert "파티장 연결" not in leader_labels
    assert "따라가기" not in leader_labels

    workspace.set_locked(False, "")
    workspace.show_picker()
    workspace._on_role_chosen("member")
    member_labels = workspace.visible_menu_labels()
    assert "파티장 연결" in member_labels
    assert "공격 지원" in member_labels
    assert "파티 관리" not in member_labels
    assert "아이템 및 루팅" not in member_labels
    assert workspace.tab._role() == "member"


def test_running_lock_hides_the_picker_and_blocks_the_other_role() -> None:
    workspace = _workspace("member")
    workspace._on_role_chosen("member")
    workspace.set_locked(True, "실행 중에는 역할을 바꿀 수 없습니다.")
    assert workspace._back.isEnabled() is False
    assert "실행 중" in workspace._banner.text()
    workspace.show_picker()
    assert workspace.current_page() == "member"
    workspace._on_role_chosen("leader")
    assert workspace.tab._role() == "member"
    workspace.set_locked(False, "")
    assert workspace._back.isEnabled() is True
    workspace.show_picker()
    assert workspace.current_page() == "picker"


def test_manage_page_hides_party_enable_and_renumbers() -> None:
    workspace = _workspace("leader")
    workspace._on_role_chosen("leader")
    assert workspace.tab.enable_host.isHidden() is True
    for button in workspace._leader_buttons:
        button.click()
        assert workspace.tab.enable_host.isHidden() is True
    workspace._show_role("member")
    for button in workspace._member_buttons:
        button.click()
        assert workspace.tab.enable_host.isHidden() is True
    workspace.tab.bag.set("party", "enabled", False)
    workspace.tab.party_enable.setChecked(False)
    workspace.present()
    assert workspace.tab.enable_host.isHidden() is True
    assert workspace.tab._party_on() is True

    tab = workspace.tab
    labels = [
        tab.roster_table.horizontalHeaderItem(index).text()
        for index in range(tab.roster_table.columnCount())
    ]
    assert labels == ["선택", "번호", "이름", "역할", "루팅", "사용", "대기"]
    assert tab.roster_table.columnWidth(0) == 34
    assert tab.roster_table.columnWidth(1) == 45
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
            {"name": "브라보", "role": "member", "loot": "responsible", "enabled": "1", "required": "1"},
        ]
    )
    tab._fill_roster_table()
    assert tab.roster_table.item(0, 1).text() == "1"
    assert tab.roster_table.item(1, 1).text() == "2"
    tab.roster_table.selectRow(0)
    tab._remove_roster_row()
    assert tab.roster_table.rowCount() == 1
    assert tab.roster_table.item(0, 1).text() == "1"
    assert tab.roster_table.item(0, 2).text() == "브라보"


def test_invite_and_kick_use_checked_names_only() -> None:
    workspace = _workspace("leader")
    tab = workspace.tab
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
            {"name": "브라보", "role": "member", "loot": "none", "enabled": "1", "required": "1"},
        ]
    )
    tab._fill_roster_table()
    sent: list[tuple[str, str]] = []

    def _submit(kind: str, name: str) -> str:
        sent.append((kind, name))
        return "queued"

    tab._party_chat_submit = lambda: _submit  # type: ignore[method-assign]
    assert tab._invite_selected() == []
    assert sent == []
    for row in (0, 1):
        box = tab.roster_table.cellWidget(row, 0).findChild(QCheckBox)
        assert box is not None
        box.setChecked(True)
    assert tab._invite_selected() == ["알파", "브라보"]
    assert sent == [("invite", "알파"), ("invite", "브라보")]
    assert tab.roster_result.item(0, 2).text() == "초대 진행 중"
    assert tab.roster_result.item(0, 3).text() == ""

    tab._confirmed_party_names = lambda: {"알파"}  # type: ignore[method-assign]
    assert tab._kick_targets() == ["알파"]
    assert tab._kick_selected() == []
    assert tab.roster_result.rowCount() == 2


def test_map_and_ops_pages_keep_existing_settings() -> None:
    workspace = _workspace("leader")
    tab = workspace.tab
    map_text = " ".join(
        label.text() for label in tab.leader_sections["map"].findChildren(QLabel)
    )
    assert "직사각형 사냥구역" not in map_text
    assert "맵을 추가하고" not in map_text
    assert tab.routine_panel is None
    hint = "맵을 추가하고 각 맵의 시간(분)과 순서를 정하세요. 구역 또는 패트롤에서 기존과 같이 편집합니다."
    profile = Profile()
    strings = {"routine_hint": hint}
    panel = PartyRoutinePanel(
        bag=SettingsBag(profile),
        profile=profile,
        strings=strings,
        language="ko",
    )
    assert all(label.isHidden() for label in panel.findChildren(QLabel) if label.text() == hint)
    solo = MoveTab(profile=profile, strings=strings, language="ko", load_profile=False)
    assert any(label.text() == hint and label.isHidden() is False for label in solo.findChildren(QLabel))

    ops = tab.leader_sections["ops"]
    radios = [button.text() for button in ops.findChildren(QRadioButton)]
    assert radios[:3] == ["계속 사냥", "제자리 대기", "지정 장소로 이동"]
    support_text = " ".join(
        label.text() for label in tab.leader_sections["support"].findChildren(QLabel)
    )
    assert "뒤처지면 대기" not in support_text
    assert not hasattr(tab, "party_lag_tiles")
    assert tab.member_sections["follow"].isAncestorOf(tab.party_follow_tiles)
    ops_text = " ".join(label.text() for label in ops.findChildren(QLabel))
    assert "파티원 따라가기 거리" not in ops_text
    assert "뒤처짐 판단 거리" not in ops_text

    before = copy.deepcopy(tab.bag.section("party") or {})
    ops.findChildren(QRadioButton)[0].setChecked(True)
    tab.ops_handover.setChecked(True)
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
        ]
    )
    names = [tab.ops_successor.itemText(i) for i in range(tab.ops_successor.count())]
    assert "알파" in names
    tab.ops_successor.setCurrentIndex(tab.ops_successor.findText("알파"))
    after = copy.deepcopy(tab.bag.section("party") or {})
    after.pop("roster", None)
    before.pop("roster", None)
    assert after == before


def test_attack_target_reuses_farm_mode() -> None:
    workspace = _workspace("leader")
    tab = workspace.tab
    tab.party_enable.setChecked(True)
    assert [button.text() for button in tab.ops_attack_buttons.values()] == [
        "파티장 공격 대상 따라가기",
        "랜덤 공격",
    ]
    assert tab.ops_attack_buttons["party"].isChecked()
    assert tab.ops_attack_buttons["party"].isEnabled()
    assert tab.member_attack_buttons["party"].isEnabled() is False
    assert tab.member_attack_buttons["solo"].isEnabled() is False
    assert tab.party_farm_mode.isEnabled() is False
    assert "엔진 연결 전" in tab.ops_attack_status.text()
    assert "읽기 전용" in tab.member_attack_status.text()
    assert tab.party_farm_mode.itemText(0) == "추종"
    assert tab.party_farm_mode.itemText(1) == "주변 대상 단독 공격"
    assert tab.bag.get_str("party", "farm_mode", "party") == "party"

    tab.ops_attack_buttons["solo"].setChecked(True)
    assert tab.bag.get_str("party", "farm_mode", "") == "solo"
    assert tab.party_farm_mode.currentData() == "solo"
    assert tab.member_attack_buttons["solo"].isChecked()

    tab.member_attack_buttons["party"].click()
    assert tab.bag.get_str("party", "farm_mode", "") == "solo"

    tab.party_farm_mode.setCurrentIndex(tab.party_farm_mode.findData("party"))
    assert tab.bag.get_str("party", "farm_mode", "") == "party"
    assert tab.ops_attack_buttons["party"].isChecked()
    assert "공격 추종" in tab.personal_summary.text() or "추종" in tab.personal_summary.text()


def test_simplified_chinese_replaces_party_labels() -> None:
    from ui.schedule_i18n import tr
    from ui_qt.i18n_overlay import merge_ui_strings

    _app()
    strings = merge_ui_strings("zh", tr("zh"))
    profile = Profile()
    bag = SettingsBag(profile)
    bag.set("party", "role", "leader")
    tab = PartyTab(bag=bag, strings=strings, language="zh", profile=None)
    workspace = PartyWorkspace(tab)
    assert "队长" in workspace._picker.leader_card.findChildren(QLabel)[1].text() or any(
        "队长" == label.text() for label in workspace._picker.leader_card.findChildren(QLabel)
    )
    assert any("上次选择" == label.text() for label in workspace._picker.findChildren(QLabel))
    workspace._on_role_chosen("leader")
    labels = workspace.visible_menu_labels()
    assert labels[0] == "队伍管理"
    assert "파티" not in "".join(labels)
    assert tab.party_random_loot.text() == "随机拾取"
    assert "全员" not in tab.party_random_loot.text()
    assert tab.ops_attack_buttons["party"].text() == "跟随队长目标"
    assert tab.ops_attack_buttons["solo"].text() == "各自攻击"
    assert "炮台" not in tab.ops_attack_status.text()
    hangul = [label for label in labels if any("\uac00" <= ch <= "\ud7a3" for ch in label)]
    assert hangul == []
