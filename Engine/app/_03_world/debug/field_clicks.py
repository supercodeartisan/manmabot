"""Recent world-relative mouse clicks for the field preview.

One entry per button click. A repeated click is one ring per press,
staggered by the same gap the mouse waits between presses.
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_CLICKS: list[tuple[float, float, float]] = []  # start time, rx, ry
_KEEP_S = 1.2


def note_clicks(rx: float, ry: float, count: int, *, interval: float = 0.1) -> None:
    """Record ``count`` clicks at relative tile ``(rx, ry)``."""
    n = int(count)
    if n <= 0:
        return
    now = time.time()
    gap = max(0.0, float(interval))
    with _LOCK:
        for i in range(n):
            _CLICKS.append((now + i * gap, float(rx), float(ry)))
        _prune(now)


def note_screen_click(px: float, py: float, bounds, count: int) -> None:
    """Convert a desktop click inside the game client into a relative tile."""
    if bounds is None or not getattr(bounds, "valid", False):
        return
    width = float(bounds.width)
    height = float(bounds.height)
    if width <= 0 or height <= 0:
        return
    nx = (float(px) - float(bounds.left)) / width
    ny = (float(py) - float(bounds.top)) / height
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return
    from app._03_world.space.world_coords import content_to_world

    tile = content_to_world(nx, ny)
    note_clicks(float(tile.x), float(tile.y), int(count))


def recent_clicks() -> list[tuple[float, float, float]]:
    """``(start_time, rx, ry)`` still inside the ring window."""
    now = time.time()
    with _LOCK:
        _prune(now)
        return list(_CLICKS)


def _prune(now: float) -> None:
    cutoff = now - _KEEP_S
    while _CLICKS and _CLICKS[0][0] < cutoff:
        _CLICKS.pop(0)
