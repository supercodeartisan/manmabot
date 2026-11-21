"""Hunt assist: haste potion toggle + hotbar cell assignment."""
from __future__ import annotations

from typing import Any, Mapping, Optional


def _usable_slot(box: Any, key: Any) -> Optional[tuple[int, str]]:
    try:
        box_i = int(box or 0)
    except (TypeError, ValueError):
        return None
    fkey = str(key or "").strip().lower()
    if box_i not in (1, 2, 3) or not fkey:
        return None
    return box_i, fkey


def hotbar_picker_rows(layout: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """24 F-key cells from a hotbar layout dict (``boxes.1.f5`` …)."""
    from settings.spell_defaults import SKILL_KEYS

    boxes = layout.get("boxes") if isinstance(layout, Mapping) else None
    if not isinstance(boxes, Mapping):
        boxes = {}
    rows: list[dict[str, Any]] = []
    for box in (1, 2, 3):
        page = boxes.get(str(box), boxes.get(box))
        if not isinstance(page, Mapping):
            page = {}
        for key in SKILL_KEYS:
            cell = page.get(key)
            if not isinstance(cell, Mapping):
                cell = {}
            name = str(
                cell.get("kr_name") or cell.get("label") or cell.get("name") or ""
            ).strip()
            rows.append(
                {
                    "box": box,
                    "key": key,
                    "slot": f"F{box}-{key.upper()}",
                    "name": name,
                    "count": cell.get("count"),
                }
            )
    return rows


def assigned_haste_slot(
    slots: Mapping[str, Any] | None,
    *,
    item_key: str = "",
    box: Any = None,
    key: Any = None,
) -> Optional[tuple[int, str]]:
    """Operator-bound haste cell when a hotbar slot was assigned."""
    if not str(item_key or "").strip() and _usable_slot(box, key) is None:
        return None
    explicit = _usable_slot(box, key)
    if explicit is not None:
        return explicit
    haste = (slots or {}).get("haste") if isinstance(slots, Mapping) else None
    if not isinstance(haste, Mapping):
        return None
    if haste.get("enabled") is False:
        return None
    return _usable_slot(haste.get("box"), haste.get("key"))


def resolve_haste_press_slot(
    *,
    item_key: str = "",
    assigned_slot: tuple[int, str] | None = None,
    live_snap: Mapping[str, Any] | None = None,
) -> Optional[tuple[int, str]]:
    """Assigned hotbar cell first; CSV haste role when nothing is assigned.

    Unread live bar (no slots yet) falls back to ``assigned_slot`` only when
    the operator did not pick a cell (checkbox-only / still scanning).
    """
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

        return find_role_on_hotbar(live_snap, "haste")
    return bound


def apply_haste_potion_to_spell_slots(
    slots: dict[str, dict[str, Any]] | None,
    *,
    use: bool,
    item_key: str = "",
    box: Any = None,
    key: Any = None,
    layout: Mapping[str, Any] | None = None,
    world: Any = None,
) -> dict[str, dict[str, Any]]:
    """Enable haste from the hunt toggle; bind the operator's hotbar cell."""
    from settings.spell_defaults import merge_spell_slots

    merged = merge_spell_slots(slots)
    haste = merged.setdefault("haste", {})
    if not isinstance(haste, dict):
        haste = {}
        merged["haste"] = haste
    haste["enabled"] = bool(use)
    name = str(item_key or "").strip()
    bound = _usable_slot(box, key)
    if use and bound is not None:
        haste["box"], haste["key"] = bound
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
            haste["box"] = int(found[0])
            haste["key"] = str(found[1]).strip().lower()
        else:
            haste["box"] = 0
    return merged
