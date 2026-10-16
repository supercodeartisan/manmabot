"""Hunt assist: antidote toggle + hotbar cell assignment.

Shares the haste hotbar table. One cell belongs to one role.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from settings.haste_potion import _usable_slot


def same_hotbar_cell(box_a: Any, key_a: Any, box_b: Any, key_b: Any) -> bool:
    left = _usable_slot(box_a, key_a)
    right = _usable_slot(box_b, key_b)
    return left is not None and left == right


def assigned_antidote_slot(
    slots: Mapping[str, Any] | None,
    *,
    item_key: str = "",
    box: Any = None,
    key: Any = None,
) -> Optional[tuple[int, str]]:
    """Operator-bound antidote cell when a hotbar slot was assigned."""
    if not str(item_key or "").strip() and _usable_slot(box, key) is None:
        return None
    explicit = _usable_slot(box, key)
    if explicit is not None:
        return explicit
    depoison = (slots or {}).get("depoison") if isinstance(slots, Mapping) else None
    if not isinstance(depoison, Mapping):
        return None
    if depoison.get("enabled") is False:
        return None
    return _usable_slot(depoison.get("box"), depoison.get("key"))


def resolve_antidote_press_slot(
    *,
    item_key: str = "",
    assigned_slot: tuple[int, str] | None = None,
    live_snap: Mapping[str, Any] | None = None,
) -> Optional[tuple[int, str]]:
    """Assigned hotbar cell first; CSV depoison role when nothing is assigned."""
    key = str(item_key or "").strip()
    bound = (
        _usable_slot(assigned_slot[0], assigned_slot[1])
        if assigned_slot is not None
        else None
    )
    if key:
        return bound
    raw_slots = live_snap.get("slots") if isinstance(live_snap, Mapping) else None
    if isinstance(raw_slots, list) and raw_slots:
        from hotbar.inspect import find_role_on_hotbar

        return find_role_on_hotbar(live_snap, "depoison")
    return bound


def apply_antidote_potion_to_spell_slots(
    slots: dict[str, dict[str, Any]] | None,
    *,
    use: bool,
    item_key: str = "",
    box: Any = None,
    key: Any = None,
    layout: Mapping[str, Any] | None = None,
    world: Any = None,
) -> dict[str, dict[str, Any]]:
    """Enable depoison from the hunt toggle; bind the operator's hotbar cell.

    A cell already used by an enabled haste slot is left unbound.
    """
    from settings.spell_defaults import merge_spell_slots

    merged = merge_spell_slots(slots)
    depoison = merged.setdefault("depoison", {})
    if not isinstance(depoison, dict):
        depoison = {}
        merged["depoison"] = depoison
    depoison["enabled"] = bool(use)
    name = str(item_key or "").strip()
    bound = _usable_slot(box, key)
    haste = merged.get("haste")
    if isinstance(haste, dict) and haste.get("enabled") is not False:
        haste_cell = _usable_slot(haste.get("box"), haste.get("key"))
        if bound is not None and haste_cell == bound:
            bound = None
            name = ""
    if use and bound is not None:
        depoison["box"], depoison["key"] = bound
        return merged
    if use and name:
        try:
            from app._04_decision.hp_actions import find_hp_restore_hotbar
        except Exception:
            find_hp_restore_hotbar = None  # type: ignore[assignment]
        found = None
        if find_hp_restore_hotbar is not None:
            found = find_hp_restore_hotbar(world, name, layout=layout)
        if found is not None:
            depoison["box"] = int(found[0])
            depoison["key"] = str(found[1]).strip().lower()
        else:
            depoison["box"] = 0
    elif use and bound is None and _usable_slot(box, key) is not None:
        depoison["box"] = 0
        depoison["key"] = ""
    return merged
