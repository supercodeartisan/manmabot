"""Mage brain (마법사).

Adopts the decision ``PartyMemberManager`` already made. Class-mage heal and
the assist skip stay in that manager. The live session still calls it directly.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import PartyMemberConfig
from ..manager import PartyMemberManager
from .base import AdoptedDecision, BrainRole, DecisionBrain


class MageBrain(DecisionBrain):
    role = BrainRole.MAGE

    def __init__(
        self,
        manager: Optional[PartyMemberManager] = None,
        config: PartyMemberConfig | dict | None = None,
    ) -> None:
        self.manager = manager if manager is not None else PartyMemberManager(config)

    def adopt(self, game_state: Any) -> AdoptedDecision:
        intent = self.manager.decide(game_state)
        reason = str(getattr(intent, "reason", "") or "") if intent is not None else "idle"
        return AdoptedDecision(
            role=self.role,
            intent=intent,
            reason=reason,
            ready=True,
        )


__all__ = ["MageBrain"]
