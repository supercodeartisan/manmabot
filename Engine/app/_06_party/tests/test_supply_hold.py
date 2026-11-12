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
        {
            "id": "hold:arrow:Elf",
            "for": "Elf",
            "map_id": 4,
            "x": 10,
            "y": 20,
            "confirmed": True,
        },
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
    orders.ingest(
        [
            _Frame(
                {
                    "from": "leader",
                    "type": "party_reports",
                    "hunt_open": True,
                    "reports": [{"from": "Elf"}],
                }
            )
        ]
    )
    assert orders.supply_open is True
    assert orders.party_reports[0]["from"] == "Elf"
    orders.ingest(
        [_Frame({"from": "leader", "type": "party_reports", "hunt_open": False, "reports": []})]
    )
    assert orders.supply_open is False


class _Inv:
    bag_ready = True
    arrows = 0
    silver_arrows = 500
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
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    member_orders.supply_stand = None
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 100, "y": 100})()
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    session.live_pose_from_state = lambda _state, fresh=False: type(
        "P", (), {"map_id": 4, "x": 100, "y": 100}
    )()
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert action is not None
    assert "supply hold" in str(getattr(action, "reason", ""))
    assert manager.runtime.supply_hold is not None


def test_a_far_recipient_keeps_moving_until_the_shopkeeper_is_close() -> None:
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.supply_stand = None
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 10, "y": 10})()
    manager._nav_blackboard.nav_goal = None
    manager._nav_blackboard.intent = None
    import app._04_decision.world_nav.session as session
    import app._04_decision.behaviors.travel as travel

    real_pose = session.live_pose_from_state
    real_start = travel.start_travel
    real_emit = travel.emit_travel_hop
    session.live_pose_from_state = lambda _state, fresh=False: type(
        "P", (), {"map_id": 4, "x": 10, "y": 10}
    )()
    travel.start_travel = lambda board, goal, reason="": setattr(
        board, "nav_goal", (int(goal[0]), int(goal[1]))
    )
    travel.emit_travel_hop = lambda *args, **kwargs: False
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        travel.start_travel = real_start
        travel.emit_travel_hop = real_emit
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert manager.runtime.supply_hold is None
    assert manager._nav_blackboard.nav_goal == (100, 100)
    assert action is None


def test_a_new_leader_session_closes_supply() -> None:
    orders = MemberOrders()
    orders.session = "old"
    orders.supply_open = True
    orders.ingest([_Frame({"from": "leader", "type": "beep", "session": "new"})])
    assert orders.supply_open is False


def test_an_open_join_keeps_the_shopkeeper_off_the_tick() -> None:
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:arrow:Elf", "for": "Elf"}
    manager._join_nav = type("Nav", (), {"active": True})()
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        member_orders.supply_open = saved_open
    assert action is None
    assert manager.runtime.supply_hold is None


def test_approach_uses_the_live_party_tile() -> None:
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.supply_stand = None
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    state = _State()
    state.last_party = {
        "in_party": True,
        "members": [{"name": "Elf", "map_id": 4, "x": 40, "y": 40}],
    }
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 10, "y": 10})()
    manager._nav_blackboard.nav_goal = None
    manager._nav_blackboard.intent = None
    import app._04_decision.world_nav.session as session
    import app._04_decision.behaviors.travel as travel

    real_pose = session.live_pose_from_state
    real_start = travel.start_travel
    real_emit = travel.emit_travel_hop
    session.live_pose_from_state = lambda _state, fresh=False: type(
        "P", (), {"map_id": 4, "x": 10, "y": 10}
    )()
    travel.start_travel = lambda board, goal, reason="": setattr(
        board, "nav_goal", (int(goal[0]), int(goal[1]))
    )
    travel.emit_travel_hop = lambda *args, **kwargs: False
    try:
        action = tick_shopkeeper_duty(manager, state, self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        travel.start_travel = real_start
        travel.emit_travel_hop = real_emit
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert action is None
    assert manager._nav_blackboard.nav_goal == (40, 40)


def test_approach_follows_a_tile_that_moves(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="manmabot.party")
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.supply_stand = None
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    state = _State()
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 10, "y": 10})()
    manager._nav_blackboard.nav_goal = None
    manager._nav_blackboard.intent = None
    import app._04_decision.behaviors.travel as travel
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    real_start = travel.start_travel
    real_emit = travel.emit_travel_hop
    session.live_pose_from_state = lambda _state, fresh=False: type(
        "P", (), {"map_id": 4, "x": 10, "y": 10}
    )()
    travel.start_travel = lambda board, goal, reason="": setattr(
        board, "nav_goal", (int(goal[0]), int(goal[1]))
    )
    travel.emit_travel_hop = lambda *args, **kwargs: False
    try:
        tick_shopkeeper_duty(manager, state, self_name="Keeper")
        assert manager._nav_blackboard.nav_goal == (100, 100)
        state.last_party = {
            "in_party": True,
            "members": [{"name": "Elf", "map_id": 4, "x": 70, "y": 70}],
        }
        tick_shopkeeper_duty(manager, state, self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        travel.start_travel = real_start
        travel.emit_travel_hop = real_emit
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert manager._nav_blackboard.nav_goal == (70, 70)
    assert "approach retarget" in caplog.text


def test_stand_uses_party_memory_and_the_hunt_map_follows() -> None:
    from app._06_party.arrow_policy import hunt_map_after_pose
    from app._06_party.leader import stand_from_party_memory

    snap = {
        "in_party": True,
        "members": [{"name": "Elf", "map_id": 4, "x": 12, "y": 13}],
    }
    stand = stand_from_party_memory(snap, "Elf", "hold:arrow:Elf")
    assert stand == {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "map_id": 4,
        "x": 12,
        "y": 13,
    }
    assert hunt_map_after_pose(4, 15, leaving=False) == 15
    assert hunt_map_after_pose(4, 15, leaving=True) == 4


def test_supply_stays_closed_until_the_hunt_starts() -> None:
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = False
    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:hp:Elf", "for": "Elf"}
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        member_orders.supply_open = saved_open
    assert action is None
    assert manager.runtime.supply_hold is None


def test_an_away_member_is_not_a_drop_target() -> None:
    from app._06_party.arrow_duty import supply_rows

    rows = supply_rows(
        [
            {"from": "Elf", "supply_ok": False, "map_id": 4},
            {"from": "Mage", "supply_ok": True, "map_id": 4},
            {"from": "Boss"},
        ]
    )
    assert [row["from"] for row in rows] == ["Mage", "Boss"]


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


def _pose(map_id: int, x: int, y: int):
    return type("P", (), {"map_id": map_id, "x": x, "y": y})()


def _close_supply(reports: list, stand: Any) -> tuple:
    """Open supply for one close recipient. Caller restores the orders."""
    member_orders.supply_open = True
    member_orders.party_reports = reports
    member_orders.supply_stand = stand
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 100, "y": 100})()
    manager._nav_blackboard.nav_goal = None
    manager._nav_blackboard.intent = None
    return manager


def test_survival_interrupts_supply_and_the_shop_resumes(monkeypatch, caplog) -> None:
    from app._02_state.enums import ActionType
    from app._04_decision.shop_trip import SCRATCH_SHOP_TRIP
    from app._06_party.manager import PartyMemberManager

    potion = type(
        "I", (), {"action": ActionType.USE_HP_POTION, "reason": "hp", "target_id": None}
    )()
    shop_calls = {"n": 0}

    def _shop(*_args, **_kwargs):
        shop_calls["n"] += 1
        return type("W", (), {"action": ActionType.IDLE, "reason": "shop", "target_id": None})()

    monkeypatch.setattr(
        "app._06_party.support.party_critical_escape", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: potion
    )
    monkeypatch.setattr("app._06_party.arrow_duty.tick_shopkeeper_duty", _shop)
    manager = PartyMemberManager(PartyMemberConfig(seat_role="shopkeeper"))
    board = _Board()
    board.scratch[SCRATCH_SHOP_TRIP] = True
    board.scratch["party_shopkeeper_arrow"] = True
    board.side_intents = []
    manager._nav_blackboard = board
    manager.world_origin = type("O", (), {"x": 10, "y": 10})()
    state = type(
        "S",
        (),
        {"player": type("P", (), {"alive": True, "hp": 40})(), "last_party": None},
    )()
    import logging

    caplog.set_level(logging.INFO, logger="manmabot.party")
    first = manager.decide(state)
    assert first is potion
    assert "care before supply" in caplog.text
    assert shop_calls["n"] == 0
    assert board.scratch[SCRATCH_SHOP_TRIP] is True
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: None
    )
    second = manager.decide(state)
    assert shop_calls["n"] == 1
    assert board.scratch[SCRATCH_SHOP_TRIP] is True
    assert second is not potion


def test_a_move_during_care_rechecks_the_shop_and_the_drop(caplog) -> None:
    from app._04_decision.shop_trip import SCRATCH_SHOP_HALTED, SCRATCH_SHOP_TRIP
    from app._06_party.arrow_duty import release_care_pose

    import logging

    caplog.set_level(logging.INFO, logger="manmabot.party")
    board = _Board()
    board.scratch[SCRATCH_SHOP_TRIP] = True
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch[SCRATCH_SHOP_HALTED] = True
    board.scratch["party_supply_item"] = "arrow"
    board.scratch["party_supply_drop"] = {"x": 1, "y": 2}
    board.scratch["party_care_pose"] = (4, 10, 10)
    board.travel_purpose = "shop"
    board.nav_goal = (3, 3)
    board.nav_path = []
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    session.live_pose_from_state = lambda _state, fresh=False: _pose(4, 30, 30)
    try:
        release_care_pose(board, _State())
    finally:
        session.live_pose_from_state = real_pose
    assert board.scratch[SCRATCH_SHOP_TRIP] is True
    assert board.scratch["party_shopkeeper_arrow"] is True
    assert board.scratch["party_supply_item"] == "arrow"
    assert SCRATCH_SHOP_HALTED not in board.scratch
    assert "party_supply_drop" not in board.scratch
    assert board.nav_goal is None
    assert "shop approach reset" in caplog.text


