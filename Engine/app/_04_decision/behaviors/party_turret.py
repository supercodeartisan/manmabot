"""Party leader turret: hunt inside the 5×5 around one map dot.

The session arms this while the leader's nav tile is within two tiles of a
party-map point. The anchor is that point, in the same nav tiles as
``world_origin``. A saved turret/moving choice is not read. An area mark
does not arm this.

- A live target inside the 5×5 is walked to. Search hops do not run.
- Outside the box a fight already in progress is finished. Other monsters
  and loot are excluded. When that target is gone, the leader walks back
  to the dot.
- ``party.turret_leash`` (before ``farm.engage``) applies that filter.
- ``party.turret_idle`` (after ``farm.engage``): nothing to fight → stand
  on the dot. Anywhere else, including inside the 5×5, walks back to it.

Solo bots never set the flag, so every step is a no-op for them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from app._03_world import ActionType, ObjectType
from app._04_decision.behavior_tree import Status

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

SCRATCH_TURRET = "party_turret"
SCRATCH_TURRET_EXCLUDE = "party_turret_exclude"

# 5×5 box: the dot, plus two tiles each way. Same radius as POINT_BOX_TILES.
LEASH_TILES = 2
# Anchor farther than this (after a long trip) is dropped and re-picked.
ANCHOR_FORGET_TILES = 40

Tile = tuple[int, int]


def _cheb(a: Tile, b: Tile) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def set_party_turret(
    blackboard: "Blackboard",
    on: bool,
    *,
    map_id: Optional[int] = None,
    leash: int = LEASH_TILES,
    anchor: Optional[tuple[int, int]] = None,
) -> None:
    """Session hook: arm / disarm turret for this tick.

    ``anchor`` pins the party-map point. The next point replaces it.
    """
    st = blackboard.scratch.get(SCRATCH_TURRET)
    if not on:
        if isinstance(st, dict):
            st["on"] = False
            st["pinned"] = False
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return
    if not isinstance(st, dict):
        st = {"anchors": {}}
        blackboard.scratch[SCRATCH_TURRET] = st
    st["on"] = True
    st["map_id"] = None if map_id is None else int(map_id)
    st["leash"] = max(1, min(4, int(leash)))
    if anchor is not None and map_id is not None:
        anchors = st.setdefault("anchors", {})
        anchors[int(map_id)] = (int(anchor[0]), int(anchor[1]))
        st["pinned"] = True
    else:
        st["pinned"] = False


def clear_party_turret(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(SCRATCH_TURRET, None)
    blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)


def party_turret_active(blackboard: "Blackboard") -> bool:
    st = blackboard.scratch.get(SCRATCH_TURRET)
    return isinstance(st, dict) and bool(st.get("on"))


def turret_excluded_ids(blackboard: "Blackboard") -> set[int]:
    """Track ids outside the anchor zone (empty unless turret is on)."""
    if not party_turret_active(blackboard):
        return set()
    raw = blackboard.scratch.get(SCRATCH_TURRET_EXCLUDE)
    return set(raw) if raw else set()


def turret_anchor(blackboard: "Blackboard") -> Optional[Tile]:
    st = blackboard.scratch.get(SCRATCH_TURRET)
    if not isinstance(st, dict):
        return None
    tile = (st.get("anchors") or {}).get(st.get("map_id"))
    return None if tile is None else (int(tile[0]), int(tile[1]))


def turret_status(blackboard: "Blackboard") -> dict[str, Any]:
    st = blackboard.scratch.get(SCRATCH_TURRET)
    if not isinstance(st, dict):
        return {"on": False}
    return {
        "on": bool(st.get("on")),
        "map_id": st.get("map_id"),
        "anchor": turret_anchor(blackboard),
        "leash": st.get("leash", LEASH_TILES),
        "excluded": len(turret_excluded_ids(blackboard)),
    }


def _me(blackboard: "Blackboard") -> Tile:
    o = blackboard.world_origin
    return (int(o.x), int(o.y))


def _ensure_anchor(blackboard: "Blackboard") -> Optional[Tile]:
    """Pinned party-map point, or the first tile stood inside the farm."""
    st = blackboard.scratch.get(SCRATCH_TURRET)
    if not isinstance(st, dict):
        return None
    if st.get("pinned"):
        tile = (st.get("anchors") or {}).get(st.get("map_id"))
        if tile is None:
            return None
        return (int(tile[0]), int(tile[1]))
    me = _me(blackboard)
    anchors = st.setdefault("anchors", {})
    key = st.get("map_id")
    tile = anchors.get(key)
    if tile is not None and _cheb(me, tile) > ANCHOR_FORGET_TILES:
        anchors.pop(key, None)
        tile = None
    if tile is not None:
        return (int(tile[0]), int(tile[1]))
    from app._04_decision.nav_config import get_active_farm

    farm = get_active_farm(blackboard.farm_area_index)
    if farm is not None and not farm.contains(me[0], me[1]):
        return None
    anchors[key] = me
    from app.bot_log import event

    event("party", "turret anchor map=%s tile=(%s,%s)", key, me[0], me[1])
    return me


def _reach(state: "GameState") -> int:
    from app._04_decision.behaviors.hold_ground import hold_ground_reach

    try:
        return int(hold_ground_reach(state))
    except Exception:
        return 1


def _zone_exclusions(
    state: "GameState", blackboard: "Blackboard", anchor: Tile, leash: int
) -> set[int]:
    """Monsters / items the leader would have to leave the anchor zone for."""
    from app._04_decision.combat_query import (
        object_absolute_tile,
        tile_distance_from_player,
    )

    origin = blackboard.world_origin
    reach = _reach(state)
    # Ranged hits from inside the zone; melee walks next to the target.
    mob_zone = leash + (reach if reach > 1 else 0)
    item_zone = leash
    out: set[int] = set()
    for kind, zone in ((ObjectType.MONSTER, mob_zone), (ObjectType.ITEM, item_zone)):
        for obj in state.objects(kind):
            try:
                tile = object_absolute_tile(obj, origin)
            except Exception:
                continue
            if _cheb(tile, anchor) <= zone:
                continue
            if kind is ObjectType.MONSTER:
                try:
                    if int(tile_distance_from_player(obj)) <= reach:
                        continue
                except (TypeError, ValueError):
                    pass
            out.add(int(obj.track_id))
    return out


def _walk_to(blackboard: "Blackboard", goal: Tile, reason: str) -> Optional[Status]:
    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.pathfinding import plan_travel_click, waypoint_to_content

    origin = blackboard.world_origin
    dest = None
    terrain = get_terrain_map()
    if terrain is not None:
        try:
            dest, _path, _wp = plan_travel_click(terrain, origin, goal)
        except Exception:
            dest = None
    if dest is None:
        dest = waypoint_to_content(goal, origin)
    blackboard.current_goal = "party_turret"
    blackboard.emit(
        ActionType.TRAVELING,
        destination=dest,
        priority=0.6,
        reason=reason,
        mid_act=False,
    )
    return Status.SUCCESS


def _hunt_target_alive(state: "GameState", blackboard: "Blackboard") -> bool:
    """True while the leader's current monster is still the fight to finish."""
    tid = getattr(blackboard, "current_target_id", None)
    if tid is None:
        return False
    try:
        from app._04_decision.behaviors.combat import sticky_target_alive

        return bool(sticky_target_alive(state, int(tid)))
    except (TypeError, ValueError):
        return False


