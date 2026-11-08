"""Pure party arrow-supply decisions. No clicks and no shop trip."""
from __future__ import annotations

from typing import Any, Callable, Optional

DUTY_FOLLOW = "follow"
DUTY_SHOP = "shop"
DUTY_SUPPLY = "supply"


def report_arrow_count(row: Any) -> Optional[int]:
    """Arrows plus silver arrows on one party report. None when the row has no bag."""
    if not isinstance(row, dict):
        return None
    items = row.get("items")
    if not isinstance(items, dict) or "arrows" not in items:
        return None
    try:
        normal = max(0, int(items.get("arrows") or 0))
        silver = max(0, int(items.get("silver_arrows") or 0))
    except (TypeError, ValueError):
        return None
    return normal + silver


def bag_arrow_count(state: Any) -> Optional[int]:
    """Local bag. None until inventory_listen has filled it."""
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None)
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return None
    try:
        return max(0, int(getattr(inv, "arrows", 0) or 0)) + max(
            0, int(getattr(inv, "silver_arrows", 0) or 0)
        )
    except (TypeError, ValueError):
        return None


def pick_arrow_duty(
    own: Optional[int],
    rows: Any,
    *,
    member_min: int,
    keeper_min: int,
    self_name: str = "",
) -> Optional[dict[str, Any]]:
    """Buy when the shopkeeper is short. Otherwise drop the first short member's gap.

    The shopkeeper keeps ``keeper_min`` arrows. A drop never spends that reserve.
    """
    if own is None:
        return None
    if int(own) < int(keeper_min):
        return {"kind": "buy"}
    spare = int(own) - int(keeper_min)
    if spare <= 0:
        return None
    me = str(self_name or "").strip().casefold()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        who = str(row.get("from") or "").strip()
        if not who or (me and who.casefold() == me):
            continue
        count = report_arrow_count(row)
        if count is None or count >= int(member_min):
            continue
        qty = min(spare, int(member_min) - int(count))
        if qty <= 0:
            continue
        return {
            "kind": "drop",
            "name": who,
            "qty": qty,
            "map_id": row.get("map_id"),
            "x": row.get("x"),
            "y": row.get("y"),
        }
    return None


def shopkeeper_socket_live(
    names: Any,
    peer_for: Callable[[str], str],
    awaiting_fresh: Callable[[str], bool],
) -> bool:
    """The first roster shopkeeper still has a connected socket.

    A dropped socket (``awaiting_fresh``) is not live. Report silence is not
    the test. No shopkeeper name means the leader's own arrow shop stays on.
    """
    for raw in names or []:
        name = str(raw or "").strip()
        if not name:
            continue
        if peer_for(name) and not awaiting_fresh(name):
            return True
        return False
    return False


def pile_reserved(item: Any, origin: Any, claim: Any, me: str, map_id: Optional[int]) -> bool:
    """True when this pile is another member's arrow drop and this seat must leave it."""
    if not isinstance(claim, dict) or bool(claim.get("clear")) or origin is None:
        return False
    who = str(claim.get("for") or "").strip()
    if who and str(me or "").strip().casefold() == who.casefold():
        return False
    try:
        if map_id is not None and int(claim.get("map_id")) != int(map_id):
            return False
        cx, cy = int(claim.get("x")), int(claim.get("y"))
    except (TypeError, ValueError):
        return False
    from app._04_decision.combat_query import object_absolute_tile

    try:
        tile = object_absolute_tile(item, origin)
    except Exception:
        return False
    return max(abs(int(tile[0]) - cx), abs(int(tile[1]) - cy)) <= 2


def line_omit_names(
    rows: Any,
    peer_for: Callable[[str], str],
    awaiting_fresh: Callable[[str], bool],
) -> list[str]:
    """Names to leave out of the leader line watch.

    Only while that socket is still up and the last phase is shop or supply.
    A dropped socket stays in the line and counts as behind.
    """
    out: list[str] = []
    items = rows.items() if isinstance(rows, dict) else rows or []
    for name, row in items:
        who = str(name or "").strip()
        if not who or not isinstance(row, dict):
            continue
        live = row.get("live")
        phase = str(live.get("phase") or "") if isinstance(live, dict) else ""
        if phase not in (DUTY_SHOP, DUTY_SUPPLY):
            continue
        if awaiting_fresh(who) or not peer_for(who):
            continue
        out.append(who)
    return out
