"""Single public entry for room-door open / cross / recover."""
from __future__ import annotations

from typing import Optional

from app._04_decision.door_navigation.log import log_door_event, result_stats
from app._04_decision.door_navigation.snapshot import (
    door_on_guide,
    find_door_at,
    parse_doors,
    seal_tiles,
    tile_past_door,
)
from app._04_decision.door_navigation.types import (
    CROSS_WAIT_S,
    MATCH_RADIUS,
    MAX_OPEN_CLICKS,
    MAX_PASS_CLICKS,
    MAX_RECOVERIES,
    OPEN_WAIT_S,
    UNKNOWN_WAIT_S,
    DoorNavRequest,
    DoorNavResult,
    DoorNavSession,
    DoorNavStatus,
    DoorPhase,
    DoorRecord,
    DoorState,
)

# Sync into legacy doors.py wall cache for TerrainMap.is_walkable.
_LAST_SEALS: frozenset[tuple[int, int]] = frozenset()


def handle_door_navigation(req: DoorNavRequest) -> DoorNavResult:
    """Detect, classify, open, cross, and recover room doors on one hop.

    Callers: travel / search / loot plan and the ground-click action path.
    Map-gate and floor-ladder clicks stay outside this module.
    """
    global _LAST_SEALS
    doors = parse_doors(req.snapshot)
    seals = seal_tiles(doors)
    _LAST_SEALS = seals
    _sync_legacy_cache(doors, seals)

    session = req.session
    if req.map_id is not None:
        session.map_id = int(req.map_id)

    if req.event == "note_open":
        return _note_open(req, doors, seals)
    if req.event == "note_pass":
        return _note_pass(req, doors, seals)

    guide = [(int(x), int(y)) for x, y in req.guide]
    start = (int(req.start[0]), int(req.start[1]))
    click = (
        None
        if req.planned_click is None
        else (int(req.planned_click[0]), int(req.planned_click[1]))
    )

    if session.phase is not DoorPhase.IDLE and session.door_tile is not None:
        active = find_door_at(doors, session.door_tile, radius=MATCH_RADIUS)
        return _continue_session(req, doors, seals, active, guide, start, click)

    door = door_on_guide(doors, guide, start, click, radius=0)
    if door is None and click is not None:
        door = door_on_guide(doors, guide, start, click, radius=MATCH_RADIUS)

    if door is None:
        # Suspected doorway: hop lands on a door tile that left the snapshot.
        if click is not None and _looks_like_doorway(guide, start, click):
            return _finish(
                DoorNavResult(
                    status=DoorNavStatus.NOT_FOUND,
                    door_state=DoorState.NOT_FOUND,
                    seal_tiles=seals,
                    reason="door missing on guide hop",
                    replace_click=True,
                ),
                None,
                req,
                log=True,
            )
        return DoorNavResult(status=DoorNavStatus.NONE, seal_tiles=seals, reason="no door")

    return _begin_or_decide(req, doors, seals, door, guide, start, click)


def sealed_nav_tiles() -> frozenset[tuple[int, int]]:
    """Absolute nav tiles currently sealed by live not_permitted doors."""
    return _LAST_SEALS


def session_from_blackboard(blackboard: object) -> DoorNavSession:
    """Per-bot session stored on the decision blackboard scratch."""
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        session = DoorNavSession()
        return session
    raw = scratch.get("door_nav_session")
    if isinstance(raw, DoorNavSession):
        return raw
    session = DoorNavSession()
    scratch["door_nav_session"] = session
    return session


def clear_session(blackboard: object) -> None:
    session = session_from_blackboard(blackboard)
    session.clear()


