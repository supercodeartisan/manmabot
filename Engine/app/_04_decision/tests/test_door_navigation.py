"""Door-navigation module: open, cross, recover, and no-door passthrough."""
from __future__ import annotations

from app._03_world.merge.memory_sync import configure_map_origin
from app._04_decision.door_navigation import (
    DOOR_GFX_LOCKED,
    DOOR_STATE_OFF,
    DoorNavRequest,
    DoorNavSession,
    DoorNavStatus,
    DoorPhase,
    DoorState,
    handle_door_navigation,
)
from app._04_decision.door_navigation.snapshot import parse_doors
from app._04_decision.doors import (
    refresh_live_doors,
    retarget_open_door,
    tile_sealed,
)


def _origin_f2() -> None:
    configure_map_origin(
        {"navigation": {"map_origin_x": 32576, "map_origin_y": 32704}}
    )


def _door_row(
    cx: int,
    cy: int,
    state: str,
    *,
    gfx: int | None = None,
    frame: int | None = None,
    ent: str = "0x1",
) -> dict:
    row = {
        "ent": ent,
        "class": "InteractiveNPC",
        "name": "Door",
        "species": 8,
        "door": state,
        "world": {"cx": cx, "cy": cy},
    }
    if gfx is not None:
        row["doorType"] = f"0x{gfx:X}"
    if frame is not None:
        row["doorFrame"] = f"0x{frame:X}"
    return row


def _snap(*rows: dict) -> dict:
    return {"entities": list(rows)}


def test_registry_offsets_match_module_constants() -> None:
    assert DOOR_STATE_OFF == 0xE0
    assert DOOR_GFX_LOCKED == 0xFFFFFFFF


def test_0x8009_is_not_not_permitted() -> None:
    _origin_f2()
    # Token comes from print_state; with registry policy gfx alone is not lock.
    doors = parse_doors(
        _snap(_door_row(32665, 32789, "close", gfx=0x8009, frame=0x1D))
    )
    assert len(doors) == 1
    assert doors[0].state is DoorState.CLOSED
    assert doors[0].gfx == 0x8009


def test_closed_door_open_now_on_act() -> None:
    _origin_f2()
    # nav = (89, 85) for world (32665, 32789) with F2 origin
    guide = [(87, 85), (88, 85), (89, 85), (90, 85), (91, 85)]
    snap = _snap(_door_row(32665, 32789, "close", frame=0x1D))
    session = DoorNavSession()
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=snap,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=100.0,
            event="act",
        )
    )
    assert res.status is DoorNavStatus.OPEN_NOW
    assert res.door_tile == (89, 85)
    assert res.door_state is DoorState.CLOSED


def test_open_door_pass_without_open_click() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85), (91, 85)]
    snap = _snap(_door_row(32665, 32789, "open", frame=0x1C))
    session = DoorNavSession()
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=snap,
            guide=guide,
            start=(87, 85),
            planned_click=(89, 85),
            session=session,
            now=100.0,
            event="act",
        )
    )
    assert res.status is DoorNavStatus.PASS_NOW
    assert res.pass_tile == (90, 85)
    assert res.replace_click is True


def test_unknown_holds_without_click() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    snap = _snap(_door_row(32665, 32789, "unknown"))
    session = DoorNavSession()
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=snap,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=100.0,
            event="act",
        )
    )
    assert res.status is DoorNavStatus.UNKNOWN
    assert res.replace_click is True


def test_not_found_when_no_door_and_none_status_for_clear_path() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    session = DoorNavSession()
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=_snap(),
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=100.0,
            event="act",
        )
    )
    assert res.status is DoorNavStatus.NONE


def test_coordinate_match_uses_map_origin() -> None:
    _origin_f2()
    doors = parse_doors(_snap(_door_row(32665, 32789, "close")))
    assert doors[0].tile == (32665 - 32576, 32789 - 32704)
    assert doors[0].world == (32665, 32789)


def test_open_then_cross_session() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85), (91, 85)]
    closed = _snap(_door_row(32665, 32789, "close", frame=0x1D))
    opened = _snap(_door_row(32665, 32789, "open", frame=0x1C))
    session = DoorNavSession()
    r1 = handle_door_navigation(
        DoorNavRequest(
            snapshot=closed,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=1.0,
            event="act",
        )
    )
    assert r1.status is DoorNavStatus.OPEN_NOW
    handle_door_navigation(
        DoorNavRequest(
            snapshot=closed,
            guide=guide,
            start=(87, 85),
            planned_click=(89, 85),
            session=session,
            now=1.1,
            event="note_open",
            opened=True,
        )
    )
    r2 = handle_door_navigation(
        DoorNavRequest(
            snapshot=opened,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=1.2,
            event="act",
        )
    )
    assert r2.status is DoorNavStatus.PASS_NOW
    assert r2.pass_tile == (90, 85)
    handle_door_navigation(
        DoorNavRequest(
            snapshot=opened,
            guide=guide,
            start=(90, 85),
            planned_click=(90, 85),
            session=session,
            now=1.3,
            event="note_pass",
            passed_pose=(90, 85),
        )
    )
    assert session.phase.value == "idle"


