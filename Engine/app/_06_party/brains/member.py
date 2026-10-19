"""Single party-member brain (팀원봇의 기초).

This is the member seat. It adopts the decision already produced by
``PartyMemberManager`` (follow, assist, settle, loot). Creating this brain
does not switch the session; the manager remains the live caller until a
later wiring step.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import PartyMemberConfig
from ..manager import PartyMemberManager
from .base import AdoptedDecision, BrainRole, DecisionBrain


class MemberBrain(DecisionBrain):
    role = BrainRole.MEMBER

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


__all__ = ["MemberBrain"]
