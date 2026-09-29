"""Lineage client language (Korean vs Chinese).

Operator UI language in Version 1 is separate. This selects in-game HUD and
dialog click calibrations. More spots can be added here as they are measured.
"""
from __future__ import annotations

from dataclasses import dataclass

from app._03_world import Position

GAME_KO = "ko"
GAME_ZH = "zh"
SUPPORTED_GAME_LANGUAGES: tuple[str, ...] = (GAME_KO, GAME_ZH)

_current = GAME_KO


def normalize_game_language(code: str | None) -> str:
    """``ko`` or ``zh``. Unknown / empty → Korean (original calibration)."""
    c = (code or GAME_KO).strip().lower().replace("_", "-")
    if c.startswith("zh") or c in ("cn", "chinese"):
        return GAME_ZH
    return GAME_KO


def get_game_language() -> str:
    return _current


def set_game_language(code: str | None) -> str:
    """Set the live client language and return the normalized code."""
    global _current
    _current = normalize_game_language(code)
    return _current


def _uv(px_x: float, px_y: float, ref_w: float, ref_h: float) -> Position:
    return Position(x=px_x / ref_w, y=px_y / ref_h)


@dataclass(frozen=True)
class ShopUiClicks:
    """Content UVs for shop-window clicks (buy tab, arrow row, confirm)."""

    buy_tab: Position
    arrow_row: Position
    confirm: Position


# Korean: 1118×839 shop-window capture.
_KO_SHOP = ShopUiClicks(
    buy_tab=_uv(130.0, 380.0, 1118.0, 839.0),
    arrow_row=_uv(280.0, 186.0, 1118.0, 839.0),
    confirm=_uv(258.0, 485.0, 1118.0, 839.0),
)
# Chinese: buy-tab Y measured on a 1017-tall capture (412/1017).
# X not re-measured yet — keep Korean buy-tab X UV. Arrow / confirm unchanged.
_ZH_SHOP = ShopUiClicks(
    buy_tab=_uv(130.0, 412.0, 1118.0, 1017.0),
    arrow_row=_KO_SHOP.arrow_row,
    confirm=_KO_SHOP.confirm,
)

SHOP_UI_CLICKS: dict[str, ShopUiClicks] = {
    GAME_KO: _KO_SHOP,
    GAME_ZH: _ZH_SHOP,
}


def shop_ui_clicks() -> ShopUiClicks:
    """Shop-window click UVs for the current game language."""
    return SHOP_UI_CLICKS.get(_current, _KO_SHOP)


__all__ = [
    "GAME_KO",
    "GAME_ZH",
    "SUPPORTED_GAME_LANGUAGES",
    "ShopUiClicks",
    "SHOP_UI_CLICKS",
    "normalize_game_language",
    "get_game_language",
    "set_game_language",
    "shop_ui_clicks",
]
