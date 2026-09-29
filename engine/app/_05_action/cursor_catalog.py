"""Cursor fine labels and coarse categories for action verification."""
from __future__ import annotations

from enum import Enum


class CursorCategory(str, Enum):
    ATTACK = "attack"  # targeting an enemy
    SPELL = "spell"  # casting / cast blocked
    ITEM = "item"  # drop / give while holding
    GATE = "gate"
    DIALOG = "dialog"
    DOOR = "door"
    NORMAL = "normal"
    PARALYZED = "paralyzed"  # poison / stun — input ignored by the game
    UNKNOWN = "unknown"


# Fine label → category (filenames without .png).
CURSOR_LABEL_CATEGORY: dict[str, CursorCategory] = {
    "arrow": CursorCategory.ATTACK,
    "arrow_lack": CursorCategory.ATTACK,
    "fist": CursorCategory.ATTACK,
    "sword": CursorCategory.ATTACK,
    "spell": CursorCategory.SPELL,
    "spell_disable": CursorCategory.SPELL,
    "spell_out_range": CursorCategory.SPELL,
    "drop": CursorCategory.ITEM,
    "give": CursorCategory.ITEM,
    "gate": CursorCategory.GATE,
    "dialog": CursorCategory.DIALOG,
    "door": CursorCategory.DOOR,
    "normal": CursorCategory.NORMAL,
    "paralyzed": CursorCategory.PARALYZED,
}

KNOWN_CURSOR_LABELS: tuple[str, ...] = tuple(CURSOR_LABEL_CATEGORY.keys())

# Mage may click only when the cast is actually allowed.
MAGE_CAST_OK_LABELS: frozenset[str] = frozenset({"spell"})

# Melee / bow / fist attack hover. ``arrow_lack`` is still ATTACK category
# but must not click — the bot goes to the shop instead.
ATTACK_OK_LABELS: frozenset[str] = frozenset({"arrow", "fist", "sword"})
ATTACK_OK_CATEGORIES: frozenset[CursorCategory] = frozenset(
    {CursorCategory.ATTACK}
)

# NPC shop / conversation hover.
DIALOG_OK_CATEGORIES: frozenset[CursorCategory] = frozenset(
    {CursorCategory.DIALOG}
)

# Ground loot: default pointer (not NPC / door / attack).
LOOT_OK_LABELS: frozenset[str] = frozenset({"normal"})
LOOT_OK_CATEGORIES: frozenset[CursorCategory] = frozenset(
    {CursorCategory.NORMAL}
)


def category_for_label(label: str | None) -> CursorCategory:
    if not label:
        return CursorCategory.UNKNOWN
    return CURSOR_LABEL_CATEGORY.get(label, CursorCategory.UNKNOWN)


__all__ = [
    "CursorCategory",
    "CURSOR_LABEL_CATEGORY",
    "KNOWN_CURSOR_LABELS",
    "MAGE_CAST_OK_LABELS",
    "ATTACK_OK_LABELS",
    "ATTACK_OK_CATEGORIES",
    "DIALOG_OK_CATEGORIES",
    "LOOT_OK_LABELS",
    "LOOT_OK_CATEGORIES",
    "category_for_label",
]
