"""Solo field Heal / Body to Mind. Mother-tree and party recovery stay elsewhere.

One cast, then the next decision tick is left to navigation. Combat and
emergency HP use the existing gates and skip this module.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app._03_world import GameState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.blackboard import Blackboard

_SCRATCH_ACTIVE = "field_recovery_active"
_SCRATCH_YIELD = "field_recovery_yield"
_SCRATCH_MAP = "field_recovery_map"
_SCRATCH_ROUTINE = "field_recovery_routine"

# Live hotbar gate for this process session only. Not written to the profile.
_capability_epoch = 0
_capability_checked = False
_capability_enabled = False


def field_recovery_capability_epoch() -> int:
    return int(_capability_epoch)


def begin_field_recovery_session() -> int:
    """Drop the previous character's hotbar result and start a new session."""
    global _capability_epoch
    invalidate_field_recovery_capability()
    _capability_epoch += 1
    return int(_capability_epoch)


def invalidate_field_recovery_capability() -> None:
    """Drop the hotbar result. The next cast waits for a new read."""
    global _capability_checked, _capability_enabled
    _capability_checked = False
    _capability_enabled = False


def field_recovery_capability_checked() -> bool:
    return bool(_capability_checked)


def is_field_auto_recovery_enabled() -> bool:
    """True only after this session's hotbar read found both skills."""
    return bool(_capability_checked and _capability_enabled)


def _both_recovery_skills_on_hotbar(snap: object) -> bool:
    """Heal and Body to Mind must both be on the live bar, with a real key.

    A catalog entry is not enough. A missing or empty read is not enough.
    """
    if not isinstance(snap, dict):
        return False
    slots = snap.get("slots")
    if not isinstance(slots, list) or not slots:
        return False
    from hotbar.inspect import find_role_on_hotbar

    return (
        find_role_on_hotbar(snap, "heal") is not None
        and find_role_on_hotbar(snap, "hp_to_mp") is not None
    )


def refresh_field_recovery_capability(snap: object, *, epoch: int | None = None) -> bool:
    """Record one hotbar read for the current run. Returns whether both skills are there.

    A stale ``epoch`` from a stopped session does not overwrite the new one.
    """
    global _capability_checked, _capability_enabled
    if epoch is not None and int(epoch) != int(_capability_epoch):
        return is_field_auto_recovery_enabled()
    _capability_checked = True
    _capability_enabled = _both_recovery_skills_on_hotbar(snap)
    return _capability_enabled


def refresh_field_recovery_from_layout(detected: object, *, epoch: int | None = None) -> bool:
    """Use the cells from one inspect. Does not read the bar again."""
    cells = getattr(detected, "cells", None)
    if not cells:
        return refresh_field_recovery_capability(None, epoch=epoch)
    slots = [
        {
            "box": getattr(cell, "box", 0),
            "key": getattr(cell, "key", ""),
            "name": getattr(cell, "kr_name", "") or getattr(cell, "label", ""),
            "zh_name": getattr(cell, "zh_name", ""),
        }
        for cell in cells
    ]
    return refresh_field_recovery_capability({"slots": slots}, epoch=epoch)


