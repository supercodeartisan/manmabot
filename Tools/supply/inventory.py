"""Fresh bag snapshot via Engine inventory_listen (no copy of the DLL)."""
from __future__ import annotations

import time
from typing import Any, Optional

from app._01_perception.inventory_listen_reader import (
    InventoryListenReader,
    shared_inventory,
)

# Post-drag bag settle: poll memory this often until qty/rows change.
AFTER_DRAG_POLL_S = 0.100


def read_bag(*, reader: Optional[InventoryListenReader] = None) -> Optional[dict[str, Any]]:
    """Blocking one-shot bag JSON. Prefer this over the tick poll cache."""
    handle = reader or shared_inventory()
    if not getattr(handle, "dll_loaded", True):
        return None
    try:
        return handle.snapshot()
    except Exception:
        return None


def wait_bag_change(
    *,
    before_rows: int,
    before_qty: int,
    item_id: Optional[int] = None,
    name: str = "",
    timeout_s: float = 2.0,
    poll_s: float = AFTER_DRAG_POLL_S,
    reader: Optional[InventoryListenReader] = None,
) -> list[dict[str, Any]]:
    """After a drag: re-read bag every ``poll_s`` until match counts change.

    Returns the latest ordered item list (changed or last sample on timeout).
    """
    deadline = time.time() + max(0.0, float(timeout_s))
    interval = max(0.02, float(poll_s))
    last: list[dict[str, Any]] = []
    while True:
        last = ordered_items(read_bag(reader=reader))
        rows, qty = count_matches(last, item_id=item_id, name=name)
        if rows != before_rows or qty != before_qty:
            return last
        if time.time() >= deadline:
            return last
        time.sleep(interval)


def ordered_items(snap: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items sorted by bag ``slot`` (0-based fill order)."""
    if not isinstance(snap, dict):
        return []
    rows = snap.get("items")
    if not isinstance(rows, list):
        return []
    out = [r for r in rows if isinstance(r, dict)]
    out.sort(key=lambda r: (int(r.get("slot") if r.get("slot") is not None else 10**9), str(r.get("va") or "")))
    return out


def find_first(
    items: list[dict[str, Any]],
    *,
    item_id: Optional[int] = None,
    name: str = "",
) -> Optional[dict[str, Any]]:
    """First bag row for this list line.

    An id the user picked from the bag is enough. The name is used only when
    the line has no id. Requiring both made a real id miss and the runner
    moved to the next list line without dragging this one.
    """
    want_name = (name or "").strip()
    for row in items:
        if item_id is not None:
            try:
                if int(row.get("id") or 0) == int(item_id):
                    return row
            except (TypeError, ValueError):
                continue
        elif want_name and str(row.get("name") or "").strip() == want_name:
            return row
    return None


def count_matches(
    items: list[dict[str, Any]],
    *,
    item_id: Optional[int] = None,
    name: str = "",
) -> tuple[int, int]:
    """Return (row_count, total_stack_qty) for matching items."""
    want_name = (name or "").strip()
    rows = 0
    qty = 0
    for row in items:
        ok = False
        if item_id is not None:
            try:
                ok = int(row.get("id") or 0) == int(item_id)
            except (TypeError, ValueError):
                ok = False
        elif want_name:
            ok = str(row.get("name") or "").strip() == want_name
        if not ok:
            continue
        rows += 1
        try:
            qty += int(row.get("count") or 0)
        except (TypeError, ValueError):
            pass
    return rows, qty


def list_index_1based(item: dict[str, Any]) -> int:
    """1-based index in the dense filled-slot list (design list_index)."""
    slot = item.get("slot")
    if slot is None:
        raise ValueError("item has no slot")
    return int(slot) + 1
