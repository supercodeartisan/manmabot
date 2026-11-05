"""Shop-keeper brain (상점담당자).

Seat for the party member who runs town shops (buy, sell, store). Later this
adopts shop runs when the leader asks. It does not emit an intent yet, and
it does not change solo ``shop_run``.
"""
from __future__ import annotations

from typing import Any

from .base import AdoptedDecision, BrainRole, DecisionBrain


class ShopkeeperBrain(DecisionBrain):
    role = BrainRole.SHOPKEEPER

    def adopt(self, game_state: Any) -> AdoptedDecision:
        del game_state
        return AdoptedDecision(
            role=self.role,
            intent=None,
            reason="shopkeeper_brain_unwired",
            ready=False,
        )


__all__ = ["ShopkeeperBrain"]
