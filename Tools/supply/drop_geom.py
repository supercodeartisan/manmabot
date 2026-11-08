"""Drop-tile screen points: etview lc_viewCalc / lc_project (1-tile neighbors)."""
from __future__ import annotations

from typing import Sequence

# etview / lcore.h defaults
REF_H = 600.0
PPS = 0.53
VP_DX = 1.8
VP_DY = 63.0
ISO_U_SCALE = 48.0
ISO_V_SCALE = 24.0

# Screen left / right / down in relative world tiles
DROP_TILES: tuple[tuple[int, int], ...] = (
    (-1, -1),  # left
    (1, 1),  # right
    (-1, 1),  # down
)


def player_screen(client_w: int, client_h: int) -> tuple[float, float, float]:
    """Return (sx, sy, pxp) for the live client size."""
    sc = float(client_h) / REF_H
    if sc < 0.2 or sc > 4.0:
        sc = 1.0
    pxp = PPS * sc
    sx = float(client_w) * 0.5 + VP_DX * sc
    sy = float(client_h) * 0.5 - VP_DY * sc
    return sx, sy, pxp


def tile_to_screen(
    dx: int,
    dy: int,
    *,
    client_w: int,
    client_h: int,
) -> tuple[int, int]:
    sx, sy, pxp = player_screen(client_w, client_h)
    du = ISO_U_SCALE * (int(dx) + int(dy))
    dv = ISO_V_SCALE * (int(dx) - int(dy))
    return int(round(sx + du * pxp)), int(round(sy - dv * pxp))


def drop_screen_points(client_w: int, client_h: int) -> list[tuple[int, int]]:
    """Three client-pixel drop aim points (left, right, down)."""
    return [
        tile_to_screen(dx, dy, client_w=client_w, client_h=client_h)
        for dx, dy in DROP_TILES
    ]


def drop_world_tile(
    player_wx: int,
    player_wy: int,
    which: int,
) -> tuple[int, int]:
    """Absolute world tile for drop index 0..2."""
    dx, dy = DROP_TILES[int(which) % len(DROP_TILES)]
    return int(player_wx) + int(dx), int(player_wy) + int(dy)


def pick_drop_index(rng) -> int:
    return int(rng.randrange(0, len(DROP_TILES)))


def validate_open_face_tiles() -> Sequence[tuple[int, int]]:
    """World deltas that must be walkable around the supply stand tile."""
    return ((1, -1), (-1, 1), (-1, -1), (1, 1))  # up, down, left, right
