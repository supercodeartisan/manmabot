"""Shared party-supply session and shop cleanup.

Leader publish, shopkeeper duty, session reset, death, and demotion call these
helpers so hold/notice/shop scratch do not leak across hunts or sockets.
"""
from __future__ import annotations

from typing import Any, Optional

from ..party_log import get_logger as _party_logger
from .communication import (
    canonical_shopkeeper_name,
    is_canonical_shopkeeper,
    shopkeeper_live_supply,
)
from .scratch_keys import (
    APPROACH_GOAL,
    ARROW_BUY_QTY,
    ATTEMPT,
    CARE_POSE,
    DROP_JOB,
    FLAG,
    JOIN,
    LEADER_HOLD_POSE,
    NAV_GOAL,
    PAUSE,
    PIN,
    SEEN,
    SUPPLY_CHAIN,
    SUPPLY_CONFIGURED,
    SUPPLY_ITEM,
    SUPPLY_KEEP,
)
from .supply import DUTY_FOLLOW

_log = _party_logger("member")


def has_shopkeeper_local_state(runtime: Any, board: Any) -> bool:
    """True when this seat owns shopkeeper supply/shop scratch worth aborting."""
    if runtime is not None:
        if getattr(runtime, "supply_hold", None) or getattr(runtime, "supply_notice", None):
            return True
    scratch = getattr(board, "scratch", None) if board is not None else None
    if not isinstance(scratch, dict):
        return False
    return bool(
        scratch.get(FLAG)
        or scratch.get(JOIN)
        or scratch.get(PIN)
        or scratch.get(SUPPLY_CHAIN)
        or scratch.get(SUPPLY_ITEM)
        or scratch.get("shop_trip")
    )


def abort_supply_session(
    runtime: Any = None,
    board: Any = None,
    *,
    reason: str = "supply abort",
    clear_notice: bool = True,
) -> bool:
    """Clear delivery hold/notice/attempt state. Idempotent.

    Leader publish sees empty ``supply_hold`` / ``supply`` on the next
    ``member_state`` and sends wire clears. Does not clear shop trips.
    """
    changed = False
    if runtime is not None:
        if getattr(runtime, "supply_hold", None) is not None:
            runtime.supply_hold = None
            changed = True
        if getattr(runtime, "supply_stand", None) is not None:
            runtime.supply_stand = None
            changed = True
        if clear_notice and getattr(runtime, "supply_notice", None) is not None:
            runtime.supply_notice = None
            changed = True
        try:
            if str(getattr(runtime, "duty_phase", "") or "") in ("shop", "supply"):
                runtime.duty_phase = DUTY_FOLLOW
                changed = True
        except Exception:
            pass
    scratch = getattr(board, "scratch", None) if board is not None else None
    if isinstance(scratch, dict):
        for key in (
            ATTEMPT,
            PAUSE,
            SEEN,
            CARE_POSE,
            APPROACH_GOAL,
            DROP_JOB,
            LEADER_HOLD_POSE,
        ):
            if key in scratch:
                scratch.pop(key, None)
                changed = True
        try:
            from app._04_decision.behaviors.search_hop import clear_search_hop

            clear_search_hop(board)
        except Exception:
            pass
        try:
            from app._04_decision.behaviors.travel import clear_travel

            purpose = str(getattr(board, "travel_purpose", "") or "")
            if purpose in (
                "party supply approach",
                "party arrow drop",
                "party supply pickup",
            ):
                clear_travel(board)
                changed = True
        except Exception:
            pass
    if changed:
        _log.info("supply session abort reason=%s", reason)
    return changed


def abort_party_shop(
    board: Any = None,
    manager: Any = None,
    *,
    reason: str = "party shop abort",
    clear_join_nav: Optional[bool] = None,
) -> bool:
    """Clear party shop buy/join scratch and an in-progress shop trip. Idempotent.

    ``PartyJoinNav`` (other-map follow) is cleared only when the supply
    ``party_join_leader`` flag was set, or when ``clear_join_nav`` is True
    (hunt close / session / death). Idle ``no supply duty`` must not cancel
    a normal map join.
    """
    changed = False
    scratch = getattr(board, "scratch", None) if board is not None else None
    had_join_flag = False
    if isinstance(scratch, dict):
        had_join_flag = bool(scratch.get(JOIN))
        had = bool(
            scratch.get(FLAG)
            or scratch.get(PIN)
            or had_join_flag
            or scratch.get(SUPPLY_CHAIN)
            or scratch.get(SUPPLY_ITEM)
            or scratch.get(ARROW_BUY_QTY)
            or scratch.get(SUPPLY_KEEP)
            or scratch.get(SUPPLY_CONFIGURED)
            or scratch.get("shop_trip")
        )
        for key in (
            FLAG,
            PIN,
            JOIN,
            SUPPLY_CHAIN,
            SUPPLY_ITEM,
            ARROW_BUY_QTY,
            SUPPLY_KEEP,
            SUPPLY_CONFIGURED,
            NAV_GOAL,
        ):
            if key in scratch:
                scratch.pop(key, None)
                changed = True
        if scratch.get("shop_trip") or had:
            try:
                from app._04_decision.shop_trip import clear_shop_trip

                clear_shop_trip(board)
                changed = True
            except Exception:
                pass
        else:
            for key in (
                "shop_scrolled",
                "shop_scrolled_at",
                "shop_halted",
                "shop_scroll_retries",
            ):
                if scratch.pop(key, None) is not None:
                    changed = True
        try:
            from app._04_decision.world_nav.hooks import SCRATCH_WORLD_NAV

            session = scratch.get(SCRATCH_WORLD_NAV)
            if getattr(session, "reason", "") in (
                "party_join_leader",
                "party_supply_walk",
            ):
                scratch.pop(SCRATCH_WORLD_NAV, None)
                changed = True
        except Exception:
            pass
    drop_join = (
        bool(clear_join_nav)
        if clear_join_nav is not None
        else had_join_flag
    )
    if manager is not None and drop_join:
        join = getattr(manager, "_join_nav", None)
        if join is not None and (
            bool(getattr(join, "active", False))
            or getattr(join, "session", None) is not None
        ):
            try:
                join.clear()
                changed = True
            except Exception:
                pass
    if runtime_phase_follow(manager):
        changed = True
    if changed:
        _log.info("party shop abort reason=%s", reason)
    return changed


def runtime_phase_follow(manager: Any) -> bool:
    runtime = getattr(manager, "runtime", None) if manager is not None else None
    if runtime is None:
        return False
    try:
        if str(getattr(runtime, "duty_phase", "") or "") in ("shop", "supply"):
            runtime.duty_phase = DUTY_FOLLOW
            return True
    except Exception:
        return False
    return False


def abort_party_supply(
    runtime: Any = None,
    board: Any = None,
    manager: Any = None,
    *,
    reason: str = "party supply abort",
    clear_notice: bool = True,
) -> bool:
    """Abort delivery and shop together (hunt close / session / death)."""
    a = abort_supply_session(
        runtime, board, reason=reason, clear_notice=clear_notice
    )
    b = abort_party_shop(
        board, manager, reason=reason, clear_join_nav=True
    )
    return a or b


__all__ = [
    "abort_party_shop",
    "abort_party_supply",
    "abort_supply_session",
    "canonical_shopkeeper_name",
    "has_shopkeeper_local_state",
    "is_canonical_shopkeeper",
    "shopkeeper_live_supply",
]
