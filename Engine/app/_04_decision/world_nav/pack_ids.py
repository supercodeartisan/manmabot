"""Pack folder id ↔ numeric LC mapId (engine ready.map_assets)."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

# When race variants share a live mapId, prefer the season base pack for
# mapId → pack install (nav / prebuild owner).
_LIVE_MAP_PACK_OWNERS: dict[int, str] = {
    244: "polluted_land_of_blessing",
    2450: "corrupted_land_of_blessing_spring",
    245: "corrupted_land_of_blessing_summer",
    2452: "corrupted_land_of_blessing_autumn",
    2454: "corrupted_land_of_blessing_winter",
}


@lru_cache(maxsize=1)
def _packs() -> list:
    from .ready.map_assets import discover_map_packs

    return list(discover_map_packs())


def pack_id_to_map_id(pack_id: str) -> Optional[int]:
    key = str(pack_id or "").strip()
    if not key:
        return None
    for pack in _packs():
        if pack.pack_id == key:
            return int(pack.map_id)
    aliases = {"talking_island": 0, "mainland": 4}
    if key in aliases:
        return aliases[key]
    return None


def map_id_to_pack_id(map_id: int) -> Optional[str]:
    mid = int(map_id)
    owner = _LIVE_MAP_PACK_OWNERS.get(mid)
    if owner is not None:
        for pack in _packs():
            if pack.pack_id == owner:
                return owner
    for pack in _packs():
        if int(pack.map_id) == mid:
            return str(pack.pack_id)
    return None


def pack_for_map_id(map_id: int):
    """Pack for live mapId. Prefers season base over race variants."""
    mid = int(map_id)
    owner = _LIVE_MAP_PACK_OWNERS.get(mid)
    if owner is not None:
        for pack in _packs():
            if pack.pack_id == owner:
                return pack
    for pack in _packs():
        if int(pack.map_id) == mid:
            return pack
    return None


def pack_origin(pack_id: str) -> Optional[tuple[int, int]]:
    key = str(pack_id or "").strip()
    for pack in _packs():
        if pack.pack_id == key:
            return int(pack.origin_x), int(pack.origin_y)
    return None


def nav_to_abs(pack_id: str, nx: int, ny: int) -> Optional[tuple[int, int]]:
    origin = pack_origin(pack_id)
    if origin is None:
        return None
    return int(nx) + origin[0], int(ny) + origin[1]


def abs_to_nav(pack_id: str, ax: int, ay: int) -> Optional[tuple[int, int]]:
    origin = pack_origin(pack_id)
    if origin is None:
        return None
    return int(ax) - origin[0], int(ay) - origin[1]