def _outside_ids(state: "GameState", keep: Optional[int]) -> set[int]:
    """Every monster except the fight in progress, plus every ground item."""
    out: set[int] = set()
    for kind in (ObjectType.MONSTER, ObjectType.ITEM):
        for obj in state.objects(kind):
            tid = int(obj.track_id)
            if keep is not None and tid == int(keep) and kind is ObjectType.MONSTER:
                continue
            out.add(tid)
    return out


def step_party_turret_leash(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Column step ``party.turret_leash``: zone filter + pull back to the anchor."""
    if not party_turret_active(blackboard):
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return None
    anchor = _ensure_anchor(blackboard)
    if anchor is None:
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return None
    st = blackboard.scratch[SCRATCH_TURRET]
    leash = int(st.get("leash", LEASH_TILES))
    me = _me(blackboard)
    outside = _cheb(me, anchor) > leash
    if outside and _hunt_target_alive(state, blackboard):
        keep = int(blackboard.current_target_id)
        blackboard.scratch[SCRATCH_TURRET_EXCLUDE] = _outside_ids(state, keep)
        return None

    excluded = _zone_exclusions(state, blackboard, anchor, leash)
    blackboard.scratch[SCRATCH_TURRET_EXCLUDE] = excluded

    if blackboard.current_target_id is not None and int(
        blackboard.current_target_id
    ) in excluded:
        from app._04_decision.behaviors.combat import clear_engage_state

        blackboard.current_target_id = None
        clear_engage_state(blackboard)
    if blackboard.current_item_id is not None and int(
        blackboard.current_item_id
    ) in excluded:
        from app._04_decision.behaviors.loot_hop import clear_loot_hop

        clear_loot_hop(blackboard)
        blackboard.current_item_id = None

    if not outside:
        return None
    return _walk_to(
        blackboard,
        anchor,
        f"party turret return to anchor {anchor[0]},{anchor[1]}",
    )


def step_party_turret_idle(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Column step ``party.turret_idle``: no target → stand on the dot.

    ``farm.engage`` already took this tick when a monster is in the 5×5.
    Search does not run after this step returns.
    """
    del state
    if not party_turret_active(blackboard):
        return None
    anchor = turret_anchor(blackboard)
    if anchor is None:
        return None
    from app._04_decision.behaviors.search_hop import clear_search_hop

    clear_search_hop(blackboard)
    if _cheb(_me(blackboard), anchor) > 0:
        return _walk_to(
            blackboard,
            anchor,
            f"party turret idle on dot {anchor[0]},{anchor[1]}",
        )
    blackboard.current_goal = "party_turret"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.2,
        reason="party turret wait on anchor",
    )
    return Status.SUCCESS


__all__ = [
    "ANCHOR_FORGET_TILES",
    "LEASH_TILES",
    "SCRATCH_TURRET",
    "SCRATCH_TURRET_EXCLUDE",
    "clear_party_turret",
    "party_turret_active",
    "set_party_turret",
    "step_party_turret_idle",
    "step_party_turret_leash",
    "turret_anchor",
    "turret_excluded_ids",
    "turret_status",
]
