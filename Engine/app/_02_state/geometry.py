"""Spatial value types (no loaders, no perception apply)."""
from __future__ import annotations

from dataclasses import dataclass

from app._02_state.objects import Position

# Default battle height as a fraction of content height.
DEFAULT_BATTLE_HEIGHT_RATIO = 795.0 / 1010.0
PLAYER_U = 1.0 / 2.0
PLAYER_V = 10.0 / 19.0
CLAMP_MARGIN = 0.05


@dataclass(frozen=True)
class BattleArea:
    """Battle rect in content-normalized coordinates (cropped canvas = 0..1)."""

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
        return Position(
            x=self.left + self.player_u * self.width,
            y=self.top + self.player_v * self.height,
        )

    def clamp(self, x: float, y: float, margin: float = CLAMP_MARGIN) -> Position:
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


@dataclass(frozen=True)
class WorldOrigin:
    """Absolute tile of the local player when relative WCS is (0, 0)."""

    x: int = 0
    y: int = 0

    def as_position(self) -> Position:
        return Position(x=float(self.x), y=float(self.y))


__all__ = [
    "BattleArea",
    "CLAMP_MARGIN",
    "DEFAULT_BATTLE_HEIGHT_RATIO",
    "PLAYER_U",
    "PLAYER_V",
    "WorldOrigin",
]
