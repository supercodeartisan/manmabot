"""Enumeration types for game state."""
from __future__ import annotations

from enum import Enum


class CharacterType(Enum):
    ROYAL = "royal"
    KNIGHT = "knight"
    ELF = "elf"
    MAGE = "mage"


class ActionType(Enum):
    """Per-tick intent for ``ActionExecutor`` (not sticky ``PlayerMode``).

    Live decide emits these. Removed aliases (use the live name instead):
    ``COMBAT``→``ATTACK``, ``LOOTING``→``PICKUP``, ``RETREATING``→``TRAVELING``,
    ``ESCAPE``→``TELEPORT``, ``MOVE`` (unused). Shop wire is ``shop_run``;
    legacy string ``shop_buy_arrows`` still resolves via ``_missing_``.
    """

    IDLE = "idle"
    SEARCHING = "searching"  # farm/search hop click
    TRAVELING = "traveling"  # same-map nav hop (incl. walk while retreating)
    ATTACK = "attack"
    PICKUP = "pickup"
    USE_HP_POTION = "use_hp_potion"
    USE_MP_POTION = "use_mp_potion"
    USE_DEPOISON = "use_depoison"
    HEAL = "heal"
    BUFF = "buff"
    TELEPORT = "teleport"
    RETURN_TO_MOTHER_TREE = "return_to_mother_tree"
    HP_TO_MP = "hp_to_mp"
    USE_TALKING_SCROLL = "use_talking_scroll"
    # Map-gate cursor probe + click (world-nav map_transition).
    GATE = "gate"
    # Generic shop open/buy/sell run.
    SHOP_RUN = "shop_run"
    SHOP_STOP = "shop_stop"
    DISMISS_LEVEL_UP = "dismiss_level_up"
    RESPAWN = "respawn"

    @classmethod
    def _missing_(cls, value):
        if value == "shop_buy_arrows":
            return cls.SHOP_RUN
        return None


class EntityType(Enum):
    PLAYER = "player"
    MONSTER = "monster"
    NPC = "npc"
    ITEM = "item"


class MoveDirection(Enum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    LEFT_UP = "left_up"
    RIGHT_UP = "right_up"
    LEFT_DOWN = "left_down"
    RIGHT_DOWN = "right_down"
