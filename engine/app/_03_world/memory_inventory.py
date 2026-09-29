"""Apply inventory_listen snapshots to PlayerState.inventory and shop needs."""
from __future__ import annotations

import time
from typing import Any, Optional, TYPE_CHECKING

from app._03_world.player import InventoryItem, InventoryState

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world.gamestate import GameState
    from app._04_decision.blackboard import Blackboard

# Stable LC item ids from inventory_listen samples / static name table.
HP_POTION_IDS = frozenset({14, 15, 80, 130, 279})
ARROW_IDS = frozenset({7})
SILVER_ARROW_IDS = frozenset({96})
DEPOISON_IDS = frozenset({76, 126})
ADENA_IDS = frozenset({5})

HP_POTION_NAMES = frozenset(
    {
        "체력 회복제",
        "빨간 물약",
        "주홍 물약",
        "맑은 물약",
        "엔트의 열매",
        "高級 체력 회복제",
        "고급 체력 회복제",
        "강력 체력 회복제",
        "治癒藥水",
        "治愈药水",
        "紅色藥水",
        "红色药水",
        "橙色藥水",
        "橙色药水",
        "白色藥水",
        "白色药水",
        "安特的水果",
        "healing potion",
        "red potion",
        "orange potion",
        "white potion",
        "ent fruit",
    }
)
ARROW_NAMES = frozenset({"화살", "箭", "arrow", "arrows"})
SILVER_ARROW_NAMES = frozenset({"은 화살", "銀箭", "银箭", "silver arrow", "silver arrows"})
DEPOISON_NAMES = frozenset(
    {"해독제", "비취 물약", "解毒劑", "解毒剂", "翡翠藥水", "antidote", "depoison"}
)
ADENA_NAMES = frozenset({"아데나", "金幣", "金币", "adena"})


def _norm_name(value: object) -> str:
    return str(value or "").strip().lower()


def _item_names(raw: dict[str, Any]) -> set[str]:
    names = {
        _norm_name(raw.get("name")),
        _norm_name(raw.get("name_tw")),
        _norm_name(raw.get("name_cn")),
        _norm_name(raw.get("name_en")),
    }
    return {n for n in names if n}


def _matches(raw: dict[str, Any], *, ids: frozenset[int], names: frozenset[str]) -> bool:
    try:
        item_id = int(raw.get("id") or 0)
    except (TypeError, ValueError):
        item_id = 0
    if item_id in ids:
        return True
    lowered = {n.lower() for n in names}
    return bool(_item_names(raw) & lowered)


def count_matching(items: list[dict[str, Any]], *, ids: frozenset[int], names: frozenset[str]) -> int:
    total = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if not _matches(raw, ids=ids, names=names):
            continue
        try:
            total += max(0, int(raw.get("count") or 0))
        except (TypeError, ValueError):
            continue
    return total


