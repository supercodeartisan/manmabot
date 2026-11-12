"""A schedule walk finishes on its own tile. A supply pile is not that tile."""
from __future__ import annotations

from types import SimpleNamespace

from app._04_decision.behavior_tree import Status
from app._04_decision.world_nav.session import WorldNavSession


def _step():
    return SimpleNamespace(detail={"to": {"mapId": 0, "x": 32626, "y": 33150}})


def _pose(x: int, y: int):
    return SimpleNamespace(map_id=0, x=x, y=y)


def _board(goal, ox: int, oy: int):
    return SimpleNamespace(
        nav_goal=goal,
        world_origin=SimpleNamespace(x=ox, y=oy),
        scratch={},
        intent=None,
    )


def _session():
    session = WorldNavSession()
    session.walk_nav = (370, 446)
    session.plan = SimpleNamespace(steps=[_step()])
    calls = {"start": 0, "finish": 0}

    def start(*_args, **kwargs):
        calls["start"] += 1
        calls["wait_for_land"] = kwargs.get("wait_for_land")
        return "started"

    def finish(*_args, **_kwargs):
        calls["finish"] += 1
        return "finished"

    session._start_walk = start  # type: ignore[method-assign]
    session._finish_walk_step = finish  # type: ignore[method-assign]
    return session, calls


def test_an_empty_goal_restarts_the_walk() -> None:
    session, calls = _session()
    got = session._tick_walk(_step(), _pose(32558, 33089), _board(None, 302, 385), None)
    assert got == "started"
    assert calls["finish"] == 0
    assert calls["wait_for_land"] is False


def test_a_pickup_tile_restarts_the_walk() -> None:
    session, calls = _session()
    got = session._tick_walk(
        _step(),
        _pose(32558, 33089),
        _board((304, 384), 304, 385),
        None,
    )
    assert got == "started"
    assert calls["finish"] == 0
    assert calls["wait_for_land"] is False


def test_the_body_on_the_planned_cell_finishes() -> None:
    session, calls = _session()
    got = session._tick_walk(
        _step(),
        _pose(32626, 33150),
        _board(None, 302, 385),
        None,
    )
    assert got == "finished"
    assert calls["start"] == 0


def test_the_snapped_walk_tile_still_finishes() -> None:
    session, calls = _session()
    session.walk_nav = (304, 384)
    got = session._tick_walk(
        _step(),
        _pose(32558, 33089),
        _board((304, 384), 304, 384),
        None,
    )
    assert got == "finished"
    assert calls["start"] == 0


def _land_step():
    return SimpleNamespace(
        op="walk",
        detail={
            "from": {"mapId": 0, "x": 32491, "y": 33061},
            "to": {"mapId": 0, "x": 32513, "y": 33029},
        },
    )


def _land_board():
    reasons: list[str] = []

    def emit(*_args, **kwargs):
        reasons.append(str(kwargs.get("reason") or ""))

    board = SimpleNamespace(
        nav_goal=None,
        world_origin=SimpleNamespace(x=256, y=332),
        scratch={},
        intent=None,
        current_goal=None,
        travel_purpose=None,
        emit=emit,
    )
    return board, reasons


def test_a_first_walk_waits_until_xy_lands() -> None:
    session = WorldNavSession()
    session.phase = "ready"
    board, reasons = _land_board()
    # 25 tiles east of the step's start cell, on the destination map.
    pose = SimpleNamespace(map_id=0, x=32516, y=33061)
    got = session._start_walk(_land_step(), pose, board, None)
    assert got == Status.SUCCESS
    assert reasons == ["world nav wait land xy"]
    assert session.phase == "ready"


def test_an_open_walk_does_not_wait_on_the_old_start_cell(monkeypatch) -> None:
    session = WorldNavSession()
    session.phase = "walk"
    step = _land_step()
    session.plan = SimpleNamespace(steps=[step])
    board, reasons = _land_board()
    pose = SimpleNamespace(map_id=0, x=32516, y=33061)
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.pack_ids.map_id_to_pack_id",
        lambda _map_id: None,
    )
    got = session._start_walk(step, pose, board, None, wait_for_land=False)
    assert got == Status.FAILURE
    assert session.error == "no pack for map0"
    assert reasons == []


def test_a_hop_that_drops_the_goal_restarts_without_the_land_wait(monkeypatch) -> None:
    session, calls = _session()
    session.walk_nav = (304, 384)
    board = _board((304, 384), 300, 380)

    def emit(blackboard, **_kwargs):
        blackboard.nav_goal = None
        blackboard.scratch["travel_hop_miss"] = "no_path"
        return False

    monkeypatch.setattr(
        "app._04_decision.world_nav.session.emit_travel_hop",
        emit,
    )
    got = session._tick_walk(_step(), _pose(32558, 33089), board, None)
    assert got == "started"
    assert calls["wait_for_land"] is False
