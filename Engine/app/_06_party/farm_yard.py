"""Turret farm yard around the fixed hunt dot, not the leader's current tile.

New fights start inside ``ENGAGE_RADIUS``. A fight already going may use an
attack tile inside ``CHASE_RADIUS``. Both are unmeasured. The leader's live
tile is for support distance and rejoining, not for sliding this box.
"""
from __future__ import annotations

from typing import Any, Optional

# The only copies of these radii live on the leader turret.
from app._04_decision.behaviors.party_turret import CHASE_RADIUS, ENGAGE_RADIUS

# A step no farther than this, plus one attack tile, is a short approach. Unmeasured.
SHORT_STEP = 2
# A path this many tiles longer than the straight gap is a wall detour. Unmeasured.
DETOUR_EXTRA = 4

_BASE_HALF_W = ENGAGE_RADIUS
_BASE_HALF_H = ENGAGE_RADIUS
_MAX_HALF_W = 8
_MAX_HALF_H = 8


def yard_half_extents(
    party_size: int,
    *,
    half_w: Optional[int] = None,
    half_h: Optional[int] = None,
    scale_with_roster: bool = True,
) -> tuple[int, int]:
    """Return ``(half_w, half_h)`` Chebyshev-style axis half-sizes from the anchor."""
    if half_w is not None and half_h is not None:
        return (
            max(1, min(_MAX_HALF_W, int(half_w))),
            max(1, min(_MAX_HALF_H, int(half_h))),
        )
    n = max(1, int(party_size))
    w = _BASE_HALF_W
    h = _BASE_HALF_H
    if scale_with_roster and n > 5:
        extra = n - 5
        w = _BASE_HALF_W + (extra + 1) // 2
        h = _BASE_HALF_H + extra // 2
    return (
        max(1, min(_MAX_HALF_W, w)),
        max(1, min(_MAX_HALF_H, h)),
    )


def in_yard(
    tile: Optional[tuple[int, int]],
    anchor: Optional[tuple[int, int]],
    *,
    half_w: int,
    half_h: int,
) -> bool:
    if tile is None or anchor is None:
        return False
    dx = abs(int(tile[0]) - int(anchor[0]))
    dy = abs(int(tile[1]) - int(anchor[1]))
    return dx <= int(half_w) and dy <= int(half_h)


def clamp_to_yard(
    tile: tuple[int, int],
    anchor: tuple[int, int],
    *,
    half_w: int,
    half_h: int,
) -> tuple[int, int]:
    ax, ay = int(anchor[0]), int(anchor[1])
    x = max(ax - int(half_w), min(ax + int(half_w), int(tile[0])))
    y = max(ay - int(half_h), min(ay + int(half_h), int(tile[1])))
    return (x, y)


def zone_radii(half_w: int, half_h: int) -> tuple[int, int]:
    """Start radius, then the wider radius for a fight already started."""
    start = max(1, min(CHASE_RADIUS, max(int(half_w), int(half_h))))
    chase = max(start, min(_MAX_HALF_W, start + (CHASE_RADIUS - ENGAGE_RADIUS)))
    return start, chase


def member_zone_center(
    anchor_x: Optional[int],
    anchor_y: Optional[int],
    anchor_map: Optional[int],
    local_map: Optional[int],
) -> Optional[tuple[int, int]]:
    """The shared dot, after this member's map matches the published one.

    Missing coordinates or a different map leave the fixed zone off. The
    caller then keeps the ordinary party follow instead of sliding the box
    onto the leader's live tile.
    """
    if anchor_x is None or anchor_y is None or anchor_map is None or local_map is None:
        return None
    try:
        if int(anchor_map) != int(local_map):
            return None
        return (int(anchor_x), int(anchor_y))
    except (TypeError, ValueError):
        return None


def hunt_center(
    leader_tile: Optional[tuple[int, int]],
    anchor_x: Optional[int],
    anchor_y: Optional[int],
) -> Optional[tuple[int, int]]:
    """Fixed routine dot when the leader has published one, else the leader tile."""
    if anchor_x is not None and anchor_y is not None:
        return (int(anchor_x), int(anchor_y))
    if leader_tile is None:
        return None
    return (int(leader_tile[0]), int(leader_tile[1]))


def _cheb(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def path_length(me: Optional[tuple[int, int]], monster: Optional[tuple[int, int]]) -> Optional[int]:
    """Tiles along a walk from ``me`` to ``monster``, or None when no map is loaded."""
    if me is None or monster is None:
        return None
    try:
        from app._04_decision.nav_config import get_terrain_map
        from app._04_decision.pathfinding import plan_travel_click

        terrain = get_terrain_map()
        if terrain is None:
            return None
        origin = type("Tile", (), {"x": int(me[0]), "y": int(me[1])})()
        _dest, path, _wp = plan_travel_click(terrain, origin, (int(monster[0]), int(monster[1])))
    except Exception:
        return None
    if not path:
        return None
    return len(path)


def target_band(
    monster: Optional[tuple[int, int]],
    me: Optional[tuple[int, int]],
    anchor: Optional[tuple[int, int]],
    *,
    engaged: bool,
    can_hit: bool,
    path_tiles: Optional[int] = None,
) -> str:
    """``now``, ``step``, ``leave``, or ``skip``.

    ``now``: this character can attack from the current tile and that tile
    is inside the radius that applies. ``step``: a short move stays inside
    the zone. ``leave``: the attack tile is outside, or the path is a long
    detour. ``skip``: there is nothing to judge.
    """
    if monster is None or anchor is None or me is None:
        return "skip"
    if path_tiles is not None and not can_hit and int(path_tiles) > _cheb(me, monster) + DETOUR_EXTRA:
        return "leave"
    limit = CHASE_RADIUS if engaged else ENGAGE_RADIUS
    if can_hit and _cheb(me, anchor) <= limit:
        return "now"
    from app._04_decision.behaviors.party_turret import pick_attack_stand

    stand = pick_attack_stand(
        monster,
        me,
        anchor,
        ranged=False,
        can_hit=bool(can_hit),
        engaged=bool(engaged),
        engage=ENGAGE_RADIUS,
        chase=CHASE_RADIUS,
        path_for=None,
    )
    if stand is None:
        return "skip"
    if stand == me:
        return "now"
    return "step"


def keep_current_target(current: str, new: str) -> bool:
    """A live ``now`` or ``step`` target is not dropped for a nearer monster."""
    del new
    return current in ("now", "step")


def tile_from_obj(obj: Any, origin: Any) -> Optional[tuple[int, int]]:
    if obj is None or origin is None:
        return None
    try:
        from app._04_decision.combat_query import object_absolute_tile

        return object_absolute_tile(obj, origin)
    except Exception:
        return None


__all__ = [
    "CHASE_RADIUS",
    "ENGAGE_RADIUS",
    "clamp_to_yard",
    "hunt_center",
    "member_zone_center",
    "in_yard",
    "keep_current_target",
    "path_length",
    "target_band",
    "tile_from_obj",
    "yard_half_extents",
    "zone_radii",
]