def inventory_state_from_snapshot(
    snapshot: dict[str, Any],
    *,
    base: Optional[InventoryState] = None,
) -> InventoryState:
    """Build InventoryState from an inventory_listen JSON payload."""
    raw_items = snapshot.get("items") if isinstance(snapshot, dict) else None
    if not isinstance(raw_items, list):
        return base or InventoryState()

    weight_ratio = float(getattr(base, "weight_ratio", 0.0) or 0.0) if base else 0.0
    parsed: list[InventoryItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            count = max(0, int(raw.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        try:
            item_id = int(raw.get("id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        try:
            kind = int(raw.get("kind") or 0)
        except (TypeError, ValueError):
            kind = 0
        name = str(raw.get("name") or raw.get("name_tw") or raw.get("name_cn") or raw.get("name_en") or "").strip()
        parsed.append(
            InventoryItem(
                name=name or f"id:{item_id}",
                quantity=count,
                weight=0.0,
                item_id=item_id,
                kind=kind,
                name_tw=str(raw.get("name_tw") or "").strip(),
                name_cn=str(raw.get("name_cn") or "").strip(),
                name_en=str(raw.get("name_en") or "").strip(),
            )
        )

    hp = count_matching(raw_items, ids=HP_POTION_IDS, names=HP_POTION_NAMES)
    arrows = count_matching(raw_items, ids=ARROW_IDS, names=ARROW_NAMES)
    silver = count_matching(raw_items, ids=SILVER_ARROW_IDS, names=SILVER_ARROW_NAMES)
    depoison = count_matching(raw_items, ids=DEPOISON_IDS, names=DEPOISON_NAMES)
    adena = count_matching(raw_items, ids=ADENA_IDS, names=ADENA_NAMES)
    return InventoryState(
        hp_potion=hp,
        mp_potion=getattr(base, "mp_potion", 0) if base else 0,
        weight_ratio=weight_ratio,
        items=parsed,
        arrows=arrows,
        silver_arrows=silver,
        depoison=depoison,
        adena=adena,
        bag_ready=True,
        bag_updated_at=time.time(),
    )


def apply_inventory_snapshot(world: "GameState", snapshot: dict[str, Any]) -> InventoryState:
    """Write bag counts onto ``world.player.inventory`` (keeps HUD weight_ratio)."""
    player = getattr(world, "player", None)
    base_inv = getattr(player, "inventory", None) if player is not None else None
    inventory = inventory_state_from_snapshot(snapshot, base=base_inv)
    if player is not None:
        from dataclasses import replace

        world.set_player(replace(player, inventory=inventory))
    world.last_inventory = snapshot
    return inventory


def refresh_shop_needs_from_inventory(
    world: "GameState",
    blackboard: "Blackboard",
) -> None:
    """Set needs_* from bag counts vs Fix/Return thresholds (shops module policy)."""
    from app._04_decision.shops import (
        BUY_DEPOISON,
        BUY_NORMAL_ARROWS,
        BUY_SILVER_ARROWS,
        RESTOCK_POTIONS,
        RETURN_ARROW_COUNT,
        RETURN_ARROW_ENABLED,
        RETURN_DEPOISON_COUNT,
        RETURN_DEPOISON_ENABLED,
        RETURN_POTION_COUNT,
        RETURN_POTION_ENABLED,
    )

    player = getattr(world, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return

    now = time.time()
    if RESTOCK_POTIONS and RETURN_POTION_ENABLED:
        suppressed = now < float(getattr(blackboard, "potion_suppress_until", 0.0) or 0.0)
        blackboard.needs_potion = (not suppressed) and int(inv.hp_potion) <= int(
            RETURN_POTION_COUNT
        )
    else:
        blackboard.needs_potion = False

    if BUY_DEPOISON and RETURN_DEPOISON_ENABLED:
        suppressed = now < float(getattr(blackboard, "depoison_suppress_until", 0.0) or 0.0)
        blackboard.needs_depoison = (not suppressed) and int(inv.depoison) <= int(
            RETURN_DEPOISON_COUNT
        )
    else:
        blackboard.needs_depoison = False

    if (BUY_NORMAL_ARROWS or BUY_SILVER_ARROWS) and RETURN_ARROW_ENABLED:
        if BUY_SILVER_ARROWS and not BUY_NORMAL_ARROWS:
            arrow_count = int(inv.silver_arrows)
        else:
            arrow_count = int(inv.arrows)
        blackboard.needs_arrows = arrow_count <= int(RETURN_ARROW_COUNT)
    else:
        blackboard.needs_arrows = False


__all__ = [
    "HP_POTION_IDS",
    "ARROW_IDS",
    "SILVER_ARROW_IDS",
    "DEPOISON_IDS",
    "ADENA_IDS",
    "inventory_state_from_snapshot",
    "apply_inventory_snapshot",
    "refresh_shop_needs_from_inventory",
    "count_matching",
]
