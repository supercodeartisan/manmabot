"""First-seen ground-item log + nearest sticky-combat drop attribution.

Perception merge calls ``note_item_first_seen`` when a new ITEM track appears.
Combat stamps recent target cells via ``note_monster_cell`` /
``note_monster_kill`` so drops can be matched by Chebyshev proximity.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Optional

# Match drop piles to the sticky kill cell.
DROP_MATCH_CHEB = 3
COMBAT_CELL_TTL_S = 20.0
ITEM_SIGHT_KEEP_S = 180.0
_MAX_COMBAT = 48

_combat_cells: deque[dict[str, Any]] = deque(maxlen=_MAX_COMBAT)
_item_first: dict[int, dict[str, Any]] = {}


def reset_item_sight_for_tests() -> None:
    _combat_cells.clear()
    _item_first.clear()


def _cheb(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def _obj_abs(obj: object) -> tuple[int, int] | None:
    cx = getattr(obj, "world_cx", None)
    cy = getattr(obj, "world_cy", None)
    if cx is not None and cy is not None:
        return int(cx), int(cy)
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    if rx is not None and ry is not None:
        # Relative-only (tests): treat as abs for matching within the same frame.
        return int(rx), int(ry)
    return None


def _obj_rel(obj: object) -> tuple[int | None, int | None]:
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    try:
        return (
            int(rx) if rx is not None else None,
            int(ry) if ry is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def _obj_name(obj: object) -> str:
    return str(
        getattr(obj, "species_name", None)
        or getattr(obj, "label", None)
        or getattr(getattr(obj, "identity", None), "name", None)
        or "?"
    ).strip() or "?"


def _prune(now: float) -> None:
    while _combat_cells and now - float(_combat_cells[0].get("t") or 0) > COMBAT_CELL_TTL_S:
        _combat_cells.popleft()
    dead = [
        tid
        for tid, row in _item_first.items()
        if now - float(row.get("t") or 0) > ITEM_SIGHT_KEEP_S
    ]
    for tid in dead:
        _item_first.pop(tid, None)


def note_monster_cell(
    obj: object | None,
    *,
    tid: int | None = None,
    species: str | None = None,
    cell: tuple[int, int] | None = None,
    killed: bool = False,
) -> None:
    """Record / refresh a combat target absolute cell for drop matching."""
    now = time.time()
    _prune(now)
    abs_xy = cell if cell is not None else (_obj_abs(obj) if obj is not None else None)
    if abs_xy is None:
        return
    mid = tid
    if mid is None and obj is not None:
        try:
            mid = int(getattr(obj, "track_id"))
        except (TypeError, ValueError):
            mid = None
    name = species if species is not None else (_obj_name(obj) if obj is not None else "?")
    # Update existing row for same tid, else append.
    if mid is not None:
        for row in _combat_cells:
            if int(row.get("id") or -1) == int(mid):
                row["x"], row["y"] = int(abs_xy[0]), int(abs_xy[1])
                row["species"] = name
                row["t"] = now
                if killed:
                    row["killed"] = True
                return
    _combat_cells.append(
        {
            "id": int(mid) if mid is not None else -1,
            "species": name,
            "x": int(abs_xy[0]),
            "y": int(abs_xy[1]),
            "t": now,
            "killed": bool(killed),
        }
    )


def note_monster_kill(
    *,
    tid: int | None,
    species: str | None,
    cell: tuple[int, int] | None,
) -> None:
    """Mark the last sticky cell as a kill (higher match priority)."""
    if cell is None:
        return
    note_monster_cell(None, tid=tid, species=species, cell=cell, killed=True)


def _match_drop(abs_xy: tuple[int, int], now: float) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_key: tuple[int, int, float] | None = None  # killed_first, cheb, age
    for row in _combat_cells:
        age = now - float(row.get("t") or 0)
        if age > COMBAT_CELL_TTL_S:
            continue
        d = _cheb(abs_xy[0], abs_xy[1], int(row["x"]), int(row["y"]))
        if d > DROP_MATCH_CHEB:
            continue
        killed = 0 if row.get("killed") else 1
        key = (killed, d, age)
        if best_key is None or key < best_key:
            best_key = key
            best = row
    return best


def note_item_first_seen(obj: object) -> Optional[dict[str, Any]]:
    """Log and store the first observation of a ground item. Idempotent per id."""
    from app._02_state.objects import ObjectType

    if getattr(obj, "object_type", None) is not ObjectType.ITEM:
        return None
    try:
        tid = int(getattr(obj, "track_id"))
    except (TypeError, ValueError):
        return None
    now = time.time()
    _prune(now)
    if tid in _item_first:
        return _item_first[tid]

    abs_xy = _obj_abs(obj)
    rx, ry = _obj_rel(obj)
    pos = getattr(obj, "position", None)
    try:
        uv_x = float(getattr(pos, "x")) if pos is not None else None
        uv_y = float(getattr(pos, "y")) if pos is not None else None
    except (TypeError, ValueError, AttributeError):
        uv_x = uv_y = None
    name = _obj_name(obj)
    drop = _match_drop(abs_xy, now) if abs_xy is not None else None
    row: dict[str, Any] = {
        "t": now,
        "id": tid,
        "name": name,
        "abs": abs_xy,
        "rel": (rx, ry),
        "uv": (uv_x, uv_y),
        "drop_id": int(drop["id"]) if drop and int(drop.get("id", -1)) >= 0 else None,
        "drop_species": str(drop["species"]) if drop else None,
        "drop_abs": (int(drop["x"]), int(drop["y"])) if drop else None,
        "drop_cheb": (
            _cheb(abs_xy[0], abs_xy[1], int(drop["x"]), int(drop["y"]))
            if drop and abs_xy is not None
            else None
        ),
        "drop_killed": bool(drop.get("killed")) if drop else False,
    }
    _item_first[tid] = row

    from app.bot_log import get_logger

    abs_s = f"({abs_xy[0]},{abs_xy[1]})" if abs_xy else "-"
    rel_s = f"({rx},{ry})" if rx is not None and ry is not None else "-"
    uv_s = (
        f"({uv_x:.3f},{uv_y:.3f})"
        if uv_x is not None and uv_y is not None
        else "-"
    )
    if drop is not None:
        drop_s = (
            f"id={row['drop_id'] if row['drop_id'] is not None else '-'} "
            f"species={row['drop_species']} "
            f"abs=({drop['x']},{drop['y']}) cheb={row['drop_cheb']} "
            f"killed={int(row['drop_killed'])}"
        )
    else:
        drop_s = "id=- species=- abs=- cheb=- killed=0"
    get_logger("loot").info(
        "item_first_seen id=%s name=%s abs=%s rel=%s uv=%s drop_mob %s",
        tid,
        name,
        abs_s,
        rel_s,
        uv_s,
        drop_s,
    )
    return row


def item_sight_row(item_id: int) -> dict[str, Any] | None:
    return _item_first.get(int(item_id))


def format_item_sight_for_begin(item_id: int) -> str:
    """Suffix for begin_loot_item: first-seen age + drop attribution."""
    row = item_sight_row(item_id)
    if row is None:
        return "first_seen=- drop_mob=-"
    age_ms = max(0.0, (time.time() - float(row["t"])) * 1000.0)
    abs_xy = row.get("abs")
    abs_s = f"({abs_xy[0]},{abs_xy[1]})" if abs_xy else "-"
    if row.get("drop_abs") is not None:
        dx, dy = row["drop_abs"]
        drop_s = (
            f"id={row.get('drop_id') if row.get('drop_id') is not None else '-'} "
            f"species={row.get('drop_species') or '-'} "
            f"abs=({dx},{dy}) cheb={row.get('drop_cheb')} "
            f"killed={int(bool(row.get('drop_killed')))}"
        )
    else:
        drop_s = "id=- species=- abs=- cheb=- killed=0"
    return (
        f"name={row.get('name') or '-'} first_abs={abs_s} "
        f"first_age_ms={age_ms:.0f} drop_mob {drop_s}"
    )


__all__ = [
    "DROP_MATCH_CHEB",
    "note_monster_cell",
    "note_monster_kill",
    "note_item_first_seen",
    "item_sight_row",
    "format_item_sight_for_begin",
    "reset_item_sight_for_tests",
]
