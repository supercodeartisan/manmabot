"""Keep active nav pack / map_origin aligned with live MapSubsystem mapId.

Live ``mapId`` (every monitor tick) is the source of truth for which pack
terrain and ``map_origin_*`` must be loaded. Hunt / routine destination
(``HUNT_MAP_ID``) must not leave a dungeon origin on Talking Island tiles.

Call :func:`ensure_navigation_for_live_map_id` after each successful monitor
snapshot and before decide/act. First start and every mapId change load the
matching pack synchronously so the next hop cannot see a stale origin.
"""
from __future__ import annotations

from typing import Any, Optional

from app.bot_log import get_logger

SCRATCH_LIVE_MAP_ID = "live_map_id"
SCRATCH_LIVE_MAP_PACK = "live_map_pack"
SCRATCH_LIVE_MAP_SYNCED = "live_map_id_synced"


def _restamp_world_origin(blackboard: Any, snapshot: dict[str, Any] | None) -> None:
    from app._03_world.merge.memory_sync import world_origin_from_snapshot

    if not isinstance(snapshot, dict):
        return
    wo = world_origin_from_snapshot(snapshot)
    if wo is not None:
        blackboard.world_origin = wo


def _snapshot_from_blackboard(blackboard: Any) -> dict[str, Any] | None:
    state = blackboard.scratch.get("_world_nav_pose_state")
    if state is None:
        return None
    print_snap = getattr(state, "last_print_state", None)
    if isinstance(print_snap, dict) and print_snap.get("player"):
        return print_snap
    mem = getattr(state, "last_memory_snapshot", None)
    if isinstance(mem, dict) and mem.get("player"):
        return mem
    return None


def ensure_navigation_for_pack_id(
    blackboard: Any,
    config: dict[str, Any],
    pack_id: str,
    *,
    snapshot: dict[str, Any] | None = None,
    live_map_id: int | None = None,
) -> tuple[bool, str]:
    """Synchronously load ``pack_id`` if it is not already the active pack.

    Waits out any in-flight async configure first so we never decide/walk on a
    half-cleared portal graph or the wrong ``map_origin``.
    """
    from app._03_world.space.map_pack import get_active_map_pack
    from app._04_decision.nav_config import (
        configure_navigation_for_map,
        navigation_configure_in_progress,
        wait_navigation_configure,
    )

    want = str(pack_id or "").strip()
    if not want:
        return False, "empty pack_id"
    if not isinstance(config, dict):
        return False, "no runtime config"

    if navigation_configure_in_progress():
        wait_navigation_configure(timeout_s=30.0)

    pack = get_active_map_pack()
    current = str(pack.id) if pack is not None else ""
    synced = blackboard.scratch.get(SCRATCH_LIVE_MAP_SYNCED)
    already = current == want and (
        live_map_id is None or synced == int(live_map_id)
    )
    if already:
        if live_map_id is not None:
            blackboard.scratch[SCRATCH_LIVE_MAP_ID] = int(live_map_id)
            blackboard.scratch[SCRATCH_LIVE_MAP_PACK] = want
        return True, ""

    prev = current or "?"
    try:
        configure_navigation_for_map(config, want)
    except Exception as exc:
        get_logger("nav").exception("live pack sync failed pack=%s: %s", want, exc)
        return False, f"pack sync failed {want}: {exc}"

    # Pack reload points farm_areas_file at the shipped yaml and drops areas
    # that exist only in the user file. Put the checked hunt rects back when
    # this pack is the active battle row.
    _remount_checked_farms(blackboard, config, want)

    # Hop rules follow the live pack, not the (possibly dungeon) hunt target.
    try:
        from app._04_decision.dungeon import set_dungeon_mode_override

        set_dungeon_mode_override(None)
    except Exception:
        pass

    snap = snapshot if isinstance(snapshot, dict) else _snapshot_from_blackboard(blackboard)
    _restamp_world_origin(blackboard, snap)

    if live_map_id is not None:
        blackboard.scratch[SCRATCH_LIVE_MAP_ID] = int(live_map_id)
        blackboard.scratch[SCRATCH_LIVE_MAP_SYNCED] = int(live_map_id)
    else:
        blackboard.scratch.pop(SCRATCH_LIVE_MAP_SYNCED, None)
    blackboard.scratch[SCRATCH_LIVE_MAP_PACK] = want

    msg = f"Nav pack {prev}→{want}"
    if live_map_id is not None:
        msg += f" (mapId={live_map_id})"
    get_logger("nav").info("%s", msg)
    return True, msg


