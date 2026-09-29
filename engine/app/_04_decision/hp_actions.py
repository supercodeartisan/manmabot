"""Ordered HP recovery actions (ratios). Heal → tree → HP items → TP → safe."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from app._05_action.spell_box import SKILL_KEYS, slot_is_enabled, slot_press

FIXED_HP_ACTION_IDS = ("heal", "mother_tree", "teleport", "safe_zone")
ITEM_ACTION_PREFIX = "item:"
LEGACY_POTION_ID = "hp_potion"
LEGACY_POTION_KEY = "빨간 물약"
RETREAT_ACTION_IDS = frozenset({"mother_tree", "teleport", "safe_zone"})
_DEFAULT_HP_ITEMS = (LEGACY_POTION_KEY,)
_FALLBACK_HP_ITEMS = ("빨간 물약", "주홍 물약", "맑은 물약", "엔트의 열매")


def hp_item_keys() -> tuple[str, ...]:
    """Catalog restore keys (matching / aliases). Not the default HP order list."""
    try:
        from app._03_world.game_catalog import list_hp_restore_items

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
    items = tuple(item_action_id(key) for key in _DEFAULT_HP_ITEMS)
    return ("heal", "mother_tree", *items, "teleport", "safe_zone")


HP_ACTION_IDS = known_hp_action_ids()


def default_hp_actions() -> list[dict[str, Any]]:
    """Heal → tree → red water → teleport → safe (user adds more items)."""
    rows: list[dict[str, Any]] = [
        {"id": "heal", "enabled": True, "hp_below": 0.55},
        {"id": "mother_tree", "enabled": True, "hp_below": 0.30},
    ]
    for key in _DEFAULT_HP_ITEMS:
        rows.append({"id": item_action_id(key), "enabled": True, "hp_below": 0.55})
    rows.extend(
        [
            {"id": "teleport", "enabled": True, "hp_below": 0.30},
            {"id": "safe_zone", "enabled": True, "hp_below": 0.30},
        ]
    )
    return rows


def normalize_hp_actions(raw: Any) -> list[dict[str, Any]]:
    base = {row["id"]: dict(row) for row in default_hp_actions()}
    ordered: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = canonical_action_id(str(item.get("id") or "").strip())
            if key in ordered:
                continue
            if key not in base:
                item_key = item_key_from_action(key)
                if not (is_item_action(key) and item_key):
                    continue
                try:
                    threshold = float(item.get("hp_below", 0.55))
                except (TypeError, ValueError):
                    threshold = 0.55
                base[key] = {
                    "id": key,
                    "enabled": bool(item.get("enabled", True)),
                    "hp_below": max(0.05, min(0.95, threshold)),
                }
            row = base[key]
            if "enabled" in item:
                row["enabled"] = bool(item["enabled"])
            if "hp_below" in item:
                try:
                    row["hp_below"] = max(0.05, min(0.95, float(item["hp_below"])))
                except (TypeError, ValueError):
                    pass
            ordered.append(key)
    if not ordered:
        ordered = [row["id"] for row in default_hp_actions()]
    else:
        for key in known_hp_action_ids():
            if key not in ordered and key in base:
                ordered.append(key)
    return [base[key] for key in ordered if key in base]


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


def _item_aliases(item_key: str) -> tuple[set[str], set[int]]:
    try:
        from app._03_world.game_catalog import hp_restore_item

        spec = hp_restore_item(item_key)
    except Exception:
        spec = None
    if spec is None:
        return {_fold(item_key)}, set()
    return {_fold(alias) for alias in spec.aliases()}, set(spec.ids)


def _slot_to_box_key(slot: int) -> tuple[int, str]:
    index = max(0, int(slot))
    return index // 8 + 1, SKILL_KEYS[index % 8]


def _bare_name(text: str) -> str:
    raw = str(text or "").strip()
    try:
        from manmabot_v1.hotbar.inspect import fold_hotbar_name

        raw = fold_hotbar_name(raw)
    except Exception:
        pass
    return _fold(raw)


def _names_match(blob: str, aliases: set[str]) -> bool:
    folded = _bare_name(blob)
    if not folded:
        return False
    if folded in aliases:
        return True
    return any(alias and alias in folded for alias in aliases)


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
    key = item_key_from_action(item_key) or str(item_key or "").strip()
    if not key:
        key = LEGACY_POTION_KEY
    aliases, ids = _item_aliases(key)
    if layout is None and world is not None:
        layout = getattr(world, "hotbar_layout", None)
    snap = getattr(world, "last_hotbar", None) if world is not None else None
    raw_slots = snap.get("slots") if isinstance(snap, Mapping) else None
    if isinstance(raw_slots, list):
        for raw in raw_slots:
            if not isinstance(raw, Mapping):
                continue
            try:
                item_id = int(raw.get("id") or raw.get("item_id") or raw.get("uid") or 0)
            except (TypeError, ValueError):
                item_id = 0
            blob = " ".join(
                str(raw.get(field) or "")
                for field in ("name", "label", "name_tw", "name_cn", "kr_name")
            )
            if item_id not in ids and not _names_match(blob, aliases):
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
                blob = " ".join(
                    str(cell.get(field) or "")
                    for field in ("kr_name", "zh_name", "label", "name")
                )
                if not _names_match(blob, aliases):
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
