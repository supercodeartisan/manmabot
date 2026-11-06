"""Team-leader seat (팀장).

The live leader tick is ``PartyLeaderManager``. This seat does not emit an
intent yet.
"""
from __future__ import annotations

from typing import Any

from .base import AdoptedDecision, BrainRole, DecisionBrain


class LeaderBrain(DecisionBrain):
    role = BrainRole.LEADER

    def adopt(self, game_state: Any) -> AdoptedDecision:
        del game_state
        return AdoptedDecision(
            role=self.role,
            intent=None,
            reason="leader_brain_unwired",
            ready=False,
        )


__all__ = ["LeaderBrain"]