def _begin_or_decide(
    req: DoorNavRequest,
    doors: list[DoorRecord],
    seals: frozenset[tuple[int, int]],
    door: DoorRecord,
    guide: list[tuple[int, int]],
    start: tuple[int, int],
    click: tuple[int, int] | None,
) -> DoorNavResult:
    session = req.session
    past = tile_past_door(guide, door.tile, doors)

    if door.state is DoorState.NOT_PERMITTED:
        session.clear()
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.SEALED,
                door_tile=door.tile,
                door_state=door.state,
                seal_tiles=seals,
                reason="not_permitted",
                replace_click=True,
            ),
            door,
            req,
            log=True,
        )

    if door.state is DoorState.OPEN:
        if past is None:
            return _finish(
                DoorNavResult(
                    status=DoorNavStatus.FAILED,
                    door_tile=door.tile,
                    door_state=door.state,
                    seal_tiles=seals,
                    reason="open door has no tile past doorway",
                    replace_click=True,
                ),
                door,
                req,
                log=True,
            )
        if not _within_hop(start, past, req.max_hop, door.tile):
            return _finish(
                DoorNavResult(
                    status=DoorNavStatus.FAILED,
                    door_tile=door.tile,
                    pass_tile=past,
                    door_state=door.state,
                    seal_tiles=seals,
                    reason="open door past doorway not clickable",
                    replace_click=True,
                ),
                door,
                req,
                log=True,
            )
        # Already open (us or a party member): never click the door.
        session.phase = DoorPhase.CROSSING
        session.door_tile = door.tile
        session.door_ent = door.ent
        session.pass_tile = past
        session.last_state = door.state
        session.phase_since = float(req.now)
        session.last_player = start
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.PASS_NOW,
                door_tile=door.tile,
                pass_tile=past,
                door_state=door.state,
                seal_tiles=seals,
                reason="door open, click past doorway",
                replace_click=True,
            ),
            door,
            req,
            log=True,
        )

    if door.state is DoorState.CLOSED:
        if req.event == "plan":
            # Planner keeps hop aimed at / past the door; action opens it.
            return DoorNavResult(
                status=DoorNavStatus.NONE,
                door_tile=door.tile,
                door_state=door.state,
                seal_tiles=seals,
                reason="closed door deferred to act",
            )
        session.phase = DoorPhase.OPENING
        session.door_tile = door.tile
        session.door_ent = door.ent
        session.pass_tile = past
        session.last_state = door.state
        session.phase_since = float(req.now)
        session.last_player = start
        if session.open_clicks >= MAX_OPEN_CLICKS:
            return _recover_or_fail(req, doors, seals, door, "open click budget")
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.OPEN_NOW,
                door_tile=door.tile,
                pass_tile=past,
                door_state=door.state,
                seal_tiles=seals,
                reason="closed door, open once",
            ),
            door,
            req,
            log=True,
        )

    # UNKNOWN
    if req.event == "plan":
        return DoorNavResult(
            status=DoorNavStatus.NONE,
            door_tile=door.tile,
            door_state=DoorState.UNKNOWN,
            seal_tiles=seals,
            reason="unknown door deferred to act",
        )
    session.phase = DoorPhase.RECOVERING
    session.door_tile = door.tile
    session.door_ent = door.ent
    session.pass_tile = past
    session.last_state = DoorState.UNKNOWN
    session.phase_since = float(req.now)
    session.last_player = start
    return _finish(
        DoorNavResult(
            status=DoorNavStatus.UNKNOWN,
            door_tile=door.tile,
            pass_tile=past,
            door_state=DoorState.UNKNOWN,
            seal_tiles=seals,
            reason="unknown door, refresh snapshot",
            replace_click=True,
        ),
        door,
        req,
        log=True,
    )


