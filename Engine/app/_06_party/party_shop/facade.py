"""PartyShopModule — single host-facing API for party supply shopping."""
from __future__ import annotations

from typing import Any, Optional

from . import duty as _duty
from .communication import shopkeeper_live_supply
from .session import (
    abort_party_shop,
    abort_party_supply,
    abort_supply_session,
    has_shopkeeper_local_state,
    is_canonical_shopkeeper,
)
from .supply import DUTY_FOLLOW, DUTY_SHOP, DUTY_SUPPLY
from .types import ShopContext, ShopResult, ShopStatus


def _phase_of(runtime: Any) -> str:
    try:
        phase = str(getattr(runtime, "duty_phase", "") or "").strip().lower()
    except Exception:
        phase = ""
    if phase in (DUTY_SHOP, DUTY_SUPPLY, DUTY_FOLLOW):
        return phase
    return DUTY_FOLLOW


def _status_for_intent(intent: Any, runtime: Any, board: Any) -> ShopStatus:
    scratch = getattr(board, "scratch", None) if board is not None else None
    if not isinstance(scratch, dict):
        scratch = {}
    if scratch.get("party_shopkeeper_arrow") or scratch.get("party_pin_shop_behavior"):
        if intent is None:
            return ShopStatus.WAITING
        return ShopStatus.RUNNING
    if getattr(runtime, "supply_hold", None) or getattr(runtime, "supply_stand", None):
        return ShopStatus.WAITING if intent is None else ShopStatus.RUNNING
    if intent is not None:
        return ShopStatus.RUNNING
    return ShopStatus.IDLE


