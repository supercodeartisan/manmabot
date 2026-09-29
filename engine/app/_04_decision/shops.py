"""Shop catalog: talking-scroll destinations with a world tile.

Loaded from ``maps/shops.yaml``. Shopping *when* / *how* is not decided here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from app._03_world import Position
from app._03_world.memory_sync import get_map_origin
from app._03_world.world_coords import WorldOrigin, world_to_content

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SHOPS_PATH = _PROJECT_ROOT / "maps" / "shops.yaml"

_shops: list["Shop"] = []
_loaded = False

# How many arrows to type into the shop buy field (1–999; Version 1 UI overrides).
ARROW_BUY_QTY = 200
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
SELL_WEIGHT_RATIO = 0.85  # bag weight_ratio ≥ this → sell trip (default 85%)
# Item/Sell mode: sell_only_garbage | sell_except_keep.
SELL_MODE = "sell_except_keep"
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
    """Ordered sell YAML ids. No UI NPC picker — locale + SELL_MODE only.

    Four NPCs: existing TI + weapon, then mainland general + mainland armor.
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


def buy_qty_for_behavior(behavior_id: str) -> int | None:
    """UI quantity for a calibrated buy behavior, or None to use YAML default."""
    bid = str(behavior_id or "")
    if "silver_arrow" in bid:
        return max(1, min(999, int(SILVER_ARROW_BUY_QTY)))
    if "normal_arrow" in bid:
        return max(1, min(999, int(ARROW_BUY_QTY)))
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
    return str(behavior_id or "").startswith("sell_")


@dataclass(frozen=True)
class Shop:
    """One shop the bot can visit.

    ``world_x`` / ``world_y`` are absolute game coordinates. ``scroll_spot``
    is the talking-scroll row that lands near that tile.
    ``roles`` tags what this NPC is used for (arrows, potions, …).
    """

    id: str
    name: str
    label: str
    map_id: str
    scroll_spot: str
    world_x: int
    world_y: int
    roles: tuple[str, ...] = ()

    def nav_tile(self, origin: WorldOrigin | tuple[int, int]) -> tuple[int, int]:
        """Nav tile on this shop's map: ``world - pack origin``."""
        if isinstance(origin, WorldOrigin):
            ox, oy = int(origin.x), int(origin.y)
        else:
            ox, oy = int(origin[0]), int(origin[1])
        return (self.world_x - ox, self.world_y - oy)

    def scroll_click_uv(self) -> Optional[Position]:
        """HUD click for this shop's talking-scroll row."""
        from app._04_decision.talking_scroll import click_uv_for_id

        return click_uv_for_id(self.scroll_spot)

    def npc_click_uv(self, origin: WorldOrigin) -> Position:
        """Content UV of this shop's world tile relative to the player."""
        nav = self.nav_tile(get_map_origin())
        return world_to_content(float(nav[0] - origin.x), float(nav[1] - origin.y))

    def to_mapping(self) -> dict[str, Any]:
        """YAML-friendly dict for ``maps/shops.yaml``."""
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "map": self.map_id,
            "scroll_spot": self.scroll_spot,
            "world": [int(self.world_x), int(self.world_y)],
        }
        if self.roles:
            data["roles"] = list(self.roles)
        return data


# Goods / purpose tags for the shop list editor and later buy methods.
SHOP_ROLE_CHOICES: tuple[str, ...] = (
    "arrows",
    "potions",
    "repair",
    "general",
    "weapons",
    "armor",
)

_SHOPS_YAML_HEADER = """# Shop catalog — each shop is reached with the talking scroll.
# world: absolute game coordinates (same space as memory monitor position).
# nav tile on that map = world - maps/<map>/meta.yaml origin.
# scroll_spot: id in app/_04_decision/talking_scroll.py ROWS (kind: spot).
# roles: optional tags (arrows, potions, repair, …) for buy/sell methods.
#
"""


def shops_path() -> Path:
    return _DEFAULT_SHOPS_PATH


def load_shops(path: Optional[Path] = None) -> list[Shop]:
    """Read the catalog from YAML. Replaces the in-memory list."""
    global _shops, _loaded
    source = path or _DEFAULT_SHOPS_PATH
    doc: Any = {}
    if source.is_file():
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            doc = loaded
    raw = doc.get("shops") if isinstance(doc.get("shops"), list) else []
    shops: list[Shop] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        shop = _shop_from_mapping(item, index=i)
        if shop.id in seen:
            raise ValueError(f"maps/shops.yaml: duplicate shop id {shop.id!r}")
        seen.add(shop.id)
        shops.append(shop)
    _shops = shops
    _loaded = True
    return list(_shops)


