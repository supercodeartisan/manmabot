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
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
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
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
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
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
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
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
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
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
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
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
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
        assert "arrow drop blocked" in str(getattr(first, "reason", ""))
        assert manager.runtime.supply_hold is not None
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


def test_a_moved_stand_cancels_without_a_pause() -> None:
    saved_reports = list(member_orders.party_reports)
    saved_stand = member_orders.supply_stand
    saved_open = bool(member_orders.supply_open)
    member_orders.supply_open = True
    member_orders.party_reports = [
        {
            "from": "Elf",
            "items": {"arrows": 0, "hp": 50, "depoison": 5, "mp": 20},
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
    }
    manager = _Manager()
    manager._nav_blackboard.world_origin = type("O", (), {"x": 100, "y": 100})()
    manager._nav_blackboard.scratch["party_supply_attempt"] = {
        "key": ("elf", "arrow"),
        "n": 0,
        "since": 0.0,
        "shifts": 0,
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
    assert "party_supply_pause" not in manager._nav_blackboard.scratch
    assert manager._nav_blackboard.scratch["party_supply_attempt"]["n"] == 1


def test_the_leader_drinks_before_a_hold_and_a_move_releases_it(monkeypatch) -> None:
    from app._06_party.arrow_duty import leader_supply_action, leader_supply_stand

    potion = type("I", (), {"reason": "hp potion"})()
    pose = {"x": 10, "y": 10}
    body = {"moving": True, "standing": False}
    row = {
        "name": "Boss",
        "guid": "0x10",
        "map_id": 4,
        "x": 10,
        "y": 10,
        "is_leader": True,
    }
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
    row["y"] = 40
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
    stand = leader_supply_stand(board, world.last_party, hold)
    assert stand is not None
    assert (stand["x"], stand["y"]) == (10, 40)
    assert board.scratch["party_leader_hold_pose"]["stopped"] is True

    pose["y"] = 41
    row["y"] = 41
    one = leader_supply_action(world, board, hold, None)
    assert one is not None
    assert board.scratch["party_leader_hold_pose"]["moved"] is False
    shifted = leader_supply_stand(board, world.last_party, hold)
    assert shifted is not None
    assert (shifted["x"], shifted["y"]) == (10, 41)

    pose["y"] = 42
    row["y"] = 42
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
    assert _leader_drop_recheck(type("S", (), {"last_party": two})(), duty) == "cancel"

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


def test_a_mage_shopkeeper_heals_only_when_the_cast_is_immediate(monkeypatch) -> None:
    from app._06_party.manager import PartyMemberManager

    manager = PartyMemberManager({"seat_role": "shopkeeper"})
    board = _Board()
    manager._nav_blackboard = board
    seen: dict = {}

    def _heal(_state, _origin, cast_only=False, below=None):
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
