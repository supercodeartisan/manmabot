"""Auto-use buffs chosen on the magic individual table.

Heal, Teleport, and attack magic stay on their existing paths. A checked
skill joins this list only when the spell catalog gives it a duration.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_LIST = Path(__file__).resolve().parents[1] / "data" / "catalog" / "list" / "korean" / "spell.json"
_DIGITS = re.compile(r"\d+")
_INSTANT = frozenset({"순간", "瞬間", "instant"})
_SKIP_KO = frozenset({"힐", "텔레포트"})


@dataclass(frozen=True)
class AutoBuff:
    skill_id: int
    priority: int
    names: tuple[str, ...]
    duration_s: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "priority": self.priority,
            "names": list(self.names),
            "duration_s": self.duration_s,
        }


def _fold_name(text: str) -> str:
    from hotbar.inspect import fold_hotbar_name

    raw = fold_hotbar_name(text)
    return raw.replace(" ", "").replace(":", "").replace("：", "").lower()


def duration_seconds(text: str) -> float | None:
    """Catalog duration in seconds. Instant and empty text are not buffs."""
    raw = str(text or "").strip()
    if not raw or raw in _INSTANT:
        return None
    digits = _DIGITS.findall(raw.replace(",", "").replace("，", ""))
    if not digits:
        return None
    # "1,200초" is one number once the thousands separator is gone.
    try:
        seconds = float("".join(digits))
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return seconds


@lru_cache(maxsize=1)
def _duration_by_id() -> dict[int, float]:
    out: dict[int, float] = {}
    if not _LIST.is_file():
        return out
    try:
        payload = json.loads(_LIST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    for row in payload.get("contents") or []:
        if not isinstance(row, dict):
            continue
        try:
            skill_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        seconds = duration_seconds(str(row.get("duration") or ""))
        if seconds is not None:
            out[skill_id] = seconds
    return out


def _selected(entry: dict[str, Any]) -> bool:
    """Checkbox after the individual table. Older saves used the On column."""
    if entry.get("auto_is_selection"):
        return bool(entry.get("auto"))
    return bool(entry.get("enabled"))


def _entry_for(magic: dict[str, Any], setting_key: str) -> dict[str, Any]:
    skills = magic.get("skills")
    entry: dict[str, Any] = {}
    if isinstance(skills, dict):
        raw = skills.get(setting_key)
        if isinstance(raw, dict):
            entry.update(raw)
    enabled = magic.get(f"skill_{setting_key}")
    auto = magic.get(f"skill_{setting_key}_auto")
    priority = magic.get(f"skill_{setting_key}_priority")
    if enabled is not None and "enabled" not in entry:
        entry["enabled"] = bool(enabled)
    if auto is not None and "auto" not in entry:
        entry["auto"] = bool(auto)
    if priority is not None and "priority" not in entry:
        try:
            entry["priority"] = int(priority)
        except (TypeError, ValueError):
            entry["priority"] = 1
    return entry


def auto_buffs_for_magic(magic: dict[str, Any] | None, ui_class: str) -> tuple[AutoBuff, ...]:
    """Checked lasting buffs for one class, lowest priority number first."""
    from settings.skill_catalog import load_skill_catalog

    character = str(ui_class or "").strip()
    if character not in ("elf", "mage", "knight", "royal"):
        return ()
    block = magic if isinstance(magic, dict) else {}
    durations = _duration_by_id()
    found: list[AutoBuff] = []
    for skill in load_skill_catalog().skills:
        if skill.ui_class != character:
            continue
        if skill.category == "attack_magic":
            continue
        if skill.ko in _SKIP_KO:
            continue
        seconds = durations.get(int(skill.skill_id))
        if seconds is None:
            continue
        entry = _entry_for(block, skill.setting_key)
        if not _selected(entry):
            continue
        try:
            priority = int(entry.get("priority") or 1)
        except (TypeError, ValueError):
            priority = 1
        names = tuple(
            dict.fromkeys(
                name
                for name in (skill.ko, skill.zh_tw, skill.zh_cn)
                if str(name or "").strip()
            )
        )
        found.append(
            AutoBuff(
                skill_id=int(skill.skill_id),
                priority=max(1, priority),
                names=names,
                duration_s=float(seconds),
            )
        )
    found.sort(key=lambda row: (row.priority, row.skill_id))
    return tuple(found)


def mage_attack_plan(magic: dict[str, Any] | None, ui_class: str) -> tuple[AutoBuff, ...]:
    """Checked mage attack spells, lowest priority number first.

    Other classes get an empty plan. Instant attacks have no catalog duration;
    ``duration_s`` stays 0 and is not used as a buff timer.
    """
    from settings.skill_catalog import load_skill_catalog

    character = str(ui_class or "").strip()
    if character != "mage":
        return ()
    block = magic if isinstance(magic, dict) else {}
    found: list[AutoBuff] = []
    for skill in load_skill_catalog().skills:
        if skill.ui_class != character or skill.category != "attack_magic":
            continue
        if skill.ko in _SKIP_KO:
            continue
        entry = _entry_for(block, skill.setting_key)
        if not _selected(entry):
            continue
        try:
            priority = int(entry.get("priority") or 1)
        except (TypeError, ValueError):
            priority = 1
        names = tuple(
            dict.fromkeys(
                name
                for name in (skill.ko, skill.zh_tw, skill.zh_cn)
                if str(name or "").strip()
            )
        )
        found.append(
            AutoBuff(
                skill_id=int(skill.skill_id),
                priority=max(1, priority),
                names=names,
                duration_s=0.0,
            )
        )
    found.sort(key=lambda row: (row.priority, row.skill_id))
    return tuple(found)


def press_for_buff(snap: Any, buff: AutoBuff) -> tuple[int, str] | None:
    """First live hotbar cell whose name is this buff. None when it is not on the bar."""
    from app._05_action.spell_box import SKILL_KEYS
    from hotbar.inspect import fold_hotbar_name, slot_to_box_key

    slots = snap.get("slots") if isinstance(snap, dict) else None
    if not isinstance(slots, list):
        return None
    wanted = {_fold_name(name) for name in buff.names if name}
    wanted.discard("")
    if not wanted:
        return None
    for raw in slots:
        if not isinstance(raw, dict):
            continue
        kr = fold_hotbar_name(
            str(raw.get("name") or raw.get("label") or raw.get("kr_name") or "")
        )
        zh = fold_hotbar_name(
            str(raw.get("name_tw") or raw.get("name_cn") or raw.get("zh_name") or "")
        )
        folded = {_fold_name(kr), _fold_name(zh)}
        if not (folded & wanted):
            continue
        try:
            box = int(raw.get("box") or 0)
        except (TypeError, ValueError):
            box = 0
        key = str(raw.get("key") or "").strip().lower()
        if box in (1, 2, 3) and key in SKILL_KEYS:
            return box, key
        try:
            index = int(raw.get("slot", -1))
        except (TypeError, ValueError):
            index = -1
        if 0 <= index <= 23:
            return slot_to_box_key(index)
    return None