def test_an_in_place_care_keeps_the_shop_approach(caplog) -> None:
    from app._04_decision.shop_trip import SCRATCH_SHOP_HALTED, SCRATCH_SHOP_TRIP
    from app._06_party.arrow_duty import release_care_pose

    import logging

    caplog.set_level(logging.INFO, logger="manmabot.party")
    board = _Board()
    board.scratch[SCRATCH_SHOP_TRIP] = True
    board.scratch[SCRATCH_SHOP_HALTED] = True
    board.scratch["party_care_pose"] = (4, 10, 10)
    board.nav_goal = (8, 8)
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    session.live_pose_from_state = lambda _state, fresh=False: _pose(4, 10, 10)
    try:
        release_care_pose(board, _State())
    finally:
        session.live_pose_from_state = real_pose
    assert board.scratch[SCRATCH_SHOP_TRIP] is True
    assert board.scratch[SCRATCH_SHOP_HALTED] is True
    assert board.nav_goal == (8, 8)
    assert "shop trip kept" in caplog.text


def test_hp_potion_returns_before_self_heal_and_keeps_the_trip(monkeypatch) -> None:
    from app._02_state.enums import ActionType
    from app._04_decision.shop_trip import SCRATCH_SHOP_TRIP
    from app._06_party.support import urgent_self_survival

    board = _Board()
    board.side_intents = []
    board.intent = None
    board.scratch[SCRATCH_SHOP_TRIP] = True
    potion = type("I", (), {"action": ActionType.USE_HP_POTION, "reason": "hp"})()

    def _heal(*_args, **_kwargs):
        raise AssertionError("self heal ran before the potion")

    monkeypatch.setattr("app._04_decision.potion_sides._side_hp_potion", lambda *_a, **_k: potion)
    monkeypatch.setattr("app._06_party.support._try_party_heal", _heal)
    got = urgent_self_survival(object(), board)
    assert got is potion
    assert board.scratch[SCRATCH_SHOP_TRIP] is True


def test_a_cleared_hold_is_published_to_the_party(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(
        "app._06_party.comms.publish.publish_body",
        lambda body: sent.append(dict(body)) or 1,
    )
    from session.bot_controller import BotController

    class _Leader:
        _party_hold_id = "hold:arrow:Elf"
        _party_stand_key = ("hold:arrow:Elf", 4, 100, 100)

        def _leader_supply_hold(self) -> None:
            return None

    leader = _Leader()
    BotController._publish_supply_hold(leader)
    assert sent[0]["type"] == "supply_hold" and sent[0]["clear"] is True
    assert sent[1]["type"] == "supply_stand" and sent[1]["clear"] is True
    assert leader._party_hold_id == ""


def test_stand_timeout_cancels_and_the_old_tile_does_not_apply(caplog) -> None:
    import logging
    import time

    caplog.set_level(logging.INFO, logger="manmabot.party")
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    manager = _close_supply(reports, None)
    manager._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": time.time() - 30.0,
        "shifts": 0,
    }
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    session.live_pose_from_state = lambda _state, fresh=False: _pose(4, 100, 100)
    try:
        timed_out = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
        assert timed_out is None
        assert manager.runtime.supply_hold is None
        assert manager.runtime.last_reason == "stand timeout"
        assert manager._nav_blackboard.scratch["party_supply_attempt"]["n"] == 1
        paused = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
        assert paused is None
        assert manager.runtime.duty_phase == "follow"
        manager._nav_blackboard.scratch["party_supply_pause"] = {
            ("elf", "arrow"): time.time() - 1.0
        }
        member_orders.supply_stand = {
            "id": "hold:arrow:Elf",
            "for": "Elf",
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
        again = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert again is not None
    assert "supply hold" in str(getattr(again, "reason", ""))
    assert manager.runtime.supply_hold["id"] == "hold:arrow:Elf:1"
    assert manager.runtime.last_reason == "wait for stand"
    assert "stand timeout" in caplog.text


def test_a_missing_neighbor_steps_aside_then_ends_the_delivery(caplog) -> None:
    import logging

    from app._06_party import arrow_duty

    caplog.set_level(logging.INFO, logger="manmabot.party")
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    stand = {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "map_id": 4,
        "x": 100,
        "y": 100,
        "confirmed": True,
    }
    blocked = {
        (100 + ox, 100 + oy) for ox, oy in arrow_duty._DROP_NEIGHBORS
    }
    manager = _close_supply(reports, stand)
    import app._04_decision.behaviors.travel as travel
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    real_open = arrow_duty._tile_open
    real_start = travel.start_travel
    real_emit = travel.emit_travel_hop
    session.live_pose_from_state = lambda _state, fresh=False: _pose(4, 100, 100)
    travel.start_travel = lambda board, goal, reason="": setattr(
        board, "nav_goal", (int(goal[0]), int(goal[1]))
    )
    travel.emit_travel_hop = lambda *args, **kwargs: False

    def _open(tile: tuple[int, int]) -> bool:
        return (int(tile[0]), int(tile[1])) not in blocked

    arrow_duty._tile_open = _open
    try:
        first = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
        assert first is None
        assert manager.runtime.supply_hold is not None
        assert manager.runtime.last_reason == "shift for drop"
        assert manager._nav_blackboard.nav_goal not in blocked
        assert manager._nav_blackboard.nav_goal != (100, 100)
        assert manager._nav_blackboard.scratch["party_supply_attempt"]["shifts"] == 1
        arrow_duty._tile_open = lambda _tile: False
        action = first
        for _ in range(arrow_duty.DROP_SHIFT_MAX + 1):
            action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
            if manager.runtime.supply_hold is None:
                break
    finally:
        arrow_duty._tile_open = real_open
        session.live_pose_from_state = real_pose
        travel.start_travel = real_start
        travel.emit_travel_hop = real_emit
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert action is None
    assert manager.runtime.supply_hold is None
    assert manager.runtime.duty_phase == "follow"
    assert manager.runtime.last_reason == "no drop tile"
    assert "supply shift" in caplog.text
    assert "no drop tile" in caplog.text


def test_a_body_on_the_stand_takes_the_next_pair_and_keeps_it() -> None:
    from app._06_party import arrow_duty

    board = _Board()
    real_open = arrow_duty._tile_open
    arrow_duty._tile_open = lambda _tile: True
    try:
        first = choose_drop_stand(100, 100, lambda _tile: True)
        assert first is not None
        taken = {(int(first["stand_x"]), int(first["stand_y"]))}
        kind, spot = arrow_duty._select_drop_spot(board, 4, 100, 100, taken)
        assert kind == "found"
        assert spot is not None
        assert (spot["stand_x"], spot["stand_y"]) != (
            first["stand_x"],
            first["stand_y"],
        )
        assert int(spot["ring"]) == 0
        arrow_duty._remember_spot(board, spot)
        kept, again = arrow_duty._select_drop_spot(board, 4, 100, 100, set())
        assert kept == "keep"
        assert (again["stand_x"], again["stand_y"]) == (
            spot["stand_x"],
            spot["stand_y"],
        )
        landed, nxt = arrow_duty._select_drop_spot(
            board, 4, 100, 100, {(spot["stand_x"], spot["stand_y"])}
        )
        assert landed == "found"
        assert (nxt["stand_x"], nxt["stand_y"]) != (
            spot["stand_x"],
            spot["stand_y"],
        )
        assert (nxt["stand_x"], nxt["stand_y"]) != (
            first["stand_x"],
            first["stand_y"],
        )
        assert int(board.scratch["party_supply_attempt"].get("shifts") or 0) == 0
    finally:
        arrow_duty._tile_open = real_open


def test_bodies_on_every_ring_end_the_drop_without_a_ring_step() -> None:
    from app._06_party import arrow_duty

    board = _Board()
    blocked: set[tuple[int, int]] = set()
    for ring in range(arrow_duty.DROP_SHIFT_MAX + 1):
        for _ox, _oy, stand, drop, _member in arrow_duty._drop_pairs(100, 100, ring):
            blocked.add(stand)
            blocked.add(drop)
    real_open = arrow_duty._tile_open
    arrow_duty._tile_open = lambda _tile: True
    try:
        kind, spot = arrow_duty._select_drop_spot(board, 4, 100, 100, blocked)
    finally:
        arrow_duty._tile_open = real_open
    assert kind == "exhausted"
    assert spot is None
    assert board.scratch == {}


def test_drop_blocks_are_the_body_centers() -> None:
    from app._06_party import arrow_duty

    def _centers(_state, _origin):
        return {(5, 5), (6, 6)}

    import app._04_decision.avoidance as avoidance

    real = avoidance.collect_body_tiles
    avoidance.collect_body_tiles = _centers
    try:
        got = arrow_duty._drop_block_tiles(object(), object())
    finally:
        avoidance.collect_body_tiles = real
    assert got == {(5, 5), (6, 6)}


def test_a_blocked_stand_walks_to_the_next_tile_without_stepping_aside() -> None:
    from app._06_party import arrow_duty

    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    stand = {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "map_id": 4,
        "x": 100,
        "y": 100,
        "confirmed": True,
    }
    manager = _close_supply(reports, stand)
    first = choose_drop_stand(100, 100, lambda _tile: True)
    assert first is not None
    seen: dict = {}

    def _beside(_manager, _state, duty):
        seen["xy"] = (int(duty["x"]), int(duty["y"]))
        return type("W", (), {"reason": "walk to member"})()

    real_open = arrow_duty._tile_open
    real_coord = arrow_duty._coord_on_map
    real_blocks = arrow_duty._drop_block_tiles
    real_beside = arrow_duty._beside_member
    arrow_duty._tile_open = lambda _tile: True
    arrow_duty._coord_on_map = lambda _map, x, y: (int(x), int(y))
    arrow_duty._drop_block_tiles = lambda _state, _origin: {
        (int(first["stand_x"]), int(first["stand_y"]))
    }
    arrow_duty._beside_member = _beside
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        arrow_duty._tile_open = real_open
        arrow_duty._coord_on_map = real_coord
        arrow_duty._drop_block_tiles = real_blocks
        arrow_duty._beside_member = real_beside
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert getattr(action, "reason", "") == "walk to member"
    assert seen["xy"] != (first["stand_x"], first["stand_y"])
    assert manager.runtime.supply_hold is not None
    assert manager.runtime.last_reason != "shift for drop"
    assert manager._nav_blackboard.scratch["party_supply_attempt"]["shifts"] == 0


def test_bodies_on_every_ring_cancel_without_stepping_aside() -> None:
    from app._06_party import arrow_duty
    import app._04_decision.world_nav.session as session

    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    stand = {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "map_id": 4,
        "x": 100,
        "y": 100,
        "confirmed": True,
    }
    manager = _close_supply(reports, stand)
    blocked: set[tuple[int, int]] = set()
    for ring in range(arrow_duty.DROP_SHIFT_MAX + 1):
        for _ox, _oy, tile_stand, drop, _member in arrow_duty._drop_pairs(100, 100, ring):
            blocked.add(tile_stand)
            blocked.add(drop)
    real_open = arrow_duty._tile_open
    real_coord = arrow_duty._coord_on_map
    real_blocks = arrow_duty._drop_block_tiles
    real_pose = session.live_pose_from_state
    arrow_duty._tile_open = lambda _tile: True
    arrow_duty._coord_on_map = lambda _map, x, y: (int(x), int(y))
    arrow_duty._drop_block_tiles = lambda _state, _origin: blocked
    session.live_pose_from_state = lambda _state, fresh=False: _pose(4, 100, 100)
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        arrow_duty._tile_open = real_open
        arrow_duty._coord_on_map = real_coord
        arrow_duty._drop_block_tiles = real_blocks
        session.live_pose_from_state = real_pose
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert action is None
    assert manager.runtime.supply_hold is None
    assert manager.runtime.last_reason == "no drop tile"
    assert manager._nav_blackboard.nav_goal is None


def test_every_neighbor_blocked_is_not_a_drop() -> None:
    assert choose_drop_stand(10, 20, lambda _tile: False) is None
    assert (
        plan_supply_drop(
            _duty(),
            {"id": "hold:arrow:Elf", "for": "Elf", "map_id": 4, "x": 10, "y": 20},
            lambda _tile: False,
        )
        is None
    )


def test_immediate_defense_stays_in_reach(monkeypatch) -> None:
    from app._02_state.enums import ActionType
    from app._04_decision.shop_trip import SCRATCH_SHOP_TRIP
    from app._06_party.support import urgent_self_survival

    board = _Board()
    board.side_intents = []
    board.intent = None
    board.scratch[SCRATCH_SHOP_TRIP] = True
    threat = type("M", (), {"track_id": 3})()
    attack = type("I", (), {"action": ActionType.ATTACK, "reason": "self defense"})()
    monkeypatch.setattr(
        "app._04_decision.potion_sides._side_hp_potion", lambda *_a, **_k: None
    )
    monkeypatch.setattr("app._06_party.support._try_party_heal", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app._06_party.assist.resolve_self_defender", lambda *_a, **_k: threat
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.hold_ground.hold_ground_reach", lambda _state: 1
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.can_engage_target", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "app._06_party.assist.engage_like_solo", lambda *_a, **_k: attack
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.tile_distance_from_player", lambda _obj: 5
    )
    assert urgent_self_survival(object(), board, object()) is None
    monkeypatch.setattr(
        "app._04_decision.combat_query.tile_distance_from_player", lambda _obj: 1
    )
    got = urgent_self_survival(object(), board, object())
    assert got is attack
    assert board.scratch[SCRATCH_SHOP_TRIP] is True


def test_survival_still_runs_when_the_hold_expires(monkeypatch) -> None:
    import time

    from app._02_state.enums import ActionType
    from app._06_party.manager import PartyMemberManager

    potion = type(
        "I", (), {"action": ActionType.USE_HP_POTION, "reason": "hp", "target_id": None}
    )()
    monkeypatch.setattr(
        "app._06_party.support.party_critical_escape", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: potion
    )
    manager = PartyMemberManager(PartyMemberConfig(seat_role="shopkeeper"))
    board = _Board()
    board.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": time.time() - 30.0,
        "shifts": 0,
        "blocks": 0,
    }
    manager._nav_blackboard = board
    manager.world_origin = type("O", (), {"x": 10, "y": 10})()
    manager.runtime.supply_hold = {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "item": "arrow",
    }
    state = type(
        "S",
        (),
        {"player": type("P", (), {"alive": True, "hp": 40})(), "last_party": None},
    )()
    action = manager.decide(state)
    assert action is potion
    assert manager.runtime.supply_hold is None
    assert manager.runtime.last_kind == "support"
    pause = board.scratch["party_supply_pause"]
    assert pause[("elf", "arrow")] > time.time()
    assert board.scratch["party_supply_attempt"]["n"] == 1
    fresh = PartyMemberManager(PartyMemberConfig(seat_role="shopkeeper"))
    fresh_board = _Board()
    fresh_board.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": time.time(),
        "shifts": 0,
    }
    fresh._nav_blackboard = fresh_board
    fresh.world_origin = type("O", (), {"x": 10, "y": 10})()
    fresh.runtime.supply_hold = {"id": "hold:arrow:Elf", "for": "Elf", "item": "arrow"}
    again = fresh.decide(state)
    assert again is potion
    assert fresh.runtime.supply_hold is not None


