"""L6 HP schema / tables only (no emit). Execution is L5 apply_hp_actions.

See Docs/architecture/DECISION_HIERARCHY.md.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from app._05_action.spell_box import SKILL_KEYS, slot_is_enabled, slot_press

FIXED_HP_ACTION_IDS = ("hp_potion", "heal", "retreat")
ITEM_ACTION_PREFIX = "item:"
LEGACY_POTION_ID = "hp_potion"
LEGACY_POTION_KEY = "빨간 물약"
RETREAT_ACTION_IDS = frozenset({"retreat"})
RETREAT_METHOD_ORDER = ("mother_tree", "safe_zone", "teleport")
_DEFAULT_HP_ITEMS = (LEGACY_POTION_KEY,)
_FALLBACK_HP_ITEMS = ("빨간 물약", "주홍 물약", "맑은 물약", "엔트의 열매")


def hp_item_keys() -> tuple[str, ...]:
    """Catalog restore keys (matching / aliases). Not the default HP order list."""
    try:
        from app._03_world.catalog.game_catalog import list_hp_restore_items

        keys = tuple(row.key for row in list_hp_restore_items())
        if keys:
            return keys
    except Exception:
        pass
    return _FALLBACK_HP_ITEMS


def item_action_id(item_key: str) -> str:
    return f"{ITEM_ACTION_PREFIX}{item_key}"


def is_item_action(action_id: str) -> bool:
    key = str(action_id or "").strip()
    return key == LEGACY_POTION_ID or key.startswith(ITEM_ACTION_PREFIX)


def item_key_from_action(action_id: str) -> str:
    key = str(action_id or "").strip()
    if key == LEGACY_POTION_ID:
        return LEGACY_POTION_KEY
    if key.startswith(ITEM_ACTION_PREFIX):
        return key[len(ITEM_ACTION_PREFIX) :]
    return ""


def canonical_action_id(action_id: str) -> str:
    key = str(action_id or "").strip()
    if key == LEGACY_POTION_ID:
        return item_action_id(LEGACY_POTION_KEY)
    return key


def known_hp_action_ids() -> tuple[str, ...]:
    return FIXED_HP_ACTION_IDS


HP_ACTION_IDS = known_hp_action_ids()


def default_hp_actions() -> list[dict[str, Any]]:
    """Potion L_3=50%, heal L_1=70%, retreat L_0=30%. Not an action ladder."""
    return [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.50},
        {"id": "heal", "enabled": True, "hp_below": 0.70},
        {"id": "retreat", "enabled": True, "hp_below": 0.30},
    ]


def _as_ratio(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return max(0.05, min(0.95, float(fallback)))
    if number > 1.0:
        number = number / 100.0
    return max(0.05, min(0.95, number))


def _first_engine_row(raw: Any, *wanted: str) -> dict[str, Any] | None:
    if not isinstance(raw, list):
        return None
    want_raw = {str(key).strip() for key in wanted}
    want_canon = {canonical_action_id(key) for key in wanted}
    potion_wanted = "hp_potion" in want_raw or any(is_item_action(key) for key in wanted)
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip()
        key = canonical_action_id(raw_id)
        if raw_id in want_raw or key in want_canon:
            return item
        if potion_wanted and is_item_action(raw_id):
            return item
    return None


def _migrate_retreat_row(raw: Any) -> dict[str, Any] | None:
    explicit = _first_engine_row(raw, "retreat")
    if explicit is not None:
        return explicit
    tree = _first_engine_row(raw, "mother_tree")
    if tree is not None and tree.get("enabled", True):
        return tree
    for action_id in ("safe_zone", "teleport"):
        row = _first_engine_row(raw, action_id)
        if row is not None and row.get("enabled", True):
            return row
    return None


def normalize_hp_actions(raw: Any) -> list[dict[str, Any]]:
    base = {row["id"]: dict(row) for row in default_hp_actions()}
    potion_row = _first_engine_row(raw, "hp_potion")
    heal_row = _first_engine_row(raw, "heal")
    retreat_row = _migrate_retreat_row(raw)
    if potion_row is not None:
        base["hp_potion"]["enabled"] = bool(potion_row.get("enabled", True))
        base["hp_potion"]["hp_below"] = _as_ratio(
            potion_row.get("hp_below"), base["hp_potion"]["hp_below"]
        )
        for key in ("box", "key", "item"):
            if key in potion_row and potion_row.get(key) not in (None, "", 0, "0"):
                base["hp_potion"][key] = potion_row[key]
    if heal_row is not None:
        base["heal"]["enabled"] = bool(heal_row.get("enabled", True))
        base["heal"]["hp_below"] = _as_ratio(
            heal_row.get("hp_below"), base["heal"]["hp_below"]
        )
        for key in ("box", "key"):
            if key in heal_row and heal_row.get(key) not in (None, "", 0, "0"):
                base["heal"][key] = heal_row[key]
    if retreat_row is not None:
        if str(retreat_row.get("id") or "") == "retreat":
            base["retreat"]["enabled"] = bool(retreat_row.get("enabled", True))
        else:
            base["retreat"]["enabled"] = True
        base["retreat"]["hp_below"] = _as_ratio(
            retreat_row.get("hp_below"), base["retreat"]["hp_below"]
        )
    return [base["hp_potion"], base["heal"], base["retreat"]]


def assigned_hotbar_slot(row: Mapping[str, Any] | None) -> tuple[int, str] | None:
    """Operator-assigned box+key on an engine HP action row."""
    if not isinstance(row, Mapping):
        return None
    try:
        box = int(row.get("box") or 0)
    except (TypeError, ValueError):
        return None
    key = str(row.get("key") or "").strip().lower()
    if box not in (1, 2, 3) or key not in SKILL_KEYS:
        return None
    return box, key


def action_row(actions: Iterable[Mapping[str, Any]], action_id: str) -> dict[str, Any] | None:
    wanted = canonical_action_id(action_id)
    for row in actions:
        if not isinstance(row, Mapping):
            continue
        if canonical_action_id(str(row.get("id") or "")) == wanted:
            return dict(row)
    return None


def pick_hp_action(
    ratio: float,
    actions: Iterable[Mapping[str, Any]],
    can: Mapping[str, bool],
) -> str | None:
    """First enabled action whose HP gate is met and that can fire now."""
    known = set(known_hp_action_ids())
    for row in actions:
        key = str(row.get("id") or "")
        canon = canonical_action_id(key)
        if canon not in known and not is_item_action(key):
            continue
        if not row.get("enabled", True):
            continue
        try:
            threshold = float(row.get("hp_below", 1.0))
        except (TypeError, ValueError):
            continue
        if ratio > threshold:
            continue
        if can.get(key) or can.get(canon):
            return key if can.get(key) else canon
        if (
            is_item_action(key)
            and item_key_from_action(key) == LEGACY_POTION_KEY
            and can.get(LEGACY_POTION_ID)
        ):
            return key
    return None


def action_threshold(actions: Iterable[Mapping[str, Any]], action_id: str) -> float | None:
    wanted = canonical_action_id(action_id)
    for row in actions:
        if canonical_action_id(str(row.get("id") or "")) == wanted and row.get("enabled", True):
            try:
                return float(row.get("hp_below"))
            except (TypeError, ValueError):
                return None
    return None


def _fold(text: str) -> str:
    return "".join(str(text or "").split()).lower()


def _resolved_item_key(item_key: str) -> str:
    key = item_key_from_action(item_key) or str(item_key or "").strip()
    if key.startswith(ITEM_ACTION_PREFIX):
        key = key[len(ITEM_ACTION_PREFIX) :]
    return key or LEGACY_POTION_KEY


def _item_aliases(item_key: str) -> tuple[set[str], set[int]]:
    """Catalog name/id sets for an HP item key.

    Unknown keys return the exact name only; callers still merge live ids
    discovered from hotbar/inventory by that name.
    """
    key = _resolved_item_key(item_key)
    try:
        from app._03_world.catalog.game_catalog import (
            hp_restore_item,
            hp_restore_live_name_aliases,
        )

        live_names = hp_restore_live_name_aliases(key)
        spec = hp_restore_item(key)
    except Exception:
        return {_fold(key)}, set()
    if spec is None:
        return {_fold(name) for name in live_names if name}, set()
    return {_fold(alias) for alias in spec.aliases()}, set(spec.ids)


def _slot_to_box_key(slot: int) -> tuple[int, str]:
    index = max(0, int(slot))
    return index // 8 + 1, SKILL_KEYS[index % 8]


_HOTBAR_NAME_FIELDS = ("name", "label", "name_tw", "name_cn", "kr_name")
_LAYOUT_NAME_FIELDS = ("kr_name", "zh_name", "label", "name")
_BAG_NAME_FIELDS = ("name", "name_tw", "name_cn", "name_en", "kr_name")


def _bare_name(text: str) -> str:
    raw = str(text or "").strip()
    try:
        from hotbar.inspect import fold_hotbar_name

        raw = fold_hotbar_name(raw)
    except Exception:
        pass
    return _fold(raw)


def _names_match(blob: str, aliases: set[str]) -> bool:
    """Exact folded name match after stripping stack/enchant suffixes."""
    folded = _bare_name(blob)
    return bool(folded) and folded in aliases


def _any_name_matches(raw: Mapping[str, Any] | object, aliases: set[str], fields: tuple[str, ...]) -> bool:
    """Match each name field alone — joining duplicates breaks exact fold match."""
    for field in fields:
        if isinstance(raw, Mapping):
            text = str(raw.get(field) or "").strip()
        else:
            text = str(getattr(raw, field, "") or "").strip()
        if text and _names_match(text, aliases):
            return True
    return False


def _live_catalog_id(raw: Mapping[str, Any]) -> int:
    """Catalog/template id from a hotbar/bag row.

    Live hotbar_listen uses ``cfg`` for the item template id and ``uid`` for the
    instance handle — never treat ``uid`` as a catalog id.
    """
    for field in ("id", "item_id", "cfg"):
        try:
            value = int(raw.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _iter_live_item_rows(world: Any) -> list[tuple[int, str]]:
    """(catalog_id, single_name_field) from live hotbar + bag snapshots."""
    rows: list[tuple[int, str]] = []
    if world is None:
        return rows
    snap = getattr(world, "last_hotbar", None)
    raw_slots = snap.get("slots") if isinstance(snap, Mapping) else None
    if isinstance(raw_slots, list):
        for raw in raw_slots:
            if not isinstance(raw, Mapping):
                continue
            item_id = _live_catalog_id(raw)
            for field in _HOTBAR_NAME_FIELDS:
                text = str(raw.get(field) or "").strip()
                if text:
                    rows.append((item_id, text))
    player = getattr(world, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is not None:
        for item in list(getattr(inv, "items", None) or []):
            try:
                item_id = int(getattr(item, "item_id", 0) or getattr(item, "id", 0) or 0)
            except (TypeError, ValueError):
                item_id = 0
            for field in _BAG_NAME_FIELDS:
                text = str(getattr(item, field, "") or "").strip()
                if text:
                    rows.append((item_id, text))
    bag = getattr(world, "last_inventory", None)
    bag_items = bag.get("items") if isinstance(bag, Mapping) else None
    if isinstance(bag_items, list):
        for raw in bag_items:
            if not isinstance(raw, Mapping):
                continue
            item_id = _live_catalog_id(raw)
            for field in _BAG_NAME_FIELDS:
                text = str(raw.get(field) or "").strip()
                if text:
                    rows.append((item_id, text))
    return rows


def discover_live_item_ids(world: Any, item_key: str) -> set[int]:
    """Item ids whose live hotbar/bag name exactly matches ``item_key``."""
    aliases, _catalog_ids = _item_aliases(item_key)
    found: set[int] = set()
    for item_id, blob in _iter_live_item_rows(world):
        if item_id and _names_match(blob, aliases):
            found.add(item_id)
    return found


def item_match_sets(world: Any, item_key: str) -> tuple[set[str], set[int]]:
    """Name aliases + catalog ids union live ids discovered by exact name."""
    aliases, ids = _item_aliases(item_key)
    ids = set(ids) | discover_live_item_ids(world, item_key)
    return aliases, ids


def _slot_box_key(raw: Mapping[str, Any]) -> tuple[int, str] | None:
    try:
        box = int(raw.get("box") or 0)
    except (TypeError, ValueError):
        box = 0
    key = str(raw.get("key") or "").strip().lower()
    if box in (1, 2, 3) and key in SKILL_KEYS:
        return box, key
    if "slot" in raw:
        try:
            slot = int(raw.get("slot"))
        except (TypeError, ValueError):
            slot = -1
        if 0 <= slot <= 23:
            return _slot_to_box_key(slot)
    if "index" in raw:
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            index = -1
        if 1 <= index <= 24:
            return _slot_to_box_key(index - 1)
    return None


def find_hp_restore_hotbar(
    world: Any,
    item_key: str,
    layout: Mapping[str, Any] | None = None,
) -> tuple[int, str] | None:
    """Box + F-key for a specific HP item on the 24-slot bar."""
    key = _resolved_item_key(item_key)
    aliases, ids = item_match_sets(world, key)
    if layout is None and world is not None:
        layout = getattr(world, "hotbar_layout", None)
    snap = getattr(world, "last_hotbar", None) if world is not None else None
    raw_slots = snap.get("slots") if isinstance(snap, Mapping) else None
    if isinstance(raw_slots, list):
        for raw in raw_slots:
            if not isinstance(raw, Mapping):
                continue
            item_id = _live_catalog_id(raw)
            if item_id not in ids and not _any_name_matches(
                raw, aliases, _HOTBAR_NAME_FIELDS
            ):
                continue
            found = _slot_box_key(raw)
            if found is not None:
                return found

    boxes = layout.get("boxes") if isinstance(layout, Mapping) else None
    if isinstance(boxes, Mapping):
        for box_key in ("1", "2", "3"):
            page = boxes.get(box_key)
            if not isinstance(page, Mapping):
                continue
            try:
                box = int(box_key)
            except (TypeError, ValueError):
                continue
            for fkey, cell in page.items():
                if not isinstance(cell, Mapping):
                    continue
                if not _any_name_matches(cell, aliases, _LAYOUT_NAME_FIELDS):
                    continue
                return box, str(fkey).strip().lower()

    if key == LEGACY_POTION_KEY and slot_is_enabled("hp_potion"):
        return slot_press("hp_potion")
    return None


def format_hotbar_binding(slot: tuple[int, str] | None) -> str:
    if slot is None:
        return ""
    box, key = slot
    return f"F{int(box)}-{str(key).upper()}"
