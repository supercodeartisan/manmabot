"""Talking-scroll destination list (HUD click, not world tiles).

Row order is fixed in the game UI. Keep Favorites empty — extra favorite
rows would shift every index below them.
Click UV is calibrated from a 1024×768 capture of the top-left list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from app._03_world import ActionType, Position
from app._04_decision.behavior_tree import Status

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard

PURPOSE_SHOP = "shop"
PURPOSE_SPELLBOOK = "spellbook"
PURPOSE_TRAINING = "training"
PURPOSE_PET = "pet"
# Dungeon-exit / long-travel purposes land here later.
PURPOSE_SPOT_ID = {
    PURPOSE_SHOP: "ti_general_goods",
    PURPOSE_SPELLBOOK: "ti_spellbook",
    PURPOSE_TRAINING: "ti_scarecrow",
    PURPOSE_PET: "ti_pet",
}
# Clickable talking-scroll spots, 1-based: warehouse, inn, teleporter,
# goods, spellbook, pet, dock, scarecrow. HP safe-zone uses the 8th.
HP_SAFE_SCROLL_PURPOSE = PURPOSE_TRAINING
# Non-HP retreats (Fix/Return, MP) still rotate these three landings
# instead of teleport + walking to a painted safe rect.
RETREAT_SCROLL_PURPOSES: tuple[str, ...] = (
    PURPOSE_SPELLBOOK,
    PURPOSE_TRAINING,
    PURPOSE_PET,
)
RETREAT_SCROLL_LABELS = {
    PURPOSE_SPELLBOOK: "마법서 상인",
    PURPOSE_TRAINING: "허수아비 수련장",
    PURPOSE_PET: "펫 관리인",
}

# Catalog ``region`` on a row is the village header it sits under.
CATALOG_TALKING_ISLAND = "talking_island"
MAP_ID_TALKING_ISLAND = "talking_island"
MAP_ID_MAINLAND = "mainland"
# Vision pack key (space, matches maps/talking_island/meta.yaml default_region).
VISION_TALKING_ISLAND = "talking island"

SCRATCH_SHOP_TRIP = "shop_trip"
SCRATCH_NEWBIE_TRAINING = "newbie_training"
SCRATCH_SCROLL_SPOT = "talking_scroll_spot"
SCRATCH_SCROLL_ARRIVAL = "talking_scroll_arrival"
SCRATCH_VISION_REGION = "vision_region"
SCRATCH_CATALOG_REGION = "talking_scroll_region"
SCRATCH_MOTHER_TREE_STAY = "mother_tree_mainland_stay"
# Set on coming alive after a confirmed death; farming tick scrolls to 마법서 상인.
SCRATCH_POST_RESPAWN_SCROLL = "post_respawn_spellbook"
# Pending retreat hop: purpose string until the scroll is emitted.
SCRATCH_RETREAT_SCROLL = "retreat_scroll"
SCRATCH_RETREAT_SCROLL_I = "retreat_scroll_i"
# One HP safe-zone talking-scroll per retreat (허수아비 수련장 / 8th TI row).
SCRATCH_HP_SAFE_SCROLLED = "hp_safe_scrolled"
# Destination map already queued for a talking-scroll nav reload this hop.
SCRATCH_NAV_RELOAD_MAP = "nav_reload_map"
# After shop buy/sell finishes: scroll (or walk) back toward the farm map.
SCRATCH_POST_SHOP_RETURN = "post_shop_return"
# Wall-clock of the last hunt-map talking-scroll (wait for the teleport).
SCRATCH_HUNT_MAP_SCROLL_AT = "hunt_map_scroll_at"
HUNT_MAP_SCROLL_COOLDOWN_S = 8.0
# Nav-tile slack: origin jitter must not look like a different map.
OFF_MAP_TERRAIN_SLACK = 24
# Last time we were in combat (for Fix/Return idle 귀환).
SCRATCH_LAST_COMBAT_AT = "last_combat_at"

# Walk here when a newbie cannot talking-scroll to 허수아비 수련장.
SCARECROW_FIELD_TILE = (32525, 32824)

# Default talking-scroll landing on each farm map (NPC in that map).
# Talking Island uses 마법서 상인 — not the teleporter row — so post-shop,
# hunt-map, and unstick scroll landings recover near spellbook / town center.
FARM_RETURN_SPOT_BY_MAP: dict[str, str] = {
    MAP_ID_TALKING_ISLAND: "ti_spellbook",
    MAP_ID_MAINLAND: "giran_teleporter",
}

# Screenshot that calibrated the first screen of the list.
# Y values are text-band peaks on the stored 1024×768 capture.
REF_W = 1024.0
REF_H = 768.0
CLICK_X_UV = 90.0 / REF_W

# kind header = not clickable; spot = click the row text.
# 말하는 두루마리 is the first list row. Skipping it shifts every label up one.
ROWS: tuple[dict[str, Any], ...] = (
    {
        "id": "window_title",
        "kind": "header",
        "region": "title",
        "label": "말하는 두루마리",
        "y_uv": 38.0 / REF_H,
    },
    {
        "id": "favorites_header",
        "kind": "header",
        "region": "favorites",
        "label": "즐겨찾기",
        "y_uv": 76.0 / REF_H,
    },
    {
        "id": "talking_island_header",
        "kind": "header",
        "region": "talking_island",
        "label": "말하는 섬",
        "y_uv": 115.0 / REF_H,
    },
    {
        "id": "ti_warehouse",
        "kind": "spot",
        "region": "talking_island",
        "label": "창고지기",
        "roles": ("warehouse",),
        "y_uv": 133.0 / REF_H,
    },
    {
        "id": "ti_inn",
        "kind": "spot",
        "region": "talking_island",
        "label": "여관",
        "roles": ("inn",),
        "y_uv": 150.0 / REF_H,
    },
    {
        "id": "ti_teleporter",
        "kind": "spot",
        "region": "talking_island",
        "label": "텔레포터",
        "roles": ("npc_teleporter",),
        "y_uv": 170.0 / REF_H,
    },
    {
        "id": "ti_general_goods",
        "kind": "spot",
        "region": "talking_island",
        "label": "잡화 상인",
        "roles": ("shop",),
        "y_uv": 188.0 / REF_H,
    },
    {
        "id": "ti_spellbook",
        "kind": "spot",
        "region": "talking_island",
        "label": "마법서 상인",
        "roles": ("spellbook",),
        "y_uv": 204.0 / REF_H,
    },
    {
        "id": "ti_pet",
        "kind": "spot",
        "region": "talking_island",
        "label": "펫 관리인",
        "roles": ("pet",),
        "y_uv": 226.0 / REF_H,
    },
    {
        "id": "ti_dock",
        "kind": "spot",
        "region": "talking_island",
        "label": "말하는 섬 선착장",
        "roles": ("dock",),
        "y_uv": 242.0 / REF_H,
    },
    {
        "id": "ti_scarecrow",
        "kind": "spot",
        "region": "talking_island",
        "label": "허수아비 수련장",
        "roles": ("training",),
        "y_uv": 262.0 / REF_H,
    },
    {
        "id": "giran_header",
        "kind": "header",
        "region": "giran",
        "label": "기란 마을",
        "y_uv": 300.0 / REF_H,
    },
    {
        "id": "giran_warehouse",
        "kind": "spot",
        "region": "giran",
        "label": "창고지기",
        "roles": ("warehouse",),
        "y_uv": 315.0 / REF_H,
    },
    {
        "id": "giran_inn",
        "kind": "spot",
        "region": "giran",
        "label": "여관",
        "roles": ("inn",),
        "y_uv": 334.0 / REF_H,
    },
    {
        "id": "giran_teleporter",
        "kind": "spot",
        "region": "giran",
        "label": "텔레포터",
        "roles": ("npc_teleporter",),
        "y_uv": 355.0 / REF_H,
    },
    {
        "id": "giran_general_goods",
        "kind": "spot",
        "region": "giran",
        "label": "잡화 상인",
        "roles": ("shop",),
        "y_uv": 370.0 / REF_H,
    },
    {
        "id": "giran_weapon",
        "kind": "spot",
        "region": "giran",
        "label": "무기 상인",
        "roles": ("weapons",),
        "y_uv": 388.0 / REF_H,
    },
    {
        "id": "giran_armor",
        "kind": "spot",
        "region": "giran",
        "label": "방어구 상인",
        "roles": ("armor",),
        "y_uv": 408.0 / REF_H,
    },
)

_ROWS_BY_ID = {str(row["id"]): row for row in ROWS}


@dataclass(frozen=True)
class ScrollGeography:
    """Where a talking-scroll spot puts the character.

    Talking Island: map pack and vision region are both Talking Island.
    Any other village: map pack is mainland; the finer region needs OCR later,
    so vision uses the mainland pack default until that exists.
    """

    catalog_region: str
    map_id: str
    vision_region: Optional[str]


def geography_for_id(spot_id: str) -> Optional[ScrollGeography]:
    row = row_by_id(spot_id)
    if row is None or row.get("kind") != "spot":
        return None
    catalog = str(row.get("region") or "").strip()
    if not catalog or catalog in ("favorites", "title"):
        return None
    if catalog == CATALOG_TALKING_ISLAND:
        return ScrollGeography(
            catalog_region=catalog,
            map_id=MAP_ID_TALKING_ISLAND,
            vision_region=VISION_TALKING_ISLAND,
        )
    return ScrollGeography(
        catalog_region=catalog,
        map_id=MAP_ID_MAINLAND,
        vision_region=None,
    )


def resolved_vision_region(geo: ScrollGeography) -> str:
    """Vision pack to load now. Mainland villages wait on OCR."""
    if geo.vision_region:
        return geo.vision_region
    return "mainland"


def row_by_id(spot_id: str) -> Optional[dict[str, Any]]:
    return _ROWS_BY_ID.get(spot_id)


def click_uv_for_id(spot_id: str) -> Optional[Position]:
    row = row_by_id(spot_id)
    if row is None or row.get("kind") != "spot":
        return None
    y = row.get("y_uv")
    if y is None:
        return None
    return Position(x=float(CLICK_X_UV), y=float(y))


def click_uv_for_purpose(purpose: str) -> Optional[Position]:
    spot_id = PURPOSE_SPOT_ID.get(purpose)
    if not spot_id:
        return None
    return click_uv_for_id(spot_id)


def emit_talking_scroll(
    blackboard: "Blackboard",
    *,
    purpose: str = "",
    reason: str = "talking scroll",
    spot_id: Optional[str] = None,
) -> Status:
    """Open the scroll and click the row for ``purpose`` or ``spot_id``. Item, not magic."""
    from app._04_decision.spells import mark_slot_used, slot_ready
    from app.bot_log import get_logger

    if not spot_id:
        spot_id = PURPOSE_SPOT_ID.get(purpose)
    dest = click_uv_for_id(spot_id) if spot_id else None
    if dest is None or not spot_id:
        get_logger("nav").warning(
            "talking scroll fail: no spot purpose=%s spot=%s reason=%s",
            purpose,
            spot_id,
            reason,
        )
        return Status.FAILURE
    if not slot_ready(blackboard, "talking_scroll", urgent=True):
        get_logger("nav").info(
            "talking scroll not ready purpose=%s spot=%s", purpose, spot_id
        )
        return Status.FAILURE
    mark_slot_used(blackboard, "talking_scroll")
    blackboard.current_goal = "talking_scroll"
    blackboard.scratch[SCRATCH_SCROLL_SPOT] = spot_id
    blackboard.scratch[SCRATCH_SCROLL_ARRIVAL] = True
    get_logger("nav").info(
        "talking scroll emit spot=%s purpose=%s reason=%s",
        spot_id,
        purpose,
        reason,
    )
    blackboard.emit(
        ActionType.USE_TALKING_SCROLL,
        destination=dest,
        priority=0.7,
        reason=reason,
    )
    return Status.SUCCESS


def _reset_nav_session(blackboard: "Blackboard") -> None:
    from app._04_decision.behaviors.travel import clear_travel
    from app._04_decision.farm_time import reset_farm_timer

    clear_travel(blackboard)
    blackboard.farm_tour.clear()
    blackboard.farm_tour_pos = 0
    blackboard.farm_area_index = 0
    blackboard.patrol_index = 0
    reset_farm_timer(blackboard)


def apply_talking_scroll_arrival(
    blackboard: "Blackboard",
    config: Optional[dict[str, Any]] = None,
    *,
    vision: Any = None,
) -> bool:
    """After the scroll click: switch map origin/vision; rebuild nav in background.

    Shopping only needs the live player coordinate + map origin, so the heavy
    ``configure_navigation_for_map`` (terrain / portal graph) runs on a daemon
    thread in parallel. Walk/travel waits until that finishes
    (``navigation_configure_in_progress``).
    """
    if not blackboard.scratch.pop(SCRATCH_SCROLL_ARRIVAL, None):
        return False
    spot_id = str(blackboard.scratch.get(SCRATCH_SCROLL_SPOT) or "")
    geo = geography_for_id(spot_id)
    if geo is None:
        return False
    blackboard.scratch[SCRATCH_CATALOG_REGION] = geo.catalog_region

    from app._03_world.map_pack import get_active_map_pack
    from app._04_decision.nav_config import (
        configure_map_origin_for_map,
        start_configure_navigation_for_map_async,
    )

    pack = get_active_map_pack()
    current = str(pack.id) if pack is not None else ""
    dest = str(geo.map_id or "").strip()
    if config is not None and dest and dest != current:
        already = str(blackboard.scratch.get(SCRATCH_NAV_RELOAD_MAP) or "")
        if already == dest:
            return True
        blackboard.scratch[SCRATCH_NAV_RELOAD_MAP] = dest
        # Fast path for shopping / memory game_to_nav.
        configure_map_origin_for_map(config, dest)
        # Do not stamp world_origin_from_config() here — that value is (0, 0)
        # and poisons NPC UV until the next snapshot. Keep the last player
        # nav tile; apply_snapshot rewrites it with the new map origin.
        _reset_nav_session(blackboard)
        # Heavy path for later travel — do not block this tick.
        start_configure_navigation_for_map_async(config, dest)
    elif dest and dest == current:
        blackboard.scratch.pop(SCRATCH_NAV_RELOAD_MAP, None)

    vision_key = resolved_vision_region(geo)
    blackboard.scratch[SCRATCH_VISION_REGION] = vision_key
    if vision is not None:
        setter = getattr(vision, "set_region", None)
        if setter is not None:
            setter(vision_key, config)
    return True


def talking_scroll_available() -> bool:
    """True when the Setup slot is on (item presence is not observed)."""
    from app._05_action.spell_box import slot_is_enabled

    return slot_is_enabled("talking_scroll")


def hunt_map_is_dungeon() -> bool:
    """True when this session's hunt target is a dungeon floor."""
    from app._04_decision.dungeon import get_dungeon_mode_override, is_dungeon_map

    if get_dungeon_mode_override() is True:
        return True
    from app._04_decision.player_mode import HUNT_MAP_ID

    mid = str(HUNT_MAP_ID or "").strip()
    return bool(mid) and is_dungeon_map(mid, mid)


