"""Shortcut-box layout (F1/F2/F3 pages, skills on F5–F12).

Box 1 is selected with F1 when the bot starts. Every spell or potion
press taps Fi for that slot's box immediately before the slot key so
F5–F12 cannot fire on the wrong page. Users can assign each role to any
box and F5–F12 via ``configure_spell_box``.

Role id catalog (``SLOT_IDS``, ``SKILL_KEYS``, cast modes) is owned by
``settings.spell_defaults``; this module re-exports them for Action callers.
"""
from __future__ import annotations

from typing import Any, Optional

from settings.spell_defaults import (
    CAST_DOUBLE,
    CAST_MODES,
    CAST_PRESS,
    SKILL_KEYS,
    SLOT_IDS,
)

BOX_KEYS = {1: "f1", 2: "f2", 3: "f3"}

BOX_MAGIC = 1
BOX_2 = 2
BOX_3 = 3
START_BOX = 1

_BUFF_IDS = ("power_up", "armor_up", "haste", "light")
# HP potion / haste potion are items. Everything else on the bar is magic.
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
    "power_up": {"box": 1, "key": "f5", "reuse_s": 1200.0, "cast": CAST_DOUBLE, "enabled": True},
    "armor_up": {"box": 1, "key": "f6", "reuse_s": 1200.0, "cast": CAST_PRESS, "enabled": True},
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

SLOTS: dict[str, dict[str, Any]] = {}
HEAL_DOUBLE_PRESS = True

POWER_UP_BOX = 1
POWER_UP_KEY = "f5"
ARMOR_UP_BOX = 1
ARMOR_UP_KEY = "f6"
HASTE_BOX = 1
HASTE_KEY = "f12"
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


# Bot run only. None = tests and tools keep using SLOTS.
# Pending until the startup hotbar scan; then the scan's talking_scroll binding.
_BOOT_PENDING = object()
_BOOT_TALKING_SCROLL: dict[str, Any] | object | None = None


def begin_talking_scroll_boot() -> None:
    """Drop any saved talking-scroll binding until this run's startup scan."""
    global _BOOT_TALKING_SCROLL
    _BOOT_TALKING_SCROLL = _BOOT_PENDING


def talking_scroll_boot_active() -> bool:
    """True after ``begin_talking_scroll_boot`` until the process leaves that run."""
    return _BOOT_TALKING_SCROLL is not None


def reset_talking_scroll_boot() -> None:
    """Tests: leave talking scroll on the normal SLOTS table."""
    global _BOOT_TALKING_SCROLL
    _BOOT_TALKING_SCROLL = None


def _talking_scroll_from_scan(detected_slots: Any) -> dict[str, Any]:
    """Binding from this scan only. A missing row is off, not a saved slot."""
    raw = None
    if isinstance(detected_slots, dict):
        found = detected_slots.get("talking_scroll")
        if isinstance(found, dict):
            raw = found
    disabled = {
        "box": 0,
        "key": "f5",
        "reuse_s": 0.0,
        "cast": CAST_PRESS,
        "enabled": False,
    }
    spec = _normalize_slot(raw if raw is not None else disabled, disabled)
    try:
        box = int(spec.get("box", 0))
    except (TypeError, ValueError):
        box = 0
    key = str(spec.get("key") or "").strip().lower()
    if not spec.get("enabled") or box not in (1, 2, 3) or key not in SKILL_KEYS:
        spec["enabled"] = False
        spec["box"] = 0
    return spec


def latch_talking_scroll_from_scan(detected_slots: Any) -> dict[str, Any] | None:
    """Record the startup scan once. Later scans return that same binding.

    Returns None when this process is not inside a bot run
    (``begin_talking_scroll_boot`` was not called).
    """
    global _BOOT_TALKING_SCROLL
    if _BOOT_TALKING_SCROLL is None:
        return None
    if _BOOT_TALKING_SCROLL is _BOOT_PENDING:
        _BOOT_TALKING_SCROLL = _talking_scroll_from_scan(detected_slots)
    return dict(_BOOT_TALKING_SCROLL)  # type: ignore[arg-type]


def apply_boot_talking_scroll(slots: dict[str, Any], detected_slots: Any) -> None:
    """Overwrite ``talking_scroll`` with the startup-scan binding, if a run is active."""
    latched = latch_talking_scroll_from_scan(detected_slots)
    if latched is None:
        return
    slots["talking_scroll"] = {
        "box": int(latched["box"]),
        "key": str(latched["key"]),
        "enabled": bool(latched["enabled"]),
    }


def _talking_scroll_spec() -> dict[str, Any]:
    if isinstance(_BOOT_TALKING_SCROLL, dict):
        return _BOOT_TALKING_SCROLL
    return _slot("talking_scroll")


def slot_press(name: str) -> tuple[int, str]:
    spec = _talking_scroll_spec() if name == "talking_scroll" else _slot(name)
    return int(spec["box"]), str(spec["key"])


def slot_is_magic(name: str) -> bool:
    return str(name) in MAGIC_SLOT_IDS


def slot_is_enabled(name: str) -> bool:
    """False when the operator turned the role off or left it unassigned.

    During a bot run, talking scroll stays off until the startup hotbar scan
    and then uses only that scan. A profile binding saved earlier does not
    turn it on, and a later refresh does not replace it.
    """
    if name == "talking_scroll" and _BOOT_TALKING_SCROLL is _BOOT_PENDING:
        return False
    spec = _talking_scroll_spec() if name == "talking_scroll" else _slot(name)
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
    """Operator box/key/enabled + engine cast/reuse_s (ignore overlay cast/reuse)."""
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


def merge_slots(raw: Optional[dict[str, Any]] = None) -> dict[str, dict[str, Any]]:
    merged = default_slots()
    if not isinstance(raw, dict):
        if "light" in merged:
            merged["light"]["enabled"] = False
        return merged
    for name, spec in raw.items():
        if name not in merged:
            continue
        merged[name] = _normalize_slot(spec, merged[name])
    if "light" in merged:
        merged["light"]["enabled"] = False
    return merged


def _apply_aliases() -> None:
    global POWER_UP_BOX, POWER_UP_KEY
    global ARMOR_UP_BOX, ARMOR_UP_KEY
    global HASTE_BOX, HASTE_KEY
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
    HASTE_BOX, HASTE_KEY = slot_press("haste")
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
    """Apply operator box/key/enabled; cast/reuse_s stay on engine DEFAULT_SLOTS.

    ``heal_double_press`` is ignored (heal cast is engine ``CAST_DOUBLE``).
    """
    del heal_double_press
    global SLOTS
    SLOTS = merge_slots(slots)
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
    "HASTE_BOX",
    "HASTE_KEY",
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
    "begin_talking_scroll_boot",
    "latch_talking_scroll_from_scan",
    "apply_boot_talking_scroll",
    "reset_talking_scroll_boot",
    "talking_scroll_boot_active",
    "slot_is_enabled",
    "slot_reuse_s",
    "slot_cooldown_s",
    "slot_is_double",
    "merge_slots",
    "configure_spell_box",
]
