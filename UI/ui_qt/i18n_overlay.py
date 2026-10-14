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
    },
}


def merge_ui_strings(language: str, base: dict[str, str]) -> dict[str, str]:
    """Return ``base`` plus Qt-only keys (overlay wins on conflict)."""
    key = language if language in _OVERLAY else "en"
    merged = dict(base)
    merged.update(_OVERLAY[key])
    return merged
