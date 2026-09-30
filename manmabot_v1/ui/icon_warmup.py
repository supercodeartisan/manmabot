"""Background PIL prep for schedule UI icon tables (UI-thread safe).

Tk ``PhotoImage`` objects must be created on the UI thread. Helpers here only
decode/resize PIL images off-thread; callers convert to PhotoImage in batches.
"""
from __future__ import annotations

import sys
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


def collect_startup_asset_jobs(engine_root: Path) -> dict[str, object]:
    """Gather icon paths for Hunt / Sell / Magic without touching Tk.

    Returns plain data only (safe for a worker thread):
    ``hunt_jobs``, ``sell_jobs``, ``magic_jobs``.
    """
    root = str(engine_root)
    if root not in sys.path:
        sys.path.insert(0, root)

    hunt_jobs: list[tuple[str, Path | None, bool]] = []
    try:
        from app._03_world.constants import list_species_catalog
        from app._03_world.game_catalog import list_monster_rows

        catalog = {item.key: item for item in list_monster_rows()}
        for key, _level in list_species_catalog():
            path = catalog[key].image_path() if key in catalog else None
            hunt_jobs.append((key, path, True))
            hunt_jobs.append((key, path, False))
    except Exception:
        pass

    sell_jobs: list[tuple[str, Path | None]] = []
    try:
        from app._03_world.game_catalog import list_item_rows

        for entry in list_item_rows():
            path = entry.image_path()
            # Hunt item rows share the same item catalog images.
            hunt_jobs.append((entry.key, path, True))
            hunt_jobs.append((entry.key, path, False))
            sell_jobs.append((entry.key, path))
    except Exception:
        pass

    magic_jobs: list[tuple[str, Path | None]] = []
    try:
        from manmabot_v1.skill_catalog import load_skill_catalog

        for skill in load_skill_catalog().skills:
            magic_jobs.append((skill.setting_key, skill.icon))
    except Exception:
        pass

    return {
        "hunt_jobs": hunt_jobs,
        "sell_jobs": sell_jobs,
        "magic_jobs": magic_jobs,
    }


def prepare_startup_assets(
    jobs: dict[str, object],
    *,
    hunt_size: int,
    sell_size: int,
    magic_size: int,
    filled_icon: Callable[..., object],
    sell_thumb: Callable[..., object],
    magic_thumb: Callable[..., object],
) -> dict[str, dict[str, object]]:
    """Decode all startup icon jobs to PIL images (worker thread)."""
    hunt_jobs = list(jobs.get("hunt_jobs") or [])
    sell_jobs = list(jobs.get("sell_jobs") or [])
    magic_jobs = list(jobs.get("magic_jobs") or [])
    return {
        "hunt": prepare_hunt_icons(
            hunt_jobs, size=hunt_size, filled_icon=filled_icon,
        ),
        "sell": {
            key: sell_thumb(path, sell_size) for key, path in sell_jobs
        },
        "magic": {
            key: magic_thumb(path, magic_size) for key, path in magic_jobs
        },
    }
