"""Local check for the travel route-click chain. Not part of the bot."""
from __future__ import annotations

import numpy as np

from app._02_state.geometry import WorldOrigin
from app._03_world.space.terrain_map import TerrainMap
from app._04_decision.behaviors.travel import _next_route_click
from app._04_decision import doors


def grid(open_cells: set[tuple[int, int]], w: int = 8, h: int = 8) -> TerrainMap:
    walk = np.zeros((h, w), dtype=bool)
    for x, y in open_cells:
        walk[y, x] = True
    return TerrainMap(walkable=walk)


def main() -> None:
    doors.refresh_live_doors(None)
    # Straight hall along y=1, x=0..6. Hop 3 from x=0 lands on x=3.
    straight = {(x, 1) for x in range(7)}
    terrain = grid(straight)
    origin = WorldOrigin(x=0, y=1)
    guide = [(x, 1) for x in range(7)]
    got = _next_route_click(terrain, origin, guide, (6, 1), set(), max_hop=3)
    assert got == (3, 1), got

    # Corner. Walls make a click from (0,1) to (2,2) step on (1,2).
    # Route: (0,1) (1,1) (2,1) (2,2) (2,3)
    corner_open = {(0, 1), (1, 1), (2, 1), (2, 2), (2, 3)}
    terrain = grid(corner_open)
    origin = WorldOrigin(x=0, y=1)
    guide = [(0, 1), (1, 1), (2, 1), (2, 2), (2, 3)]
    got = _next_route_click(terrain, origin, guide, (2, 3), set(), max_hop=3)
    assert got == (2, 1), got
    # Once the live tile is on the corner approach, the new direction is clear.
    origin = WorldOrigin(x=1, y=1)
    got = _next_route_click(terrain, origin, guide, (2, 3), set(), max_hop=3)
    assert got == (2, 3), got
    # The cell after the turn is a wall, so the click stops on the first new cell.
    short = {(0, 1), (1, 1), (2, 1), (2, 2)}
    terrain = grid(short)
    got = _next_route_click(
        terrain, origin, [(0, 1), (1, 1), (2, 1), (2, 2)], (2, 2), set(), max_hop=3
    )
    assert got == (2, 2), got

    # Body on (2,1) shortens the straight hop to the cell before it.
    terrain = grid(straight)
    origin = WorldOrigin(x=0, y=1)
    got = _next_route_click(
        terrain, origin, [(x, 1) for x in range(7)], (6, 1), {(2, 1)}, max_hop=3
    )
    assert got == (1, 1), got

    # Goal tile is the last click even when the hop could see farther.
    terrain = grid(straight)
    origin = WorldOrigin(x=0, y=1)
    guide = [(x, 1) for x in range(7)]
    got = _next_route_click(terrain, origin, guide, (2, 1), set(), max_hop=3)
    assert got == (2, 1), got

    print("route click checks passed")


if __name__ == "__main__":
    main()
