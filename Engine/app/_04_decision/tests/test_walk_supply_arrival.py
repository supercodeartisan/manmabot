"""A schedule walk finishes on its own tile. A supply pile is not that tile."""
from __future__ import annotations

from types import SimpleNamespace

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

    def start(*_args, **_kwargs):
        calls["start"] += 1
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
