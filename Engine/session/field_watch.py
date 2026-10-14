"""Idle field view: read player pose and nearby entities without the bot loop.

The debug field view normally paints the worker snapshot. While the bot is
stopped that snapshot is empty or leftover, so this watcher polls player
memory and print_state on its own thread and returns the same navigation /
world shape the view already consumes. It does not decide, click, or move.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from session.debug_snapshot import (
    _abs_to_nav_xy,
    _live_pose_debug,
    _resolve_display_pack,
)


def field_frame_from_snapshots(
    *,
    player: Any,
    print_state: Any,
    profile: Any,
) -> dict[str, Any]:
    """Navigation origin and monster/item rows for the field view."""
    world = type(
        "_FieldPose",
        (),
        {
            "last_memory_snapshot": player if isinstance(player, dict) else None,
            "last_print_state": print_state if isinstance(print_state, dict) else None,
        },
    )()
    map_id, abs_xy = _live_pose_debug(world)
    pack = _resolve_display_pack(live_map_id=map_id, profile=profile)
    origin = None
    if abs_xy is not None and pack:
        origin = _abs_to_nav_xy(pack, int(abs_xy[0]), int(abs_xy[1]))
    navigation: dict[str, Any] = {
        "live_map_id": map_id,
        "live_pack": pack,
        "display_map": pack,
        "live_abs_xy": list(abs_xy) if abs_xy else None,
        "live_origin_xy": list(origin) if origin else None,
        "origin_xy": list(origin) if origin else None,
    }
    return {
        "navigation": navigation,
        "world": {"objects": _field_objects(print_state)},
    }


def _field_objects(print_state: Any) -> list[dict[str, Any]]:
    if not isinstance(print_state, dict):
        return []
    from app._03_world.merge.memory_entities import entities_to_handoff

    objects: list[dict[str, Any]] = []
    for row in entities_to_handoff(print_state):
        kind = str(row.get("classification") or "")
        if kind not in ("monster", "item"):
            continue
        objects.append(
            {
                "type": kind,
                "rx": row.get("world_rx"),
                "ry": row.get("world_ry"),
                "bait": bool(row.get("bait")),
                "dead": False,
                "missed": int(row.get("frames_lost") or 0),
            }
        )
    return objects


def read_field_frame(profile: Any) -> dict[str, Any]:
    """One live memory read. Safe to call only while the bot worker is idle."""
    from app._01_perception.sensors import shared_sensors

    buf = shared_sensors().capture_field()
    player = buf.player if isinstance(buf.player, dict) else None
    print_state = buf.print_state if isinstance(buf.print_state, dict) else None
    return field_frame_from_snapshots(
        player=player,
        print_state=print_state,
        profile=profile,
    )


class FieldWatch:
    """Background poller. ``idle`` is true when the bot is not publishing."""

    def __init__(
        self,
        *,
        profile_of: Callable[[], Any],
        idle: Callable[[], bool],
    ) -> None:
        self._profile_of = profile_of
        self._idle = idle
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._frame: dict[str, Any] | None = None

    def ensure_running(self) -> None:
        self._stop.clear()
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="field-watch",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._frame

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._idle():
                with self._lock:
                    self._frame = None
                self._stop.wait(0.1)
                continue
            frame: dict[str, Any] | None
            try:
                frame = read_field_frame(self._profile_of())
            except Exception:
                frame = None
            if self._stop.is_set() or not self._idle():
                with self._lock:
                    self._frame = None
            else:
                with self._lock:
                    self._frame = frame
            self._stop.wait(0.12)
        with self._lock:
            self._frame = None
