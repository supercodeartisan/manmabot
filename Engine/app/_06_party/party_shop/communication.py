"""Shopkeeper live view and frame-body helpers for host publish."""
from __future__ import annotations

from typing import Any


def canonical_shopkeeper_name(roster: Any) -> str:
    """First enabled roster shopkeeper, roster order. Empty when none."""
    rows = roster if isinstance(roster, (list, tuple)) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "").strip().lower() != "shopkeeper":
            continue
        if str(row.get("enabled") or "1").strip() in ("0", "false", "no", "off"):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            return name
    return ""


def is_canonical_shopkeeper(roster: Any, self_name: str) -> bool:
    """True when ``self_name`` is the sole supply shopkeeper."""
    keeper = canonical_shopkeeper_name(roster)
    me = str(self_name or "").strip()
    return bool(keeper and me and keeper.casefold() == me.casefold())


def shopkeeper_live_supply(
    roster: Any,
    states: Any = None,
) -> dict[str, Any]:
    """Validated shopkeeper hold/notice for leader publish.

    When the keeper socket is stale or awaiting a fresh ``member_state``,
    ``hold`` and ``notice`` are None so the leader publishes clear. Stale live
    payloads are never treated as active supply.
    """
    from ..sync import member_states as _states

    book = states if states is not None else _states
    name = canonical_shopkeeper_name(roster)
    empty = {"name": name, "hold": None, "notice": None, "valid": False}
    if not name:
        return empty
    try:
        awaiting = bool(book.awaiting_fresh(name))
        fresh = bool(book.fresh(name))
    except Exception:
        return empty
    if awaiting or not fresh:
        return empty
    row = None
    try:
        row = book.rows.get(name.casefold())
    except Exception:
        row = None
    if not isinstance(row, dict):
        try:
            for key, value in book.rows.items():
                if str(key).casefold() == name.casefold():
                    row = value
                    break
        except Exception:
            row = None
    live = row.get("live") if isinstance(row, dict) else None
    if not isinstance(live, dict):
        return {"name": name, "hold": None, "notice": None, "valid": True}
    hold = live.get("supply_hold")
    notice = live.get("supply")
    return {
        "name": name,
        "hold": dict(hold) if isinstance(hold, dict) and hold.get("id") else None,
        "notice": dict(notice) if isinstance(notice, dict) and notice.get("id") else None,
        "valid": True,
    }


__all__ = [
    "canonical_shopkeeper_name",
    "is_canonical_shopkeeper",
    "shopkeeper_live_supply",
]
