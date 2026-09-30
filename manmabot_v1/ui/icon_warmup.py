"""Background PIL icon prep for schedule Hunt tables (UI-thread safe).

Tk ``PhotoImage`` objects must be created on the UI thread. This helper only
decodes/resizes PIL images off-thread; callers convert to PhotoImage in batches.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable


def hunt_icon_cache_key(key: str, *, allowed: bool, size: int) -> str:
    state = "on" if allowed else "off"
    return f"{key}:{state}:{size}"


def prepare_hunt_icons(
    jobs: list[tuple[str, Path | None, bool]],
    *,
    size: int,
    filled_icon: Callable[..., object],
) -> dict[str, object]:
    """Return ``cache_key -> PIL Image`` for each (row_key, path, allowed)."""
    prepared: dict[str, object] = {}
    for key, path, allowed in jobs:
        cache_key = hunt_icon_cache_key(key, allowed=allowed, size=size)
        prepared[cache_key] = filled_icon(path, size, enabled=allowed)
    return prepared
