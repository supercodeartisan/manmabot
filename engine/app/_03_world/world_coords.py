"""Relative World Coordinate System (WCS) centered on the local player.

One WCS unit is the game's smallest object tile (player, NPC, small monster,
tree, etc.). The game world is **discrete integer tiles**. The affine map
produces continuous values that are snapped to nearest integers for all
public relative-world APIs.

Battle UV uses ``u=0`` left … ``u=1`` right, ``v=0`` top … ``v=1`` bottom.
Measured corner samples form a parallelogram:

  left-top     (0, 0) -> (  2, -18)
  right-top    (1, 0) -> ( 18,  -2)
  left-bottom  (0, 1) -> (-17,   1)
  right-bottom (1, 1) -> ( -1,  17)

Affine map (origin at left-top, basis U=(16,16), V=(-19,19)):

  wx =  2 + 16*u - 19*v
  wy = -18 + 16*u + 19*v

The default player anchor (u=1/2, v=10/19) maps exactly to (0, 0).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from app._03_world.battle_area import BattleArea, get_battle_area
from app._03_world.constants import MAGE_SPELL_RANGE
from app._03_world.objects import Position

# Measured battle corners in relative WCS (player = origin).
CORNER_LEFT_TOP = Position(2.0, -18.0)
CORNER_RIGHT_TOP = Position(18.0, -2.0)
CORNER_LEFT_BOTTOM = Position(-17.0, 1.0)
CORNER_RIGHT_BOTTOM = Position(-1.0, 17.0)

# Basis vectors of the battle parallelogram in WCS.
_U_X = CORNER_RIGHT_TOP.x - CORNER_LEFT_TOP.x  # 16
_U_Y = CORNER_RIGHT_TOP.y - CORNER_LEFT_TOP.y  # 16
_V_X = CORNER_LEFT_BOTTOM.x - CORNER_LEFT_TOP.x  # -19
_V_Y = CORNER_LEFT_BOTTOM.y - CORNER_LEFT_TOP.y  # 19

# det([U V]) = 16*19 - 16*(-19) = 304 + 304 = 608
_DET = _U_X * _V_Y - _U_Y * _V_X


def round_half_away(x: float) -> int:
    """Nearest integer; halves round away from zero."""
    if x >= 0:
        return int(math.floor(x + 0.5))
    return int(math.ceil(x - 0.5))


def snap_world(wx: float, wy: float) -> Position:
    """Snap continuous WCS to discrete tiles (nearest integer)."""
    return Position(x=float(round_half_away(wx)), y=float(round_half_away(wy)))


def battle_uv_to_world_continuous(u: float, v: float) -> Position:
    """Map battle-local UV to continuous relative WCS (no snap)."""
    return Position(
        x=CORNER_LEFT_TOP.x + _U_X * u + _V_X * v,
        y=CORNER_LEFT_TOP.y + _U_Y * u + _V_Y * v,
    )


def battle_uv_to_world(u: float, v: float) -> Position:
    """Map battle-local UV to discrete relative WCS tiles."""
    c = battle_uv_to_world_continuous(u, v)
    return snap_world(c.x, c.y)


def world_to_battle_uv(wx: float, wy: float) -> Tuple[float, float]:
    """Inverse of the continuous affine map (accepts tile or float WCS)."""
    dx = wx - CORNER_LEFT_TOP.x
    dy = wy - CORNER_LEFT_TOP.y
    u = (_V_Y * dx - _V_X * dy) / _DET
    v = (-_U_Y * dx + _U_X * dy) / _DET
    return u, v


def content_to_battle_uv(
    x: float,
    y: float,
    battle: Optional[BattleArea] = None,
) -> Tuple[float, float]:
    """Content-normalized (0..1) position → battle-local UV."""
    ba = battle if battle is not None else get_battle_area()
    if ba.width == 0 or ba.height == 0:
        raise ValueError("battle area has zero width or height")
    u = (x - ba.left) / ba.width
    v = (y - ba.top) / ba.height
    return u, v


def battle_uv_to_content(
    u: float,
    v: float,
    battle: Optional[BattleArea] = None,
) -> Position:
    """Battle-local UV → content-normalized (0..1) position."""
    ba = battle if battle is not None else get_battle_area()
    return Position(
        x=ba.left + u * ba.width,
        y=ba.top + v * ba.height,
    )


def content_to_world_continuous(
    x: float,
    y: float,
    battle: Optional[BattleArea] = None,
) -> Position:
    """Content-normalized position → continuous relative WCS."""
    u, v = content_to_battle_uv(x, y, battle)
    return battle_uv_to_world_continuous(u, v)


def content_to_world(
    x: float,
    y: float,
    battle: Optional[BattleArea] = None,
) -> Position:
    """Content-normalized position → discrete relative WCS tiles."""
    c = content_to_world_continuous(x, y, battle)
    return snap_world(c.x, c.y)


def content_on_player_tile(
    x: float,
    y: float,
    battle: Optional[BattleArea] = None,
) -> bool:
    """True when content position snaps to relative WCS ``(0, 0)`` (player)."""
    tile = content_to_world(x, y, battle)
    return int(tile.x) == 0 and int(tile.y) == 0


# Alias used by combat/range callers.
content_to_world_tile = content_to_world


def world_to_content(
    wx: float,
    wy: float,
    battle: Optional[BattleArea] = None,
) -> Position:
    """Relative WCS (tile or continuous) → content-normalized position."""
    u, v = world_to_battle_uv(wx, wy)
    return battle_uv_to_content(u, v, battle)


def max_distance(a: Position, b: Position) -> int:
    """Chebyshev (max) distance between two WCS positions/tiles."""
    return max(abs(round_half_away(a.x) - round_half_away(b.x)),
               abs(round_half_away(a.y) - round_half_away(b.y)))


def content_max_distance(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    battle: Optional[BattleArea] = None,
) -> int:
    """Max-distance between two content positions via snapped WCS tiles."""
    a = content_to_world(ax, ay, battle)
    b = content_to_world(bx, by, battle)
    return max_distance(a, b)


def in_mage_spell_range(
    content_x: float,
    content_y: float,
    battle: Optional[BattleArea] = None,
    range_tiles: int = MAGE_SPELL_RANGE,
) -> bool:
    """True when content point is within mage cast range of the player tile."""
    tile = content_to_world(content_x, content_y, battle)
    return max(abs(int(tile.x)), abs(int(tile.y))) <= range_tiles


# ---------------------------------------------------------------------------
# Absolute WCS + battle click parallelogram (relative tiles)
# ---------------------------------------------------------------------------

# Mouse-clickable region in relative WCS (integer tiles). Screen battle area
# is a rectangle; in WCS it is a parallelogram inset 2 tiles from the measured
# edges so clicks avoid silhouette / boundary tiles:
#   -14 <= x + y <= 14
#   -16 <= x - y <= 18
CLICK_SUM_MIN = -14
CLICK_SUM_MAX = 14
CLICK_DIFF_MIN = -16
CLICK_DIFF_MAX = 18

# Slack for click validity: astar_d <= chev_d + CLICK_PATH_SLACK
CLICK_PATH_SLACK = 3
# Attack targets: allow a slightly longer wall detour than loot clicks.
ATTACK_PATH_SLACK = 4


@dataclass(frozen=True)
class WorldOrigin:
    """Absolute tile of the local player when relative WCS is (0, 0)."""

    x: int = 0
    y: int = 0

    def as_position(self) -> Position:
        return Position(x=float(self.x), y=float(self.y))


def distance_tiles_from_memory(obj: Any) -> int | None:
    """Chebyshev tiles from the player when memory stored a same-sweep delta."""
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    if rx is None or ry is None:
        return None
    return max(abs(int(rx)), abs(int(ry)))


def memory_nav_tile(obj: Any) -> tuple[int, int] | None:
    """Absolute nav tile from a memory world cell, or None."""
    cx = getattr(obj, "world_cx", None)
    cy = getattr(obj, "world_cy", None)
    if cx is None or cy is None:
        return None
    from app._03_world.memory_sync import game_to_nav

    return game_to_nav(int(cx), int(cy))


def tile_chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    """Chebyshev (max) distance between two integer tiles."""
    return max(abs(ax - bx), abs(ay - by))


def in_battle_click_region(rx: float, ry: float) -> bool:
    """True when relative WCS tile is inside the clickable parallelogram."""
    x = round_half_away(rx)
    y = round_half_away(ry)
    s = x + y
    d = x - y
    return (
        CLICK_SUM_MIN <= s <= CLICK_SUM_MAX
        and CLICK_DIFF_MIN <= d <= CLICK_DIFF_MAX
    )


def relative_to_absolute(
    rx: float,
    ry: float,
    origin: WorldOrigin,
) -> tuple[int, int]:
    """Relative tile (player-centered) → absolute world tile."""
    return origin.x + round_half_away(rx), origin.y + round_half_away(ry)


def absolute_to_relative(
    ax: float,
    ay: float,
    origin: WorldOrigin,
) -> tuple[int, int]:
    """Absolute world tile → relative tile (player at origin)."""
    return round_half_away(ax) - origin.x, round_half_away(ay) - origin.y
