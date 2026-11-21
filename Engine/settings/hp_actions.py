"""Operator-side HP recovery action order (percent thresholds)."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

RECOVERY_SLOT_IDS = {
    "heal": "heal",
    "hp_potion": "hp_potion",
    "teleport": "teleport",
    "mother_tree": "mother_tree",
}

FIXED_HP_ACTION_IDS = ("hp_potion", "heal", "retreat")
ITEM_ACTION_PREFIX = "item:"
LEGACY_POTION_ID = "hp_potion"
LEGACY_POTION_KEY = "빨간 물약"
RETREAT_ACTION_IDS = frozenset({"retreat"})
DEFAULT_HEAL_PCT = 70
DEFAULT_POTION_PCT = 50
DEFAULT_INPLACE_PCT = DEFAULT_HEAL_PCT
DEFAULT_RETREAT_PCT = 30
# Default HP order includes only this consumable; users add more from the bag.
_DEFAULT_HP_ITEMS = (LEGACY_POTION_KEY,)
_FALLBACK_HP_ITEMS = ("빨간 물약", "주홍 물약", "맑은 물약", "엔트의 열매")


def hp_item_keys() -> tuple[str, ...]:
    """Catalog restore keys (for hints / matching). Not auto-filled into HP order."""
    try:
        from app._03_world.catalog.game_catalog import list_hp_restore_items

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
    return FIXED_HP_ACTION_IDS


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
        from app._03_world.catalog.game_catalog import hp_restore_item, list_hp_restore_items
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


def _usable_hotbar_slot(box: Any, key: Any) -> tuple[int, str] | None:
    try:
        box_i = int(box or 0)
    except (TypeError, ValueError):
        return None
    fkey = str(key or "").strip().lower()
    if box_i not in (1, 2, 3) or not fkey:
        return None
    from settings.spell_defaults import SKILL_KEYS

    if fkey not in SKILL_KEYS:
        return None
    return box_i, fkey


def hotbar_binding_from_row(row: Mapping[str, Any] | None) -> tuple[int, str] | None:
    """Operator-assigned hotbar cell on an HP action row, if any."""
    if not isinstance(row, Mapping):
        return None
    return _usable_hotbar_slot(row.get("box"), row.get("key"))


def _hotbar_fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    bound = hotbar_binding_from_row(row)
    if bound is None:
        return {}
    out: dict[str, Any] = {"box": bound[0], "key": bound[1]}
    if isinstance(row, Mapping):
        item = str(row.get("item") or "").strip()
        if item:
            out["item"] = item
    return out


def default_hp_actions(
    *,
    heal_pct: int = DEFAULT_HEAL_PCT,
    potion_pct: int = DEFAULT_POTION_PCT,
    escape_pct: int = DEFAULT_RETREAT_PCT,
    use_heal: bool = True,
    use_potion: bool = True,
    extra_item_keys: Iterable[str] | None = None,
    fill_catalog: bool = False,
) -> list[dict[str, Any]]:
    """Three HP gates: potion, heal, retreat. Order is not a ladder."""
    del extra_item_keys, fill_catalog
    return [
        {
            "id": "hp_potion",
            "enabled": bool(use_potion),
            "hp_below": _clamp_pct(potion_pct, DEFAULT_POTION_PCT),
        },
        {
            "id": "heal",
            "enabled": bool(use_heal),
            "hp_below": _clamp_pct(heal_pct, DEFAULT_HEAL_PCT),
        },
        {
            "id": "retreat",
            "enabled": True,
            "hp_below": _clamp_pct(escape_pct, DEFAULT_RETREAT_PCT),
        },
    ]


def _row_pct(item: Mapping[str, Any] | None, fallback: int) -> int:
    if not isinstance(item, dict):
        return _clamp_pct(fallback, fallback)
    return _as_pct(item.get("hp_below"), fallback)


def _as_pct(value: Any, fallback: int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _clamp_pct(fallback, fallback)
    if 0 < number <= 1.0:
        number = round(number * 100.0)
    return _clamp_pct(number, fallback)


def _first_row(raw: Any, *wanted: str) -> dict[str, Any] | None:
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
    explicit = _first_row(raw, "retreat")
    if explicit is not None:
        return explicit
    tree = _first_row(raw, "mother_tree")
    if tree is not None and tree.get("enabled", True):
        return tree
    for action_id in ("safe_zone", "teleport"):
        row = _first_row(raw, action_id)
        if row is not None and row.get("enabled", True):
            return row
    return None


def normalize_hp_actions(
    raw: Any,
    *,
    potion_pct: int | None = None,
    heal_pct: int | None = None,
    escape_pct: int | None = None,
    use_heal: bool | None = None,
    use_potion: bool | None = None,
    extra_item_keys: Iterable[str] | None = None,
    fill_catalog: bool = False,
) -> list[dict[str, Any]]:
    """Collapse saved lists onto potion / heal / retreat. Ignore leftover order."""
    del extra_item_keys, fill_catalog
    potion_row = _first_row(raw, "hp_potion")
    heal_row = _first_row(raw, "heal")
    retreat_row = _migrate_retreat_row(raw)
    potion_on = True if use_potion is None else bool(use_potion)
    if potion_row is not None and "enabled" in potion_row and use_potion is None:
        potion_on = bool(potion_row["enabled"])
    heal_on = True if use_heal is None else bool(use_heal)
    if heal_row is not None and "enabled" in heal_row and use_heal is None:
        heal_on = bool(heal_row["enabled"])
    retreat_on = True
    if retreat_row is not None and str(retreat_row.get("id") or "") == "retreat":
        retreat_on = bool(retreat_row.get("enabled", True))
    return [
        {
            "id": "hp_potion",
            "enabled": potion_on,
            "hp_below": _row_pct(
                potion_row,
                DEFAULT_POTION_PCT if potion_pct is None else potion_pct,
            ),
            **_hotbar_fields(potion_row),
        },
        {
            "id": "heal",
            "enabled": heal_on,
            "hp_below": _row_pct(
                heal_row, DEFAULT_HEAL_PCT if heal_pct is None else heal_pct
            ),
            **_hotbar_fields(heal_row),
        },
        {
            "id": "retreat",
            "enabled": retreat_on,
            "hp_below": _row_pct(
                retreat_row,
                DEFAULT_RETREAT_PCT if escape_pct is None else escape_pct,
            ),
        },
    ]


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
    """Keep older Profile / recovery fields in sync with the three HP gates."""
    return {
        "use_heal": action_enabled(actions, "heal"),
        "use_hp_potion": action_enabled(actions, "hp_potion"),
        "hp_potion_below": action_hp_below(actions, "hp_potion", DEFAULT_POTION_PCT),
        "hp_heal_below": action_hp_below(actions, "heal", DEFAULT_HEAL_PCT),
        "escape_hp_below": action_hp_below(actions, "retreat", DEFAULT_RETREAT_PCT),
    }


def apply_recovery_to_spell_slots(
    slots: dict[str, dict[str, Any]] | None,
    actions: Any,
) -> dict[str, dict[str, Any]]:
    """Turn on Setup roles that Recovery enabled; bind operator hotbar cells."""
    from settings.spell_defaults import merge_spell_slots

    # box/key/enabled from ``slots``; cast/reuse_s always engine defaults.
    merged = merge_spell_slots(slots)
    normalized = normalize_hp_actions(actions)
    wanted = {
        canonical_action_id(str(row.get("id") or ""))
        for row in normalized
        if row.get("enabled")
    }
    slot_wanted = set()
    for action_id in wanted:
        if action_id in RECOVERY_SLOT_IDS:
            slot_wanted.add(RECOVERY_SLOT_IDS[action_id])
        elif is_item_action(action_id):
            slot_wanted.add("hp_potion")
    for row in normalized:
        action_id = str(row.get("id") or "")
        role = RECOVERY_SLOT_IDS.get(action_id)
        if role is None and is_item_action(action_id):
            role = "hp_potion"
        if role not in ("heal", "hp_potion"):
            continue
        bound = hotbar_binding_from_row(row)
        if bound is None:
            continue
        spec = merged.get(role)
        if not isinstance(spec, dict):
            continue
        spec["box"], spec["key"] = bound
        if row.get("enabled"):
            spec["enabled"] = True
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
    """Percent thresholds → ratios for decision.hp.actions (+ optional hotbar)."""
    out: list[dict[str, Any]] = []
    for row in normalize_hp_actions(actions):
        entry: dict[str, Any] = {
            "id": str(row["id"]),
            "enabled": bool(row.get("enabled")),
            "hp_below": _clamp_pct(row.get("hp_below"), DEFAULT_INPLACE_PCT) / 100.0,
        }
        entry.update(_hotbar_fields(row))
        out.append(entry)
    return out


def _clamp_pct(value: Any, fallback: int) -> int:
    try:
        return max(5, min(95, int(value)))
    except (TypeError, ValueError):
        return max(5, min(95, int(fallback)))
