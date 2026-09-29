"""Navigation config helpers: terrain, origin, farm/safe rects, home, loot."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from app.bot_log import get_logger
from app._03_world.terrain_map import configure_terrain_map, get_terrain_map
from app._03_world.world_coords import WorldOrigin
from app._03_world.map_pack import navigation_with_map_pack
from app._03_world.memory_sync import configure_map_origin
from app._04_decision.farm_area import (
    DEFAULT_COVERAGE_CELL,
    FarmRect,
    farm_rect_from_mapping,
)
from app._04_decision.hierarchical_path import DEFAULT_CLUSTER, CoarseMap
from app._04_decision.portal_graph import PortalGraph, build_portal_graph

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Legacy defaults when no map pack is active (tests / old configs).
_DEFAULT_AREAS_DIR = _PROJECT_ROOT / "areas"
_DEFAULT_FARM_FILE = _DEFAULT_AREAS_DIR / "farming_areas1.yaml"
_DEFAULT_SAFE_FILE = _DEFAULT_AREAS_DIR / "safe_areas.yaml"
_DEFAULT_HOME_FILE = _DEFAULT_AREAS_DIR / "home.yaml"

_coarse_map: Optional[CoarseMap] = None
_portal_graph: Optional[PortalGraph] = None
_cluster_size: int = DEFAULT_CLUSTER
_farm_areas: list[FarmRect] = []
_safe_areas: list[FarmRect] = []
_home_tile: Optional[tuple[int, int]] = None
_coverage_cell: int = DEFAULT_COVERAGE_CELL
_loot_mode: str = "all_items"


def get_coarse_map() -> Optional[CoarseMap]:
    return _coarse_map


def get_cluster_size() -> int:
    return _cluster_size


def set_coarse_map(coarse: Optional[CoarseMap]) -> None:
    global _coarse_map
    _coarse_map = coarse


def get_portal_graph() -> Optional[PortalGraph]:
    return _portal_graph


def set_portal_graph(graph: Optional[PortalGraph]) -> None:
    global _portal_graph
    _portal_graph = graph


def get_farm_areas() -> list[FarmRect]:
    return list(_farm_areas)


def get_safe_areas() -> list[FarmRect]:
    return list(_safe_areas)


def get_home_tile() -> Optional[tuple[int, int]]:
    return _home_tile


def get_coverage_cell() -> int:
    return _coverage_cell


def get_loot_mode() -> str:
    return _loot_mode


def set_loot_mode(mode: str) -> str:
    """Override session loot mode (``all_items`` or ``adena_only``)."""
    global _loot_mode
    from app._04_decision.player_mode import DEFAULT_LOOT_MODE, LOOT_MODE_ADENA, LOOT_MODE_ALL

    cleaned = str(mode).strip().lower()
    if cleaned not in (LOOT_MODE_ALL, LOOT_MODE_ADENA):
        cleaned = DEFAULT_LOOT_MODE
    _loot_mode = cleaned
    return _loot_mode


def get_active_farm(index: int) -> Optional[FarmRect]:
    """Active farm by index; wraps if index is past the end."""
    if not _farm_areas:
        return None
    return _farm_areas[index % len(_farm_areas)]


def nearest_safe_area(
    start: tuple[int, int],
    terrain: Optional[Any] = None,
    *,
    exclude: Optional[FarmRect] = None,
) -> Optional[tuple[FarmRect, tuple[int, int]]]:
    """Nearest safe rect + walkable entry tile from ``start``.

    Prefers walkable entry when terrain is available; otherwise rect center.
    When ``exclude`` is set, that rect is skipped (used to pick another safe).
    """
    from app._03_world.terrain_map import TerrainMap

    if not _safe_areas:
        return None
    best: Optional[tuple[FarmRect, tuple[int, int]]] = None
    best_d: Optional[int] = None
    from app._03_world.world_coords import tile_chebyshev

    for rect in _safe_areas:
        if exclude is not None and rect == exclude:
            continue
        if isinstance(terrain, TerrainMap):
            entry = rect.nearest_walkable(terrain, start)
            if entry is None:
                continue
        else:
            entry = rect.center()
        d = tile_chebyshev(start[0], start[1], entry[0], entry[1])
        if best_d is None or d < best_d:
            best_d = d
            best = (rect, entry)
    return best


def safe_containing(tile: tuple[int, int]) -> Optional[FarmRect]:
    """First configured safe rect that contains ``tile``, or None."""
    for rect in _safe_areas:
        if rect.contains(tile[0], tile[1]):
            return rect
    return None


def safe_for_goal(goal: Optional[tuple[int, int]]) -> Optional[FarmRect]:
    """Safe rect that contains ``goal``, if any."""
    if goal is None:
        return None
    return safe_containing(goal)


def world_origin_from_config(config: Optional[dict[str, Any]] = None) -> WorldOrigin:
    """Read optional ``navigation.origin_x/y`` (default 0,0)."""
    section = (config or {}).get("navigation") or {}
    return WorldOrigin(
        x=int(section.get("origin_x", 0)),
        y=int(section.get("origin_y", 0)),
    )


def _resolve_path(raw: Any, *, default: Optional[Path]) -> Optional[Path]:
    """Resolve a path; ``False`` / empty string disables file load."""
    if raw is False or raw == "":
        return None
    if raw is None:
        return default
    path = Path(str(raw))
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path


def _load_yaml_file(path: Optional[Path]) -> Any:
    if path is None or not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rects_from_yaml_doc(doc: Any, *, key: str) -> list[FarmRect]:
    """Accept ``{areas: [...]}``, ``{farm_areas: [...]}``, or a bare list."""
    if doc is None:
        return []
    raw: Any = doc
    if isinstance(doc, dict):
        for candidate in ("areas", key, "farm_areas", "safe_areas"):
            if candidate in doc and isinstance(doc[candidate], list):
                raw = doc[candidate]
                break
        else:
            return []
    return _load_rect_list(raw, key=key)


def _home_tile_from_yaml_doc(doc: Any) -> Optional[tuple[int, int]]:
    """Home as explicit x/y, or center of the first rect in ``areas``."""
    if doc is None:
        return None
    if isinstance(doc, dict):
        if "home_x" in doc and "home_y" in doc:
            return int(doc["home_x"]), int(doc["home_y"])
        if "x" in doc and "y" in doc:
            return int(doc["x"]), int(doc["y"])
        rects = _rects_from_yaml_doc(doc, key="home")
        if rects:
            return rects[0].center()
    return None


def _load_rect_list(raw: Any, *, key: str) -> list[FarmRect]:
    rects: list[FarmRect] = []
    if not isinstance(raw, list):
        return rects
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"navigation.{key}[{i}] must be a mapping")
        rects.append(farm_rect_from_mapping(item, index=i))
    return rects


def _load_farms_and_home(section: dict[str, Any]) -> None:
    global _farm_areas, _safe_areas, _home_tile, _coverage_cell
    _coverage_cell = int(section.get("coverage_cell", DEFAULT_COVERAGE_CELL))

    dungeon_pack = False
    from app._03_world.map_pack import get_active_map_pack
    from app._04_decision.dungeon import is_dungeon_map

    pack = get_active_map_pack()
    if pack is not None:
        dungeon_pack = is_dungeon_map(pack.id, pack.name)
    farm_file = _resolve_path(
        section.get("farm_areas_file"),
        default=None if dungeon_pack else _DEFAULT_FARM_FILE,
    )
    safe_file = _resolve_path(
        section.get("safe_areas_file"), default=_DEFAULT_SAFE_FILE
    )
    home_file = _resolve_path(section.get("home_file"), default=_DEFAULT_HOME_FILE)

    # Files first (pack or legacy areas/*.yaml), then non-empty inline lists override.
    _farm_areas = _rects_from_yaml_doc(
        _load_yaml_file(farm_file), key="farm_areas"
    )
    _safe_areas = _rects_from_yaml_doc(
        _load_yaml_file(safe_file), key="safe_areas"
    )
    inline_farms = section.get("farm_areas") or []
    inline_safe = section.get("safe_areas") or []
    if isinstance(inline_farms, list) and inline_farms:
        _farm_areas = _load_rect_list(inline_farms, key="farm_areas")
    if isinstance(inline_safe, list) and inline_safe:
        _safe_areas = _load_rect_list(inline_safe, key="safe_areas")

    _home_tile = _home_tile_from_yaml_doc(_load_yaml_file(home_file))
    if "home_x" in section and "home_y" in section:
        # Explicit config home wins (including when intentionally set).
        _home_tile = (int(section["home_x"]), int(section["home_y"]))

    get_logger("nav").info(
        "farms=%s safe=%s home=%s (files farm=%s safe=%s home=%s)",
        len(_farm_areas),
        len(_safe_areas),
        _home_tile,
        farm_file,
        safe_file,
        home_file,
    )


def _load_farming_options(config: Optional[dict[str, Any]]) -> None:
    global _loot_mode
    from app._04_decision.player_mode import DEFAULT_LOOT_MODE, LOOT_MODE_ADENA, LOOT_MODE_ALL

    section = (config or {}).get("farming") or {}
    mode = str(section.get("loot_mode", DEFAULT_LOOT_MODE)).strip().lower()
    if mode not in (LOOT_MODE_ALL, LOOT_MODE_ADENA):
        mode = DEFAULT_LOOT_MODE
    _loot_mode = mode


def configure_navigation(config: Optional[dict[str, Any]] = None) -> WorldOrigin:
    """Load terrain, portal graph, farm/safe rects, home; return origin seed.

    When ``navigation.maps_dir`` + ``active_map`` are set, terrain path and
    world origin come from ``maps/<id>/meta.yaml``. Otherwise legacy
    ``terrain_map`` / ``map_origin_*`` keys are used.
    """
    global _cluster_size
    cfg = navigation_with_map_pack(config)
    section = (cfg or {}).get("navigation") or {}
    _cluster_size = int(section.get("cluster_size", DEFAULT_CLUSTER))
    configure_terrain_map(cfg)
    terrain = get_terrain_map()
    if terrain is not None:
        set_coarse_map(CoarseMap.from_terrain(terrain, _cluster_size))
        log = get_logger("nav")
        log.info(
            "building portal graph (cluster=%s, %sx%s)",
            _cluster_size,
            terrain.width,
            terrain.height,
        )
        import time

        t0 = time.perf_counter()
        graph = build_portal_graph(terrain, _cluster_size)
        set_portal_graph(graph)
        log.info(
            "portal graph: %s components, %.0f ms",
            graph.node_count,
            (time.perf_counter() - t0) * 1000.0,
        )
    else:
        set_coarse_map(None)
        set_portal_graph(None)
    _load_farms_and_home(section)
    _load_farming_options(cfg)
    from app._04_decision.patrol import configure_patrol_waypoints

    configure_patrol_waypoints(terrain=get_terrain_map())
    configure_map_origin(cfg)
    return world_origin_from_config(cfg)


def configure_navigation_for_map(
    config: dict[str, Any],
    map_id: str,
) -> WorldOrigin:
    """Reload terrain, origin, and areas for ``map_id`` (live talking-scroll hop).

    Drops previous farm/safe/home overlays so the new pack files win.
    Does not change the operator's Setup map selection.
    """
    nav = dict(config.get("navigation") or {})
    nav["active_map"] = str(map_id).strip()
    for key in ("farm_areas", "farm_areas_file", "safe_areas_file", "home_file"):
        nav.pop(key, None)
    config["navigation"] = nav
    return configure_navigation(config)


# -- async nav reload (shopping can proceed while terrain/portal rebuilds) ----

_nav_async_lock = threading.Lock()
_nav_async_thread: Optional[threading.Thread] = None
_nav_async_busy: bool = False
_nav_async_error: Optional[str] = None


def navigation_configure_in_progress() -> bool:
    """True while a background ``configure_navigation_for_map`` is running."""
    return bool(_nav_async_busy)


def navigation_configure_error() -> Optional[str]:
    return _nav_async_error


def configure_map_origin_for_map(
    config: dict[str, Any],
    map_id: str,
) -> WorldOrigin:
    """Update game↔nav origin for ``map_id`` without rebuilding terrain/portals.

    Shopping only needs memory position + this origin. Full navigation (walk /
    pathfinding) is started separately via
    ``start_configure_navigation_for_map_async``.
    """
    from app._03_world.map_pack import load_map_pack, resolve_maps_dir

    mid = str(map_id).strip()
    section = dict(config.get("navigation") or {})
    section["active_map"] = mid
    for key in ("farm_areas", "farm_areas_file", "safe_areas_file", "home_file"):
        section.pop(key, None)

    maps_dir = resolve_maps_dir({"navigation": section})
    if maps_dir is not None and mid:
        pack = load_map_pack(maps_dir, mid, section=section)
        section["terrain_map"] = str(pack.terrain_path)
        section["map_origin_x"] = pack.origin_x
        section["map_origin_y"] = pack.origin_y
        section["pixel_scale"] = pack.pixel_scale
        if pack.clearance_tiles is not None:
            section["clearance_tiles"] = pack.clearance_tiles
        if pack.wall_penalty is not None:
            section["wall_penalty"] = pack.wall_penalty
        if pack.cluster_size is not None:
            section["cluster_size"] = pack.cluster_size
        if not section.get("farm_areas_file") and pack.farm_areas_path is not None:
            section["farm_areas_file"] = str(pack.farm_areas_path)
        if not section.get("safe_areas_file") and pack.safe_areas_path is not None:
            section["safe_areas_file"] = str(pack.safe_areas_path)
        if not section.get("home_file") and pack.home_path is not None:
            section["home_file"] = str(pack.home_path)

    config["navigation"] = section
    # Origin globals only — do not set_active_map_pack (keeps _can_walk false
    # until the background full configure finishes).
    configure_map_origin({"navigation": section})
    return world_origin_from_config({"navigation": section})


def start_configure_navigation_for_map_async(
    config: dict[str, Any],
    map_id: str,
) -> None:
    """Run ``configure_navigation_for_map`` on a daemon thread (non-blocking)."""
    global _nav_async_thread, _nav_async_busy, _nav_async_error

    mid = str(map_id).strip()
    if not mid:
        return

    # Snapshot config so the worker is not racing the live dict mid-tick.
    cfg: dict[str, Any] = {key: value for key, value in config.items() if key != "navigation"}
    cfg["navigation"] = dict(config.get("navigation") or {})

    def _worker() -> None:
        global _nav_async_busy, _nav_async_error
        log = get_logger("nav")
        try:
            log.info("async nav configure start map=%s", mid)
            t0 = time.perf_counter()
            # Drop walk graphs until rebuild finishes so travel does not use a
            # half-switched pack (shopping only needs map origin, already set).
            set_portal_graph(None)
            set_coarse_map(None)
            configure_navigation_for_map(cfg, mid)
            # Push finished nav section back so callers see the active pack keys.
            config["navigation"] = dict(cfg.get("navigation") or {})
            log.info(
                "async nav configure done map=%s (%.0f ms)",
                mid,
                (time.perf_counter() - t0) * 1000.0,
            )
            _nav_async_error = None
        except Exception as exc:
            _nav_async_error = str(exc)
            log.exception("async nav configure failed map=%s: %s", mid, exc)
        finally:
            with _nav_async_lock:
                _nav_async_busy = False

    with _nav_async_lock:
        if _nav_async_busy and _nav_async_thread is not None and _nav_async_thread.is_alive():
            # A reload is already running; leave it (map_id should match hop).
            return
        _nav_async_busy = True
        _nav_async_error = None
        _nav_async_thread = threading.Thread(
            target=_worker,
            name=f"nav-configure-{mid}",
            daemon=True,
        )
        _nav_async_thread.start()


def wait_navigation_configure(*, timeout_s: Optional[float] = None) -> bool:
    """Block until background nav configure finishes. True if idle/ready."""
    thread = _nav_async_thread
    if thread is None or not thread.is_alive():
        return not _nav_async_busy
    thread.join(timeout=timeout_s)
    return not (thread.is_alive() or _nav_async_busy)


__all__ = [
    "configure_navigation",
    "configure_navigation_for_map",
    "configure_map_origin_for_map",
    "start_configure_navigation_for_map_async",
    "navigation_configure_in_progress",
    "navigation_configure_error",
    "wait_navigation_configure",
    "world_origin_from_config",
    "get_terrain_map",
    "get_coarse_map",
    "get_cluster_size",
    "set_coarse_map",
    "get_portal_graph",
    "set_portal_graph",
    "get_farm_areas",
    "get_safe_areas",
    "get_home_tile",
    "get_coverage_cell",
    "get_loot_mode",
    "set_loot_mode",
    "get_active_farm",
    "nearest_safe_area",
    "safe_containing",
    "safe_for_goal",
]
