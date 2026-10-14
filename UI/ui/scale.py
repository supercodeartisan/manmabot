"""Window scale helpers shared by Qt (and any non-Tk callers).

Extracted from the retired ttk ``design_system`` — toolkit-free.
"""

from __future__ import annotations

# Schedule window was designed at ~1760×1000. Default size is 1187×806.
DESIGN_WIDTH = 1760
DESIGN_HEIGHT = 1000
DEFAULT_WIDTH = 1187
DEFAULT_HEIGHT = 806
MIN_WIDTH = 800
MIN_HEIGHT = 600
MIN_FONT_SIZE = 8
UI_SCALE = DEFAULT_WIDTH / DESIGN_WIDTH


def compute_ui_scale(width: int, height: int) -> float:
    """Map a live window size onto the original 1760×1000 design."""
    fallback = DEFAULT_WIDTH / DESIGN_WIDTH
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return fallback
    if width < 50 or height < 50:
        return fallback
    return max(0.55, min(1.0, min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)))


def scaled(value: int | float, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * UI_SCALE)))