def test_a_blocked_drop_retries_then_releases_the_hold() -> None:
    from app._06_party.arrow_duty import DROP_SHIFT_MAX, _tick_drop

    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:arrow:Elf", "for": "Elf", "item": "arrow"}
    duty = {
        "item": "arrow",
        "qty": 100,
        "name": "Elf",
        "min": 300,
        "map_id": 4,
        "x": 10,
        "y": 12,
        "attempt": 0,
    }

    def _blocked(state, board, qty, kind="arrow"):
        return {"blocked": True, "reason": "arrow drop blocked"}

    import app._06_party.arrow_duty as arrow_duty
    import app._06_party.supply_drop as supply_drop

    real_beside = arrow_duty._beside_member
    real_step = supply_drop.step_ground_drop
    arrow_duty._beside_member = lambda *_a, **_k: True
    supply_drop.step_ground_drop = _blocked
    try:
        first = _tick_drop(manager, object(), duty)
        assert first is not None
        assert "supply drop" in str(getattr(first, "reason", ""))
        assert manager.runtime.supply_hold.get("dropping") is True
        assert manager.runtime.duty_phase == "supply"
        action = first
        for _ in range(DROP_SHIFT_MAX):
            action = _tick_drop(manager, object(), duty)
            if manager.runtime.supply_hold is None:
                break
    finally:
        arrow_duty._beside_member = real_beside
        supply_drop.step_ground_drop = real_step
    assert action is None
    assert manager.runtime.supply_hold is None
    assert manager.runtime.duty_phase == "follow"
    pause = manager._nav_blackboard.scratch["party_supply_pause"]
    assert ("elf", "arrow") in pause


def test_a_finished_drop_returns_to_follow() -> None:
    from app._06_party.arrow_duty import _tick_drop

    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:arrow:Elf", "for": "Elf", "item": "arrow"}
    duty = {
        "item": "arrow",
        "qty": 100,
        "name": "Elf",
        "min": 300,
        "map_id": 4,
        "x": 10,
        "y": 12,
    }

    def _ok(state, board, qty, kind="arrow"):
        return {"ok": True, "map_id": 4, "x": 11, "y": 13, "qty": qty}

    import app._06_party.arrow_duty as arrow_duty
    import app._06_party.supply_drop as supply_drop

    real_beside = arrow_duty._beside_member
    real_step = supply_drop.step_ground_drop
    arrow_duty._beside_member = lambda *_a, **_k: True
    supply_drop.step_ground_drop = _ok
    try:
        announced = _tick_drop(manager, _State(), duty)
        assert "supply drop" in str(getattr(announced, "reason", ""))
        assert manager.runtime.supply_hold.get("dropping") is True
        action = _tick_drop(manager, _State(), duty)
    finally:
        arrow_duty._beside_member = real_beside
        supply_drop.step_ground_drop = real_step
    assert action is None
    assert manager.runtime.supply_hold is None
    assert manager.runtime.duty_phase == "follow"
    assert manager.runtime.last_reason == "arrow dropped"


def test_the_shop_trip_is_still_the_next_tick(monkeypatch) -> None:
    from app._04_decision.shop_trip import SCRATCH_SHOP_TRIP

    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    seen = {"n": 0}

    def _buy(manager, _state, _duty):
        seen["n"] += 1
        assert manager._nav_blackboard.scratch[SCRATCH_SHOP_TRIP] is True
        return type("I", (), {"reason": "shop"})()

    monkeypatch.setattr("app._06_party.arrow_duty._tick_buy", _buy)
    manager = _Manager()
    manager._nav_blackboard.scratch[SCRATCH_SHOP_TRIP] = True
    manager._nav_blackboard.scratch["party_shopkeeper_arrow"] = True
    manager._nav_blackboard.scratch["party_supply_item"] = "arrow"
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        member_orders.supply_open = saved_open
    assert seen["n"] == 1
    assert action is not None
    assert manager._nav_blackboard.scratch[SCRATCH_SHOP_TRIP] is True
    assert manager._nav_blackboard.scratch["party_supply_item"] == "arrow"


def test_a_finished_shop_does_not_block_the_join(monkeypatch) -> None:
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    joined = {"n": 0}

    def _join(_manager, _state):
        joined["n"] += 1
        return type("I", (), {"reason": "join"})()

    def _buy(*_args, **_kwargs):
        raise AssertionError("a finished shop must not buy again")

    monkeypatch.setattr("app._06_party.arrow_duty._tick_join", _join)
    monkeypatch.setattr("app._06_party.arrow_duty.next_supply_buy", lambda *_a, **_k: None)
    monkeypatch.setattr("app._06_party.arrow_duty._tick_buy", _buy)
    manager = _Manager()
    board = manager._nav_blackboard
    board.player_mode = None
    board.scratch["shop_trip"] = True
    board.scratch["party_shopkeeper_arrow"] = True
    board.scratch["party_supply_chain"] = ["arrow"]
    board.scratch["shop_scrolled"] = True
    board.scratch["need_world_nav"] = "after_shop"
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        member_orders.supply_open = saved_open
    assert joined["n"] == 1
    assert getattr(action, "reason", "") == "join"
    assert "shop_trip" not in board.scratch
    assert "shop_scrolled" not in board.scratch
    assert board.scratch.get("need_world_nav") is None


