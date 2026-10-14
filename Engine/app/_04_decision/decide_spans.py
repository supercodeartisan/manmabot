"""Per-tick timings for the decision loop. Does not change the chosen action."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

_lock = threading.Lock()
_active = False
_depth = 0
_rows: list[dict[str, Any]] = []

F = TypeVar("F", bound=Callable[..., Any])

_LABELS = {
    "mode handoff": "mode handoff",
    "farm presence": "farm presence",
    "golem hazards": "golem hazards",
    "tick_farming": "farming",
    "tick_traveling": "traveling",
    "tick_retreating": "retreating",
    "tick_world_navigating": "world nav",
    "tick_shopping": "shopping",
    "tick_mode": "mode tick",
    "_drive_shop": "shop drive",
    "_tick_dungeon_farming": "dungeon farming",
    "_tick_newbie_training": "newbie training",
    "_search_inside_farm": "search inside farm",
    "_enter_farm_if_needed": "enter farm",
    "_maybe_shop_trip": "shop trip",
    "farm_loot_or_combat": "loot or combat",
    "nearest_attackable": "nearest monster",
    "list_attackable": "scan monsters",
    "can_engage_target": "engage check",
    "dungeon_new_engage_path_ok": "dungeon path cap",
    "attack_path_clickable": "engage path",
    "continue_or_start_combat": "combat",
    "continue_or_start_loot": "loot",
    "nearest_lootable": "nearest loot",
    "list_lootable": "scan loot",
    "loot_path_clickable": "loot path",
    "emit_travel_hop": "travel hop",
    "plan_travel_click": "travel plan",
    "plan_travel_click_hierarchical": "hierarchical plan",
    "emit_search_hop": "search hop",
    "apply_hp_actions": "hp",
}


def begin_tick() -> None:
    """Start a fresh span list for this decision."""
    global _active, _depth, _rows
    with _lock:
        _rows = []
        _depth = 0
        _active = True


def take_tick() -> list[dict[str, Any]]:
    """Return this decision's spans and stop recording."""
    global _active, _rows
    with _lock:
        rows = _rows
        _rows = []
        _active = False
    return rows


def label_for(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    return name.lstrip("_").replace("_", " ")


@contextmanager
def span(name: str) -> Iterator[None]:
    """Record one decision step. Nested spans keep a depth."""
    global _depth
    if not _active:
        yield
        return
    with _lock:
        depth = _depth
        _depth += 1
        row = {"name": name, "ms": 0.0, "depth": depth}
        _rows.append(row)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        with _lock:
            _depth = max(0, _depth - 1)
            row["ms"] = round(ms, 1)


def traced(fn: F) -> F:
    """Time ``fn`` whenever a decision tick is recording."""
    name = fn.__name__

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with span(name):
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def summarize(
    rows: list[dict[str, Any]] | None,
    *,
    min_ms: float = 5.0,
) -> tuple[float, list[dict[str, Any]]]:
    """Collapse consecutive same-name spans. Drop nested spans under ``min_ms``."""
    grouped: list[dict[str, Any]] = []
    for row in list(rows or []):
        name = str(row.get("name") or "")
        depth = int(row.get("depth") or 0)
        ms = float(row.get("ms") or 0.0)
        if (
            grouped
            and grouped[-1]["name"] == name
            and grouped[-1]["depth"] == depth
        ):
            item = grouped[-1]
            item["calls"] += 1
            item["ms"] = round(float(item["ms"]) + ms, 1)
            item["max_ms"] = round(max(float(item["max_ms"]), ms), 1)
            continue
        grouped.append(
            {
                "name": name,
                "depth": depth,
                "calls": 1,
                "ms": round(ms, 1),
                "max_ms": round(ms, 1),
            }
        )
    total = round(sum(float(item["ms"]) for item in grouped if item["depth"] == 0), 1)
    visible = [
        item
        for item in grouped
        if item["depth"] == 0 or float(item["ms"]) >= min_ms
    ]
    return total, visible
