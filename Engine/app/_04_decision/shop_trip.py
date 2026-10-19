"""Shop trip: travel to an NPC behavior, then run calibrated buy/sell.

Priority (one action family): overweight sell → HP potion → depoison → arrows.
Sell has no NPC picker. Locale + sell_mode pick the four merchant behaviors.
Each sell trip shuffles those four. The warehouse keeper stays after them
when ``store_after_sell`` is checked and the bag still holds something
outside the keep list. Unchecked, the trip ends after the four merchants.
Weight trigger uses Recovery Fix/Return gauge.
"""
from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Optional

from app._03_world import ActionType
from app._03_world.space.map_pack import get_active_map_pack
from app._04_decision.behavior_tree import Status
from app._04_decision.player_mode import PlayerMode
from app._04_decision import shops as shops_mod
from app._04_decision.shops import (
    resolve_sell_behavior_ids,
    resolve_shopping_behavior_id,
)
from app._04_decision.talking_scroll import (
    PURPOSE_SHOP,
    SCRATCH_SHOP_TRIP,
    emit_talking_scroll,
)
from app._05_action.spell_box import slot_is_enabled

if TYPE_CHECKING:
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

SCRATCH_SHOP_ID = "shop_id"  # legacy alias
SCRATCH_SHOP_BEHAVIOR = "shop_behavior_id"
SCRATCH_SHOP_SCROLLED = "shop_scrolled"
SCRATCH_SHOP_SCROLLED_AT = "shop_scrolled_at"
SCRATCH_SHOP_SCROLL_RETRIES = "shop_scroll_retries"
SCRATCH_SHOP_HALTED = "shop_halted"
SCRATCH_SELL_QUEUE = "shop_sell_queue"
# HP retreat decided: "selling" while the sell queue runs, then "retreat".
SCRATCH_HP_SELL_BEFORE_RETREAT = "hp_sell_before_retreat"
# Weight at the retreat decision. 50% sells first; below that retreats now.
HP_RETREAT_SELL_WEIGHT = 0.50
GIVE_GOODS_ID = "give_goods"

# After talking-scroll emit, wait this long for landing before retry/cancel.
SHOP_LANDING_WAIT_S = 25.0
SHOP_SCROLL_MAX_RETRIES = 2


def ensure_shopping_mode(blackboard: "Blackboard") -> None:
    """Sticky ``PlayerMode.SHOPPING`` while a shop trip owns the character."""
    from app._04_decision.mode_control import set_mode

    if blackboard.player_mode is not PlayerMode.SHOPPING:
        set_mode(blackboard, PlayerMode.SHOPPING)


def begin_shopping(blackboard: "Blackboard", reason: str = "shop") -> None:
    """Enter ``SHOPPING`` mode (trip arm happens in ``tick_shop_trip``)."""
    del reason
    from app._04_decision.farm_tour import remember_return_farm

    remember_return_farm(blackboard)
    ensure_shopping_mode(blackboard)


def leave_shopping_mode_if_idle(blackboard: "Blackboard") -> None:
    """Leave ``SHOPPING`` when the trip scratch is gone.

    Prefers a pending ``need_world_nav`` (e.g. after_shop) over bare farming.
    """
    from app._04_decision.mode_control import set_mode

    if blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        return
    if blackboard.player_mode is not PlayerMode.SHOPPING:
        return
    from app._04_decision.world_nav import (
        SCRATCH_NEED_WORLD_NAV,
        begin_world_nav,
    )

    need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)
    if need:
        begin_world_nav(blackboard, str(need))
        return
    set_mode(blackboard, PlayerMode.FARMING)


def shopping_blocks_teleport(blackboard: "Blackboard") -> bool:
    """True for the whole shop trip (scroll settle through buy/sell).

    Practice has no farming loop. Live must not confined-teleport off the
    landing while the 2s scroll settle / Esc / NPC click runs.

    Absolute survival (emergency PK/surround TP, HP retreat starters) bypasses
    this gate at the call site — see ``_maybe_emergency_teleport`` and
    ``apply_hp_actions``.
    """
    return bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))


