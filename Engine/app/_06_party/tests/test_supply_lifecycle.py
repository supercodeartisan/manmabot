"""Phase 2 supply lifecycle: abort, freshness, single shopkeeper, notice keep."""
from __future__ import annotations

import time
from types import SimpleNamespace

from app._06_party.party_shop.duty import tick_shopkeeper_duty
from app._06_party.party_shop.supply import (
    REPORT_FRESH_S,
    choose_supply_duty,
    fresh_supply_rows,
    supply_report_is_fresh,
)
from app._06_party.comms.orders import member_orders
from app._06_party.config import PartyMemberConfig
from app._06_party.manager import PartyMemberManager
from app._06_party.party_shop.session import (
    abort_party_shop,
    abort_party_supply,
    abort_supply_session,
    canonical_shopkeeper_name,
    is_canonical_shopkeeper,
    shopkeeper_live_supply,
)
from app._06_party.sync import MemberStates
from settings.profile import normalize_party_roster


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.world_origin = SimpleNamespace(x=10, y=10)
        self.nav_goal = None
        self.travel_purpose = ""
        self.intent = None


class _Runtime:
    def __init__(self) -> None:
        self.duty_phase = "follow"
        self.supply_hold = {"id": "hold:hp:Elf", "for": "Elf"}
        self.supply_stand = {"id": "hold:hp:Elf", "x": 1, "y": 2}
        self.supply_notice = {"id": "n1", "for": "Elf", "item": "hp"}
        self.supply_expected: dict = {}
        self.last_kind = ""
        self.last_reason = ""


class _Join:
    def __init__(self, active: bool = True) -> None:
        self._active = active
        self.session = object() if active else None

    @property
    def active(self) -> bool:
        return self._active

    def clear(self) -> None:
        self._active = False
        self.session = None


class _Manager:
    def __init__(self) -> None:
        self.runtime = _Runtime()
        self._nav_blackboard = _Board()
        self._join_nav = _Join(False)
        self.config = PartyMemberConfig(seat_role="shopkeeper")
        self.leader_policy = {
            "roster": [{"name": "Keeper", "role": "shopkeeper", "enabled": "1"}]
        }


def _specs() -> list[dict]:
    return [
        {
            "item": "hp",
            "member_min": 10,
            "keeper_min": 20,
            "give": 10,
            "buy": 20,
            "can_buy": True,
        }
    ]


def test_abort_supply_session_is_idempotent() -> None:
    runtime = _Runtime()
    board = _Board()
    board.scratch["party_supply_attempt"] = {"n": 1}
    board.scratch["party_approach_goal"] = ("Elf", "memory", 4, 1, 2)
    assert abort_supply_session(runtime, board, reason="test") is True
    assert runtime.supply_hold is None
    assert runtime.supply_notice is None
    assert runtime.supply_stand is None
    assert "party_supply_attempt" not in board.scratch
    assert abort_supply_session(runtime, board, reason="test") is False


def test_abort_party_shop_clears_join_and_flags() -> None:
    manager = _Manager()
    board = manager._nav_blackboard
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch["party_join_leader"] = True
    board.scratch["party_supply_chain"] = ["hp"]
    board.scratch["party_supply_item"] = "hp"
    manager._join_nav = _Join(True)
    assert abort_party_shop(board, manager, reason="test") is True
    assert board.scratch.get("party_join_leader") is None
    assert board.scratch.get("party_shopkeeper_arrow") is None
    assert manager._join_nav.active is False
    assert abort_party_shop(board, manager, reason="test") is False


def test_supply_closed_aborts_buy_and_join() -> None:
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = False
    manager = _Manager()
    board = manager._nav_blackboard
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch["party_supply_item"] = "hp"
    board.scratch["shop_trip"] = True
    board.scratch["party_join_leader"] = True
    manager._join_nav = _Join(True)
    manager.runtime.supply_notice = {"id": "n1", "for": "Elf"}
    try:
        action = tick_shopkeeper_duty(manager, object(), self_name="Keeper")
    finally:
        member_orders.supply_open = saved_open
    assert action is None
    assert manager.runtime.supply_notice is None
    assert board.scratch.get("party_join_leader") is None
    assert board.scratch.get("party_shopkeeper_arrow") is None
    assert manager._join_nav.active is False


def test_new_buy_keeps_existing_supply_notice(monkeypatch) -> None:
    saved_open = bool(member_orders.supply_open)
    saved_reports = list(member_orders.party_reports)
    member_orders.supply_open = True
    member_orders.party_reports = []
    manager = _Manager()
    manager.runtime.supply_notice = {
        "id": "n1",
        "for": "Elf",
        "item": "hp",
        "min": 10,
        "at": time.time(),
    }
    board = manager._nav_blackboard
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch["party_supply_item"] = "hp"
    board.scratch["shop_trip"] = True
    board.scratch["party_supply_configured"] = 20
    board.scratch["party_supply_keep"] = 20

    monkeypatch.setattr(
        "app._04_decision.shop_trip.tick_shop_trip",
        lambda _state, _board: None,
    )
    try:
        tick_shopkeeper_duty(manager, object(), self_name="Keeper")
    finally:
        member_orders.supply_open = saved_open
        member_orders.party_reports = saved_reports
    assert manager.runtime.supply_notice is not None
    assert manager.runtime.supply_notice["id"] == "n1"


