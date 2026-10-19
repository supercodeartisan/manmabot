"""Potion side-intents: parallel to the primary ActionIntent.

HP / MP / depoison never win the mode ladder alone. Each tick, decide arms
zero or more ``USE_*`` intents on ``blackboard.side_intents``; Action runs
them alongside the primary (see ``ActionExecutor.execute``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._04_decision.types import ActionIntent

if TYPE_CHECKING:
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

_POTION_ACTIONS = frozenset(
    {
        ActionType.USE_HP_POTION,
        ActionType.USE_MP_POTION,
        ActionType.USE_DEPOISON,
    }
)


def is_potion_action(action: ActionType | None) -> bool:
    return action in _POTION_ACTIONS


def arm_potion_side_intents(state: "GameState", blackboard: "Blackboard") -> None:
    """Fill ``blackboard.side_intents`` for this tick (clears first)."""
    blackboard.side_intents.clear()
    # If the ladder still emitted a potion as primary, move it to the side
    # channel so a later primary (or IDLE) is not blocked incorrectly.
    primary = blackboard.intent
    if primary is not None and is_potion_action(primary.action):
        blackboard.side_intents.append(primary)
        blackboard.intent = None

    depoison = _side_depoison(state, blackboard)
    if depoison is not None:
        blackboard.side_intents.append(depoison)

    hp = _side_hp_potion(state, blackboard)
    if hp is not None:
        blackboard.side_intents.append(hp)

    mp = _side_mp_potion(state, blackboard)
    if mp is not None:
        blackboard.side_intents.append(mp)


def _side_depoison(
    state: "GameState", blackboard: "Blackboard"
) -> ActionIntent | None:
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors.mode_actions import player_should_drink_antidote
    from app._04_decision.spells import (
        ANTIDOTE_POTION_ITEM,
        _live_hotbar_snap,
        mark_slot_used,
        slot_ready,
    )
    from app._05_action.spell_box import slot_is_enabled, slot_press
    from settings.antidote_potion import resolve_antidote_press_slot

    if not pm.ANTIDOTE_AUTO:
        return None
    if not player_should_drink_antidote(state):
        return None
    if not slot_ready(blackboard, "depoison"):
        return None
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is not None and bool(getattr(inv, "bag_ready", False)):
        try:
            if int(getattr(inv, "depoison", 0) or 0) <= 0:
                return None
        except (TypeError, ValueError):
            return None
    if any(s.action is ActionType.USE_DEPOISON for s in blackboard.side_intents):
        return None
    assigned = slot_press("depoison") if slot_is_enabled("depoison") else None
    found = resolve_antidote_press_slot(
        item_key=ANTIDOTE_POTION_ITEM,
        assigned_slot=assigned,
        live_snap=_live_hotbar_snap(state, blackboard),
    )
    if found is None:
        return None
    mark_slot_used(blackboard, "depoison")
    return ActionIntent(
        action=ActionType.USE_DEPOISON,
        priority=0.93,
        reason="poisoned",
        item_key=str(ANTIDOTE_POTION_ITEM or "").strip() or None,
        hotbar_box=int(found[0]),
        hotbar_key=str(found[1]).strip().lower() or None,
    )


def _side_hp_potion(
    state: "GameState", blackboard: "Blackboard"
) -> ActionIntent | None:
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors.mode_actions import (
        _hp_action_availability,
        hp_potion_reason,
    )
    from app._04_decision.hp_actions import (
        action_threshold,
        find_hp_restore_hotbar,
        item_key_from_action,
        normalize_hp_actions,
    )
    from app._04_decision.mode_control import hp_ratio, is_hp_zero
    from app._04_decision.spells import mark_slot_used, slot_ready

    if is_hp_zero(state):
        return None
    if not pm.USE_HP_POTION:
        return None
    if any(s.action is ActionType.USE_HP_POTION for s in blackboard.side_intents):
        return None
    ratio = hp_ratio(state)
    if ratio is None:
        return None
    # Spike escape path skips heal/items — keep that: no HP potion side on spike.
    from app._04_decision.behaviors.mode_actions import (
        _combat_hp_threat,
        hp_spike_drop,
    )

    if hp_spike_drop(blackboard) and _combat_hp_threat(state, blackboard):
        return None

    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    from app._04_decision.behaviors.mode_actions import retreat_fill_until_ratio

    fill_until = retreat_fill_until_ratio(blackboard)
    potion_th = action_threshold(actions, "hp_potion")
    if fill_until is not None:
        if ratio >= fill_until:
            return None
        intent = blackboard.intent
        if intent is not None and intent.action is ActionType.HEAL:
            return None
    elif potion_th is None or ratio > potion_th:
        return None
    if not any(
        str(row.get("id") or "") == "hp_potion" and row.get("enabled", True)
        for row in actions
    ):
        return None
    can = _hp_action_availability(state, blackboard, retreat_starters=True)
    if not can.get("hp_potion"):
        return None
    item_key = item_key_from_action("hp_potion")
    slot = find_hp_restore_hotbar(state, item_key)
    if slot is None:
        if not slot_ready(blackboard, "hp_potion", urgent=True):
            return None
        box, key = None, ""
    else:
        box, key = slot
    mark_slot_used(blackboard, "hp_potion")
    return ActionIntent(
        action=ActionType.USE_HP_POTION,
        priority=0.9,
        reason=hp_potion_reason(state),
        item_key=item_key or None,
        hotbar_box=box,
        hotbar_key=str(key or "").strip().lower() or None,
    )


def _side_mp_potion(
    state: "GameState", blackboard: "Blackboard"
) -> ActionIntent | None:
    from app._04_decision.behaviors.mode_actions import should_drink_mp_potion
    from app._04_decision.spells import mark_slot_used, slot_ready

    if not should_drink_mp_potion(state):
        return None
    if not slot_ready(blackboard, "mp_potion"):
        return None
    if any(s.action is ActionType.USE_MP_POTION for s in blackboard.side_intents):
        return None
    mark_slot_used(blackboard, "mp_potion")
    return ActionIntent(
        action=ActionType.USE_MP_POTION,
        priority=0.88,
        reason="low mp",
    )


__all__ = [
    "arm_potion_side_intents",
    "is_potion_action",
]