def farm_return_scroll_spot(map_id: str | None = None) -> Optional[str]:
    """Talking-scroll row for an NPC/teleporter on the farming map."""
    mid = str(map_id or "").strip()
    if not mid:
        from app._03_world.map_pack import get_active_map_pack

        pack = get_active_map_pack()
        mid = str(pack.id) if pack is not None else MAP_ID_TALKING_ISLAND
    spot = FARM_RETURN_SPOT_BY_MAP.get(mid)
    if not spot:
        low = mid.lower()
        if low.startswith("talking_"):
            spot = FARM_RETURN_SPOT_BY_MAP[MAP_ID_TALKING_ISLAND]
        elif "dungeon" in low or mid:
            # Dungeon floors have no scroll row. Land at the nearest town.
            spot = FARM_RETURN_SPOT_BY_MAP[MAP_ID_MAINLAND]
    if spot and row_by_id(spot) is not None:
        return spot
    fallback = FARM_RETURN_SPOT_BY_MAP[MAP_ID_TALKING_ISLAND]
    return fallback if row_by_id(fallback) is not None else None


def on_dungeon_return_town() -> bool:
    """True when live pack is already the town a dungeon hunt would scroll to."""
    if not hunt_map_is_dungeon():
        return False
    from app._03_world.map_pack import get_active_map_pack
    from app._04_decision.player_mode import HUNT_MAP_ID

    pack = get_active_map_pack()
    if pack is None:
        return False
    spot = farm_return_scroll_spot(HUNT_MAP_ID)
    geo = geography_for_id(spot) if spot else None
    return geo is not None and str(pack.id) == str(geo.map_id)


