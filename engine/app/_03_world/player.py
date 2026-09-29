"""Player state and inventory types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .enums import CharacterType
from .objects import Position


@dataclass
class StatusEffect:
    name: str
    duration: float
    value: float = 0.0


@dataclass
class InventoryItem:
    name: str
    quantity: int = 1
    weight: float = 0.0
    item_id: int = 0
    kind: int = 0
    name_tw: str = ""
    name_cn: str = ""
    name_en: str = ""


@dataclass
class InventoryState:
    hp_potion: int = 0
    mp_potion: int = 0
    weight_ratio: float = 0.0
    items: list[InventoryItem] = field(default_factory=list)
    arrows: int = 0
    silver_arrows: int = 0
    depoison: int = 0
    adena: int = 0
    bag_ready: bool = False
    bag_updated_at: float = 0.0


@dataclass(frozen=True)
class PlayerState:
    """Local character status for the decision layer.

    Position is the fixed battle-area player anchor (camera follows the
    character). HP/MP/level come from the memory monitor when available —
    never from YOLO detection. Bag fill (``inventory.weight_ratio``) comes
    from character memory (weight/maxWeight) when the monitor has it,
    otherwise from HUD template matching.
    """

    track_id: int
    position: Position
    hp: int | None = None
    mp: int | None = None
    level: int | None = None
    max_hp: int | None = None
    max_mp: int | None = None
    hp_ratio: float = 1.0
    mp_ratio: float = 1.0
    exp_percent: float = 0.0
    weight: float = 0.0
    max_weight: float = 0.0
    character_type: CharacterType = CharacterType.ELF
    zone: str = ""
    region: str = ""
    attack_power: float = 100.0
    defense: float = 100.0
    alive: bool = True
    buffs: list[StatusEffect] = field(default_factory=list)
    debuffs: list[StatusEffect] = field(default_factory=list)
    poisoned: bool = False
    inventory: InventoryState = field(default_factory=InventoryState)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def memory_weight_ready(player: PlayerState | None) -> bool:
    """True when the memory monitor already supplies bag weight."""
    if player is None:
        return False
    try:
        return float(getattr(player, "max_weight", 0.0) or 0.0) > 0.0
    except (TypeError, ValueError):
        return False