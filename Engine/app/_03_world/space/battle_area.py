"""Battle area runtime install (config → ``_02_state.BattleArea``)."""
from __future__ import annotations

from typing import Any, Optional

from app._02_state.geometry import (
    CLAMP_MARGIN,
    BattleArea,
    DEFAULT_BATTLE_HEIGHT_RATIO,
    PLAYER_U,
    PLAYER_V,
)
from app._02_state.objects import Position

# Re-export constants used by callers.
__all__ = [
    "BattleArea",
    "CLAMP_MARGIN",
    "DEFAULT_BATTLE_HEIGHT_RATIO",
    "PLAYER_U",
    "PLAYER_V",
    "configure_battle_area",
    "get_battle_area",
    "player_screen_position",
    "set_battle_area",
]

_DEFAULT = BattleArea()
_current: BattleArea = _DEFAULT
_clamp_margin = CLAMP_MARGIN


def get_battle_area() -> BattleArea:
    return _current


def set_battle_area(area: BattleArea) -> None:
    global _current
    _current = area


def configure_battle_area(config: Optional[dict[str, Any]] = None) -> BattleArea:
    """Load battle_area from config dict (or defaults) and install it."""
    global _clamp_margin
    section = (config or {}).get("battle_area") or {}
    if "clamp_margin" in section:
        _clamp_margin = float(section["clamp_margin"])
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
