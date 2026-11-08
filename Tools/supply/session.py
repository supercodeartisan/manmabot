"""Supply session flags, loot block, drop records, failed list."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


LOOT_BLOCK_AFTER_S = 5.0
MAX_DRAG_TRIES = 1


@dataclass
class SupplyItem:
    """One requested supply line."""

    item_id: Optional[int] = None
    name: str = ""
    qty: int = 0

    def key(self) -> str:
        if self.item_id is not None:
            return f"id:{int(self.item_id)}"
        return f"name:{self.name.strip()}"


@dataclass
class DropRecord:
    item_id: Optional[int]
    name: str
    world_x: int
    world_y: int
    qty: int


@dataclass
class SupplySession:
    active: bool = False
    dropping: bool = False  # standing drop: block combat/move/loot
    loot_block_until: float = 0.0
    request: list[SupplyItem] = field(default_factory=list)
    remaining: dict[str, int] = field(default_factory=dict)
    failed: list[SupplyItem] = field(default_factory=list)
    records: list[DropRecord] = field(default_factory=list)

    def begin(self, items: list[SupplyItem]) -> None:
        self.active = True
        self.dropping = False
        self.loot_block_until = 0.0
        self.request = [SupplyItem(item_id=i.item_id, name=i.name, qty=int(i.qty)) for i in items if int(i.qty) > 0]
        self.remaining = {i.key(): int(i.qty) for i in self.request}
        self.failed = []
        self.records = []

    def start_dropping(self) -> None:
        self.dropping = True
        self.loot_block_until = 0.0

    def finish(self) -> None:
        self.dropping = False
        self.active = False
        self.loot_block_until = time.time() + LOOT_BLOCK_AFTER_S

    def loot_blocked(self, now: Optional[float] = None) -> bool:
        stamp = time.time() if now is None else float(now)
        if self.active and self.dropping:
            return True
        return stamp < float(self.loot_block_until)

    def combat_move_blocked(self) -> bool:
        return bool(self.active and self.dropping)

    def record_drop(
        self,
        *,
        item_id: Optional[int],
        name: str,
        world_x: int,
        world_y: int,
        qty: int,
    ) -> None:
        if qty <= 0:
            return
        self.records.append(
            DropRecord(
                item_id=item_id,
                name=name,
                world_x=int(world_x),
                world_y=int(world_y),
                qty=int(qty),
            )
        )

    def note_failed(self, item: SupplyItem, left: int) -> None:
        if left <= 0:
            return
        self.failed.append(SupplyItem(item_id=item.item_id, name=item.name, qty=int(left)))

    def delivered_qty(self, item: SupplyItem) -> int:
        key_id = item.item_id
        name = (item.name or "").strip()
        total = 0
        for row in self.records:
            if key_id is not None and row.item_id == key_id:
                total += row.qty
            elif key_id is None and name and row.name == name:
                total += row.qty
        return total

    def summary(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "dropping": self.dropping,
            "loot_block_until": self.loot_block_until,
            "failed": [
                {"id": f.item_id, "name": f.name, "qty": f.qty} for f in self.failed
            ],
            "records": [
                {
                    "id": r.item_id,
                    "name": r.name,
                    "world": [r.world_x, r.world_y],
                    "qty": r.qty,
                }
                for r in self.records
            ],
        }