def _continue_session(
    req: DoorNavRequest,
    doors: list[DoorRecord],
    seals: frozenset[tuple[int, int]],
    active: Optional[DoorRecord],
    guide: list[tuple[int, int]],
    start: tuple[int, int],
    click: tuple[int, int] | None,
) -> DoorNavResult:
    session = req.session
    door_tile = session.door_tile
    assert door_tile is not None

    if active is None:
        if session.phase is DoorPhase.CROSSING and _player_past(start, door_tile, session.pass_tile):
            return _mark_crossed(req, seals, None)
        if float(req.now) - float(session.phase_since) >= UNKNOWN_WAIT_S:
            return _recover_or_fail(req, doors, seals, None, "door left snapshot")
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.NOT_FOUND,
                door_tile=door_tile,
                pass_tile=session.pass_tile,
                door_state=DoorState.NOT_FOUND,
                seal_tiles=seals,
                reason="door missing mid-session",
                replace_click=True,
            ),
            None,
            req,
            log=True,
        )

    session.last_state = active.state
    past = session.pass_tile or tile_past_door(guide, active.tile, doors)
    session.pass_tile = past

    if active.state is DoorState.NOT_PERMITTED:
        session.clear()
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.SEALED,
                door_tile=active.tile,
                door_state=active.state,
                seal_tiles=seals,
                reason="became not_permitted",
                replace_click=True,
            ),
            active,
            req,
            log=True,
        )

    if session.phase is DoorPhase.OPENING:
        if active.state is DoorState.OPEN:
            session.phase = DoorPhase.CROSSING
            session.phase_since = float(req.now)
            if past is None:
                return _recover_or_fail(req, doors, seals, active, "opened but no pass tile")
            return _finish(
                DoorNavResult(
                    status=DoorNavStatus.PASS_NOW,
                    door_tile=active.tile,
                    pass_tile=past,
                    door_state=active.state,
                    seal_tiles=seals,
                    reason="opened, cross now",
                    replace_click=True,
                ),
                active,
                req,
                log=True,
            )
        if active.state is DoorState.CLOSED:
            if float(req.now) - float(session.phase_since) >= OPEN_WAIT_S:
                if session.open_clicks >= MAX_OPEN_CLICKS:
                    return _recover_or_fail(req, doors, seals, active, "still closed after opens")
                if req.event == "act":
                    return _finish(
                        DoorNavResult(
                            status=DoorNavStatus.OPEN_NOW,
                            door_tile=active.tile,
                            pass_tile=past,
                            door_state=active.state,
                            seal_tiles=seals,
                            reason="retry open",
                        ),
                        active,
                        req,
                        log=True,
                    )
            return _finish(
                DoorNavResult(
                    status=DoorNavStatus.WAIT_OPEN,
                    door_tile=active.tile,
                    pass_tile=past,
                    door_state=active.state,
                    seal_tiles=seals,
                    reason="waiting for open state",
                    replace_click=True,
                ),
                active,
                req,
                log=False,
            )
        if float(req.now) - float(session.phase_since) >= UNKNOWN_WAIT_S:
            return _recover_or_fail(req, doors, seals, active, "unknown while opening")
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.UNKNOWN,
                door_tile=active.tile,
                pass_tile=past,
                door_state=DoorState.UNKNOWN,
                seal_tiles=seals,
                reason="unknown while opening",
                replace_click=True,
            ),
            active,
            req,
            log=False,
        )

    if session.phase is DoorPhase.CROSSING:
        if _player_past(start, door_tile, past):
            return _mark_crossed(req, seals, active)
        if active.state is DoorState.CLOSED:
            # Someone (or a laggy reclick) shut it — reopen without infinite loop.
            session.phase = DoorPhase.OPENING
            session.phase_since = float(req.now)
            session.opened_by_us = False
            if session.open_clicks >= MAX_OPEN_CLICKS:
                return _recover_or_fail(req, doors, seals, active, "shut during cross")
            if req.event == "act":
                return _finish(
                    DoorNavResult(
                        status=DoorNavStatus.OPEN_NOW,
                        door_tile=active.tile,
                        pass_tile=past,
                        door_state=active.state,
                        seal_tiles=seals,
                        reason="reopen after close mid-cross",
                    ),
                    active,
                    req,
                    log=True,
                )
            return _finish(
                DoorNavResult(
                    status=DoorNavStatus.WAIT_OPEN,
                    door_tile=active.tile,
                    pass_tile=past,
                    door_state=active.state,
                    seal_tiles=seals,
                    reason="closed mid-cross",
                    replace_click=True,
                ),
                active,
                req,
                log=True,
            )
        if past is None:
            return _recover_or_fail(req, doors, seals, active, "no pass tile while crossing")
        if session.pass_clicks >= MAX_PASS_CLICKS:
            return _recover_or_fail(req, doors, seals, active, "pass click budget")
        if float(req.now) - float(session.phase_since) >= CROSS_WAIT_S and start == session.last_player:
            session.stuck_clicks += 1
            if session.stuck_clicks >= 2:
                return _recover_or_fail(req, doors, seals, active, "stuck before doorway")
        session.last_player = start
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.PASS_NOW if req.event == "act" else DoorNavStatus.WAIT_CROSS,
                door_tile=active.tile,
                pass_tile=past,
                door_state=active.state,
                seal_tiles=seals,
                reason="crossing",
                replace_click=True,
            ),
            active,
            req,
            log=False,
        )

    if session.phase is DoorPhase.RECOVERING:
        if active.state is DoorState.OPEN:
            session.phase = DoorPhase.CROSSING
            session.phase_since = float(req.now)
            return _continue_session(req, doors, seals, active, guide, start, click)
        if active.state is DoorState.CLOSED and req.event == "act":
            session.phase = DoorPhase.OPENING
            session.phase_since = float(req.now)
            return _continue_session(req, doors, seals, active, guide, start, click)
        if float(req.now) - float(session.phase_since) >= UNKNOWN_WAIT_S:
            return _recover_or_fail(req, doors, seals, active, "recovery timeout")
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.UNKNOWN,
                door_tile=active.tile,
                pass_tile=past,
                door_state=active.state,
                seal_tiles=seals,
                reason="recovering",
                replace_click=True,
            ),
            active,
            req,
            log=False,
        )

    session.clear()
    return DoorNavResult(status=DoorNavStatus.NONE, seal_tiles=seals, reason="idle")


