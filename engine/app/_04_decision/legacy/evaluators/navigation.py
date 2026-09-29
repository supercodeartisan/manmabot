"""Navigation evaluator: A* pathfinding on minimap occupancy grid."""
from __future__ import annotations

import heapq
import random
from typing import Optional

from app._04_decision.types import ActionIntent, ActionType
from app._03_world import WorldState
from app._03_world.objects import Position, distance_squared


class GridPoint:
    """A point on the occupancy grid."""
    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, GridPoint) and self.x == other.x == self.y

    def __hash__(self):
        return hash((self.x, self.y))

    def __repr__(self):
        return f"GridPoint({self.x}, {self.y})"


class OccupancyGrid:
    """2D occupancy grid for A* pathfinding."""

    def __init__(self, width: int, height: int, data: list[list[bool]] | None = None):
        self.width = width
        self.height = height
        if data is not None:
            self.grid = data
        else:
            self.grid = [[False for _ in range(width)] for _ in range(height)]

    def is_walkable(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height and not self.grid[y][x]

    def set_blocked(self, x: int, y: int, blocked: bool = True):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.grid[y][x] = blocked

    @classmethod
    def from_minimap(cls, minimap_image, grid_size: int = 50) -> "OccupancyGrid":
        """Create occupancy grid from minimap image (placeholder)."""
        # In real implementation, analyze minimap pixels for obstacles
        # For now, return empty grid
        return cls(grid_size, grid_size)


class Path:
    """A* path result."""

    def __init__(self, points: list[GridPoint]):
        self.points = points

    def is_empty(self) -> bool:
        return len(self.points) == 0

    def __len__(self):
        return len(self.points)


class PathFinder:
    """A* pathfinder on occupancy grid."""

    def __init__(self):
        self.directions = [
            (1, 0), (-1, 0), (0, 1), (0, -1),
            (1, 1), (1, -1), (-1, 1), (-1, -1),
        ]

    def find(self, grid: OccupancyGrid, start: GridPoint, goal: GridPoint) -> Path:
        """Find path using A* algorithm."""
        open_set = []
        heapq.heappush(open_set, (0, start))

        came_from = {}
        g_score = {start: 0}
        f_score = {start: self._heuristic(start, goal)}

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == goal:
                return self._reconstruct_path(came_from, current)

            for dx, dy in self.directions:
                neighbor = GridPoint(current.x + dx, current.y + dy)

                if not grid.is_walkable(neighbor.x, neighbor.y):
                    continue

                tentative_g = g_score[current] + (1.414 if dx != 0 and dy != 0 else 1.0)

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self._heuristic(neighbor, goal)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return Path([])  # No path found

    def _heuristic(self, a: GridPoint, b: GridPoint) -> float:
        return abs(a.x - b.x) + abs(a.y - b.y)

    def _reconstruct_path(self, came_from: dict, current: GridPoint) -> Path:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return Path(path)


class PathSmoother:
    """Smooth path by removing unnecessary waypoints."""

    def smooth(self, grid: OccupancyGrid, path: Path) -> Path:
        if path.is_empty() or len(path.points) < 3:
            return path

        smoothed = [path.points[0]]
        i = 0

        while i < len(path.points) - 1:
            j = len(path.points) - 1
            while j > i + 1:
                if self._line_of_sight(grid, path.points[i], path.points[j]):
                    break
                j -= 1
            smoothed.append(path.points[j])
            i = j

        return Path(smoothed)

    def _line_of_sight(self, grid: OccupancyGrid, a: GridPoint, b: GridPoint) -> bool:
        """Bresenham line of sight check."""
        x0, y0 = a.x, a.y
        x1, y1 = b.x, b.y

        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            if not grid.is_walkable(x0, y0):
                return False
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

        return True


class PathFollower:
    """Execute path by converting grid points to world coordinates."""

    def __init__(self, grid_width: int, grid_height: int, world_width: float = 1.0, world_height: float = 1.0):
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.world_width = world_width
        self.world_height = world_height

    def grid_to_world(self, point: GridPoint) -> Position:
        """Convert grid coordinates to normalized world coordinates."""
        return Position(
            x=point.x / self.grid_width,
            y=point.y / self.grid_height,
        )

    def execute(self, path: Path) -> list[Position]:
        """Convert path to world coordinate waypoints."""
        return [self.grid_to_world(p) for p in path.points]


# Global pathfinder instances
_path_finder = PathFinder()
_path_smoother = PathSmoother()
_path_follower = PathFollower(50, 50)


def evaluate(world_state: WorldState) -> ActionIntent | None:
    """Return SEARCHING/TRAVELING action toward a random or target destination."""
    player = world_state.player
    if player is None:
        return None

    minimap = world_state.minimap
    if minimap is None:
        # No minimap - return random search destination
        return _random_search_action(player.position)

    # Try to find path to a destination
    # For now, pick random destination on minimap
    grid = OccupancyGrid.from_minimap(minimap)
    start = GridPoint(grid.width // 2, grid.height // 2)
    dest = GridPoint(random.randint(0, grid.width - 1), random.randint(0, grid.height - 1))

    path = _path_finder.find(grid, start, dest)
    if path.is_empty():
        return _random_search_action(player.position)

    path = _path_smoother.smooth(grid, path)
    waypoints = _path_follower.execute(path)

    if not waypoints:
        return _random_search_action(player.position)

    # Return first waypoint as destination
    return ActionIntent(
        action=ActionType.SEARCHING,
        destination=waypoints[0],
        priority=0.2,
        reason="path to random destination",
    )


def _random_search_action(current_pos: Position) -> ActionIntent:
    """Generate random search destination."""
    import random
    return ActionIntent(
        action=ActionType.SEARCHING,
        destination=Position(
            x=max(0.1, min(0.9, current_pos.x + random.uniform(-0.2, 0.2))),
            y=max(0.1, min(0.9, current_pos.y + random.uniform(-0.2, 0.2))),
        ),
        priority=0.1,
        reason="random search",
    )


def evaluate_travel(world_state: WorldState, destination: Position) -> ActionIntent | None:
    """Evaluate travel to a specific destination using pathfinding."""
    player = world_state.player
    if player is None:
        return None

    minimap = world_state.minimap
    if minimap is None:
        return ActionIntent(
            action=ActionType.TRAVELING,
            destination=destination,
            priority=0.3,
            reason="direct travel (no minimap)",
        )

    grid = OccupancyGrid.from_minimap(minimap)
    start = GridPoint(grid.width // 2, grid.height // 2)
    dest_grid = GridPoint(
        int(destination.x * grid.width),
        int(destination.y * grid.height),
    )

    path = _path_finder.find(grid, start, dest_grid)
    if path.is_empty():
        return ActionIntent(
            action=ActionType.TRAVELING,
            destination=destination,
            priority=0.2,
            reason="no path found, direct travel",
        )

    path = _path_smoother.smooth(grid, path)
    waypoints = _path_follower.execute(path)

    if not waypoints:
        return ActionIntent(
            action=ActionType.TRAVELING,
            destination=destination,
            priority=0.2,
            reason="no waypoints, direct travel",
        )

    return ActionIntent(
        action=ActionType.TRAVELING,
        destination=waypoints[0],
        priority=0.3,
        reason="path to destination",
    )