def player_on_selected_map(blackboard: "Blackboard") -> bool:
    """True when the live nav tile sits on the selected hunt-map terrain.

    Dungeon hunts compare the active pack id to ``HUNT_MAP_ID`` so a shop
    reload of mainland/TI terrain is not treated as “already on the floor”.
    Island hunts keep the farm-rect + current-PNG test unchanged.
    """
    from app._04_decision.nav_config import get_active_farm, get_farm_areas, get_terrain_map

    if hunt_map_is_dungeon():
        from app._03_world.map_pack import get_active_map_pack
        from app._04_decision.player_mode import HUNT_MAP_ID

        pack = get_active_map_pack()
        return pack is not None and str(pack.id) == str(HUNT_MAP_ID)

    ox = int(blackboard.world_origin.x)
    oy = int(blackboard.world_origin.y)
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is not None and farm.contains(ox, oy):
        return True
    for rect in get_farm_areas() or ():
        if rect.contains(ox, oy):
            return True
    terrain = get_terrain_map()
    if terrain is None:
        return True
    slack = int(OFF_MAP_TERRAIN_SLACK)
    return (
        -slack <= ox < int(terrain.width) + slack
        and -slack <= oy < int(terrain.height) + slack
    )


def mark_post_shop_return(blackboard: "Blackboard") -> None:
    """Arm scrolling/walking back to the farm after a finished shop trip."""
    blackboard.scratch[SCRATCH_POST_SHOP_RETURN] = True


