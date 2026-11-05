"""NPC behaviors: identity, travel, and calibrated dialog click UVs.

Canonical file: ``Engine/data/npc_behaviors.yaml``
(buy, sell, warehouse, teleporter). Kept outside ``data/maps`` so a map-pack
replace cannot wipe it.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

import yaml

_ENGINE_ROOT = Path(__file__).resolve().parents[1]
BEHAVIORS_PATH = _ENGINE_ROOT / "data" / "npc_behaviors.yaml"
# Older locations. Load copies once into BEHAVIORS_PATH when that file is missing.
_LEGACY_MAPS_BEHAVIORS = (
    _ENGINE_ROOT / "data" / "maps" / "shopping_behaviors.yaml"
)
_LEGACY_USERDATA_BEHAVIORS = (
    _ENGINE_ROOT.parent / "UserData" / "shopping_behaviors.yaml"
)
ITEM_ROW_COUNT = 7
_ID_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

ACTION_BUY = "buy"
ACTION_SELL = "sell"
ACTION_STORE = "store"
ACTION_TELEPORTER = "teleporter"
ACTIONS: tuple[str, ...] = (
    ACTION_BUY,
    ACTION_SELL,
    ACTION_STORE,
    ACTION_TELEPORTER,
)

# Teleporter arrival model (world-nav).
TELEPORT_KIND_DUNGEON_GATE = "dungeon_gate"
TELEPORT_KIND_FIELD_LAND = "field_land"
TELEPORT_KINDS: tuple[str, ...] = (
    TELEPORT_KIND_DUNGEON_GATE,
    TELEPORT_KIND_FIELD_LAND,
)

SELL_MODE_ONLY_GARBAGE = "sell_only_garbage"
SELL_MODE_EXCEPT_KEEP = "sell_except_keep"
SELL_MODES: tuple[str, ...] = (SELL_MODE_ONLY_GARBAGE, SELL_MODE_EXCEPT_KEEP)

# When ``world_nav`` is omitted in YAML, these Korean base ids stay enabled
# (pre-checkbox default). ``*_ch`` follows the same base.
_LEGACY_WORLD_NAV_BASE_IDS: frozenset[str] = frozenset(
    (
        "teleport_talking_island",
        "teleport_giran",
        "teleport_gludin",
    )
)

_HEADER = """# NPC behaviors — buy/sell/store/teleporter (travel + dialog UVs).
# npc_world: absolute game coordinates (memory monitor space).
# scroll_spot: talking-scroll spot id (hubs usage rules; wheels live on the spot).
# click_offset_uv: optional [du, dv] added to computed NPC content UV when opening.
#   When set → single click at (A + offset). When unset → cursor-search open.
# adena_cost: teleporter fare in adena (affordability gate vs walk path); 0 = free/unset.
# teleport_kind: dungeon_gate (default) | field_land.
#   dungeon_gate: destination_dungeon = LC mapId (ground_enter.to). Same NPC can have
#     one behavior per dungeon (e.g. Giran → 30 vs 53). After SHOP_RUN, world-nav
#     rewrites the next gate to the nearest matching entrance.
#   field_land: land_map_id + land_world = same-map (or other) field xy after the
#     dialog (e.g. Giran TP → Dragon Valley field). No dungeon gate rewrite.
# world_nav: true → world-nav planner may use this teleporter (Shopping Practice checkbox).
# ui.*: content-normalized UVs [u, v] on the perception capture (0..1).
# item_index: 0-based index in the full merchant list (7 rows visible) — buy only.
# sell_mode: sell_only_garbage | sell_except_keep (sell/store).
# Prefer sell_except_keep: keep_list = names to retain; all other sell-tab rows sell.
# garbage_list / keep_list: shared item-name filters for ALL sell behaviors (file-level).
# Live sell/store: shop_listen memory list + list scroll (item_index rule: scroll = max(0,n-6)).
# store: warehouse keeper (e.g. give_goods); same dialog UVs as sell for now.
# teleporter: option + confirm only (no slot/qty); dungeon or field shortcut via NPC.
# Engine data: Engine/data/npc_behaviors.yaml (not inside maps/, not UserData).
# Edited by Shopping Practice / bot_data_editors tools.
#
"""


@dataclass(frozen=True)
class ShoppingSellFilters:
    """Shared sell name lists (one set for the whole catalog)."""

    garbage_list: tuple[str, ...] = ()
    keep_list: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "garbage_list": list(self.garbage_list),
            "keep_list": list(self.keep_list),
        }


@dataclass(frozen=True)
class ShoppingUiClicks:
    """Dialog click points in content UV space."""

    buy_button: Optional[tuple[float, float]] = None
    sell_button: Optional[tuple[float, float]] = None
    list_scroll_point: Optional[tuple[float, float]] = None
    confirm_button: Optional[tuple[float, float]] = None
    item_rows: tuple[Optional[tuple[float, float]], ...] = field(
        default_factory=lambda: tuple(None for _ in range(ITEM_ROW_COUNT))
    )

    def to_mapping(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.buy_button is not None:
            data["buy_button"] = [float(self.buy_button[0]), float(self.buy_button[1])]
        if self.sell_button is not None:
            data["sell_button"] = [
                float(self.sell_button[0]),
                float(self.sell_button[1]),
            ]
        if self.list_scroll_point is not None:
            data["list_scroll_point"] = [
                float(self.list_scroll_point[0]),
                float(self.list_scroll_point[1]),
            ]
        if self.confirm_button is not None:
            data["confirm_button"] = [
                float(self.confirm_button[0]),
                float(self.confirm_button[1]),
            ]
        rows = []
        for pt in self.item_rows:
            if pt is None:
                rows.append(None)
            else:
                rows.append([float(pt[0]), float(pt[1])])
        if any(r is not None for r in rows):
            data["item_rows"] = rows
        return data

    def calibrated(self, *, action: str | None = None) -> bool:
        """True when enough UVs exist for the given action (or either if unset)."""
        rows_ok = sum(1 for r in self.item_rows if r is not None) == ITEM_ROW_COUNT
        act = str(action or "").strip().lower()
        if act == ACTION_TELEPORTER:
            # Option click + confirm only (no list scroll / item rows / qty).
            return bool(
                self.buy_button is not None and self.confirm_button is not None
            )
        if act in (ACTION_SELL, ACTION_STORE):
            # Memory sell/store: sell/confirm + 7 item rows + list scroll.
            return bool(
                rows_ok
                and self.sell_button is not None
                and self.list_scroll_point is not None
                and self.confirm_button is not None
            )
        if act == ACTION_BUY:
            return bool(
                rows_ok
                and self.buy_button is not None
                and self.list_scroll_point is not None
                and self.confirm_button is not None
            )
        mode_ok = self.buy_button is not None or self.sell_button is not None
        return bool(
            rows_ok
            and mode_ok
            and self.list_scroll_point is not None
            and self.confirm_button is not None
        )


@dataclass(frozen=True)
class ShoppingBehavior:
    id: str
    name: str
    action: str  # buy | sell | store | teleporter
    map_id: str
    scroll_spot: str
    npc_world_x: int
    npc_world_y: int
    default_qty: int = 200
    item_index: int = 0
    # Teleporter fare (adena). Ignored for buy/sell/store (forced 0 on save).
    adena_cost: int = 0
    # Teleporter: dungeon_gate (ground_enter dest) or field_land (absolute land xy).
    teleport_kind: str = TELEPORT_KIND_DUNGEON_GATE
    # Teleporter dungeon_gate: LC mapId of the dungeon this option enters.
    destination_dungeon: int = 0
    # Teleporter field_land: LC mapId + absolute game xy after the dialog.
    land_map_id: int = 0
    land_world_x: int = 0
    land_world_y: int = 0
    # Teleporter: include in world-nav NPC teleporter graph (Shopping Practice toggle).
    world_nav: bool = False
    # Per sell/store behavior; name lists live in ShoppingSellFilters (file-level).
    sell_mode: str = SELL_MODE_EXCEPT_KEEP
    # Content-UV delta added to computed NPC point A when opening the dialog.
    # None → cursor-search open (legacy). Set → single click at A + offset.
    click_offset_uv: Optional[tuple[float, float]] = None
    ui: ShoppingUiClicks = field(default_factory=ShoppingUiClicks)

    def has_click_offset(self) -> bool:
        return self.click_offset_uv is not None

    def is_field_land(self) -> bool:
        return (
            self.action == ACTION_TELEPORTER
            and str(self.teleport_kind or "") == TELEPORT_KIND_FIELD_LAND
        )

    def to_mapping(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "map": self.map_id,
            "scroll_spot": self.scroll_spot,
            "npc_world": [int(self.npc_world_x), int(self.npc_world_y)],
        }
        if self.click_offset_uv is not None:
            data["click_offset_uv"] = [
                float(self.click_offset_uv[0]),
                float(self.click_offset_uv[1]),
            ]
        if self.action == ACTION_BUY:
            data["default_qty"] = int(self.default_qty)
            data["item_index"] = int(self.item_index)
        elif self.action in (ACTION_SELL, ACTION_STORE):
            data["default_qty"] = int(self.default_qty)
            data["item_index"] = int(self.item_index)
            data["sell_mode"] = str(self.sell_mode or SELL_MODE_ONLY_GARBAGE)
        elif self.action == ACTION_TELEPORTER:
            kind = _normalize_teleport_kind(
                self.teleport_kind,
                destination_dungeon=self.destination_dungeon,
                land_map_id=self.land_map_id,
            )
            data["adena_cost"] = max(0, int(self.adena_cost))
            data["teleport_kind"] = kind
            data["world_nav"] = bool(self.world_nav)
            if kind == TELEPORT_KIND_FIELD_LAND:
                data["destination_dungeon"] = 0
                data["land_map_id"] = max(0, int(self.land_map_id))
                data["land_world"] = [
                    int(self.land_world_x),
                    int(self.land_world_y),
                ]
            else:
                data["destination_dungeon"] = max(0, int(self.destination_dungeon))
        ui = self.ui.to_mapping()
        if self.action == ACTION_TELEPORTER:
            # Keep only option (buy_button) + confirm; drop shop list markers.
            slim: dict[str, Any] = {}
            if "buy_button" in ui:
                slim["buy_button"] = ui["buy_button"]
            if "confirm_button" in ui:
                slim["confirm_button"] = ui["confirm_button"]
            ui = slim
        if ui:
            data["ui"] = ui
        return data

    def visible_row_for_item(self) -> int:
        """Which of the 7 on-screen rows to click after scrolling."""
        n = max(0, int(self.item_index))
        return min(n, ITEM_ROW_COUNT - 1)

    def scroll_steps_for_item(self) -> int:
        """Mouse-wheel downs needed so item_index is in the visible window."""
        n = max(0, int(self.item_index))
        return max(0, n - (ITEM_ROW_COUNT - 1))


def behaviors_path() -> Path:
    return BEHAVIORS_PATH


def _clamp_uv(pt: Any) -> Optional[tuple[float, float]]:
    if pt is None:
        return None
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        return None
    try:
        u, v = float(pt[0]), float(pt[1])
    except (TypeError, ValueError):
        return None
    return (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))


def _parse_offset_uv(pt: Any) -> Optional[tuple[float, float]]:
    """Signed content-UV delta (B − A). Not clamped to [0,1]."""
    if pt is None:
        return None
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        return None
    try:
        du, dv = float(pt[0]), float(pt[1])
    except (TypeError, ValueError):
        return None
    if not (-1.0 <= du <= 1.0 and -1.0 <= dv <= 1.0):
        return None
    return (du, dv)


def _parse_ui(raw: Any) -> ShoppingUiClicks:
    if not isinstance(raw, dict):
        return ShoppingUiClicks()
    rows_raw = raw.get("item_rows")
    rows: list[Optional[tuple[float, float]]] = [
        None for _ in range(ITEM_ROW_COUNT)
    ]
    if isinstance(rows_raw, list):
        for i in range(min(ITEM_ROW_COUNT, len(rows_raw))):
            rows[i] = _clamp_uv(rows_raw[i])
    return ShoppingUiClicks(
        buy_button=_clamp_uv(raw.get("buy_button")),
        sell_button=_clamp_uv(raw.get("sell_button")),
        list_scroll_point=_clamp_uv(raw.get("list_scroll_point")),
        confirm_button=_clamp_uv(raw.get("confirm_button")),
        item_rows=tuple(rows),
    )


def _parse_name_list(raw: Any) -> tuple[str, ...]:
    """YAML list or newline/comma string → unique non-empty item names (order kept)."""
    names: list[str] = []
    if raw is None:
        return ()
    if isinstance(raw, str):
        parts = re.split(r"[\n,;]+", raw)
        candidates = parts
    elif isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        return ()
    seen: set[str] = set()
    for part in candidates:
        name = str(part or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def _parse_sell_mode(raw: Any, *, action: str) -> str:
    mode = str(raw or SELL_MODE_EXCEPT_KEEP).strip()
    if mode not in SELL_MODES:
        mode = SELL_MODE_EXCEPT_KEEP
    if action not in (ACTION_SELL, ACTION_STORE):
        return SELL_MODE_EXCEPT_KEEP
    return mode


def _legacy_world_nav_default(behavior_id: str) -> bool:
    sid = str(behavior_id or "").strip()
    if sid.endswith("_ch"):
        sid = sid[:-3]
    return sid in _LEGACY_WORLD_NAV_BASE_IDS


def _normalize_teleport_kind(
    raw: Any,
    *,
    destination_dungeon: int = 0,
    land_map_id: int = 0,
) -> str:
    """Resolve teleport_kind; legacy rows without the key keep dungeon_gate."""
    text = str(raw or "").strip().lower()
    if text in TELEPORT_KINDS:
        return text
    if int(land_map_id or 0) > 0 and int(destination_dungeon or 0) <= 0:
        return TELEPORT_KIND_FIELD_LAND
    return TELEPORT_KIND_DUNGEON_GATE


def _parse_world_nav_flag(raw: Any, *, behavior_id: str) -> bool:
    if raw is None:
        return _legacy_world_nav_default(behavior_id)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return _legacy_world_nav_default(behavior_id)


def _catalog_keys_for_names(names: tuple[str, ...] | list[str]) -> set[str]:
    """Map stored filter names to catalog keys (+ raw) for locale-stable match."""
    keys: set[str] = set()
    try:
        from app._03_world.catalog.game_catalog import resolve_item_key
    except Exception:
        resolve_item_key = None  # type: ignore[assignment]
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        keys.add(name)
        if resolve_item_key is not None:
            try:
                key = resolve_item_key(name)
            except Exception:
                key = None
            if key:
                keys.add(str(key).strip())
    return keys


def item_passes_sell_filter(
    kr_name: str,
    *,
    sell_mode: str,
    garbage_list: tuple[str, ...] | list[str],
    keep_list: tuple[str, ...] | list[str],
    item_id: int = 0,
) -> bool:
    """Whether a sell-list item should be sold under the active mode.

    Names are matched as stored strings and via ``game_catalog.resolve_item_key``.
    Adena (id 5) is never sold.
    """
    if int(item_id or 0) == 5:
        return False
    name = str(kr_name or "").strip()
    mode = str(sell_mode or SELL_MODE_EXCEPT_KEEP).strip()
    garbage = _catalog_keys_for_names(garbage_list)
    keep = _catalog_keys_for_names(keep_list)
    name_keys = _catalog_keys_for_names((name,)) if name else set()
    if name_keys & keep:
        return False
    if mode == SELL_MODE_EXCEPT_KEEP:
        if not name and item_id:
            # Unresolved name: sell unless keep listed by id-less names only.
            return True
        return not bool(name_keys & keep)
    if not name:
        return False
    return bool(name_keys & garbage)


def resolve_active_sell_mode(
    *,
    filters: ShoppingSellFilters | None = None,
    behaviors: list[ShoppingBehavior] | None = None,
) -> str:
    """Sell-mode used by Debug and live sell (keep UI wins over YAML NPC modes).

    If ``keep_list`` is non-empty → ``sell_except_keep``. Otherwise the first
    sell behavior's mode, else ``sell_except_keep``.
    """
    if filters is None:
        filters = load_sell_filters()
    if filters.keep_list:
        return SELL_MODE_EXCEPT_KEEP
    if behaviors is None:
        behaviors = load_behaviors()
    for behavior in behaviors:
        if behavior.action != "sell":
            continue
        mode = str(behavior.sell_mode or "").strip()
        if mode in SELL_MODES:
            return mode
    return SELL_MODE_EXCEPT_KEEP


def _behavior_from_mapping(item: Any, *, index: int) -> ShoppingBehavior:
    if not isinstance(item, dict):
        raise ValueError(f"behaviors[{index}] must be a mapping")
    sid = str(item.get("id") or "").strip()
    if not sid or not _ID_SAFE.match(sid):
        raise ValueError(f"behaviors[{index}] needs a safe id")
    action = str(item.get("action") or ACTION_BUY).strip().lower()
    # Legacy: warehouse give_goods was stored as sell.
    if sid == "give_goods" and action == ACTION_SELL:
        action = ACTION_STORE
    if action not in ACTIONS:
        raise ValueError(
            f"behavior {sid!r}: action must be buy, sell, store, or teleporter"
        )
    world = item.get("npc_world") or item.get("world")
    if not (isinstance(world, (list, tuple)) and len(world) >= 2):
        raise ValueError(f"behavior {sid!r} needs npc_world: [x, y]")
    map_id = str(item.get("map") or item.get("map_id") or "").strip()
    scroll = str(item.get("scroll_spot") or "").strip()
    if not map_id:
        raise ValueError(f"behavior {sid!r} needs map")
    if not scroll:
        raise ValueError(f"behavior {sid!r} needs scroll_spot")
    default_qty_raw = 1 if action == ACTION_TELEPORTER else 200
    try:
        qty = max(1, min(999, int(item.get("default_qty", default_qty_raw))))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"behavior {sid!r}: bad default_qty") from exc
    try:
        item_index = max(0, int(item.get("item_index", 0)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"behavior {sid!r}: bad item_index") from exc
    try:
        adena_cost = max(0, int(item.get("adena_cost", 0) or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"behavior {sid!r}: bad adena_cost") from exc
    try:
        destination_dungeon = max(
            0, int(item.get("destination_dungeon", 0) or 0)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"behavior {sid!r}: bad destination_dungeon") from exc
    try:
        land_map_id = max(0, int(item.get("land_map_id", 0) or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"behavior {sid!r}: bad land_map_id") from exc
    land = item.get("land_world")
    land_world_x = 0
    land_world_y = 0
    if isinstance(land, (list, tuple)) and len(land) >= 2:
        try:
            land_world_x = int(land[0])
            land_world_y = int(land[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"behavior {sid!r}: bad land_world") from exc
    teleport_kind = TELEPORT_KIND_DUNGEON_GATE
    if action == ACTION_TELEPORTER:
        qty = 1
        item_index = 0
        world_nav = _parse_world_nav_flag(item.get("world_nav"), behavior_id=sid)
        teleport_kind = _normalize_teleport_kind(
            item.get("teleport_kind"),
            destination_dungeon=destination_dungeon,
            land_map_id=land_map_id,
        )
        if teleport_kind == TELEPORT_KIND_FIELD_LAND:
            destination_dungeon = 0
        else:
            land_map_id = 0
            land_world_x = 0
            land_world_y = 0
    else:
        adena_cost = 0
        destination_dungeon = 0
        land_map_id = 0
        land_world_x = 0
        land_world_y = 0
        world_nav = False
        teleport_kind = TELEPORT_KIND_DUNGEON_GATE
    sell_mode = _parse_sell_mode(item.get("sell_mode"), action=action)
    ui = _parse_ui(item.get("ui"))
    if action == ACTION_TELEPORTER:
        ui = ShoppingUiClicks(
            buy_button=ui.buy_button,
            confirm_button=ui.confirm_button,
        )
    click_offset_uv = _parse_offset_uv(item.get("click_offset_uv"))
    return ShoppingBehavior(
        id=sid,
        name=str(item.get("name") or sid).strip(),
        action=action,
        map_id=map_id,
        scroll_spot=scroll,
        npc_world_x=int(world[0]),
        npc_world_y=int(world[1]),
        default_qty=qty,
        item_index=item_index,
        adena_cost=adena_cost,
        teleport_kind=teleport_kind,
        destination_dungeon=destination_dungeon,
        land_map_id=land_map_id,
        land_world_x=land_world_x,
        land_world_y=land_world_y,
        world_nav=world_nav,
        sell_mode=sell_mode,
        click_offset_uv=click_offset_uv,
        ui=ui,
    )


def _merge_name_lists(*lists: tuple[str, ...]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for name in lst:
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
    return tuple(names)


def _sell_filters_from_doc(doc: dict[str, Any]) -> ShoppingSellFilters:
    """Read shared lists; hoist legacy per-behavior lists if file-level empty."""
    garbage = _parse_name_list(doc.get("garbage_list"))
    keep = _parse_name_list(doc.get("keep_list"))
    raw = doc.get("behaviors")
    if (not garbage and not keep) and isinstance(raw, list):
        legacy_g: list[tuple[str, ...]] = []
        legacy_k: list[tuple[str, ...]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            legacy_g.append(_parse_name_list(item.get("garbage_list")))
            legacy_k.append(_parse_name_list(item.get("keep_list")))
        garbage = _merge_name_lists(*legacy_g)
        keep = _merge_name_lists(*legacy_k)
    return ShoppingSellFilters(garbage_list=garbage, keep_list=keep)


def default_behavior(behavior_id: str = "new_behavior") -> ShoppingBehavior:
    return ShoppingBehavior(
        id=behavior_id,
        name="New NPC behavior",
        action="buy",
        map_id="talking_island",
        scroll_spot="ti_general_goods",
        npc_world_x=0,
        npc_world_y=0,
        default_qty=200,
        item_index=0,
        ui=ShoppingUiClicks(),
    )


def seed_behaviors() -> list[ShoppingBehavior]:
    """Default catalog when engine data file is missing."""
    return [
        ShoppingBehavior(
            id="buy_normal_arrows",
            name="Buy normal arrows",
            action="buy",
            map_id="talking_island",
            scroll_spot="ti_general_goods",
            npc_world_x=32642,
            npc_world_y=32946,
            default_qty=200,
            item_index=0,
            ui=ShoppingUiClicks(),
        )
    ]


def _ensure_behaviors_file(path: Path) -> Path:
    """Return ``path``, copying an older catalog in once if the live file is missing."""
    if path.is_file():
        return path
    if path != BEHAVIORS_PATH:
        return path
    for legacy in (_LEGACY_MAPS_BEHAVIORS, _LEGACY_USERDATA_BEHAVIORS):
        if not legacy.is_file():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, path)
        try:
            legacy.unlink()
        except OSError:
            pass
        return path
    return path


def load_sell_filters(path: Optional[Path] = None) -> ShoppingSellFilters:
    """Load shared garbage/keep lists (empty if file missing)."""
    source = path or BEHAVIORS_PATH
    if path is None:
        _ensure_behaviors_file(source)
    if not source.is_file():
        return ShoppingSellFilters()
    doc = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{source.name} must be a mapping")
    return _sell_filters_from_doc(doc)


def load_behaviors(path: Optional[Path] = None) -> list[ShoppingBehavior]:
    """Load behaviors from engine data (seed+write if missing)."""
    source = path or BEHAVIORS_PATH
    if path is None:
        _ensure_behaviors_file(source)
    if not source.is_file():
        seeded = seed_behaviors()
        if path is None:
            save_behaviors(seeded, source)
        return seeded
    doc = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{source.name} must be a mapping")
    raw = doc.get("behaviors")
    if not isinstance(raw, list):
        raise ValueError(f"{source.name}: missing behaviors list")
    behaviors: list[ShoppingBehavior] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        b = _behavior_from_mapping(item, index=i)
        if b.id in seen:
            raise ValueError(f"duplicate behavior id {b.id!r}")
        seen.add(b.id)
        behaviors.append(b)
    return behaviors


def save_behaviors(
    behaviors: list[ShoppingBehavior],
    path: Optional[Path] = None,
    *,
    sell_filters: Optional[ShoppingSellFilters] = None,
) -> Path:
    """Validate and write ``Engine/data/npc_behaviors.yaml``."""
    target = path or BEHAVIORS_PATH
    if sell_filters is None:
        sell_filters = (
            load_sell_filters(target) if target.is_file() else ShoppingSellFilters()
        )
    else:
        sell_filters = ShoppingSellFilters(
            garbage_list=_parse_name_list(list(sell_filters.garbage_list)),
            keep_list=_parse_name_list(list(sell_filters.keep_list)),
        )
    cleaned: list[ShoppingBehavior] = []
    seen: set[str] = set()
    for i, b in enumerate(behaviors):
        if not isinstance(b, ShoppingBehavior):
            raise TypeError(f"behaviors[{i}] must be ShoppingBehavior")
        sid = str(b.id).strip()
        if not sid or not _ID_SAFE.match(sid):
            raise ValueError(f"behaviors[{i}] needs a safe id")
        if sid in seen:
            raise ValueError(f"duplicate behavior id {sid!r}")
        seen.add(sid)
        action = str(b.action).strip().lower()
        if action not in ACTIONS:
            raise ValueError(f"{sid}: action must be buy, sell, store, or teleporter")
        if sid == "give_goods" and action == ACTION_SELL:
            action = ACTION_STORE
        if not str(b.map_id).strip():
            raise ValueError(f"{sid}: map required")
        if not str(b.scroll_spot).strip():
            raise ValueError(f"{sid}: scroll_spot required")
        sell_mode = _parse_sell_mode(b.sell_mode, action=action)
        qty = max(1, min(999, int(b.default_qty)))
        item_index = max(0, int(b.item_index))
        adena_cost = max(0, int(b.adena_cost))
        destination_dungeon = max(0, int(b.destination_dungeon))
        land_map_id = max(0, int(getattr(b, "land_map_id", 0) or 0))
        land_world_x = int(getattr(b, "land_world_x", 0) or 0)
        land_world_y = int(getattr(b, "land_world_y", 0) or 0)
        teleport_kind = TELEPORT_KIND_DUNGEON_GATE
        if action == ACTION_TELEPORTER:
            qty = 1
            item_index = 0
            world_nav = bool(getattr(b, "world_nav", False))
            teleport_kind = _normalize_teleport_kind(
                getattr(b, "teleport_kind", None),
                destination_dungeon=destination_dungeon,
                land_map_id=land_map_id,
            )
            if teleport_kind == TELEPORT_KIND_FIELD_LAND:
                destination_dungeon = 0
                if land_map_id <= 0:
                    raise ValueError(f"{sid}: field_land needs land_map_id")
            else:
                land_map_id = 0
                land_world_x = 0
                land_world_y = 0
                if destination_dungeon <= 0:
                    raise ValueError(f"{sid}: dungeon_gate needs destination_dungeon")
            ui = ShoppingUiClicks(
                buy_button=b.ui.buy_button,
                confirm_button=b.ui.confirm_button,
            )
        else:
            adena_cost = 0
            destination_dungeon = 0
            land_map_id = 0
            land_world_x = 0
            land_world_y = 0
            world_nav = False
            teleport_kind = TELEPORT_KIND_DUNGEON_GATE
            rows = list(b.ui.item_rows)
            while len(rows) < ITEM_ROW_COUNT:
                rows.append(None)
            rows = rows[:ITEM_ROW_COUNT]
            ui = ShoppingUiClicks(
                buy_button=b.ui.buy_button,
                sell_button=b.ui.sell_button,
                list_scroll_point=b.ui.list_scroll_point,
                confirm_button=b.ui.confirm_button,
                item_rows=tuple(rows),
            )
        cleaned.append(
            replace(
                b,
                id=sid,
                name=str(b.name or sid).strip(),
                action=action,
                map_id=str(b.map_id).strip(),
                scroll_spot=str(b.scroll_spot).strip(),
                npc_world_x=int(b.npc_world_x),
                npc_world_y=int(b.npc_world_y),
                default_qty=qty,
                item_index=item_index,
                adena_cost=adena_cost,
                teleport_kind=teleport_kind,
                destination_dungeon=destination_dungeon,
                land_map_id=land_map_id,
                land_world_x=land_world_x,
                land_world_y=land_world_y,
                world_nav=world_nav,
                sell_mode=sell_mode,
                click_offset_uv=_parse_offset_uv(b.click_offset_uv),
                ui=ui,
            )
        )
    payload: dict[str, Any] = {
        **sell_filters.to_mapping(),
        "behaviors": [b.to_mapping() for b in cleaned],
    }
    body = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(_HEADER + body, encoding="utf-8", newline="\n")
    tmp.replace(target)
    return target


def apply_sell_mode(mode: str) -> bool:
    """Point every sell behavior at one shared mode. Returns False if nothing changed."""
    chosen = mode if mode in SELL_MODES else SELL_MODE_ONLY_GARBAGE
    behaviors = load_behaviors()
    updated = [
        replace(behavior, sell_mode=chosen)
        if behavior.action == "sell" and behavior.sell_mode != chosen
        else behavior
        for behavior in behaviors
    ]
    if updated == behaviors:
        return False
    save_behaviors(updated)
    return True


def behavior_by_id(
    behavior_id: str,
    behaviors: Optional[list[ShoppingBehavior]] = None,
) -> Optional[ShoppingBehavior]:
    want = str(behavior_id).strip()
    for b in behaviors if behaviors is not None else load_behaviors():
        if b.id == want:
            return b
    return None


def update_click_offset_uv(
    behavior_id: str,
    offset_uv: Optional[tuple[float, float]],
    *,
    path: Optional[Path] = None,
) -> ShoppingBehavior:
    """Persist ``click_offset_uv`` on one behavior in npc_behaviors.yaml."""
    want = str(behavior_id).strip()
    behaviors = load_behaviors(path)
    found: Optional[ShoppingBehavior] = None
    updated: list[ShoppingBehavior] = []
    for b in behaviors:
        if b.id != want:
            updated.append(b)
            continue
        off = _parse_offset_uv(offset_uv) if offset_uv is not None else None
        found = replace(b, click_offset_uv=off)
        updated.append(found)
    if found is None:
        raise KeyError(f"unknown behavior id {want!r}")
    save_behaviors(updated, path)
    return found