def _note_open(
    req: DoorNavRequest,
    doors: list[DoorRecord],
    seals: frozenset[tuple[int, int]],
) -> DoorNavResult:
    session = req.session
    session.open_clicks += 1
    session.opened_by_us = bool(req.opened)
    session.phase = DoorPhase.OPENING
    session.phase_since = float(req.now)
    door = None
    if session.door_tile is not None:
        door = find_door_at(doors, session.door_tile, radius=MATCH_RADIUS)
    log_door_event(
        status=DoorNavStatus.WAIT_OPEN,
        door=door,
        player=req.start,
        pass_tile=session.pass_tile,
        map_id=session.map_id,
        reason="open click issued",
        retry=session.open_clicks,
    )
    return DoorNavResult(
        status=DoorNavStatus.WAIT_OPEN,
        door_tile=session.door_tile,
        pass_tile=session.pass_tile,
        door_state=door.state if door else DoorState.UNKNOWN,
        seal_tiles=seals,
        reason="open click issued",
        replace_click=True,
    )


def _note_pass(
    req: DoorNavRequest,
    doors: list[DoorRecord],
    seals: frozenset[tuple[int, int]],
) -> DoorNavResult:
    session = req.session
    session.pass_clicks += 1
    session.phase = DoorPhase.CROSSING
    if session.phase_since <= 0.0:
        session.phase_since = float(req.now)
    pose = req.passed_pose or req.start
    session.last_player = (int(pose[0]), int(pose[1]))
    door = None
    if session.door_tile is not None:
        door = find_door_at(doors, session.door_tile, radius=MATCH_RADIUS)
        if door is not None and _player_past(session.last_player, session.door_tile, session.pass_tile):
            return _mark_crossed(req, seals, door)
    return DoorNavResult(
        status=DoorNavStatus.WAIT_CROSS,
        door_tile=session.door_tile,
        pass_tile=session.pass_tile,
        door_state=door.state if door else session.last_state,
        seal_tiles=seals,
        reason="pass click issued",
        replace_click=True,
    )


def _mark_crossed(
    req: DoorNavRequest,
    seals: frozenset[tuple[int, int]],
    door: Optional[DoorRecord],
) -> DoorNavResult:
    session = req.session
    tile = session.door_tile
    past = session.pass_tile
    result = DoorNavResult(
        status=DoorNavStatus.CROSSED,
        door_tile=tile,
        pass_tile=past,
        door_state=door.state if door else DoorState.OPEN,
        seal_tiles=seals,
        reason="crossed doorway",
    )
    log_door_event(
        status=DoorNavStatus.CROSSED,
        door=door,
        player=req.start,
        pass_tile=past,
        map_id=session.map_id,
        reason="crossed doorway",
        retry=session.pass_clicks,
    )
    session.clear()
    result.stats = result_stats(result, door, map_id=req.map_id)
    return result


