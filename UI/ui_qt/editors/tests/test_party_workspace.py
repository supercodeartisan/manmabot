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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QStyleOptionViewItem,
)

from ui_qt.widgets.step_spin import StepSpinBox

from settings.profile import Profile
from ui_qt.editors.move_tab import MoveTab
from ui_qt.editors.party_routine_panel import PartyRoutinePanel
from ui_qt.editors.party_tab import PartyTab
from ui_qt.editors.party_workspace import PartyWorkspace
from ui_qt.editors.task_editor import TaskEditor
from ui_qt.shell.schedule_shell import ScheduleShell
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
        "파티운영",
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
    assert workspace.tab._party_on() is False
    workspace._on_role_chosen("leader")
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

    bag = SettingsBag(profile)
    bag.set(
        "party",
        "routine",
        [
            {
                "id": "row-1",
                "map_id": "talking_island",
                "kind": "battle",
                "duration_minutes": 60,
                "selected_farms": ["point_1"],
                "farm_stays_s": {"point_1": 600.0},
                "coords_saved": True,
                "areas": [
                    {
                        "name": "마을 중간",
                        "shape": "area",
                        "x0": 215,
                        "y0": 295,
                        "x1": 299,
                        "y1": 356,
                    },
                    {"name": "point_1", "shape": "point", "x": 217, "y": 406},
                ],
                "patrol": [],
            }
        ],
    )
    hunt = PartyRoutinePanel(
        bag=bag,
        profile=profile,
        strings={**strings, "routine_area_set": "구역 · 완료"},
        language="ko",
    )
    setting = next(
        button
        for button in hunt.table.findChildren(QPushButton)
        if "구역" in button.text()
    )
    setting.click()
    opened = [
        widget
        for widget in QApplication.instance().topLevelWidgets()
        if isinstance(widget, QDialog) and widget.isVisible()
    ]
    assert opened
    opened[0].close()

    ops = tab.leader_sections["ops"]
    radios = [button.text() for button in ops.findChildren(QRadioButton)]
    assert radios[:3] == [
        "기존 사냥 계속하기",
        "현재 위치에서 대기하기",
        "지정 장소로 이동하기",
    ]
    assert "파티장 공격 대상 따라가기" in radios
    assert "support" not in tab.leader_sections
    assert not hasattr(tab, "party_lag_tiles")
    assert tab.member_sections["follow"].isAncestorOf(tab.party_follow_tiles)
    ops_text = " ".join(label.text() for label in ops.findChildren(QLabel))
    assert "파티원 따라가기 거리" not in ops_text
    assert "뒤처짐 판단 거리" not in ops_text
    assert not hasattr(tab, "party_near_tiles")
    assert "가까운 파티원 대기" not in ops_text

    before = copy.deepcopy(tab.bag.section("party") or {})
    ops.findChildren(QRadioButton)[0].setChecked(True)
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
        ]
    )
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


def test_member_support_saves_hit_mode_and_hp_threshold() -> None:
    from settings.settings_sections import normalize_settings

    workspace = _workspace("member")
    workspace._on_role_chosen("member")
    assert "지원 및 보호" in workspace.visible_menu_labels()
    assert "파티장 연결" in workspace.visible_menu_labels()
    assert "따라가기" in workspace.visible_menu_labels()
    tab = workspace.tab
    tab.party_enable.setChecked(True)
    assert "support" not in tab.leader_sections
    support = tab.member_sections["support"]
    assert [button.text() for button in tab.member_hit_buttons.values()] == [
        "즉시 지원",
        "현재 공격하던 몬스터 처치 후 지원",
    ]
    assert tab.member_hit_buttons["immediate"].isChecked()
    assert tab.member_hit_buttons["finish"].isChecked() is False
    tab.member_hit_buttons["finish"].setChecked(True)
    assert tab.member_hit_buttons["immediate"].isChecked() is False
    assert tab.bag.get_str("party", "hit_support", "") == "finish"
    tab.member_hit_buttons["immediate"].setChecked(True)
    assert tab.bag.get_str("party", "hit_support", "") == "immediate"
    member_text = " ".join(label.text() for label in support.findChildren(QLabel))
    assert "파티원 체력 위험 시 긴급 지원" not in member_text

    stored = normalize_settings({"party": dict(tab.bag.section("party"))})
    assert stored["party"]["hit_support"] == "immediate"
    reopened = PartyTab(bag=tab.bag, strings={}, language="ko", profile=None)
    assert reopened.member_hit_buttons["immediate"].isChecked()
    follow_text = " ".join(
        label.text() for label in tab.member_sections["follow"].findChildren(QLabel)
    )
    assert "파티원 피격 시 지원" not in follow_text
    map_text = " ".join(
        label.text() for label in tab.leader_sections["map"].findChildren(QLabel)
    )
    assert "파티원 피격 시 지원" not in map_text
    assert support.findChildren(QRadioButton)[0].group() is tab.member_hit_group