def _remount_checked_farms(blackboard: Any, config: dict[str, Any], pack_id: str) -> None:
    """Load the active row's checked userdata farms after a pack reload.

    A battle row on this same pack keeps those rects, including areas that are
    not in the shipped ``farms.yaml``. A break row, a dungeon, or a different
    map leaves the pack files just loaded. The stay clock and tour index are
    not cleared when the name list is unchanged.
    """
    from app._04_decision.nav_config import get_farm_areas
    from app._04_decision.world_nav.overlays import farm_rects_selected, is_dungeon_pack

    if is_dungeon_pack(blackboard, pack_id):
        return
    cursor = blackboard.scratch.get("routine_cursor")
    entry = cursor.active() if cursor is not None and hasattr(cursor, "active") else None
    if not isinstance(entry, dict):
        return
    if str(entry.get("map_id") or "").strip() != pack_id:
        return
    if str(entry.get("kind") or "battle").strip().lower() == "break":
        return
    names = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    if not names:
        return
    rects = farm_rects_selected(blackboard, pack_id, names)
    if not rects:
        return
    from app._03_world.space.map_pack import navigation_with_map_pack

    filled = navigation_with_map_pack(config)
    nav = dict(filled.get("navigation") or {})
    nav["farm_areas"] = rects
    nav.pop("farm_areas_file", None)
    config["navigation"] = nav
    try:
        from app._04_decision import nav_config as nc

        nc._load_farms_and_home(nav)
    except Exception as exc:
        get_logger("nav").warning("checked farm remount failed pack=%s: %s", pack_id, exc)
        return
    loaded = [str(getattr(farm, "name", "") or "") for farm in get_farm_areas()]
    wanted = [str(rect.get("name") or "") for rect in rects]
    if loaded != wanted:
        get_logger("nav").warning(
            "checked farm remount mismatch pack=%s wanted=%s loaded=%s",
            pack_id,
            ",".join(wanted),
            ",".join(loaded),
        )
        return
    previous = blackboard.scratch.get("farm_area_names")
    if previous != loaded:
        blackboard.farm_tour.clear()
        try:
            index = int(getattr(blackboard, "farm_area_index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index >= len(loaded):
            blackboard.farm_area_index = 0
            blackboard.farm_tour_pos = 0
    blackboard.scratch["farm_area_names"] = list(loaded)
    get_logger("nav").info(
        "checked farms remounted pack=%s n=%s names=%s",
        pack_id,
        len(loaded),
        ",".join(loaded),
    )


def ensure_navigation_for_live_map_id(
    blackboard: Any,
    config: dict[str, Any],
    map_id: int,
    *,
    snapshot: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """MapSubsystem ``mapId`` → pack folder; sync when first seen or changed."""
    from app._04_decision.world_nav.pack_ids import map_id_to_pack_id

    mid = int(map_id)
    pack_id = map_id_to_pack_id(mid)
    if not pack_id:
        blackboard.scratch[SCRATCH_LIVE_MAP_ID] = mid
        return False, f"no pack mapping for mapId={mid}"
    return ensure_navigation_for_pack_id(
        blackboard,
        config,
        pack_id,
        snapshot=snapshot,
        live_map_id=mid,
    )


def live_map_pack_ready(blackboard: Any, map_id: int) -> bool:
    """True when scratch says this mapId was synced to its pack."""
    try:
        return int(blackboard.scratch.get(SCRATCH_LIVE_MAP_SYNCED)) == int(map_id)
    except (TypeError, ValueError):
        return False


__all__ = [
    "SCRATCH_LIVE_MAP_ID",
    "SCRATCH_LIVE_MAP_PACK",
    "SCRATCH_LIVE_MAP_SYNCED",
    "ensure_navigation_for_pack_id",
    "ensure_navigation_for_live_map_id",
    "live_map_pack_ready",
]
