"""Farm visit order: user-selected list order, then cycle."""
from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING, Optional, Sequence

from app._03_world.world_coords import tile_chebyshev
from app._04_decision.farm_area import FarmRect
from app._04_decision.nav_config import get_farm_areas

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard

# Exact TSP over centers is fine up to ~10 farms; beyond that use greedy.
_EXACT_TOUR_MAX = 10


def farm_center_distance(a: FarmRect, b: FarmRect) -> int:
    """Chebyshev distance between farm centers (tile metric)."""
    ax, ay = a.center()
    bx, by = b.center()
    return tile_chebyshev(ax, ay, bx, by)


def nearest_farm_index(
    farms: Sequence[FarmRect],
    origin: tuple[int, int],
) -> int:
    """Index of the farm whose center is closest to ``origin``."""
    if not farms:
        raise ValueError("no farm areas")
    ox, oy = origin
    best_i = 0
    best_d: Optional[int] = None
    for i, farm in enumerate(farms):
        cx, cy = farm.center()
        d = tile_chebyshev(ox, oy, cx, cy)
        if best_d is None or d < best_d:
            best_d = d
            best_i = i
    return best_i


def shortest_hamiltonian_cycle(
    farms: Sequence[FarmRect],
    start_index: int,
) -> list[int]:
    """Shortest cycle through all farms, reported starting at ``start_index``.

    Cost is Chebyshev between centers. Uses exact permutation search when
    ``len(farms) <= 10``; otherwise a nearest-neighbor cycle.
    """
    n = len(farms)
    if n == 0:
        return []
    if n == 1:
        return [start_index]
    if start_index < 0 or start_index >= n:
        raise ValueError(f"start_index {start_index} out of range for {n} farms")

    if n > _EXACT_TOUR_MAX:
        return _nearest_neighbor_cycle(farms, start_index)

    others = [i for i in range(n) if i != start_index]
    best_order: Optional[list[int]] = None
    best_len = math.inf
    for perm in itertools.permutations(others):
        order = [start_index, *perm]
        length = 0
        for a, b in zip(order, order[1:]):
            length += farm_center_distance(farms[a], farms[b])
        length += farm_center_distance(farms[order[-1]], farms[order[0]])
        if length < best_len:
            best_len = length
            best_order = order
    assert best_order is not None
    return best_order


def _nearest_neighbor_cycle(
    farms: Sequence[FarmRect],
    start_index: int,
) -> list[int]:
    n = len(farms)
    remaining = set(range(n))
    order = [start_index]
    remaining.remove(start_index)
    while remaining:
        cur = order[-1]
        nxt = min(
            remaining,
            key=lambda j: farm_center_distance(farms[cur], farms[j]),
        )
        order.append(nxt)
        remaining.remove(nxt)
    return order


def user_farm_tour(n: int) -> list[int]:
    """Visit farms in the order they were loaded (schedule list order)."""
    return list(range(n))


def ensure_farm_tour(blackboard: "Blackboard") -> None:
    """Build tour once from the scheduled farm list order.

    Sets ``farm_tour``, ``farm_tour_pos``, and ``farm_area_index``.
    If the character is already inside a scheduled farm, resume there.
    """
    farms = get_farm_areas()
    if not farms:
        blackboard.farm_tour = []
        blackboard.farm_tour_pos = 0
        blackboard.farm_area_index = 0
        return

    tour = blackboard.farm_tour
    if tour and len(tour) == len(farms) and all(0 <= i < len(farms) for i in tour):
        # Keep existing tour; sync index from tour position.
        pos = blackboard.farm_tour_pos % len(tour)
        blackboard.farm_tour_pos = pos
        blackboard.farm_area_index = tour[pos]
        return

    tour = user_farm_tour(len(farms))
    pos = 0
    ox = blackboard.world_origin.x
    oy = blackboard.world_origin.y
    for i, farm in enumerate(farms):
        if farm.contains(ox, oy):
            pos = i
            break
    blackboard.farm_tour = list(tour)
    blackboard.farm_tour_pos = pos
    blackboard.farm_area_index = tour[pos]


def advance_farm_tour(blackboard: "Blackboard") -> int:
    """Move to the next farm on the cycle; return the new farm index."""
    ensure_farm_tour(blackboard)
    tour = blackboard.farm_tour
    if not tour:
        return blackboard.farm_area_index
    blackboard.farm_tour_pos = (blackboard.farm_tour_pos + 1) % len(tour)
    blackboard.farm_area_index = tour[blackboard.farm_tour_pos]
    return blackboard.farm_area_index


__all__ = [
    "farm_center_distance",
    "nearest_farm_index",
    "shortest_hamiltonian_cycle",
    "user_farm_tour",
    "ensure_farm_tour",
    "advance_farm_tour",
]