def _self_hidden(widget) -> bool:
    return widget.testAttribute(Qt.WidgetAttribute.WA_WState_Hidden)


def test_party_heal_is_visible_for_every_member() -> None:
    workspace = _workspace("member")
    tab = workspace.tab
    tab.party_enable.setChecked(True)
    titles = [
        box.title()
        for box in tab.member_sections["support"].findChildren(QGroupBox)
    ]
    assert titles[:2] == [
        "파티원 피격 시 지원",
        "파티 지원 마법",
    ]
    assert "파티원 체력 위험 시 긴급 지원" not in titles
    ops_titles = [
        box.title() for box in tab.leader_sections["ops"].findChildren(QGroupBox)
    ]
    assert "마법사가 다른 파티원을 힐" in ops_titles
    assert "support" not in tab.leader_sections
    assert tab.party_mage_heal_pct.value() == 80
    assert "파티원 힐 관리 (F06)" not in titles
    assert tab.member_support_magic_table.item(0, 2).text() == "힐"


def _support_row(tab: PartyTab, name: str) -> int:
    table = tab.member_support_magic_table
    for row in range(table.rowCount()):
        item = table.item(row, 2)
        if item is not None and item.text() == name:
            return row
    raise AssertionError(name)


def test_missing_party_heal_is_saved_and_an_explicit_off_stays_off() -> None:
    workspace = _workspace()
    tab = workspace.tab
    assert tab.bag.get("party", "mage_support_skills", {}).get("mage_0") is True
    heal = _support_row(tab, "힐")
    heal_box = tab.member_support_magic_table.cellWidget(heal, 0).findChild(QCheckBox)
    assert heal_box is not None and heal_box.isChecked() is True
    heal_box.setChecked(False)
    assert tab.bag.get("party", "mage_support_skills", {}).get("mage_0") is False
    tab._refresh_party_heal()
    heal_box = tab.member_support_magic_table.cellWidget(heal, 0).findChild(QCheckBox)
    assert heal_box is not None and heal_box.isChecked() is False
    heal_box.setChecked(True)
    assert tab.bag.get("party", "mage_support_skills", {}).get("mage_0") is True


