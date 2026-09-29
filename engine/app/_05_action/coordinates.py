"""Map game-frame normalized coordinates to desktop pixels."""
from __future__ import annotations

from app._01_capture.window_bounds import WindowBounds


def game_to_screen(
    nx: float,
    ny: float,
    bounds: WindowBounds,
) -> tuple[int, int]:
    """Convert normalized game-frame coords (0-1) to desktop pixel coords."""
    if nx <= 1.0 and ny <= 1.0:
        return (
            int(bounds.left + nx * bounds.width),
            int(bounds.top + ny * bounds.height),
        )
    return int(nx), int(ny)
