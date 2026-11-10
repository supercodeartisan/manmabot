"""Pure party arrow-supply decisions. No clicks and no shop trip."""
from __future__ import annotations

from typing import Any, Callable, Optional

DUTY_FOLLOW = "follow"
DUTY_SHOP = "shop"
DUTY_SUPPLY = "supply"


def hunt_map_after_pose(stored: Any, pose_map: Any, *, leaving: bool) -> Any:
    """While the leader is hunting, the hunt map is the map they are on.

    A retreat or a return scroll keeps the previous map so people still there
    stay eligible and the leader, now elsewhere, does not.
    """
    if leaving or pose_map is None:
        return stored
    try:
        return int(pose_map)
    except (TypeError, ValueError):
        return stored


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


def mage_seat_names(roster: Any) -> set[str]:
    """Roster names whose seat is mage. A missing row is not a mage.

    ``seat_role_for_name`` leaves an unknown name as unknown. The party boss is
    not on the roster, so this list is the only skip set.
    """
    names: set[str] = set()
    rows = roster if isinstance(roster, (list, tuple)) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "").strip().lower() != "mage":
            continue
        name = str(row.get("name") or "").strip().casefold()
        if name:
            names.add(name)
    return names


def _row_is_class_mage(raw: Any) -> bool:
    """True for a party-memory row whose character class is mage."""
    if not isinstance(raw, dict):
        return False
    kind = str(raw.get("type") or raw.get("class") or "").strip().casefold()
    if kind in ("마법사", "mage", "wizard"):
        return True
    try:
        return int(raw.get("cls")) == 3
    except (TypeError, ValueError):
        return False


def mp_recipient_names(roster: Any, party: Any = None) -> set[str]:
    """Who receives MP and does not receive arrows.

    The roster mage seat is the explicit MP setting. A class mage keeps that
    supply even when the seat is something else. Healing and melee assist stay
    on the class check, not on this set.
    """
    names = set(mage_seat_names(roster))
    if not isinstance(party, dict):
        return names
    rows = list(party.get("members") or [])
    leader = party.get("leader")
    if isinstance(leader, dict):
        rows.append(leader)
    for raw in rows:
        if not _row_is_class_mage(raw):
            continue
        name = str(raw.get("name") or "").strip().casefold()
        if name:
            names.add(name)
    return names


def remember_delivered(
    book: dict,
    name: str,
    item: str,
    reported: Optional[int],
    qty: int,
) -> Optional[int]:
    """Add a drop onto the count the last report still shows.

    Returns the expected count, or None when the report had no count to adjust.
    A later report that no longer matches ``seen`` replaces this entry.
    """
    if reported is None or not isinstance(book, dict):
        return None
    who = str(name or "").strip().casefold()
    kind = str(item or "arrow")
    if not who:
        return None
    try:
        seen = int(reported)
        add = max(0, int(qty))
    except (TypeError, ValueError):
        return None
    key = (who, kind)
    prev = book.get(key)
    base = seen
    if isinstance(prev, dict) and prev.get("seen") == seen:
        try:
            base = int(prev.get("count") or seen)
        except (TypeError, ValueError):
            base = seen
    count = base + add
    book[key] = {"seen": seen, "count": count}
    return count


def count_with_delivery(
    book: Any,
    name: str,
    item: str,
    reported: Optional[int],
) -> Optional[int]:
    """Reported count, plus a drop the next report has not absorbed yet."""
    if reported is None or not isinstance(book, dict):
        return reported
    key = (str(name or "").strip().casefold(), str(item or "arrow"))
    prev = book.get(key)
    if not isinstance(prev, dict):
        return reported
    try:
        seen = int(reported)
        expected = int(prev.get("count"))
    except (TypeError, ValueError):
        book.pop(key, None)
        return reported
    if prev.get("seen") != seen:
        book.pop(key, None)
        return reported
    return expected


def rows_with_expected(rows: Any, book: Any) -> list:
    """Copy of the reports with delivered stacks filled in. Live rows stay put."""
    out: list = []
    for row in rows or []:
        if not isinstance(row, dict) or not isinstance(book, dict) or not book:
            out.append(row)
            continue
        items = row.get("items")
        if not isinstance(items, dict):
            out.append(row)
            continue
        who = str(row.get("from") or "")
        new_items = dict(items)
        changed = False
        for item, key in (
            ("hp", "hp_potion"),
            ("depoison", "depoison"),
            ("mp", "mp_potion"),
        ):
            reported = report_supply_count(row, item)
            adjusted = count_with_delivery(book, who, item, reported)
            if adjusted is None or adjusted == reported:
                continue
            new_items[key] = adjusted
            changed = True
        reported_arrows = report_supply_count(row, "arrow")
        adjusted_arrows = count_with_delivery(book, who, "arrow", reported_arrows)
        if (
            adjusted_arrows is not None
            and reported_arrows is not None
            and adjusted_arrows != reported_arrows
        ):
            new_items["arrows"] = adjusted_arrows
            new_items["silver_arrows"] = 0
            changed = True
        if not changed:
            out.append(row)
            continue
        copied = dict(row)
        copied["items"] = new_items
        out.append(copied)
    return out


