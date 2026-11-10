"""Party supply drop confirms each step. No game client."""
from __future__ import annotations

from app._05_action.uidialog_gate import unexpected_open_labels
from app._06_party.arrow_duty import _tick_drop
from app._06_party.arrow_policy import DUTY_FOLLOW, DUTY_SUPPLY
from app._06_party import supply_drop
from app._06_party.supply_drop import confirm_live_slot, dismiss_allowed_labels


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.world_origin = type("O", (), {"x": 100, "y": 200})()


class _Bag:
    item_id = 96
    slot = 4
    quantity = 2402


class _Path:
    def is_file(self) -> bool:
        return True


class _Patch:
    def __init__(self, live, **extra) -> None:
        typed: list[int] = []
        dragged: list[int] = []

        def _drag(state, blackboard, scratch):
            dragged.append(int(scratch.get("list_index") or 0))
            return {"map_id": 4, "x": 99, "y": 199}

        def _type(qty: int) -> None:
            typed.append(int(qty))

        self.seen = {"typed": typed, "dragged": dragged}
        self._saved: dict = {}
        base = {
            "grid_path": lambda: _Path(),
            "_kind_stack": lambda state, kind: _Bag(),
            "_ensure_inventory": lambda: True,
            "_inventory_is_open": lambda: True,
            "_live_slot": live,
            "_scroll_until_visible": lambda scratch: True,
            "_total_qty": lambda item_id: 2402,
            "_drag_once": _drag,
            "_wait_qty_dialog": lambda: "qty_prompt",
            "_type_qty": _type,
            "_await_bag_drop": lambda item_id, before, want: int(before) - int(want),
            "_ground_seen": lambda state, blackboard, tile, kind: True,
            "_tap_esc": lambda: None,
            "_tile_from_pose": lambda state, blackboard: {"map_id": 4, "x": 99, "y": 199},
        }
        base.update(extra)
        self._base = base

    def __enter__(self) -> dict:
        for name in self._base:
            self._saved[name] = getattr(supply_drop, name)
            setattr(supply_drop, name, self._base[name])
        return self.seen

    def __exit__(self, *args) -> None:
        for name, fn in self._saved.items():
            setattr(supply_drop, name, fn)


def test_inventory_esc_skips_only_an_active_drop() -> None:
    board = _Board()
    snap = {"open": ["Inventory"]}
    assert dismiss_allowed_labels(board) == ()
    assert unexpected_open_labels(snap, allowed=dismiss_allowed_labels(board)) == ["Inventory"]
    board.scratch["party_supply_drop"] = {"active": True, "item": "arrow"}
    assert unexpected_open_labels(snap, allowed=dismiss_allowed_labels(board)) == []
    both = {"open": ["Inventory", "NPCShop"]}
    assert unexpected_open_labels(both, allowed=dismiss_allowed_labels(board)) == ["NPCShop"]
    board.scratch["party_supply_drop"]["active"] = False
    assert unexpected_open_labels(snap, allowed=dismiss_allowed_labels(board)) == ["Inventory"]


def test_silver_slot_must_match_the_memory_slot() -> None:
    rows = [
        {"id": 96, "slot": 4, "count": 2402},
        {"id": 7, "slot": 1, "count": 965},
    ]
    assert confirm_live_slot(rows, item_id=96, memory_slot=4) == (5, 2402, 2402)
    assert confirm_live_slot(rows, item_id=96, memory_slot=1) is None


def test_drag_uses_the_confirmed_silver_slot() -> None:
    with _Patch(lambda item_id, memory_slot: (5, 2402, 2402)) as seen:
        result = supply_drop.step_ground_drop(_Board(), _Board(), 300, kind="arrow")
        assert result is not None and result.get("ok") is True
        assert result["qty"] == 300
        assert seen["dragged"] == [5]
        assert seen["typed"] == [300]


def test_no_digits_when_the_qty_prompt_is_absent() -> None:
    with _Patch(lambda item_id, memory_slot: (5, 2402, 2402), _wait_qty_dialog=lambda: None) as seen:
        board = _Board()
        result = supply_drop.step_ground_drop(board, board, 300, kind="arrow")
        assert seen["typed"] == []
        assert result is not None and result.get("blocked") is True
        assert result["reason"] == "qty prompt failed"
        assert result.get("ok") is not True


def test_closed_inventory_does_not_reach_drag() -> None:
    with _Patch(lambda item_id, memory_slot: (5, 2402, 2402), _ensure_inventory=lambda: False) as seen:
        result = supply_drop.step_ground_drop(_Board(), _Board(), 300, kind="arrow")
        assert seen["dragged"] == []
        assert seen["typed"] == []
        assert result is not None and result["reason"] == "inventory open failed"


def test_slot_mismatch_does_not_drag() -> None:
    with _Patch(lambda item_id, memory_slot: None) as seen:
        result = supply_drop.step_ground_drop(_Board(), _Board(), 300, kind="arrow")
        assert seen["dragged"] == []
        assert result is not None and result["reason"] == "slot check failed"


