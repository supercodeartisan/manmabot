"""Re-export Engine edge layers for the TI edge-nav tool."""
from __future__ import annotations

from pathlib import Path

from app._03_world.space.edge_layers import (  # noqa: F401
    OX,
    TILE_PX,
    EdgeLayers,
    edge_layers_from_arrays,
    load_edge_layers as _load_edge_layers,
    support_s32_dir,
)

# Tool defaults (Talking Island).
ORIGIN_X = 32256
ORIGIN_Y = 32704
TILE_W = 512
TILE_H = 576
DEFAULT_S32_DIR = support_s32_dir("talking_island")
if not DEFAULT_S32_DIR.is_dir():
    DEFAULT_S32_DIR = Path(r"D:\map_0")


def load_edge_layers(s32_dir: Path | None = None) -> EdgeLayers:
    root = Path(s32_dir) if s32_dir is not None else DEFAULT_S32_DIR
    return _load_edge_layers(
        root,
        origin_x=ORIGIN_X,
        origin_y=ORIGIN_Y,
        width=TILE_W,
        height=TILE_H,
    )