def pick_arrow_duty(
    own: Optional[int],
    rows: Any,
    *,
    member_min: int,
    keeper_min: int,
    give_qty: int = 100,
    self_name: str = "",
    skip_names: Any = None,
) -> Optional[dict[str, Any]]:
    """Buy when the shopkeeper is short. Otherwise drop ``give_qty`` to the first short member.

    The shopkeeper keeps ``keeper_min`` arrows. A drop never spends that reserve,
    so a short spare drops only what is left above it. ``skip_names`` leaves the
    mage seat out.
    """
    if own is None:
        return None
    if int(own) < int(keeper_min):
        return {"kind": "buy"}
    spare = int(own) - int(keeper_min)
    if spare <= 0:
        return None
    try:
        give = max(1, int(give_qty))
    except (TypeError, ValueError):
        give = 100
    me = str(self_name or "").strip().casefold()
    blocked = {
        str(name).strip().casefold()
        for name in (skip_names or [])
        if str(name).strip()
    }
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        who = str(row.get("from") or "").strip()
        if not who or (me and who.casefold() == me):
            continue
        if who.casefold() in blocked:
            continue
        count = report_arrow_count(row)
        if count is None or count >= int(member_min):
            continue
        qty = min(spare, give)
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


def report_supply_count(row: Any, item: str) -> Optional[int]:
    """One reported stack. None when that item was not in the bag report."""
    if item == "arrow":
        return report_arrow_count(row)
    key = {"hp": "hp_potion", "depoison": "depoison", "mp": "mp_potion"}.get(str(item))
    if not key or not isinstance(row, dict):
        return None
    items = row.get("items")
    if not isinstance(items, dict) or key not in items:
        return None
    try:
        return max(0, int(items.get(key) or 0))
    except (TypeError, ValueError):
        return None


def bag_supply_counts(state: Any) -> dict[str, Optional[int]]:
    """Local bag counts. None until inventory_listen has filled the bag."""
    empty: dict[str, Optional[int]] = {
        "hp": None,
        "depoison": None,
        "mp": None,
        "arrow": None,
    }
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None)
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return empty

    def _n(attr: str) -> Optional[int]:
        try:
            return max(0, int(getattr(inv, attr, 0) or 0))
        except (TypeError, ValueError):
            return None

    arrows = _n("arrows")
    silver = _n("silver_arrows")
    if arrows is None or silver is None:
        empty["arrow"] = None
    else:
        empty["arrow"] = arrows + silver
    empty["hp"] = _n("hp_potion")
    empty["depoison"] = _n("depoison")
    empty["mp"] = _n("mp_potion")
    return empty


def supply_fill_qty(own: Optional[int], keeper_min: int, configured: int) -> int:
    """One shop trip. At least the boss buy count, and enough to reach the reserve.

    The shop quantity field stops at 999.
    """
    try:
        buy = max(1, min(999, int(configured)))
    except (TypeError, ValueError):
        buy = 1
    if own is None:
        return buy
    try:
        gap = max(0, int(keeper_min) - int(own))
    except (TypeError, ValueError):
        return buy
    if gap <= 0:
        return buy
    return max(1, min(999, max(buy, gap)))


