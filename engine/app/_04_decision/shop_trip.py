"""Shop trip: travel to a shopping behavior NPC, then run calibrated buy/sell.

Priority (one action family): overweight sell → HP potion → depoison → arrows.
Sell has no NPC picker. Locale + sell_mode pick two YAML behaviors in order
(general goods, then weapon). Weight trigger uses Recovery Fix/Return gauge.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app._03_world import ActionType
from app._03_world.map_pack import get_active_map_pack
from app._03_world.world_coords import tile_chebyshev
from app._04_decision.behavior_tree import Status
from app._04_decision.player_mode import PlayerMode
from app._04_decision import shops as shops_mod
from app._04_decision.shops import (
    is_arrow_behavior,
    is_sell_behavior,
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

# After talking-scroll emit, wait this long for landing before retry/cancel.
SHOP_LANDING_WAIT_S = 25.0
SHOP_SCROLL_MAX_RETRIES = 2


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
    """Bag fill 0..1 from memory weight/maxWeight, else HUD ``weight_ratio``."""
    player = getattr(state, "player", None)
    if player is None:
        return 0.0
    try:
        max_w = float(getattr(player, "max_weight", 0.0) or 0.0)
        cur = float(getattr(player, "weight", 0.0) or 0.0)
    except (TypeError, ValueError):
        max_w, cur = 0.0, 0.0
    if max_w > 0:
        return max(0.0, min(1.0, cur / max_w))
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


def _begin_sell_queue(blackboard: "Blackboard") -> Optional[str]:
    queue = [str(x) for x in resolve_sell_behavior_ids() if str(x).strip()]
    if not queue:
        return None
    first = queue[0]
    blackboard.scratch[SCRATCH_SELL_QUEUE] = queue[1:]
    return first


def advance_sell_trip(blackboard: "Blackboard") -> Optional[str]:
    """After one sell succeeds, start the next sell shop or end the trip."""
    remaining = blackboard.scratch.get(SCRATCH_SELL_QUEUE)
    if not isinstance(remaining, list) or not remaining:
        clear_shop_trip(blackboard)
        return None
    next_id = str(remaining[0] or "").strip()
    rest = [str(x) for x in remaining[1:] if str(x).strip()]
    if not next_id:
        clear_shop_trip(blackboard)
        return None
    blackboard.scratch[SCRATCH_SELL_QUEUE] = rest
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED_AT, None)
    blackboard.scratch.pop(SCRATCH_SHOP_HALTED, None)
    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = next_id
    blackboard.scratch[SCRATCH_SHOP_ID] = next_id
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    return next_id


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
    # No sell_npc picker — YAML behavior ids already name both shop visits.
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


def clear_shop_trip(blackboard: "Blackboard") -> None:
    from app.bot_log import get_logger

    was = bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))
    bid = blackboard.scratch.get(SCRATCH_SHOP_BEHAVIOR)
    blackboard.scratch.pop(SCRATCH_SHOP_TRIP, None)
    blackboard.scratch.pop(SCRATCH_SHOP_ID, None)
    blackboard.scratch.pop(SCRATCH_SHOP_BEHAVIOR, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLLED_AT, None)
    blackboard.scratch.pop(SCRATCH_SHOP_SCROLL_RETRIES, None)
    blackboard.scratch.pop(SCRATCH_SHOP_HALTED, None)
    blackboard.scratch.pop(SCRATCH_SELL_QUEUE, None)
    if was:
        get_logger("shop").info("clear shop trip behavior=%s", bid)


def _load_behavior(behavior_id: str):
    from manmabot_v1.shopping.runtime import resolve_behavior

    return resolve_behavior(behavior_id)


def _near_behavior(blackboard: "Blackboard", behavior) -> bool:
    from manmabot_v1.shopping.runtime import near_shop

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
    from manmabot_v1.shopping.runtime import world_near_shop

    if world_near_shop(state, behavior):
        return True
    # Scroll landing can be a bit farther than arrive-tiles; Practice still clicks.
    if blackboard.scratch.get(SCRATCH_SHOP_SCROLLED) and world_near_shop(
        state, behavior, tiles=20
    ):
        return True
    from manmabot_v1.shopping.runtime import close_enough_to_click

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


def _emit_shop_run(blackboard: "Blackboard", behavior, behavior_id: str) -> Status:
    from app.bot_log import get_logger
    from manmabot_v1.shopping.runtime import npc_content_uv

    blackboard.current_goal = "shop"
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = behavior_id
    get_logger("shop").info("open shop UI behavior=%s", behavior_id)
    blackboard.emit(
        ActionType.SHOP_BUY_ARROWS,  # generic shop-run intent (name kept for recover)
        destination=npc_content_uv(behavior, blackboard.world_origin),
        priority=0.7,
        reason=f"shop:{behavior_id}",
        shop_behavior_id=behavior_id,
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
        # Unknown / missing YAML — arrows can still use recover stub travel via shops.yaml
        if is_arrow_behavior(behavior_id):
            return _tick_legacy_arrows(state, blackboard)
        clear_shop_trip(blackboard)
        return None

    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = behavior_id
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    blackboard.scratch[SCRATCH_SHOP_ID] = behavior_id

    # Open only when live world coords are at the stall. After a talking-scroll
    # hop, wait here — opening on the old map (common right after login)
    # clicks the wrong UV and fails buy_hp_potions_mainland.
    if _at_shop(state, blackboard, behavior):
        if blackboard.player_mode is PlayerMode.TRAVELING:
            from app._04_decision.mode_control import complete_travel_arrival

            complete_travel_arrival(blackboard)
        if not blackboard.scratch.get(SCRATCH_SHOP_HALTED):
            return _emit_shop_stop(blackboard)
        return _emit_shop_run(blackboard, behavior, behavior_id)

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

    traveling_to_shop = (
        blackboard.player_mode is PlayerMode.TRAVELING
        and blackboard.travel_purpose == PURPOSE_SHOP
    )
    if traveling_to_shop:
        return None

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
        from app._04_decision.mode_control import begin_travel
        from manmabot_v1.shopping.runtime import shop_nav_tile

        begin_travel(
            blackboard,
            shop_nav_tile(behavior),
            purpose=PURPOSE_SHOP,
            reason=f"walk to shop ({behavior_id})",
        )
        return Status.FAILURE

    blackboard.current_goal = "shop"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.65,
        reason=f"cannot reach shop ({behavior_id})",
    )
    return Status.SUCCESS


def _tick_legacy_arrows(state: "GameState", blackboard: "Blackboard") -> Status | None:
    """Recover path: old shops.yaml + hardcoded buy UI when YAML behavior missing."""
    from app._03_world.memory_sync import get_map_origin
    from app._04_decision.nav_config import navigation_configure_in_progress
    from app._04_decision.shops import get_shops, shop_by_id

    sticky = str(blackboard.scratch.get(SCRATCH_SHOP_ID) or "")
    shop = None
    if sticky and not is_arrow_behavior(sticky) and not is_sell_behavior(sticky):
        shop = shop_by_id(sticky)
    if shop is None:
        shops = get_shops()
        if not shops:
            clear_shop_trip(blackboard)
            return None
        pack = get_active_map_pack()
        mid = pack.id if pack is not None else ""
        for s in shops:
            if s.map_id == mid:
                shop = s
                break
        if shop is None:
            shop = shops[0]

    arrow_id = resolve_shopping_behavior_id(
        "silver_arrows"
        if shops_mod.BUY_SILVER_ARROWS and not shops_mod.BUY_NORMAL_ARROWS
        else "normal_arrows"
    )
    blackboard.scratch[SCRATCH_SHOP_ID] = shop.id
    blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    blackboard.scratch[SCRATCH_SHOP_BEHAVIOR] = arrow_id

    nav = shop.nav_tile(get_map_origin())
    near = (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            nav[0],
            nav[1],
        )
        <= shops_mod.SHOP_CLICK_TILES
    )
    pack = get_active_map_pack()
    can_walk = (
        not navigation_configure_in_progress()
        and pack is not None
        and pack.id == shop.map_id
    )
    at = near

    if at:
        if blackboard.player_mode is PlayerMode.TRAVELING:
            from app._04_decision.mode_control import complete_travel_arrival

            complete_travel_arrival(blackboard)
        if not blackboard.scratch.get(SCRATCH_SHOP_HALTED):
            return _emit_shop_stop(blackboard)
        blackboard.current_goal = "shop"
        blackboard.emit(
            ActionType.SHOP_BUY_ARROWS,
            destination=shop.npc_click_uv(blackboard.world_origin),
            priority=0.7,
            reason="buy arrows (recover stub)",
            shop_behavior_id="",
        )
        return Status.SUCCESS

    traveling = (
        blackboard.player_mode is PlayerMode.TRAVELING
        and blackboard.travel_purpose == PURPOSE_SHOP
    )
    if traveling:
        return None

    if (
        not blackboard.scratch.get(SCRATCH_SHOP_SCROLLED)
        and slot_is_enabled("talking_scroll")
        and shop.scroll_click_uv() is not None
    ):
        if emit_talking_scroll(
            blackboard,
            purpose=PURPOSE_SHOP,
            spot_id=shop.scroll_spot,
            reason="go to shop (recover)",
        ) is Status.SUCCESS:
            _mark_shop_scrolled(blackboard)
            from app._04_decision.behaviors.travel import clear_travel

            clear_travel(blackboard)
            return Status.SUCCESS

    if can_walk:
        from app._04_decision.mode_control import begin_travel

        begin_travel(
            blackboard,
            nav,
            purpose=PURPOSE_SHOP,
            reason="walk to shop (recover)",
        )
        return Status.FAILURE

    blackboard.emit(
        ActionType.IDLE, priority=0.65, reason="cannot reach shop (recover)"
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
    "clear_shop_trip",
    "tick_shop_trip",
]