def _clear(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(_SCRATCH_ACTIVE, None)
    blackboard.scratch.pop(_SCRATCH_YIELD, None)
    blackboard.scratch.pop(_SCRATCH_MAP, None)
    blackboard.scratch.pop(_SCRATCH_ROUTINE, None)


def _limits() -> dict[str, float]:
    from app._04_decision import player_mode as pm

    stop = float(pm.FIELD_RECOVERY_STOP)
    return {
        "hp_start": float(pm.FIELD_RECOVERY_HP_START),
        "mp_start": float(pm.FIELD_RECOVERY_MP_START),
        "stop": stop,
        "hp_stop": stop,
        "mp_stop": stop,
        "min_hp": float(pm.FIELD_RECOVERY_MIN_HP),
        "min_mp": float(pm.FIELD_RECOVERY_MIN_MP),
    }


def _ratios(state: "GameState") -> tuple[Optional[float], Optional[float]]:
    from app._04_decision.mode_control import hp_ratio, mp_ratio

    return hp_ratio(state), mp_ratio(state)


def _routine_token(blackboard: "Blackboard") -> str:
    cursor = blackboard.scratch.get("routine_cursor")
    if cursor is None or not hasattr(cursor, "active"):
        return ""
    try:
        entry = cursor.active()
    except Exception:
        return ""
    if not isinstance(entry, dict):
        return ""
    farms = entry.get("selected_farms") or []
    names = ",".join(str(name) for name in farms)
    return "|".join(
        (
            str(entry.get("map_id") or ""),
            str(entry.get("kind") or ""),
            names,
        )
    )


def _live_map_id(state: "GameState") -> Optional[int]:
    from app._04_decision.world_nav.session import live_pose_from_state

    try:
        pose = live_pose_from_state(state)
    except Exception:
        return None
    if pose is None:
        return None
    raw = getattr(pose, "map_id", None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _context_reset(state: "GameState", blackboard: "Blackboard") -> bool:
    """True when this tick must drop a field-recovery session."""
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import is_hp_zero
    from app._04_decision.player_mode import PlayerMode
    from app._06_party.recovery import party_on

    if not bool(pm.FIELD_RECOVERY_ENABLED) or party_on():
        return True
    if blackboard.player_mode is not PlayerMode.FARMING:
        return True
    if is_hp_zero(state):
        return True
    if blackboard.scratch.get("mother_tree_trip"):
        return True
    if blackboard.scratch.get("shop_trip"):
        return True
    if blackboard.scratch.get("world_nav_session") is not None:
        return True
    from app._04_decision.world_nav.routine import routine_hunt_zone_inside

    try:
        inside = bool(routine_hunt_zone_inside(blackboard))
    except Exception:
        inside = False
    if not inside:
        return True
    stored_map = blackboard.scratch.get(_SCRATCH_MAP)
    live_map = _live_map_id(state)
    if stored_map is not None and live_map is not None and int(stored_map) != int(live_map):
        return True
    stored_routine = blackboard.scratch.get(_SCRATCH_ROUTINE)
    token = _routine_token(blackboard)
    if stored_routine is not None and str(stored_routine) != token:
        return True
    return False


def _combat_blocks(state: "GameState", blackboard: "Blackboard") -> bool:
    """Same attack chances farm.engage uses, read without giving up a lock."""
    from app._04_decision.attack_feedback import excluded_target_ids
    from app._04_decision.behaviors.mode_actions import (
        _combat_hp_threat,
        character_is_attacking,
        hp_spike_drop,
    )
    from app._04_decision.combat_query import (
        nearest_attackable,
        nearest_attacks_me_force,
    )

    if blackboard.current_target_id is not None:
        return True
    if bool(getattr(blackboard, "sticky_attacked_me", False)):
        return True
    try:
        if character_is_attacking(state, blackboard):
            return True
    except Exception:
        return True
    if hp_spike_drop(blackboard) and _combat_hp_threat(state, blackboard):
        return True
    origin = getattr(blackboard, "world_origin", None)
    try:
        exclude = excluded_target_ids(blackboard)
    except Exception:
        exclude = set()
    try:
        if nearest_attacks_me_force(state, exclude=exclude, origin=origin) is not None:
            return True
    except Exception:
        return True
    try:
        enemy = nearest_attackable(
            state,
            exclude=exclude,
            origin=origin,
            screen_only=True,
        )
    except Exception:
        return True
    return enemy is not None


def _retreat_blocks(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio

    ratio = hp_ratio(state)
    if ratio is None:
        return True
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    retreat_th = action_threshold(actions, "retreat")
    return retreat_th is not None and ratio <= float(retreat_th)


def _potion_due(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors.mode_actions import should_drink_mp_potion
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio

    if should_drink_mp_potion(state):
        return True
    if not pm.USE_HP_POTION:
        return False
    ratio = hp_ratio(state)
    if ratio is None:
        return False
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    potion_th = action_threshold(actions, "hp_potion")
    return potion_th is not None and ratio <= float(potion_th)


def _existing_heal_owns(state: "GameState") -> bool:
    """True while the recovery-tab heal line still covers this HP."""
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio

    if not pm.USE_HEAL:
        return False
    ratio = hp_ratio(state)
    if ratio is None:
        return False
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    heal_th = action_threshold(actions, "heal")
    return heal_th is not None and ratio <= float(heal_th)


def _start_due(state: "GameState") -> bool:
    limits = _limits()
    hp, mp = _ratios(state)
    hp_low = hp is not None and hp < limits["hp_start"]
    mp_low = mp is not None and mp < limits["mp_start"]
    return hp_low or mp_low


def _both_at_stop(state: "GameState") -> bool:
    limits = _limits()
    hp, mp = _ratios(state)
    if hp is None or mp is None:
        return False
    stop = limits["stop"]
    return hp >= stop and mp >= stop


def _heal_affordable(state: "GameState", blackboard: "Blackboard") -> bool:
    from app._04_decision.behaviors.mode_actions import (
        current_mp,
        heal_blocked_by_mana,
    )
    from app._04_decision.spells import slot_ready, spell_mp_cost_for_role
    from app._05_action.spell_box import slot_is_enabled

    if _existing_heal_owns(state):
        return False
    if not slot_is_enabled("heal") or not slot_ready(blackboard, "heal"):
        return False
    if heal_blocked_by_mana(state, blackboard, role="heal"):
        return False
    mp = current_mp(state)
    player = getattr(state, "player", None)
    max_mp = getattr(player, "max_mp", None) if player is not None else None
    cost = spell_mp_cost_for_role("heal", state, blackboard)
    if mp is None or max_mp is None or cost is None or int(max_mp) <= 0:
        return False
    if int(mp) < int(cost):
        return False
    remain = (float(mp) - float(cost)) / float(max_mp)
    return remain >= float(_limits()["min_mp"])


def _body_to_mind_safe(state: "GameState", blackboard: "Blackboard") -> bool:
    from app._04_decision.spells import slot_ready
    from app._05_action.spell_box import slot_is_enabled
    from settings.spell_mana_cost import hp_cost_for_role_fallback

    if _existing_heal_owns(state):
        return False
    if not slot_is_enabled("hp_to_mp") or not slot_ready(blackboard, "hp_to_mp"):
        return False
    player = getattr(state, "player", None)
    if player is None or player.hp is None or not player.max_hp:
        return False
    cost = hp_cost_for_role_fallback("hp_to_mp")
    if cost is None:
        return False
    remain = int(player.hp) - int(cost)
    if remain <= 0:
        return False
    return (float(remain) / float(player.max_hp)) >= float(_limits()["min_hp"])


def is_field_recovery_allowed(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """True when a solo hunt tick may consider one field recovery cast."""
    if _context_reset(state, blackboard):
        return False
    if _combat_blocks(state, blackboard) or _retreat_blocks(state):
        return False
    return True


def select_field_recovery_skill(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional[str]:
    """The lower live percent. None when that skill is not safe to cast.

    A resource already above the shared stop stays in the comparison. The
    next read can select it again after the other cast spends it.
    """
    if not is_field_auto_recovery_enabled():
        return None
    hp, mp = _ratios(state)
    if hp is None or mp is None:
        return None
    if hp < mp:
        skill = "heal"
    elif mp < hp:
        skill = "hp_to_mp"
    else:
        skill = random.choice(("heal", "hp_to_mp"))
    if skill == "heal":
        return "heal" if _heal_affordable(state, blackboard) else None
    return "hp_to_mp" if _body_to_mind_safe(state, blackboard) else None


def _remember(state: "GameState", blackboard: "Blackboard") -> None:
    blackboard.scratch[_SCRATCH_ACTIVE] = True
    live_map = _live_map_id(state)
    if live_map is not None:
        blackboard.scratch[_SCRATCH_MAP] = int(live_map)
    blackboard.scratch[_SCRATCH_ROUTINE] = _routine_token(blackboard)


def _emit_body_to_mind(state: "GameState", blackboard: "Blackboard") -> "Status":
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.spells import mark_slot_used

    mark_slot_used(blackboard, "hp_to_mp")
    blackboard.current_goal = "field_recovery"
    blackboard.emit(
        ActionType.HP_TO_MP,
        priority=0.9,
        reason="field recover mp",
    )
    del state
    return Status.SUCCESS


def try_field_auto_recovery(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional["Status"]:
    """One field cast, or None so hunting movement can run.

    A successful cast sets a one-tick yield. The following decision does not
    cast again. ``nav_goal`` is left as it is.
    """
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors.mode_actions import emit_heal

    if not is_field_auto_recovery_enabled():
        _clear(blackboard)
        return None
    if _context_reset(state, blackboard):
        _clear(blackboard)
        return None
    if _combat_blocks(state, blackboard) or _retreat_blocks(state):
        _clear(blackboard)
        return None
    if _potion_due(state):
        return None
    if blackboard.scratch.pop(_SCRATCH_YIELD, None):
        return None
    active = bool(blackboard.scratch.get(_SCRATCH_ACTIVE))
    if not active and not _start_due(state):
        return None
    if _both_at_stop(state):
        _clear(blackboard)
        return None
    skill = select_field_recovery_skill(state, blackboard)
    if skill is None:
        return None
    if skill == "heal":
        result = emit_heal(blackboard, state, reason="field recover hp")
        if result is not Status.SUCCESS:
            return None
        _remember(state, blackboard)
        blackboard.scratch[_SCRATCH_YIELD] = True
        return result
    result = _emit_body_to_mind(state, blackboard)
    _remember(state, blackboard)
    blackboard.scratch[_SCRATCH_YIELD] = True
    return result