def needs_potion_restock(blackboard: "Blackboard") -> bool:
    if not shops_mod.RESTOCK_POTIONS:
        return False
    if time.time() < float(getattr(blackboard, "potion_suppress_until", 0.0) or 0.0):
        return False
    return bool(getattr(blackboard, "needs_potion", False))


def needs_depoison_buy(blackboard: "Blackboard") -> bool:
    if not shops_mod.BUY_DEPOISON:
        return False
    if time.time() < float(getattr(blackboard, "depoison_suppress_until", 0.0) or 0.0):
        return False
    return bool(getattr(blackboard, "needs_depoison", False))


def needs_arrow_buy(blackboard: "Blackboard") -> bool:
    if not bool(getattr(blackboard, "needs_arrows", False)):
        return False
    return bool(shops_mod.BUY_NORMAL_ARROWS or shops_mod.BUY_SILVER_ARROWS)


def bag_weight_ratio(state: "GameState") -> float:
    """Bag fill 0..1 from decoded WEIGHT (0x300), stored as ``weight_ratio``."""
    player = getattr(state, "player", None)
    if player is None:
        return 0.0
    inv = getattr(player, "inventory", None)
    if inv is None:
        return 0.0
    try:
        return max(0.0, min(1.0, float(getattr(inv, "weight_ratio", 0.0) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def needs_sell(state: "GameState") -> bool:
    """True when bag weight meets Recovery Fix/Return weight gauge."""
    if not shops_mod.RETURN_WEIGHT_ENABLED:
        return False
    return bag_weight_ratio(state) >= float(shops_mod.SELL_WEIGHT_RATIO)


# Back-compat alias used by older imports / farm BT.
needs_sell_garbage = needs_sell


def _shuffled_sell_ids() -> list[str]:
    """The four sell merchants, visit order shuffled. Warehouse is not included."""
    queue = [str(x) for x in resolve_sell_behavior_ids() if str(x).strip()]
    random.shuffle(queue)
    if queue:
        from app.bot_log import get_logger

        get_logger("shop").info("sell npc order %s", " → ".join(queue))
    return queue


def _begin_sell_queue(blackboard: "Blackboard") -> Optional[str]:
    queue = _shuffled_sell_ids()
    if not queue:
        return None
    first = queue[0]
    blackboard.scratch[SCRATCH_SELL_QUEUE] = queue[1:]
    return first


def _bag_needs_give_goods(state: "GameState | None") -> bool:
    """True when the bag still holds something outside the keep list.

    An unread bag still visits ``give_goods`` so leftovers are not skipped.
    """
    from shop.behaviors import (
        SELL_MODE_EXCEPT_KEEP,
        item_passes_sell_filter,
        load_sell_filters,
    )

    player = getattr(state, "player", None) if state is not None else None
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return True
    filters = load_sell_filters()
    for item in list(getattr(inv, "items", None) or []):
        try:
            item_id = int(getattr(item, "item_id", 0) or 0)
        except (TypeError, ValueError):
            item_id = 0
        if item_passes_sell_filter(
            str(getattr(item, "name", "") or ""),
            sell_mode=SELL_MODE_EXCEPT_KEEP,
            garbage_list=filters.garbage_list,
            keep_list=filters.keep_list,
            item_id=item_id,
        ):
            return True
    return False


def _arm_next_shop(blackboard: "Blackboard", behavior_id: str, rest: list[str]) -> str:
    blackboard.scratch[SCRATCH_SELL_QUEUE] = rest
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED_AT, None)
    blackboard.scratch.pop(SCRATCH_SHOP_HALTED, None)
    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = behavior_id
    blackboard.scratch[SCRATCH_SHOP_ID] = behavior_id
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    return behavior_id


def advance_sell_trip(
    blackboard: "Blackboard", state: "GameState | None" = None
) -> Optional[str]:
    """After one sell succeeds, start the next sell shop or end the trip.

    When the merchant queue is done, ``store_after_sell`` is checked, and the
    bag still has items outside the keep list, ``give_goods`` runs before the
    trip ends. The following tick then picks the next needed NPC (potions, arrows).
    """
    remaining = blackboard.scratch.get(SCRATCH_SELL_QUEUE)
    if isinstance(remaining, list) and remaining:
        next_id = str(remaining[0] or "").strip()
        rest = [str(x) for x in remaining[1:] if str(x).strip()]
        if next_id:
            return _arm_next_shop(blackboard, next_id, rest)
    current = str(blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR) or "")
    if (
        shops_mod.STORE_AFTER_SELL
        and current != GIVE_GOODS_ID
        and _bag_needs_give_goods(state)
    ):
        from app.bot_log import get_logger

        get_logger("shop").info("sell done, leftovers outside keep list → give_goods")
        return _arm_next_shop(blackboard, GIVE_GOODS_ID, [])
    clear_shop_trip(blackboard)
    return None


def choose_shopping_behavior(
    state: "GameState", blackboard: "Blackboard"
) -> Optional[str]:
    """Highest-priority needed behavior id, or sticky mid-trip id."""
    sticky = str(blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR) or "").strip()
    if sticky:
        return sticky
    remaining = blackboard.scratch.get(SCRATCH_SELL_QUEUE)
    if isinstance(remaining, list) and remaining:
        # Resume a sell chain if sticky was lost mid-trip.
        nxt = str(remaining[0] or "").strip()
        blackboard.scratch[SCRATCH_SELL_QUEUE] = [
            str(x) for x in remaining[1:] if str(x).strip()
        ]
        if nxt:
            return nxt
    # Overweight sell first so perpetual potion/arrow restock cannot block it.
    # No sell_npc picker — the four merchants are shuffled per trip.
    if needs_sell(state):
        return _begin_sell_queue(blackboard)
    if needs_potion_restock(blackboard):
        from app._04_decision.hunt_area import current_adena
        from app._04_decision.shops import HP_POTION_PRICE

        adena = current_adena(state)
        if adena is not None and int(adena) < int(HP_POTION_PRICE):
            blackboard.needs_potion = False
        else:
            return resolve_shopping_behavior_id("hp")
    if needs_depoison_buy(blackboard):
        return resolve_shopping_behavior_id("depoison")
    if needs_arrow_buy(blackboard):
        if shops_mod.BUY_SILVER_ARROWS and not shops_mod.BUY_NORMAL_ARROWS:
            return resolve_shopping_behavior_id("silver_arrows")
        return resolve_shopping_behavior_id("normal_arrows")
    return None


