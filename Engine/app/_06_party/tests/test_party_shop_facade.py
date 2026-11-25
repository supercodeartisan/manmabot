"""Facade contract: start/tick/cancel/pause/resume status transitions."""
from __future__ import annotations

from types import SimpleNamespace

from app._06_party.party_shop import PartyShopModule, ShopContext, ShopStatus
from app._06_party.party_shop.scratch_keys import FLAG, JOIN, PIN


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.travel_purpose = None
        self.nav_goal = None


class _Runtime:
    def __init__(self) -> None:
        self.supply_hold = {"id": "h1"}
        self.supply_stand = {"id": "h1"}
        self.supply_notice = {"id": "n1"}
        self.duty_phase = "supply"


def test_cancel_clears_local_state() -> None:
    mod = PartyShopModule()
    board = _Board()
    board.scratch[FLAG] = True
    board.scratch[PIN] = "buy_arrows"
    board.scratch[JOIN] = True
    runtime = _Runtime()
    ctx = ShopContext(blackboard=board, runtime=runtime, role="keeper")
    result = mod.cancel("hunt close", ctx)
    assert result.status is ShopStatus.CANCELLED
    assert board.scratch.get(FLAG) is None
    assert board.scratch.get(JOIN) is None
    assert runtime.supply_hold is None
    assert runtime.supply_notice is None
    assert runtime.duty_phase == "follow"


def test_pause_resume_status() -> None:
    mod = PartyShopModule()
    paused = mod.pause()
    assert paused.status is ShopStatus.WAITING
    resumed = mod.resume()
    assert resumed.status is ShopStatus.RUNNING


def test_live_supply_empty_without_keeper() -> None:
    mod = PartyShopModule()
    view = mod.live_supply([])
    assert view["valid"] is False
    assert view["hold"] is None
    assert view["notice"] is None


def test_on_shop_finished_arms_chain() -> None:
    mod = PartyShopModule()
    board = _Board()
    board.scratch["party_supply_item"] = "arrow"
    board.scratch[FLAG] = True
    assert mod.on_shop_finished(board) is True
    assert "arrow" in (board.scratch.get("party_supply_chain") or [])


def test_status_defaults_idle() -> None:
    mod = PartyShopModule()
    assert mod.status().status is ShopStatus.IDLE
