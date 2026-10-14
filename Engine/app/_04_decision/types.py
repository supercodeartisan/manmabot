"""Decision Module type definitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app._03_world import Position

# Re-export for callers that still import ActionType from decision.types.
# Prefer ``app._03_world.ActionType`` in new code.
from app._03_world import ActionType


@dataclass
class ActionIntent:
    """A single high-level action request from the Decision Module.

    This is the ONLY output of the Decision Module. The Action Module
    will execute the actual game interaction.
    """

    action: ActionType
    target_id: Optional[int] = None
    destination: Optional[Position] = None
    priority: float = 0.0
    reason: str = ""
    # Decide-owned sticky flag (travel/search legs, combat re-click). Action
    # reads this only — it must not clear or force ``mid_act``.
    mid_act: bool = False
    # NPC behavior id from Engine/data/npc_behaviors.yaml.
    shop_behavior_id: Optional[str] = None
    # Buy UI quantity chosen by decide (None → YAML default / N/A for sell).
    shop_qty: Optional[int] = None
    # buy | sell | teleporter — decide-owned; action must not re-resolve kind.
    shop_kind: Optional[str] = None
    # After buy: equip arrow stack ("silver" | "normal") or None.
    shop_equip: Optional[str] = None
    # True → run legacy hardcoded arrow-buy UI (only when decide asks).
    shop_use_recover: bool = False
    # Talking-scroll land: wait for shop settle after list click.
    shop_land_wait: bool = False
    # Specific HP restore item (catalog key). Empty → assigned hp_potion slot.
    item_key: Optional[str] = None
    hotbar_box: Optional[int] = None
    hotbar_key: Optional[str] = None
    # Talking-scroll list: wheel notches before click (world-nav hubs).
    scroll_times: int = 0
    # GATE: entrance abs cell, expected land mapId + cell (world-nav transition).
    gate_entrance: Optional[tuple[int, int]] = None
    gate_expect_map_id: Optional[int] = None
    gate_expect_xy: Optional[tuple[int, int]] = None
    gate_from_map_id: Optional[int] = None
    gate_edge: str = ""
