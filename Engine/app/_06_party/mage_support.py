"""Checked party-support spells for other members.

Heal, cure, resurrection, and lasting buffs. One cast per call. Buff remain
comes from a fresh party-buff report when one exists, otherwise from the
cast ledger. The solo magic table is not read here.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .hud_heal import (
    HEAL_RANGE_TILES,
    _on_mage_screen,
    _stand_in_reach,
    guid_int,
    heal_nav_delta,
    heal_nav_pair,
)

# Strongest single-target heal first.
_HEAL_RANK = (56, 34, 18, 0)
_HEAL_ALL = 48
_CURE = 8
_CURSE = 36
_RESURRECT = 60
# One spell per group, strongest first. The others stack.
# Shield, greater haste, and decrease weight are self-only and stay off this list.
_WEAPON = (47, 11, 7)
_HASTE = (42,)
_OWN_BUFFS = (20, 25, 41, 54)
_BUFF_IDS = _WEAPON + _HASTE + _OWN_BUFFS
# Same window solo buffs use before a recast.
_RECAST_S = 10.0
# A report older than this is not evidence the buff is missing.
_REPORT_TRUST_S = 20.0
_MISS_LIMIT = 3
_PARK_S = 30.0
_POISON = ("독", "포이즌", "poison", "중독")
_CURSE_WORDS = ("커스", "저주", "curse")


def empty_ledger() -> dict[str, Any]:
    return {"maps": {}, "spells": {}}


def _fold(text: str) -> str:
    return str(text or "").replace(" ", "").replace(":", "").replace("：", "").lower()


def _names(skill_id: int) -> tuple[str, ...]:
    from settings.skill_catalog import load_skill_catalog

    for skill in load_skill_catalog().skills:
        if skill.ui_class == "mage" and int(skill.skill_id) == int(skill_id):
            return tuple(
                name
                for name in (skill.ko, skill.zh_tw, skill.zh_cn)
                if str(name or "").strip()
            )
    return ()


def _label(skill_id: int) -> str:
    names = _names(skill_id)
    return names[0] if names else str(skill_id)


def _duration(skill_id: int) -> float:
    from settings.auto_buffs import _duration_by_id

    found = _duration_by_id().get(int(skill_id))
    if found is not None and float(found) > 0:
        return float(found)
    return 1200.0


def _press(hotbar: Any, skill_id: int) -> Optional[tuple[int, str]]:
    from settings.auto_buffs import AutoBuff, press_for_buff

    names = _names(skill_id)
    if not names:
        return None
    return press_for_buff(
        hotbar,
        AutoBuff(
            skill_id=int(skill_id),
            priority=1,
            names=names,
            duration_s=_duration(skill_id),
        ),
    )


def _rows(slots: Any) -> dict[int, dict[str, Any]]:
    boxes: dict[int, dict[str, Any]] = {}
    if not isinstance(slots, list):
        return boxes
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        gid = guid_int(slot.get("guid"))
        row = slot.get("row")
        if gid is None or not isinstance(row, dict):
            continue
        boxes[gid] = row
    return boxes


def _click(row: dict[str, Any]) -> tuple[int, int]:
    return (
        (int(row["x0"]) + int(row["x1"])) // 2,
        (int(row["y0"]) + int(row["y1"])) // 2,
    )


def _report_index(reports: Any, now: float) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not isinstance(reports, list):
        return found
    for row in reports:
        if not isinstance(row, dict):
            continue
        name = str(row.get("from") or "").strip()
        if not name:
            continue
        try:
            noted = float(row.get("noted_at") or 0.0)
        except (TypeError, ValueError):
            noted = 0.0
        if noted <= 0.0 or (now - noted) > _REPORT_TRUST_S:
            continue
        found[name.casefold()] = row
    return found


def _effect_hit(effects: Any, skill_id: int, names: tuple[str, ...]) -> Optional[float]:
    wanted = {_fold(name) for name in names if name}
    if not isinstance(effects, list):
        return None
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        try:
            skill = int(effect.get("skill") or 0)
        except (TypeError, ValueError):
            skill = 0
        if skill and skill == int(skill_id):
            try:
                return float(effect.get("duration") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        if _fold(str(effect.get("name") or "")) in wanted:
            try:
                return float(effect.get("duration") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return None


def _ailment(report: Optional[dict[str, Any]], words: tuple[str, ...], flag: str = "") -> bool:
    if not isinstance(report, dict):
        return False
    if flag and bool(report.get(flag)):
        return True
    blobs: list[str] = []
    for key in ("buffs", "debuffs"):
        for effect in report.get(key) or []:
            if isinstance(effect, dict):
                blobs.append(_fold(str(effect.get("name") or "")))
    for word in words:
        needle = _fold(word)
        if any(needle and needle in blob for blob in blobs):
            return True
    return False


def _spell_row(ledger: dict[str, Any], guid: int, skill_id: int) -> dict[str, Any]:
    spells = ledger.setdefault("spells", {})
    key = f"{int(guid)}:{int(skill_id)}"
    row = spells.get(key)
    if not isinstance(row, dict):
        row = {}
        spells[key] = row
    return row


def _drop_member(ledger: dict[str, Any], guid: int) -> None:
    prefix = f"{int(guid)}:"
    spells = ledger.setdefault("spells", {})
    for key in [key for key in spells if str(key).startswith(prefix)]:
        spells.pop(key, None)


def sync_member_ledgers(ledger: dict[str, Any], members: Any) -> None:
    """Drop a member's buff clock when they die or change maps."""
    if not isinstance(members, list):
        return
    maps = ledger.setdefault("maps", {})
    for member in members:
        if not isinstance(member, dict):
            continue
        gid = guid_int(member.get("guid"))
        if gid is None:
            continue
        try:
            hp = int(member.get("hp_pct"))
        except (TypeError, ValueError):
            hp = None
        try:
            map_id = int(member.get("map_id"))
        except (TypeError, ValueError):
            map_id = None
        if hp is not None and hp <= 0:
            _drop_member(ledger, gid)
            maps.pop(str(gid), None)
            continue
        if map_id is None:
            continue
        prev = maps.get(str(gid))
        if prev is not None and int(prev) != map_id:
            _drop_member(ledger, gid)
        maps[str(gid)] = map_id


