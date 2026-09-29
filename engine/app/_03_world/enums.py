"""Enumeration types for the World module."""
from __future__ import annotations

from enum import Enum


class CharacterType(Enum):
    ROYAL = "royal"
    KNIGHT = "knight"
    ELF = "elf"
    MAGE = "mage"


class ActionType(Enum):
    IDLE = "idle"
    SEARCHING = "searching"
    COMBAT = "combat"
    RETREATING = "retreating"
    LOOTING = "looting"
    TRAVELING = "traveling"
    MOVE = "move"
    ATTACK = "attack"
    PICKUP = "pickup"
    USE_HP_POTION = "use_hp_potion"
    USE_MP_POTION = "use_mp_potion"
    USE_DEPOISON = "use_depoison"
    HEAL = "heal"
    BUFF = "buff"
    ESCAPE = "escape"
    TELEPORT = "teleport"
    RETURN_TO_MOTHER_TREE = "return_to_mother_tree"
    HP_TO_MP = "hp_to_mp"
    USE_TALKING_SCROLL = "use_talking_scroll"
    SHOP_BUY_ARROWS = "shop_buy_arrows"
    SHOP_STOP = "shop_stop"
    DISMISS_LEVEL_UP = "dismiss_level_up"
    RESPAWN = "respawn"


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