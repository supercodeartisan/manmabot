"""Party assist keeps its chosen id and reuses the solo shot gate."""
from __future__ import annotations

import logging

from app._02_state.enums import ActionType
from app._02_state.geometry import WorldOrigin
from app._02_state.objects import ObjectStatus, ObjectType, Position, WorldObject
from app._03_world.space.terrain_map import get_terrain_map, set_terrain_map
from app._06_party import assist as assist_mod
from app._06_party.intents import intent_for_kind
from app._06_party.policy import MemberKind


class _Terrain:
    has_edge_fences = False

    def __init__(self, blocked: set[tuple[int, int]] | None = None) -> None:
        self.blocked = blocked or set()

    def is_walkable(self, x: int, y: int) -> bool:
        return (int(x), int(y)) not in self.blocked


class _State:
    def __init__(self, obj: WorldObject | None) -> None:
        self.obj = obj
        self.last_print_state = {"entities": []}

    def get_object(self, tid: int):
        if self.obj is not None and int(self.obj.track_id) == int(tid):
            return self.obj
        return None

    def missing_frames(self, tid: int) -> int:
        return 0


def _mob(tid: int, x: int, y: int, *, on_screen: bool = True, dead: bool = False) -> WorldObject:
    return WorldObject(
        track_id=tid,
        object_type=ObjectType.MONSTER,
        position=Position(0.5, 0.5) if on_screen else Position(1.5, 1.5),
        status=ObjectStatus.DEAD if dead else ObjectStatus.ALIVE,
        world_cx=x,
        world_cy=y,
    )


def _hold_logs() -> tuple[logging.Logger, logging.Handler, list[str]]:
    found: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            found.append(record.getMessage())

    log = logging.getLogger("manmabot.combat")
    handler = _Grab()
    handler.setLevel(logging.INFO)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log, handler, found


def _reset() -> None:
    assist_mod._assist_block_log_key = None


def test_open_ground_keeps_the_party_id() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain())
    try:
        _reset()
        state = _State(_mob(4955, 2, 0))
        ok, why = assist_mod.assist_shot_gate(
            state,
            WorldOrigin(0, 0),
            4955,
            source="assist src=leader_attack",
        )
        assert ok and why == ""
        intent, _goal, detail = intent_for_kind(
            MemberKind.ASSIST,
            reason="assist src=leader_attack",
            game_state=state,
            origin=WorldOrigin(0, 0),
            assist_id=4955,
            mid_act=True,
        )
        assert intent.action is ActionType.ATTACK
        assert intent.target_id == 4955
        assert intent.mid_act is True
        assert detail == "assist src=leader_attack"
    finally:
        set_terrain_map(previous)


def test_inn_wall_blocks_the_click_and_keeps_the_id() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain({(1, 0)}))
    try:
        _reset()
        state = _State(_mob(4955, 2, 0))
        ok, why = assist_mod.assist_shot_gate(
            state,
            WorldOrigin(0, 0),
            4955,
            source="assist dist=13 src=leader_strike",
        )
        assert not ok
        assert why == "assist_blocked id=4955 src=leader_strike reason=black_cell"
        assert "4958" not in why
        intent, goal, detail = intent_for_kind(
            MemberKind.ASSIST,
            reason="assist dist=13 src=leader_strike",
            game_state=state,
            origin=WorldOrigin(0, 0),
            assist_id=4955,
        )
        assert intent.action is ActionType.IDLE
        assert intent.target_id is None
        assert goal is None
        assert detail == why
    finally:
        set_terrain_map(previous)


def test_open_door_matches_the_solo_line() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain())
    try:
        _reset()
        state = _State(_mob(7, 3, 0))
        ok, why = assist_mod.assist_shot_gate(
            state, WorldOrigin(0, 0), 7, source="assist src=external"
        )
        assert ok and why == ""
    finally:
        set_terrain_map(previous)


def test_moving_onto_a_closed_line_stops_the_shot() -> None:
    previous = get_terrain_map()
    terrain = _Terrain()
    set_terrain_map(terrain)
    try:
        _reset()
        state = _State(_mob(4955, 2, 0))
        origin = WorldOrigin(0, 0)
        ok, _why = assist_mod.assist_shot_gate(
            state, origin, 4955, source="assist src=own_finish"
        )
        assert ok
        terrain.blocked.add((1, 0))
        ok, why = assist_mod.assist_shot_gate(
            state, origin, 4955, source="assist src=own_finish"
        )
        assert not ok
        assert "reason=black_cell" in why
        assert "src=own_finish" in why
    finally:
        set_terrain_map(previous)