def test_failed_cross_recovery_budget() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    opened = _snap(_door_row(32665, 32789, "open", frame=0x1C))
    session = DoorNavSession()
    handle_door_navigation(
        DoorNavRequest(
            snapshot=opened,
            guide=guide,
            start=(87, 85),
            planned_click=(89, 85),
            session=session,
            now=1.0,
            event="act",
        )
    )
    session.pass_clicks = 4
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=opened,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=10.0,
            event="act",
        )
    )
    assert res.status in (DoorNavStatus.UNKNOWN, DoorNavStatus.FAILED)


def test_stale_snapshot_unknown_then_recover() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    session = DoorNavSession()
    handle_door_navigation(
        DoorNavRequest(
            snapshot=_snap(_door_row(32665, 32789, "close")),
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=1.0,
            event="act",
        )
    )
    handle_door_navigation(
        DoorNavRequest(
            snapshot=_snap(_door_row(32665, 32789, "close")),
            guide=guide,
            start=(87, 85),
            planned_click=(89, 85),
            session=session,
            now=1.1,
            event="note_open",
            opened=True,
        )
    )
    # Door vanished from snapshot while opening.
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=_snap(),
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=1.2,
            event="act",
        )
    )
    assert res.status is DoorNavStatus.NOT_FOUND


def test_retry_limits_exhaust_to_failed() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    snap = _snap(_door_row(32665, 32789, "unknown"))
    session = DoorNavSession()
    session.recoveries = 3
    session.phase = DoorPhase.RECOVERING
    session.door_tile = (89, 85)
    session.phase_since = 1.0
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=snap,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=session,
            now=5.0,
            event="act",
        )
    )
    assert res.status is DoorNavStatus.FAILED


def test_normal_movement_without_doors() -> None:
    _origin_f2()
    guide = [(10, 10), (11, 10), (12, 10)]
    session = DoorNavSession()
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=_snap(),
            guide=guide,
            start=(10, 10),
            planned_click=(12, 10),
            session=session,
            now=1.0,
            event="plan",
        )
    )
    assert res.status is DoorNavStatus.NONE
    beyond, replaced = retarget_open_door(guide, (10, 10), (12, 10), 3)
    assert replaced is False
    assert beyond == (12, 10)


def test_party_shared_open_door_never_reopens() -> None:
    """A door already open (another member) only yields PASS_NOW."""
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    snap = _snap(_door_row(32665, 32789, "open", frame=0x1C))
    for _ in range(2):
        session = DoorNavSession()
        res = handle_door_navigation(
            DoorNavRequest(
                snapshot=snap,
                guide=guide,
                start=(87, 85),
                planned_click=(89, 85),
                session=session,
                now=1.0,
                event="act",
            )
        )
        assert res.status is DoorNavStatus.PASS_NOW
        assert res.status is not DoorNavStatus.OPEN_NOW


def test_tile_past_door_and_retarget() -> None:
    _origin_f2()
    refresh_live_doors(_snap(_door_row(32665, 32789, "open")))
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    beyond, replaced = retarget_open_door(guide, (87, 85), (89, 85), 3)
    assert replaced is True
    assert beyond == (90, 85)


def test_not_permitted_seals_tile() -> None:
    _origin_f2()
    refresh_live_doors(_snap(_door_row(32665, 32789, "not_permitted")))
    assert tile_sealed(89, 85) is True


def test_talking_island_f2_nav_math() -> None:
    _origin_f2()
    # floors_entrances F2 stair cell (32665,32788) → nav relative to F2 origin
    doors = parse_doors(_snap(_door_row(32665, 32788, "close")))
    assert doors[0].tile == (89, 84)


def test_plan_defers_closed_door() -> None:
    _origin_f2()
    guide = [(87, 85), (88, 85), (89, 85), (90, 85)]
    snap = _snap(_door_row(32665, 32789, "close"))
    res = handle_door_navigation(
        DoorNavRequest(
            snapshot=snap,
            guide=guide,
            start=(87, 85),
            planned_click=(90, 85),
            session=DoorNavSession(),
            now=1.0,
            event="plan",
        )
    )
    assert res.status is DoorNavStatus.NONE
    assert res.door_state is DoorState.CLOSED