def next_retreat_scroll_purpose(blackboard: "Blackboard") -> str:
    """Rotate 마법서 상인 → 허수아비 수련장 → 펫 관리인 for non-HP retreat hops."""
    i = int(blackboard.scratch.get(SCRATCH_RETREAT_SCROLL_I, 0) or 0)
    purpose = RETREAT_SCROLL_PURPOSES[i % len(RETREAT_SCROLL_PURPOSES)]
    blackboard.scratch[SCRATCH_RETREAT_SCROLL_I] = i + 1
    return purpose


def apply_mother_tree_mainland_stay(
    blackboard: "Blackboard",
    config: Optional[dict[str, Any]] = None,
    *,
    vision: Any = None,
) -> bool:
    """After Mother Tree recharge with no talking scroll: live on mainland.

    The tree warp already put the character there. Operator Setup map is
    not changed — only the live pack and models. Heavy nav reload is async
    (same as talking-scroll arrival).
    """
    if not blackboard.scratch.pop(SCRATCH_MOTHER_TREE_STAY, None):
        return False
    blackboard.scratch[SCRATCH_CATALOG_REGION] = MAP_ID_MAINLAND

    from app._03_world.map_pack import get_active_map_pack
    from app._04_decision.nav_config import (
        configure_map_origin_for_map,
        start_configure_navigation_for_map_async,
    )

    pack = get_active_map_pack()
    current = str(pack.id) if pack is not None else ""
    if config is not None and MAP_ID_MAINLAND != current:
        origin = configure_map_origin_for_map(config, MAP_ID_MAINLAND)
        blackboard.world_origin = origin
        _reset_nav_session(blackboard)
        start_configure_navigation_for_map_async(config, MAP_ID_MAINLAND)

    vision_key = "mainland"
    blackboard.scratch[SCRATCH_VISION_REGION] = vision_key
    if vision is not None:
        setter = getattr(vision, "set_region", None)
        if setter is not None:
            setter(vision_key, config)
    return True


