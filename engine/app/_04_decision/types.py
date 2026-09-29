"""Decision Module type definitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app._03_world import Position

# ``ActionType`` lives in app._03_world; the import below is kept only so the
# archived legacy modules (app._04_decision.legacy.*) keep importing it from
# here. Active code imports ActionType straight from app._03_world.
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
    mid_act: bool = False
    # Shopping: userdata shopping_behaviors.yaml id (empty → recover stub for arrows).
    shop_behavior_id: Optional[str] = None
    # Specific HP restore item (catalog key). Empty → assigned hp_potion slot.
    item_key: Optional[str] = None
    hotbar_box: Optional[int] = None
    hotbar_key: Optional[str] = None
