"""Equal-length shortest path alternatives for same-map movement."""
from __future__ import annotations

import random

import numpy as np

from app._03_world.space.terrain_map import TerrainMap
from app._04_decision.pathfinding import (
    MAX_SHORTEST_ALTERNATIVES,
    find_path,
    find_path_random_shortest,
    list_shortest_paths,
    nudge_path_lateral,
    sticky_shortest_suffix,
)


def _terrain(walk: np.ndarray) -> TerrainMap:
    """Build a map without scipy (precomputed clearance/costs)."""
    arr = np.asarray(walk, dtype=bool)
    costs = np.where(arr, 1, 0).astype(np.int32)
    clearance = np.where(arr, 2, 0).astype(np.int32)
    return TerrainMap.from_array(arr, clearance=clearance, costs=costs)


def _open_rect(width: int, height: int) -> TerrainMap:
    return _terrain(np.ones((height, width), dtype=bool))


def test_list_shortest_paths_caps_under_five():
    terrain = _open_rect(6, 6)
    paths = list_shortest_paths(terrain, (0, 0), (5, 0), max_paths=10)
    assert 1 <= len(paths) <= MAX_SHORTEST_ALTERNATIVES
    lengths = {len(p) - 1 for p in paths}
    assert len(lengths) == 1
    assert lengths.pop() == len(find_path(terrain, (0, 0), (5, 0))) - 1


def test_open_field_has_multiple_equal_shortest():
    # Block the direct diagonal corridor so several length-equal detours remain.
    walk = np.ones((5, 5), dtype=bool)
    walk[1, 1] = False
    walk[2, 2] = False
    walk[3, 3] = False
    terrain = _terrain(walk)
    paths = list_shortest_paths(terrain, (0, 0), (4, 4))
    assert paths
    opt = len(paths[0]) - 1
    assert all(len(p) - 1 == opt for p in paths)
    unique = {tuple(p) for p in paths}
    assert len(unique) == len(paths)
    if len(paths) > 1:
        assert len(unique) > 1


def test_random_pick_stays_shortest_and_sticky():
    walk = np.ones((5, 5), dtype=bool)
    walk[1, 1] = False
    walk[2, 2] = False
    walk[3, 3] = False
    terrain = _terrain(walk)
    random.seed(0)
    first = find_path_random_shortest(
        terrain, (0, 0), (4, 4), apply_lateral_nudge=False
    )
    assert first
    opt = len(find_path(terrain, (0, 0), (4, 4))) - 1
    assert len(first) - 1 == opt
    # Midpoint along the chosen guide must reuse the same corridor.
    mid = first[len(first) // 2]
    reused = find_path_random_shortest(
        terrain, mid, (4, 4), sticky_path=first, apply_lateral_nudge=False
    )
    assert reused == sticky_shortest_suffix(first, terrain, mid, (4, 4))
    assert reused[0] == mid
    assert reused[-1] == (4, 4)


def test_unique_corridor_returns_one():
    walk = np.zeros((3, 5), dtype=bool)
    walk[1, :] = True  # single-tile hallway
    terrain = _terrain(walk)
    paths = list_shortest_paths(terrain, (0, 1), (4, 1))
    assert len(paths) == 1
    assert paths[0] == find_path(terrain, (0, 1), (4, 1))


def test_via_deform_recomputes_shortest_segments():
    terrain = _open_rect(12, 12)
    base = find_path(terrain, (0, 5), (11, 5))
    assert len(base) >= 5
    random.seed(1)
    deformed = nudge_path_lateral(terrain, base, (11, 5), nudge_count=2)
    assert deformed[0] == base[0] and deformed[-1] == base[-1]
    assert len(deformed) >= len(base)
    assert deformed != base
    for a, b in zip(deformed, deformed[1:]):
        assert terrain.can_step(a[0], a[1], b[0], b[1])
    assert set(deformed) - set(base)


def test_hallway_via_deform_stays_on_walkable():
    walk = np.zeros((3, 8), dtype=bool)
    walk[1, :] = True
    terrain = _terrain(walk)
    base = find_path(terrain, (0, 1), (7, 1))
    deformed = nudge_path_lateral(terrain, base, (7, 1), nudge_count=2)
    assert deformed[0] == base[0] and deformed[-1] == base[-1]
    for x, y in deformed:
        assert terrain.is_walkable(x, y)
    for a, b in zip(deformed, deformed[1:]):
        assert terrain.can_step(a[0], a[1], b[0], b[1])