class PartyShopModule:
    """Strangler facade over party supply buy / deliver / pickup."""

    def __init__(self) -> None:
        self._last = ShopResult(status=ShopStatus.IDLE, reason="init")

    def start(self, ctx: ShopContext) -> ShopResult:
        """Arm when supply is open and this seat is the canonical keeper."""
        roster = ctx.roster
        if ctx.role == "keeper" or is_canonical_shopkeeper(roster, ctx.self_name):
            self._last = ShopResult(
                status=ShopStatus.RUNNING,
                reason="shop module armed",
                phase=DUTY_FOLLOW,
            )
            return self._last
        self._last = ShopResult(status=ShopStatus.IDLE, reason="not shopkeeper")
        return self._last

    def tick(self, ctx: ShopContext) -> ShopResult:
        """One decide tick for keeper, recipient, or leader receive."""
        role = str(ctx.role or "member").strip().lower()
        runtime = ctx.runtime
        board = ctx.blackboard
        if role == "leader":
            return self._tick_leader(ctx)
        if role == "recipient":
            return self._tick_recipient(ctx)
        # Default: keeper / shopkeeper duty path.
        if ctx.manager is not None and ctx.state is not None:
            intent = _duty.tick_shopkeeper_duty(
                ctx.manager, ctx.state, self_name=str(ctx.self_name or "")
            )
            phase = _phase_of(runtime)
            status = _status_for_intent(intent, runtime, board)
            self._last = ShopResult(
                status=status,
                intent=intent,
                reason=str(getattr(intent, "reason", "") or "") if intent else "idle",
                phase=phase,
            )
            return self._last
        self._last = ShopResult(status=ShopStatus.IDLE, reason="missing manager/state")
        return self._last

    def _tick_recipient(self, ctx: ShopContext) -> ShopResult:
        board = ctx.blackboard
        state = ctx.state
        hold = ctx.hold
        intent = None
        if ctx.manager is not None and state is not None:
            intent = _duty.tick_supply_pickup(
                ctx.manager,
                state,
                self_name=ctx.self_name,
                self_guid=ctx.self_guid,
            )
        if intent is None and hold is not None and state is not None and board is not None:
            tracked = bool((ctx.extra or {}).get("tracked", True))
            intent = _duty.recipient_hold_intent(state, board, hold, tracked=tracked)
        phase = _phase_of(ctx.runtime)
        status = _status_for_intent(intent, ctx.runtime, board)
        self._last = ShopResult(
            status=status,
            intent=intent,
            reason=str(getattr(intent, "reason", "") or "") if intent else "idle",
            phase=phase,
        )
        return self._last

    def _tick_leader(self, ctx: ShopContext) -> ShopResult:
        board = ctx.blackboard
        world = ctx.state
        hold = ctx.hold
        claim = ctx.claim
        intent = None
        if world is not None and board is not None:
            intent = _duty.leader_supply_action(world, board, hold, claim)
        phase = _phase_of(ctx.runtime)
        status = _status_for_intent(intent, ctx.runtime, board)
        publish = None
        if hold is not None and board is not None and world is not None:
            stand = _duty.leader_supply_stand(
                board, getattr(world, "last_party", None), hold
            )
            if stand is not None:
                publish = {"supply_stand": stand}
                if intent is None:
                    status = ShopStatus.WAITING
        self._last = ShopResult(
            status=status,
            intent=intent,
            reason=str(getattr(intent, "reason", "") or "") if intent else "idle",
            phase=phase,
            publish=publish,
        )
        return self._last

    def pause(self) -> ShopResult:
        self._last = ShopResult(
            status=ShopStatus.WAITING,
            reason="paused",
            phase=self._last.phase if self._last else DUTY_FOLLOW,
        )
        return self._last

    def resume(self, ctx: Optional[ShopContext] = None) -> ShopResult:
        """Resume after pause; abort invalid leftover per Phase 2 when ctx given."""
        if ctx is not None and ctx.blackboard is not None:
            # Invalid leftover shop pin without open supply is cleared by host
            # via cancel; resume itself does not wipe a live notice.
            pass
        self._last = ShopResult(
            status=ShopStatus.RUNNING,
            reason="resumed",
            phase=self._last.phase if self._last else DUTY_FOLLOW,
        )
        return self._last

    def cancel(self, reason: str = "cancelled", ctx: Optional[ShopContext] = None) -> ShopResult:
        if ctx is not None:
            abort_party_supply(
                ctx.runtime,
                ctx.blackboard,
                ctx.manager,
                reason=reason,
                clear_notice=True,
            )
        else:
            abort_party_supply(reason=reason)
        self._last = ShopResult(
            status=ShopStatus.CANCELLED,
            reason=str(reason or "cancelled"),
            phase=DUTY_FOLLOW,
        )
        return self._last

    def status(self) -> ShopResult:
        return self._last

    def on_shop_finished(self, board: Any) -> bool:
        """DecisionManager shop-success hook.

        Returns whether this success was a party supply buy. Always releases
        leftover shop travel so join is not blocked.
        """
        armed = _duty.note_supply_shop_finished(board)
        _duty.release_finished_party_shop(board)
        return armed

    def live_supply(self, roster: Any, states: Any = None) -> dict[str, Any]:
        """Leader publish view of the canonical shopkeeper."""
        return shopkeeper_live_supply(roster, states)

    def abort_session(
        self,
        runtime: Any = None,
        board: Any = None,
        *,
        reason: str = "supply abort",
        clear_notice: bool = True,
    ) -> bool:
        return abort_supply_session(
            runtime, board, reason=reason, clear_notice=clear_notice
        )

    def abort_shop(
        self,
        board: Any = None,
        manager: Any = None,
        *,
        reason: str = "party shop abort",
        clear_join_nav: Optional[bool] = None,
    ) -> bool:
        return abort_party_shop(
            board, manager, reason=reason, clear_join_nav=clear_join_nav
        )

    def abort_all(
        self,
        runtime: Any = None,
        board: Any = None,
        manager: Any = None,
        *,
        reason: str = "party supply abort",
        clear_notice: bool = True,
    ) -> bool:
        return abort_party_supply(
            runtime,
            board,
            manager,
            reason=reason,
            clear_notice=clear_notice,
        )

    def has_local_state(self, runtime: Any, board: Any) -> bool:
        return has_shopkeeper_local_state(runtime, board)


# Process-wide default used by host call sites.
_MODULE = PartyShopModule()


def get_party_shop() -> PartyShopModule:
    return _MODULE


__all__ = ["PartyShopModule", "get_party_shop"]