__all__ = [
    "PURPOSE_SHOP",
    "PURPOSE_SPELLBOOK",
    "PURPOSE_TRAINING",
    "PURPOSE_PET",
    "PURPOSE_SPOT_ID",
    "HP_SAFE_SCROLL_PURPOSE",
    "RETREAT_SCROLL_PURPOSES",
    "RETREAT_SCROLL_LABELS",
    "CATALOG_TALKING_ISLAND",
    "MAP_ID_TALKING_ISLAND",
    "MAP_ID_MAINLAND",
    "VISION_TALKING_ISLAND",
    "REF_W",
    "REF_H",
    "CLICK_X_UV",
    "ROWS",
    "SCRATCH_SHOP_TRIP",
    "SCRATCH_NEWBIE_TRAINING",
    "SCRATCH_SCROLL_SPOT",
    "SCRATCH_SCROLL_ARRIVAL",
    "SCRATCH_VISION_REGION",
    "SCRATCH_CATALOG_REGION",
    "SCRATCH_MOTHER_TREE_STAY",
    "SCRATCH_POST_RESPAWN_SCROLL",
    "SCRATCH_RETREAT_SCROLL",
    "SCRATCH_RETREAT_SCROLL_I",
    "SCRATCH_HP_SAFE_SCROLLED",
    "SCRATCH_NAV_RELOAD_MAP",
    "SCRATCH_POST_SHOP_RETURN",
    "SCRATCH_HUNT_MAP_SCROLL_AT",
    "HUNT_MAP_SCROLL_COOLDOWN_S",
    "SCRATCH_LAST_COMBAT_AT",
    "player_on_selected_map",
    "hunt_map_is_dungeon",
    "on_dungeon_return_town",
    "SCARECROW_FIELD_TILE",
    "FARM_RETURN_SPOT_BY_MAP",
    "ScrollGeography",
    "row_by_id",
    "geography_for_id",
    "resolved_vision_region",
    "click_uv_for_id",
    "click_uv_for_purpose",
    "emit_talking_scroll",
    "talking_scroll_available",
    "farm_return_scroll_spot",
    "mark_post_shop_return",
    "next_retreat_scroll_purpose",
    "apply_talking_scroll_arrival",
    "apply_mother_tree_mainland_stay",
]
