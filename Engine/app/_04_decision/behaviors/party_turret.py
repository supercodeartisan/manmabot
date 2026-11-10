"""Party leader turret: the hunt for one map dot.

The anchor is that dot, in the same nav tiles as ``world_origin``. A saved
turret/moving choice is not read. An area mark does not arm this. After the
point routine has started, the schedule keeps this module on, including a
step outside the box. That step does not open a world-nav route.

- The leader stands inside the 3×3. A pile is taken only inside the 5×5.
  A monster uses the solo hunt distance: on screen, or off screen within
  the solo click range. A mage in spell aim also stays inside the solo
  spell range. The 5×5 limits walking, not that shot.
- Outside the 5×5 the leader walks back to the dot. Fights and piles past
  the box are excluded, so the moving hunt does not take that tick.
- ``party.turret_leash`` (before ``farm.engage``) applies the box.
- ``party.turret_idle`` (after ``farm.engage``): nothing to fight and
  already inside the 3×3 → stand. Outside that 3×3, walk back to the dot.
  Search hops do not run.

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
# Set on arrival at a point. Stays set while that mark's time is still running,
# including a walk back onto the dot. Cleared when the schedule leaves the mark.
SCRATCH_TURRET_ROUTINE = "party_turret_routine"

# 5×5 box: the dot, plus two tiles each way. Same radius as POINT_BOX_TILES.
LEASH_TILES = 2
# 3×3 around the dot. Already inside this, the leader stands and does not
# click the center tile.
STAND_TILES = 1
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


def hold_turret_routine(blackboard: "Blackboard") -> None:
    """Remember that this point's hunt has started. The 13 s pocket stays off."""
    blackboard.scratch[SCRATCH_TURRET_ROUTINE] = True


def release_turret_routine(blackboard: "Blackboard") -> None:
    """The schedule left this mark. The next walk may use the 13 s pocket again."""
    blackboard.scratch.pop(SCRATCH_TURRET_ROUTINE, None)


def turret_routine_held(blackboard: "Blackboard") -> bool:
    """True from point arrival until that mark's time ends."""
    return bool(blackboard.scratch.get(SCRATCH_TURRET_ROUTINE))


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


def _object_tile(obj: object, origin: Any) -> Optional[Tile]:
    """Nav tile of one monster or pile. Unknown tiles stay out of the box."""
    from app._04_decision.combat_query import object_absolute_tile, relative_tile_xy

    rel = relative_tile_xy(obj)
    if rel is not None and origin is not None:
        try:
            return (int(origin.x) + int(rel[0]), int(origin.y) + int(rel[1]))
        except (TypeError, ValueError, AttributeError):
            return None
    try:
        tile = object_absolute_tile(obj, origin)
    except Exception:
        return None
    return (int(tile[0]), int(tile[1]))


def _distance(obj: object) -> Optional[int]:
    from app._04_decision.combat_query import tile_distance_from_player

    try:
        return int(tile_distance_from_player(obj))
    except (TypeError, ValueError, AttributeError):
        return None


def _solo_hunt_distance(state: "GameState", obj: object) -> bool:
    """Same distance gate the solo farm uses for a new attack."""
    from app._03_world.space.world_coords import in_mage_spell_range
    from app._04_decision.combat_query import _uses_spell_range, in_attack_click_range

    if not in_attack_click_range(obj):
        return False
    if not _uses_spell_range(state):
        return True
    pos = getattr(obj, "position", None)
    if pos is None:
        return False
    try:
        return bool(in_mage_spell_range(float(pos.x), float(pos.y)))
    except (TypeError, ValueError, AttributeError):
        return False


def _zone_exclusions(
    state: "GameState", blackboard: "Blackboard", anchor: Tile, leash: int
) -> set[int]:
    """Piles outside the 5×5. Monsters use the solo hunt distance.

    A monster inside the 5×5 stays, so a melee step inside the box still
    happens. While the body is inside that box, any monster the solo hunt
    would click from here also stays. The box does not shorten that click.
    """
    origin = blackboard.world_origin
    inside = _cheb(_me(blackboard), anchor) <= int(leash)
    span = int(leash) * 2
    out: set[int] = set()
    for kind in (ObjectType.MONSTER, ObjectType.ITEM):
        for obj in state.objects(kind):
            tile = _object_tile(obj, origin)
            dist = _distance(obj)
            in_box = tile is not None and _cheb(tile, anchor) <= int(leash)
            if dist is not None and dist > span:
                in_box = False
            if kind is ObjectType.ITEM:
                if not in_box:
                    out.add(int(obj.track_id))
                continue
            if in_box:
                continue
            if inside and _solo_hunt_distance(state, obj):
                continue
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


def step_party_turret_leash(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Column step ``party.turret_leash``: the 5×5 is the whole hunt.

    Inside the box, ``farm.engage`` runs on what this step left in. Outside
    it, this step walks back to the dot and the moving hunt does not run.
    """
    if not party_turret_active(blackboard):
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return None
    anchor = _ensure_anchor(blackboard)
    if anchor is None:
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return None
    st = blackboard.scratch[SCRATCH_TURRET]
    leash = int(st.get("leash", LEASH_TILES))
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

    if _cheb(_me(blackboard), anchor) <= leash:
        return None
    return _walk_to(
        blackboard,
        anchor,
        f"party turret return to anchor {anchor[0]},{anchor[1]}",
    )


def step_party_turret_idle(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Column step ``party.turret_idle``: no target → stand inside the 3×3.

    ``farm.engage`` already took this tick when a monster is in the 5×5.
    Search does not run after this step returns. A body already inside the
    3×3 does not click the center tile.
    """
    del state
    if not party_turret_active(blackboard):
        return None
    anchor = turret_anchor(blackboard)
    if anchor is None:
        return None
    from app._04_decision.behaviors.search_hop import clear_search_hop

    clear_search_hop(blackboard)
    if _cheb(_me(blackboard), anchor) > STAND_TILES:
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
    "STAND_TILES",
    "SCRATCH_TURRET",
    "SCRATCH_TURRET_EXCLUDE",
    "SCRATCH_TURRET_ROUTINE",
    "clear_party_turret",
    "hold_turret_routine",
    "party_turret_active",
    "release_turret_routine",
    "set_party_turret",
    "turret_routine_held",
    "step_party_turret_idle",
    "step_party_turret_leash",
    "turret_anchor",
    "turret_excluded_ids",
    "turret_status",
]