def needs_shop(state: "GameState", blackboard: "Blackboard") -> bool:
    """True when any shopping behavior should run."""
    return choose_shopping_behavior(state, blackboard) is not None


def arm_sell_before_hp_retreat(blackboard: "Blackboard") -> bool:
    """Start the sell queue, then retreat after it finishes.

    Does nothing when a pre-retreat sell is already running. Returns False
    when no sell behavior is configured.
    """
    if blackboard.scratch.get(SCRATCH_HP_SELL_BEFORE_RETREAT) == "selling":
        return True
    from app._04_decision.shops import is_sell_behavior, is_store_behavior

    current = str(blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR) or "")
    if blackboard.scratch.get(SCRATCH_SHOP_TRIP) and (
        is_sell_behavior(current) or is_store_behavior(current)
    ):
        blackboard.scratch[SCRATCH_HP_SELL_BEFORE_RETREAT] = "selling"
        return True
    queue = _shuffled_sell_ids()
    if not queue:
        return False
    _arm_next_shop(blackboard, queue[0], queue[1:])
    blackboard.scratch[SCRATCH_HP_SELL_BEFORE_RETREAT] = "selling"
    from app.bot_log import get_logger

    get_logger("hp").info("hp retreat weight>=%.0f%% → sell then retreat", HP_RETREAT_SELL_WEIGHT * 100)
    return True


def drop_hp_sell_before_retreat(blackboard: "Blackboard") -> None:
    """Forget a pre-retreat sell. Used when death takes over."""
    phase = blackboard.scratch.pop(SCRATCH_HP_SELL_BEFORE_RETREAT, None)
    if phase == "selling" and blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        clear_shop_trip(blackboard)


