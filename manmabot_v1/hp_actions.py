"""Operator-side HP recovery action order (percent thresholds)."""
from __future__ import annotations

from typing import Any, Iterable

RECOVERY_SLOT_IDS = {
    "heal": "heal",
    "hp_potion": "hp_potion",
    "teleport": "teleport",
    "mother_tree": "mother_tree",
}

FIXED_HP_ACTION_IDS = ("heal", "mother_tree", "teleport", "safe_zone")
ITEM_ACTION_PREFIX = "item:"
LEGACY_POTION_ID = "hp_potion"
LEGACY_POTION_KEY = "빨간 물약"
RETREAT_ACTION_IDS = frozenset({"mother_tree", "teleport", "safe_zone"})
DEFAULT_INPLACE_PCT = 55
DEFAULT_RETREAT_PCT = 30
# Default HP order includes only this consumable; users add more from the bag.
_DEFAULT_HP_ITEMS = (LEGACY_POTION_KEY,)
_FALLBACK_HP_ITEMS = ("빨간 물약", "주홍 물약", "맑은 물약", "엔트의 열매")


def hp_item_keys() -> tuple[str, ...]:
    """Catalog restore keys (for hints / matching). Not auto-filled into HP order."""
    try:
        from app._03_world.game_catalog import list_hp_restore_items

        keys = tuple(row.key for row in list_hp_restore_items())
        if keys:
            return keys
    except Exception:
        pass
    return _FALLBACK_HP_ITEMS


def default_hp_item_keys() -> tuple[str, ...]:
    return _DEFAULT_HP_ITEMS


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
    items = tuple(item_action_id(key) for key in default_hp_item_keys())
    return (
        "heal",
        "mother_tree",
        *items,
        "teleport",
        "safe_zone",
    )


# Kept for older imports / tests that still read the 5-role tuple.
HP_ACTION_IDS = known_hp_action_ids()


def _normalize_item_key(raw_key: str) -> str:
    text = str(raw_key or "").strip()
    if not text:
        return ""
    if text == LEGACY_POTION_ID or text.startswith(ITEM_ACTION_PREFIX):
        return item_key_from_action(text)
    return text


def item_keys_from_actions(raw: Any) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return keys
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_id = canonical_action_id(str(item.get("id") or ""))
        if not is_item_action(action_id):
            continue
        key = item_key_from_action(action_id)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def merge_item_keys(*groups: Iterable[str] | None) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if group is None:
            continue
        for raw in group:
            key = _normalize_item_key(str(raw))
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys


def hp_restore_key_for_inventory_item(item: Any) -> str:
    """Catalog HP-restore key for a live bag row, or empty if it is not one."""
    if not isinstance(item, dict):
        return ""
    try:
        from app._03_world.game_catalog import hp_restore_item, list_hp_restore_items
    except Exception:
        return ""
    try:
        item_id = int(item.get("id") or 0)
    except (TypeError, ValueError):
        item_id = 0
    if item_id:
        try:
            catalog = list_hp_restore_items()
        except Exception:
            catalog = ()
        for row in catalog:
            if item_id in row.ids:
                return row.key
    for field in ("name", "name_tw", "name_cn", "name_en", "tw"):
        spec = hp_restore_item(str(item.get(field) or ""))
        if spec is not None:
            return spec.key
    return ""


def inventory_item_key_for_hp_action(item: Any) -> str:
    """Key used when adding any bag row to the HP order (catalog name preferred)."""
    if not isinstance(item, dict):
        return ""
    known = hp_restore_key_for_inventory_item(item)
    if known:
        return known
    placeholders = {"", "—", "-", "–", "?"}
    for field in ("name", "name_tw", "name_cn", "name_en", "tw"):
        text = str(item.get(field) or "").strip()
        if text and text not in placeholders:
            return text
    try:
        item_id = int(item.get("id") or 0)
    except (TypeError, ValueError):
        item_id = 0
    return f"#{item_id}" if item_id else ""


def inventory_hp_item_keys(items: Iterable[Any]) -> tuple[str, ...]:
    """Legacy helper: catalog restore keys present in ``items``."""
    keys: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = hp_restore_key_for_inventory_item(item)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return tuple(keys)


def default_hp_actions(
    *,
    potion_pct: int = DEFAULT_INPLACE_PCT,
    escape_pct: int = DEFAULT_RETREAT_PCT,
    use_heal: bool = True,
    use_potion: bool = True,
    extra_item_keys: Iterable[str] | None = None,
    fill_catalog: bool = False,
) -> list[dict[str, Any]]:
    """Heal → Mother Tree → red water (default) → teleport → talking scroll.

    Extra bag items are operator-added; catalog restore items are not pre-listed.
    """
    potion = _clamp_pct(potion_pct, DEFAULT_INPLACE_PCT)
    escape = _clamp_pct(escape_pct, DEFAULT_RETREAT_PCT)
    rows = [
        {"id": "heal", "enabled": bool(use_heal), "hp_below": potion},
        {"id": "mother_tree", "enabled": True, "hp_below": escape},
    ]
    keys = merge_item_keys(extra_item_keys)
    if fill_catalog:
        keys = merge_item_keys(keys, hp_item_keys())
    elif not keys:
        keys = list(default_hp_item_keys())
    for index, key in enumerate(keys):
        rows.append(
            {
                "id": item_action_id(key),
                "enabled": bool(use_potion),
                "hp_below": potion,
            }
        )
        if index == 0 and not use_potion:
            rows[-1]["enabled"] = False
    rows.extend(
        [
            {"id": "teleport", "enabled": True, "hp_below": escape},
            {"id": "safe_zone", "enabled": True, "hp_below": escape},
        ]
    )
    return rows