def test_finished_shopping_joins_a_leader_on_any_map(monkeypatch) -> None:
    from app._06_party.arrow_duty import _tick_join

    seen = {}

    def _nav(_manager, _state, map_id, x, y, *, reason):
        seen["goal"] = (map_id, x, y, reason)
        return type("I", (), {"reason": reason})()

    monkeypatch.setattr("app._06_party.arrow_duty._tick_nav", _nav)
    manager = _Manager()
    manager.config = PartyMemberConfig(
        seat_role="shopkeeper", leader_name="매력여기사"
    )
    manager.runtime.leader_same_map = False
    manager.runtime.sticky_leader_tile = None
    state = _State()
    state.party_read_ok = True
    state.last_party = {
        "in_party": True,
        "leader": {"name": "매력여기사", "map_id": 0, "x": 32607, "y": 33134},
    }
    action = _tick_join(manager, state)
    assert seen["goal"] == (0, 32607, 33134, "party_join_leader")
    assert getattr(action, "reason", "") == "party_join_leader"


def test_a_short_leader_step_keeps_the_join_route(monkeypatch) -> None:
    from app._06_party.arrow_duty import _tick_join

    seen = {}

    def _nav(_manager, _state, map_id, x, y, *, reason):
        seen["goal"] = (map_id, x, y)
        return type("I", (), {"reason": reason})()

    monkeypatch.setattr("app._06_party.arrow_duty._tick_nav", _nav)
    manager = _Manager()
    manager.config = PartyMemberConfig(
        seat_role="shopkeeper", leader_name="매력여기사"
    )
    manager.runtime.leader_same_map = False
    manager._nav_blackboard.scratch["party_nav_goal"] = (
        "party_join_leader",
        4,
        33400,
        32800,
    )
    state = _State()
    state.party_read_ok = True
    state.last_party = {
        "in_party": True,
        "leader": {"name": "매력여기사", "map_id": 4, "x": 33410, "y": 32808},
    }
    _tick_join(manager, state)
    assert seen["goal"] == (4, 33400, 32800)


def test_a_missed_party_read_keeps_the_join_walk(monkeypatch) -> None:
    from app._06_party.arrow_duty import _tick_join

    seen = {}

    def _nav(_manager, _state, map_id, x, y, *, reason):
        seen["goal"] = (map_id, x, y, reason)
        return type("I", (), {"reason": reason})()

    monkeypatch.setattr("app._06_party.arrow_duty._tick_nav", _nav)
    manager = _Manager()
    manager.runtime.leader_same_map = False
    manager._nav_blackboard.scratch["party_nav_goal"] = (
        "party_join_leader",
        0,
        32607,
        33134,
    )
    state = _State()
    state.party_read_ok = False
    state.last_party = {
        "in_party": True,
        "leader": {"name": "매력여기사", "map_id": 4, "x": 1, "y": 1},
    }
    _tick_join(manager, state)
    assert seen["goal"] == (0, 32607, 33134, "party_join_leader")


def test_join_waits_without_a_leader_pose() -> None:
    from app._06_party.arrow_duty import _tick_join

    manager = _Manager()
    manager.runtime.leader_same_map = False
    state = _State()
    state.party_read_ok = False
    action = _tick_join(manager, state)
    assert getattr(action, "reason", "") == "party_member:join leader no pose"
    assert "party_join_leader" not in manager._nav_blackboard.scratch


def test_join_ends_when_already_beside_the_leader(monkeypatch) -> None:
    from app._06_party.arrow_duty import _tick_join

    def _nav(*_args, **_kwargs):
        raise AssertionError("already beside the leader")

    monkeypatch.setattr("app._06_party.arrow_duty._tick_nav", _nav)
    manager = _Manager()
    manager.runtime.leader_same_map = True
    manager.runtime.leader_dist = 2
    manager._nav_blackboard.scratch["party_join_leader"] = True
    manager._nav_blackboard.scratch["party_supply_chain"] = ["hp"]
    state = _State()
    state.party_read_ok = True
    state.last_party = {
        "in_party": True,
        "leader": {"name": "매력여기사", "map_id": 0, "x": 32607, "y": 33134},
    }
    assert _tick_join(manager, state) is None
    assert "party_join_leader" not in manager._nav_blackboard.scratch
    assert "party_supply_chain" not in manager._nav_blackboard.scratch


def test_a_moved_stand_pauses_before_the_next_try() -> None:
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    member_orders.supply_stand = {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "map_id": 4,
        "x": 100,
        "y": 100,
        "confirmed": True,
    }
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 100, "y": 100})()
    manager._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": 0.0,
        "shifts": 0,
        "stand_id": "hold:arrow:Elf",
        "stand_confirmed": True,
        "stand_at": [4, 100, 140],
    }
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    session.live_pose_from_state = lambda _state, fresh=False: type(
        "P", (), {"map_id": 4, "x": 100, "y": 100}
    )()
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert action is None
    assert manager.runtime.supply_hold is None
    assert manager.runtime.last_reason == "stand moved"
    assert ("elf", "arrow") in manager._nav_blackboard.scratch["party_supply_pause"]
    assert manager._nav_blackboard.scratch["party_supply_attempt"]["n"] == 1


def test_the_leader_drinks_before_a_hold_and_a_move_releases_it(monkeypatch) -> None:
    from app._06_party.arrow_duty import leader_supply_action, leader_supply_stand

    potion = type("I", (), {"reason": "hp potion"})()
    pose = {"x": 10, "y": 10}
    body = {"moving": True, "standing": False}
    clock = {"t": 1000.0}
    row = {
        "name": "Boss",
        "guid": "0x10",
        "map_id": 4,
        "x": 10,
        "y": 10,
        "is_leader": True,
    }
    monkeypatch.setattr("app._06_party.arrow_duty.time.time", lambda: clock["t"])
    monkeypatch.setattr(
        "app._06_party.support.party_critical_escape", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type(
            "P", (), {"map_id": 4, "x": pose["x"], "y": pose["y"]}
        )(),
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_moving", lambda: body["moving"]
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_standing", lambda: body["standing"]
    )
    world = type(
        "W",
        (),
        {
            "player": type("P", (), {"identity": type("N", (), {"name": "Boss"})()})(),
            "last_party": {"in_party": True, "members": [row]},
            "last_print_state": None,
        },
    )()
    hold = {"id": "hold:hp:Boss", "for": "Boss", "item": "hp"}
    board = _Board()
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: potion
    )
    assert leader_supply_action(world, board, hold, None) is potion

    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: None
    )
    pose["y"] = 40
    walking = leader_supply_action(world, board, hold, None)
    assert walking is not None
    assert "hold" in str(getattr(walking, "reason", ""))
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    assert board.scratch["party_leader_hold_pose"]["y"] == 40
    assert leader_supply_stand(board, world.last_party, hold) is None

    body["moving"] = False
    body["standing"] = True
    stopped = leader_supply_action(world, board, hold, None)
    assert stopped is not None
    assert leader_supply_stand(board, world.last_party, hold) is None
    assert board.scratch["party_leader_hold_pose"].get("confirmed") is not True
    clock["t"] += 0.5
    settled = leader_supply_action(world, board, hold, None)
    assert settled is not None
    stand = leader_supply_stand(board, world.last_party, hold)
    assert stand is not None
    assert stand["map_id"] == 4
    assert (stand["x"], stand["y"]) == (10, 40)
    assert board.scratch["party_leader_hold_pose"]["stopped"] is True

    pose["y"] = 41
    one = leader_supply_action(world, board, hold, None)
    assert one is not None
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    shifted = leader_supply_stand(board, world.last_party, hold)
    assert shifted is not None
    assert shifted["map_id"] == 4
    assert (shifted["x"], shifted["y"]) == (10, 40)

    pose["y"] = 42
    stayed = leader_supply_action(world, board, hold, None)
    assert stayed is not None
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    frozen = leader_supply_stand(board, world.last_party, hold)
    assert frozen is not None
    assert (frozen["x"], frozen["y"]) == (10, 40)

    hold["dropping"] = True
    assert leader_supply_action(world, board, hold, None) is None
    assert board.scratch["party_leader_hold_pose"]["moved"] is True

    assert leader_supply_action(world, board, None, None) is None
    fresh = {"id": "hold:hp:Boss:1", "for": "Boss", "item": "hp"}
    pose["y"] = 42
    again = leader_supply_action(world, board, fresh, None)
    assert again is not None
    assert board.scratch["party_leader_hold_pose"]["id"] == "hold:hp:Boss:1"
    assert board.scratch["party_leader_hold_pose"]["moved"] is False


def test_supply_identity_prefers_guid_and_skips_an_ambiguous_tile() -> None:
    from app._06_party.arrow_duty import claim_names_me
    from app._06_party.loot import stable_self_identity

    snap = {
        "in_party": True,
        "members": [
            {"name": "Elf", "guid": "0xAA", "map_id": 4, "x": 10, "y": 10},
            {"name": "Mage", "guid": "0xBB", "map_id": 4, "x": 11, "y": 10},
        ],
    }
    player = type("P", (), {"memory_guid": "0xBB"})()
    assert stable_self_identity(snap, (10, 10), 4, player=player) == ("Mage", "0xBB")
    assert stable_self_identity(snap, (10, 10), 4) == ("", "")
    twins = {
        "in_party": True,
        "members": [
            {"name": "Elf", "map_id": 4, "x": 10, "y": 10},
            {"name": "Elf", "map_id": 4, "x": 12, "y": 10},
        ],
    }
    named = type("P", (), {"identity": type("N", (), {"name": "Elf"})()})()
    assert stable_self_identity(twins, (10, 10), 4, player=named) == ("", "")
    assert claim_names_me({"for": "Elf", "guid": "0xAA"}, "Elf", "0xBB") is False
    assert claim_names_me({"for": "Elf", "guid": "0xAA"}, "Other", "0xAA") is True
    assert claim_names_me({"for": "Elf"}, "Elf", "") is True


