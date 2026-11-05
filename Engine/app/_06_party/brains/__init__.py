"""Party decision brains — one seat, one adopted decision per tick.

Live session still calls ``PartyMemberManager.decide``. These types are the
seats (팀장 / 팀원 / 마법사 / 상점담당자) to wire later.
"""
from __future__ import annotations

from typing import Any

from .base import AdoptedDecision, BrainRole, DecisionBrain, parse_role
from .leader import LeaderBrain
from .mage import MageBrain
from .member import MemberBrain
from .shopkeeper import ShopkeeperBrain

_FACTORIES = {
    BrainRole.LEADER: LeaderBrain,
    BrainRole.MEMBER: MemberBrain,
    BrainRole.MAGE: MageBrain,
    BrainRole.SHOPKEEPER: ShopkeeperBrain,
}


def make_brain(role: BrainRole | str, **kwargs: Any) -> DecisionBrain:
    """Build the brain for ``role``. Unknown roles raise ``ValueError``."""
    parsed = role if isinstance(role, BrainRole) else parse_role(role)
    if parsed is None or parsed not in _FACTORIES:
        raise ValueError(f"unknown party brain role: {role!r}")
    return _FACTORIES[parsed](**kwargs)


__all__ = [
    "AdoptedDecision",
    "BrainRole",
    "DecisionBrain",
    "LeaderBrain",
    "MageBrain",
    "MemberBrain",
    "ShopkeeperBrain",
    "make_brain",
    "parse_role",
]
