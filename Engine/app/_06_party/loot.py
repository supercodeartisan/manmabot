"""Party-member loot gates + side/primary pickup (reuses solo loot hop)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .config import PartyMemberConfig

if TYPE_CHECKING:
    from app._02_state.objects import WorldObject
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


def party_loot_ownership_filter(cfg: PartyMemberConfig) -> Optional[bool]:
    """None = do not loot; True/False = ``list_lootable(..., ownership_filter=)``.

    Random ON → every member loots without ownership gate (False).
    Random OFF + responsible → ownership gate on (True).
    Random OFF + none → no loot.
    """
    if bool(getattr(cfg, "random_loot", False)):
        return False
    role = str(getattr(cfg, "loot_role", "none") or "none").strip().lower()
    if role in ("responsible", "self", "looter"):
        return True
    return None


def party_may_loot(cfg: PartyMemberConfig) -> bool:
    return party_loot_ownership_filter(cfg) is not None


def clear_party_loot_sticky(blackboard: Any) -> None:
    """Drop sticky approach loot when follow/join/defend must win."""
    if blackboard is None:
        return
    try:
        from app._04_decision.behaviors.loot_hop import clear_loot_hop

        clear_loot_hop(blackboard)
    except Exception:
        pass
    try:
        blackboard.current_item_id = None
    except Exception:
        pass


def arm_party_loot_side(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    ownership_filter: bool,
) -> None:
    """Append in-range ``PICKUP`` to ``side_intents`` (does not clear)."""
    from app._03_world import ActionType
    from app._04_decision.types import ActionIntent

    if state is None or blackboard is None:
        return
    primary = getattr(blackboard, "intent", None)
    if primary is not None and getattr(primary, "action", None) is ActionType.PICKUP:
        return
    sides = getattr(blackboard, "side_intents", None) or []
    if any(getattr(s, "action", None) is ActionType.PICKUP for s in sides):
        return
    item = find_party_pickup_range_loot(
        state, blackboard, ownership_filter=ownership_filter
    )
    if item is None:
        return
    try:
        from app._04_decision.loot_sides import _log_side_loot_decide

        _log_side_loot_decide(blackboard, item)
    except Exception:
        pass
    blackboard.side_intents.append(
        ActionIntent(
            action=ActionType.PICKUP,
            target_id=int(item.track_id),
            priority=0.3,
            reason="party side loot in range",
            mid_act=False,
        )
    )


def find_party_pickup_range_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    ownership_filter: bool,
) -> Optional["WorldObject"]:
    """Nearest lootable pile already within pickup tiles."""
    from app._04_decision.attack_feedback import excluded_target_ids
    from app._04_decision.behaviors.combat import GIVE_UP_COOLDOWN_TICKS
    from app._04_decision.behaviors.loot_hop import recently_clicked_loot
    from app._04_decision.behaviors.mode_actions import _effective_loot_mode
    from app._04_decision.combat_query import (
        is_adena,
        list_lootable,
        tile_distance_from_player,
    )
    from app._04_decision.loot_sides import _item_in_pickup_range
    from app._04_decision.mode_control import is_hp_zero

    if is_hp_zero(state):
        return None

    loot_mode = _effective_loot_mode(state)
    origin = blackboard.world_origin
    skip = set(excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )

    sticky_id = blackboard.current_item_id
    if sticky_id is not None and int(sticky_id) not in skip:
        sticky = state.get_object(int(sticky_id))
        if sticky is not None and _item_in_pickup_range(state, sticky, origin):
            if ownership_filter:
                from app._04_decision.ground_loot import loot_ownership_allowed

                if not loot_ownership_allowed(sticky):
                    sticky = None
                else:
                    return sticky
            else:
                return sticky

    candidates = list_lootable(
        state,
        loot_mode=loot_mode,
        farm=None,
        origin=origin,
        check_path=False,
        exclude=skip,
        screen_only=False,
        ownership_filter=ownership_filter,
    )
    in_range: list = []
    for item in candidates:
        if _item_in_pickup_range(state, item, origin):
            in_range.append(item)
    if not in_range:
        return None

    return min(
        in_range,
        key=lambda o: (
            0 if is_adena(o) else 1,
            tile_distance_from_player(o),
            int(getattr(o, "track_id", 0)),
        ),
    )


def try_party_hold_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    ownership_filter: bool,
    max_tiles: int = 8,
) -> Any:
    """Primary walk-to-item / pickup while HOLD near the leader.

    Returns an ActionIntent when loot won this tick, else None.
    """
    from app._03_world import ObjectType
    from app._04_decision.attack_feedback import excluded_target_ids
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors.combat import GIVE_UP_COOLDOWN_TICKS
    from app._04_decision.behaviors.loot_hop import (
        begin_loot_item,
        clear_loot_hop,
        recently_clicked_loot,
        tick_loot_item,
        try_finish_pending_pickup,
    )
    from app._04_decision.behaviors.mode_actions import _effective_loot_mode
    from app._04_decision.combat_query import (
        memory_target_gone,
        nearest_lootable,
        tile_distance_from_player,
    )
    from app._04_decision.ground_loot import loot_ownership_allowed
    from app._04_decision.mode_control import is_hp_zero

    if state is None or blackboard is None or is_hp_zero(state):
        return None

    pending = try_finish_pending_pickup(state, blackboard)
    if pending is not None:
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            _tag_party_loot(intent)
            return intent

    loot_mode = _effective_loot_mode(state)
    skip = set(excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )

    if blackboard.current_item_id is not None:
        sticky = state.get_object(int(blackboard.current_item_id))
        drop = False
        if (
            sticky is None
            or getattr(sticky, "object_type", None) is not ObjectType.ITEM
            or memory_target_gone(state, sticky)
            or recently_clicked_loot(blackboard, sticky.track_id)
        ):
            drop = True
        elif ownership_filter and not loot_ownership_allowed(sticky):
            drop = True
        elif tile_distance_from_player(sticky) > int(max_tiles):
            drop = True
        if drop:
            clear_loot_hop(blackboard)
            blackboard.current_item_id = None
        else:
            status = tick_loot_item(state, blackboard, sticky, fresh=False)
            if status is Status.SUCCESS:
                intent = getattr(blackboard, "intent", None)
                if intent is not None:
                    _tag_party_loot(intent)
                    return intent
            return None

    item = nearest_lootable(
        state,
        loot_mode=loot_mode,
        farm=None,
        origin=blackboard.world_origin,
        check_path=False,
        exclude=skip,
        screen_only=False,
        ownership_filter=ownership_filter,
    )
    if item is None:
        return None
    if tile_distance_from_player(item) > int(max_tiles):
        return None
    begin_loot_item(blackboard, int(item.track_id), item)
    status = tick_loot_item(state, blackboard, item, fresh=True)
    if status is Status.SUCCESS:
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            _tag_party_loot(intent)
            return intent
    return None


def _tag_party_loot(intent: Any) -> None:
    why = str(getattr(intent, "reason", "") or "")
    if why.startswith("party_member:"):
        return
    try:
        intent.reason = f"party_member:loot {why}".strip()
    except Exception:
        pass


__all__ = [
    "arm_party_loot_side",
    "clear_party_loot_sticky",
    "find_party_pickup_range_loot",
    "party_loot_ownership_filter",
    "party_may_loot",
    "try_party_hold_loot",
]