def test_mage_party_support_skills_are_selectable_without_touching_solo() -> None:
    workspace = _workspace()
    tab = workspace.tab
    magic_before = copy.deepcopy(tab.bag.section("magic"))
    assert tab.member_support_magic_box.title() == "파티 지원 마법"
    assert _self_hidden(tab.member_support_magic_box) is False
    names = [
        tab.member_support_magic_table.item(row, 2).text()
        for row in range(tab.member_support_magic_table.rowCount())
    ]
    assert names == [
        "힐",
        "익스트라 힐",
        "그레이터 힐",
        "풀 힐",
        "힐 올",
        "큐어 포이즌",
        "리무브 커스",
        "리절렉션",
        "실드",
        "홀리 웨폰",
        "인챈트 웨폰",
        "블레스 웨폰",
        "블레스드 아머",
        "인챈트 덱스터리티",
        "인챈트 마이티",
        "헤이스트",
        "그레이터 헤이스트",
        "버서커스",
        "디크리즈 웨이트",
    ]
    heal = _support_row(tab, "힐")
    heal_box = tab.member_support_magic_table.cellWidget(heal, 0).findChild(QCheckBox)
    assert heal_box is not None and heal_box.isChecked() is True
    heal_detail = tab.member_support_magic_table.cellWidget(heal, 3).findChild(QLabel)
    assert isinstance(heal_detail, QLabel)
    assert heal_detail.alignment() & Qt.AlignmentFlag.AlignVCenter
    assert "HP를 조금 회복" in heal_detail.text()
    extra = _support_row(tab, "익스트라 힐")
    detail = tab.member_support_magic_table.cellWidget(extra, 3).findChild(QLabel)
    assert isinstance(detail, QLabel)
    assert "대상의 HP를 약간 회복" in detail.text()
    assert "파티원 한 명" in detail.text()
    haste = _support_row(tab, "헤이스트")
    haste_detail = tab.member_support_magic_table.cellWidget(haste, 3).findChild(QLabel)
    assert haste_detail is not None
    assert "지속 시간" in haste_detail.text()
    check = tab.member_support_magic_table.cellWidget(extra, 0).findChild(QCheckBox)
    assert check is not None and check.isChecked() is False
    check.setChecked(True)
    saved = tab.bag.get("party", "mage_support_skills", {})
    assert saved.get("mage_18") is True
    assert tab.bag.section("magic") == magic_before

    reopened = PartyTab(bag=tab.bag, strings={}, language="ko", profile=None)
    again = reopened.member_support_magic_table.cellWidget(
        _support_row(reopened, "익스트라 힐"), 0
    ).findChild(QCheckBox)
    assert again is not None and again.isChecked() is True

    tab.bag.set("magic", "class", "elf")
    tab._refresh_party_heal()
    assert _self_hidden(tab.member_support_magic_box) is True
    assert tab.bag.get("party", "mage_support_skills", {}).get("mage_18") is True

    wide = PartyTab(bag=SettingsBag(Profile()), strings={}, language="ko", profile=None)
    table = wide.member_support_magic_table
    row = _support_row(wide, "버서커스")
    table.resize(920, 200)
    table.apply_description_width()
    table.refit()
    wide_width = table.columnWidth(3)
    wide_height = table.rowHeight(row)
    table.resize(340, 200)
    table.apply_description_width()
    table.refit()
    assert table.columnWidth(3) < wide_width
    assert table.rowHeight(row) > wide_height
    assert table.columnWidth(0) == 56


