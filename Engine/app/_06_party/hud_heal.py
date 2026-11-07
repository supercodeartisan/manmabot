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


def in_heal_reach(
    member: dict[str, Any],
    *,
    here_x: Any,
    here_y: Any,
    here_map: Any,
    reach: int = HEAL_RANGE_TILES,
) -> bool:
    """Same map and Chebyshev distance of ``reach`` tiles or less."""
    mx = _tile_int(member.get("map_id"))
    x = _tile_int(member.get("x"))
    y = _tile_int(member.get("y"))
    hx = _tile_int(here_x)
    hy = _tile_int(here_y)
    hm = _tile_int(here_map)
    if None in (mx, x, y, hx, hy, hm):
        return False
    if mx != hm:
        return False
    return max(abs(int(x) - int(hx)), abs(int(y) - int(hy))) <= int(reach)


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
        if here is not None:
            hx, hy, hm = here[0], here[1], here[2]
            if not in_heal_reach(
                member, here_x=hx, here_y=hy, here_map=hm, reach=reach
            ):
                continue
        row = boxes.get(gid) if gid is not None else None
        if row is None:
            continue
        found.append(
            {
                "name": name,
                "guid": gid,
                "hp_pct": hp_pct,
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
        "click_x": (int(row["x0"]) + int(row["x1"])) // 2,
        "click_y": (int(row["y0"]) + int(row["y1"])) // 2,
    }


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
    "guid_int",
    "heal_targets",
    "list_heal_click",
    "next_heal_target",
]
