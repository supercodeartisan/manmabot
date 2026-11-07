"""Extra UI strings required by the Qt shell (merged on top of ``schedule_i18n.tr``)."""

from __future__ import annotations

_OVERLAY: dict[str, dict[str, str]] = {
    "en": {
        "form_recovery": "Recovery",
        "form_return": "Return",
        "form_return_supplies": "Supplies / weight",
        "form_teleport": "Emergency teleport",
        "form_teleport_note": (
            "For PK and surround only. Low-HP teleport is set in HP action order."
        ),
        "form_recovery_note": "In combat recover order: heal -> potion",
        "form_options": "Options",
        "form_inventory": "Hotbar",
        "fix_inventory": "Hotbar",
        "delay_min": "min",
        "delay_max": "max",
        "mp_recover": "MP recover",
    },
    "ko": {
        "form_recovery": "회복",
        "form_return": "귀환",
        "form_return_supplies": "소모품 / 무게",
        "form_teleport": "긴급 텔레포트",
        "form_teleport_note": (
            "PK·포위 시에만 사용합니다. 체력 부족 텔레포트는 HP 행동 순서에서 설정합니다."
        ),
        "form_recovery_note": "전투 중 회복 우선순위: 힐 -> 물약",
        "form_options": "설정",
        "form_inventory": "핫바",
        "fix_inventory": "핫바",
        "delay_min": "최소",
        "delay_max": "최대",
        "mp_recover": "MP 회복",
        "party_ui_role_back": "역할 선택",
        "party_ui_leader": "파티장",
        "party_ui_member": "파티원",
        "party_ui_menu_manage": "파티 관리",
        "party_ui_menu_map": "사냥터 및 지도",
        "party_ui_menu_ops": "사냥 운영",
        "party_ui_menu_support": "지원 및 보호",
        "party_ui_menu_supply": "마을 및 보급",
        "party_ui_menu_loot": "아이템 및 루팅",
        "party_ui_menu_common": "공통 설정",
        "party_ui_menu_link": "파티장 연결",
        "party_ui_menu_follow": "따라가기",
        "party_ui_menu_assist": "공격 지원",
        "party_ui_menu_personal": "개인 행동 설정",
        "party_ui_menu_status": "파티 상태",
        "party_ui_picker_title": "파티봇 역할 선택",
        "party_ui_picker_sub": "파티봇을 어떤 역할로 실행할지 선택하세요.",
        "party_ui_last_choice": "마지막 선택",
        "party_ui_locked": "역할 변경이 잠겨 있습니다",
        "party_ui_leader_desc": "파티 전체의 사냥 계획과 운영을 관리합니다.",
        "party_ui_member_desc": "파티장에게 연결되어 지정된 정책에 따라 사냥합니다.",
        "party_ui_feat_roster": "파티원 관리",
        "party_ui_feat_map": "사냥터 및 순찰 지도",
        "party_ui_feat_hunt": "사냥 방식",
        "party_ui_feat_guard": "지원 및 보호",
        "party_ui_feat_loot": "아이템 및 루팅",
        "party_ui_feat_server": "파티장 서버 연결",
        "party_ui_feat_link": "연결 상태 확인",
        "party_ui_feat_follow": "따라가기 설정",
        "party_ui_feat_target": "공격 대상 추종",
        "party_ui_feat_assist": "어시스트 설정",
        "party_ui_lock_arming": "실행 준비 중에는 역할을 바꿀 수 없습니다.",
        "party_ui_lock_running": "실행 중에는 역할을 바꿀 수 없습니다.",
        "party_ui_lock_paused": "일시정지 중에는 역할을 바꿀 수 없습니다.",
        "party_ui_lock_stopping": "종료 중입니다. 마우스 입력이 해제된 뒤에 역할을 바꿀 수 없습니다.",
        "party_ui_start_need_role": "역할을 선택한 뒤 파티봇을 시작할 수 없습니다.",
        "party_ui_state_arming": "실행 준비",
        "party_ui_state_running": "실행 중",
        "party_ui_state_paused": "일시정지",
        "party_ui_state_stopping": "종료 중",
        "party_ui_state_stopped": "정지",
        "party_ui_motion": "이동 상태: {text}",
        "party_start_confirm": "파티봇을 시작할까요? 솔로봇 일정은 실행하지 않습니다.",
        "party_start_needs_game": "파티봇은 솔로봇 일정을 기다리지 않습니다. 게임이 켜진 뒤에 시작하세요.",
        "party_ui_point": "점 ({x}, {y})",
        "party_ui_area": "구역 ({x0}, {y0} ~ {x1}, {y1})",
        "party_ui_point_row": "{index}. 점  {note}",
        "party_ui_area_row": "{index}. 구역  {note}",
        "party_ui_absent_action": "파티장 부재 시 행동",
        "party_ui_absent_note": "화면 구성만 되어 있습니다. 선택값은 저장되지 않고 실행되지도 않습니다.",
        "party_ui_absent_title": "파티장 부재 시 운영",
        "party_ui_add": "추가",
        "party_ui_assist_distance": "어시스트 거리",
        "party_ui_assist_follow": "추종",
        "party_ui_assist_hint": "파티: 파티장이 공격하는 대상을 따라 공격합니다. 단독: 파티장 근처에서 자기 대상을 공격합니다.",
        "party_ui_assist_label": "파티장 공격 대상 추종",
        "party_ui_assist_own": "주변 대상 단독 공격",
        "party_ui_assist_title": "공격 지원",
        "party_ui_blank": "미입력",
        "party_ui_busy": "진행 중",
        "party_ui_col_job": "작업",
        "party_ui_col_number": "번호",
        "party_ui_col_reason": "사유",
        "party_ui_col_result": "결과",
        "party_ui_col_select": "선택",
        "party_ui_col_status": "상태",
        "party_ui_col_use": "사용",
        "party_ui_col_wait": "대기",
        "party_ui_common_title": "공통 설정",
        "party_ui_delete": "삭제",
        "party_ui_follow_distance": "따라가기 거리",
        "party_ui_follow_note": "이동 상태는 프로그램 상태만 표시합니다. 따라가는 중의 칸 거리는 실행 중 파티 동작이 처리하며, 이 화면은 그 값을 새로 만들지 않습니다.",
        "party_ui_follow_title": "따라가기",
        "party_ui_keep_hunting": "계속 사냥",
        "party_ui_hold": "제자리 대기",
        "party_ui_move_spot": "지정 장소로 이동",
        "party_ui_handover": "파티장 인계 사용",
        "party_ui_invite": "파티 초대",
        "party_ui_invite_busy": "초대 진행 중",
        "party_ui_invite_fail": "초대 실패",
        "party_ui_job_invite": "초대",
        "party_ui_job_kick": "추방",
        "party_ui_join_note": "파티 참여 상태는 실행 중 파티 메모리로 확인합니다. 이 화면은 참여 여부를 새로 판단하지 않습니다.",
        "party_ui_kick": "파티 추방",
        "party_ui_kick_fail": "추방 실패",
        "party_ui_lan_ip": "내부 IP",
        "party_ui_leader_info": "파티장 정보: {shown} · 포트 {port}",
        "party_ui_leader_ip": "파티장 IP",
        "party_ui_leader_state": "파티장 상태: {shown} · 포트 {port}",
        "party_ui_leader_unknown": "파티장 상태: 미입력",
        "party_ui_local_hint": "파티장 봇을 먼저 시작하세요. 이 PC에서 localhost로 확인한 뒤 LAN IP로 확인합니다.",
        "party_ui_local_test": "로컬 연결 테스트",
        "party_ui_loot_col": "루팅",
        "party_ui_loot_hint": "무작위 루팅: 파티장과 마법사를 제외하고 가장 가까운 파티원이 파티 드랍을 줍습니다. 끄면 명단에서 담당으로 표시된 줄만 자기 드랍을 줍습니다. 파티장이 이동 중일 때 파티원은 줍지 않습니다.",
        "party_ui_loot_none": "없음",
        "party_ui_loot_owner": "담당",
        "party_ui_loot_title": "아이템 및 루팅",
        "party_ui_map_pending": "프로필이 연결되면 기존 파티 지도 편집기가 이 자리에 열립니다.",
        "party_ui_motion_idle": "이동 상태: 정지",
        "party_ui_name": "이름",
        "party_ui_personal_hint": "따라가기, 정지, 어시스트, 사냥 방식은 이 봇의 개인 설정입니다. 루팅 규칙은 파티장에게서 받습니다.",
        "party_ui_personal_now": "현재 개인 설정 · 따라가기 {follow}칸, 정지 {stop}칸, 어시스트 {assist}칸, 공격 {mode}",
        "party_ui_personal_title": "개인 행동 설정",
        "party_ui_policy_reserved": "파티장이 보낸 정책은 이후 이 자리에 읽기 전용으로 표시합니다.",
        "party_ui_policy_title": "파티장 정책 요약",
        "party_ui_port": "포트",
        "party_ui_random_loot": "무작위 루팅",
        "party_ui_result_fail": "실패",
        "party_ui_role": "역할",
        "party_ui_roster_title": "파티 관리",
        "party_ui_seat_mage": "마법사",
        "party_ui_seat_member": "파티원",
        "party_ui_seat_shop": "상점",
        "party_ui_status_title": "파티 상태",
        "party_ui_status_untested": "연결 상태: 아직 테스트하지 않음",
        "party_ui_stop_distance": "정지 거리",
        "party_ui_successor": "차기 파티장",
        "party_ui_successor_none": "선택 안 함",
        "party_ui_supply_note": "보급 담당은 파티 관리의 자리 역할에서 상점 역할로 지정합니다. 별도 보급 화면은 아직 없고, 기존 파티원 명단은 그대로 유지됩니다.",
        "party_ui_supply_title": "마을 및 보급",
        "party_ui_target_follow": "파티장 공격 대상 따라가기",
        "party_ui_target_follow_note": "파티장이 공격하는 몬스터를 파티원도 같이 공격합니다.",
        "party_ui_target_random": "랜덤 공격",
        "party_ui_target_random_note": "각 파티원이 주변의 공격 가능한 몬스터를 따로 고릅니다.",
        "party_ui_target_readonly": "읽기 전용 · 엔진 연결 전. 다른 PC의 파티장 선택은 아직 수신되지 않습니다.",
        "party_ui_target_saved": "설정 저장 가능 · 파티원 전달은 엔진 연결 전",
        "party_ui_target_title": "공격 대상 선택",
        "party_ui_test": "연결 테스트",
        "party_ui_test_lan": "LAN IP 테스트",
        "party_ui_test_localhost": "localhost 테스트",
    },
    "zh": {
        "form_recovery": "恢复",
        "form_return": "回城",
        "form_return_supplies": "补给 / 负重",
        "form_teleport": "紧急传送",
        "form_teleport_note": "仅用于被玩家攻击或包围。低 HP 传送请在 HP 行动顺序中设置。",
        "form_recovery_note": "战斗中恢复顺序：治愈 -> 药水",
        "form_options": "设置",
        "form_inventory": "快捷栏",
        "fix_inventory": "快捷栏",
        "delay_min": "最小",
        "delay_max": "最大",
        "mp_recover": "MP 恢复",
        "party_ui_role_back": "选择角色",
        "party_ui_leader": "队长",
        "party_ui_member": "队员",
        "party_ui_menu_manage": "队伍管理",
        "party_ui_menu_map": "猎场与地图",
        "party_ui_menu_ops": "狩猎安排",
        "party_ui_menu_support": "支援与保护",
        "party_ui_menu_supply": "村庄补给",
        "party_ui_menu_loot": "物品与拾取",
        "party_ui_menu_common": "共用设置",
        "party_ui_menu_link": "连接队长",
        "party_ui_menu_follow": "跟随",
        "party_ui_menu_assist": "攻击协助",
        "party_ui_menu_personal": "个人行动",
        "party_ui_menu_status": "队伍状态",
        "party_ui_picker_title": "选择组队角色",
        "party_ui_picker_sub": "请选择这台机器人在队伍中的角色。",
        "party_ui_last_choice": "上次选择",
        "party_ui_locked": "角色切换已锁定",
        "party_ui_leader_desc": "管理全队的狩猎计划与运行。",
        "party_ui_member_desc": "连接队长，并按收到的策略狩猎。",
        "party_ui_feat_roster": "队员管理",
        "party_ui_feat_map": "猎场与巡逻地图",
        "party_ui_feat_hunt": "狩猎方式",
        "party_ui_feat_guard": "支援与保护",
        "party_ui_feat_loot": "物品与拾取",
        "party_ui_feat_server": "连接队长服务",
        "party_ui_feat_link": "查看连接状态",
        "party_ui_feat_follow": "跟随设置",
        "party_ui_feat_target": "跟随队长目标",
        "party_ui_feat_assist": "协助设置",
        "party_ui_lock_arming": "准备运行时不能切换角色。",
        "party_ui_lock_running": "运行中不能切换角色。",
        "party_ui_lock_paused": "暂停中不能切换角色。",
        "party_ui_lock_stopping": "正在停止。鼠标输入解除后才能切换角色。",
        "party_ui_start_need_role": "请先选择角色，再启动组队机器人。",
        "party_ui_state_arming": "准备运行",
        "party_ui_state_running": "运行中",
        "party_ui_state_paused": "已暂停",
        "party_ui_state_stopping": "正在停止",
        "party_ui_state_stopped": "已停止",
        "party_ui_motion": "移动状态：{text}",
        "party_start_confirm": "要启动组队机器人吗？不会执行单人日程。",
        "party_start_needs_game": "组队机器人不会等待单人日程。请先启动游戏。",
        "party_ui_point": "点 ({x}, {y})",
        "party_ui_area": "区域 ({x0}, {y0} ~ {x1}, {y1})",
        "party_ui_point_row": "{index}. 点  {note}",
        "party_ui_area_row": "{index}. 区域  {note}",
        "party_ui_link_title": "连接队长",
        "party_ui_leader_ip": "队长 IP",
        "party_ui_port": "端口",
        "party_ui_test": "测试连接",
        "party_ui_status_untested": "连接状态：尚未测试",
        "party_ui_follow_title": "跟随",
        "party_ui_follow_distance": "跟随距离",
        "party_ui_stop_distance": "停止距离",
        "party_ui_motion_idle": "移动状态：已停止",
        "party_ui_follow_note": "移动状态只显示程序状态。跟随中的格数由运行中的队伍动作处理，此画面不另行计算。",
        "party_ui_assist_title": "攻击协助",
        "party_ui_assist_hint": "跟随：攻击队长正在攻击的目标。单独：在队长附近攻击自己的目标。",
        "party_ui_assist_label": "跟随队长目标",
        "party_ui_assist_follow": "跟随",
        "party_ui_assist_own": "攻击附近目标",
        "party_ui_assist_distance": "协助距离",
        "party_ui_personal_title": "个人行动",
        "party_ui_personal_hint": "跟随、停止、协助和狩猎方式是这台机器人自己的设置。拾取规则由队长下发。",
        "party_ui_policy_title": "队长策略摘要",
        "party_ui_policy_reserved": "队长发来的策略以后在这里只读显示。",
        "party_ui_status_title": "队伍状态",
        "party_ui_leader_unknown": "队长状态：未填写",
        "party_ui_join_note": "是否已加入队伍，由运行中的队伍内存确认。此画面不另行判断。",
        "party_ui_absent_title": "队长不在时",
        "party_ui_absent_note": "这里只是画面。选项不会保存，也不会执行。",
        "party_ui_absent_action": "队长不在时的行动",
        "party_ui_keep_hunting": "继续狩猎",
        "party_ui_hold": "原地等待",
        "party_ui_move_spot": "移动到指定地点",
        "party_ui_handover": "使用队长交接",
        "party_ui_successor": "下一任队长",
        "party_ui_successor_none": "不选择",
        "party_ui_target_title": "攻击目标",
        "party_ui_target_follow": "跟随队长目标",
        "party_ui_target_follow_note": "队员一起攻击队长正在攻击的怪物。",
        "party_ui_target_random": "各自攻击",
        "party_ui_target_random_note": "队长和每名队员各自选择附近可攻击的怪物。",
        "party_ui_target_saved": "可以保存设置 · 发给队员的功能尚未连接引擎",
        "party_ui_target_readonly": "只读 · 引擎未连接。尚未收到其他电脑上队长的选择。",
        "party_ui_map_pending": "连接配置后，现有的队伍地图编辑器会显示在这里。",
        "party_ui_supply_title": "村庄补给",
        "party_ui_supply_note": "补给负责人在队伍管理的席位里指定为商店角色。还没有单独的补给画面，现有队员名册保持不变。",
        "party_ui_loot_title": "物品与拾取",
        "party_ui_loot_hint": "随机拾取：除队长和法师外，距离最近的队员拾取队伍掉落。关闭后，只有名册中标为负责的队员拾取自己的掉落。队长移动时队员不拾取。",
        "party_ui_random_loot": "随机拾取",
        "party_ui_loot_none": "无",
        "party_ui_loot_owner": "负责",
        "party_ui_common_title": "共用设置",
        "party_ui_lan_ip": "内网 IP",
        "party_ui_local_test": "本地连接测试",
        "party_ui_local_hint": "请先启动队长机器人。先在这台电脑用 localhost 确认，再用局域网 IP 确认。",
        "party_ui_test_localhost": "测试 localhost",
        "party_ui_test_lan": "测试局域网 IP",
        "party_ui_roster_title": "队伍管理",
        "party_ui_name": "名字",
        "party_ui_role": "角色",
        "party_ui_loot_col": "拾取",
        "party_ui_add": "添加",
        "party_ui_delete": "删除",
        "party_ui_col_select": "选择",
        "party_ui_col_number": "编号",
        "party_ui_col_use": "使用",
        "party_ui_col_wait": "待命",
        "party_ui_invite": "邀请入队",
        "party_ui_kick": "移出队伍",
        "party_ui_col_job": "操作",
        "party_ui_col_status": "状态",
        "party_ui_col_result": "结果",
        "party_ui_col_reason": "原因",
        "party_ui_seat_member": "队员",
        "party_ui_seat_mage": "法师",
        "party_ui_seat_shop": "商店",
        "party_ui_job_invite": "邀请",
        "party_ui_job_kick": "移出",
        "party_ui_invite_busy": "邀请处理中",
        "party_ui_busy": "处理中",
        "party_ui_invite_fail": "邀请失败",
        "party_ui_kick_fail": "移出失败",
        "party_ui_result_fail": "失败",
        "party_ui_leader_info": "队长信息：{shown} · 端口 {port}",
        "party_ui_leader_state": "队长状态：{shown} · 端口 {port}",
        "party_ui_blank": "未填写",
        "party_ui_personal_now": "当前个人设置 · 跟随 {follow} 格，停止 {stop} 格，协助 {assist} 格，攻击 {mode}",
        "party_ui_mon_name": "名字",
        "party_ui_mon_invite": "邀请",
        "party_ui_mon_name_hint": "角色名",
        "party_ui_mon_invite_tip": "在机器人线程排队发送 /초대 名字。与自动邀请同一路径。排队成功不等于已经加入队伍。",
        "party_ui_mon_accept_tip": "在机器人线程排队发送 Y 和 Enter。与自动接受同一路径。",
    },
}