def _remain(
    ledger: dict[str, Any],
    guid: int,
    skill_id: int,
    report: Optional[dict[str, Any]],
    now: float,
) -> float:
    """Seconds left. Missing is 0. A parked skill stays out of the queue."""
    row = _spell_row(ledger, guid, skill_id)
    try:
        park = float(row.get("park_until") or 0.0)
    except (TypeError, ValueError):
        park = 0.0
    if park > now:
        return 1.0e9
    if park and park <= now:
        row["misses"] = 0
        row["park_until"] = 0.0
    names = _names(skill_id)
    noted = None
    reported = None
    if isinstance(report, dict):
        try:
            noted = float(report.get("noted_at") or 0.0)
        except (TypeError, ValueError):
            noted = None
        reported = _effect_hit(report.get("buffs"), skill_id, names)
    fresh = noted is not None and noted > 0.0 and (now - noted) <= _REPORT_TRUST_S
    try:
        cast_at = float(row.get("at") or 0.0)
    except (TypeError, ValueError):
        cast_at = 0.0
    if fresh and noted is not None:
        if cast_at > noted:
            try:
                duration = float(row.get("duration") or _duration(skill_id))
            except (TypeError, ValueError):
                duration = _duration(skill_id)
            return max(0.0, duration - (now - cast_at))
        if reported is None:
            try:
                counted = float(row.get("counted_at") or 0.0)
            except (TypeError, ValueError):
                counted = 0.0
            if cast_at > 0.0 and cast_at < noted and counted < noted:
                misses = int(row.get("misses") or 0) + 1
                row["misses"] = misses
                row["counted_at"] = noted
                if misses >= _MISS_LIMIT:
                    row["park_until"] = now + _PARK_S
                    row["at"] = 0.0
                    return 1.0e9
            return 0.0
        row["misses"] = 0
        row["park_until"] = 0.0
        row["at"] = float(noted)
        row["duration"] = float(reported)
        return max(0.0, float(reported) - max(0.0, now - float(noted)))
    if cast_at > 0.0:
        try:
            duration = float(row.get("duration") or _duration(skill_id))
        except (TypeError, ValueError):
            duration = _duration(skill_id)
        return max(0.0, duration - (now - cast_at))
    return 0.0


