"""Talking-scroll destination list (HUD click, not world tiles).

Row order is fixed in the game UI. Keep Favorites empty — extra favorite
rows would shift every index below them.
Click UV for the first screen is calibrated from a 1024×768 capture.
Full destinations (incl. wheel notches) come from world-nav hubs JSON.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from app._03_world import ActionType, Position
from app._04_decision.behavior_tree import Status

_HUBS_JSON = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "world_nav"
    / "providers"
    / "20_hubs_talking_scroll.json"
)

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard

PURPOSE_SHOP = "shop"
PURPOSE_SPELLBOOK = "spellbook"
PURPOSE_TRAINING = "training"
PURPOSE_PET = "pet"
PURPOSE_HP_SAFE = "hp_safe"
# Dungeon-exit / long-travel purposes land here later.
PURPOSE_SPOT_ID = {
    PURPOSE_SHOP: "ti_general_goods",
    PURPOSE_SPELLBOOK: "ti_spellbook",
    PURPOSE_TRAINING: "ti_scarecrow",
    PURPOSE_PET: "ti_pet",
}
# HP safe-zone: random among wheel-0 spots except 마법서 상인.
HP_SAFE_SCROLL_PURPOSE = PURPOSE_HP_SAFE
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
SCRATCH_SCROLL_ARRIVAL_AT = "talking_scroll_arrival_at"
SCRATCH_SCROLL_LAND_PACK = "talking_scroll_land_pack"
SCRATCH_SCROLL_LAND_MAP_ID = "talking_scroll_land_map_id"
SCRATCH_SCROLL_LAND_X = "talking_scroll_land_x"
SCRATCH_SCROLL_LAND_Y = "talking_scroll_land_y"
# Live pose must sit within this Chebyshev of the spot's recorded cell.
SCROLL_ARRIVAL_SLACK = 4
SCROLL_ARRIVAL_TIMEOUT_S = 25.0
SCRATCH_VISION_REGION = "vision_region"
SCRATCH_CATALOG_REGION = "talking_scroll_region"
SCRATCH_MOTHER_TREE_STAY = "mother_tree_mainland_stay"
# Set on coming alive after a confirmed death; farming tick scrolls to 마법서 상인.
# Legacy: prefer SCRATCH_POST_RESPAWN_RETREAT + finish_retreat → world_nav.
SCRATCH_POST_RESPAWN_SCROLL = "post_respawn_spellbook"
# Revive → RETREATING recover; finish_retreat requests world_nav post_respawn.
SCRATCH_POST_RESPAWN_RETREAT = "post_respawn_retreat"
# Pending retreat hop: purpose string until the scroll is emitted.
SCRATCH_RETREAT_SCROLL = "retreat_scroll"
SCRATCH_RETREAT_SCROLL_I = "retreat_scroll_i"
# One HP safe-zone talking-scroll per retreat (wheel-0 lottery, no 마법서 상인).
SCRATCH_HP_SAFE_SCROLLED = "hp_safe_scrolled"
SCRATCH_HP_SAFE_SPOT = "hp_safe_scroll_spot"
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
# Confined-escape scroll has landed (or is in flight). Return by world nav,
# even on the same map, instead of the enter-farm walk.
SCRATCH_UNSTICK_SCROLL_RETURN = "unstick_scroll_return"
# Field mapId of mainland talking-scroll hubs (은기사, 기란, …).
_MAINLAND_FIELD_MAP_ID = 4

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


def _legacy_spot_ids() -> tuple[str, ...]:
    """First-screen spot ids (hub index 0..n-1), order matches hubs JSON."""
    return tuple(
        str(row["id"])
        for row in ROWS
        if row.get("kind") == "spot" and row.get("id")
    )


def _canonical_spot_id(hub_index: int) -> str:
    legacy = _legacy_spot_ids()
    if 0 <= int(hub_index) < len(legacy):
        return legacy[int(hub_index)]
    return f"hub_{int(hub_index)}"


@dataclass(frozen=True)
class ScrollSpotPlan:
    """One talking-scroll destination from usage rules (hubs provider)."""

    id: str
    hub_index: int
    name: str
    region: str
    game_map_id: int
    world_x: int
    world_y: int
    scroll_times: int
    click_u: float
    click_v: float

    @property
    def click_uv(self) -> Position:
        return Position(x=float(self.click_u), y=float(self.click_v))


@lru_cache(maxsize=1)
def scroll_spot_plans() -> tuple[ScrollSpotPlan, ...]:
    """All talking-scroll spots (wheels + click UV) from hubs provider."""
    if not _HUBS_JSON.is_file():
        return ()
    try:
        doc = json.loads(_HUBS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return ()
    out: list[ScrollSpotPlan] = []
    for raw in doc.get("hubs") or ():
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw["index"])
            ui = raw.get("ui") or {}
            click = ui.get("click") or {}
            snap = ui.get("snapshot_size") or {}
            sw = float(snap.get("width") or 800)
            sh = float(snap.get("height") or 600)
            cu = float(click["x"]) / sw
            cv = float(click["y"]) / sh
            wheels = max(0, int(ui.get("scroll_times") or 0))
            out.append(
                ScrollSpotPlan(
                    id=_canonical_spot_id(idx),
                    hub_index=idx,
                    name=str(raw.get("name") or f"hub_{idx}"),
                    region=str(raw.get("region") or ""),
                    game_map_id=int(raw["mapId"]),
                    world_x=int(raw["x"]),
                    world_y=int(raw["y"]),
                    scroll_times=wheels,
                    click_u=max(0.0, min(1.0, cu)),
                    click_v=max(0.0, min(1.0, cv)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda p: p.hub_index)
    return tuple(out)


def scroll_spot_plan(spot_id: str | None) -> Optional[ScrollSpotPlan]:
    """Resolve a spot id (legacy ROWS id or hub_N) to hub usage rules."""
    want = str(spot_id or "").strip()
    if not want:
        return None
    plans = scroll_spot_plans()
    by_id = {p.id: p for p in plans}
    if want in by_id:
        return by_id[want]
    if want.startswith("hub_"):
        try:
            idx = int(want[4:])
        except ValueError:
            return None
        for plan in plans:
            if plan.hub_index == idx:
                return plan
    return None


def list_talking_scroll_spot_ids() -> list[str]:
    """Stable spot ids for editors (legacy first-screen ids + hub_N)."""
    plans = scroll_spot_plans()
    if plans:
        return [p.id for p in plans]
    return list(_legacy_spot_ids())


def list_talking_scroll_spot_choices() -> list[tuple[str, str]]:
    """``(id, label)`` for comboboxes — includes wheel count from hubs."""
    plans = scroll_spot_plans()
    if not plans:
        return [(sid, sid) for sid in _legacy_spot_ids()]
    return [
        (
            p.id,
            f"{p.id} · {p.region}/{p.name} · wheels={p.scroll_times}",
        )
        for p in plans
    ]


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
    plan = scroll_spot_plan(spot_id)
    if plan is not None:
        if int(plan.game_map_id) == 0:
            return ScrollGeography(
                catalog_region=CATALOG_TALKING_ISLAND,
                map_id=MAP_ID_TALKING_ISLAND,
                vision_region=VISION_TALKING_ISLAND,
            )
        return ScrollGeography(
            catalog_region=str(plan.region or "mainland"),
            map_id=MAP_ID_MAINLAND,
            vision_region=None,
        )
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
    # Prefer calibrated first-screen ROWS UVs for legacy ids; hub UV for the rest.
    row = row_by_id(spot_id)
    if row is not None and row.get("kind") == "spot":
        y = row.get("y_uv")
        if y is not None:
            return Position(x=float(CLICK_X_UV), y=float(y))
    plan = scroll_spot_plan(spot_id)
    if plan is not None:
        return plan.click_uv
    return None


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
    """Open the scroll and click the row for ``purpose`` or ``spot_id``. Item, not magic.

    Wheel notches come from talking-scroll hub usage rules for ``spot_id``.
    """
    from app._04_decision.spells import mark_slot_used, slot_ready
    from app.bot_log import get_logger

    if not spot_id:
        spot_id = PURPOSE_SPOT_ID.get(purpose)
    plan = scroll_spot_plan(spot_id) if spot_id else None
    dest = click_uv_for_id(spot_id) if spot_id else None
    wheels = int(plan.scroll_times) if plan is not None else 0
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
    _arm_scroll_arrival(
        blackboard,
        plan=plan,
        spot_id=spot_id,
    )
    get_logger("nav").info(
        "talking scroll emit spot=%s purpose=%s wheels=%s reason=%s",
        spot_id,
        purpose,
        wheels,
        reason,
    )
    blackboard.emit(
        ActionType.USE_TALKING_SCROLL,
        destination=dest,
        priority=0.7,
        reason=reason,
        shop_land_wait=(purpose == PURPOSE_SHOP),
        scroll_times=max(0, wheels),
    )
    return Status.SUCCESS


def emit_talking_scroll_uv(
    blackboard: "Blackboard",
    *,
    destination: Position,
    reason: str = "world nav talking scroll",
    land_map_id: Optional[int] = None,
    land_pack_id: Optional[str] = None,
    land_x: Optional[int] = None,
    land_y: Optional[int] = None,
    scroll_times: int = 0,
) -> Status:
    """Open talking scroll and click an arbitrary list UV (world-nav hubs)."""
    from app._04_decision.spells import mark_slot_used, slot_ready
    from app.bot_log import get_logger

    if destination is None:
        return Status.FAILURE
    if not slot_ready(blackboard, "talking_scroll", urgent=True):
        get_logger("nav").info("talking scroll uv not ready reason=%s", reason)
        return Status.FAILURE
    mark_slot_used(blackboard, "talking_scroll")
    blackboard.current_goal = "talking_scroll"
    blackboard.scratch[SCRATCH_SCROLL_SPOT] = "world_nav_uv"
    _arm_scroll_arrival(
        blackboard,
        land_map_id=land_map_id,
        land_pack_id=land_pack_id,
        land_x=land_x,
        land_y=land_y,
    )
    get_logger("nav").info(
        "talking scroll uv emit land_pack=%s mapId=%s xy=(%s,%s) wheels=%s reason=%s",
        land_pack_id,
        land_map_id,
        land_x,
        land_y,
        scroll_times,
        reason,
    )
    blackboard.emit(
        ActionType.USE_TALKING_SCROLL,
        destination=destination,
        priority=0.7,
        reason=reason,
        scroll_times=max(0, int(scroll_times)),
    )
    return Status.SUCCESS


def _reset_nav_session(blackboard: "Blackboard") -> None:
    from app._04_decision.behaviors.travel import clear_travel
    from app._04_decision.farm_time import reset_farm_timer

    clear_travel(blackboard)
    blackboard.farm_route.clear()
    blackboard.farm_route_pos = 0
    blackboard.farm_area_index = 0
    blackboard.patrol_index = 0
    reset_farm_timer(blackboard)


def _arm_scroll_arrival(
    blackboard: "Blackboard",
    *,
    plan: Optional[ScrollSpotPlan] = None,
    spot_id: Optional[str] = None,
    land_map_id: Optional[int] = None,
    land_pack_id: Optional[str] = None,
    land_x: Optional[int] = None,
    land_y: Optional[int] = None,
) -> None:
    """Remember expected land mapId/xy; arrival applies only after live pose matches."""
    import time

    blackboard.scratch[SCRATCH_SCROLL_ARRIVAL] = True
    blackboard.scratch[SCRATCH_SCROLL_ARRIVAL_AT] = time.time()
    if plan is not None:
        blackboard.scratch[SCRATCH_SCROLL_LAND_MAP_ID] = int(plan.game_map_id)
        blackboard.scratch[SCRATCH_SCROLL_LAND_X] = int(plan.world_x)
        blackboard.scratch[SCRATCH_SCROLL_LAND_Y] = int(plan.world_y)
        geo = geography_for_id(plan.id)
        if geo is not None:
            blackboard.scratch[SCRATCH_SCROLL_LAND_PACK] = str(geo.map_id)
        return
    sid = str(spot_id or "").strip()
    if sid and sid != "world_nav_uv":
        resolved = scroll_spot_plan(sid)
        if resolved is not None:
            _arm_scroll_arrival(blackboard, plan=resolved)
            return
        geo = geography_for_id(sid)
        if geo is not None:
            blackboard.scratch[SCRATCH_SCROLL_LAND_PACK] = str(geo.map_id)
    if land_pack_id:
        blackboard.scratch[SCRATCH_SCROLL_LAND_PACK] = str(land_pack_id)
    if land_map_id is not None:
        blackboard.scratch[SCRATCH_SCROLL_LAND_MAP_ID] = int(land_map_id)
    if land_x is not None and land_y is not None:
        blackboard.scratch[SCRATCH_SCROLL_LAND_X] = int(land_x)
        blackboard.scratch[SCRATCH_SCROLL_LAND_Y] = int(land_y)


def _clear_scroll_arrival(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(SCRATCH_SCROLL_ARRIVAL, None)
    blackboard.scratch.pop(SCRATCH_SCROLL_ARRIVAL_AT, None)
    blackboard.scratch.pop(SCRATCH_SCROLL_LAND_PACK, None)
    blackboard.scratch.pop(SCRATCH_SCROLL_LAND_MAP_ID, None)
    blackboard.scratch.pop(SCRATCH_SCROLL_LAND_X, None)
    blackboard.scratch.pop(SCRATCH_SCROLL_LAND_Y, None)


def _scroll_arrival_expect(
    blackboard: "Blackboard",
) -> tuple[Optional[int], Optional[int], Optional[int], str]:
    """Return ``(mapId, x, y, land_pack)`` for the pending scroll land."""
    spot_id = str(blackboard.scratch.get(SCRATCH_SCROLL_SPOT) or "")
    land_pack = str(blackboard.scratch.get(SCRATCH_SCROLL_LAND_PACK) or "").strip()
    mid = blackboard.scratch.get(SCRATCH_SCROLL_LAND_MAP_ID)
    lx = blackboard.scratch.get(SCRATCH_SCROLL_LAND_X)
    ly = blackboard.scratch.get(SCRATCH_SCROLL_LAND_Y)
    try:
        mid_i = int(mid) if mid is not None else None
    except (TypeError, ValueError):
        mid_i = None
    try:
        lx_i = int(lx) if lx is not None else None
        ly_i = int(ly) if ly is not None else None
    except (TypeError, ValueError):
        lx_i = ly_i = None
    if (mid_i is None or lx_i is None or ly_i is None) and spot_id and spot_id != "world_nav_uv":
        plan = scroll_spot_plan(spot_id)
        if plan is not None:
            mid_i = int(plan.game_map_id)
            lx_i = int(plan.world_x)
            ly_i = int(plan.world_y)
            if not land_pack:
                geo = geography_for_id(spot_id)
                if geo is not None:
                    land_pack = str(geo.map_id)
    return mid_i, lx_i, ly_i, land_pack


def apply_talking_scroll_arrival(
    blackboard: "Blackboard",
    config: Optional[dict[str, Any]] = None,
    *,
    vision: Any = None,
    state: Any = None,
) -> bool:
    """After scroll click: wait until live pose is within 4 tiles of the spot cell.

    Only then switch map pack/origin. Call every tick while
    ``SCRATCH_SCROLL_ARRIVAL`` is set. Full pack load is synchronous via
    ``live_map_pack`` so the next decide/walk cannot see a stale dungeon origin.
    """
    import time

    if not blackboard.scratch.get(SCRATCH_SCROLL_ARRIVAL):
        return False

    from app.bot_log import get_logger

    log = get_logger("nav")
    spot_id = str(blackboard.scratch.get(SCRATCH_SCROLL_SPOT) or "")
    mid, lx, ly, land_pack = _scroll_arrival_expect(blackboard)
    geo = geography_for_id(spot_id) if spot_id and spot_id != "world_nav_uv" else None
    if geo is None and not land_pack and mid is None:
        _clear_scroll_arrival(blackboard)
        return False

    started = float(blackboard.scratch.get(SCRATCH_SCROLL_ARRIVAL_AT) or 0.0)
    timed_out = started > 0 and (time.time() - started) > SCROLL_ARRIVAL_TIMEOUT_S

    pose = None
    if state is not None:
        try:
            from app._04_decision.world_nav.session import live_pose_from_state

            pose = live_pose_from_state(state, fresh=True)
        except Exception:
            pose = None

    if mid is not None and lx is not None and ly is not None:
        if pose is None:
            if timed_out:
                log.warning(
                    "talking scroll arrival timeout (no pose) want map%s (%s,%s)",
                    mid,
                    lx,
                    ly,
                )
                _clear_scroll_arrival(blackboard)
            return False
        dist = max(abs(int(pose.x) - lx), abs(int(pose.y) - ly))
        if int(pose.map_id) != int(mid) or dist > SCROLL_ARRIVAL_SLACK:
            if timed_out:
                log.warning(
                    "talking scroll arrival timeout at map%s (%s,%s) "
                    "want map%s (%s,%s) r<=%s",
                    pose.map_id,
                    pose.x,
                    pose.y,
                    mid,
                    lx,
                    ly,
                    SCROLL_ARRIVAL_SLACK,
                )
                _clear_scroll_arrival(blackboard)
            return False
    elif timed_out:
        log.warning("talking scroll arrival timeout (no land xy) spot=%s", spot_id)
        _clear_scroll_arrival(blackboard)
        return False
    elif pose is None:
        return False

    if geo is not None:
        blackboard.scratch[SCRATCH_CATALOG_REGION] = geo.catalog_region

    from app._03_world.space.map_pack import get_active_map_pack
    from app._04_decision.live_map_pack import ensure_navigation_for_pack_id

    pack = get_active_map_pack()
    current = str(pack.id) if pack is not None else ""
    dest = land_pack or (str(geo.map_id or "").strip() if geo is not None else "")
    if config is not None and dest and dest != current:
        already = str(blackboard.scratch.get(SCRATCH_NAV_RELOAD_MAP) or "")
        if already != dest:
            blackboard.scratch[SCRATCH_NAV_RELOAD_MAP] = dest
            _reset_nav_session(blackboard)
            ensure_navigation_for_pack_id(blackboard, config, dest)
    elif dest and dest == current:
        blackboard.scratch.pop(SCRATCH_NAV_RELOAD_MAP, None)

    if pose is not None:
        try:
            from app._03_world.merge.memory_sync import game_to_nav
            from app._03_world.space.world_coords import WorldOrigin

            nx, ny = game_to_nav(int(pose.x), int(pose.y))
            blackboard.world_origin = WorldOrigin(x=int(nx), y=int(ny))
        except Exception:
            pass

    if geo is not None:
        vision_key = resolved_vision_region(geo)
        blackboard.scratch[SCRATCH_VISION_REGION] = vision_key
        if vision is not None:
            setter = getattr(vision, "set_region", None)
            if setter is not None:
                setter(vision_key, config)

    log.info(
        "talking scroll arrival ok spot=%s map%s (%s,%s) pack=%s",
        spot_id or "-",
        getattr(pose, "map_id", mid),
        getattr(pose, "x", lx),
        getattr(pose, "y", ly),
        dest or "-",
    )
    _clear_scroll_arrival(blackboard)
    return True


def talking_scroll_available() -> bool:
    """True when this run's startup hotbar scan placed the scroll on a slot.

    A binding saved from an earlier run does not count. Bag count is not read.
    """
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


def nearest_mainland_hub_spot(
    world_xy: tuple[int, int] | None,
) -> Optional[str]:
    """Mainland talking-scroll hub closest to ``world_xy`` (absolute tiles).

    Talking Island rows (mapId 0) are not candidates. Equal distance keeps
    the earlier hub index.
    """
    if world_xy is None:
        return None
    ax, ay = int(world_xy[0]), int(world_xy[1])
    best_id: Optional[str] = None
    best_key: Optional[tuple[int, int]] = None
    for plan in scroll_spot_plans():
        if int(plan.game_map_id) != _MAINLAND_FIELD_MAP_ID:
            continue
        dist = max(abs(int(plan.world_x) - ax), abs(int(plan.world_y) - ay))
        key = (dist, int(plan.hub_index))
        if best_key is None or key < best_key:
            best_key = key
            best_id = plan.id
    return best_id


def farm_return_scroll_spot(
    map_id: str | None = None,
    *,
    near: tuple[int, int] | None = None,
) -> Optional[str]:
    """Talking-scroll row for an NPC/teleporter on the farming map.

    Mainland uses the hub nearest ``near`` (absolute tiles of the current
    hunt area). Talking Island stays on 마법서 상인. A dungeon floor still
    lands at the fixed mainland town row.
    """
    mid = str(map_id or "").strip()
    if not mid:
        from app._03_world.space.map_pack import get_active_map_pack

        pack = get_active_map_pack()
        mid = str(pack.id) if pack is not None else MAP_ID_TALKING_ISLAND
    if mid == MAP_ID_MAINLAND:
        spot = nearest_mainland_hub_spot(near)
        if spot and scroll_spot_plan(spot) is not None:
            return spot
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
    from app._03_world.space.map_pack import get_active_map_pack
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
        from app._03_world.space.map_pack import get_active_map_pack
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


def _is_spellbook_merchant_spot(plan: ScrollSpotPlan) -> bool:
    if plan.id == PURPOSE_SPOT_ID.get(PURPOSE_SPELLBOOK) or plan.id == "ti_spellbook":
        return True
    folded = "".join(str(plan.name or "").split())
    return "마법서상인" in folded


def hp_safe_scroll_plans() -> tuple[ScrollSpotPlan, ...]:
    """Wheel-0 talking-scroll landings except 마법서 상인."""
    return tuple(
        plan
        for plan in scroll_spot_plans()
        if int(plan.scroll_times) == 0 and not _is_spellbook_merchant_spot(plan)
    )


def pick_hp_safe_scroll_spot(
    blackboard: "Blackboard",
    *,
    rng: Optional[random.Random] = None,
) -> str:
    """Pick one HP-safe landing per retreat episode (no re-roll)."""
    existing = str(blackboard.scratch.get(SCRATCH_HP_SAFE_SPOT) or "").strip()
    if existing:
        plan = scroll_spot_plan(existing)
        if (
            plan is not None
            and int(plan.scroll_times) == 0
            and not _is_spellbook_merchant_spot(plan)
        ):
            return existing
    plans = hp_safe_scroll_plans()
    picker = rng if rng is not None else random
    if plans:
        spot = str(picker.choice(plans).id)
    else:
        spot = str(PURPOSE_SPOT_ID.get(PURPOSE_TRAINING) or "ti_scarecrow")
    blackboard.scratch[SCRATCH_HP_SAFE_SPOT] = spot
    return spot


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
    not changed — only the live pack. Pack load is synchronous (live_map_pack).
    """
    if not blackboard.scratch.pop(SCRATCH_MOTHER_TREE_STAY, None):
        return False
    blackboard.scratch[SCRATCH_CATALOG_REGION] = MAP_ID_MAINLAND

    from app._03_world.space.map_pack import get_active_map_pack
    from app._04_decision.live_map_pack import ensure_navigation_for_pack_id

    pack = get_active_map_pack()
    current = str(pack.id) if pack is not None else ""
    if config is not None and MAP_ID_MAINLAND != current:
        _reset_nav_session(blackboard)
        # Do not stamp world_origin_from_config() — that is (0,0) and poisons UV.
        ensure_navigation_for_pack_id(blackboard, config, MAP_ID_MAINLAND)

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
    "PURPOSE_HP_SAFE",
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
    "SCRATCH_POST_RESPAWN_RETREAT",
    "SCRATCH_RETREAT_SCROLL",
    "SCRATCH_RETREAT_SCROLL_I",
    "SCRATCH_HP_SAFE_SCROLLED",
    "SCRATCH_HP_SAFE_SPOT",
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
    "ScrollSpotPlan",
    "row_by_id",
    "geography_for_id",
    "resolved_vision_region",
    "click_uv_for_id",
    "click_uv_for_purpose",
    "scroll_spot_plans",
    "scroll_spot_plan",
    "list_talking_scroll_spot_ids",
    "list_talking_scroll_spot_choices",
    "emit_talking_scroll",
    "talking_scroll_available",
    "farm_return_scroll_spot",
    "mark_post_shop_return",
    "next_retreat_scroll_purpose",
    "hp_safe_scroll_plans",
    "pick_hp_safe_scroll_spot",
    "apply_talking_scroll_arrival",
    "apply_mother_tree_mainland_stay",
]
