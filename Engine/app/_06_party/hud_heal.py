"""Who a party mage heals, and which HUD list row to aim at.

Other members only. A member is due when party ``hp_pct`` is under 80,
above 0, on the mage's map, and within ``HEAL_RANGE_TILES`` (Chebyshev).
The lowest percent comes first. The aim point is that member's HUD row,
matched by guid. The body on the ground is not a heal target.
"""
from __future__ import annotations

from typing import Any, Optional

HEAL_HP_BELOW = 80
# Party-list heal reach. Attack spell range stays ``MAGE_SPELL_RANGE``.
HEAL_RANGE_TILES = 9


def guid_int(value: Any) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text:
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def _tile_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nav_xy(x: int, y: int) -> tuple[int, int]:
    """PartySubsystem pos is raw game (~32k). Follow uses nav tiles."""
    try:
        from app._03_world.merge.memory_sync import game_to_nav

        nx, ny = game_to_nav(int(x), int(y))
        return int(nx), int(ny)
    except Exception:
        return int(x), int(y)


def heal_nav_delta(
    member: dict[str, Any],
    *,
    here_x: Any,
    here_y: Any,
    here_map: Any,
) -> Optional[int]:
    """Chebyshev tiles after both sides are nav, or None when the pose is incomplete."""
    mx = _tile_int(member.get("map_id"))
    x = _tile_int(member.get("x"))
    y = _tile_int(member.get("y"))
    hx = _tile_int(here_x)
    hy = _tile_int(here_y)
    hm = _tile_int(here_map)
    if None in (mx, x, y, hx, hy, hm):
        return None
    if mx != hm:
        return None
    px, py = _nav_xy(int(x), int(y))
    qx, qy = _nav_xy(int(hx), int(hy))
    return max(abs(px - qx), abs(py - qy))


def in_heal_reach(
    member: dict[str, Any],
    *,
    here_x: Any,
    here_y: Any,
    here_map: Any,
    reach: int = HEAL_RANGE_TILES,
) -> bool:
    """Same map and Chebyshev distance of ``reach`` tiles or less."""
    dist = heal_nav_delta(
        member, here_x=here_x, here_y=here_y, here_map=here_map
    )
    return dist is not None and dist <= int(reach)


def heal_targets(
    members: Any,
    slots: Any,
    *,
    self_guid: Any = None,
    self_name: str = "",
    below: int = HEAL_HP_BELOW,
    here: Any = None,
    reach: int = HEAL_RANGE_TILES,
) -> list[dict[str, Any]]:
    """Members under ``below`` HP percent, lowest first, with a placed row box.

    ``hp_pct`` of 0 is treated as dead and skipped. When ``here`` is
    ``(x, y, map_id)``, a member on another map or farther than ``reach``
    tiles is skipped too.
    """
    boxes: dict[int, dict[str, Any]] = {}
    if isinstance(slots, list):
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            gid = guid_int(slot.get("guid"))
            row = slot.get("row")
            if gid is None or not isinstance(row, dict):
                continue
            boxes[gid] = row

    own = guid_int(self_guid)
    own_name = str(self_name or "").strip()
    found: list[dict[str, Any]] = []
    if not isinstance(members, list):
        return found
    for member in members:
        if not isinstance(member, dict):
            continue
        gid = guid_int(member.get("guid"))
        name = str(member.get("name") or "").strip()
        if own is not None and gid == own:
            continue
        if own_name and name == own_name:
            continue
        try:
            hp_pct = int(member.get("hp_pct"))
        except (TypeError, ValueError):
            continue
        if hp_pct <= 0 or hp_pct >= int(below):
            continue
        dist = None
        if here is not None:
            hx, hy, hm = here[0], here[1], here[2]
            dist = heal_nav_delta(member, here_x=hx, here_y=hy, here_map=hm)
            if dist is None or dist > int(reach):
                continue
        row = boxes.get(gid) if gid is not None else None
        if row is None:
            continue
        found.append(
            {
                "name": name,
                "guid": gid,
                "hp_pct": hp_pct,
                "dist": dist,
                "row": row,
            }
        )
    found.sort(key=lambda row: (int(row["hp_pct"]), int(row["guid"])))
    return found


