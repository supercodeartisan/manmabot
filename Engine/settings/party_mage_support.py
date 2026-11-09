"""Mage spells a party member can choose for other members.

The solo magic table does not read this list. Selection lives on the party
settings bag. Casting these spells is not decided here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_SPELL_DIR = Path(__file__).resolve().parents[1] / "data" / "catalog" / "list"
_INSTANT = frozenset({"순간", "瞬間", "瞬间", "instant"})


@dataclass(frozen=True)
class _SupportSpec:
    skill_id: int
    group: str
    note_ko: str
    note_zh: str


# Party-target support, including heal. Self-only spells
# (이뮨 투 함, 어드밴스 스피릿, 카운터 매직, 홀리 워크, 인비지블리티) stay out.
_SPECS: tuple[_SupportSpec, ...] = (
    _SupportSpec(
        0,
        "recovery",
        "파티원 한 명의 HP를 조금 회복합니다. 언데드에게 쓰면 피해가 됩니다.",
        "恢復一名隊員少量體力。對不死系會造成傷害。",
    ),
    _SupportSpec(
        18,
        "recovery",
        "힐보다 더 회복합니다. 파티원 한 명을 지정해 겁니다. 언데드에게 쓰면 피해가 됩니다.",
        "比初級治癒恢復更多。指定一名隊員施放。對不死系會造成傷害。",
    ),
    _SupportSpec(
        34,
        "recovery",
        "한 명의 HP를 더 크게 회복합니다. 언데드에게 쓰면 피해가 됩니다.",
        "恢復一名隊員更多體力。對不死系會造成傷害。",
    ),
    _SupportSpec(
        56,
        "recovery",
        "한 명을 지정하는 회복 중 양이 가장 큽니다. 언데드에게 쓰면 피해가 됩니다.",
        "指定一人的治癒裡恢復量最大。對不死系會造成傷害。",
    ),
    _SupportSpec(
        48,
        "recovery",
        "시전자를 뺀 파티원 전체의 HP를 한 번에 회복합니다. 한 명을 찍지 않습니다.",
        "除施法者外，同時恢復全體隊員的體力。不用指定一人。",
    ),
    _SupportSpec(
        8,
        "recovery",
        "대상에게 걸린 독을 풉니다. 체력은 채우지 않습니다.",
        "解除對象身上的毒。不恢復體力。",
    ),
    _SupportSpec(
        36,
        "recovery",
        "대상에게 걸린 저주를 풉니다. 체력은 채우지 않습니다.",
        "解除對象身上的詛咒。不恢復體力。",
    ),
    _SupportSpec(
        60,
        "recovery",
        "죽은 파티원의 시체를 부활시킵니다. 살아 있는 대상의 체력은 채우지 않습니다.",
        "復活已死亡隊員的屍體。不能用來補活人的體力。",
    ),
    _SupportSpec(
        2,
        "buff",
        "대상의 방어력을 올립니다. 파티원 한 명에게 겁니다.",
        "提升對象的防禦力。可施放在一名隊員身上。",
    ),
    _SupportSpec(
        7,
        "buff",
        "대상의 무기에 겁니다. 추가 대미지와 근거리 명중이 오르고, 언데드에게 추가 피해가 있습니다.",
        "施放在對象的武器上。追加傷害與近距離命中上升，對不死族有追加傷害。",
    ),
    _SupportSpec(
        11,
        "buff",
        "대상의 무기에 겁니다. 추가 대미지가 오릅니다.",
        "施放在對象的武器上。追加傷害上升。",
    ),
    _SupportSpec(
        47,
        "buff",
        "대상의 무기에 겁니다. 추가 대미지와 근거리 명중이 오릅니다.",
        "施放在對象的武器上。追加傷害與近距離命中上升。",
    ),
    _SupportSpec(
        20,
        "buff",
        "대상의 갑옷에 겁니다. 방어력이 오릅니다.",
        "施放在對象的盔甲上。防禦力上升。",
    ),
    _SupportSpec(
        25,
        "buff",
        "대상의 민첩을 올립니다. 파티원 한 명에게 겁니다.",
        "提升對象的敏捷。可施放在一名隊員身上。",
    ),
    _SupportSpec(
        41,
        "buff",
        "대상의 완력을 올립니다. 파티원 한 명에게 겁니다.",
        "提升對象的力量。可施放在一名隊員身上。",
    ),
    _SupportSpec(
        42,
        "buff",
        "대상의 이동 속도와 공격 속도를 올립니다. 파티원 한 명에게 겁니다.",
        "提升對象的移動速度與攻擊速度。可施放在一名隊員身上。",
    ),
    _SupportSpec(
        53,
        "buff",
        "이동 속도와 공격 속도를 올립니다. 헤이스트보다 오래 갑니다.",
        "提升移動速度與攻擊速度。持續時間比加速術更長。",
    ),
    _SupportSpec(
        54,
        "buff",
        "대상을 광전사화합니다. 근거리 대미지가 오르고, 방어는 나빠지며, 체력 자연 회복이 멈춥니다.",
        "使對象陷入狂戰士狀態。近距離傷害上升，防禦變差，且無法自然恢復體力。",
    ),
    _SupportSpec(
        13,
        "buff",
        "대상이 들고 있는 아이템 무게를 줄입니다. 파티원 한 명에게 겁니다.",
        "降低對象所持道具的重量。可施放在一名隊員身上。",
    ),
)


def _spell_path(language: str) -> Path:
    if str(language or "").lower().startswith("zh"):
        return _SPELL_DIR / "chinese" / "spell.json"
    return _SPELL_DIR / "korean" / "spell.json"


@lru_cache(maxsize=2)
def _spell_rows(language: str) -> dict[int, tuple[str, str]]:
    path = _spell_path(language)
    out: dict[int, tuple[str, str]] = {}
    if not path.is_file():
        return out
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    for row in payload.get("contents") or []:
        if not isinstance(row, dict):
            continue
        try:
            skill_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        out[skill_id] = (
            str(row.get("description") or "").strip(),
            str(row.get("duration") or "").strip(),
        )
    return out


def _duration_sentence(duration: str, language: str) -> str:
    text = str(duration or "").strip()
    if not text or text in _INSTANT:
        return ""
    if str(language or "").lower().startswith("zh"):
        return f"持續時間 {text}."
    return f"지속 시간 {text}."


def party_mage_support_rows(language: str = "ko") -> list[dict[str, str]]:
    """Catalog name plus the official line, a party note, and the duration."""
    from settings.skill_catalog import load_skill_catalog

    by_id = {
        int(skill.skill_id): skill
        for skill in load_skill_catalog().skills
        if skill.ui_class == "mage"
    }
    spells = _spell_rows("zh" if str(language or "").lower().startswith("zh") else "ko")
    rows: list[dict[str, str]] = []
    zh = str(language or "").lower().startswith("zh")
    for spec in _SPECS:
        skill = by_id.get(spec.skill_id)
        if skill is None:
            continue
        official, duration = spells.get(spec.skill_id, ("", ""))
        note = spec.note_zh if zh else spec.note_ko
        detail = " ".join(
            part
            for part in (official, note, _duration_sentence(duration, language))
            if part
        )
        rows.append(
            {
                "skill_id": str(spec.skill_id),
                "setting_key": skill.setting_key,
                "group": spec.group,
                "name": skill.label(language),
                "detail": detail,
            }
        )
    return rows
