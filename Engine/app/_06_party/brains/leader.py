"""Team-leader brain (팀장).

Seat for the PC that hosts the party. Farming stays on the solo decision
loop; this brain will later adopt only the decisions the party must share
(map change, shop run, return). It does not replace solo farm and does not
emit an intent yet.
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
