"""Isometric screen projection matching avoid_view / debug field view."""
from __future__ import annotations

import math

import numpy as np


def iso_screen(
    tx: float,
    ty: float,
    focus_x: float,
    focus_y: float,
    cx: float,
    cy: float,
    tile: float,
) -> tuple[float, float]:
    rx = float(tx) - float(focus_x)
    ry = float(ty) - float(focus_y)
    return (
        cx + (rx + ry) * tile,
        cy - (rx - ry) * tile * 0.5,
    )


def iso_tile(
    sx: float,
    sy: float,
    focus_x: float,
    focus_y: float,
    cx: float,
    cy: float,
    tile: float,
) -> tuple[float, float]:
    u = (float(sx) - cx) / tile
    v = (cy - float(sy)) * 2.0 / tile
    return ((u + v) * 0.5 + focus_x, (u - v) * 0.5 + focus_y)


def nearest(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def pan_focus(
    focus_x: float, focus_y: float, dx: float, dy: float, tile: float
) -> tuple[float, float]:
    return (
        focus_x - dx / (2.0 * tile) + dy / tile,
        focus_y - dx / (2.0 * tile) - dy / tile,
    )


def focus_keeping(
    sx: float,
    sy: float,
    tx: float,
    ty: float,
    cx: float,
    cy: float,
    tile: float,
) -> tuple[float, float]:
    u = (float(sx) - cx) / tile
    v = (cy - float(sy)) * 2.0 / tile
    return (float(tx) - (u + v) * 0.5, float(ty) - (u - v) * 0.5)


def map_margin(scale: float) -> int:
    return max(48, int(scale) * 3)


def image_shift(
    old_x: float, old_y: float, focus_x: float, focus_y: float, scale: float
) -> tuple[float, float]:
    dx = old_x - focus_x
    dy = old_y - focus_y
    return (dx + dy) * scale, -((dx - dy) * scale * 0.5)


def block_diamond(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    project,
    tile: float,
) -> list[float]:
    top = project((x1, y0))
    right = project((x1, y1))
    bottom = project((x0, y1))
    left = project((x0, y0))
    half = tile * 0.5
    return [
        top[0],
        top[1] - half,
        right[0] + tile,
        right[1],
        bottom[0],
        bottom[1] + half,
        left[0] - tile,
        left[1],
    ]


def class_rgb_ppm(
    rgb: np.ndarray,
    focus_x: float,
    focus_y: float,
    width: int,
    height: int,
    tile: float,
    *,
    tile_px: int = 1,
) -> bytes:
    """PPM in isometric projection.

    ``rgb`` is either 1 px/nav-tile or a fine raster with ``tile_px``² per
    nav tile (fence B/W map). ``focus`` / ``tile`` stay in nav-tile units.
    """
    margin = map_margin(tile)
    width = int(width) + 2 * margin
    height = int(height) + 2 * margin
    cx = width / 2.0
    cy = height / 2.0
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    u = (xs[None, :] - cx) / tile
    v = (cy - ys[:, None]) * 2.0 / tile
    # Continuous nav coords, then fine pixels when tile_px > 1.
    tx_f = (u + v) * 0.5 + float(focus_x)
    ty_f = (u - v) * 0.5 + float(focus_y)
    px = int(max(1, tile_px))
    if px <= 1:
        tx = np.floor(tx_f + 0.5).astype(np.int32)
        ty = np.floor(ty_f + 0.5).astype(np.int32)
    else:
        tx = np.floor(tx_f * px).astype(np.int32)
        ty = np.floor(ty_f * px).astype(np.int32)
    rows, cols = rgb.shape[0], rgb.shape[1]
    valid = (tx >= 0) & (tx < cols) & (ty >= 0) & (ty < rows)
    color = np.empty((height, width, 3), dtype=np.uint8)
    color[:] = (26, 28, 30)
    if np.any(valid):
        color[valid] = rgb[ty[valid], tx[valid]]
    header = f"P6 {width} {height} 255\n".encode("ascii")
    return header + np.ascontiguousarray(color).tobytes()
