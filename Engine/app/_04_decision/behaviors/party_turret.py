"""Party leader turret: a hunt zone around one fixed map dot.

The anchor is that dot, in the same nav tiles as ``world_origin``. It does
not move when the leader steps toward a monster. A new fight starts inside
``ENGAGE_RADIUS``. A fight already started may use an attack tile inside
``CHASE_RADIUS``. Both radii are unmeasured.

After a fight, a leader who is still inside the zone waits there. The next
monster is judged from that tile. The walk back to the dot runs when the
body has left the zone, when the party is regrouping, or when the empty-zone
look cycle reaches the dot.

``party.turret_leash`` (before ``farm.engage``) drops monsters past the
radius and walks back only from outside the chase radius.
``party.turret_idle`` (after ``farm.engage``) waits, then takes one short
look inside the zone. Solo bots never set the flag.
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

# New fights start inside this radius of the fixed dot. Unmeasured.
ENGAGE_RADIUS = 6
# A fight already started may keep an attack tile out to this radius. Unmeasured.
CHASE_RADIUS = 8
# How long an empty zone waits on the last tile before one look step. Unmeasured.
TURRET_LOOK_S = 2.0
# Kept so older callers still pass a leash. The zone uses the radii above.
LEASH_TILES = ENGAGE_RADIUS
STAND_TILES = CHASE_RADIUS
# Anchor farther than this (after a long trip) is dropped and re-picked.
ANCHOR_FORGET_TILES = 40
# Look steps around the dot. The dot itself is last, not first.
_LOOKS = ((4, 0), (0, 4), (-4, 0), (0, -4), (3, 3), (-3, 3), (3, -3), (-3, -3), (0, 0))

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
    engage: Optional[int] = None,
    chase: Optional[int] = None,
) -> None:
    """Session hook: arm / disarm turret for this tick.

    ``anchor`` pins the party-map point. A different point or map drops the
    current approach. The same point keeps it. ``engage`` and ``chase`` are
    stored as given. They are not cut down to 4.
    """
    del leash
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
    engage_v = ENGAGE_RADIUS if engage is None else max(1, int(engage))
    chase_v = CHASE_RADIUS if chase is None else max(engage_v, int(chase))
    prev_map = st.get("map_id")
    prev_anchor = None
    if map_id is not None:
        prev_anchor = (st.get("anchors") or {}).get(int(map_id))
    point_changed = (
        anchor is not None
        and map_id is not None
        and prev_anchor is not None
        and (int(prev_anchor[0]), int(prev_anchor[1])) != (int(anchor[0]), int(anchor[1]))
    )
    map_changed = (
        prev_map is not None
        and map_id is not None
        and int(prev_map) != int(map_id)
    )
    st["on"] = True
    st["map_id"] = None if map_id is None else int(map_id)
    st["engage"] = engage_v
    st["chase"] = chase_v
    st["leash"] = chase_v
    if anchor is not None and map_id is not None:
        anchors = st.setdefault("anchors", {})
        anchors[int(map_id)] = (int(anchor[0]), int(anchor[1]))
        st["pinned"] = True
    else:
        st["pinned"] = False
    if point_changed or map_changed:
        _clear_approach(blackboard)


def zone_pair(blackboard: "Blackboard") -> tuple[int, int]:
    """Engage radius, then chase radius, as stored on this turret."""
    st = blackboard.scratch.get(SCRATCH_TURRET) if blackboard is not None else None
    if not isinstance(st, dict):
        return ENGAGE_RADIUS, CHASE_RADIUS
    engage = max(1, int(st.get("engage", ENGAGE_RADIUS)))
    chase = max(engage, int(st.get("chase", CHASE_RADIUS)))
    return engage, chase


def _clear_approach(blackboard: "Blackboard") -> None:
    """Drop the previous point's target and the click that was walking to it."""
    blackboard.current_target_id = None
    scratch = getattr(blackboard, "scratch", None)
    if isinstance(scratch, dict):
        scratch.pop("party_turret_issued", None)
        scratch.pop("party_turret_look_i", None)
        scratch.pop("party_turret_look_at", None)
    try:
        from app._04_decision.behaviors.combat import clear_engage_state

        clear_engage_state(blackboard)
    except Exception:
        return


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
        "leash": st.get("chase", st.get("leash", LEASH_TILES)),
        "engage": st.get("engage", ENGAGE_RADIUS),
        "chase": st.get("chase", CHASE_RADIUS),
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


