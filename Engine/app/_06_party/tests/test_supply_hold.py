"""Recipient stands still, the drop lands on an empty neighbor, pickup interrupts."""
from __future__ import annotations

from app._06_party.arrow_duty import (
    choose_drop_stand,
    plan_supply_drop,
    supply_hold_for,
    tick_shopkeeper_duty,
)
from app._06_party.comms.orders import member_orders
from app._06_party.config import PartyMemberConfig
from app._06_party.frame_check import reject_leader_frame
from websocket.party_orders import MemberOrders


def _duty() -> dict:
    return {
        "kind": "drop",
        "item": "arrow",
        "name": "Elf",
        "qty": 100,
        "min": 300,
        "map_id": 4,
        "x": 1,
        "y": 2,
    }


def test_drop_tile_is_beside_the_stand_and_not_under_the_body() -> None:
    spot = choose_drop_stand(10, 20)
    assert spot is not None
    assert (spot["drop_x"], spot["drop_y"]) != (10, 20)
    assert (spot["stand_x"], spot["stand_y"]) != (10, 20)
    assert max(abs(spot["drop_x"] - 10), abs(spot["drop_y"] - 20)) == 1
    # Drag offset is (-1, -1), so the shopkeeper stands one step the other way.
    assert spot["stand_x"] - spot["drop_x"] == 1
    assert spot["stand_y"] - spot["drop_y"] == 1


def test_blocked_neighbor_is_skipped() -> None:
    first = choose_drop_stand(10, 20)

    def _open(tile: tuple[int, int]) -> bool:
        return (tile[0], tile[1]) != (first["drop_x"], first["drop_y"])

    spot = choose_drop_stand(10, 20, _open)
    assert spot is not None
    assert (spot["drop_x"], spot["drop_y"]) != (first["drop_x"], first["drop_y"])
    assert (spot["stand_x"], spot["stand_y"]) != (10, 20)


def test_plan_waits_until_the_stop_tile_is_confirmed() -> None:
    assert plan_supply_drop(_duty(), None) is None
    planned = plan_supply_drop(
        _duty(),
        {"id": "hold:arrow:Elf", "for": "Elf", "map_id": 4, "x": 10, "y": 20},
    )
    assert planned is not None
    assert planned["exact"] is True
    assert (planned["x"], planned["y"]) != (10, 20)
    assert (planned["x"], planned["y"]) != (1, 2)


class _Frame:
    def __init__(self, message: dict) -> None:
        self.message = message


def test_leader_frames_carry_the_hold_and_the_stand() -> None:
    assert reject_leader_frame(
        {"from": "leader", "type": "supply_hold", "for": "Elf", "id": "hold:arrow:Elf"}
    ) == ""
    assert reject_leader_frame(
        {
            "from": "leader",
            "type": "supply_stand",
            "id": "hold:arrow:Elf",
            "x": 10,
            "y": 20,
            "map_id": 4,
        }
    ) == ""
    assert reject_leader_frame({"from": "leader", "type": "supply_drop", "clear": True}) == ""
    orders = MemberOrders()
    orders.ingest(
        [
            _Frame(
                {
                    "from": "leader",
                    "type": "supply_hold",
                    "id": "hold:arrow:Elf",
                    "for": "Elf",
                    "item": "arrow",
                }
            )
        ]
    )
    assert orders.supply_hold is not None
    assert orders.supply_hold["for"] == "Elf"
    orders.ingest([_Frame({"from": "leader", "type": "supply_hold", "clear": True})])
    assert orders.supply_hold is None


class _Inv:
    bag_ready = True
    arrows = 500
    silver_arrows = 0
    hp_potion = 50
    depoison = 5
    mp_potion = 20


class _State:
    player = type("P", (), {"inventory": _Inv()})()


class _Runtime:
    def __init__(self) -> None:
        self.duty_phase = "follow"
        self.supply_notice = None
        self.supply_hold = None
        self.last_kind = ""
        self.last_reason = ""


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}


class _Manager:
    def __init__(self) -> None:
        self.runtime = _Runtime()
        self._nav_blackboard = _Board()
        self.config = PartyMemberConfig(seat_role="shopkeeper")
        self.leader_policy = None


def test_shopkeeper_holds_until_the_recipient_reports_the_stop_tile() -> None:
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    member_orders.supply_stand = None
    try:
        action = tick_shopkeeper_duty(_Manager(), _State(), self_name="Keeper")
    finally:
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
    assert action is not None
    assert "supply hold" in str(getattr(action, "reason", ""))


def test_close_claim_without_a_pile_does_not_hand_the_tick_back() -> None:
    from app._06_party import arrow_duty

    class _Origin:
        x = 10
        y = 10

    class _Pose:
        map_id = 4
        x = 10
        y = 10

    class _Blackboard:
        def __init__(self) -> None:
            self.world_origin = _Origin()
            self.nav_goal = None
            self.intent = None
            self.scratch: dict = {}
            self.current_target_id = 7

    import app._04_decision.world_nav.session as session
    import app._04_decision.combat_query as combat_query

    real_pose = session.live_pose_from_state
    real_loot = combat_query.list_lootable
    session.live_pose_from_state = lambda _state, fresh=False: _Pose()
    combat_query.list_lootable = lambda *_args, **_kwargs: []
    try:
        action = arrow_duty._pickup_claim(
            object(),
            _Blackboard(),
            {"for": "Elf", "item": "arrow", "map_id": 4, "x": 10, "y": 10, "qty": 100},
            None,
        )
    finally:
        session.live_pose_from_state = real_pose
        combat_query.list_lootable = real_loot
    assert action is not None
    assert "supply pickup" in str(getattr(action, "reason", ""))
    assert supply_hold_for(_duty())["id"] == "hold:arrow:Elf"
