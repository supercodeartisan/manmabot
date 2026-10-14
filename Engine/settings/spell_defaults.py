"""Default in-game shortcut slots and usage knobs (Version 1 profile)."""
from __future__ import annotations

from typing import Any, Optional

SLOT_IDS = (
    "power_up",
    "armor_up",
    "haste",
    "light",
    "heal",
    "hp_potion",
    "mp_potion",
    "teleport",
    "mage_attack",
    "talking_scroll",
    "mother_tree",
    "hp_to_mp",
    "depoison",
)

SKILL_KEYS = ("f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12")
SKILL_GRID = (
    ("f5", "f6", "f7", "f8"),
    ("f9", "f10", "f11", "f12"),
)
CAST_PRESS = "press"
CAST_DOUBLE = "double"
CAST_MODES = (CAST_PRESS, CAST_DOUBLE)
UNASSIGNED_BOX = 0
# Operator / profile persistence: placement only. cast + reuse_s are engine rules.
PROFILE_SLOT_KEYS = ("box", "key", "enabled")

DEFAULT_SPELL_SLOTS: dict[str, dict[str, Any]] = {
    "power_up": {"box": 1, "key": "f5", "reuse_s": 1200.0, "cast": CAST_DOUBLE, "enabled": True},
    "armor_up": {"box": 1, "key": "f6", "reuse_s": 1200.0, "cast": CAST_PRESS, "enabled": True},
    # Item (초록/강화 초록 등). Timer fallback ~5 min green potion; memory remain preferred.
    "haste": {"box": 1, "key": "f12", "reuse_s": 290.0, "cast": CAST_PRESS, "enabled": True},
    "light": {"box": 1, "key": "f7", "reuse_s": 720.0, "cast": CAST_PRESS, "enabled": False},
    "heal": {"box": 1, "key": "f8", "reuse_s": 0.0, "cast": CAST_DOUBLE, "enabled": True},
    "hp_potion": {"box": 1, "key": "f9", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": True},
    "mp_potion": {"box": 1, "key": "f12", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": False},
    "teleport": {"box": 1, "key": "f10", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": True},
    "mage_attack": {"box": 1, "key": "f11", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": True},
    "talking_scroll": {"box": 2, "key": "f5", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": True},
    "mother_tree": {"box": 2, "key": "f6", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": True},
    "hp_to_mp": {"box": 2, "key": "f7", "reuse_s": 0.0, "cast": CAST_PRESS, "enabled": True},
    "depoison": {"box": 0, "key": "f5", "reuse_s": 1.0, "cast": CAST_PRESS, "enabled": False},
}

DEFAULT_HEAL_UNTIL_HP = 0.50
DEFAULT_SPELL_RESERVE = 0.20
# Kept for migrating older profiles that stored one shared buff timer.
DEFAULT_BUFF_COOLDOWN_MIN = 20.0
DEFAULT_HEAL_DOUBLE = True


def default_spell_slots() -> dict[str, dict[str, Any]]:
    """Full engine catalog (box/key/enabled + cast/reuse_s)."""
    return {name: dict(spec) for name, spec in DEFAULT_SPELL_SLOTS.items()}


def spell_slot_bindings(
    slots: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, Any]]:
    """Profile/schedule shape: box/key/enabled only (no cast/reuse_s)."""
    src = slots if isinstance(slots, dict) else DEFAULT_SPELL_SLOTS
    out: dict[str, dict[str, Any]] = {}
    for name in SLOT_IDS:
        fallback = DEFAULT_SPELL_SLOTS[name]
        spec = src.get(name) if isinstance(src, dict) else None
        if not isinstance(spec, dict):
            spec = fallback
        try:
            box = int(spec.get("box", fallback["box"]))
        except (TypeError, ValueError):
            box = int(fallback["box"])
        if box not in (0, 1, 2, 3):
            box = int(fallback["box"])
        key = str(spec.get("key", fallback["key"])).strip().lower()
        if key not in SKILL_KEYS:
            key = str(fallback["key"])
        if "enabled" in spec:
            enabled = bool(spec["enabled"])
        else:
            enabled = bool(fallback.get("enabled", True))
        if name == "light":
            enabled = False
        out[name] = {"box": box, "key": key, "enabled": enabled}
    return out


def default_spell_bindings() -> dict[str, dict[str, Any]]:
    return spell_slot_bindings(DEFAULT_SPELL_SLOTS)


def _normalize_slot(spec: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    """Runtime slot: operator box/key/enabled + engine cast/reuse_s."""
    if not isinstance(spec, dict):
        return dict(fallback)
    try:
        box = int(spec.get("box", fallback["box"]))
    except (TypeError, ValueError):
        box = int(fallback["box"])
    key = str(spec.get("key", fallback["key"])).strip().lower()
    if box not in (0, 1, 2, 3):
        box = int(fallback["box"])
    if key not in SKILL_KEYS:
        key = str(fallback["key"])
    if "enabled" in spec:
        enabled = bool(spec["enabled"])
    else:
        enabled = bool(fallback.get("enabled", True))
    # cast / reuse_s are game rules — never take them from profile/UI overlays.
    cast = str(fallback.get("cast") or CAST_PRESS).strip().lower()
    if cast not in CAST_MODES:
        cast = CAST_PRESS
    try:
        reuse_s = max(0.0, float(fallback.get("reuse_s", 0.0) or 0.0))
    except (TypeError, ValueError):
        reuse_s = 0.0
    return {
        "box": box,
        "key": key,
        "reuse_s": reuse_s,
        "cast": cast,
        "enabled": enabled,
    }


def _reuse_from_mapping(spec: dict[str, Any], fallback: dict[str, Any]) -> float:
    default = fallback.get("reuse_s", fallback.get("cooldown_s", 0.0))
    try:
        base = max(0.0, float(default or 0.0))
    except (TypeError, ValueError):
        base = 0.0
    for key, scale in (("reuse_s", 1.0), ("reuse_min", 60.0), ("cooldown_s", 1.0), ("cooldown_min", 60.0)):
        if key not in spec:
            continue
        try:
            return max(0.0, float(spec[key]) * scale)
        except (TypeError, ValueError):
            return base
    return base


def slot_reuse_s(spec: dict[str, Any] | None) -> float:
    if not isinstance(spec, dict):
        return 0.0
    return _reuse_from_mapping(spec, {"reuse_s": 0.0})


def slot_enabled(spec: dict[str, Any] | None) -> bool:
    if not isinstance(spec, dict):
        return True
    return bool(spec.get("enabled", True))


def merge_spell_slots(
    raw: Optional[dict[str, Any]] = None,
    *,
    buff_cooldown_min: Optional[float] = None,
    heal_double_press: Optional[bool] = None,
) -> dict[str, dict[str, Any]]:
    """Engine catalog + operator box/key/enabled.

    ``buff_cooldown_min`` / ``heal_double_press`` are ignored: reuse/cast are
    engine constants (kept as kwargs for older Profile.from_dict callers).
    """
    del buff_cooldown_min, heal_double_press
    merged = default_spell_slots()
    if isinstance(raw, dict):
        for name, spec in raw.items():
            if name not in merged:
                continue
            merged[name] = _normalize_slot(spec, merged[name])
    # Light is not used — keep placement keys but never enable for casting.
    if "light" in merged:
        merged["light"]["enabled"] = False
    return merged


def occupant_at(
    slots: dict[str, dict[str, Any]],
    box: int,
    key: str,
) -> Optional[str]:
    """Spell id sitting on this box+key, or None if the cell is empty."""
    want = str(key).strip().lower()
    for name in SLOT_IDS:
        spec = slots.get(name) or DEFAULT_SPELL_SLOTS[name]
        try:
            spec_box = int(spec.get("box", 0) or 0)
        except (TypeError, ValueError):
            continue
        if spec_box != int(box):
            continue
        if str(spec.get("key", "")).strip().lower() == want:
            return name
    return None


def assign_spell_to_cell(
    slots: dict[str, dict[str, Any]],
    box: int,
    key: str,
    sid: Optional[str],
) -> dict[str, dict[str, Any]]:
    """Place ``sid`` on (box, key), swapping with whoever is there. None clears."""
    out = {name: dict(spec) for name, spec in slots.items()}
    for name in SLOT_IDS:
        out.setdefault(name, dict(DEFAULT_SPELL_SLOTS[name]))
    key = str(key).strip().lower()
    current = occupant_at(out, box, key)
    if sid == current:
        return out
    if not sid:
        if current:
            out[current]["box"] = UNASSIGNED_BOX
        return out
    if sid not in SLOT_IDS:
        return out
    prev_box = int(out[sid].get("box", 0) or 0)
    prev_key = str(out[sid].get("key", "f5")).strip().lower()
    if current:
        if prev_box in (1, 2, 3):
            out[current]["box"] = prev_box
            out[current]["key"] = prev_key
        else:
            out[current]["box"] = UNASSIGNED_BOX
    out[sid]["box"] = int(box)
    out[sid]["key"] = key
    return out


def slot_conflict(slots: dict[str, dict[str, Any]]) -> Optional[tuple[str, str]]:
    """Return two role ids that share the same box+key, if any."""
    seen: dict[tuple[int, str], str] = {}
    for name in SLOT_IDS:
        spec = slots.get(name) or DEFAULT_SPELL_SLOTS[name]
        try:
            box = int(spec.get("box", 0) or 0)
        except (TypeError, ValueError):
            continue
        if box not in (1, 2, 3):
            continue
        mark = (box, str(spec.get("key", "")).strip().lower())
        if mark in seen:
            return seen[mark], name
        seen[mark] = name
    return None
