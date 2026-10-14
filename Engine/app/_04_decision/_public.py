"""Decision: sticky PlayerMode policy → one ActionIntent per tick.

Hierarchy (see ``Docs/architecture/DECISION_HIERARCHY.md``):

- L1 ``DecisionManager.decide``
- L2 ``PlayerMode`` + ``mode_control`` transitions
- L3 ``mode_ticks`` priority ladders
- L4 concerns (shop, world_nav, farm, …)
- L5 emitters (``mode_actions``, travel/loot hops)
- L6 queries / schema (``combat_query``, ``hp_actions`` tables)
- L7 ``Blackboard``

Not a live behavior tree. ``Status`` in ``behavior_tree`` is kept as the
tick outcome type; BT composites / ``build_*_node`` / ``legacy/`` are gone.
"""
from .manager import DecisionManager
from .blackboard import Blackboard
from .types import ActionIntent
from .pathfinding import (
    find_path,
    is_click_valid,
    plan_travel_click,
    select_click_waypoint,
    waypoint_to_content,
)
from .hierarchical_path import (
    DEFAULT_CLUSTER,
    HIERARCHICAL_AREA_THRESHOLD,
    CoarseMap,
    find_coarse_path,
    plan_travel_click_hierarchical,
)
from .nav_config import (
    configure_navigation,
    get_active_farm,
    get_coarse_map,
    get_portal_graph,
    set_portal_graph,
    get_cluster_size,
    get_coverage_cell,
    get_farm_areas,
    get_home_tile,
    get_loot_mode,
    get_safe_areas,
    nearest_safe_area,
    set_loot_mode,
)

__all__ = [
    "DecisionManager",
    "Blackboard",
    "ActionIntent",
    "find_path",
    "is_click_valid",
    "plan_travel_click",
    "select_click_waypoint",
    "waypoint_to_content",
    "DEFAULT_CLUSTER",
    "HIERARCHICAL_AREA_THRESHOLD",
    "CoarseMap",
    "find_coarse_path",
    "plan_travel_click_hierarchical",
    "configure_navigation",
    "get_active_farm",
    "get_coarse_map",
    "get_portal_graph",
    "set_portal_graph",
    "get_cluster_size",
    "get_coverage_cell",
    "get_farm_areas",
    "get_home_tile",
    "get_loot_mode",
    "get_safe_areas",
    "nearest_safe_area",
    "set_loot_mode",
]
