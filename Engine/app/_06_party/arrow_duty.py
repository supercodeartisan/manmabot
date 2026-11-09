"""Shopkeeper arrow buy / ground drop, and the short member's pickup.

Solo shop, sell, potions, and post-shop hunt return stay on their own flags.
This module sets ``party_pin_shop_behavior`` and ``party_shopkeeper_arrow``
only on the shopkeeper blackboard.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .arrow_policy import DUTY_FOLLOW, DUTY_SHOP, DUTY_SUPPLY, bag_arrow_count, pick_arrow_duty

_JOIN = "party_join_leader"
_PIN = "party_pin_shop_behavior"
_FLAG = "party_shopkeeper_arrow"
_NEAR = 3


def tick_shopkeeper_duty(
    manager: Any,
    state: Any,
    *,
    self_name: str,
) -> Any:
    """One shopkeeper tick. None lets follow and combat run."""
    runtime = manager.runtime
    board = manager._nav_blackboard
    cfg = manager.config
    if board is None:
        runtime.duty_phase = DUTY_FOLLOW
        return None
    if board.scratch.get(_JOIN):
        runtime.duty_phase = DUTY_SHOP
        return _tick_join(manager, state)

    own = bag_arrow_count(state)
    from .comms.orders import member_orders

    _expire_notice(runtime, member_orders.party_reports, int(cfg.member_arrow_min))
    duty = pick_arrow_duty(
        own,
        member_orders.party_reports,
        member_min=int(cfg.member_arrow_min),
        keeper_min=int(cfg.shopkeeper_arrow_min),
        self_name=self_name,
    )
    if duty is None:
        _clear_shop_flags(board)
        runtime.duty_phase = DUTY_FOLLOW
        runtime.supply_notice = None
        return None
    if duty["kind"] == "buy":
        return _tick_buy(manager, state)
    notice = getattr(runtime, "supply_notice", None)
    if isinstance(notice, dict) and str(notice.get("for") or "") == str(duty["name"]):
        runtime.duty_phase = DUTY_FOLLOW
        return None
    return _tick_drop(manager, state, duty)


def tick_supply_pickup(
    manager: Any,
    state: Any,
    *,
    self_name: str,
) -> Any:
    """The named member walks to the dropped arrows and picks them up."""
    from .comms.orders import member_orders

    claim = member_orders.supply_drop
    if not isinstance(claim, dict) or bool(claim.get("clear")):
        return None
    who = str(claim.get("for") or "").strip()
    me = str(self_name or "").strip()
    if not who or not me or who.casefold() != me.casefold():
        return None
    return _pickup_claim(state, manager._nav_blackboard, claim, manager.runtime)


def leader_supply_pickup(state: Any, blackboard: Any, claim: Optional[dict]) -> Any:
    """Same pickup when the short character is the leader."""
    if not isinstance(claim, dict):
        return None
    return _pickup_claim(state, blackboard, claim, None)


def _tick_buy(manager: Any, state: Any) -> Any:
    from app._04_decision.shop_trip import (
        SCRATCH_SHOP_BEHAVIOR,
        SCRATCH_SHOP_TRIP,
        tick_shop_trip,
    )

    board = manager._nav_blackboard
    runtime = manager.runtime
    runtime.duty_phase = DUTY_SHOP
    runtime.supply_notice = None
    board.scratch[_FLAG] = True
    if not str(board.scratch.get(SCRATCH_SHOP_BEHAVIOR) or "").strip():
        if shops_arrow_id() is None:
            runtime.duty_phase = DUTY_FOLLOW
            return None
        board.scratch[_PIN] = shops_arrow_id()
    status = tick_shop_trip(state, board)
    if status is None and not board.scratch.get(SCRATCH_SHOP_TRIP):
        board.scratch.pop(_PIN, None)
        if board.scratch.get(_JOIN):
            return _tick_join(manager, state)
        runtime.duty_phase = DUTY_FOLLOW
        return None
    intent = getattr(board, "intent", None)
    if intent is not None:
        runtime.last_kind = "shop"
        runtime.last_reason = "arrow shop"
        return intent
    from .intents import idle

    runtime.last_kind = "shop"
    runtime.last_reason = "arrow shop"
    return idle("arrow shop")


def shops_arrow_id() -> Optional[str]:
    from app._04_decision import shops as shops_mod
    from app._04_decision.shops import resolve_shopping_behavior_id

    if not (shops_mod.BUY_NORMAL_ARROWS or shops_mod.BUY_SILVER_ARROWS):
        return None
    if shops_mod.BUY_SILVER_ARROWS and not shops_mod.BUY_NORMAL_ARROWS:
        return resolve_shopping_behavior_id("silver_arrows")
    return resolve_shopping_behavior_id("normal_arrows")


def _tick_drop(manager: Any, state: Any, duty: dict) -> Any:
    runtime = manager.runtime
    board = manager._nav_blackboard
    runtime.duty_phase = DUTY_SUPPLY
    board.scratch.pop(_FLAG, None)
    board.scratch.pop(_PIN, None)
    arrived = _beside_member(manager, state, duty)
    if arrived is not True:
        return arrived
    from .supply_drop import step_ground_drop

    result = step_ground_drop(state, board, int(duty["qty"]))
    if result is None:
        runtime.last_kind = "supply"
        runtime.last_reason = "arrow drop"
        from .intents import idle

        return idle("arrow drop")
    if result.get("blocked"):
        runtime.duty_phase = DUTY_FOLLOW
        runtime.last_reason = str(result.get("reason") or "arrow drop blocked")
        return None
    runtime.supply_notice = {
        "id": f"{duty['name']}:{int(time.time())}",
        "for": str(duty["name"]),
        "map_id": result.get("map_id"),
        "x": result.get("x"),
        "y": result.get("y"),
        "qty": int(duty["qty"]),
        "at": time.time(),
    }
    runtime.duty_phase = DUTY_FOLLOW
    runtime.last_kind = "supply"
    runtime.last_reason = "arrow dropped"
    return None


def _beside_member(manager: Any, state: Any, duty: dict) -> Any:
    """True when standing next to the short member. Otherwise a walk intent."""
    board = manager._nav_blackboard
    origin = getattr(board, "world_origin", None)
    try:
        mx = int(duty.get("x"))
        my = int(duty.get("y"))
        mid = int(duty.get("map_id"))
    except (TypeError, ValueError):
        manager.runtime.duty_phase = DUTY_FOLLOW
        return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    if pose is None or origin is None:
        from .intents import idle

        return idle("arrow drop no pose")
    if int(pose.map_id) != mid:
        return _tick_nav(manager, state, mid, mx, my, reason="party_supply_walk")
    from app._03_world.space.world_coords import tile_chebyshev

    dist = tile_chebyshev(int(origin.x), int(origin.y), mx, my)
    if dist <= _NEAR:
        return True
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel

    goal = (mx, my)
    if getattr(board, "nav_goal", None) != goal:
        start_travel(board, goal, reason="party arrow drop")
    if emit_travel_hop(board, reason="party arrow drop", priority=0.6, state=state):
        intent = getattr(board, "intent", None)
        if intent is not None:
            manager.runtime.last_kind = "supply"
            manager.runtime.last_reason = "walk to member"
            return intent
    from .intents import idle

    return idle("arrow drop walk")


def _expire_notice(runtime: Any, rows: Any, member_min: int) -> None:
    notice = getattr(runtime, "supply_notice", None)
    if not isinstance(notice, dict):
        return
    who = str(notice.get("for") or "").casefold()
    try:
        age = time.time() - float(notice.get("at") or 0.0)
    except (TypeError, ValueError):
        age = 0.0
    count = None
    for row in rows or []:
        if str(row.get("from") or "").strip().casefold() == who:
            from .arrow_policy import report_arrow_count

            count = report_arrow_count(row)
            break
    if age > 90.0 or (count is not None and count >= int(member_min)):
        runtime.supply_notice = None


def _tick_join(manager: Any, state: Any) -> Any:
    tile = getattr(manager.runtime, "sticky_leader_tile", None)
    map_id = getattr(manager.runtime, "leader_map_id", None)
    if tile is None or map_id is None:
        from .intents import idle

        return idle("join leader no pose")
    dist = getattr(manager.runtime, "leader_dist", None)
    same = bool(getattr(manager.runtime, "leader_same_map", False))
    if same and dist is not None and int(dist) <= _NEAR:
        _finish_join(manager)
        return None
    intent = _tick_nav(
        manager,
        state,
        int(map_id),
        int(tile[0]),
        int(tile[1]),
        reason="party_join_leader",
    )
    if intent is None:
        _finish_join(manager)
    return intent


def _tick_nav(
    manager: Any,
    state: Any,
    map_id: int,
    x: int,
    y: int,
    *,
    reason: str,
) -> Any:
    from app._04_decision.talking_scroll import talking_scroll_available
    from app._04_decision.world_nav.hooks import SCRATCH_WORLD_NAV
    from app._04_decision.world_nav.planner_api import Goal
    from app._04_decision.world_nav.session import WorldNavSession, live_pose_from_state

    board = manager._nav_blackboard
    pose = live_pose_from_state(state)
    if pose is None:
        from .intents import idle

        return idle("world nav no pose")
    session = board.scratch.get(SCRATCH_WORLD_NAV)
    goal_key = (reason, int(map_id), int(x), int(y))
    same_goal = (
        isinstance(session, WorldNavSession)
        and session.reason == reason
        and board.scratch.get("party_nav_goal") == goal_key
    )
    if same_goal and session.phase in ("done", "fail"):
        if int(pose.map_id) == int(map_id) or session.phase == "done":
            return None
        if time.time() < float(board.scratch.get("party_nav_retry") or 0.0):
            from .intents import idle

            return idle("world nav retry")
        same_goal = False
    if not same_goal:
        session = WorldNavSession()
        adena = None
        inv = getattr(getattr(state, "player", None), "inventory", None)
        if inv is not None:
            try:
                adena = int(getattr(inv, "adena", 0) or 0)
            except (TypeError, ValueError):
                adena = None
        try:
            ok = session.begin(
                pose,
                Goal("point", int(map_id), int(x), int(y)),
                reason=reason,
                has_talking_scroll=talking_scroll_available(),
                adena=adena,
                use_npc_teleporters=True,
            )
        except Exception:
            ok = False
        board.scratch[SCRATCH_WORLD_NAV] = session
        board.scratch["party_nav_goal"] = goal_key
        if not ok:
            board.scratch["party_nav_retry"] = time.time() + 5.0
            if int(pose.map_id) == int(map_id):
                return None
            from .intents import idle

            return idle("world nav no plan")
    try:
        session.tick(state, board)
    except Exception:
        from .intents import idle

        return idle("world nav tick")
    if session.phase in ("done", "fail") and int(pose.map_id) == int(map_id):
        return None
    intent = getattr(board, "intent", None)
    if intent is not None:
        manager.runtime.last_kind = "shop" if reason == "party_join_leader" else "supply"
        manager.runtime.last_reason = reason
        return intent
    from .intents import idle

    return idle(reason)


def _finish_join(manager: Any) -> None:
    board = manager._nav_blackboard
    if board is not None:
        _clear_shop_flags(board)
        from app._04_decision.world_nav.hooks import SCRATCH_WORLD_NAV

        session = board.scratch.get(SCRATCH_WORLD_NAV)
        if getattr(session, "reason", "") in ("party_join_leader", "party_supply_walk"):
            board.scratch.pop(SCRATCH_WORLD_NAV, None)
        board.scratch.pop("party_nav_goal", None)
    manager.runtime.duty_phase = DUTY_FOLLOW


def _clear_shop_flags(board: Any) -> None:
    board.scratch.pop(_FLAG, None)
    board.scratch.pop(_PIN, None)
    board.scratch.pop(_JOIN, None)


def _pickup_claim(state: Any, blackboard: Any, claim: dict, runtime: Any) -> Any:
    if blackboard is None:
        return None
    try:
        tx = int(claim.get("x"))
        ty = int(claim.get("y"))
        mid = int(claim.get("map_id"))
    except (TypeError, ValueError):
        return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    origin = getattr(blackboard, "world_origin", None)
    if pose is None or origin is None or int(pose.map_id) != mid:
        return None
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.combat_query import is_adena, list_lootable, object_absolute_tile

    dist = tile_chebyshev(int(origin.x), int(origin.y), tx, ty)
    pile = None
    if dist <= 8:
        for item in list_lootable(
            state,
            loot_mode="all_items",
            farm=None,
            origin=origin,
            check_path=False,
            ownership_filter=False,
        ):
            try:
                tile = object_absolute_tile(item, origin)
            except Exception:
                continue
            if tile is None or is_adena(item):
                continue
            if tile_chebyshev(int(tile[0]), int(tile[1]), tx, ty) <= 2:
                pile = item
                break
    if pile is not None and dist <= 2:
        from app._02_state.enums import ActionType
        from .types import ActionIntent

        if runtime is not None:
            runtime.last_kind = "supply"
            runtime.last_reason = "pick up arrows"
        return ActionIntent(
            action=ActionType.PICKUP,
            target_id=int(getattr(pile, "track_id", 0)),
            priority=0.7,
            reason="party_member:supply arrows",
        )
    if dist <= _NEAR and pile is None:
        return None
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel

    goal = (tx, ty)
    if getattr(blackboard, "nav_goal", None) != goal:
        start_travel(blackboard, goal, reason="party supply pickup")
    if emit_travel_hop(
        blackboard, reason="party supply pickup", priority=0.6, state=state
    ):
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            if runtime is not None:
                runtime.last_kind = "supply"
                runtime.last_reason = "walk to arrows"
            return intent
    return None
