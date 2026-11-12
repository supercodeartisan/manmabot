"""Pick the shorter route to the leader: walk (TRAVELING) vs WORLD_NAV (scroll/TP)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Skip WORLD_NAV planning when Chebyshev walk is already this short.
_MIN_DIST_FOR_NAV = 24
# Prefer WORLD_NAV only if it beats walk by at least this many tiles.
_NAV_WIN_SLACK = 4


@dataclass(frozen=True)
class FollowRouteChoice:
    mode: str  # "walk" | "world_nav"
    walk_cost: int
    nav_cost: Optional[int] = None
    uses_tp: bool = False
    reason: str = ""


def _plan_ops(plan: Any) -> set[str]:
    steps = getattr(plan, "steps", None) or []
    return {str(getattr(s, "op", "") or "") for s in steps}


def estimate_walk_cost(leader_dist: Optional[int]) -> Optional[int]:
    if leader_dist is None:
        return None
    try:
        return max(0, int(leader_dist))
    except (TypeError, ValueError):
        return None


# Walk steps beyond the follow field: A* inside this margin around both ends.
WALK_WINDOW_MARGIN = 48
# Past this Chebyshev the window A* is too large; the planner compares instead.
WALK_WINDOW_MAX_CHEBYSHEV = 64
# No walk on this map reaches the leader. Large enough that any scroll or TP wins.
UNREACHABLE_WALK = 9999


def estimate_walk_steps(
    terrain: Any,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> Optional[int]:
    """Walk steps from ``start`` to ``goal`` on the nav map, not Chebyshev.

    Returns ``UNREACHABLE_WALK`` when the portal graph says no walk exists,
    and ``None`` when the distance is too far to measure here.
    """
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.hierarchical_path import _clamp_window, find_path_in_window

    from .follow_field import nearest_walkable

    s = nearest_walkable(terrain, start, toward=goal)
    g = nearest_walkable(terrain, goal, toward=start)
    if s is None or g is None:
        return None
    cheb = tile_chebyshev(s[0], s[1], g[0], g[1])
    if cheb > WALK_WINDOW_MAX_CHEBYSHEV:
        return None
    window = _clamp_window(terrain, s, g, WALK_WINDOW_MARGIN)
    path = find_path_in_window(terrain, s, g, window)
    if path:
        return max(cheb, len(path) - 1)
    try:
        from app._04_decision.nav_config import get_portal_graph

        graph = get_portal_graph()
    except Exception:
        graph = None
    if graph is not None:
        if graph.node_at(*s) is not None and graph.node_at(*g) is not None:
            if not graph.find_abstract_path(s, g):
                return UNREACHABLE_WALK
    # A walk exists only outside the window: longer than the window allows.
    return cheb + 2 * WALK_WINDOW_MARGIN


def choose_follow_route(
    game_state: Any,
    *,
    walk_cost: int,
    dest_map: int,
    dest_game_x: int,
    dest_game_y: int,
) -> FollowRouteChoice:
    """Return walk or world_nav — winner by tile cost (scroll/TP allowed).

    WORLD_NAV is considered when walk is long enough that talking-scroll / TP
    hubs can beat a blind walk (leader teleported far away on the same map).
    """
    walk = max(0, int(walk_cost))
    if walk < _MIN_DIST_FOR_NAV:
        return FollowRouteChoice(
            mode="walk",
            walk_cost=walk,
            reason=f"walk_short dist={walk}",
        )

    try:
        from app._04_decision.talking_scroll import talking_scroll_available
        from app._04_decision.world_nav import planner_api as api
        from app._04_decision.world_nav.session import live_pose_from_state
    except Exception as exc:
        return FollowRouteChoice(
            mode="walk",
            walk_cost=walk,
            reason=f"walk_nav_import {exc}",
        )

    pose = live_pose_from_state(game_state)
    if pose is None:
        return FollowRouteChoice(
            mode="walk",
            walk_cost=walk,
            reason="walk_no_pose",
        )

    adena = None
    try:
        from app._04_decision.hunt_area import current_adena

        adena = current_adena(game_state)
    except Exception:
        adena = None

    try:
        plan = api.plan(
            pose,
            api.point_goal(int(dest_map), int(dest_game_x), int(dest_game_y)),
            has_talking_scroll=talking_scroll_available(),
            adena=adena,
            use_npc_teleporters=True,
        )
    except Exception as exc:
        return FollowRouteChoice(
            mode="walk",
            walk_cost=walk,
            reason=f"walk_plan_err {exc}",
        )

    if not getattr(plan, "ok", False):
        return FollowRouteChoice(
            mode="walk",
            walk_cost=walk,
            reason=f"walk_plan_fail {getattr(plan, 'error', '')}",
        )

    nav_cost = int(getattr(plan, "total_cost_tiles", 0) or 0)
    ops = _plan_ops(plan)
    uses_tp = bool(ops & {"talking_scroll", "npc_teleporter", "map_transition"})
    # Pure walk WORLD_NAV is redundant with TRAVELING — keep local hops.
    if not uses_tp:
        return FollowRouteChoice(
            mode="walk",
            walk_cost=walk,
            nav_cost=nav_cost,
            uses_tp=False,
            reason=f"walk_beats_plain_nav walk={walk} nav={nav_cost}",
        )
    if nav_cost + _NAV_WIN_SLACK <= walk:
        return FollowRouteChoice(
            mode="world_nav",
            walk_cost=walk,
            nav_cost=nav_cost,
            uses_tp=True,
            reason=f"world_nav_wins walk={walk} nav={nav_cost} ops={sorted(ops)}",
        )
    return FollowRouteChoice(
        mode="walk",
        walk_cost=walk,
        nav_cost=nav_cost,
        uses_tp=uses_tp,
        reason=f"walk_wins walk={walk} nav={nav_cost}",
    )


__all__ = [
    "FollowRouteChoice",
    "choose_follow_route",
    "estimate_walk_cost",
    "estimate_walk_steps",
    "UNREACHABLE_WALK",
]
