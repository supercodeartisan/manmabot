"""Local ActionIntent mirror so member code need not import ``_04_decision`` package init.

``ActionExecutor`` only needs these fields at runtime (duck typing).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app._02_state.enums import ActionType
from app._02_state.objects import Position


@dataclass
class ActionIntent:
    action: ActionType
    target_id: Optional[int] = None
    destination: Optional[Position] = None
    priority: float = 0.0
    reason: str = ""
    mid_act: bool = False
    shop_behavior_id: Optional[str] = None
    shop_qty: Optional[int] = None
    shop_kind: Optional[str] = None
    shop_equip: Optional[str] = None
    shop_use_recover: bool = False
    shop_land_wait: bool = False
    item_key: Optional[str] = None
    hotbar_box: Optional[int] = None
    hotbar_key: Optional[str] = None
    # Party-list heal: client pixels of the member row. None keeps a key-only heal.
    click_x: Optional[int] = None
    click_y: Optional[int] = None
    scroll_times: int = 0
    gate_entrance: Optional[tuple[int, int]] = None
    gate_expect_map_id: Optional[int] = None
    gate_expect_xy: Optional[tuple[int, int]] = None
    gate_from_map_id: Optional[int] = None
    gate_edge: str = ""


__all__ = ["ActionIntent", "ActionType"]