def remember_cast(
    ledger: dict[str, Any],
    guid: int,
    skill_id: int,
    now: float,
) -> None:
    row = _spell_row(ledger, guid, skill_id)
    row["at"] = float(now)
    row["duration"] = _duration(skill_id)


def _others(
    members: Any,
    *,
    self_guid: Any,
    self_name: str,
) -> list[dict[str, Any]]:
    own = guid_int(self_guid)
    own_name = str(self_name or "").strip()
    found: list[dict[str, Any]] = []
    if not isinstance(members, list):
        return found
    for member in members:
        if not isinstance(member, dict):
            continue
        gid = guid_int(member.get("guid"))
        name = str(member.get("name") or "").strip()
        if own is not None and gid == own:
            continue
        if own_name and name == own_name:
            continue
        found.append(member)
    return found


def _hp(member: dict[str, Any]) -> Optional[int]:
    try:
        return int(member.get("hp_pct"))
    except (TypeError, ValueError):
        return None


def _place(
    member: dict[str, Any],
    here: Any,
) -> Optional[tuple[int, int, int, int, int]]:
    if here is None:
        return None
    return heal_nav_pair(
        member, here_x=here[0], here_y=here[1], here_map=here[2]
    )


def _line_open(pair: tuple[int, int, int, int, int]) -> bool:
    """True when no wall or fence sits between the mage and the member.

    Missing terrain stays open, the same rule as an attack line. Another
    character's body is not a blocker.
    """
    from app._04_decision.dungeon import line_of_sight_clear
    from app._04_decision.nav_config import get_terrain_map

    terrain = get_terrain_map()
    if terrain is None:
        return True
    mx, my, qx, qy, _dist = pair
    return line_of_sight_clear(terrain, (int(qx), int(qy)), (int(mx), int(my)))


def _buff_ids(checked: set[int]) -> list[int]:
    chosen: list[int] = []
    for group in (_WEAPON, _HASTE):
        for skill_id in group:
            if skill_id in checked:
                chosen.append(skill_id)
                break
    for skill_id in _OWN_BUFFS:
        if skill_id in checked:
            chosen.append(skill_id)
    return chosen


def _cast(
    *,
    spell: str,
    skill_id: int,
    member: Optional[dict[str, Any]],
    dist: Optional[int],
    press: tuple[int, str],
    click: Optional[tuple[int, int]],
    hp_pct: int = 0,
) -> dict[str, Any]:
    name = ""
    guid = 0
    if member is not None:
        name = str(member.get("name") or "").strip()
        guid = int(guid_int(member.get("guid")) or 0)
    return {
        "kind": "cast",
        "spell": spell,
        "skill_id": int(skill_id),
        "label": _label(skill_id),
        "name": name,
        "guid": guid,
        "hp_pct": int(hp_pct),
        "dist": dist,
        "click_x": None if click is None else int(click[0]),
        "click_y": None if click is None else int(click[1]),
        "goal": None,
        "box": int(press[0]),
        "key": str(press[1]),
    }


def _step(member: dict[str, Any], pair: tuple[int, int, int, int, int], reach: int) -> dict[str, Any]:
    mx, my, _qx, _qy, dist = pair
    goal = _stand_in_reach(mx, my, pair[2], pair[3], int(reach))
    return {
        "kind": "step",
        "spell": "",
        "skill_id": 0,
        "label": "",
        "name": str(member.get("name") or "").strip(),
        "guid": int(guid_int(member.get("guid")) or 0),
        "hp_pct": int(_hp(member) or 0),
        "dist": int(dist),
        "click_x": None,
        "click_y": None,
        "goal": goal,
        "box": None,
        "key": "",
    }


