"""Loot side-intent: F4 pickup while another ActionIntent is primary.

Approach (SEARCHING) stays exclusive to primary loot. When any other primary
wins the ladder, decide still arms ``PICKUP`` on ``side_intents`` if an item
is already in pickup range so Action can F4 before the primary runs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._04_decision.types import ActionIntent

if TYPE_CHECKING:
    from app._02_state.objects import WorldObject
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


def _log_side_loot_decide(blackboard: "Blackboard", item: "WorldObject") -> None:
    """Log a side F4 choice once per id and claim, not every tick."""
    from app.bot_log import event
    from app._04_decision.ground_loot import format_loot_claim

    claim = format_loot_claim(item)
    key = (int(item.track_id), claim)
    if blackboard.scratch.get("_loot_side_decide") == key:
        return
    blackboard.scratch["_loot_side_decide"] = key
    event(
        "loot",
        "loot decide via=side gate=arm id=%s %s",
        int(item.track_id),
        claim,
    )


def arm_loot_side_intent(state: "GameState", blackboard: "Blackboard") -> None:
    """Append a standing F4 when no attack, walk, or sticky loot owns the tick.

    Combat and travel keep their primary click. A pile already being walked
    or confirmed stays on the normal loot path so a side F4 cannot clear it.
    The party leader never loots.
    """
    if blackboard.scratch.get("party_leader_no_loot"):
        return
    if blackboard.loot_await_gone_id is not None or blackboard.current_item_id is not None:
        return
    primary = blackboard.intent
    if primary is not None and primary.action in (
        ActionType.PICKUP,
        ActionType.ATTACK,
        ActionType.SEARCHING,
        ActionType.TRAVELING,
    ):
        return
    if any(s.action is ActionType.PICKUP for s in blackboard.side_intents):
        return
    item = find_pickup_range_loot(state, blackboard)
    if item is None:
        return
    from app._04_decision.behaviors.loot_hop import f4_allowed

    if not f4_allowed(blackboard, state, int(item.track_id)):
        return
    _log_side_loot_decide(blackboard, item)
    blackboard.side_intents.append(
        ActionIntent(
            action=ActionType.PICKUP,
            target_id=int(item.track_id),
            priority=0.3,
            reason="side loot in range",
            mid_act=False,
        )
    )


def find_pickup_range_loot(
    state: "GameState", blackboard: "Blackboard"
) -> "WorldObject | None":
    """Nearest lootable pile already within ``LOOT_PICKUP_TILES`` (no approach)."""
    from app._04_decision.attack_feedback import excluded_target_ids
    from app._04_decision.behaviors.loot_hop import recently_clicked_loot
    from app._04_decision.behaviors.mode_actions import _effective_loot_mode
    from app._04_decision.combat_query import (
        is_adena,
        list_lootable,
        tile_distance_from_player,
    )
    from app._04_decision.mode_control import is_hp_zero

    if is_hp_zero(state):
        return None

    from app._04_decision.behaviors.mode_actions import (
        SCRATCH_APPROACH_CORPSE_IDS,
        SCRATCH_APPROACH_HOLD_FIRE,
    )

    hold_fire = bool(blackboard.scratch.get(SCRATCH_APPROACH_HOLD_FIRE))
    corpse_ids = {
        int(item_id)
        for item_id in (blackboard.scratch.get(SCRATCH_APPROACH_CORPSE_IDS) or [])
    }

    loot_mode = _effective_loot_mode(state)
    origin = blackboard.world_origin
    skip = set(excluded_target_ids(blackboard))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )

    # Prefer sticky item if still in pickup range.
    sticky_id = blackboard.current_item_id
    if sticky_id is not None and int(sticky_id) not in skip:
        if not hold_fire or int(sticky_id) in corpse_ids:
            sticky = state.get_object(int(sticky_id))
            if sticky is not None and _item_in_pickup_range(state, sticky, origin):
                return sticky

    candidates = list_lootable(
        state,
        loot_mode=loot_mode,
        farm=None,
        origin=origin,
        check_path=False,
        exclude=skip,
        screen_only=False,
        ownership_filter=False,
    )
    in_range: list = []
    for item in candidates:
        if hold_fire and int(item.track_id) not in corpse_ids:
            continue
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


def _item_in_pickup_range(state, item: "WorldObject", origin) -> bool:
    from app._03_world import ObjectType
    from app._04_decision.behaviors.loot_hop import _in_pickup_range
    from app._04_decision.combat_query import memory_target_gone, object_absolute_tile

    if item is None or getattr(item, "object_type", None) is not ObjectType.ITEM:
        return False
    if memory_target_gone(state, item):
        return False
    item_tile = object_absolute_tile(item, origin)
    return _in_pickup_range(origin, item, item_tile)


__all__ = [
    "arm_loot_side_intent",
    "find_pickup_range_loot",
]