def clear_shop_trip(blackboard: "Blackboard") -> None:
    from app.bot_log import get_logger

    was = bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))
    bid = blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR)
    sell_then_retreat = (
        blackboard.scratch.get(SCRATCH_HP_SELL_BEFORE_RETREAT) == "selling"
    )
    blackboard.scratch.pop(SCRATCH_SHOP_TRIP, None)
    blackboard.scratch.pop(SCRATCH_SHOP_ID, None)
    blackboard.scratch.pop(SCRATCH_SHOP_BEHAVIOR, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED_AT, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLL_RETRIES, None)
    blackboard.scratch.pop(SCRATCH_SHOP_HALTED, None)
    blackboard.scratch.pop(SCRATCH_SELL_QUEUE, None)
    if sell_then_retreat:
        blackboard.scratch[SCRATCH_HP_SELL_BEFORE_RETREAT] = "retreat"
    if was:
        get_logger("shop").info("clear shop trip behavior=%s", bid)
    leave_shopping_mode_if_idle(blackboard)


def _load_behavior(behavior_id: str):
    from shop.runtime import resolve_behavior

    return resolve_behavior(behavior_id)


def _near_behavior(blackboard: "Blackboard", behavior) -> bool:
    from shop.runtime import near_shop

    return near_shop(blackboard.world_origin, behavior)


def _can_scroll(behavior) -> bool:
    spot = str(getattr(behavior, "scroll_spot", "") or "")
    return slot_is_enabled("talking_scroll") and bool(spot)


def _mark_shop_scrolled(blackboard: "Blackboard") -> None:
    from app.bot_log import get_logger

    blackboard.scratch[SCRATCH_SHOP_SCROLLED] = True
    blackboard.scratch[SCRATCH_SHOP_SCROLLED_AT] = time.time()
    get_logger("shop").info(
        "shop scrolled behavior=%s retry=%s",
        blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR),
        blackboard.scratch.get(SCRATCH_SHOP_SCROLL_RETRIES) or 0,
    )


def _shop_landing_timed_out(blackboard: "Blackboard") -> bool:
    started = float(blackboard.scratch.get(SCRATCH_SHOP_SCROLLED_AT) or 0.0)
    if started <= 0:
        # Legacy trips marked scrolled without a clock — start one now.
        blackboard.scratch[SCRATCH_SHOP_SCROLLED_AT] = time.time()
        return False
    return (time.time() - started) >= float(SHOP_LANDING_WAIT_S)


def _retry_or_abort_shop_landing(
    blackboard: "Blackboard", behavior_id: str
) -> Status | None:
    """After landing wait expires: re-scroll/walk once, then clear the trip."""
    from app.bot_log import get_logger

    retries = int(blackboard.scratch.get(SCRATCH_SHOP_SCROLL_RETRIES) or 0)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED_AT, None)
    if retries >= int(SHOP_SCROLL_MAX_RETRIES):
        get_logger("shop").warning(
            "shop landing timeout — abort behavior=%s after %s retries",
            behavior_id,
            retries,
        )
        clear_shop_trip(blackboard)
        blackboard.current_goal = "shop"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.55,
            reason=f"shop landing timeout ({behavior_id})",
        )
        return Status.SUCCESS
    blackboard.scratch[SCRATCH_SHOP_SCROLL_RETRIES] = retries + 1
    get_logger("shop").info(
        "shop landing timeout — retry %s/%s behavior=%s",
        retries + 1,
        SHOP_SCROLL_MAX_RETRIES,
        behavior_id,
    )
    return None


def _can_walk(behavior) -> bool:
    from app._04_decision.nav_config import navigation_configure_in_progress

    if navigation_configure_in_progress():
        return False
    pack = get_active_map_pack()
    mid = pack.id if pack is not None else ""
    return pack is not None and mid == str(behavior.map_id)


