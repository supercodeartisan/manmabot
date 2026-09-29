"""Movement planning: human-like SEARCHING legs inside a farm rect.

When a farm area is configured, legs are absolute-tile targets biased toward
under-visited coverage cells, clamped to the farm, and converted to battle
content clicks. Without a farm rect, the legacy battle-space spiral is used
(tests / free roam).
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app._03_world import Position
from app._03_world.battle_area import get_battle_area
from app._03_world.terrain_map import TerrainMap
from app._03_world.world_coords import (
    WorldOrigin,
    in_battle_click_region,
    tile_chebyshev,
    world_to_content,
)
from app._04_decision.farm_area import DEFAULT_COVERAGE_CELL, FarmRect
from app._04_decision.nav_config import (
    get_active_farm,
    get_coverage_cell,
    get_terrain_map,
)
from app._04_decision.species_rules import tile_in_hazard

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._04_decision.blackboard import Blackboard

# Legacy battle-space distances (normalized content units).
LEG_DIST_MIN = 0.3
LEG_DIST_MAX = 0.5

# Absolute-tile hop length while scanning a farm.
TILE_DIST_MIN = 5
TILE_DIST_MAX = 7

# When within this many tiles of a farm border, pull bearing toward the center
# so corner/edge clamps do not keep emitting tiny outbound hops.
EDGE_CENTER_BIAS_MARGIN = TILE_DIST_MAX

# Sweep tuning for farm searching (directional "lawn-mower" feeling).
BEARING_PERSIST_FARM_MIN = 12
BEARING_PERSIST_FARM_MAX = 20

# Angular jitter around the current sweep bearing (degrees).
ANGULAR_SIGMA_FARM_PERSIST_DEG_MIN = 3.0
ANGULAR_SIGMA_FARM_PERSIST_DEG_MAX = 8.0

# Angular jitter when starting a new sweep bearing.
# Keep it small to avoid zigzag wobble, but allow tiny variation for
# walkability.
ANGULAR_SIGMA_FARM_NEW_DEG_MIN = 0.0
ANGULAR_SIGMA_FARM_NEW_DEG_MAX = 2.0

ANGULAR_SIGMA_DEG_MIN = 10.0
ANGULAR_SIGMA_DEG_MAX = 45.0

BEARING_PERSIST_MIN = 3
BEARING_PERSIST_MAX = 5

SPIRAL_STEP_DEG = 90.0

MAX_WALKABILITY_ATTEMPTS = 12
LEG_HISTORY_SIZE = 32


def _player_anchor() -> Position:
    return get_battle_area().player_position


def _clamp_click(x: float, y: float) -> Position:
    return get_battle_area().clamp(x, y)


def _dist_to_farm_edge(farm: FarmRect, ox: int, oy: int) -> int:
    """Chebyshev-style inset: min tiles to any farm border (0 = on edge)."""
    return min(ox - farm.x0, farm.x1 - ox, oy - farm.y0, farm.y1 - oy)


def _bearing_deg(ox: int, oy: int, tx: int, ty: int) -> float:
    return math.degrees(math.atan2(ty - oy, tx - ox))


def _blend_bearings_deg(a_deg: float, b_deg: float, weight_b: float) -> float:
    """Blend two headings as unit vectors; ``weight_b`` in [0, 1] toward ``b``."""
    w = max(0.0, min(1.0, float(weight_b)))
    ar = math.radians(a_deg)
    br = math.radians(b_deg)
    x = (1.0 - w) * math.cos(ar) + w * math.cos(br)
    y = (1.0 - w) * math.sin(ar) + w * math.sin(br)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return b_deg
    return math.degrees(math.atan2(y, x))


def bias_bearing_toward_farm_center(
    farm: FarmRect,
    ox: int,
    oy: int,
    bearing_deg: float,
    *,
    margin: int = EDGE_CENTER_BIAS_MARGIN,
) -> float:
    """Pull ``bearing_deg`` toward the farm center when near an edge/corner.

    Strength ramps from 0 (deeper than ``margin`` tiles inside) to 1 (on the
    border). Corners (near two edges) get at least a strong inward pull.
    """
    inset = _dist_to_farm_edge(farm, ox, oy)
    if inset > margin:
        return bearing_deg
    # Near two edges → treat as corner: full center bias.
    near_x = min(ox - farm.x0, farm.x1 - ox) <= margin
    near_y = min(oy - farm.y0, farm.y1 - oy) <= margin
    if near_x and near_y:
        weight = 1.0
    else:
        weight = 1.0 - (inset / float(margin))
    cx, cy = farm.center()
    if (cx, cy) == (ox, oy):
        return bearing_deg
    center = _bearing_deg(ox, oy, cx, cy)
    return _blend_bearings_deg(bearing_deg, center, weight)


@dataclass(frozen=True)
class MovementLeg:
    """One destination roll (a click the character walks to)."""

    tick: int
    timestamp: float
    reason: str
    bearing_deg: float
    leg_distance: float
    click: Position
    virtual_position: Position
    world_target: Position
    displacement: float
    mid_act: bool = False
    walkable: bool = True
    absolute_target: Optional[tuple[int, int]] = None

    def to_dict(self) -> dict:
        payload = {
            "tick": self.tick,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "bearing_deg": round(self.bearing_deg, 1),
            "leg_distance": round(self.leg_distance, 4),
            "displacement": round(self.displacement, 4),
            "click_x": round(self.click.x, 4),
            "click_y": round(self.click.y, 4),
            "virtual_x": round(self.virtual_position.x, 4),
            "virtual_y": round(self.virtual_position.y, 4),
            "world_target_x": round(self.world_target.x, 4),
            "world_target_y": round(self.world_target.y, 4),
            "mid_act": self.mid_act,
            "walkable": self.walkable,
        }
        if self.absolute_target is not None:
            payload["abs_x"] = self.absolute_target[0]
            payload["abs_y"] = self.absolute_target[1]
        return payload


class MovementPlanner:
    """Stateless per-leg: all movement state lives on the blackboard."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def next_leg(
        self,
        blackboard: "Blackboard",
        reason: str,
        *,
        persist: bool = False,
        legacy_spiral: bool = False,
    ) -> Position:
        farm = get_active_farm(blackboard.farm_area_index)
        terrain = get_terrain_map()
        if (
            not legacy_spiral
            and farm is not None
            and terrain is not None
        ):
            return self._next_leg_farm(
                blackboard, reason, farm, terrain, persist=persist
            )
        return self._next_leg_spiral(blackboard, reason, persist=persist)

    # -- farm coverage scan -------------------------------------------------

    def _next_leg_farm(
        self,
        bb: "Blackboard",
        reason: str,
        farm: FarmRect,
        terrain: TerrainMap,
        *,
        persist: bool,
    ) -> Position:
        cell = get_coverage_cell()
        ox, oy = bb.world_origin.x, bb.world_origin.y

        continuing = persist and bb.bearing_legs > 0 and bb.bearing_legs < bb.bearing_legs_target
        if continuing:
            bearing = bb.movement_bearing_deg
            bb.bearing_legs += 1
            sigma_base = self._rng.uniform(
                ANGULAR_SIGMA_FARM_PERSIST_DEG_MIN,
                ANGULAR_SIGMA_FARM_PERSIST_DEG_MAX,
            )
        else:
            # Turn between sweeps:
            # - first leg in a session -> pick a coverage-biased direction
            # - later legs (and stuck re-plans) -> rotate ~90° to avoid zigzag
            if bb.bearing_legs == 0 or not persist:
                bearing = self._coverage_bearing(bb, farm, ox, oy, cell)
            else:
                bearing = bb.movement_bearing_deg + 90.0

            bb.bearing_legs = 1
            bb.bearing_legs_target = self._rng.randint(
                BEARING_PERSIST_FARM_MIN, BEARING_PERSIST_FARM_MAX
            )
            sigma_base = self._rng.uniform(
                ANGULAR_SIGMA_FARM_NEW_DEG_MIN,
                ANGULAR_SIGMA_FARM_NEW_DEG_MAX,
            )

        # Edge/corner: pull heading inward so clamped hops do not thrash.
        bearing = bias_bearing_toward_farm_center(farm, ox, oy, bearing)
        bb.movement_bearing_deg = bearing

        abs_target, click, tiles, walkable = self._sample_farm_click(
            bb, farm, terrain, bearing, sigma_base=sigma_base
        )
        rx = abs_target[0] - ox
        ry = abs_target[1] - oy
        content = click

        bb.virtual_position = content

        anchor = _player_anchor()
        bb.leg_history.append(
            MovementLeg(
                tick=bb.tick_count,
                timestamp=time.time(),
                reason=reason,
                bearing_deg=bearing,
                leg_distance=float(tiles),
                click=content,
                virtual_position=bb.virtual_position,
                world_target=Position(x=float(abs_target[0]), y=float(abs_target[1])),
                displacement=math.hypot(content.x - anchor.x, content.y - anchor.y),
                mid_act=False,
                walkable=walkable,
                absolute_target=abs_target,
            )
        )
        return content

    def _coverage_bearing(
        self,
        bb: "Blackboard",
        farm: FarmRect,
        ox: int,
        oy: int,
        cell: int,
    ) -> float:
        """Bearing toward a nearby under-visited coverage cell (degrees)."""
        target = self._pick_under_visited_cell(bb, farm, ox, oy, cell)
        if target is None:
            return bb.movement_bearing_deg + SPIRAL_STEP_DEG
        tx, ty = target
        return math.degrees(math.atan2(ty - oy, tx - ox))

    def _pick_under_visited_cell(
        self,
        bb: "Blackboard",
        farm: FarmRect,
        ox: int,
        oy: int,
        cell: int,
    ) -> Optional[tuple[int, int]]:
        """Return center tile of a low-visit cell near the player."""
        cx0 = farm.x0 // cell
        cy0 = farm.y0 // cell
        cx1 = farm.x1 // cell
        cy1 = farm.y1 // cell
        best_visit = None
        candidates: list[tuple[int, int, int, int]] = []  # visit, dist, cx, cy
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                # Cell must overlap the farm.
                x_lo = max(farm.x0, cx * cell)
                y_lo = max(farm.y0, cy * cell)
                x_hi = min(farm.x1, (cx + 1) * cell - 1)
                y_hi = min(farm.y1, (cy + 1) * cell - 1)
                if x_lo > x_hi or y_lo > y_hi:
                    continue
                mid = ((x_lo + x_hi) // 2, (y_lo + y_hi) // 2)
                if tile_in_hazard(bb, mid[0], mid[1]):
                    continue
                visits = bb.farm_visit.get((cx, cy), 0)
                dist = tile_chebyshev(ox, oy, mid[0], mid[1])
                if best_visit is None or visits < best_visit:
                    best_visit = visits
                    candidates = [(visits, dist, mid[0], mid[1])]
                elif visits == best_visit:
                    candidates.append((visits, dist, mid[0], mid[1]))
        if not candidates:
            return None
        # Prefer nearer under-visited cells; slight randomness among top.
        candidates.sort(key=lambda c: (c[0], c[1]))
        top = candidates[: max(1, min(5, len(candidates)))]
        pick = top[self._rng.randrange(len(top))]
        return pick[2], pick[3]

    def _sample_farm_click(
        self,
        bb: "Blackboard",
        farm: FarmRect,
        terrain: TerrainMap,
        bearing_deg: float,
        *,
        sigma_base: float,
    ) -> tuple[tuple[int, int], Position, int, bool]:
        ox, oy = bb.world_origin.x, bb.world_origin.y
        # Outside the farm: never clamp a short hop onto a distant edge —
        # that produces huge relative WCS → wild content UV clicks.
        # Enter-farm travel must run first.
        if not farm.contains(ox, oy):
            return (ox, oy), _player_anchor(), 0, False

        sigma = sigma_base
        last_tiles = TILE_DIST_MIN
        for attempt in range(MAX_WALKABILITY_ATTEMPTS):
            tiles = self._rng.randint(TILE_DIST_MIN, TILE_DIST_MAX)
            widen = sigma if attempt == 0 else sigma * 2.0
            angle = math.radians(bearing_deg + self._rng.gauss(0.0, widen))
            dx = int(round(math.cos(angle) * tiles))
            dy = int(round(math.sin(angle) * tiles))
            if dx == 0 and dy == 0:
                dx = 1 if abs(math.cos(angle)) >= abs(math.sin(angle)) else 0
                dy = 0 if dx else (1 if math.sin(angle) >= 0 else -1)
            tx, ty = farm.clamp(ox + dx, oy + dy)
            if (tx, ty) == (ox, oy):
                # Nudge toward farm center if stuck on a point.
                cx, cy = farm.center()
                tx, ty = farm.clamp(
                    ox + (1 if cx >= ox else -1),
                    oy + (1 if cy >= oy else -1),
                )
            if not terrain.is_walkable(tx, ty):
                last_tiles = tiles
                continue
            if tile_in_hazard(bb, tx, ty):
                last_tiles = tiles
                continue
            rx, ry = tx - ox, ty - oy
            if not in_battle_click_region(rx, ry):
                # Shrink toward origin until inside click parallelogram.
                stepped = self._shrink_into_click(ox, oy, tx, ty)
                if stepped is None:
                    continue
                tx, ty = stepped
                if not farm.contains(tx, ty) or not terrain.is_walkable(tx, ty):
                    continue
                if tile_in_hazard(bb, tx, ty):
                    continue
                rx, ry = tx - ox, ty - oy
                if not in_battle_click_region(rx, ry):
                    continue
            click = world_to_content(float(rx), float(ry))
            return (tx, ty), click, tiles, True
        # Soft: if every sample hit a hazard, retry without hazard filter.
        for attempt in range(MAX_WALKABILITY_ATTEMPTS):
            tiles = self._rng.randint(TILE_DIST_MIN, TILE_DIST_MAX)
            widen = sigma if attempt == 0 else sigma * 2.0
            angle = math.radians(bearing_deg + self._rng.gauss(0.0, widen))
            dx = int(round(math.cos(angle) * tiles))
            dy = int(round(math.sin(angle) * tiles))
            if dx == 0 and dy == 0:
                dx = 1 if abs(math.cos(angle)) >= abs(math.sin(angle)) else 0
                dy = 0 if dx else (1 if math.sin(angle) >= 0 else -1)
            tx, ty = farm.clamp(ox + dx, oy + dy)
            if (tx, ty) == (ox, oy):
                cx, cy = farm.center()
                tx, ty = farm.clamp(
                    ox + (1 if cx >= ox else -1),
                    oy + (1 if cy >= oy else -1),
                )
            if not terrain.is_walkable(tx, ty):
                last_tiles = tiles
                continue
            rx, ry = tx - ox, ty - oy
            if not in_battle_click_region(rx, ry):
                stepped = self._shrink_into_click(ox, oy, tx, ty)
                if stepped is None:
                    continue
                tx, ty = stepped
                if not farm.contains(tx, ty) or not terrain.is_walkable(tx, ty):
                    continue
                rx, ry = tx - ox, ty - oy
                if not in_battle_click_region(rx, ry):
                    continue
            click = world_to_content(float(rx), float(ry))
            return (tx, ty), click, tiles, True
        # No valid in-view hop: stay put rather than emit an uncapped click.
        return (ox, oy), _player_anchor(), last_tiles, False

    def _shrink_into_click(
        self,
        ox: int,
        oy: int,
        tx: int,
        ty: int,
    ) -> Optional[tuple[int, int]]:
        """Walk from target toward origin until relative tile is clickable."""
        x, y = tx, ty
        for _ in range(64):
            if (x, y) == (ox, oy):
                return None
            if in_battle_click_region(x - ox, y - oy):
                return x, y
            sx = 0 if x == ox else (1 if ox > x else -1)
            sy = 0 if y == oy else (1 if oy > y else -1)
            x += sx
            y += sy
        return None

    @staticmethod
    def _mark_visit(bb: "Blackboard", x: int, y: int, cell: int) -> None:
        key = (x // cell, y // cell)
        bb.farm_visit[key] = bb.farm_visit.get(key, 0) + 1

    # -- legacy spiral (no farm / no terrain) -------------------------------

    def _next_leg_spiral(
        self,
        bb: "Blackboard",
        reason: str,
        *,
        persist: bool,
    ) -> Position:
        if persist and bb.bearing_legs < bb.bearing_legs_target:
            bearing = bb.movement_bearing_deg
            bb.bearing_legs += 1
        else:
            bearing = bb.movement_bearing_deg + SPIRAL_STEP_DEG
            bb.movement_bearing_deg = bearing
            bb.bearing_legs = 0
            bb.bearing_legs_target = self._rng.randint(
                BEARING_PERSIST_MIN, BEARING_PERSIST_MAX
            )

        leg_distance, click, world_target, walkable = self._sample_click(bb, bearing)
        anchor = _player_anchor()
        bb.virtual_position = world_target
        bb.leg_history.append(
            MovementLeg(
                tick=bb.tick_count,
                timestamp=time.time(),
                reason=reason,
                bearing_deg=bearing,
                leg_distance=leg_distance,
                click=click,
                virtual_position=bb.virtual_position,
                world_target=world_target,
                displacement=math.hypot(click.x - anchor.x, click.y - anchor.y),
                mid_act=False,
                walkable=walkable,
            )
        )
        return click

    def _sample_click(
        self, bb: "Blackboard", bearing_deg: float
    ) -> tuple[float, Position, Position, bool]:
        sigma_deg = self._rng.uniform(
            ANGULAR_SIGMA_DEG_MIN, ANGULAR_SIGMA_DEG_MAX
        )
        leg_distance = self._sample_distance()
        click = self._click_for(bearing_deg, sigma_deg, leg_distance)
        world_target = self._world_target(bb, click)
        if bb.is_walkable(world_target):
            return leg_distance, click, world_target, True

        for _ in range(MAX_WALKABILITY_ATTEMPTS - 1):
            leg_distance = self._sample_distance()
            click = self._click_for(bearing_deg, sigma_deg * 2.0, leg_distance)
            world_target = self._world_target(bb, click)
            if bb.is_walkable(world_target):
                return leg_distance, click, world_target, True
        return leg_distance, click, world_target, False

    def _world_target(self, bb: "Blackboard", click: Position) -> Position:
        anchor = _player_anchor()
        return Position(
            x=bb.virtual_position.x + (click.x - anchor.x),
            y=bb.virtual_position.y + (click.y - anchor.y),
        )

    def _click_for(self, bearing_deg: float, sigma_deg: float, distance: float) -> Position:
        anchor = _player_anchor()
        angle = math.radians(bearing_deg + self._rng.gauss(0.0, sigma_deg))
        return _clamp_click(
            anchor.x + math.cos(angle) * distance,
            anchor.y + math.sin(angle) * distance,
        )

    def _sample_distance(self) -> float:
        r = self._rng.random()
        return LEG_DIST_MAX - (LEG_DIST_MAX - LEG_DIST_MIN) * math.sqrt(r)


__all__ = [
    "ANGULAR_SIGMA_DEG_MAX",
    "ANGULAR_SIGMA_DEG_MIN",
    "BEARING_PERSIST_MAX",
    "BEARING_PERSIST_MIN",
    "DEFAULT_COVERAGE_CELL",
    "EDGE_CENTER_BIAS_MARGIN",
    "LEG_DIST_MAX",
    "LEG_DIST_MIN",
    "LEG_HISTORY_SIZE",
    "MAX_WALKABILITY_ATTEMPTS",
    "MovementLeg",
    "MovementPlanner",
    "SPIRAL_STEP_DEG",
    "TILE_DIST_MAX",
    "TILE_DIST_MIN",
    "bias_bearing_toward_farm_center",
]
