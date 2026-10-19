"""Shared contract for party decision brains (결심채택).

A brain adopts one decision per tick. It does not move, click, or talk to
the socket itself. Session still calls ``PartyMemberManager.decide`` until a
brain is explicitly selected.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional


class BrainRole(str, Enum):
    """Which party seat this brain occupies."""

    LEADER = "leader"
    MEMBER = "member"
    MAGE = "mage"
    SHOPKEEPER = "shopkeeper"


@dataclass(frozen=True)
class AdoptedDecision:
    """One tick's adopted decision.

    ``intent`` is an ``ActionIntent`` (or None). ``ready`` is False while the
    brain is only a seat and must not drive the executor.
    """

    role: BrainRole
    intent: Any = None
    reason: str = ""
    ready: bool = False


class DecisionBrain(ABC):
    """Party-bot brain: look at the world, adopt one decision."""

    role: ClassVar[BrainRole]

    @abstractmethod
    def adopt(self, game_state: Any) -> AdoptedDecision:
        """Return the decision for this tick. No I/O beyond reading state."""


def parse_role(value: object) -> Optional[BrainRole]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    aliases = {
        "leader": BrainRole.LEADER,
        "team_leader": BrainRole.LEADER,
        "member": BrainRole.MEMBER,
        "single": BrainRole.MEMBER,
        "party_member": BrainRole.MEMBER,
        "mage": BrainRole.MAGE,
        "wizard": BrainRole.MAGE,
        "shop": BrainRole.SHOPKEEPER,
        "shopkeeper": BrainRole.SHOPKEEPER,
        "merchant": BrainRole.SHOPKEEPER,
    }
    if text in aliases:
        return aliases[text]
    try:
        return BrainRole(text)
    except ValueError:
        return None


__all__ = [
    "AdoptedDecision",
    "BrainRole",
    "DecisionBrain",
    "parse_role",
]