def test_report_freshness_window() -> None:
    now = time.time()
    fresh = {"from": "Elf", "noted_at": now - 10.0, "items": {"hp_potion": 0}}
    stale = {"from": "Elf", "noted_at": now - (REPORT_FRESH_S + 5.0), "items": {"hp_potion": 0}}
    assert supply_report_is_fresh(fresh, now=now) is True
    assert supply_report_is_fresh(stale, now=now) is False
    assert fresh_supply_rows([fresh, stale], now=now) == [fresh]


def test_stale_report_not_chosen_for_duty() -> None:
    now = time.time()
    rows = fresh_supply_rows(
        [
            {
                "from": "Elf",
                "noted_at": now - (REPORT_FRESH_S + 1.0),
                "items": {"hp_potion": 0},
                "map_id": 4,
                "x": 1,
                "y": 1,
            }
        ],
        now=now,
    )
    duty = choose_supply_duty(
        {"hp": 50, "arrow": 500},
        rows,
        _specs(),
        self_name="Keeper",
    )
    assert duty is None


def test_normalize_keeps_one_shopkeeper() -> None:
    rows = normalize_party_roster(
        [
            {"name": "A", "role": "shopkeeper"},
            {"name": "B", "role": "shopkeeper"},
            {"name": "C", "role": "mage"},
        ]
    )
    assert [r["role"] for r in rows] == ["shopkeeper", "member", "mage"]
    assert canonical_shopkeeper_name(rows) == "A"
    assert is_canonical_shopkeeper(rows, "A") is True
    assert is_canonical_shopkeeper(rows, "B") is False


def test_shopkeeper_live_supply_rejects_stale() -> None:
    states = MemberStates()
    states.rows["keeper"] = {
        "name": "Keeper",
        "live": {
            "supply_hold": {"id": "hold:hp:Elf", "for": "Elf"},
            "supply": {"id": "n1", "for": "Elf"},
        },
        "fresh_at": time.monotonic() - 30.0,
    }
    roster = [{"name": "Keeper", "role": "shopkeeper", "enabled": "1"}]
    view = shopkeeper_live_supply(roster, states=states)
    assert view["valid"] is False
    assert view["hold"] is None
    assert view["notice"] is None


def test_shopkeeper_live_supply_rejects_awaiting_fresh() -> None:
    states = MemberStates()
    states.rows["keeper"] = {
        "name": "Keeper",
        "live": {"supply_hold": {"id": "hold:hp:Elf", "for": "Elf"}},
        "fresh_at": time.monotonic(),
    }
    states.hold_until_fresh("Keeper")
    roster = [{"name": "Keeper", "role": "shopkeeper", "enabled": "1"}]
    view = shopkeeper_live_supply(roster, states=states)
    assert view["valid"] is False
    assert view["hold"] is None


def test_shopkeeper_live_supply_accepts_fresh_hold() -> None:
    states = MemberStates()
    states.rows["keeper"] = {
        "name": "Keeper",
        "live": {
            "supply_hold": {"id": "hold:hp:Elf", "for": "Elf"},
            "supply": {"id": "n1", "for": "Elf", "item": "hp"},
        },
        "fresh_at": time.monotonic(),
    }
    roster = [{"name": "Keeper", "role": "shopkeeper", "enabled": "1"}]
    view = shopkeeper_live_supply(roster, states=states)
    assert view["valid"] is True
    assert view["hold"]["id"] == "hold:hp:Elf"
    assert view["notice"]["id"] == "n1"


def test_session_reset_clears_shop_and_notice() -> None:
    manager = PartyMemberManager(PartyMemberConfig(seat_role="shopkeeper"))
    board = _Board()
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch["party_supply_chain"] = ["hp"]
    board.scratch["party_join_leader"] = True
    manager.set_nav_blackboard(board)
    manager.runtime.supply_notice = {"id": "n1", "for": "Elf"}
    manager.runtime.supply_hold = {"id": "hold:hp:Elf", "for": "Elf"}
    manager._join_nav = _Join(True)
    manager.reset_for_new_leader_session()
    assert manager.runtime.supply_notice is None
    assert manager.runtime.supply_hold is None
    assert board.scratch.get("party_shopkeeper_arrow") is None
    assert board.scratch.get("party_join_leader") is None
    assert manager._join_nav.active is False


def test_abort_party_supply_clears_delivery_and_shop() -> None:
    manager = _Manager()
    manager._join_nav = _Join(True)
    board = manager._nav_blackboard
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch["party_approach_goal"] = ("Elf", "memory", 4, 1, 1)
    abort_party_supply(manager.runtime, board, manager, reason="hunt end")
    assert manager.runtime.supply_hold is None
    assert manager.runtime.supply_notice is None
    assert board.scratch.get("party_shopkeeper_arrow") is None
    assert manager._join_nav.active is False


def test_idle_no_duty_does_not_cancel_map_join() -> None:
    manager = _Manager()
    manager._join_nav = _Join(True)
    board = manager._nav_blackboard
    abort_party_shop(board, manager, reason="no supply duty")
    assert manager._join_nav.active is True