def test_a_far_party_row_keeps_the_confirmed_stand() -> None:
    from app._06_party.arrow_duty import _apply_leader_drop_recheck, _leader_drop_recheck

    duty = {
        "kind": "drop",
        "item": "hp",
        "name": "Boss",
        "qty": 10,
        "min": 1,
        "guid": "0x10",
        "attempt": 0,
        "member_map": 4,
        "member_x": 10,
        "member_y": 20,
    }

    def _party(y: int) -> dict:
        return {
            "in_party": True,
            "leader": {
                "name": "Boss",
                "guid": "0x10",
                "is_leader": True,
                "map_id": 4,
                "x": 10,
                "y": y,
            },
            "members": [],
        }

    far = type("S", (), {"last_party": _party(24)})()
    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:hp:Boss", "for": "Boss"}
    assert _leader_drop_recheck(far, dict(duty), manager._nav_blackboard) is None
    kept = _apply_leader_drop_recheck(manager, far, dict(duty))
    assert kept is not None
    assert manager.runtime.supply_hold is not None
    assert manager.runtime.last_reason != "stand moved"

    same = type("S", (), {"last_party": _party(20)})()
    assert _leader_drop_recheck(same, dict(duty), manager._nav_blackboard) is None

    two = type("S", (), {"last_party": _party(22)})()
    assert _leader_drop_recheck(two, dict(duty), manager._nav_blackboard) is None
    kept_after = _apply_leader_drop_recheck(manager, two, dict(duty))
    assert kept_after is not None
    assert (kept_after["member_x"], kept_after["member_y"]) == (10, 20)
    assert manager.runtime.supply_hold is not None
    assert manager.runtime.last_reason != "stand moved"


def test_a_one_tile_leader_move_retargets_the_drop_without_clearing_the_hold() -> None:
    from app._06_party.arrow_duty import _leader_drop_recheck, _tick_drop

    duty = {
        "kind": "drop",
        "item": "arrow",
        "name": "Boss",
        "qty": 10,
        "min": 1,
        "map_id": 4,
        "x": 9,
        "y": 19,
        "member_map": 4,
        "member_x": 10,
        "member_y": 20,
        "exact": True,
    }
    same = {
        "in_party": True,
        "leader": {"name": "Boss", "guid": "0x10", "is_leader": True, "map_id": 4, "x": 10, "y": 20},
        "members": [],
    }
    assert _leader_drop_recheck(type("S", (), {"last_party": same})(), duty) is None
    one = {
        "in_party": True,
        "leader": {"name": "Boss", "guid": "0x10", "is_leader": True, "map_id": 4, "x": 11, "y": 20},
        "members": [],
    }
    refreshed = _leader_drop_recheck(type("S", (), {"last_party": one})(), duty)
    assert isinstance(refreshed, dict)
    assert (refreshed["x"], refreshed["y"]) == (11, 20)
    two = {
        "in_party": True,
        "leader": {"name": "Boss", "guid": "0x10", "is_leader": True, "map_id": 4, "x": 10, "y": 22},
        "members": [],
    }
    assert _leader_drop_recheck(type("S", (), {"last_party": two})(), duty) is None

    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:arrow:Boss", "for": "Boss"}
    state = type("S", (), {"last_party": one})()
    dropped = {"n": 0}

    def _beside(_manager, _state, planned):
        assert (planned["member_x"], planned["member_y"]) == (11, 20)
        return type("W", (), {"reason": "walk to member"})()

    def _step(*_args, **_kwargs):
        dropped["n"] += 1
        return {"ok": True}

    import app._06_party.arrow_duty as arrow_duty
    import app._06_party.supply_drop as supply_drop

    real_beside = arrow_duty._beside_member
    real_step = supply_drop.step_ground_drop
    arrow_duty._beside_member = _beside
    supply_drop.step_ground_drop = _step
    try:
        action = _tick_drop(manager, state, duty)
    finally:
        arrow_duty._beside_member = real_beside
        supply_drop.step_ground_drop = real_step
    assert getattr(action, "reason", "") == "walk to member"
    assert dropped["n"] == 0
    assert manager.runtime.supply_hold is not None


def test_a_one_tile_party_row_retargets_the_drop_again() -> None:
    from app._06_party.arrow_duty import _ATTEMPT, _apply_leader_drop_recheck

    stand = {
        "id": "hold:hp:poorboy",
        "for": "poorboy",
        "map_id": 0,
        "x": 32624,
        "y": 33148,
        "confirmed": True,
    }
    duty = {"name": "poorboy", "item": "hp", "guid": "0x10", "qty": 10, "min": 1}

    def _near_stand(tile: tuple[int, int]) -> bool:
        return max(abs(int(tile[0]) - 368), abs(int(tile[1]) - 444)) <= 4

    planned = plan_supply_drop(duty, stand, _near_stand)
    assert planned is not None
    one = type("S", (), {"last_party": _leader_party(0, 32625, 33148)})()
    manager = _Manager()
    manager._nav_blackboard.scratch[_ATTEMPT] = {"walk_idle_since": 10.0}
    first = _apply_leader_drop_recheck(manager, one, planned)
    assert first is not None
    assert (first["member_x"], first["member_y"]) == (32625, 33148)
    assert "walk_idle_since" not in manager._nav_blackboard.scratch[_ATTEMPT]
    manager._nav_blackboard.scratch[_ATTEMPT]["walk_idle_since"] = 12345.0
    second = _apply_leader_drop_recheck(manager, one, planned)
    assert second is not None
    assert (second["member_x"], second["member_y"]) == (32625, 33148)
    assert "walk_idle_since" not in manager._nav_blackboard.scratch[_ATTEMPT]


def test_a_mage_shopkeeper_heals_only_when_the_cast_is_immediate(monkeypatch) -> None:
    from app._06_party.manager import PartyMemberManager

    manager = PartyMemberManager({"seat_role": "shopkeeper"})
    board = _Board()
    manager._nav_blackboard = board
    seen: dict = {}

    def _heal(_state, _origin, cast_only=False, below=None, **_extra):
        seen["cast_only"] = cast_only
        seen["below"] = below
        return type("I", (), {"reason": "list heal"})()

    monkeypatch.setattr(manager, "_party_list_heal", _heal)
    monkeypatch.setattr(
        "app._06_party.manager.mage_skips_party_assist", lambda _state: True
    )
    state = type("S", (), {})()
    origin = type("O", (), {"x": 1, "y": 1})()
    heal = manager._opening_shopkeeper_heal(state, origin)
    assert heal is not None
    assert seen["cast_only"] is True
    assert isinstance(seen["below"], int)
    board.scratch["shop_halted"] = True
    assert manager._opening_shopkeeper_heal(state, origin) is None
    board.scratch.clear()
    monkeypatch.setattr(
        "app._06_party.manager.mage_skips_party_assist", lambda _state: False
    )
    assert manager._opening_shopkeeper_heal(state, origin) is None


def test_same_tile_keeps_the_confirmed_name_and_unknown_is_not_mage() -> None:
    from app._06_party.config import PartyMemberConfig
    from websocket.party_orders import seat_role_for_name, self_name_from_party

    snap = {
        "in_party": True,
        "members": [
            {"name": "매력여기사", "is_leader": True, "map_id": 4, "x": 10, "y": 10},
            {"name": "데컨큐인", "map_id": 4, "x": 10, "y": 10},
        ],
    }
    assert self_name_from_party(snap, 4, 10, 10) == ""
    assert self_name_from_party(snap, 4, 10, 10, confirmed="데컨큐인") == "데컨큐인"
    assert self_name_from_party(snap, 4, 10, 10, confirmed="leader") == ""

    roster = [{"name": "데컨큐인", "role": "shopkeeper", "loot": "responsible"}]
    assert seat_role_for_name(roster, "매력여기사") == "unknown"
    assert seat_role_for_name(roster, "") == "unknown"
    assert seat_role_for_name(roster, "데컨큐인") == "shopkeeper"
    own = PartyMemberConfig(seat_role="shopkeeper", loot_role="responsible")
    missed = own.merge_leader_policy(
        {"roster": roster, "loot_role": "none"},
        self_name="매력여기사",
        resolve_seat=True,
    )
    assert missed.seat_role == "unknown"
    assert missed.loot_role == "responsible"
    named = own.merge_leader_policy(
        {"roster": roster, "loot_role": "none"},
        self_name="데컨큐인",
        resolve_seat=True,
    )
    assert named.seat_role == "shopkeeper"
    assert named.loot_role == "responsible"


def test_a_latched_hold_stays_when_the_recipient_steps_outside_12() -> None:
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.supply_stand = None
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    manager = _Manager()
    origin = type("O", (), {"x": 100, "y": 100})()
    manager._nav_blackboard.world_origin = origin
    manager._nav_blackboard.nav_goal = None
    manager._nav_blackboard.intent = None
    pose = {"x": 100, "y": 100}
    import app._04_decision.behaviors.travel as travel
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    real_start = travel.start_travel
    real_emit = travel.emit_travel_hop
    session.live_pose_from_state = lambda _state, fresh=False: type(
        "P", (), {"map_id": 4, "x": pose["x"], "y": pose["y"]}
    )()
    travel.start_travel = lambda board, goal, reason="": setattr(
        board, "nav_goal", (int(goal[0]), int(goal[1]))
    )
    travel.emit_travel_hop = lambda *args, **kwargs: False
    try:
        near = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
        assert manager.runtime.supply_hold is not None
        assert "supply hold" in str(getattr(near, "reason", ""))
        origin.x, origin.y = 10, 10
        pose["x"], pose["y"] = 10, 10
        far = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        travel.start_travel = real_start
        travel.emit_travel_hop = real_emit
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert manager.runtime.supply_hold is not None
    assert manager.runtime.supply_hold.get("dropping") is not True
    assert manager._nav_blackboard.scratch["party_supply_attempt"]["latched"] is True
    assert manager._nav_blackboard.nav_goal == (100, 100)
    assert far is None or getattr(far, "reason", "") != "supply receive"