def affordable_supply_qty(
    wanted: int,
    adena: Optional[int],
    unit_price: Optional[int],
) -> int:
    """Buy ``wanted`` when Adena covers it. Otherwise buy as many as the price allows.

    Unknown Adena or an unknown price keeps ``wanted``. Zero means one unit
    does not fit.
    """
    try:
        want = max(0, min(999, int(wanted)))
    except (TypeError, ValueError):
        want = 0
    if want <= 0:
        return 0
    if unit_price is None or adena is None:
        return want
    try:
        price = int(unit_price)
        have = int(adena)
    except (TypeError, ValueError):
        return want
    if price <= 0:
        return want
    return max(0, min(want, have // price))


def party_supply_need(
    spec: dict,
    rows: Any,
    *,
    self_name: str = "",
    held: Any = None,
) -> int:
    """How many of this item the eligible members are still short.

    Each short report contributes ``member_min - count``. The shopkeeper, skipped
    names, and a pile already on the ground are left out.
    """
    item = str(spec.get("item") or "")
    try:
        floor = int(spec.get("member_min") or 0)
    except (TypeError, ValueError):
        return 0
    me = str(self_name or "").strip().casefold()
    held_name = ""
    held_item = ""
    if isinstance(held, tuple) and len(held) == 2:
        held_name = str(held[0] or "").strip().casefold()
        held_item = str(held[1] or "").strip()
    blocked = {
        str(name).strip().casefold()
        for name in (spec.get("skip_names") or [])
        if str(name).strip()
    }
    only = spec.get("only_names")
    only_set = None
    if only is not None:
        only_set = {str(name).strip().casefold() for name in only if str(name).strip()}
    total = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        who = str(row.get("from") or "").strip()
        if not who or (me and who.casefold() == me):
            continue
        if who.casefold() in blocked:
            continue
        if only_set is not None and who.casefold() not in only_set:
            continue
        if held_name and held_item == item and who.casefold() == held_name:
            continue
        count = report_supply_count(row, item)
        if count is None or count >= floor:
            continue
        total += floor - int(count)
    return max(0, total)


def planned_buy_qty(
    own: int,
    keeper_min: int,
    configured: int,
    party_need: int,
) -> Optional[int]:
    """Buy for an empty reserve, or None while spare is still on hand to drop.

    A bag under the reserve buys the reserve gap and the party shortage together.
    Spare above the reserve is delivered first. Once that spare is gone, one buy
    covers the party shortage. The count stops at 999.
    """
    try:
        have = int(own)
        keep = int(keeper_min)
        base = max(1, int(configured))
        need = max(0, int(party_need))
    except (TypeError, ValueError):
        return None
    spare = have - keep
    if have >= keep and (spare > 0 or need <= 0):
        return None
    gap = need if have >= keep else max(0, keep + need - have)
    return max(1, min(999, max(base, gap)))


def next_supply_buy(
    counts: Any,
    specs: Any,
    *,
    after_item: str,
    skip_buys: Any = None,
    rows: Any = None,
    self_name: str = "",
    held: Any = None,
) -> Optional[dict[str, Any]]:
    """The next keeper buy after ``after_item``. None means go back to the leader.

    Earlier rows are not bought again on this outing. A remembered price the
    bag cannot cover is skipped, and the row after that is considered. When
    ``rows`` is present, a reserve that cannot cover the party is bought too.
    """
    bag = counts if isinstance(counts, dict) else {}
    broke = {
        str(name).strip()
        for name in (skip_buys or [])
        if str(name).strip()
    }
    seen = False
    after = str(after_item or "")
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        item = str(spec.get("item") or "")
        if not seen:
            if item == after:
                seen = True
            continue
        if not bool(spec.get("can_buy", True)) or item in broke:
            continue
        own = bag.get(item)
        if own is None:
            continue
        try:
            keep = int(spec.get("keeper_min") or 0)
        except (TypeError, ValueError):
            continue
        need = 0 if rows is None else party_supply_need(
            spec, rows, self_name=self_name, held=held
        )
        qty = planned_buy_qty(int(own), keep, int(spec.get("buy") or 1), need)
        if qty is None:
            continue
        return {
            "kind": "buy",
            "item": item,
            "buy": qty,
            "keeper_min": keep,
            "own": int(own),
            "party_need": need,
        }
    return None


def choose_supply_duty(
    counts: Any,
    rows: Any,
    specs: Any,
    *,
    self_name: str = "",
    held: Any = None,
    skip_buys: Any = None,
) -> Optional[dict[str, Any]]:
    """Drop spare that is already in the bag, else buy the reserve and the party.

    ``specs`` is priority order. ``held`` is ``(name, item)`` already on the ground.
    Spare above the reserve is delivered before another town trip. MP stays
    ``can_buy`` false while no shop behavior exists.
    """
    bag = counts if isinstance(counts, dict) else {}
    held_name = ""
    held_item = ""
    if isinstance(held, tuple) and len(held) == 2:
        held_name = str(held[0] or "").strip().casefold()
        held_item = str(held[1] or "").strip()
    me = str(self_name or "").strip().casefold()
    broke = {
        str(name).strip()
        for name in (skip_buys or [])
        if str(name).strip()
    }
    for spec in specs or []:
        if not isinstance(spec, dict) or not bool(spec.get("can_buy", True)):
            continue
        item = str(spec.get("item") or "")
        if item in broke:
            continue
        own = bag.get(item)
        if own is None:
            continue
        try:
            keep = int(spec.get("keeper_min") or 0)
        except (TypeError, ValueError):
            continue
        need = party_supply_need(spec, rows, self_name=self_name, held=held)
        qty = planned_buy_qty(int(own), keep, int(spec.get("buy") or 1), need)
        if qty is None:
            continue
        return {
            "kind": "buy",
            "item": item,
            "buy": qty,
            "keeper_min": keep,
            "own": int(own),
            "party_need": need,
        }
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        item = str(spec.get("item") or "")
        own = bag.get(item)
        if own is None:
            continue
        try:
            spare = int(own) - int(spec.get("keeper_min") or 0)
            give = max(1, int(spec.get("give") or 1))
            floor = int(spec.get("member_min") or 0)
        except (TypeError, ValueError):
            continue
        if spare <= 0:
            continue
        blocked = {
            str(name).strip().casefold()
            for name in (spec.get("skip_names") or [])
            if str(name).strip()
        }
        only = spec.get("only_names")
        only_set = None
        if only is not None:
            only_set = {str(name).strip().casefold() for name in only if str(name).strip()}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            who = str(row.get("from") or "").strip()
            if not who or (me and who.casefold() == me):
                continue
            if who.casefold() in blocked:
                continue
            if only_set is not None and who.casefold() not in only_set:
                continue
            if held_name and held_item == item and who.casefold() == held_name:
                continue
            count = report_supply_count(row, item)
            if count is None or count >= floor:
                continue
            duty = {
                "kind": "drop",
                "item": item,
                "name": who,
                "qty": min(spare, give),
                "min": floor,
                "map_id": row.get("map_id"),
                "x": row.get("x"),
                "y": row.get("y"),
            }
            guid = str(row.get("guid") or "").strip()
            if guid:
                duty["guid"] = guid
            return duty
    return None


def supply_pile_qty_ok(item: Any, wanted: Any) -> bool:
    """True when the ground count matches the notice.

    A missing notice count or an unread ground count keeps the name match.
    """
    if wanted is None or str(wanted).strip() == "":
        return True
    try:
        need = int(wanted)
    except (TypeError, ValueError):
        return True
    raw = getattr(item, "loot_qty", None)
    if raw is None:
        return True
    try:
        return int(raw) == need
    except (TypeError, ValueError):
        return True


def supply_pile_matches(item: Any, kind: str) -> bool:
    """True when a ground pile can be the supply claim.

    A named pile must be that item. An unnamed pile is left alone: the ground
    reader already treats a pile with no name as adena.
    """
    from app._03_world.merge.memory_inventory import (
        ARROW_NAMES,
        DEPOISON_NAMES,
        HP_POTION_NAMES,
        MP_POTION_NAMES,
        SILVER_ARROW_NAMES,
    )
    from app._04_decision.combat_query import is_adena

    if is_adena(item):
        return False
    want = str(kind or "").strip()
    if not want:
        return True
    identity = getattr(item, "identity", None)
    parts = [
        getattr(item, "detail_classification", ""),
        getattr(item, "species_name", ""),
        getattr(identity, "name", "") if identity is not None else "",
    ]
    text = " ".join(str(part or "") for part in parts).casefold()
    named = text.strip() not in ("", "item", "grounditem")
    groups = (
        ("mp", MP_POTION_NAMES),
        ("depoison", DEPOISON_NAMES),
        ("arrow", ARROW_NAMES | SILVER_ARROW_NAMES),
        ("hp", HP_POTION_NAMES),
    )
    found = None
    for label, names in groups:
        if any(str(name).casefold() in text for name in names):
            found = label
            break
    if found is None:
        return not named
    return found == want


def party_shop_buy_qty(
    scratch: Any,
    behavior_id: str,
    solo_qty: Optional[int],
    state: Any = None,
) -> Optional[int]:
    """Party supply shop uses the boss buy count. Every other shop keeps ``solo_qty``."""
    if not isinstance(scratch, dict) or not scratch.get("party_shopkeeper_arrow"):
        return solo_qty
    item = str(scratch.get("party_supply_item") or "arrow")
    bid = str(behavior_id or "")
    matches = (
        (item == "arrow" and "arrow" in bid)
        or (item == "hp" and "hp_potion" in bid)
        or (item == "depoison" and "depoison" in bid)
    )
    if not matches:
        return solo_qty
    raw = scratch.get("party_arrow_buy_qty")
    configured = scratch.get("party_supply_configured", raw)
    keep = scratch.get("party_supply_keep")
    if state is not None and keep is not None and configured is not None:
        own = bag_supply_counts(state).get(item)
        try:
            return supply_fill_qty(own, int(keep), int(configured))
        except (TypeError, ValueError):
            pass
    if raw is None:
        return solo_qty
    try:
        return max(1, min(999, int(raw)))
    except (TypeError, ValueError):
        return solo_qty


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
