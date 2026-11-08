"""Solo mage buffs and attack spell from the individual magic table.

Party leader scratch ``party_leader_no_loot`` and every other class stay on
``maybe_cast_buff`` / ``mage_attack``. A live fight keeps attacking; expired
buffs are refreshed only once that target is no longer sticky.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app._03_world import ActionType
from app._04_decision.behavior_tree import Status

if TYPE_CHECKING:
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

# After this many presses with the effect still missing, skip the skill.
BUFF_CAST_ATTEMPTS = 3
# How long a failed skill stays skipped so the hunt does not spin on it.
BUFF_FAIL_PARK_S = 30.0
_SCRATCH = "solo_mage_buff_try"
# Skill id due for the next attack press. Stays put until that key is pressed.
_ATTACK_TURN = "solo_mage_attack_turn"
_ATTACK_ORDER = "solo_mage_attack_order"


def _now() -> float:
    return time.time()


def solo_mage_active(state: "GameState", blackboard: "Blackboard") -> bool:
    """Spell-aim mage on the solo columns. Party leader and other classes are not."""
    if blackboard.scratch.get("party_leader_no_loot"):
        return False
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import is_mage

    return bool(is_mage(state) and pm.uses_spell_aim())


def _try_rows(blackboard: "Blackboard") -> dict:
    raw = blackboard.scratch.get(_SCRATCH)
    if not isinstance(raw, dict):
        raw = {}
        blackboard.scratch[_SCRATCH] = raw
    return raw


def _in_fight(state: "GameState", blackboard: "Blackboard") -> bool:
    tid = blackboard.current_target_id
    if tid is None:
        return False
    from app._04_decision.behaviors.combat import sticky_target_alive

    return bool(sticky_target_alive(state, int(tid)))


def _satisfied(buff, effects: list) -> bool:
    from app._04_decision.spells import BUFF_REMAIN_RECAST_S, _match_catalog_buff

    live = _match_catalog_buff(buff, effects)
    if live is None:
        return False
    try:
        remain = float(getattr(live, "duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        remain = 0.0
    return remain > float(BUFF_REMAIN_RECAST_S)


def _hold(blackboard: "Blackboard", reason: str) -> Status:
    blackboard.current_goal = "buff"
    blackboard.emit(ActionType.IDLE, priority=0.4, reason=reason)
    return Status.SUCCESS


def _emit_buff(blackboard: "Blackboard", buff, box: int, key: str) -> Status:
    token = f"buff:{int(buff.skill_id)}"
    blackboard.current_goal = "buff"
    blackboard.emit(
        ActionType.BUFF,
        priority=0.4,
        reason=token,
        hotbar_box=int(box),
        hotbar_key=str(key),
    )
    return Status.SUCCESS


def maybe_solo_mage_buffs(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional[Status]:
    """Cast the next checked buff that memory says is down. None if combat may start.

    A key press is not success. The live buff remain must rise above
    ``BUFF_REMAIN_RECAST_S``. MP below the reserve does not wait here; the
    earlier MP retreat step owns that. A skill that never appears is parked.
    """
    from app._04_decision.spells import (
        AUTO_BUFFS,
        BUFF_CAST_GUARD_S,
        _live_hotbar_snap,
        _memory_buffs_ready,
        can_cast_spell,
        magic_ready,
    )
    from settings.auto_buffs import press_for_buff

    if _in_fight(state, blackboard):
        return None
    if not AUTO_BUFFS:
        return None
    buffs = sorted(AUTO_BUFFS, key=lambda row: (int(row.priority), int(row.skill_id)))

    now = _now()
    memory_ok = _memory_buffs_ready(state)
    effects = (
        list(getattr(getattr(state, "player", None), "buffs", None) or [])
        if memory_ok
        else []
    )
    snap = _live_hotbar_snap(state, blackboard)
    rows = _try_rows(blackboard)

    for buff in buffs:
        skill_id = int(buff.skill_id)
        key = str(skill_id)
        row = rows.get(key) if isinstance(rows.get(key), dict) else {}
        parked = float(row.get("park") or 0.0)
        if parked > now:
            continue
        slot = press_for_buff(snap, buff) if snap is not None else None
        if slot is None:
            continue
        if memory_ok and _satisfied(buff, effects):
            rows.pop(key, None)
            continue
        if not memory_ok:
            # Same wall-clock fallback as due_buff when the buff snapshot is empty.
            pressed = float(row.get("at") or 0.0)
            if pressed > 0.0 and (now - pressed) < float(buff.duration_s or 0.0):
                continue
        spell_name = buff.names[0] if buff.names else ""
        if not can_cast_spell(state, role=spell_name or None, blackboard=blackboard):
            continue
        attempts = int(row.get("n") or 0)
        pressed_at = float(row.get("at") or 0.0)
        waiting = pressed_at > 0.0 and (now - pressed_at) < float(BUFF_CAST_GUARD_S)
        if waiting:
            return _hold(blackboard, "solo mage buff confirm")
        if attempts >= BUFF_CAST_ATTEMPTS:
            rows[key] = {"n": attempts, "at": pressed_at, "park": now + BUFF_FAIL_PARK_S}
            continue
        if not magic_ready(blackboard):
            return _hold(blackboard, "solo mage buff cooldown")
        rows[key] = {"n": attempts + 1, "at": now, "park": 0.0}
        box, hotkey = slot
        return _emit_buff(blackboard, buff, box, hotkey)
    return None


def _attack_rows(state: "GameState", blackboard: "Blackboard") -> list[tuple[int, int, str]]:
    """Checked attack spells that are on the live hotbar, priority then skill id."""
    from app._04_decision.spells import SOLO_MAGE_ATTACKS, _live_hotbar_snap
    from settings.auto_buffs import press_for_buff

    snap = _live_hotbar_snap(state, blackboard)
    if snap is None:
        return []
    rows: list[tuple[int, int, str]] = []
    for buff in sorted(
        SOLO_MAGE_ATTACKS, key=lambda row: (int(row.priority), int(row.skill_id))
    ):
        slot = press_for_buff(snap, buff)
        if slot is None:
            continue
        rows.append((int(buff.skill_id), int(slot[0]), str(slot[1])))
    return rows


def solo_mage_attack_fields(
    state: "GameState",
    blackboard: "Blackboard",
) -> dict[str, int | str]:
    """Hotbar cell of the attack spell due this cast. Empty keeps ``mage_attack``.

    Checked spells rotate one press each. A tick that does not press the key
    keeps the same spell.
    """
    if not solo_mage_active(state, blackboard):
        return {}
    rows = _attack_rows(state, blackboard)
    if not rows:
        blackboard.scratch.pop(_ATTACK_TURN, None)
        blackboard.scratch.pop(_ATTACK_ORDER, None)
        return {}
    order = [skill_id for skill_id, _box, _key in rows]
    blackboard.scratch[_ATTACK_ORDER] = order
    try:
        want = int(blackboard.scratch.get(_ATTACK_TURN))
    except (TypeError, ValueError):
        want = order[0]
    if want not in order:
        want = order[0]
    blackboard.scratch[_ATTACK_TURN] = want
    for skill_id, box, key in rows:
        if skill_id == want:
            return {"hotbar_box": box, "hotbar_key": key}
    return {}


def note_solo_mage_attack_pressed(blackboard: "Blackboard | None") -> None:
    """The attack key went out. The next cast uses the following checked spell."""
    if blackboard is None:
        return
    order = blackboard.scratch.get(_ATTACK_ORDER)
    if not isinstance(order, list) or not order:
        return
    try:
        current = int(blackboard.scratch.get(_ATTACK_TURN))
    except (TypeError, ValueError):
        return
    ids: list[int] = []
    for item in order:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if current not in ids:
        return
    blackboard.scratch[_ATTACK_TURN] = ids[(ids.index(current) + 1) % len(ids)]


__all__ = [
    "BUFF_CAST_ATTEMPTS",
    "BUFF_FAIL_PARK_S",
    "maybe_solo_mage_buffs",
    "note_solo_mage_attack_pressed",
    "solo_mage_active",
    "solo_mage_attack_fields",
]
