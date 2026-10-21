"""Walk-step distance field around the leader (bounded reverse BFS).

One BFS from the leader tile gives the walk steps from every nearby tile to
the leader, so the member's real distance and its descent path come from the
same search. Steps match the client: 8-connected, unit cost, diagonal closed
by two blocked shoulders, N/E fences when the pack has them. Bodies block.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Optional

# Hard cap so a large follow_tiles never costs more than a 49×49 window.
MAX_FIELD_RADIUS = 24

_STEPS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)


def field_radius(follow_tiles: int) -> int:
    """Window half-size: room for a detour of about 2× the leash."""
    return max(8, min(MAX_FIELD_RADIUS, 2 * int(follow_tiles) + 2))


@dataclass(frozen=True)
class FollowField:
    leader: tuple[int, int]
    radius: int
    x0: int
    y0: int
    width: int
    height: int
    # Row-major walk steps to the leader; -1 = unreachable inside the window.
    dist: tuple[int, ...]
    blocked: frozenset[tuple[int, int]]
    terrain: Any

    def in_window(self, tile: tuple[int, int]) -> bool:
        x, y = int(tile[0]) - self.x0, int(tile[1]) - self.y0
        return 0 <= x < self.width and 0 <= y < self.height

    def steps(self, tile: tuple[int, int]) -> Optional[int]:
        """Walk steps from ``tile`` to the leader, ``None`` if not reached."""
        if not self.in_window(tile):
            return None
        d = self.dist[(int(tile[1]) - self.y0) * self.width + (int(tile[0]) - self.x0)]
        return None if d < 0 else d

    def walk_distance(self, tile: tuple[int, int], chebyshev: int) -> int:
        """Steps when reached; otherwise a value past the window (never "close")."""
        d = self.steps(tile)
        if d is not None:
            return d
        return max(int(chebyshev), self.radius + 1)

    def descent(
        self,
        start: tuple[int, int],
        *,
        stop_steps: int,
    ) -> list[tuple[int, int]]:
        """Path from ``start`` down the field until within ``stop_steps``.

        Includes ``start``. Among equal next steps, prefers the one nearest the
        leader so the walk stays straight. Empty when ``start`` is not reached.
        """
        d = self.steps(start)
        if d is None:
            return []
        lx, ly = self.leader
        stop = max(1, int(stop_steps))
        cx, cy = int(start[0]), int(start[1])
        path = [(cx, cy)]
        while d > stop:
            best: Optional[tuple[int, int]] = None
            best_key: Optional[tuple[int, int]] = None
            for dx, dy in _STEPS:
                nx, ny = cx + dx, cy + dy
                if self.steps((nx, ny)) != d - 1:
                    continue
                if not self._step_ok(cx, cy, nx, ny):
                    continue
                key = (
                    max(abs(nx - lx), abs(ny - ly)),
                    (nx - lx) * (nx - lx) + (ny - ly) * (ny - ly),
                )
                if best_key is None or key < best_key:
                    best, best_key = (nx, ny), key
            if best is None:
                break
            cx, cy = best
            d -= 1
            path.append(best)
        return path

    def pick_travel_offset(
        self,
        band: int,
        rng: Any,
        previous: Optional[tuple[int, int]] = None,
        *,
        move_dir: Optional[tuple[int, int]] = None,
        slot_distance: Optional[int] = None,
        lateral: int = 0,
    ) -> Optional[tuple[int, int]]:
        """Reynolds leader-following formation slot (behind + optional side).

        Ideal offset is behind the leader's move dir at ``slot_distance`` walk
        steps, with ``lateral`` (-1/0/1) for a slight flank. If that tile is
        blocked, the nearest in-band rear/side candidate is used. ``previous``
        is kept while still free and close to the ideal (sticky).
        """
        from .follow import formation_slot_offset, offset_behind_move

        b = max(1, int(band))
        dist = max(1, min(b, int(slot_distance) if slot_distance is not None else b))
        lat = max(-1, min(1, int(lateral)))
        lx, ly = self.leader

        def ok(dx: int, dy: int) -> bool:
            if dx == 0 and dy == 0:
                return False
            steps = self.steps((lx + dx, ly + dy))
            return steps is not None and 1 <= steps <= b

        ideal = formation_slot_offset(move_dir, dist, lateral=lat)
        if previous is not None:
            prev = (int(previous[0]), int(previous[1]))
            if ok(prev[0], prev[1]):
                # Sticky: keep while still near the ideal formation slot.
                if max(abs(prev[0] - ideal[0]), abs(prev[1] - ideal[1])) <= 2:
                    return prev
        if ok(ideal[0], ideal[1]):
            return ideal
        # Snap: prefer rear half-plane, then closest to ideal.
        candidates = [
            (dx, dy)
            for dy in range(-b, b + 1)
            for dx in range(-b, b + 1)
            if ok(dx, dy)
        ]
        if not candidates:
            return None
        rear = [c for c in candidates if offset_behind_move(c, move_dir)]
        pool = rear if rear else candidates

        def score(c: tuple[int, int]) -> tuple[int, int, int]:
            return (
                max(abs(c[0] - ideal[0]), abs(c[1] - ideal[1])),
                abs(c[0]) + abs(c[1]),
                abs(c[0]) + 1000 * abs(c[1]),
            )

        best = min(pool, key=score)
        # Stable pick among equal scores (rng only as tie-break).
        ties = [c for c in pool if score(c) == score(best)]
        return rng.choice(ties) if len(ties) > 1 else best

    def _open(self, x: int, y: int) -> bool:
        if (x, y) in self.blocked:
            return False
        try:
            return bool(self.terrain.is_walkable(x, y))
        except Exception:
            return False

    def _step_ok(self, ax: int, ay: int, bx: int, by: int) -> bool:
        if bool(getattr(self.terrain, "has_edge_fences", False)):
            return _can_step(self.terrain, ax, ay, bx, by)
        if not (self._open(ax, ay) and self._open(bx, by)):
            return False
        if ax != bx and ay != by:
            return self._open(bx, ay) or self._open(ax, by)
        return True


def _can_step(terrain: Any, ax: int, ay: int, bx: int, by: int) -> bool:
    try:
        return bool(terrain.can_step(ax, ay, bx, by))
    except Exception:
        return False


def build_follow_field(
    terrain: Any,
    leader: tuple[int, int],
    radius: int,
    blocked: Iterable[tuple[int, int]] = (),
) -> FollowField:
    """Reverse BFS from ``leader`` over a ``(2r+1)²`` window."""
    lx, ly = int(leader[0]), int(leader[1])
    r = max(1, int(radius))
    x0 = max(0, lx - r)
    y0 = max(0, ly - r)
    x1 = min(int(terrain.width), lx + r + 1)
    y1 = min(int(terrain.height), ly + r + 1)
    w = max(0, x1 - x0)
    h = max(0, y1 - y0)
    body = frozenset(
        (int(x), int(y))
        for x, y in blocked
        if x0 <= int(x) < x1 and y0 <= int(y) < y1 and (int(x), int(y)) != (lx, ly)
    )
    dist = [-1] * (w * h)
    if w == 0 or h == 0 or not terrain.is_walkable(lx, ly):
        return FollowField((lx, ly), r, x0, y0, w, h, tuple(dist), body, terrain)

    walk = terrain.walkable[y0:y1, x0:x1].tolist()
    for bx, by in body:
        walk[by - y0][bx - x0] = False
    fences = bool(getattr(terrain, "has_edge_fences", False))

    def open_(x: int, y: int) -> bool:
        return 0 <= x < w and 0 <= y < h and walk[y][x]

    sx, sy = lx - x0, ly - y0
    dist[sy * w + sx] = 0
    queue: deque[tuple[int, int]] = deque([(sx, sy)])
    while queue:
        cx, cy = queue.popleft()
        nd = dist[cy * w + cx] + 1
        for dx, dy in _STEPS:
            nx, ny = cx + dx, cy + dy
            if not open_(nx, ny):
                continue
            idx = ny * w + nx
            if dist[idx] >= 0:
                continue
            # The member walks neighbor → current, so test that direction.
            if fences:
                if not _can_step(terrain, nx + x0, ny + y0, cx + x0, cy + y0):
                    continue
            elif dx and dy and not (open_(cx, ny) or open_(nx, cy)):
                continue
            dist[idx] = nd
            queue.append((nx, ny))
    return FollowField((lx, ly), r, x0, y0, w, h, tuple(dist), body, terrain)


class FollowFieldCache:
    """Rebuild only when the leader tile, window, terrain, or bodies change."""

    def __init__(self) -> None:
        self._key: Optional[tuple[Any, ...]] = None
        self._field: Optional[FollowField] = None

    def get(
        self,
        terrain: Any,
        leader: tuple[int, int],
        radius: int,
        blocked: Iterable[tuple[int, int]] = (),
    ) -> FollowField:
        lx, ly = int(leader[0]), int(leader[1])
        r = max(1, int(radius))
        near = frozenset(
            (int(x), int(y))
            for x, y in blocked
            if abs(int(x) - lx) <= r and abs(int(y) - ly) <= r
        )
        key = (id(terrain), lx, ly, r, near)
        if self._field is None or key != self._key:
            self._field = build_follow_field(terrain, (lx, ly), r, near)
            self._key = key
        return self._field

    def clear(self) -> None:
        self._key = None
        self._field = None


__all__ = [
    "FollowField",
    "FollowFieldCache",
    "MAX_FIELD_RADIUS",
    "build_follow_field",
    "field_radius",
]
