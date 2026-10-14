"""Per-tick record of A* searches. Does not change the path that is returned."""
from __future__ import annotations

import inspect
import threading
from typing import Any

_lock = threading.Lock()
_rows: list[dict[str, Any]] = []

_SKIP_SUFFIXES = (
    "pathfinding",
    "hierarchical_path",
    "portal_graph",
    "astar_trace",
)


def begin_tick() -> None:
    """Drop records so the next take() is only this tick."""
    global _rows
    with _lock:
        _rows = []


def take_tick() -> list[dict[str, Any]]:
    """Return this tick's searches and clear the buffer."""
    global _rows
    with _lock:
        rows = _rows
        _rows = []
    return rows


_SEARCH_LABELS = {
    "find_path_in_corridor": "corridor",
    "find_path_in_window": "window",
    "find_coarse_path": "coarse",
    "plan_travel_click_hierarchical": "full map",
    "plan_travel_click": "full map",
    "_path_within_slack": "engage",
}


def labels_from_stack() -> tuple[str, str]:
    """``(behavior that asked, kind of search)`` for the debug tab."""
    frames = inspect.stack()[2:20]
    search = frames[0].function if frames else "find_path"
    cause = search
    for info in frames:
        mod = str(info.frame.f_globals.get("__name__", ""))
        if any(mod.endswith(suffix) for suffix in _SKIP_SUFFIXES):
            continue
        name = info.function
        if name.startswith("_") or name in {"<module>", "find_path"}:
            continue
        cause = name
        break
    return cause, _SEARCH_LABELS.get(search, search)


def record_search(
    *,
    cause: str,
    search: str,
    ms: float,
    start: tuple[int, int],
    goal: tuple[int, int],
    steps: int,
    expanded: int,
) -> None:
    row = {
        "cause": cause,
        "search": search,
        "ms": round(float(ms), 1),
        "start": f"{int(start[0])},{int(start[1])}",
        "goal": f"{int(goal[0])},{int(goal[1])}",
        "steps": int(steps),
        "expanded": int(expanded),
    }
    with _lock:
        _rows.append(row)
