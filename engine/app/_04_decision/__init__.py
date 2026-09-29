"""Decision Module: answers 'What should the bot do next?'

Input: GameState from World Data Module
Output: ActionIntent (high-level action request)

The decision logic is a behavior tree (see ``behavior_tree/`` and
``behaviors/``) owned by :class:`DecisionManager`. The pre-refactor
state-machine implementation is archived under ``legacy/``.
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
    world_origin_from_config,
)
from .farm_area import ARRIVE_TILES, DEFAULT_COVERAGE_CELL, FarmRect
from .player_mode import PlayerMode

__all__ = [
    "DecisionManager",
    "Blackboard",
    "ActionIntent",
    "PlayerMode",
    "find_path",
    "is_click_valid",
    "plan_travel_click",
    "select_click_waypoint",
    "waypoint_to_content",
    "configure_navigation",
    "world_origin_from_config",
    "get_coarse_map",
    "get_portal_graph",
    "set_portal_graph",
    "get_cluster_size",
    "get_farm_areas",
    "get_safe_areas",
    "get_home_tile",
    "get_active_farm",
    "get_coverage_cell",
    "get_loot_mode",
    "set_loot_mode",
    "nearest_safe_area",
    "FarmRect",
    "ARRIVE_TILES",
    "DEFAULT_COVERAGE_CELL",
    "DEFAULT_CLUSTER",
    "HIERARCHICAL_AREA_THRESHOLD",
    "CoarseMap",
    "find_coarse_path",
    "plan_travel_click_hierarchical",
]
