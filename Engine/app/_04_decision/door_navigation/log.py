"""Structured door-navigation diagnostics."""
from __future__ import annotations

from typing import Any, Optional

from app._04_decision.door_navigation.types import (
    DOOR_STATE_OFF,
    DoorNavResult,
    DoorNavStatus,
    DoorRecord,
    DoorState,
)


def log_door_event(
    *,
    status: DoorNavStatus | str,
    door: Optional[DoorRecord] = None,
    player: Optional[tuple[int, int]] = None,
    pass_tile: Optional[tuple[int, int]] = None,
    map_id: Optional[int] = None,
    reason: str = "",
    retry: int = 0,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """One travel log line for a door transition."""
    try:
        from app.bot_log import event
    except Exception:
        return
    tile = door.tile if door is not None else None
    world = door.world if door is not None else None
    state = door.state.value if door is not None else DoorState.NOT_FOUND.value
    gfx = None if door is None else door.gfx
    frame = None if door is None else door.frame
    ent = "" if door is None else door.ent
    payload = {
        "map": map_id if map_id is not None else "-",
        "ent": ent or "-",
        "world": world if world is not None else "-",
        "nav": tile if tile is not None else "-",
        "state": state,
        "gfx": f"0x{gfx:X}" if isinstance(gfx, int) else "-",
        "frame": f"0x{frame:X}" if isinstance(frame, int) else "-",
        "off": f"0x{DOOR_STATE_OFF:X}",
        "player": player if player is not None else "-",
        "pass": pass_tile if pass_tile is not None else "-",
        "retry": int(retry),
        "status": status.value if isinstance(status, DoorNavStatus) else str(status),
        "reason": reason or "-",
    }
    if extra:
        payload.update(extra)
    event(
        "travel",
        "door nav map=%s ent=%s world=%s nav=%s state=%s gfx=%s frame=%s "
        "off=%s player=%s pass=%s retry=%s status=%s reason=%s",
        payload["map"],
        payload["ent"],
        payload["world"],
        payload["nav"],
        payload["state"],
        payload["gfx"],
        payload["frame"],
        payload["off"],
        payload["player"],
        payload["pass"],
        payload["retry"],
        payload["status"],
        payload["reason"],
    )


def result_stats(
    result: DoorNavResult,
    door: Optional[DoorRecord],
    *,
    map_id: Optional[int] = None,
) -> dict[str, Any]:
    stats = dict(result.stats)
    stats.setdefault("door", result.door_state.value)
    stats.setdefault("door_status", result.status.value)
    stats.setdefault("door_reason", result.reason or "-")
    stats.setdefault("map_id", map_id if map_id is not None else "-")
    stats.setdefault("state_off", f"0x{DOOR_STATE_OFF:X}")
    if door is not None:
        stats.setdefault("door_nav", door.tile)
        stats.setdefault("door_world", door.world)
        stats.setdefault("door_ent", door.ent or "-")
        if door.gfx is not None:
            stats.setdefault("door_gfx", f"0x{door.gfx:X}")
        if door.frame is not None:
            stats.setdefault("door_frame", f"0x{door.frame:X}")
    return stats