def test_the_recipient_hunts_in_place_until_the_drop_is_announced() -> None:
    from app._06_party.arrow_duty import recipient_hold_intent

    board = _Board()
    board.current_target_id = 7
    waiting = recipient_hold_intent(object(), board, {"id": "hold:hp:Boss", "for": "Boss"})
    assert "supply hold" in str(getattr(waiting, "reason", ""))
    board.current_target_id = 7
    receiving = recipient_hold_intent(
        object(),
        board,
        {"id": "hold:hp:Boss", "for": "Boss", "dropping": True},
    )
    assert "supply receive" in str(getattr(receiving, "reason", ""))
    assert board.current_target_id is None


def test_a_dropping_hold_is_published_again(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(
        "app._06_party.comms.publish.publish_body",
        lambda body: sent.append(dict(body)) or 1,
    )
    from session.bot_controller import BotController

    class _Leader:
        _party_hold_id = ""
        _party_hold_drop = False
        _party_stand_key = None
        hold = {"id": "hold:hp:Boss", "for": "Boss", "item": "hp", "qty": 5, "min": 10}

        def _leader_supply_hold(self):
            return dict(self.hold)

    leader = _Leader()
    BotController._publish_supply_hold(leader)
    assert sent[0]["dropping"] is False
    leader.hold["dropping"] = True
    BotController._publish_supply_hold(leader)
    assert sent[1]["id"] == "hold:hp:Boss"
    assert sent[1]["dropping"] is True
    BotController._publish_supply_hold(leader)
    assert len(sent) == 2


def test_a_walk_halts_and_the_stand_waits_for_a_real_stop(monkeypatch) -> None:
    from app._02_state.enums import ActionType
    from app._06_party.arrow_duty import leader_supply_action, leader_supply_stand

    pose = {"x": 10, "y": 10}
    body = {"moving": True, "standing": False}
    clock = {"t": 2000.0}
    row = {
        "name": "Boss",
        "guid": "0x10",
        "map_id": 0,
        "x": 1,
        "y": 1,
        "is_leader": True,
    }
    monkeypatch.setattr("app._06_party.arrow_duty.time.time", lambda: clock["t"])
    monkeypatch.setattr(
        "app._06_party.support.party_critical_escape", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type(
            "P", (), {"map_id": 4, "x": pose["x"], "y": pose["y"]}
        )(),
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_moving", lambda: body["moving"]
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_standing", lambda: body["standing"]
    )
    world = type(
        "W",
        (),
        {
            "player": type("P", (), {"identity": type("N", (), {"name": "Boss"})()})(),
            "last_party": {"in_party": True, "members": [row], "leader": row},
            "last_print_state": None,
        },
    )()
    hold = {"id": "hold:hp:Boss", "for": "Boss", "item": "hp"}
    board = _Board()
    walking = leader_supply_action(world, board, hold, None)
    assert walking.action is ActionType.SHOP_STOP
    assert "hold" in str(walking.reason)
    pose["y"] = 40
    body["moving"] = False
    body["standing"] = True
    jumped = leader_supply_action(world, board, hold, None)
    assert jumped is not None
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    assert board.scratch["party_leader_hold_pose"].get("confirmed") is not True
    assert leader_supply_stand(board, world.last_party, hold) is None
    parked = leader_supply_action(world, board, hold, None)
    assert parked is not None
    assert leader_supply_stand(board, world.last_party, hold) is None
    clock["t"] += 0.5
    settled = leader_supply_action(world, board, hold, None)
    assert settled is not None
    stand = leader_supply_stand(board, world.last_party, hold)
    assert stand is not None and stand.get("confirmed") is True
    assert stand["map_id"] == 4
    assert (stand["x"], stand["y"]) == (10, 40)
    pose["y"] = 42
    stayed = leader_supply_action(world, board, hold, None)
    assert stayed is not None
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    frozen = leader_supply_stand(board, world.last_party, hold)
    assert frozen is not None
    assert (frozen["x"], frozen["y"]) == (10, 40)


def test_esc_retries_only_while_the_body_is_moving(monkeypatch, caplog) -> None:
    import logging

    from app._02_state.enums import ActionType
    from app._06_party.arrow_duty import HOLD_HALT_MAX, leader_supply_action

    caplog.set_level(logging.INFO, logger="manmabot.party")
    pose = {"map": 4, "x": 10, "y": 10}
    body = {"moving": True, "standing": False}
    clock = {"t": 3000.0}
    care = {"intent": None}
    row = {
        "name": "Boss",
        "guid": "0x10",
        "map_id": 0,
        "x": 1,
        "y": 1,
        "is_leader": True,
    }
    monkeypatch.setattr("app._06_party.arrow_duty.time.time", lambda: clock["t"])
    monkeypatch.setattr(
        "app._06_party.support.party_critical_escape", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival",
        lambda *_a, **_k: care["intent"],
    )
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type(
            "P", (), {"map_id": pose["map"], "x": pose["x"], "y": pose["y"]}
        )(),
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_moving", lambda: body["moving"]
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_standing", lambda: body["standing"]
    )
    world = type(
        "W",
        (),
        {
            "player": type("P", (), {"identity": type("N", (), {"name": "Boss"})()})(),
            "last_party": {"in_party": True, "members": [row]},
            "last_print_state": None,
        },
    )()
    hold = {"id": "hold:hp:Boss", "for": "Boss", "item": "hp"}
    board = _Board()
    first = leader_supply_action(world, board, hold, None)
    assert first.action is ActionType.SHOP_STOP
    assert board.scratch["party_leader_hold_pose"]["halt_n"] == 1
    second = leader_supply_action(world, board, hold, None)
    assert second.action is not ActionType.SHOP_STOP
    assert board.scratch["party_leader_hold_pose"]["halt_n"] == 1

    clock["t"] += 0.5
    retried = leader_supply_action(world, board, hold, None)
    assert retried.action is ActionType.SHOP_STOP
    assert board.scratch["party_leader_hold_pose"]["halt_n"] == 2

    care["intent"] = type("I", (), {"reason": "hp potion"})()
    clock["t"] += 0.5
    assert leader_supply_action(world, board, hold, None) is care["intent"]
    assert board.scratch["party_leader_hold_pose"]["halt_n"] == 2

    care["intent"] = None
    body["moving"] = False
    body["standing"] = True
    stopped = leader_supply_action(world, board, hold, None)
    assert stopped.action is not ActionType.SHOP_STOP
    assert "supply hold halt stopped n=2" in caplog.text
    pose["y"] = 18
    body["moving"] = True
    body["standing"] = False
    leader_supply_action(world, board, hold, None)
    assert board.scratch["party_leader_hold_pose"].get("confirmed") is not True
    assert board.scratch["party_leader_hold_pose"]["settle_at"] == 0.0

    for _ in range(HOLD_HALT_MAX):
        clock["t"] += 0.5
        leader_supply_action(world, board, hold, None)
    assert board.scratch["party_leader_hold_pose"]["halt_n"] == HOLD_HALT_MAX
    clock["t"] += 0.5
    gave_up = leader_supply_action(world, board, hold, None)
    assert gave_up.action is not ActionType.SHOP_STOP
    assert "supply hold halt still moving n=3" in caplog.text


def test_talking_island_map_zero_stands_and_a_missing_map_does_not(monkeypatch) -> None:
    from app._06_party.arrow_duty import (
        STAND_WAIT_S,
        _leader_drop_recheck,
        _stand_ready,
        leader_supply_action,
        leader_supply_stand,
        plan_supply_drop,
        tick_shopkeeper_duty,
    )

    pose = {"ready": True, "map": 0, "x": 381, "y": 442}
    body = {"moving": True, "standing": False}
    clock = {"t": 4000.0}
    sent: list[dict] = []
    monkeypatch.setattr("app._06_party.arrow_duty.time.time", lambda: clock["t"])
    monkeypatch.setattr(
        "app._06_party.comms.publish.publish_body",
        lambda body: sent.append(dict(body)) or 1,
    )
    monkeypatch.setattr(
        "app._06_party.support.party_critical_escape", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._06_party.support.urgent_self_survival", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: (
            None
            if not pose["ready"]
            else type("P", (), {"map_id": pose["map"], "x": pose["x"], "y": pose["y"]})()
        ),
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_moving", lambda: body["moving"]
    )
    monkeypatch.setattr(
        "app._05_action.body_pose.body_is_standing", lambda: body["standing"]
    )
    world = type(
        "W",
        (),
        {
            "player": type("P", (), {"identity": type("N", (), {"name": "Boss"})()})(),
            "last_party": {
                "in_party": True,
                "members": [
                    {
                        "name": "Boss",
                        "guid": "0x10",
                        "map_id": 0,
                        "x": 1,
                        "y": 1,
                        "is_leader": True,
                    }
                ],
            },
            "last_print_state": None,
        },
    )()
    hold = {"id": "hold:hp:Boss", "for": "Boss", "item": "hp"}
    board = _Board()
    leader_supply_action(world, board, hold, None)
    body["moving"] = False
    body["standing"] = True
    leader_supply_action(world, board, hold, None)
    assert leader_supply_stand(board, world.last_party, hold) is None
    clock["t"] += 0.5
    leader_supply_action(world, board, hold, None)
    stand = leader_supply_stand(board, world.last_party, hold)
    assert stand is not None
    assert stand["map_id"] == 0
    assert (stand["x"], stand["y"]) == (381, 442)
    assert stand["confirmed"] is True

    from session.bot_controller import BotController

    class _Leader:
        _party_hold_id = "hold:hp:Boss"
        _party_hold_drop = False
        _party_stand_key = None

        def _leader_supply_hold(self):
            return dict(hold)

    BotController._publish_supply_stand(_Leader(), world, None, board)
    assert sent[0]["map_id"] == 0
    assert (sent[0]["x"], sent[0]["y"]) == (381, 442)

    duty = {"name": "Boss", "item": "hp", "guid": "0x10", "attempt": 0}
    assert _stand_ready(duty, stand) is True
    planned = plan_supply_drop(duty, stand, lambda _tile: True)
    assert planned is not None
    assert planned["member_map"] == 0
    assert (planned["member_x"], planned["member_y"]) == (381, 442)
    world.last_party["members"][0]["x"] = 381
    world.last_party["members"][0]["y"] = 443
    stepped = _leader_drop_recheck(world, planned)
    assert isinstance(stepped, dict)
    assert stepped["map_id"] == 0
    assert (stepped["x"], stepped["y"]) == (381, 443)

    pose["y"] = 444
    stayed = leader_supply_action(world, board, hold, None)
    assert stayed is not None
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    frozen = leader_supply_stand(board, world.last_party, hold)
    assert frozen is not None
    assert (frozen["x"], frozen["y"]) == (381, 442)
    pose["map"] = 4
    assert leader_supply_action(world, board, hold, None) is None
    assert board.scratch["party_leader_hold_pose"]["moved"] is True
    pose["map"] = 0

    pose["x"], pose["y"] = 0, 0
    fresh = {"id": "hold:hp:Boss:1", "for": "Boss", "item": "hp"}
    leader_supply_action(world, board, fresh, None)
    clock["t"] += 0.5
    leader_supply_action(world, board, fresh, None)
    clock["t"] += 0.5
    leader_supply_action(world, board, fresh, None)
    assert board.scratch["party_leader_hold_pose"].get("confirmed") is not True
    assert leader_supply_stand(board, world.last_party, fresh) is None

    pose["ready"] = False
    pose["x"], pose["y"] = 381, 442
    unread = {"id": "hold:hp:Boss:2", "for": "Boss", "item": "hp"}
    leader_supply_action(world, board, unread, None)
    clock["t"] += 1.0
    leader_supply_action(world, board, unread, None)
    assert board.scratch["party_leader_hold_pose"]["id"] == "hold:hp:Boss:1"
    assert leader_supply_stand(board, world.last_party, unread) is None
    missing = dict(stand)
    missing.pop("map_id")
    assert _stand_ready(duty, missing) is False

    pose["ready"] = True
    pose["x"], pose["y"] = 100, 100
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 0,
            "x": 100,
            "y": 100,
        }
    ]
    manager = _close_supply(reports, None)
    manager._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": clock["t"] - STAND_WAIT_S - 1.0,
        "shifts": 0,
    }
    try:
        timed_out = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert timed_out is None
    assert manager.runtime.last_reason == "stand timeout"


