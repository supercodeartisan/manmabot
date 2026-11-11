"""Shopping policy: when to buy or sell, and which NPC behavior id to run.

Travel and dialog live in ``Engine/data/npc_behaviors.yaml``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app._03_world import Position

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Arrows the user wants (1–999). The shop field is bundles, not this count.
# Normal: 1 typed = 10 arrows. Silver: 1 typed = 5 arrows.
ARROW_BUY_QTY = 200
NORMAL_ARROWS_PER_SHOP_UNIT = 10
SILVER_ARROWS_PER_SHOP_UNIT = 5
# Live shopping policy (Version 1 profile / schedule → configure_decision).
BUY_NORMAL_ARROWS = True
BUY_SILVER_ARROWS = False
SILVER_ARROW_BUY_QTY = 200
RESTOCK_POTIONS = True
BUY_DEPOISON = False
HP_POTION_BUY_QTY = 100
# Mainland / Talking Island red HP potion list price.
HP_POTION_PRICE = 52
DEPOISON_BUY_QTY = 1
# Fix/Return thresholds (schedule hunt.return_* → configure_decision).
RETURN_POTION_ENABLED = True
RETURN_POTION_COUNT = 20
RETURN_ARROW_ENABLED = True
RETURN_ARROW_COUNT = 300
RETURN_DEPOISON_ENABLED = False
RETURN_DEPOISON_COUNT = 1
# Account server language for calibrated behavior ids: "ko" | "zh".
SHOP_LOCALE = "ko"
# HP potion shop village: "talking" | "mainland".
HP_POTION_NPC = "talking"
# Fix/Return weight gauge (schedule hunt.return_weight_* → configure_decision).
RETURN_WEIGHT_ENABLED = True
SELL_WEIGHT_RATIO = 0.70  # decoded WEIGHT percent/100 ≥ this → sell trip
# Item/Sell mode: sell_only_garbage | sell_except_keep.
SELL_MODE = "sell_except_keep"
# Schedule equipment.store_after_sell. Off skips the warehouse keeper.
STORE_AFTER_SELL = True
POTION_SUPPRESS_S = 600.0
# Chebyshev tiles from the shop NPC to click / buy (walk stops here).
SHOP_ARRIVE_TILES = 7
# Click the NPC only when this close. Giran is crowded; 7 tiles + a 20px
# ring picks the wrong merchant. Practice lands 1–3 tiles from the stall.
SHOP_CLICK_TILES = 3
# Screen-pixel radius of the dialog-cursor ring around the catalog UV.
SHOP_NPC_SEARCH_PX = 20
# Korean shop-window capture (1118×839). Live clicks use ``shop_ui_clicks()``
# so Chinese (and later languages) can override individual UVs.
SHOP_UI_REF_W = 1118.0
SHOP_UI_REF_H = 839.0
SHOP_BUY_TAB_PX = (130.0, 380.0)
SHOP_ARROW_ROW_PX = (280.0, 186.0)
SHOP_CONFIRM_PX = (258.0, 485.0)


def normalize_shop_locale(value: object) -> str:
    text = str(value or "ko").strip().lower()
    if text.startswith("zh"):
        return "zh"
    return "ko"


def normalize_hp_potion_npc(value: object) -> str:
    """Map UI NPC label / id to talking | mainland."""
    text = str(value or "").strip().lower()
    if not text:
        return "talking"
    if any(token in text for token in ("giran", "기란", "mainland", "본토", "奇岩")):
        return "mainland"
    if any(token in text for token in ("talking", "말하는", "ti_general", "说话")):
        return "talking"
    return "talking"


def normalize_sell_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in ("sell_only_garbage", "only_garbage", "garbage"):
        return "sell_only_garbage"
    return "sell_except_keep"


def resolve_shopping_behavior_id(kind: str) -> str:
    """Calibrated YAML behavior id for a buy kind.

    kind: hp | depoison | normal_arrows | silver_arrows
    """
    chinese = SHOP_LOCALE == "zh"
    key = str(kind or "").strip().lower()
    if key == "hp":
        if HP_POTION_NPC == "mainland":
            return (
                "buy_hp_potions_ch_mainland"
                if chinese
                else "buy_hp_potions_mainland"
            )
        return (
            "buy_hp_potions_talking_ch"
            if chinese
            else "buy_hp_potions_talking"
        )
    if key == "depoison":
        return (
            "buy_depoison_potions_ch_mainland"
            if chinese
            else "buy_depoison_potions_mainland"
        )
    if key == "silver_arrows":
        return (
            "buy_silver_arrows_ch_mainland"
            if chinese
            else "buy_silver_arrows_mainland"
        )
    # normal_arrows
    return (
        "buy_normal_arrows_ch_talking"
        if chinese
        else "buy_normal_arrows_talking"
    )


def resolve_sell_behavior_ids() -> tuple[str, ...]:
    """The four sell YAML ids. No UI NPC picker — locale + SELL_MODE only.

    Visit order is shuffled in ``shop_trip._shuffled_sell_ids``. This tuple
    stays stable so the candidate set does not change between calls.
    Four NPCs: TI general, weapon, mainland general, mainland armor.
    sell_only_garbage: sell_garbage[_ch], sell_garbage_weapon[_ch],
                       sell_garbage_mainland[_ch], sell_garbage_armor_mainland[_ch]
    sell_except_keep:  sell_except_keep[_ch], sell_except_keep_weapon[_ch],
                       sell_except_keep_mainland[_ch], sell_except_keep_armor_mainland[_ch]
    """
    chinese = SHOP_LOCALE == "zh"
    if SELL_MODE == "sell_except_keep":
        if chinese:
            return (
                "sell_except_keep_ch",
                "sell_except_keep_weapon_ch",
                "sell_except_keep_mainland_ch",
                "sell_except_keep_armor_mainland_ch",
            )
        return (
            "sell_except_keep",
            "sell_except_keep_weapon",
            "sell_except_keep_mainland",
            "sell_except_keep_armor_mainland",
        )
    if chinese:
        return (
            "sell_garbage_ch",
            "sell_garbage_weapon_ch",
            "sell_garbage_mainland_ch",
            "sell_garbage_armor_mainland_ch",
        )
    return (
        "sell_garbage",
        "sell_garbage_weapon",
        "sell_garbage_mainland",
        "sell_garbage_armor_mainland",
    )


def arrow_shop_units(behavior_id: str, arrow_count: int) -> int | None:
    """Shop-dialog digits for an arrow buy. None when ``behavior_id`` is not arrows.

    The profile count stays in arrows. The dialog counts bundles:
    1 normal = 10 arrows, 1 silver = 5 arrows. 200 silver types 40;
    200 normal types 20. A remainder is dropped. Fewer than one bundle
    still types 1.
    """
    bid = str(behavior_id or "")
    if "arrow" not in bid:
        return None
    per = (
        SILVER_ARROWS_PER_SHOP_UNIT
        if "silver" in bid
        else NORMAL_ARROWS_PER_SHOP_UNIT
    )
    try:
        count = int(arrow_count)
    except (TypeError, ValueError):
        count = per
    return max(1, min(999, count // per))


def buy_qty_for_behavior(behavior_id: str) -> int | None:
    """UI quantity for a calibrated buy behavior, or None to use YAML default.

    Arrow settings are arrow counts. This returns the bundle count the
    shop dialog accepts.
    """
    bid = str(behavior_id or "")
    if "silver_arrow" in bid:
        units = arrow_shop_units(bid, SILVER_ARROW_BUY_QTY)
        return units if units is not None else 1
    if "normal_arrow" in bid:
        units = arrow_shop_units(bid, ARROW_BUY_QTY)
        return units if units is not None else 1
    if "depoison" in bid:
        return max(1, min(999, int(DEPOISON_BUY_QTY)))
    if "hp_potion" in bid:
        return max(1, min(999, int(HP_POTION_BUY_QTY)))
    return None


def affordable_hp_potion_qty(wanted: int, adena: int | None) -> int:
    """Buy the UI quantity when Adena covers ``52 * qty``, else as many as fit.

    Unknown Adena keeps the requested count. Below one potion price → 0.
    """
    try:
        want = max(1, min(999, int(wanted)))
    except (TypeError, ValueError):
        want = 1
    if adena is None:
        return want
    try:
        have = max(0, int(adena))
    except (TypeError, ValueError):
        return want
    if have < int(HP_POTION_PRICE):
        return 0
    return min(want, have // int(HP_POTION_PRICE))


def is_arrow_behavior(behavior_id: str) -> bool:
    return "arrow" in str(behavior_id or "")


def is_hp_potion_behavior(behavior_id: str) -> bool:
    return "hp_potion" in str(behavior_id or "")


def is_depoison_behavior(behavior_id: str) -> bool:
    return "depoison" in str(behavior_id or "")


def is_sell_behavior(behavior_id: str) -> bool:
    bid = str(behavior_id or "")
    return bid.startswith("sell_")


def is_store_behavior(behavior_id: str) -> bool:
    """Warehouse / store NPC (e.g. give_goods), not merchant sell_*."""
    bid = str(behavior_id or "")
    if bid == "give_goods" or bid.startswith("store_"):
        return True
    try:
        from shop.behaviors import ACTION_STORE, behavior_by_id, load_behaviors

        b = behavior_by_id(bid, load_behaviors())
        return b is not None and str(b.action) == ACTION_STORE
    except Exception:
        return False


def is_teleporter_behavior(behavior_id: str) -> bool:
    """Dungeon-entry teleporter NPC (npc_behaviors action=teleporter)."""
    bid = str(behavior_id or "")
    if bid.startswith("teleport_"):
        return True
    try:
        from shop.behaviors import ACTION_TELEPORTER, behavior_by_id, load_behaviors

        b = behavior_by_id(bid, load_behaviors())
        return b is not None and str(b.action) == ACTION_TELEPORTER
    except Exception:
        return False



def list_scroll_spot_ids() -> list[str]:
    """Talking-scroll spot ids from hub usage rules (all wheel depths)."""
    from app._04_decision.talking_scroll import list_talking_scroll_spot_ids

    return list_talking_scroll_spot_ids()


def list_scroll_spot_choices() -> list[tuple[str, str]]:
    """``(id, label)`` including region/name/wheels for the behavior editor."""
    from app._04_decision.talking_scroll import list_talking_scroll_spot_choices

    return list_talking_scroll_spot_choices()


def list_map_ids() -> list[str]:
    """Map pack ids under ``engine/maps/*/meta.yaml``."""
    maps_root = _PROJECT_ROOT / "data" / "maps"
    if not maps_root.is_dir():
        return ["talking_island", "mainland"]
    found = sorted(
        p.name
        for p in maps_root.iterdir()
        if p.is_dir() and (p / "meta.yaml").is_file()
    )
    return found or ["talking_island", "mainland"]


def _map_transition_map_choices(
    *,
    dungeons_only: bool | None = None,
) -> list[tuple[int, str]]:
    """``(mapId, label)`` from ``map_transitions.json``.

    ``dungeons_only=True`` → ``is_dungeon`` maps (Dest dungeon).
    ``dungeons_only=False`` → non-dungeon maps (field land).
    ``dungeons_only=None`` → every map.
    """
    path = _PROJECT_ROOT / "data" / "world" / "map_transitions.json"
    if not path.is_file():
        return []
    try:
        import json

        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    maps = doc.get("maps") or {}
    out: list[tuple[int, str]] = []
    seen: set[int] = set()
    items = maps.values() if isinstance(maps, dict) else maps
    if not isinstance(items, list):
        items = list(items) if maps else []
    for m in items:
        if not isinstance(m, dict) or m.get("mapId") is None:
            continue
        is_dungeon = bool(m.get("is_dungeon"))
        if dungeons_only is True and not is_dungeon:
            continue
        if dungeons_only is False and is_dungeon:
            continue
        try:
            mid = int(m["mapId"])
        except (TypeError, ValueError):
            continue
        if mid in seen or mid < 0:
            continue
        seen.add(mid)
        name = str(m.get("kr") or m.get("en") or mid).strip()
        out.append((mid, f"{mid} · {name}" if name else str(mid)))
    out.sort(key=lambda t: t[0])
    return out


def list_destination_dungeon_choices() -> list[tuple[int, str]]:
    """``(mapId, label)`` for teleporter destination_dungeon (is_dungeon maps)."""
    return _map_transition_map_choices(dungeons_only=True)


def list_land_map_choices() -> list[tuple[int, str]]:
    """``(mapId, label)`` for teleporter field_land (non-dungeon maps)."""
    return _map_transition_map_choices(dungeons_only=False)


def shop_ui_uv(px: tuple[float, float]) -> Position:
    """Content UV for a shop-window pixel on the Korean calibration capture."""
    return Position(x=px[0] / SHOP_UI_REF_W, y=px[1] / SHOP_UI_REF_H)


def shop_ui_clicks():
    """Buy-tab / arrow-row / confirm UVs for the current game language."""
    from app._04_decision.game_language import shop_ui_clicks as _clicks

    return _clicks()



__all__ = [
    "list_scroll_spot_ids",
    "list_scroll_spot_choices",
    "list_map_ids",
    "list_destination_dungeon_choices",
    "list_land_map_choices",
    "shop_ui_uv",
    "shop_ui_clicks",
    "ARROW_BUY_QTY",
    "BUY_NORMAL_ARROWS",
    "BUY_SILVER_ARROWS",
    "SILVER_ARROW_BUY_QTY",
    "HP_POTION_BUY_QTY",
    "HP_POTION_PRICE",
    "RESTOCK_POTIONS",
    "RETURN_WEIGHT_ENABLED",
    "SELL_WEIGHT_RATIO",
    "SELL_MODE",
    "STORE_AFTER_SELL",
    "POTION_SUPPRESS_S",
    "SHOP_ARRIVE_TILES",
    "SHOP_CLICK_TILES",
    "SHOP_NPC_SEARCH_PX",
    "SHOP_UI_REF_W",
    "SHOP_UI_REF_H",
    "SHOP_BUY_TAB_PX",
    "SHOP_ARROW_ROW_PX",
    "SHOP_CONFIRM_PX",
    "normalize_shop_locale",
    "normalize_hp_potion_npc",
    "normalize_sell_mode",
    "resolve_shopping_behavior_id",
    "resolve_sell_behavior_ids",
    "is_arrow_behavior",
    "is_hp_potion_behavior",
    "is_depoison_behavior",
    "is_sell_behavior",
    "is_store_behavior",
    "is_teleporter_behavior",
    "arrow_shop_units",
    "buy_qty_for_behavior",
    "affordable_hp_potion_qty",
]