def save_shops(
    shops: list[Shop],
    path: Optional[Path] = None,
) -> Path:
    """Write the catalog to YAML and reload the in-memory list (live bot file)."""
    global _shops, _loaded
    target = path or _DEFAULT_SHOPS_PATH
    cleaned: list[Shop] = []
    seen: set[str] = set()
    for i, shop in enumerate(shops):
        if not isinstance(shop, Shop):
            raise TypeError(f"shops[{i}] must be Shop")
        sid = str(shop.id).strip()
        if not sid:
            raise ValueError(f"shops[{i}] needs an id")
        if sid in seen:
            raise ValueError(f"duplicate shop id {sid!r}")
        seen.add(sid)
        if not str(shop.scroll_spot).strip():
            raise ValueError(f"shop {sid!r} needs scroll_spot")
        if not str(shop.map_id).strip():
            raise ValueError(f"shop {sid!r} needs map")
        cleaned.append(
            Shop(
                id=sid,
                name=str(shop.name or sid).strip(),
                label=str(shop.label or "").strip(),
                map_id=str(shop.map_id).strip(),
                scroll_spot=str(shop.scroll_spot).strip(),
                world_x=int(shop.world_x),
                world_y=int(shop.world_y),
                roles=tuple(
                    str(r).strip()
                    for r in (shop.roles or ())
                    if str(r).strip()
                ),
            )
        )
    payload = {"shops": [s.to_mapping() for s in cleaned]}
    # Avoid sort_keys= (not always accepted); keep insertion order from dicts.
    body = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(_SHOPS_YAML_HEADER + body, encoding="utf-8", newline="\n")
    tmp.replace(target)
    _shops = cleaned
    _loaded = True
    return target


def get_shops() -> list[Shop]:
    """All shops, loading the default YAML on first call."""
    if not _loaded:
        load_shops()
    return list(_shops)


def reload_shops(path: Optional[Path] = None) -> list[Shop]:
    """Force re-read from disk (after external edits)."""
    return load_shops(path)


def shop_by_id(shop_id: str) -> Optional[Shop]:
    want = str(shop_id).strip()
    for shop in get_shops():
        if shop.id == want:
            return shop
    return None


def shops_with_role(role: str) -> list[Shop]:
    """Shops tagged with ``role`` (empty roles match nothing)."""
    want = str(role).strip().lower()
    if not want:
        return []
    return [
        shop
        for shop in get_shops()
        if want in {r.lower() for r in shop.roles}
    ]


def shop_for_scroll_spot(spot_id: str) -> Optional[Shop]:
    want = str(spot_id).strip()
    for shop in get_shops():
        if shop.scroll_spot == want:
            return shop
    return None


def list_scroll_spot_ids() -> list[str]:
    """Talking-scroll spot ids (clickable rows) for the shop editor."""
    from app._04_decision.talking_scroll import ROWS

    return [
        str(row["id"])
        for row in ROWS
        if row.get("kind") == "spot" and row.get("id")
    ]


def list_map_ids() -> list[str]:
    """Map pack ids under ``engine/maps/*/meta.yaml``."""
    maps_root = _PROJECT_ROOT / "maps"
    if not maps_root.is_dir():
        return ["talking_island", "mainland"]
    found = sorted(
        p.name
        for p in maps_root.iterdir()
        if p.is_dir() and (p / "meta.yaml").is_file()
    )
    return found or ["talking_island", "mainland"]


def shop_ui_uv(px: tuple[float, float]) -> Position:
    """Content UV for a shop-window pixel on the Korean calibration capture."""
    return Position(x=px[0] / SHOP_UI_REF_W, y=px[1] / SHOP_UI_REF_H)


def shop_ui_clicks():
    """Buy-tab / arrow-row / confirm UVs for the current game language."""
    from app._04_decision.game_language import shop_ui_clicks as _clicks

    return _clicks()


def _shop_from_mapping(item: Any, *, index: int) -> Shop:
    if not isinstance(item, dict):
        raise ValueError(f"maps/shops.yaml shops[{index}] must be a mapping")
    sid = str(item.get("id") or "").strip()
    if not sid:
        raise ValueError(f"maps/shops.yaml shops[{index}] needs an id")
    world = item.get("world")
    if not (isinstance(world, (list, tuple)) and len(world) >= 2):
        raise ValueError(f"maps/shops.yaml shop {sid!r} needs world: [x, y]")
    scroll_spot = str(item.get("scroll_spot") or "").strip()
    if not scroll_spot:
        raise ValueError(f"maps/shops.yaml shop {sid!r} needs scroll_spot")
    name = str(item.get("name") or sid).strip()
    label = str(item.get("label") or "").strip()
    map_id = str(item.get("map") or "").strip()
    if not map_id:
        raise ValueError(f"maps/shops.yaml shop {sid!r} needs map")
    raw_roles = item.get("roles") or []
    roles: list[str] = []
    if isinstance(raw_roles, str):
        roles = [p.strip() for p in raw_roles.split(",") if p.strip()]
    elif isinstance(raw_roles, (list, tuple)):
        roles = [str(p).strip() for p in raw_roles if str(p).strip()]
    return Shop(
        id=sid,
        name=name,
        label=label,
        map_id=map_id,
        scroll_spot=scroll_spot,
        world_x=int(world[0]),
        world_y=int(world[1]),
        roles=tuple(roles),
    )


__all__ = [
    "Shop",
    "SHOP_ROLE_CHOICES",
    "shops_path",
    "load_shops",
    "save_shops",
    "reload_shops",
    "get_shops",
    "shop_by_id",
    "shops_with_role",
    "shop_for_scroll_spot",
    "list_scroll_spot_ids",
    "list_map_ids",
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
    "buy_qty_for_behavior",
    "affordable_hp_potion_qty",
]