def test_a_member_stand_keeps_confirmed_so_the_leader_can_publish_it(monkeypatch) -> None:
    """The mage's settled tile is useless to the shopkeeper without confirmed."""
    from session.bot_controller import BotController
    from app._06_party.sync import member_states

    sent: list[dict] = []
    monkeypatch.setattr(
        "app._06_party.comms.publish.publish_body",
        lambda body: sent.append(dict(body)) or 1,
    )
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: None,
    )
    stand = {
        "id": "hold:hp:poorboy",
        "for": "poorboy",
        "map_id": 0,
        "x": 360,
        "y": 424,
        "confirmed": True,
    }
    runtime = type(
        "R",
        (),
        {
            "last_kind": "supply",
            "last_reason": "supply hold",
            "duty_phase": "follow",
            "supply_notice": None,
            "supply_hold": None,
            "supply_stand": stand,
        },
    )()
    member = type(
        "M",
        (),
        {
            "state": type("S", (), {"value": "running"})(),
            "_party_brain_ref": type("B", (), {"runtime": runtime})(),
        },
    )()
    live = BotController._member_live_view(member, object())
    assert live["supply_stand"]["confirmed"] is True
    assert (live["supply_stand"]["x"], live["supply_stand"]["y"]) == (360, 424)

    hold = {"id": "hold:hp:poorboy", "for": "poorboy", "item": "hp"}
    leader = type(
        "L",
        (),
        {
            "_party_hold_id": hold["id"],
            "_party_hold_drop": False,
            "_party_stand_key": None,
            "_leader_supply_hold": lambda self: dict(hold),
        },
    )()
    saved = dict(member_states.rows)
    try:
        member_states.rows.clear()
        member_states.rows["poorboy"] = {
            "live": {"supply_stand": {k: v for k, v in stand.items() if k != "confirmed"}}
        }
        BotController._publish_supply_stand(leader, object(), None, None)
        assert sent == []
        member_states.rows["poorboy"] = {"live": {"supply_stand": dict(live["supply_stand"])}}
        BotController._publish_supply_stand(leader, object(), None, None)
    finally:
        member_states.rows.clear()
        member_states.rows.update(saved)
    assert sent[0]["type"] == "supply_stand"
    assert sent[0]["confirmed"] is True
    assert sent[0]["map_id"] == 0
    assert (sent[0]["x"], sent[0]["y"]) == (360, 424)


def test_an_unconfirmed_stand_updates_and_an_old_attempt_does_not_drop() -> None:
    import time

    from app._06_party.arrow_duty import _stand_ready

    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.supply_stand = {
        "id": "hold:arrow:Elf",
        "for": "Elf",
        "map_id": 4,
        "x": 100,
        "y": 80,
        "confirmed": False,
    }
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 500, "silver_arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
            "map_id": 4,
            "x": 100,
            "y": 100,
        }
    ]
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 100, "y": 100})()
    manager._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": time.time(),
        "shifts": 0,
        "stand_id": "hold:arrow:Elf",
        "stand_at": [4, 100, 100],
    }
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    session.live_pose_from_state = lambda _state, fresh=False: _pose(4, 100, 100)
    try:
        action = tick_shopkeeper_duty(manager, _State(), self_name="Keeper")
    finally:
        session.live_pose_from_state = real_pose
        member_orders.party_reports = saved_reports
        member_orders.supply_stand = saved_stand
        member_orders.supply_open = saved_open
    assert action is not None
    assert manager.runtime.supply_hold is not None
    assert manager.runtime.last_reason == "wait for stand"
    assert manager._nav_blackboard.scratch["party_supply_attempt"]["stand_at"][2] == 80
    duty = {"name": "Elf", "item": "arrow", "attempt": 1}
    assert (
        _stand_ready(
            duty,
            {
                "id": "hold:arrow:Elf",
                "for": "Elf",
                "map_id": 4,
                "x": 1,
                "y": 1,
                "confirmed": True,
            },
        )
        is False
    )


def _leader_party(map_id: int, x: int, y: int) -> dict:
    return {
        "in_party": True,
        "members": [
            {
                "name": "poorboy",
                "guid": "0x10",
                "is_leader": True,
                "map_id": map_id,
                "x": x,
                "y": y,
            }
        ],
    }


def test_talking_island_game_stand_drops_on_the_nav_tile() -> None:
    """Game (32624,33148) on map 0 is nav (368,444). A bad map waits."""
    from app._06_party.arrow_duty import (
        _apply_leader_drop_recheck,
        _leader_drop_recheck,
        _tick_drop,
    )

    stand = {
        "id": "hold:hp:poorboy",
        "for": "poorboy",
        "map_id": 0,
        "x": 32624,
        "y": 33148,
        "confirmed": True,
    }
    duty = {"name": "poorboy", "item": "hp", "guid": "0x10", "qty": 10, "min": 1}

    def _near_stand(tile: tuple[int, int]) -> bool:
        return max(abs(int(tile[0]) - 368), abs(int(tile[1]) - 444)) <= 4

    planned = plan_supply_drop(duty, stand, _near_stand)
    assert planned is not None
    assert planned["member_map"] == 0
    assert (planned["member_x"], planned["member_y"]) == (32624, 33148)
    assert (planned["drop_x"], planned["drop_y"]) == (369, 445)
    assert (planned["x"], planned["y"]) == (370, 446)
    assert max(planned["drop_x"], planned["drop_y"], planned["x"], planned["y"]) < 1000

    same = type("S", (), {"last_party": _leader_party(0, 32624, 33148)})()
    assert _leader_drop_recheck(same, planned) is None

    wrong_map = type("S", (), {"last_party": _leader_party(4, 32624, 33148)})()
    assert _leader_drop_recheck(wrong_map, planned) == "defer"
    held = _Manager()
    held.runtime.supply_hold = {"id": "hold:hp:poorboy", "for": "poorboy"}
    waiting = _tick_drop(held, wrong_map, planned)
    assert getattr(waiting, "reason", "") == "party_member:supply drop held"
    assert held.runtime.supply_hold is not None
    assert held.runtime.last_reason == "supply drop held"

    moved_map = type("S", (), {"last_party": _leader_party(4, 33154, 33401)})()
    assert _leader_drop_recheck(moved_map, planned) == "cancel"
    cancelled = _Manager()
    cancelled.runtime.supply_hold = {"id": "hold:hp:poorboy", "for": "poorboy"}
    assert _tick_drop(cancelled, moved_map, planned) is None
    assert cancelled.runtime.supply_hold is None
    assert cancelled.runtime.last_reason == "stand moved"

    one = type("S", (), {"last_party": _leader_party(0, 32625, 33148)})()
    stepped = _leader_drop_recheck(one, planned)
    assert isinstance(stepped, dict)
    assert stepped["map_id"] == 0
    assert (stepped["x"], stepped["y"]) == (32625, 33148)
    retargeted = plan_supply_drop(duty, stepped, _near_stand)
    assert retargeted is not None
    assert (retargeted["member_x"], retargeted["member_y"]) == (32625, 33148)
    assert max(
        abs(retargeted["drop_x"] - 369),
        abs(retargeted["drop_y"] - 444),
    ) == 1

    two = type("S", (), {"last_party": _leader_party(0, 32626, 33148)})()
    assert _leader_drop_recheck(two, planned) is None

    finished = _Manager()
    finished.runtime.supply_hold = {"id": "hold:hp:poorboy", "for": "poorboy"}
    drops = {"n": 0}

    def _beside(_manager, _state, _duty):
        return True

    def _step(*_args, **_kwargs):
        drops["n"] += 1
        return {"ok": True, "map_id": 0, "x": 369, "y": 445}

    import app._06_party.arrow_duty as arrow_duty
    import app._06_party.supply_drop as supply_drop

    real_beside = arrow_duty._beside_member
    real_step = supply_drop.step_ground_drop
    arrow_duty._beside_member = _beside
    supply_drop.step_ground_drop = _step
    try:
        announced = _tick_drop(finished, same, planned)
        assert getattr(announced, "reason", "") == "party_member:supply drop"
        assert finished.runtime.supply_hold is not None
        assert drops["n"] == 0
        done = _tick_drop(finished, same, planned)
    finally:
        arrow_duty._beside_member = real_beside
        supply_drop.step_ground_drop = real_step
    assert done is None
    assert drops["n"] == 1
    assert finished.runtime.supply_hold is None
    assert finished.runtime.last_reason == "hp dropped"
    kept = _apply_leader_drop_recheck(finished, two, planned)
    assert kept is planned
    assert finished.runtime.last_reason == "hp dropped"
    assert finished.runtime.supply_hold is None