_bind_depth = 0
_recent: list[tuple[str, str]] = []


def bind_tx_depth() -> int:
    return _bind_depth


def push_tx_bind() -> None:
    global _bind_depth
    _bind_depth += 1


def pop_tx_bind() -> None:
    global _bind_depth
    _bind_depth = max(0, _bind_depth - 1)
    if _bind_depth == 0:
        _recent.clear()


def note_tx(key: str, text: str) -> None:
    """Remember a phrase just handed to a widget constructor."""
    if _bind_depth and text:
        _recent.append((key, text))
        if len(_recent) > 48:
            del _recent[:-48]


def take_tx(text: str) -> str | None:
    """Claim the newest remembered key whose phrase equals ``text``."""
    if not text:
        return None
    for index in range(len(_recent) - 1, -1, -1):
        key, value = _recent[index]
        if value == text:
            del _recent[index]
            return key
    return None


def tx(strings: dict | None, key: str, fallback: str) -> str:
    """Translated label, or the Korean fallback when the key is absent."""
    value = fallback
    if isinstance(strings, dict):
        found = strings.get(key)
        if isinstance(found, str) and found:
            value = found
    note_tx(key, value)
    return value


class TxDict(dict):
    """String table that remembers which key produced a phrase during construction."""

    def __getitem__(self, key: str) -> str:
        value = super().__getitem__(key)
        if isinstance(key, str) and isinstance(value, str):
            note_tx(key, value)
        return value

    def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
        if isinstance(key, str) and key in self:
            value = super().get(key)
            if isinstance(value, str):
                note_tx(key, value)
            return value
        return super().get(key, default)


def merge_ui_strings(language: str, base: dict[str, str]) -> TxDict:
    """Return ``base`` plus Qt-only keys (overlay wins on conflict)."""
    key = language if language in _OVERLAY else "en"
    merged = TxDict(base)
    merged.update(_OVERLAY[key])
    return merged