def test_bag_must_shrink_before_success() -> None:
    with _Patch(
        lambda item_id, memory_slot: (5, 2402, 2402),
        _await_bag_drop=lambda item_id, before, want: None,
    ) as seen:
        result = supply_drop.step_ground_drop(_Board(), _Board(), 300, kind="arrow")
        assert seen["typed"] == [300]
        assert result is not None and result.get("ok") is not True
        assert result["reason"] == "drop confirm failed"


def test_a_later_bag_shrink_does_not_drag_again() -> None:
    calls = {"n": 0}

    def live(item_id, memory_slot):
        calls["n"] += 1
        if calls["n"] <= 2:
            return (5, 2402, 2402)
        return (5, 2102, 2102)

    with _Patch(live, _await_bag_drop=lambda item_id, before, want: None) as seen:
        board = _Board()
        first = supply_drop.step_ground_drop(board, board, 300, kind="arrow")
        second = supply_drop.step_ground_drop(board, board, 300, kind="arrow")
        assert first is not None and first["reason"] == "drop confirm failed"
        assert second is not None and second.get("ok") is True
        assert seen["dragged"] == [5]


def test_same_stage_stops_after_two_failures() -> None:
    with _Patch(lambda item_id, memory_slot: (5, 2402, 2402), _wait_qty_dialog=lambda: None) as seen:
        board = _Board()
        supply_drop.step_ground_drop(board, board, 300, kind="arrow")
        supply_drop.step_ground_drop(board, board, 300, kind="arrow")
        third = supply_drop.step_ground_drop(board, board, 300, kind="arrow")
        assert seen["dragged"] == [5, 5]
        assert seen["typed"] == []
        assert third is not None and third["reason"] == "qty prompt failed"


class _Runtime:
    def __init__(self) -> None:
        self.duty_phase = None
        self.supply_notice = None
        self.last_kind = ""
        self.last_reason = ""


class _Manager:
    def __init__(self) -> None:
        self.runtime = _Runtime()
        self._nav_blackboard = _Board()


def _duty() -> dict:
    return {
        "item": "arrow",
        "qty": 300,
        "name": "Leader",
        "min": 300,
        "map_id": 4,
        "x": 10,
        "y": 12,
    }


def test_failed_drop_does_not_notify_or_follow() -> None:
    from app._06_party import arrow_duty

    real_beside = arrow_duty._beside_member
    real_step = supply_drop.step_ground_drop
    arrow_duty._beside_member = lambda manager, state, duty: True  # type: ignore[method-assign]
    supply_drop.step_ground_drop = lambda state, board, qty, kind="arrow": {  # type: ignore[method-assign]
        "blocked": True,
        "reason": "qty prompt failed",
    }
    manager = _Manager()
    manager._nav_blackboard.scratch["party_supply_attempt"] = {"dropping": True}
    try:
        action = _tick_drop(manager, object(), _duty())
    finally:
        arrow_duty._beside_member = real_beside  # type: ignore[method-assign]
        supply_drop.step_ground_drop = real_step  # type: ignore[method-assign]
    assert manager.runtime.supply_notice is None
    assert manager.runtime.duty_phase == DUTY_SUPPLY
    assert action is not None
    assert "qty prompt failed" in str(getattr(action, "reason", ""))


def test_verified_drop_notifies_and_resumes_follow() -> None:
    def _ok(state, board, qty, kind="arrow"):
        return {"ok": True, "map_id": 4, "x": 99, "y": 199, "qty": qty}

    from app._06_party import arrow_duty

    real_beside = arrow_duty._beside_member
    real_step = supply_drop.step_ground_drop
    arrow_duty._beside_member = lambda manager, state, duty: True  # type: ignore[method-assign]
    supply_drop.step_ground_drop = _ok  # type: ignore[method-assign]
    manager = _Manager()
    manager._nav_blackboard.scratch["party_supply_attempt"] = {"dropping": True}
    try:
        action = _tick_drop(manager, object(), _duty())
    finally:
        arrow_duty._beside_member = real_beside  # type: ignore[method-assign]
        supply_drop.step_ground_drop = real_step  # type: ignore[method-assign]
    assert action is None
    assert manager.runtime.duty_phase == DUTY_FOLLOW
    notice = manager.runtime.supply_notice
    assert notice is not None
    assert notice["for"] == "Leader"
    assert notice["item"] == "arrow"
    assert notice["qty"] == 300
    assert notice["x"] == 99 and notice["y"] == 199


if __name__ == "__main__":
    test_inventory_esc_skips_only_an_active_drop()
    test_silver_slot_must_match_the_memory_slot()
    test_drag_uses_the_confirmed_silver_slot()
    test_no_digits_when_the_qty_prompt_is_absent()
    test_closed_inventory_does_not_reach_drag()
    test_slot_mismatch_does_not_drag()
    test_bag_must_shrink_before_success()
    test_a_later_bag_shrink_does_not_drag_again()
    test_same_stage_stops_after_two_failures()
    test_failed_drop_does_not_notify_or_follow()
    test_verified_drop_notifies_and_resumes_follow()
    print("ok")