def _at_shop(state: "GameState", blackboard: "Blackboard", behavior) -> bool:
    """True when the live player world tile is near the catalog NPC.

    Practice clicks from the talking-scroll landing using raw memory coords.
    Nav-space checks after a TI→Mainland hop mix origins and either click
    too early or walk into a different Giran stall.
    """
    from shop.runtime import world_near_shop

    if world_near_shop(state, behavior):
        return True
    # Scroll landing can be a bit farther than arrive-tiles; Practice still clicks.
    if blackboard.scratch.get(SCRATCH_SHOP_SCROLLED) and world_near_shop(
        state, behavior, tiles=20
    ):
        return True
    from shop.runtime import close_enough_to_click

    return close_enough_to_click(blackboard.world_origin, behavior)


def _emit_shop_stop(blackboard: "Blackboard") -> Status:
    from app.bot_log import get_logger

    blackboard.current_goal = "shop"
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    blackboard.scratch[SCRATCH_SHOP_HALTED] = True
    get_logger("shop").info(
        "at shop — stop behavior=%s",
        blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR),
    )
    blackboard.emit(
        ActionType.SHOP_STOP,
        priority=0.7,
        reason="stop at shop",
    )
    return Status.SUCCESS


def _adena_from_state(state: "GameState | None") -> int | None:
    player = getattr(state, "player", None) if state is not None else None
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return None
    try:
        return max(0, int(getattr(inv, "adena", 0) or 0))
    except (TypeError, ValueError):
        return None


def _shop_qty_for_emit(state: "GameState | None", behavior_id: str) -> int | None:
    """Decide-owned buy quantity (incl. HP potion Adena clamp)."""
    from app._04_decision.shops import (
        HP_POTION_BUY_QTY,
        affordable_hp_potion_qty,
        buy_qty_for_behavior,
        is_hp_potion_behavior,
    )

    qty = buy_qty_for_behavior(behavior_id)
    if not is_hp_potion_behavior(behavior_id):
        return qty
    return affordable_hp_potion_qty(
        qty if qty is not None else HP_POTION_BUY_QTY,
        _adena_from_state(state),
    )


def _shop_equip_for_behavior(behavior_id: str) -> str | None:
    bid = str(behavior_id or "").lower()
    if "silver" in bid and "arrow" in bid:
        return "silver"
    if "arrow" in bid:
        return "normal"
    return None


def _emit_shop_run(
    blackboard: "Blackboard",
    behavior,
    behavior_id: str,
    state: "GameState | None" = None,
) -> Status:
    from app.bot_log import get_logger
    from shop.runtime import npc_content_uv

    blackboard.current_goal = "shop"
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = behavior_id
    qty = _shop_qty_for_emit(state, behavior_id)
    kind = str(getattr(behavior, "action", "") or "buy").strip().lower() or "buy"
    equip = _shop_equip_for_behavior(behavior_id)
    get_logger("shop").info(
        "open shop UI behavior=%s kind=%s qty=%s equip=%s",
        behavior_id,
        kind,
        qty,
        equip,
    )
    blackboard.emit(
        ActionType.SHOP_RUN,
        destination=npc_content_uv(behavior, blackboard.world_origin),
        priority=0.7,
        reason=f"shop:{behavior_id}",
        shop_behavior_id=behavior_id,
        shop_qty=qty,
        shop_kind=kind,
        shop_equip=equip,
    )
    return Status.SUCCESS


