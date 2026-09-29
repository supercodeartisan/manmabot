"""Shortcut-box layout (F1/F2/F3 pages, skills on F5–F12).

Box 1 is selected with F1 when the bot starts. Every spell or potion
press taps Fi for that slot's box immediately before the slot key so
F5–F12 cannot fire on the wrong page. Users can assign each role to any
box and F5–F12 via ``configure_spell_box``.
"""
from __future__ import annotations

from typing import Any, Optional

BOX_KEYS = {1: "f1", 2: "f2", 3: "f3"}
SKILL_KEYS = ("f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12")
CAST_PRESS = "press"
CAST_DOUBLE = "double"
CAST_MODES = (CAST_PRESS, CAST_DOUBLE)

BOX_MAGIC = 1
BOX_2 = 2
BOX_3 = 3
START_BOX = 1

SLOT_IDS = (
    "power_up",
    "armor_up",
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

_BUFF_IDS = ("power_up", "armor_up", "light")
# HP potion is an item. Everything else on the bar is magic.
MAGIC_SLOT_IDS = frozenset(
    (
        "power_up",
        "armor_up",
        "light",
        "heal",
        "teleport",
        "mage_attack",
        "mother_tree",
        "hp_to_mp",
    )
)
# Game rule: next magic only after this many seconds.
MAGIC_COOLDOWN_S = 0.5

DEFAULT_SLOTS: dict[str, dict[str, Any]] = {
    "power_up": {"box": 1, "key": "f5", "reuse_s": 1200.0, "cast": CAST_PRESS, "enabled": True},
    "armor_up": {"box": 1, "key": "f6", "reuse_s": 1200.0, "cast": CAST_PRESS, "enabled": True},
    "light": {"box": 1, "key": "f7", "reuse_s": 720.0, "cast": CAST_PRESS, "enabled": True},
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

SLOTS: dict[str, dict[str, Any]] = {}
HEAL_DOUBLE_PRESS = True

POWER_UP_BOX = 1
POWER_UP_KEY = "f5"
ARMOR_UP_BOX = 1
ARMOR_UP_KEY = "f6"
LIGHT_BOX = 1
LIGHT_KEY = "f7"
HEAL_BOX = 1
HEAL_KEY = "f8"
HP_POTION_BOX = 1
HP_POTION_KEY = "f9"
MP_POTION_BOX = 1
MP_POTION_KEY = "f12"
TELEPORT_BOX = 1
TELEPORT_KEY = "f10"
MAGE_ATTACK_BOX = 1
MAGE_ATTACK_KEY = "f11"
TALKING_SCROLL_BOX = 2
TALKING_SCROLL_KEY = "f5"
MOTHER_TREE_BOX = 2
MOTHER_TREE_KEY = "f6"
HP_TO_MP_BOX = 2
HP_TO_MP_KEY = "f7"


def default_slots() -> dict[str, dict[str, Any]]:
    return {name: dict(spec) for name, spec in DEFAULT_SLOTS.items()}


def _slot(name: str) -> dict[str, Any]:
    return SLOTS.get(name) or DEFAULT_SLOTS[name]


def slot_press(name: str) -> tuple[int, str]:
    spec = _slot(name)
    return int(spec["box"]), str(spec["key"])


def slot_is_magic(name: str) -> bool:
    return str(name) in MAGIC_SLOT_IDS


def slot_is_enabled(name: str) -> bool:
    """False when the operator turned the role off or left it unassigned."""
    spec = _slot(name)
    if not bool(spec.get("enabled", True)):
        return False
    try:
        box = int(spec.get("box", 1))
    except (TypeError, ValueError):
        return False
    return box in (1, 2, 3)


def slot_reuse_s(name: str) -> float:
    """Seconds between scheduled recasts of this role (0 = only when needed)."""
    spec = _slot(name)
    raw = spec.get("reuse_s", spec.get("cooldown_s", 0.0))
    try:
        return max(0.0, float(raw or 0.0))
    except (TypeError, ValueError):
        return 0.0


def slot_cooldown_s(name: str) -> float:
    """Backward-compatible alias of ``slot_reuse_s``."""
    return slot_reuse_s(name)


def slot_is_double(name: str) -> bool:
    return str(_slot(name).get("cast") or CAST_PRESS) == CAST_DOUBLE


def _normalize_slot(spec: Any, fallback: dict[str, Any]) -> dict[str, Any]:
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
    reuse_s = _reuse_from_mapping(spec, fallback)
    cast = str(spec.get("cast", fallback["cast"])).strip().lower()
    if cast not in CAST_MODES:
        cast = str(fallback["cast"])
    if "enabled" in spec:
        enabled = bool(spec["enabled"])
    else:
        enabled = bool(fallback.get("enabled", True))
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
    if "reuse_s" in spec:
        try:
            return max(0.0, float(spec["reuse_s"]))
        except (TypeError, ValueError):
            return base
    if "reuse_min" in spec:
        try:
            return max(0.0, float(spec["reuse_min"]) * 60.0)
        except (TypeError, ValueError):
            return base
    if "cooldown_s" in spec:
        try:
            return max(0.0, float(spec["cooldown_s"]))
        except (TypeError, ValueError):
            return base
    if "cooldown_min" in spec:
        try:
            return max(0.0, float(spec["cooldown_min"]) * 60.0)
        except (TypeError, ValueError):
            return base
    return base


def merge_slots(raw: Optional[dict[str, Any]] = None) -> dict[str, dict[str, Any]]:
    merged = default_slots()
    if not isinstance(raw, dict):
        return merged
    for name, spec in raw.items():
        if name not in merged:
            continue
        merged[name] = _normalize_slot(spec, merged[name])
    return merged


def _apply_aliases() -> None:
    global POWER_UP_BOX, POWER_UP_KEY
    global ARMOR_UP_BOX, ARMOR_UP_KEY
    global LIGHT_BOX, LIGHT_KEY
    global HEAL_BOX, HEAL_KEY
    global HP_POTION_BOX, HP_POTION_KEY
    global MP_POTION_BOX, MP_POTION_KEY
    global TELEPORT_BOX, TELEPORT_KEY
    global MAGE_ATTACK_BOX, MAGE_ATTACK_KEY
    global TALKING_SCROLL_BOX, TALKING_SCROLL_KEY
    global MOTHER_TREE_BOX, MOTHER_TREE_KEY
    global HP_TO_MP_BOX, HP_TO_MP_KEY
    global HEAL_DOUBLE_PRESS
    POWER_UP_BOX, POWER_UP_KEY = slot_press("power_up")
    ARMOR_UP_BOX, ARMOR_UP_KEY = slot_press("armor_up")
    LIGHT_BOX, LIGHT_KEY = slot_press("light")
    HEAL_BOX, HEAL_KEY = slot_press("heal")
    HP_POTION_BOX, HP_POTION_KEY = slot_press("hp_potion")
    MP_POTION_BOX, MP_POTION_KEY = slot_press("mp_potion")
    TELEPORT_BOX, TELEPORT_KEY = slot_press("teleport")
    MAGE_ATTACK_BOX, MAGE_ATTACK_KEY = slot_press("mage_attack")
    TALKING_SCROLL_BOX, TALKING_SCROLL_KEY = slot_press("talking_scroll")
    MOTHER_TREE_BOX, MOTHER_TREE_KEY = slot_press("mother_tree")
    HP_TO_MP_BOX, HP_TO_MP_KEY = slot_press("hp_to_mp")
    HEAL_DOUBLE_PRESS = slot_is_double("heal")


def configure_spell_box(
    slots: Optional[dict[str, Any]] = None,
    *,
    heal_double_press: Optional[bool] = None,
) -> None:
    """Apply operator slot assignments (box, key, reuse, cast, enabled)."""
    global SLOTS
    SLOTS = merge_slots(slots)
    if heal_double_press is not None:
        SLOTS["heal"]["cast"] = CAST_DOUBLE if heal_double_press else CAST_PRESS
    _apply_aliases()


configure_spell_box()

__all__ = [
    "BOX_KEYS",
    "SKILL_KEYS",
    "CAST_PRESS",
    "CAST_DOUBLE",
    "CAST_MODES",
    "BOX_MAGIC",
    "BOX_2",
    "BOX_3",
    "START_BOX",
    "SLOT_IDS",
    "MAGIC_SLOT_IDS",
    "MAGIC_COOLDOWN_S",
    "DEFAULT_SLOTS",
    "SLOTS",
    "HEAL_DOUBLE_PRESS",
    "POWER_UP_BOX",
    "POWER_UP_KEY",
    "ARMOR_UP_BOX",
    "ARMOR_UP_KEY",
    "LIGHT_BOX",
    "LIGHT_KEY",
    "HEAL_BOX",
    "HEAL_KEY",
    "HP_POTION_BOX",
    "HP_POTION_KEY",
    "MP_POTION_BOX",
    "MP_POTION_KEY",
    "TELEPORT_BOX",
    "TELEPORT_KEY",
    "MAGE_ATTACK_BOX",
    "MAGE_ATTACK_KEY",
    "TALKING_SCROLL_BOX",
    "TALKING_SCROLL_KEY",
    "MOTHER_TREE_BOX",
    "MOTHER_TREE_KEY",
    "HP_TO_MP_BOX",
    "HP_TO_MP_KEY",
    "default_slots",
    "slot_press",
    "slot_is_magic",
    "slot_is_enabled",
    "slot_reuse_s",
    "slot_cooldown_s",
    "slot_is_double",
    "merge_slots",
    "configure_spell_box",
]