def choose_party_support(
    members: Any,
    slots: Any,
    *,
    self_guid: Any = None,
    self_name: str = "",
    here: Any = None,
    checked: Any = None,
    hotbar: Any = None,
    reports: Any = None,
    ledger: Optional[dict[str, Any]] = None,
    now: Optional[float] = None,
    below: int = 80,
    cast_only: bool = False,
    heals_only: bool = False,
    allow_heals: bool = True,
    reach: int = HEAL_RANGE_TILES,
) -> tuple[Optional[dict[str, Any]], str]:
    """The one party-support action for this tick, or ``(None, note)``.

    Heal, heal all, and buffs cast only when the straight line is open.
    A wall or a fence holds the cast. Cure, curse, and resurrect stay on distance.
    """
    book = ledger if isinstance(ledger, dict) else empty_ledger()
    clock = time.time() if now is None else float(now)
    ids = set(checked or ())
    sync_member_ledgers(book, members)
    boxes = _rows(slots)
    people = _others(members, self_guid=self_guid, self_name=self_name)
    by_name = _report_index(reports, clock)
    if not people:
        return None, "skip only self"

    heal_press = None
    heal_id = 0
    if allow_heals:
        for skill_id in _HEAL_RANK:
            if skill_id not in ids:
                continue
            found = _press(hotbar, skill_id)
            if found is not None:
                heal_press = found
                heal_id = int(skill_id)
                break

    low_in_range: list[tuple[int, int, dict[str, Any], int]] = []
    low_screen: list[tuple[int, int, dict[str, Any], tuple[int, int, int, int, int]]] = []
    line_blocked = False
    for member in people:
        hp = _hp(member)
        gid = guid_int(member.get("guid"))
        if hp is None or hp <= 0 or hp >= int(below) or gid is None:
            continue
        pair = _place(member, here)
        if pair is None:
            continue
        dist = int(pair[4])
        if dist <= int(reach):
            if not _line_open(pair):
                line_blocked = True
                continue
            if gid in boxes:
                low_in_range.append((hp, gid, member, dist))
            continue
        if cast_only or gid not in boxes:
            continue
        mx, my, qx, qy, _dist = pair
        if _on_mage_screen(mx, my, qx, qy):
            low_screen.append((hp, gid, member, pair))
    low_in_range.sort()
    low_screen.sort()

    all_press = (
        _press(hotbar, _HEAL_ALL) if allow_heals and _HEAL_ALL in ids else None
    )
    ranged_low = [
        member
        for member in people
        if (_hp(member) or 0) > 0
        and (_hp(member) or 100) < int(below)
        and (pair := _place(member, here)) is not None
        and int(pair[4]) <= int(reach)
        and _line_open(pair)
    ]
    if all_press is not None and len(ranged_low) >= 2:
        return (
            _cast(
                spell="heal_all",
                skill_id=_HEAL_ALL,
                member=None,
                dist=None,
                press=all_press,
                click=None,
            ),
            f"cast heal all n={len(ranged_low)}",
        )
    if heal_press is not None and low_in_range:
        hp, _gid, member, dist = low_in_range[0]
        row = boxes[int(guid_int(member.get("guid")) or 0)]
        click = _click(row)
        return (
            _cast(
                spell="heal",
                skill_id=heal_id,
                member=member,
                dist=dist,
                press=heal_press,
                click=click,
                hp_pct=hp,
            ),
            f"cast {member.get('name')} hp={hp} dist={dist}",
        )
    if heal_press is not None and low_screen:
        hp, _gid, member, pair = low_screen[0]
        choice = _step(member, pair, reach)
        return choice, f"step {choice['name']} hp={hp} dist={choice['dist']}"

    if heals_only:
        if not low_in_range and not low_screen:
            if line_blocked:
                return None, "skip line blocked"
            return None, f"skip no member under {int(below)}"
        return None, "skip heal not ready"

    def _targeted(skill_id: int, spell: str, want) -> tuple[Optional[dict[str, Any]], str]:
        press = _press(hotbar, skill_id)
        if press is None:
            return None, ""
        ready: list[tuple[int, int, dict[str, Any], int, bool, Any]] = []
        for member in people:
            gid = guid_int(member.get("guid"))
            hp = _hp(member)
            if gid is None or hp is None or gid not in boxes:
                continue
            if spell == "resurrect":
                if hp != 0:
                    continue
            elif hp <= 0 or not want(member):
                continue
            pair = _place(member, here)
            if pair is None:
                continue
            dist = int(pair[4])
            in_range = dist <= int(reach)
            if not in_range:
                if cast_only:
                    continue
                mx, my, qx, qy, _dist = pair
                if not _on_mage_screen(mx, my, qx, qy):
                    continue
            ready.append((0 if in_range else 1, hp, member, dist, in_range, pair))
        if not ready:
            return None, ""
        ready.sort(key=lambda row: (row[0], row[1], int(guid_int(row[2].get("guid")) or 0)))
        _rank, hp, member, dist, in_range, pair = ready[0]
        if not in_range:
            choice = _step(member, pair, reach)
            return choice, f"step {choice['name']} hp={hp} dist={dist}"
        click = _click(boxes[int(guid_int(member.get("guid")) or 0)])
        return (
            _cast(
                spell=spell,
                skill_id=skill_id,
                member=member,
                dist=dist,
                press=press,
                click=click,
                hp_pct=hp,
            ),
            f"cast {spell} {member.get('name')} hp={hp} dist={dist}",
        )

    if _RESURRECT in ids:
        choice, note = _targeted(_RESURRECT, "resurrect", lambda _member: False)
        if choice is not None:
            return choice, note
    if _CURE in ids:
        choice, note = _targeted(
            _CURE,
            "cure",
            lambda member: _ailment(
                by_name.get(str(member.get("name") or "").strip().casefold()),
                _POISON,
                "poisoned",
            ),
        )
        if choice is not None:
            return choice, note
    if _CURSE in ids:
        choice, note = _targeted(
            _CURSE,
            "curse",
            lambda member: _ailment(
                by_name.get(str(member.get("name") or "").strip().casefold()),
                _CURSE_WORDS,
            ),
        )
        if choice is not None:
            return choice, note

    due: list[tuple[float, int, int, int, dict[str, Any], int, bool, Any, tuple[int, str]]] = []
    for skill_id in _buff_ids(ids):
        press = _press(hotbar, skill_id)
        if press is None:
            continue
        for member in people:
            gid = guid_int(member.get("guid"))
            hp = _hp(member)
            if gid is None or hp is None or hp <= 0 or gid not in boxes:
                continue
            pair = _place(member, here)
            if pair is None:
                continue
            dist = int(pair[4])
            if dist <= int(reach) and not _line_open(pair):
                line_blocked = True
                continue
            in_range = dist <= int(reach)
            if not in_range:
                if cast_only:
                    continue
                mx, my, qx, qy, _dist = pair
                if not _on_mage_screen(mx, my, qx, qy):
                    continue
            report = by_name.get(str(member.get("name") or "").strip().casefold())
            remain = _remain(book, gid, skill_id, report, clock)
            if remain > _RECAST_S:
                continue
            due.append((remain, hp, gid, skill_id, member, dist, in_range, pair, press))
    if not due:
        if line_blocked:
            return None, "skip line blocked"
        if _buff_ids(ids) or _CURE in ids or _CURSE in ids or _RESURRECT in ids:
            return None, "skip support held"
        return None, f"skip no member under {int(below)}"
    due.sort()
    remain, hp, _gid, skill_id, member, dist, in_range, pair, press = due[0]
    if not in_range:
        choice = _step(member, pair, reach)
        return choice, f"step {choice['name']} buff dist={dist}"
    click = _click(boxes[int(guid_int(member.get("guid")) or 0)])
    choice = _cast(
        spell="buff",
        skill_id=skill_id,
        member=member,
        dist=dist,
        press=press,
        click=click,
        hp_pct=hp,
    )
    return choice, f"cast {_label(skill_id)} {member.get('name')} remain={remain:.0f} dist={dist}"
