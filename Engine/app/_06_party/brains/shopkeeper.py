"""Shop-keeper brain (상점담당자).

Adopts the decision ``PartyMemberManager`` already made, including the supply
tick. The live session still calls the manager directly.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import PartyMemberConfig
from ..manager import PartyMemberManager
from .base import AdoptedDecision, BrainRole, DecisionBrain


class ShopkeeperBrain(DecisionBrain):
    role = BrainRole.SHOPKEEPER

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


__all__ = ["ShopkeeperBrain"]