def test_a_leader_row_without_a_tile_drops_on_the_confirmed_stand(monkeypatch) -> None:
    """An empty or unreadable leader row keeps the stand. Another map that still projects waits."""
    from app._06_party.arrow_duty import (
        STAND_WAIT_S,
        _apply_leader_drop_recheck,
        _beside_member,
        _coord_on_map,
        _leader_drop_recheck,
        _map_nav_frame,
        _tick_drop,
    )

    stand = {
        "id": "hold:hp:poorboy",
        "for": "poorboy",
        "map_id": 0,
        "x": 32624,
        "y": 33148,
        "confirmed": True,
    }
    duty = {"name": "poorboy", "item": "hp", "guid": "0x10", "qty": 10, "min": 1}

    def _near_stand(tile: tuple[int, int]) -> bool:
        return max(abs(int(tile[0]) - 368), abs(int(tile[1]) - 444)) <= 4

    planned = plan_supply_drop(duty, stand, _near_stand)
    assert planned is not None
    frame = _map_nav_frame(0)
    assert frame is not None
    ox, oy, width, height = frame
    unread = (int(ox) + int(width) + 50, int(oy) + int(height) + 50)
    assert _coord_on_map(0, unread[0], unread[1]) is None

    missing = {
        "in_party": True,
        "members": [{"name": "poorboy", "guid": "0x10", "is_leader": True, "map_id": 0}],
    }
    assert _leader_drop_recheck(type("S", (), {"last_party": missing})(), planned) is None
    assert _leader_drop_recheck(type("S", (), {"last_party": _leader_party(0, 0, 0)})(), planned) is None
    unreadable = type("S", (), {"last_party": _leader_party(0, unread[0], unread[1])})()
    assert _leader_drop_recheck(unreadable, planned) is None

    empty_drop = _Manager()
    import app._06_party.arrow_duty as arrow_duty

    real_beside = arrow_duty._beside_member
    arrow_duty._beside_member = lambda *_args, **_kwargs: True
    try:
        announced = _tick_drop(
            empty_drop, type("S", (), {"last_party": missing})(), planned
        )
    finally:
        arrow_duty._beside_member = real_beside
    assert getattr(announced, "reason", "") == "party_member:supply drop"
    assert empty_drop.runtime.last_reason == "supply drop"

    other = {
        "in_party": True,
        "leader": {"name": "Boss", "guid": "0x1", "is_leader": True, "map_id": 4, "x": 10, "y": 10},
        "members": [{"name": "Mage", "guid": "0x20", "map_id": 4}],
    }
    member = dict(planned)
    member["name"] = "Mage"
    member["guid"] = "0x20"
    assert _leader_drop_recheck(type("S", (), {"last_party": other})(), member) is None

    clock = {"t": 5000.0}
    monkeypatch.setattr("app._06_party.arrow_duty.time.time", lambda: clock["t"])
    wrong_map = type("S", (), {"last_party": _leader_party(4, 32624, 33148)})()
    waiting = _Manager()
    waiting._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("poorboy", "hp"),
        "n": 0,
        "since": 0.0,
        "shifts": 0,
    }
    held = _tick_drop(waiting, wrong_map, planned)
    assert getattr(held, "reason", "") == "party_member:supply drop held"
    assert waiting.runtime.supply_hold is not None
    attempt = waiting._nav_blackboard.scratch["party_supply_attempt"]
    assert attempt["defer_since"] == 5000.0
    assert attempt["since"] == 0.0

    clock["t"] = 5000.0 + STAND_WAIT_S
    attempt["since"] = 0.0
    timed_out = _tick_drop(waiting, wrong_map, planned)
    assert timed_out is None
    assert waiting.runtime.supply_hold is None
    assert waiting.runtime.last_reason == "stand timeout"
    assert "defer_since" not in waiting._nav_blackboard.scratch["party_supply_attempt"]

    matched = _Manager()
    matched.runtime.last_reason = "supply drop"
    matched._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("poorboy", "hp"),
        "n": 0,
        "since": clock["t"] - 30.0,
        "shifts": 0,
    }
    same = type("S", (), {"last_party": _leader_party(0, 32624, 33148)})()
    assert _apply_leader_drop_recheck(matched, same, planned) is not None
    assert matched.runtime.last_reason == "supply drop"
    assert matched._nav_blackboard.scratch["party_supply_attempt"]["since"] == clock["t"] - 30.0

    label = _Manager()
    label.runtime.last_reason = "supply drop held"
    label._nav_blackboard.world_origin = type("O", (), {"x": 1, "y": 1})()
    label._nav_blackboard.nav_goal = None
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type("P", (), {"map_id": 0, "x": 1, "y": 1})(),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.travel.start_travel",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.travel.emit_travel_hop",
        lambda *_args, **_kwargs: False,
    )
    walked = _beside_member(label, same, planned)
    assert getattr(walked, "reason", "") == "party_member:arrow drop walk"
    assert label.runtime.last_reason == "arrow drop walk"

    kept = _Manager()
    kept.runtime.last_reason = "walk to member"
    kept._nav_blackboard.world_origin = type("O", (), {"x": 1, "y": 1})()
    kept._nav_blackboard.nav_goal = (planned["x"], planned["y"])
    stayed = _beside_member(kept, same, planned)
    assert getattr(stayed, "reason", "") == "party_member:arrow drop walk"
    assert kept.runtime.last_reason == "walk to member"


def test_a_drop_with_no_click_expires_without_using_the_walk_clock(monkeypatch) -> None:
    """Eight seconds without a hop releases the hold. A hop resets that wait."""
    from app._06_party.arrow_duty import STAND_WAIT_S, _beside_member

    duty = {
        "kind": "drop",
        "item": "hp",
        "name": "Mage",
        "qty": 10,
        "min": 1,
        "map_id": 4,
        "x": 10,
        "y": 20,
        "exact": True,
    }
    state = type("S", (), {})()
    clock = {"t": 8000.0}
    hops = {"emit": False}
    monkeypatch.setattr("app._06_party.arrow_duty.time.time", lambda: clock["t"])
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type("P", (), {"map_id": 4, "x": 1, "y": 1})(),
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.travel.start_travel",
        lambda *_args, **_kwargs: None,
    )

    def _emit(board, *_args, **_kwargs):
        if not hops["emit"]:
            return False
        board.intent = type("I", (), {"reason": "hop"})()
        return True

    monkeypatch.setattr("app._04_decision.behaviors.travel.emit_travel_hop", _emit)

    manager = _Manager()
    manager.runtime.supply_hold = {"id": "hold:hp:Mage", "for": "Mage"}
    manager._nav_blackboard.world_origin = type("O", (), {"x": 1, "y": 1})()
    manager._nav_blackboard.nav_goal = None
    manager._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("mage", "hp"),
        "n": 0,
        "since": 0.0,
        "shifts": 0,
    }
    waiting = _beside_member(manager, state, duty)
    assert getattr(waiting, "reason", "") == "party_member:arrow drop walk"
    attempt = manager._nav_blackboard.scratch["party_supply_attempt"]
    assert attempt["walk_idle_since"] == 8000.0
    assert attempt["since"] == 0.0
    assert manager.runtime.supply_hold is not None

    clock["t"] = 8000.0 + STAND_WAIT_S - 0.1
    attempt["since"] = 0.0
    still = _beside_member(manager, state, duty)
    assert getattr(still, "reason", "") == "party_member:arrow drop walk"
    assert manager.runtime.supply_hold is not None
    assert manager._nav_blackboard.scratch["party_supply_attempt"]["since"] == 0.0

    hops["emit"] = True
    clock["t"] = 8000.0 + STAND_WAIT_S
    stepped = _beside_member(manager, state, duty)
    assert getattr(stepped, "reason", "") == "hop"
    assert manager.runtime.last_reason == "walk to member"
    assert manager.runtime.supply_hold is not None
    assert "walk_idle_since" not in manager._nav_blackboard.scratch["party_supply_attempt"]

    hops["emit"] = False
    manager._nav_blackboard.nav_goal = (10, 20)
    restarted = _beside_member(manager, state, duty)
    assert getattr(restarted, "reason", "") == "party_member:arrow drop walk"
    assert (
        manager._nav_blackboard.scratch["party_supply_attempt"]["walk_idle_since"]
        == clock["t"]
    )

    clock["t"] += STAND_WAIT_S
    manager._nav_blackboard.scratch["party_supply_attempt"]["since"] = 0.0
    expired = _beside_member(manager, state, duty)
    assert expired is None
    assert manager.runtime.supply_hold is None
    assert manager.runtime.last_reason == "stand timeout"
    assert "walk_idle_since" not in manager._nav_blackboard.scratch["party_supply_attempt"]

    arrived = _Manager()
    arrived.runtime.supply_hold = {"id": "hold:hp:Mage", "for": "Mage"}
    arrived._nav_blackboard.world_origin = type("O", (), {"x": 10, "y": 20})()
    arrived._nav_blackboard.scratch["party_supply_attempt"] = {
        "since": 0.0,
        "walk_idle_since": clock["t"] - STAND_WAIT_S,
    }
    assert _beside_member(arrived, state, duty) is True
    assert arrived.runtime.supply_hold is not None
    assert arrived.runtime.last_reason != "stand timeout"
    assert "walk_idle_since" not in arrived._nav_blackboard.scratch["party_supply_attempt"]