def _recover_or_fail(
    req: DoorNavRequest,
    doors: list[DoorRecord],
    seals: frozenset[tuple[int, int]],
    door: Optional[DoorRecord],
    reason: str,
) -> DoorNavResult:
    session = req.session
    session.recoveries += 1
    session.phase = DoorPhase.RECOVERING
    session.phase_since = float(req.now)
    if session.recoveries > MAX_RECOVERIES:
        tile = session.door_tile
        session.clear()
        return _finish(
            DoorNavResult(
                status=DoorNavStatus.FAILED,
                door_tile=tile,
                door_state=door.state if door else DoorState.UNKNOWN,
                seal_tiles=seals,
                reason=f"recovery exhausted: {reason}",
                replace_click=True,
            ),
            door,
            req,
            log=True,
        )
    log_door_event(
        status=DoorNavStatus.UNKNOWN,
        door=door,
        player=req.start,
        pass_tile=session.pass_tile,
        map_id=session.map_id,
        reason=f"recover: {reason}",
        retry=session.recoveries,
    )
    return DoorNavResult(
        status=DoorNavStatus.UNKNOWN,
        door_tile=session.door_tile,
        pass_tile=session.pass_tile,
        door_state=door.state if door else DoorState.UNKNOWN,
        seal_tiles=seals,
        reason=f"recover: {reason}",
        replace_click=True,
    )


def _finish(
    result: DoorNavResult,
    door: Optional[DoorRecord],
    req: DoorNavRequest,
    *,
    log: bool,
) -> DoorNavResult:
    result.stats = result_stats(result, door, map_id=req.map_id or req.session.map_id)
    if log:
        log_door_event(
            status=result.status,
            door=door,
            player=req.start,
            pass_tile=result.pass_tile,
            map_id=req.map_id or req.session.map_id,
            reason=result.reason,
            retry=req.session.recoveries + req.session.open_clicks,
        )
    return result


def _within_hop(
    start: tuple[int, int],
    tile: tuple[int, int],
    max_hop: Optional[int],
    door_tile: tuple[int, int],
) -> bool:
    if max_hop is None:
        return True
    dist = max(abs(tile[0] - start[0]), abs(tile[1] - start[1]))
    # Same allowance as retarget_open_door: one step past the door may exceed hop.
    door_dist = max(abs(door_tile[0] - start[0]), abs(door_tile[1] - start[1]))
    return dist <= int(max_hop) or dist <= door_dist + 1


def _player_past(
    player: tuple[int, int],
    door: tuple[int, int],
    pass_tile: Optional[tuple[int, int]],
) -> bool:
    if pass_tile is None:
        return False
    # Past when on/after the pass tile relative to the door.
    px, py = int(player[0]), int(player[1])
    if (px, py) == (int(pass_tile[0]), int(pass_tile[1])):
        return True
    dx = int(pass_tile[0]) - int(door[0])
    dy = int(pass_tile[1]) - int(door[1])
    sx = 0 if dx == 0 else (1 if dx > 0 else -1)
    sy = 0 if dy == 0 else (1 if dy > 0 else -1)
    from_door_x = px - int(door[0])
    from_door_y = py - int(door[1])
    if sx != 0 and from_door_x * sx > 0:
        return True
    if sy != 0 and from_door_y * sy > 0:
        return True
    return False


def _looks_like_doorway(
    guide: list[tuple[int, int]],
    start: tuple[int, int],
    click: tuple[int, int],
) -> bool:
    """True when the hop stops abruptly on a corridor cell (legacy soft signal)."""
    del guide, start, click
    return False


def _sync_legacy_cache(doors: list[DoorRecord], seals: frozenset[tuple[int, int]]) -> None:
    """Keep ``doors.py`` wall / state helpers consistent for TerrainMap."""
    try:
        from app._04_decision import doors as legacy

        legacy._DOORS = tuple((d.tile[0], d.tile[1], d.state.value) for d in doors)
        legacy._WALLS = seals
    except Exception:
        pass