def test_leader_succession_and_absence_settings() -> None:
    from ui_qt.debug.party_dashboard import monitor_failure_reason, monitor_state_text

    workspace = _workspace("leader")
    tab = workspace.tab
    tab.party_enable.setChecked(True)
    manage = tab.leader_sections["manage"]
    assert [box.title() for box in manage.findChildren(QGroupBox)][:2] == [
        "파티 관리",
        "파티장 자동 인계",
    ]
    assert tab.roster_table.columnCount() == 7
    tab.note_local_character("알파")
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
            {"name": "브라보", "role": "member", "loot": "none", "enabled": "1", "required": "1"},
            {"name": "찰리", "role": "member", "loot": "none", "enabled": "1", "required": "1"},
        ]
    )
    assert [
        tab.succession_combo.itemText(i) for i in range(tab.succession_combo.count())
    ] == ["선택 안 함", "브라보", "찰리"]
    assert _self_hidden(tab.succession_warning)
    tab.succession_enable.setChecked(True)
    assert _self_hidden(tab.succession_warning) is False
    tab.succession_combo.setCurrentIndex(tab.succession_combo.findData("브라보"))
    assert tab.bag.get_str("party", "successor_name", "") == "브라보"
    assert _self_hidden(tab.succession_warning)
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
            {"name": "찰리", "role": "member", "loot": "none", "enabled": "1", "required": "1"},
        ]
    )
    assert tab.bag.get_str("party", "successor_name", "") == ""
    assert tab.succession_combo.currentData() in ("", None)
    assert tab.succession_state.text() == "인계 상태: —"
    assert "인계 성공" not in tab.succession_state.text()
    assert tab._succession_state_label("running") == "인계 진행 중"
    assert tab._succession_state_label("ok") == "인계 성공"
    assert tab._succession_state_label("") == "—"

    ops = tab.leader_sections["ops"]
    assert [box.title() for box in ops.findChildren(QGroupBox)][:3] == [
        "파티장 부재 시 파티원 행동",
        "공격 대상 선택",
        "마법사가 다른 파티원을 힐",
    ]
    assert tab.absence_buttons["hunt"].isChecked()
    tab.absence_buttons["hold"].setChecked(True)
    assert tab.absence_buttons["hunt"].isChecked() is False
    assert tab.absence_buttons["move"].isChecked() is False
    assert tab.bag.get_str("party", "absence_action", "") == "hold"
    tab.absence_buttons["move"].setChecked(True)
    assert tab.bag.get_str("party", "absence_action", "") == "move"
    assert tab.absence_place.isEnabled() is False
    assert _self_hidden(tab.absence_place_pending) is False
    assert tab.absence_place.count() == 1
    routine = [
        {
            "id": "row1",
            "map_id": "map-a",
            "kind": "battle",
            "duration_minutes": 60,
            "areas": [
                {"name": "북쪽", "shape": "area", "x0": 1, "y0": 2, "x1": 3, "y1": 4},
            ],
            "patrol": [{"x": 9, "y": 8, "name": "길"}],
        }
    ]
    tab.bag.set("party", "routine", copy.deepcopy(routine))
    tab._fill_absence_places()
    assert tab.absence_place.isEnabled() is True
    labels = [tab.absence_place.itemText(i) for i in range(tab.absence_place.count())]
    assert labels == ["선택 안 함", "북쪽 (map-a)"]
    tab.absence_place.setCurrentIndex(1)
    saved_place = tab.bag.get_str("party", "absence_place", "")
    assert saved_place == "map-a|area|북쪽|1,2,3,4"
    assert tab.bag.get("party", "routine", None) == routine
    assert tab.absence_state.text() == "행동 상태: —"
    assert tab._absence_state_label("fail") == "행동 전환 실패"
    assert "행동 전환 실패" not in tab.absence_state.text()
    tab.t = {
        "party_ui_absence_state": "行动状态",
        "party_ui_fail_reason": "失败原因",
        "party_ui_succession_state": "交接状态",
    }
    tab.refresh_status_lines()
    assert tab.absence_state.text() == "行动状态: —"
    assert tab.absence_reason.text() == "失败原因: —"
    tab.t = {}
    tab.refresh_status_lines()
    assert tab.absence_state.text() == "행동 상태: —"
    assert tab.absence_reason.text() == "실패 사유: —"
    assert tab.succession_state.text() == "인계 상태: —"

    for section in tab.member_sections.values():
        text = " ".join(box.title() for box in section.findChildren(QGroupBox))
        assert "파티장 자동 인계" not in text
        assert "파티장 부재 시 파티원 행동" not in text
    workspace._on_role_chosen("member")
    assert workspace._stack.currentWidget() is workspace._member_page

    reopened = PartyTab(bag=tab.bag, strings={}, language="ko", profile=None)
    reopened.party_enable.setChecked(True)
    reopened.note_local_character("알파")
    assert reopened.succession_enable.isChecked() is True
    assert reopened.succession_combo.currentData() in ("", None)
    assert reopened.absence_buttons["move"].isChecked()
    assert reopened.absence_place.currentData() == saved_place
    assert monitor_state_text(None, "succession") == "—"
    assert monitor_state_text({"state": "ok"}, "succession") == "인계 성공"
    assert monitor_state_text({"state": "done"}, "succession") == "—"
    assert monitor_failure_reason({"state": "ok", "reason": "없음"}) == "—"
    assert monitor_failure_reason({"state": "fail", "reason": "대상 없음"}) == "대상 없음"