def tick_shop_trip(state: "GameState", blackboard: "Blackboard") -> Status | None:
    """Go to the chosen shopping behavior NPC and run buy/sell. None if idle."""
    behavior_id = choose_shopping_behavior(state, blackboard)
    if not behavior_id:
        clear_shop_trip(blackboard)
        return None

    behavior = _load_behavior(behavior_id)
    if behavior is None:
        clear_shop_trip(blackboard)
        return None

    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = behavior_id
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    blackboard.scratch[SCRATCH_SHOP_ID] = behavior_id
    from app._04_decision.farm_tour import remember_return_farm

    remember_return_farm(blackboard)
    ensure_shopping_mode(blackboard)

    # Open only when live world coords are at the stall. After a talking-scroll
    # hop, wait here — opening on the old map (common right after login)
    # clicks the wrong UV and fails buy_hp_potions_mainland.
    if _at_shop(state, blackboard, behavior):
        from app._04_decision.behaviors.travel import clear_travel

        if (
            blackboard.travel_purpose == PURPOSE_SHOP
            or blackboard.player_mode is PlayerMode.TRAVELING
        ):
            clear_travel(blackboard)
            blackboard.travel_purpose = None
        ensure_shopping_mode(blackboard)
        if not blackboard.scratch.get(SCRATCH_SHOP_HALTED):
            return _emit_shop_stop(blackboard)
        return _emit_shop_run(blackboard, behavior, behavior_id, state)

    if blackboard.scratch.get(SCRATCH_SHOP_SCROLLED):
        if _shop_landing_timed_out(blackboard):
            aborted = _retry_or_abort_shop_landing(blackboard, behavior_id)
            if aborted is not None:
                return aborted
            # Fall through: re-try scroll / walk / cannot-reach below.
        else:
            blackboard.current_goal = "shop"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.65,
                reason=f"waiting for shop landing ({behavior_id})",
            )
            return Status.SUCCESS

    # Same-map walk under SHOPPING (do not hand off to PlayerMode.TRAVELING).
    if blackboard.travel_purpose == PURPOSE_SHOP and blackboard.nav_goal is not None:
        from app._04_decision.behaviors.travel import (
            emit_travel_hop,
            travel_arrived,
        )

        if travel_arrived(blackboard):
            from app._04_decision.behaviors.travel import clear_travel

            clear_travel(blackboard)
            blackboard.travel_purpose = None
            # Re-check stall on next lines / next tick.
        elif emit_travel_hop(
            blackboard, reason=f"walk to shop ({behavior_id})", priority=0.65
        ):
            return Status.SUCCESS

    if _can_scroll(behavior):
        if emit_talking_scroll(
            blackboard,
            purpose=PURPOSE_SHOP,
            spot_id=behavior.scroll_spot,
            reason=f"go to shop ({behavior_id})",
        ) is Status.SUCCESS:
            _mark_shop_scrolled(blackboard)
            from app._04_decision.behaviors.travel import clear_travel

            clear_travel(blackboard)
            return Status.SUCCESS

    if _can_walk(behavior):
        from app._04_decision.behaviors.travel import emit_travel_hop, start_travel
        from shop.runtime import shop_nav_tile

        start_travel(
            blackboard,
            shop_nav_tile(behavior),
            reason=f"walk to shop ({behavior_id})",
        )
        blackboard.travel_purpose = PURPOSE_SHOP
        ensure_shopping_mode(blackboard)
        if emit_travel_hop(
            blackboard, reason=f"walk to shop ({behavior_id})", priority=0.65
        ):
            return Status.SUCCESS
        blackboard.current_goal = "shop"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.65,
            reason=f"walk to shop blocked ({behavior_id})",
        )
        return Status.SUCCESS

    blackboard.current_goal = "shop"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.65,
        reason=f"cannot reach shop ({behavior_id})",
    )
    return Status.SUCCESS


__all__ = [
    "SCRATCH_SHOP_ID",
    "SCRATCH_SHOP_BEHAVIOR",
    "SCRATCH_SHOP_SCROLLED",
    "SCRATCH_SHOP_SCROLLED_AT",
    "SCRATCH_SHOP_SCROLL_RETRIES",
    "SCRATCH_SHOP_HALTED",
    "SCRATCH_SELL_QUEUE",
    "SHOP_LANDING_WAIT_S",
    "SHOP_SCROLL_MAX_RETRIES",
    "needs_shop",
    "needs_potion_restock",
    "needs_depoison_buy",
    "needs_arrow_buy",
    "bag_weight_ratio",
    "needs_sell",
    "needs_sell_garbage",
    "choose_shopping_behavior",
    "shopping_blocks_teleport",
    "advance_sell_trip",
    "SCRATCH_HP_SELL_BEFORE_RETREAT",
    "HP_RETREAT_SELL_WEIGHT",
    "arm_sell_before_hp_retreat",
    "drop_hp_sell_before_retreat",
    "clear_shop_trip",
    "tick_shop_trip",
    "ensure_shopping_mode",
    "begin_shopping",
    "leave_shopping_mode_if_idle",
]
