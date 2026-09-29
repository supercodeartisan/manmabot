"""Battle area geometry inside the game content (normalized 0-1).

All values are **fractions of the cropped game canvas**, not fixed pixel
sizes. The game window can be any resolution; after the 4:3 content crop,
these ratios still apply.

Example (one measured layout, not a required size):
  content ~1345x1010, battle height ~795 -> height fraction 795/1010.
  Player sits at battle-local (1/2, 10/19), not geometric center.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app._03_world.objects import Position

# Default battle height as a fraction of content height.
# Derived from one example measurement (795px battle / 1010px content);
# the absolute pixels are irrelevant — only this ratio is used at runtime.
DEFAULT_BATTLE_HEIGHT_RATIO = 795.0 / 1010.0

# Player anchor inside the battle rect (battle-local u,v in 0-1).
PLAYER_U = 1.0 / 2.0
PLAYER_V = 10.0 / 19.0

# Inner margin for click clamp, as a fraction of battle width/height.
CLAMP_MARGIN = 0.05


@dataclass(frozen=True)
class BattleArea:
    """Battle rect in content-normalized coordinates (cropped canvas = 0..1).

    Independent of absolute window resolution. ``left``/``top``/``width``/
    ``height`` are fractions of the game content frame after any 4:3 crop.
    """

    left: float = 0.0
    top: float = 0.0
    width: float = 1.0
    height: float = DEFAULT_BATTLE_HEIGHT_RATIO
    player_u: float = PLAYER_U
    player_v: float = PLAYER_V

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def player_position(self) -> Position:
        """Local character in content-normalized coords (any resolution)."""
        return Position(
            x=self.left + self.player_u * self.width,
            y=self.top + self.player_v * self.height,
        )

    def clamp(self, x: float, y: float, margin: float = CLAMP_MARGIN) -> Position:
        """Clamp a content-normalized point into the battle rect (with margin)."""
        mx = self.width * margin
        my = self.height * margin
        return Position(
            x=max(self.left + mx, min(self.right - mx, x)),
            y=max(self.top + my, min(self.bottom - my, y)),
        )

    def contains(self, x: float, y: float, margin: float = 0.0) -> bool:
        mx = self.width * margin
        my = self.height * margin
        return (
            self.left + mx <= x <= self.right - mx
            and self.top + my <= y <= self.bottom - my
        )


_DEFAULT = BattleArea()
_current: BattleArea = _DEFAULT


def get_battle_area() -> BattleArea:
    return _current


def set_battle_area(area: BattleArea) -> None:
    global _current
    _current = area


def configure_battle_area(config: Optional[dict[str, Any]] = None) -> BattleArea:
    """Load battle_area from config dict (or defaults) and install it."""
    global CLAMP_MARGIN
    section = (config or {}).get("battle_area") or {}
    if "clamp_margin" in section:
        CLAMP_MARGIN = float(section["clamp_margin"])
    area = BattleArea(
        left=float(section.get("left", _DEFAULT.left)),
        top=float(section.get("top", _DEFAULT.top)),
        width=float(section.get("width", _DEFAULT.width)),
        height=float(section.get("height", _DEFAULT.height)),
        player_u=float(section.get("player_u", _DEFAULT.player_u)),
        player_v=float(section.get("player_v", _DEFAULT.player_v)),
    )
    set_battle_area(area)
    return area


def player_screen_position() -> Position:
    """Shortcut: local-player position in content-normalized coords."""
    return get_battle_area().player_position