def test_roster_name_role_and_loot_edit_in_place() -> None:
    workspace = _workspace("leader")
    tab = workspace.tab
    tab._store_roster(
        [
            {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
            {"name": "브라보", "role": "member", "loot": "none", "enabled": "1", "required": "0"},
        ]
    )
    tab.bag.set("party", "successor_name", "알파")
    tab.bag.set(
        "party",
        "heal_targets",
        {"알파": {"enabled": True, "hp_percent": 40, "priority": 2}},
    )
    tab._fill_roster_table()
    table = tab.roster_table
    assert table.editTriggers() == table.EditTrigger.DoubleClicked
    assert table.columnWidth(0) == 34
    assert table.columnWidth(3) == 100
    name = table.item(0, 2)
    number = table.item(0, 1)
    enabled = table.item(0, 5)
    assert name.flags() & Qt.ItemFlag.ItemIsEditable
    assert not (number.flags() & Qt.ItemFlag.ItemIsEditable)
    assert enabled.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert not (enabled.flags() & Qt.ItemFlag.ItemIsEditable)

    name.setText("  찰리  ")
    assert tab._roster_rows()[0]["name"] == "찰리"
    assert name.text() == "찰리"
    assert tab.bag.get_str("party", "successor_name", "") == "찰리"
    assert "찰리" in tab.bag.get("party", "heal_targets", {})
    assert "알파" not in tab.bag.get("party", "heal_targets", {})

    name.setText("   ")
    assert tab._roster_rows()[0]["name"] == "찰리"
    assert name.text() == "찰리"
    name.setText("브라보")
    assert tab._roster_rows()[0]["name"] == "찰리"
    assert name.text() == "찰리"

    option = QStyleOptionViewItem()
    role_delegate = table.itemDelegateForColumn(3)
    role_index = table.model().index(0, 3)
    role_editor = role_delegate.createEditor(table.viewport(), option, role_index)
    assert [role_editor.itemData(i) for i in range(role_editor.count())] == [
        "member",
        "mage",
        "shopkeeper",
    ]
    role_editor.setCurrentIndex(role_editor.findData("member"))
    role_delegate.setModelData(role_editor, table.model(), role_index)
    assert tab._roster_rows()[0]["role"] == "member"
    assert table.item(0, 3).text() == "파티원"
    role_editor.setCurrentIndex(role_editor.findData("shopkeeper"))
    role_delegate.setModelData(role_editor, table.model(), role_index)
    assert tab._roster_rows()[0]["role"] == "shopkeeper"
    assert table.item(0, 3).text() == "상점"

    loot_delegate = table.itemDelegateForColumn(4)
    loot_index = table.model().index(0, 4)
    loot_editor = loot_delegate.createEditor(table.viewport(), option, loot_index)
    assert [loot_editor.itemData(i) for i in range(loot_editor.count())] == [
        "none",
        "responsible",
    ]
    loot_editor.setCurrentIndex(loot_editor.findData("responsible"))
    loot_delegate.setModelData(loot_editor, table.model(), loot_index)
    assert tab._roster_rows()[0]["loot"] == "responsible"
    assert table.item(0, 4).text() == "담당"

    enabled.setCheckState(Qt.CheckState.Unchecked)
    assert tab._roster_rows()[0]["enabled"] == "0"
    table.item(0, 6).setCheckState(Qt.CheckState.Checked)
    assert tab._roster_rows()[0]["required"] == "1"

    tab._fill_roster_table()
    box = table.cellWidget(0, 0).findChild(QCheckBox)
    assert box is not None
    box.setChecked(True)
    sent: list[str] = []
    tab._party_chat_submit = lambda: (lambda kind, who: sent.append(who) or "queued")  # type: ignore[method-assign]
    assert tab._invite_selected() == ["찰리"]
    assert sent == ["찰리"]

    reopened = PartyTab(bag=tab.bag, strings={}, language="ko", profile=None)
    saved = reopened._roster_rows()
    assert saved[0]["name"] == "찰리"
    assert saved[0]["role"] == "shopkeeper"
    assert saved[0]["loot"] == "responsible"
    assert saved[0]["enabled"] == "0"
    assert reopened.roster_table.item(0, 3).text() == "상점"
    assert reopened.roster_table.columnCount() == 7


_RUNNING = "실행 중에는 역할을 바꿀 수 없습니다."


def _reason_workspace(role: str) -> tuple[PartyWorkspace, dict[str, str]]:
    state = {"reason": ""}
    workspace = _workspace(role)
    workspace._lock_reason = lambda: state["reason"]
    return workspace, state


def _party_snapshot(tab: PartyTab) -> dict:
    party = tab.bag.section("party")
    return {
        "role": party.get("role"),
        "enabled": party.get("enabled"),
        "roster": copy.deepcopy(party.get("roster")),
        "routine": copy.deepcopy(party.get("routine")),
        "ws_port": party.get("ws_port"),
        "farm_mode": party.get("farm_mode"),
        "random_loot": party.get("random_loot"),
    }


def test_stopped_reentry_shows_the_picker_for_a_saved_leader() -> None:
    workspace, _state = _reason_workspace("leader")
    workspace._show_role("leader")
    workspace._locked = True
    workspace.present()
    assert workspace.current_page() == "picker"
    assert workspace._locked is False
    assert workspace.role_ready() is False
    assert workspace.saved_role() == "leader"
    assert workspace._picker.leader_card._saved.isHidden() is False
    assert workspace.tab._party_on() is False


def test_stopped_reentry_shows_the_picker_for_a_saved_member() -> None:
    workspace, _state = _reason_workspace("member")
    workspace._show_role("member")
    workspace._locked = True
    workspace.present()
    assert workspace.current_page() == "picker"
    assert workspace.role_ready() is False
    assert workspace.saved_role() == "member"
    assert workspace._picker.member_card._saved.isHidden() is False
    assert workspace.tab._party_on() is False


def test_leader_cycle_returns_to_the_picker_without_dropping_settings() -> None:
    workspace, state = _reason_workspace("leader")
    tab = workspace.tab
    roster = [
        {"name": "알파", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
    ]
    routine = [{"id": "row1", "map_id": "map-a", "kind": "battle", "duration_minutes": 60}]
    tab.bag.set("party", "roster", copy.deepcopy(roster))
    tab.bag.set("party", "routine", copy.deepcopy(routine))
    tab.bag.set("party", "ws_port", 9001)
    tab.bag.set("party", "farm_mode", "party")
    tab.bag.set("party", "random_loot", True)
    workspace._on_role_chosen("leader")
    assert workspace.role_ready() is True
    state["reason"] = _RUNNING
    workspace.set_locked(True, state["reason"])
    state["reason"] = ""
    workspace.set_locked(False, "")
    tab.set_master_enabled(False)
    kept = _party_snapshot(tab)
    workspace.present()
    assert workspace.current_page() == "picker"
    assert workspace.role_ready() is False
    assert workspace.saved_role() == "leader"
    assert _party_snapshot(tab) == kept
    workspace.set_locked(False, "")
    assert workspace.current_page() == "picker"


def test_member_cycle_returns_to_the_picker_without_dropping_settings() -> None:
    workspace, state = _reason_workspace("member")
    workspace._on_role_chosen("member")
    state["reason"] = _RUNNING
    workspace.set_locked(True, state["reason"])
    state["reason"] = ""
    workspace.set_locked(False, "")
    workspace.tab.set_master_enabled(False)
    workspace.present()
    assert workspace.current_page() == "picker"
    assert workspace.role_ready() is False
    assert workspace.saved_role() == "member"
    assert workspace.tab._party_on() is False


def test_solo_running_keeps_party_role_changes_locked() -> None:
    workspace, state = _reason_workspace("leader")
    state["reason"] = _RUNNING
    workspace.present()
    assert workspace.current_page() == "leader"
    assert workspace._back.isEnabled() is False
    assert workspace.role_ready() is False
    workspace._on_role_chosen("member")
    assert workspace.saved_role() == "leader"
    assert workspace.tab._party_on() is False


def test_running_party_survives_a_solo_view_and_return() -> None:
    workspace, state = _reason_workspace("leader")
    workspace._on_role_chosen("leader")
    state["reason"] = _RUNNING
    workspace.set_locked(True, state["reason"])
    workspace.tab.set_master_enabled(False)
    workspace.present()
    assert workspace.current_page() == "leader"
    assert workspace.role_ready() is True
    assert workspace.saved_role() == "leader"
    assert workspace._confirmed is True
    workspace.show_picker()
    assert workspace.current_page() == "leader"
    workspace._on_role_chosen("member")
    assert workspace.saved_role() == "leader"


def test_stopped_picker_survives_the_following_lock_sync() -> None:
    workspace, _state = _reason_workspace("leader")
    workspace._show_role("leader")
    workspace._locked = True
    workspace.present()
    assert workspace.current_page() == "picker"
    workspace.set_locked(False, "")
    assert workspace.current_page() == "picker"
    assert workspace.role_ready() is False
    workspace.set_locked(True, _RUNNING)
    assert workspace.current_page() == "leader"
    assert workspace._back.isEnabled() is False


def test_start_warns_until_a_role_card_enables_party() -> None:
    workspace, _state = _reason_workspace("leader")
    workspace.present()
    editor = TaskEditor.__new__(TaskEditor)
    editor.party_workspace = workspace
    editor.t = {}
    assert workspace.role_ready() is False
    assert editor.party_start_block_message() == "역할을 선택한 뒤 파티봇을 시작할 수 없습니다."
    assert workspace.tab._party_on() is False
    workspace._on_role_chosen("leader")
    assert workspace.role_ready() is True
    assert workspace.current_page() == "leader"
    assert workspace.tab._party_on() is True
    assert editor.party_start_block_message() is None


def test_repeated_stopped_entry_keeps_party_settings() -> None:
    workspace, _state = _reason_workspace("leader")
    tab = workspace.tab
    tab.bag.set(
        "party",
        "roster",
        [{"name": "알파", "role": "mage", "loot": "responsible", "enabled": "1", "required": "1"}],
    )
    tab.bag.set("party", "routine", [{"id": "row1", "map_id": "4", "kind": "battle"}])
    tab.bag.set("party", "ws_port", 8770)
    tab.set_master_enabled(False)
    before = _party_snapshot(tab)
    workspace._show_role("leader")
    workspace.present()
    workspace.present()
    assert workspace.current_page() == "picker"
    assert _party_snapshot(tab) == before


def test_party_entry_reads_the_live_lock_before_opening_settings() -> None:
    calls: list[str] = []

    class _Stack:
        def setCurrentIndex(self, index: int) -> None:
            calls.append(f"stack:{index}")

    class _Tab:
        def reload_from_bag(self) -> None:
            calls.append("reload")

    class _Workspace:
        def present(self) -> None:
            calls.append("present")

    editor = TaskEditor.__new__(TaskEditor)
    editor._settings_stack = _Stack()
    editor.party_tab = _Tab()
    editor.party_workspace = _Workspace()
    editor.sync_party_role_lock = lambda: calls.append("sync")
    editor.set_settings_mode("party")
    assert calls == ["stack:1", "sync", "reload", "present"]
    calls.clear()
    editor.set_settings_mode("solo")
    assert calls == ["stack:0"]


def test_solo_mode_button_turns_party_off_and_does_not_open_party() -> None:
    events: list[tuple[str, object]] = []

    class _Tab:
        def set_master_enabled(self, on: bool) -> None:
            events.append(("master", bool(on)))

    class _Editor:
        party_tab = _Tab()

        def set_settings_mode(self, mode: str) -> None:
            events.append(("mode", mode))

        def sync_party_role_lock(self) -> None:
            events.append(("sync", None))

    shell = ScheduleShell.__new__(ScheduleShell)
    shell.editor = _Editor()
    shell._apply_schedule_pane_mode = lambda: events.append(("pane", None))
    shell._paint_mode_buttons = lambda: events.append(("paint", None))
    shell._on_mode_button(0)
    assert ("master", False) in events
    assert ("mode", "solo") in events
    assert events.index(("sync", None)) < events.index(("mode", "solo"))
    assert all(name != "present" for name, _value in events)
    shell._on_mode_button(1)
    assert ("mode", "party") in events
    assert ("master", True) not in events


def test_supply_tables_split_self_shop_and_party_give() -> None:
    workspace = _workspace("leader")
    tab = workspace.tab
    titles = [
        box.title()
        for box in tab.leader_sections["supply"].findChildren(QGroupBox)
    ]
    assert titles[:2] == ["본인이 사는 것", "다른 파티원에게 주는 것"]
    assert tab.supply_self_table.columnCount() == 3
    assert tab.supply_others_table.columnCount() == 4
    assert [tab.supply_self_table.item(row, 0).text() for row in range(2)] == [
        "체력 물약",
        "은화살",
    ]
    assert tab.supply_others_table.item(0, 1).text() == "전원 (담당 제외)"
    assert tab.supply_others_table.item(1, 1).text() == "마법사 제외"
    tab.party_shopkeeper_hp_buy.setValue(30)
    tab.party_member_hp_min.setValue(7)
    assert tab.bag.get_int("party", "shopkeeper_hp_buy", 0) == 30
    assert tab.bag.get_int("party", "member_hp_min", 0) == 7