def test_clearing_the_wall_uses_the_same_id() -> None:
    previous = get_terrain_map()
    terrain = _Terrain({(1, 0)})
    set_terrain_map(terrain)
    try:
        _reset()
        state = _State(_mob(4955, 2, 0))
        origin = WorldOrigin(0, 0)
        ok, _why = assist_mod.assist_shot_gate(
            state, origin, 4955, source="assist src=leader_attack"
        )
        assert not ok
        terrain.blocked.clear()
        ok, why = assist_mod.assist_shot_gate(
            state, origin, 4955, source="assist src=leader_attack"
        )
        assert ok and why == ""
    finally:
        set_terrain_map(previous)


def test_click_range_is_not_treated_as_a_wall() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain())
    try:
        _reset()
        state = _State(_mob(9, 20, 0, on_screen=False))
        ok, why = assist_mod.assist_shot_gate(
            state, WorldOrigin(0, 0), 9, source="assist src=leader_strike"
        )
        assert not ok
        assert why.endswith("reason=range")
        assert "black_cell" not in why
    finally:
        set_terrain_map(previous)


def test_dead_and_missing_do_not_substitute_another_id() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain())
    try:
        _reset()
        dead = _State(_mob(4955, 2, 0, dead=True))
        ok, why = assist_mod.assist_shot_gate(
            dead, WorldOrigin(0, 0), 4955, source="assist src=external"
        )
        assert not ok and why.endswith("reason=dead")
        missing = _State(None)
        ok, why = assist_mod.assist_shot_gate(
            missing, WorldOrigin(0, 0), 4955, source="assist src=external"
        )
        assert not ok and why.endswith("reason=missing")
        assert "4958" not in why
    finally:
        set_terrain_map(previous)


def test_repeat_block_logs_once() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain({(1, 0)}))
    log, handler, found = _hold_logs()
    try:
        _reset()
        state = _State(_mob(4955, 2, 0))
        origin = WorldOrigin(0, 0)
        assist_mod.assist_shot_gate(
            state, origin, 4955, source="assist src=leader_strike"
        )
        assist_mod.assist_shot_gate(
            state, origin, 4955, source="assist src=leader_strike"
        )
        holds = [line for line in found if "party assist hold" in line]
        assert len(holds) == 1
        assert "id=4955" in holds[0]
        assert "src=leader_strike" in holds[0]
        assert "P=(0,0)" in holds[0]
        assert "M=(2,0)" in holds[0]
        assert "block=(1,0)" in holds[0]
    finally:
        log.removeHandler(handler)
        set_terrain_map(previous)


def test_gate_does_not_call_list_attackable() -> None:
    import app._04_decision.combat_query as combat_query

    previous = get_terrain_map()
    set_terrain_map(_Terrain())
    real = combat_query.list_attackable

    def _boom(*_args, **_kwargs):
        raise AssertionError("list_attackable")

    combat_query.list_attackable = _boom
    try:
        _reset()
        state = _State(_mob(4955, 2, 0))
        ok, why = assist_mod.assist_shot_gate(
            state, WorldOrigin(0, 0), 4955, source="assist src=leader_attack"
        )
        assert ok and why == ""
    finally:
        combat_query.list_attackable = real
        set_terrain_map(previous)


def test_defend_still_emits_its_own_attack() -> None:
    previous = get_terrain_map()
    set_terrain_map(_Terrain({(1, 0)}))
    try:
        intent, _goal, detail = intent_for_kind(
            MemberKind.DEFEND,
            reason="defend_self",
            game_state=_State(_mob(3, 2, 0)),
            origin=WorldOrigin(0, 0),
            defend_id=3,
        )
        assert intent.action is ActionType.ATTACK
        assert intent.target_id == 3
        assert detail == "defend_self"
    finally:
        set_terrain_map(previous)


if __name__ == "__main__":
    test_open_ground_keeps_the_party_id()
    test_inn_wall_blocks_the_click_and_keeps_the_id()
    test_open_door_matches_the_solo_line()
    test_moving_onto_a_closed_line_stops_the_shot()
    test_clearing_the_wall_uses_the_same_id()
    test_click_range_is_not_treated_as_a_wall()
    test_dead_and_missing_do_not_substitute_another_id()
    test_repeat_block_logs_once()
    test_gate_does_not_call_list_attackable()
    test_defend_still_emits_its_own_attack()
    print("OK")
