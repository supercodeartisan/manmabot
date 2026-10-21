"""In-process perception buffer for one capture.

Sensors write raw DLL snapshots here. World reads this object and updates
``GameState``. Fields left empty were not read this capture (partial OK).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PerceptionBuffer:
    """Raw memory snapshots owned by perception for one capture."""

    captured_at: float = 0.0
    player: Optional[dict[str, Any]] = None
    print_state: Optional[dict[str, Any]] = None
    attacks_me: Optional[dict[str, Any]] = None
    contested_mobs: Optional[dict[str, Any]] = None
    inventory: Optional[dict[str, Any]] = None
    hotbar: Optional[dict[str, Any]] = None
    shop: Optional[dict[str, Any]] = None
    buff: Optional[dict[str, Any]] = None
    uidialog: Optional[dict[str, Any]] = None
    party: Optional[dict[str, Any]] = None
    # True only when the matching DLL returned a usable payload this capture.
    player_ok: bool = False
    print_state_ok: bool = False
    inventory_ok: bool = False
    hotbar_ok: bool = False
    shop_ok: bool = False
    buff_ok: bool = False
    uidialog_ok: bool = False
    party_ok: bool = False
    errors: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.captured_at = 0.0
        self.player = None
        self.print_state = None
        self.attacks_me = None
        self.contested_mobs = None
        self.inventory = None
        self.hotbar = None
        self.shop = None
        self.buff = None
        self.uidialog = None
        self.party = None
        self.player_ok = False
        self.print_state_ok = False
        self.inventory_ok = False
        self.hotbar_ok = False
        self.shop_ok = False
        self.buff_ok = False
        self.uidialog_ok = False
        self.party_ok = False
        self.errors.clear()

    def stamp(self) -> None:
        self.captured_at = time.time()


__all__ = ["PerceptionBuffer"]
