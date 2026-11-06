"""Party hunt dots follow the nav grid, not whoever is standing there."""
from __future__ import annotations

from app._03_world.space.hunt_point import hunt_point_refused


class _Grid:
    def __init__(self, cells: set[tuple[int, int]], closed: set[tuple[int, int]] | None = None):
        self.cells = cells
        self.closed = closed or set()

    def is_walkable(self, x: int, y: int) -> bool:
        return (int(x), int(y)) in self.cells

    def can_step(self, ax: int, ay: int, bx: int, by: int) -> bool:
        a = (int(ax), int(ay))
        b = (int(bx), int(by))
        if a not in self.cells or b not in self.cells:
            return False
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            return False
        return (a, b) not in self.closed


def test_blocked_and_fenced_dots_are_refused() -> None:
    grid = _Grid({(1, 1), (2, 1)}, closed={((2, 1), (1, 1))})
    assert hunt_point_refused(None, 1, 1)
    assert hunt_point_refused(grid, 0, 0)
    assert hunt_point_refused(grid, 1, 1)
    assert not hunt_point_refused(grid, 2, 1)


if __name__ == "__main__":
    test_blocked_and_fenced_dots_are_refused()
    print("OK")
