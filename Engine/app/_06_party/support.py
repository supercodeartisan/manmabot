"""Party self-support: heal + buff + potion sides. Never retreat / escape / tree."""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger("party.member")


def apply_party_support(
    game_state: Any,
    blackboard: Any,
    *,
    allow_buffs: bool = True,
) -> Optional[Any]:
    """Arm potion sides; optionally emit primary HEAL or BUFF.

    Reuses solo helpers (``emit_heal``, ``maybe_cast_buff``, ``arm_potion_side_intents``)
    but never starts retreat, mother-tree, safe-scroll, or shop.
    Returns the primary ActionIntent when heal/buff won, else None (follow may run).
    """
    if game_state is None or blackboard is None:
        return None

    from app._02_state.enums import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.potion_sides import arm_potion_side_intents

    blackboard.intent = None
    try:
        blackboard.side_intents.clear()
    except Exception:
        blackboard.side_intents = []

    primary = None
    try:
        primary = _try_party_heal(game_state, blackboard)
    except Exception as exc:
        _log.debug("party heal failed: %s", exc)
        primary = None
    if primary is None and allow_buffs:
        try:
            primary = _try_party_buff(game_state, blackboard)
        except Exception as exc:
            _log.debug("party buff failed: %s", exc)
            primary = None

    try:
        arm_potion_side_intents(game_state, blackboard)
    except Exception as exc:
        _log.debug("party potion sides failed: %s", exc)

    # If potion sides stole a potion primary, keep sides only.
    intent = getattr(blackboard, "intent", None)
    if intent is not None and getattr(intent, "action", None) in (
        ActionType.USE_HP_POTION,
        ActionType.USE_MP_POTION,
        ActionType.USE_DEPOISON,
    ):
        intent = None
        blackboard.intent = None

    if primary is not None and intent is primary:
        why = str(getattr(primary, "reason", "") or "")
        if not why.startswith("party_member:"):
            try:
                primary.reason = f"party_member:{why}".strip()
            except Exception:
                pass
        return primary
    if intent is not None:
        why = str(getattr(intent, "reason", "") or "")
        if not why.startswith("party_member:"):
            try:
                intent.reason = f"party_member:{why}".strip()
            except Exception:
                pass
        return intent
    return None


def _try_party_heal(game_state: Any, blackboard: Any) -> Optional[Any]:
    """Same heal threshold as solo ``apply_hp_actions``, without retreat starters."""
    from app._04_decision import player_mode as pm
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors.mode_actions import (
        _hp_action_availability,
        emit_heal,
    )
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio, is_hp_zero

    if is_hp_zero(game_state):
        return None
    ratio = hp_ratio(game_state)
    if ratio is None:
        return None
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    can = _hp_action_availability(
        game_state,
        blackboard,
        retreat_starters=False,
    )
    heal_th = action_threshold(actions, "heal")
    if heal_th is None or not can.get("heal") or float(ratio) > float(heal_th):
        # Still allow convert skill when configured (solo field path).
        try:
            from app._04_decision.spells import maybe_hp_to_mp

            convert = maybe_hp_to_mp(game_state, blackboard)
            if convert is not None and getattr(blackboard, "intent", None) is not None:
                return blackboard.intent
        except Exception:
            pass
        return None
    result = emit_heal(blackboard, game_state, reason="recover hp")
    if result is Status.FAILURE:
        return None
    return getattr(blackboard, "intent", None)


def _try_party_buff(game_state: Any, blackboard: Any) -> Optional[Any]:
    from app._04_decision.behavior_tree import Status
    from app._04_decision.spells import maybe_cast_buff

    try:
        status = maybe_cast_buff(game_state, blackboard)
    except Exception as exc:
        _log.debug("party buff failed: %s", exc)
        return None
    if status is not Status.SUCCESS:
        return None
    return getattr(blackboard, "intent", None)


__all__ = ["apply_party_support"]