def list_heal_click(
    members: Any,
    slots: Any,
    *,
    self_guid: Any = None,
    self_name: str = "",
    below: int = HEAL_HP_BELOW,
    here: Any = None,
    reach: int = HEAL_RANGE_TILES,
) -> Optional[dict[str, Any]]:
    """Center of the chosen member's list row, in client pixels."""
    target = next_heal_target(
        members,
        slots,
        self_guid=self_guid,
        self_name=self_name,
        below=below,
        here=here,
        reach=reach,
    )
    if target is None:
        return None
    row = target["row"]
    return {
        "name": target["name"],
        "guid": target["guid"],
        "hp_pct": target["hp_pct"],
        "dist": target.get("dist"),
        "click_x": (int(row["x0"]) + int(row["x1"])) // 2,
        "click_y": (int(row["y0"]) + int(row["y1"])) // 2,
    }


def assess_list_heal(
    members: Any,
    slots: Any,
    *,
    self_guid: Any = None,
    self_name: str = "",
    below: int = HEAL_HP_BELOW,
    here: Any = None,
    reach: int = HEAL_RANGE_TILES,
) -> tuple[Optional[dict[str, Any]], str]:
    """``(click or None, one stable note)`` for the party log.

    Out-of-range notes say ``dist>9`` instead of the live distance, so a
    follow does not write a line on every tile.
    """
    click = list_heal_click(
        members,
        slots,
        self_guid=self_guid,
        self_name=self_name,
        below=below,
        here=here,
        reach=reach,
    )
    if click is not None:
        dist = click.get("dist")
        dist_bit = f" dist={dist}" if dist is not None else ""
        return click, f"cast {click['name']} hp={click['hp_pct']}{dist_bit}"

    if not isinstance(members, list) or not members:
        return None, "skip no party members"
    if here is None:
        return None, "skip no pose"
    hx, hy, hm = here[0], here[1], here[2]
    own = guid_int(self_guid)
    own_name = str(self_name or "").strip()
    boxes: dict[int, dict[str, Any]] = {}
    if isinstance(slots, list):
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            gid = guid_int(slot.get("guid"))
            row = slot.get("row")
            if gid is None or not isinstance(row, dict):
                continue
            boxes[gid] = row
    blocked: list[str] = []
    saw_other = False
    for member in members:
        if not isinstance(member, dict):
            continue
        gid = guid_int(member.get("guid"))
        name = str(member.get("name") or "").strip() or "?"
        if own is not None and gid == own:
            continue
        if own_name and name == own_name:
            continue
        saw_other = True
        try:
            hp_pct = int(member.get("hp_pct"))
        except (TypeError, ValueError):
            blocked.append(f"{name} hp=?")
            continue
        if hp_pct <= 0 or hp_pct >= int(below):
            continue
        dist = heal_nav_delta(member, here_x=hx, here_y=hy, here_map=hm)
        if dist is None:
            blocked.append(f"{name} hp={hp_pct} no pos")
            continue
        if dist > int(reach):
            blocked.append(f"{name} hp={hp_pct} dist>{int(reach)}")
            continue
        if gid is None or gid not in boxes:
            blocked.append(f"{name} hp={hp_pct} dist={dist} no list row")
            continue
        blocked.append(f"{name} hp={hp_pct} dist={dist}")
    if not saw_other:
        return None, "skip only self"
    if not blocked:
        return None, f"skip no member under {int(below)}"
    return None, "skip " + "; ".join(blocked[:4])


def next_heal_target(
    members: Any,
    slots: Any,
    *,
    self_guid: Any = None,
    self_name: str = "",
    below: int = HEAL_HP_BELOW,
    here: Any = None,
    reach: int = HEAL_RANGE_TILES,
) -> Optional[dict[str, Any]]:
    """The one member to heal this cast, or None."""
    rows = heal_targets(
        members,
        slots,
        self_guid=self_guid,
        self_name=self_name,
        below=below,
        here=here,
        reach=reach,
    )
    return rows[0] if rows else None


__all__ = [
    "HEAL_HP_BELOW",
    "HEAL_RANGE_TILES",
    "in_heal_reach",
    "heal_nav_delta",
    "guid_int",
    "heal_targets",
    "list_heal_click",
    "assess_list_heal",
    "next_heal_target",
]