def melee_stands(monster: Tile) -> list[Tile]:
    """The eight tiles a knight can strike from."""
    x, y = int(monster[0]), int(monster[1])
    return [
        (x + dx, y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if dx or dy
    ]


def path_stays(
    path: Optional[list],
    click: Optional[Tile],
    anchor: Tile,
    limit: int,
) -> bool:
    """The click landing and every path tile stay inside ``limit``."""
    if click is not None and _cheb(click, anchor) > int(limit):
        return False
    if not path:
        return True
    return all(_cheb((int(p[0]), int(p[1])), anchor) <= int(limit) for p in path)


def pick_attack_stand(
    monster: Optional[Tile],
    me: Optional[Tile],
    anchor: Optional[Tile],
    *,
    ranged: bool,
    can_hit: bool,
    engaged: bool,
    engage: int,
    chase: int,
    path_for: Any = None,
) -> Optional[Tile]:
    """Tile to stand on. None means this monster is not a legal turret target.

    A ranged shot from the current tile stays there. A new fight uses
    ``engage``. Only ``engaged`` (a fight already started) may use ``chase``.
    A path that leaves the radius rejects that stand.
    """
    if monster is None or me is None or anchor is None:
        return None
    limit = int(chase) if engaged else int(engage)
    if ranged and can_hit and _cheb(me, anchor) <= limit:
        return me
    stands = [s for s in melee_stands(monster) if _cheb(s, anchor) <= limit]
    stands.sort(key=lambda s: (_cheb(s, me), s[0], s[1]))
    for stand in stands:
        if stand == me or path_for is None:
            return stand
        got = path_for(me, stand)
        if got is None:
            return stand
        click, path = got
        if path_stays(path, click, anchor, limit):
            return stand
    return None


def ring_tile(me: Tile, anchor: Tile, radius: int) -> Tile:
    """A tile on the engage ring toward ``me``, or ``me`` when already inside."""
    if _cheb(me, anchor) <= int(radius):
        return me
    dx = int(me[0]) - int(anchor[0])
    dy = int(me[1]) - int(anchor[1])
    span = max(abs(dx), abs(dy), 1)
    return (
        int(anchor[0]) + int(round(dx * int(radius) / span)),
        int(anchor[1]) + int(round(dy * int(radius) / span)),
    )


def _is_ranged(state: "GameState") -> bool:
    from app._04_decision.combat_query import _uses_spell_range

    if getattr(state, "player", None) is None:
        return False
    if _uses_spell_range(state):
        return True
    player = getattr(state, "player", None)
    kind = getattr(player, "character_type", None)
    name = str(getattr(kind, "value", kind) or "").lower()
    return name in ("elf", "mage")


def _path_for(blackboard: "Blackboard"):
    hook = blackboard.scratch.get("party_turret_path_for")
    if callable(hook):
        return hook

    def planner(me: Tile, stand: Tile):
        from app._04_decision.nav_config import get_terrain_map
        from app._04_decision.pathfinding import plan_travel_click

        terrain = get_terrain_map()
        if terrain is None:
            return None
        try:
            origin = type("Origin", (), {"x": int(me[0]), "y": int(me[1])})()
            _dest, path, wp = plan_travel_click(terrain, origin, stand)
        except Exception:
            return None
        click = wp if isinstance(wp, tuple) else (path[0] if path else stand)
        return click, list(path or [])

    return planner


def _zone_exclusions(
    state: "GameState", blackboard: "Blackboard", anchor: Tile, leash: int
) -> set[int]:
    """Drop monsters with no attack tile inside the stored radius.

    ``leash`` is not a second cap. A new monster uses the engage radius.
    The current target, and only that, may use the chase radius. A ranged
    character who can already shoot from inside the radius keeps the shot.
    """
    del leash
    origin = blackboard.world_origin
    me = _me(blackboard)
    engage, chase = zone_pair(blackboard)
    current = getattr(blackboard, "current_target_id", None)
    ranged = _is_ranged(state)
    paths = _path_for(blackboard)
    out: set[int] = set()
    for kind in (ObjectType.MONSTER, ObjectType.ITEM):
        for obj in state.objects(kind):
            tile = _object_tile(obj, origin)
            fighting = (
                kind is ObjectType.MONSTER
                and current is not None
                and int(current) == int(getattr(obj, "track_id", 0) or 0)
            )
            limit = chase if fighting else engage
            if kind is ObjectType.ITEM:
                if tile is None or _cheb(tile, anchor) > engage:
                    out.add(int(obj.track_id))
                continue
            try:
                shot = bool(tile is not None and _solo_hunt_distance(state, obj))
            except Exception:
                shot = False
            stand = pick_attack_stand(
                tile,
                me,
                anchor,
                ranged=ranged,
                can_hit=shot,
                engaged=fighting,
                engage=engage,
                chase=chase,
                path_for=paths,
            )
            if stand is None or _cheb(stand, anchor) > limit:
                out.add(int(obj.track_id))
    return out


def _hold_outside(blackboard: "Blackboard", now: Optional[float]) -> bool:
    """True once an outside reading has lasted ``TURRET_LOOK_S``.

    The first sample only starts the clock, so one missed pose does not walk.
    """
    import time

    clock = time.monotonic() if now is None else float(now)
    since = blackboard.scratch.get("party_turret_outside_at")
    if not isinstance(since, (int, float)):
        blackboard.scratch["party_turret_outside_at"] = clock
        return False
    return clock - float(since) >= TURRET_LOOK_S


def _walk_to(blackboard: "Blackboard", goal: Tile, reason: str) -> Optional[Status]:
    """Click a verified hop, then wait on the observed tile.

    The same goal does not mean the body has arrived. A click, a walk, an
    intermediate hop, and a stall are separate. One late pose does not click
    again. A search that does not return a hop does not send a straight click.
    """
    import time

    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.pathfinding import plan_travel_click
    from app._06_party.follow import FOLLOW_STUCK_S

    goal_t = (int(goal[0]), int(goal[1]))
    origin = blackboard.world_origin
    me = None
    if origin is not None and getattr(origin, "x", None) is not None:
        me = (int(origin.x), int(origin.y))
    now = time.monotonic()

    def _idle(why: str) -> Status:
        blackboard.current_goal = "party_turret"
        blackboard.emit(ActionType.IDLE, priority=0.2, reason=why)
        return Status.SUCCESS

    if me == goal_t:
        for key in (
            "party_turret_issued",
            "party_turret_at",
            "party_turret_hop",
            "party_turret_stuck_at",
        ):
            blackboard.scratch.pop(key, None)
        return _idle("party turret arrived")

    issued = blackboard.scratch.get("party_turret_issued")
    last = blackboard.scratch.get("party_turret_at")
    if issued == goal_t and me is not None and isinstance(last, tuple):
        last_t = (int(last[0]), int(last[1]))
        hop = blackboard.scratch.get("party_turret_hop")
        hop_t = (int(hop[0]), int(hop[1])) if isinstance(hop, tuple) else None
        if last_t != me:
            blackboard.scratch["party_turret_at"] = me
            blackboard.scratch["party_turret_stuck_at"] = now
            if hop_t is not None and me != hop_t:
                return _idle("party turret wait on anchor")
        else:
            since = blackboard.scratch.get("party_turret_stuck_at")
            if not isinstance(since, (int, float)):
                blackboard.scratch["party_turret_stuck_at"] = now
                return _idle("party turret wait on anchor")
            if now - float(since) < FOLLOW_STUCK_S:
                return _idle("party turret wait on anchor")

    dest = None
    hop_tile = None
    terrain = get_terrain_map()
    if terrain is not None and origin is not None:
        try:
            dest, _path, wp = plan_travel_click(terrain, origin, goal)
            if isinstance(wp, tuple) and len(wp) >= 2:
                hop_tile = (int(wp[0]), int(wp[1]))
        except Exception:
            dest = None
    if dest is None:
        return _idle("party turret no path")
    blackboard.scratch["party_turret_issued"] = goal_t
    blackboard.scratch["party_turret_hop"] = hop_tile or goal_t
    blackboard.scratch["party_turret_stuck_at"] = now
    if me is not None:
        blackboard.scratch["party_turret_at"] = me
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
    """Column step ``party.turret_leash``: the fixed zone is the whole hunt.

    Inside the chase radius, ``farm.engage`` runs on what this step left in.
    Outside it, this step walks back to the dot.
    """
    if not party_turret_active(blackboard):
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return None
    anchor = _ensure_anchor(blackboard)
    if anchor is None:
        blackboard.scratch.pop(SCRATCH_TURRET_EXCLUDE, None)
        return None
    st = blackboard.scratch[SCRATCH_TURRET]
    _engage, chase = zone_pair(blackboard)
    excluded = _zone_exclusions(state, blackboard, anchor, chase)
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

    if getattr(blackboard, "world_origin", None) is None:
        return None
    me = _me(blackboard)
    if _cheb(me, anchor) <= chase:
        blackboard.scratch.pop("party_turret_outside_at", None)
        return None
    if not _hold_outside(blackboard, None):
        return None
    goal = ring_tile(me, anchor, _engage)
    if goal == me:
        return None
    return _walk_to(
        blackboard,
        goal,
        f"party turret return toward {goal[0]},{goal[1]}",
    )


def _look_tile(anchor: Tile, index: int) -> Tile:
    dx, dy = _LOOKS[int(index) % len(_LOOKS)]
    return (int(anchor[0]) + int(dx), int(anchor[1]) + int(dy))


def step_party_turret_idle(
    state: "GameState", blackboard: "Blackboard", *, now: Optional[float] = None
) -> Status | None:
    """No target: wait on the current tile while it is still inside the zone.

    ``farm.engage`` already took this tick when a monster was allowed.
    Outside the chase radius, or while regrouping, walk to the dot.
    After ``TURRET_LOOK_S`` with nothing seen, take one look step inside
    the engage radius. The dot is one of those steps, not the default.
    """
    import time

    del state
    if not party_turret_active(blackboard):
        return None
    anchor = turret_anchor(blackboard)
    if anchor is None:
        return None
    from app._04_decision.behaviors.search_hop import clear_search_hop

    clear_search_hop(blackboard)
    if getattr(blackboard, "world_origin", None) is None:
        return None
    me = _me(blackboard)
    engage, chase = zone_pair(blackboard)
    regroup = bool(blackboard.scratch.get("party_turret_regroup"))
    outside = _cheb(me, anchor) > chase
    if outside and not regroup and not _hold_outside(blackboard, now):
        blackboard.current_goal = "party_turret"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="party turret wait on anchor",
        )
        return Status.SUCCESS
    if regroup or outside:
        goal = anchor if regroup else ring_tile(me, anchor, engage)
        if goal == me:
            blackboard.current_goal = "party_turret"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.2,
                reason="party turret wait on anchor",
            )
            return Status.SUCCESS
        return _walk_to(
            blackboard,
            goal,
            f"party turret return toward {goal[0]},{goal[1]}",
        )
    if not outside:
        blackboard.scratch.pop("party_turret_outside_at", None)
    clock = time.monotonic() if now is None else float(now)
    since = blackboard.scratch.get("party_turret_look_at")
    if not isinstance(since, (int, float)):
        blackboard.scratch["party_turret_look_at"] = clock
        since = clock
    if clock - float(since) < TURRET_LOOK_S:
        blackboard.current_goal = "party_turret"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="party turret wait on anchor",
        )
        return Status.SUCCESS
    index = int(blackboard.scratch.get("party_turret_look_i") or 0)
    goal = _look_tile(anchor, index)
    blackboard.scratch["party_turret_look_i"] = (index + 1) % len(_LOOKS)
    blackboard.scratch["party_turret_look_at"] = clock
    if goal == me:
        blackboard.current_goal = "party_turret"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="party turret wait on anchor",
        )
        return Status.SUCCESS
    return _walk_to(
        blackboard,
        goal,
        f"party turret look {goal[0]},{goal[1]}",
    )


__all__ = [
    "ANCHOR_FORGET_TILES",
    "CHASE_RADIUS",
    "ENGAGE_RADIUS",
    "LEASH_TILES",
    "STAND_TILES",
    "TURRET_LOOK_S",
    "SCRATCH_TURRET",
    "SCRATCH_TURRET_EXCLUDE",
    "SCRATCH_TURRET_ROUTINE",
    "clear_party_turret",
    "hold_turret_routine",
    "party_turret_active",
    "release_turret_routine",
    "set_party_turret",
    "turret_routine_held",
    "melee_stands",
    "path_stays",
    "pick_attack_stand",
    "ring_tile",
    "step_party_turret_idle",
    "step_party_turret_leash",
    "zone_pair",
    "turret_anchor",
    "turret_excluded_ids",
    "turret_status",
]
