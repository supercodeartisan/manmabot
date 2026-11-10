"""Party self-support: heal + buff + potion sides.

The retreat gate uses the party recovery lines (mother tree, talking scroll,
safe zone). After HP recovers, a solo post_retreat walk back to the hunt is
dropped so the member follows the leader.
"""
from __future__ import annotations

from typing import Any, Optional

from .party_log import get_logger as _party_logger

_log = _party_logger("member")


def party_critical_escape(game_state: Any, blackboard: Any) -> Optional[Any]:
    """Party retreat line, only at the party retreat gate or while that trip runs.

    Mother tree, talking scroll, and safe zone follow the party recovery
    overlay. After HP recovers, a solo ``post_retreat`` world-nav back to the
    hunt map is dropped so this member follows the party leader again.
    """
    if game_state is None or blackboard is None:
        return None

    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors.mode_ticks import (
        _step_survival_hp,
        tick_retreating,
        tick_shopping,
    )
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio, set_mode
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.shop_trip import SCRATCH_HP_SELL_BEFORE_RETREAT
    from app._04_decision.world_nav.hooks import (
        SCRATCH_NEED_WORLD_NAV,
        clear_world_nav_run,
    )

    def _drop_hunt_return() -> None:
        if getattr(blackboard, "player_mode", None) is not PlayerMode.WORLD_NAV:
            return
        if str(blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV) or "") != "post_retreat":
            return
        clear_world_nav_run(blackboard)
        set_mode(blackboard, PlayerMode.FARMING)

    mode = getattr(blackboard, "player_mode", None)
    selling = bool(blackboard.scratch.get(SCRATCH_HP_SELL_BEFORE_RETREAT))
    if mode is PlayerMode.RETREATING or (mode is PlayerMode.SHOPPING and selling):
        try:
            blackboard.side_intents.clear()
        except Exception:
            blackboard.side_intents = []
    if mode is PlayerMode.RETREATING:
        blackboard.intent = None
        tick_retreating(game_state, blackboard)
        _drop_hunt_return()
    elif mode is PlayerMode.SHOPPING and selling:
        blackboard.intent = None
        tick_shopping(game_state, blackboard)
    else:
        actions = pm.HP_ACTIONS or normalize_hp_actions(None)
        threshold = action_threshold(actions, "retreat")
        ratio = hp_ratio(game_state)
        if threshold is None or ratio is None or float(ratio) > float(threshold):
            return None
        blackboard.intent = None
        _step_survival_hp(game_state, blackboard)
        _drop_hunt_return()

    if getattr(blackboard, "player_mode", None) is PlayerMode.FARMING:
        intent = getattr(blackboard, "intent", None)
        if intent is None:
            return None
        return intent

    intent = getattr(blackboard, "intent", None)
    if intent is not None:
        return intent
    from .intents import idle

    return idle("critical retreat")


def urgent_self_survival(
    game_state: Any,
    blackboard: Any,
    origin: Any = None,
) -> Optional[Any]:
    """HP potion, self heal, then an in-range defense. No buffs and no party heal.

    Does not clear a shop trip. Buffs and party-list heals stay on their
    later tick. An in-place result leaves the shop approach where it is.
    """
    if game_state is None or blackboard is None:
        return None
    sides = getattr(blackboard, "side_intents", None)
    if sides is None:
        try:
            blackboard.side_intents = []
        except Exception:
            return None

    potion = None
    try:
        from app._04_decision.potion_sides import _side_hp_potion

        potion = _side_hp_potion(game_state, blackboard)
    except Exception as exc:
        _log.debug("urgent potion failed: %s", exc)
        potion = None
    if potion is not None:
        return potion

    saved = getattr(blackboard, "intent", None)
    heal = None
    try:
        heal = _try_party_heal(game_state, blackboard)
    except Exception as exc:
        _log.debug("urgent heal failed: %s", exc)
        heal = None
    from app._02_state.enums import ActionType

    if heal is not None and getattr(heal, "action", None) is ActionType.HEAL:
        return heal
    if getattr(blackboard, "intent", None) is not saved:
        blackboard.intent = saved
    return _immediate_defense(game_state, blackboard, origin)


def _immediate_defense(game_state: Any, blackboard: Any, origin: Any) -> Optional[Any]:
    """Attack only a threat already inside reach. A chase waits for the later tick."""
    try:
        from app._02_state.enums import ActionType
        from app._04_decision.behaviors.hold_ground import hold_ground_reach
        from app._04_decision.combat_query import (
            can_engage_target,
            tile_distance_from_player,
        )

        from .assist import engage_like_solo, resolve_self_defender

        threat = resolve_self_defender(game_state, origin=origin)
        if threat is None:
            return None
        reach = int(hold_ground_reach(game_state))
        if tile_distance_from_player(threat) > reach:
            return None
        if origin is not None and not can_engage_target(threat, origin):
            return None
        intent = engage_like_solo(
            game_state, blackboard, threat, reason="self defense"
        )
    except Exception as exc:
        _log.debug("urgent defense failed: %s", exc)
        return None
    if getattr(intent, "action", None) is not ActionType.ATTACK:
        return None
    return intent


def apply_party_support(
    game_state: Any,
    blackboard: Any,
    *,
    allow_buffs: bool = True,
    heal_below: Optional[float] = None,
    potion_below: Optional[float] = None,
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
        primary = _try_party_heal(game_state, blackboard, heal_below=heal_below)
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
        arm_potion_side_intents(
            game_state, blackboard, hp_potion_below=potion_below
        )
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


def _try_party_heal(
    game_state: Any,
    blackboard: Any,
    *,
    heal_below: Optional[float] = None,
) -> Optional[Any]:
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
    heal_th = (
        float(heal_below)
        if heal_below is not None
        else action_threshold(actions, "heal")
    )
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


def urgent_list_heal_pct() -> Optional[int]:
    """Party-list heal line for a cast that may interrupt a shop trip.

    This is the character's own heal threshold, stricter than the routine
    party-list percent. None means that heal action is off.
    """
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions

    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    threshold = action_threshold(actions, "heal")
    if threshold is None:
        return None
    return max(1, min(99, int(round(float(threshold) * 100))))


def shop_floor_blocks_party_heal(blackboard: Any) -> bool:
    """True while the shopkeeper is on the town side of a purchase.

    A walk that has not scrolled yet can still be interrupted by an in-range
    heal. The stall, the scroll, and the landing wait keep the trip.
    """
    if blackboard is None:
        return False
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return False
    return bool(scratch.get("shop_halted") or scratch.get("shop_scrolled"))


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


__all__ = [
    "apply_party_support",
    "party_critical_escape",
    "shop_floor_blocks_party_heal",
    "urgent_list_heal_pct",
    "urgent_self_survival",
]
