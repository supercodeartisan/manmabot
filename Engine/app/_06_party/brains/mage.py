"""Mage brain (마법사).

Seat for a spell caster in the party. Later this adopts buff, heal, and
spell-range steps. It does not emit an intent yet, and it does not change
the member assist path.
"""
from __future__ import annotations

from typing import Any

from .base import AdoptedDecision, BrainRole, DecisionBrain


class MageBrain(DecisionBrain):
    role = BrainRole.MAGE

    def adopt(self, game_state: Any) -> AdoptedDecision:
        del game_state
        return AdoptedDecision(
            role=self.role,
            intent=None,
            reason="mage_brain_unwired",
            ready=False,
        )


__all__ = ["MageBrain"]