def normalize_hp_actions(
    raw: Any,
    *,
    potion_pct: int | None = None,
    escape_pct: int | None = None,
    use_heal: bool | None = None,
    use_potion: bool | None = None,
    extra_item_keys: Iterable[str] | None = None,
    fill_catalog: bool = False,
) -> list[dict[str, Any]]:
    """Merge a saved list onto the default 5 rows; keep user-added item rows."""
    merged_keys = merge_item_keys(item_keys_from_actions(raw), extra_item_keys)
    base = default_hp_actions(
        potion_pct=DEFAULT_INPLACE_PCT if potion_pct is None else potion_pct,
        escape_pct=DEFAULT_RETREAT_PCT if escape_pct is None else escape_pct,
        use_heal=True if use_heal is None else use_heal,
        use_potion=True if use_potion is None else use_potion,
        extra_item_keys=merged_keys,
        fill_catalog=fill_catalog,
    )
    by_id = {row["id"]: dict(row) for row in base}
    ordered: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = canonical_action_id(str(item.get("id") or "").strip())
            if not key or key in ordered:
                continue
            if key not in by_id:
                item_key = item_key_from_action(key)
                if not (is_item_action(key) and item_key):
                    continue
                by_id[key] = {
                    "id": key,
                    "enabled": bool(item.get("enabled", True)),
                    "hp_below": _clamp_pct(
                        item.get("hp_below"), DEFAULT_INPLACE_PCT
                    ),
                }
            row = by_id[key]
            if "enabled" in item:
                row["enabled"] = bool(item["enabled"])
            if "hp_below" in item:
                row["hp_below"] = _clamp_pct(item["hp_below"], row["hp_below"])
            ordered.append(key)
    if not ordered:
        ordered = [row["id"] for row in base]
    else:
        # Ensure fixed skills + default red water exist; do not re-add catalog.
        fill_ids = list(known_hp_action_ids())
        if fill_catalog:
            fill_ids = list(
                dict.fromkeys(
                    (
                        *FIXED_HP_ACTION_IDS[:2],
                        *(item_action_id(k) for k in hp_item_keys()),
                        *FIXED_HP_ACTION_IDS[2:],
                    )
                )
            )
        for key in fill_ids:
            if key not in ordered and key in by_id:
                ordered.append(key)
    return [by_id[key] for key in ordered if key in by_id]


def action_enabled(actions: Iterable[dict[str, Any]], action_id: str) -> bool:
    wanted = canonical_action_id(action_id)
    for row in actions:
        if canonical_action_id(str(row.get("id") or "")) == wanted:
            return bool(row.get("enabled"))
    return False


def action_hp_below(actions: Iterable[dict[str, Any]], action_id: str, fallback: int) -> int:
    wanted = canonical_action_id(action_id)
    for row in actions:
        if canonical_action_id(str(row.get("id") or "")) == wanted:
            return _clamp_pct(row.get("hp_below"), fallback)
    return _clamp_pct(fallback, fallback)


def sync_legacy_from_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep older Profile / recovery fields in sync with the ordered list."""
    inplace = [
        action_hp_below(actions, "heal", DEFAULT_INPLACE_PCT),
    ] if action_enabled(actions, "heal") else []
    for row in actions:
        key = str(row.get("id") or "")
        if is_item_action(key) and row.get("enabled"):
            inplace.append(action_hp_below(actions, key, DEFAULT_INPLACE_PCT))
    retreat = [
        action_hp_below(actions, key, DEFAULT_RETREAT_PCT)
        for key in RETREAT_ACTION_IDS
        if action_enabled(actions, key)
    ]
    potion_on = any(
        is_item_action(str(row.get("id") or "")) and row.get("enabled")
        for row in actions
    )
    return {
        "use_heal": action_enabled(actions, "heal"),
        "use_hp_potion": potion_on,
        "hp_potion_below": min(inplace) if inplace else DEFAULT_INPLACE_PCT,
        "escape_hp_below": min(retreat) if retreat else DEFAULT_RETREAT_PCT,
    }


def apply_recovery_to_spell_slots(
    slots: dict[str, dict[str, Any]] | None,
    actions: Any,
) -> dict[str, dict[str, Any]]:
    """Turn on Setup roles that Recovery enabled, when a box/key is assigned."""
    from copy import deepcopy

    from manmabot_v1.spell_defaults import default_spell_slots

    merged = default_spell_slots()
    if isinstance(slots, dict):
        for key, spec in slots.items():
            if key in merged and isinstance(spec, dict):
                merged[key] = {**merged[key], **deepcopy(spec)}
    wanted = {
        canonical_action_id(str(row.get("id") or ""))
        for row in normalize_hp_actions(actions)
        if row.get("enabled")
    }
    slot_wanted = set()
    for action_id in wanted:
        if action_id in RECOVERY_SLOT_IDS:
            slot_wanted.add(RECOVERY_SLOT_IDS[action_id])
        elif is_item_action(action_id):
            slot_wanted.add("hp_potion")
    for slot_id in slot_wanted:
        spec = merged.get(slot_id)
        if not isinstance(spec, dict):
            continue
        try:
            box = int(spec.get("box") or 0)
        except (TypeError, ValueError):
            continue
        if box in (1, 2, 3):
            spec["enabled"] = True
    return merged


def to_engine_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Percent thresholds → ratios for decision.hp.actions."""
    return [
        {
            "id": str(row["id"]),
            "enabled": bool(row.get("enabled")),
            "hp_below": _clamp_pct(row.get("hp_below"), DEFAULT_INPLACE_PCT) / 100.0,
        }
        for row in normalize_hp_actions(actions)
    ]


def _clamp_pct(value: Any, fallback: int) -> int:
    try:
        return max(5, min(95, int(value)))
    except (TypeError, ValueError):
        return max(5, min(95, int(fallback)))
