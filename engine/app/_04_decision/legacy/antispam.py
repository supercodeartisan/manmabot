"""Anti-spam / stuck detection logic."""
from __future__ import annotations

import random
from typing import Optional

from app._03_world import ActionType, Position
from app._04_decision.types import ActionIntent


class AntiSpam:
    """Prevents rapid action switching and detects stuck states."""

    def __init__(self) -> None:
        self._act_counter = 0
        self._stuck_thresholds = {
            ActionType.SEARCHING: 40,
            ActionType.COMBAT: 20,
            ActionType.LOOTING: 20,
            ActionType.TRAVELING: 20,
        }

    def apply(self, action: ActionIntent, last_action_type: ActionType) -> tuple[ActionIntent, int]:
        """Apply anti-spam logic, return updated action and new counter."""
        if action.action == last_action_type:
            self._act_counter += 1
            threshold = self._stuck_thresholds.get(action.action, 0)
            if self._act_counter >= threshold:
                # Stuck - force re-evaluation by clearing mid_act
                action.mid_act = False
                if action.action in (ActionType.SEARCHING, ActionType.TRAVELING):
                    if action.destination:
                        action.destination = Position(
                            x=action.destination.x + random.uniform(-0.1, 0.1),
                            y=action.destination.y + random.uniform(-0.1, 0.1),
                        )
        else:
            self._act_counter = 0
        return action, self._act_counter