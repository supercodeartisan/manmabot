"""Decision Manager: runs evaluators with Lineage_bot-style state machine logic."""
from __future__ import annotations

from app._03_world import GameState, MemoryState, ActionType
from app._04_decision.types import ActionIntent
from app._04_decision.legacy.statemachine import StateMachine
from app._04_decision.legacy.decision_memory import update_memory
from app._04_decision.legacy.antispam import AntiSpam


class DecisionManager:
    """Runs evaluators with Lineage_bot state machine logic and memory persistence."""

    def __init__(self) -> None:
        self._memory = MemoryState()
        self._state_machine = StateMachine()
        self._anti_spam = AntiSpam()

    def decide(self, game_state: GameState) -> ActionIntent:
        """Run Lineage_bot-style state machine and return best action."""
        current_action = self._memory.action_type

        # ======================
        # IDLE
        # ======================
        if current_action == ActionType.IDLE:
            action = self._state_machine.handle_idle(game_state)

        # ======================
        # COMBAT
        # ======================
        elif current_action == ActionType.COMBAT:
            enemy_id = self._memory.enemy.track_id if self._memory.enemy else None
            action = self._state_machine.handle_combat(game_state, enemy_id)

        # ======================
        # LOOTING
        # ======================
        elif current_action == ActionType.LOOTING:
            item_id = self._memory.item.track_id if self._memory.item else None
            action = self._state_machine.handle_looting(game_state, item_id)

        # ======================
        # SEARCHING
        # ======================
        elif current_action == ActionType.SEARCHING:
            action = self._state_machine.handle_searching(game_state)

        # ======================
        # TRAVELING
        # ======================
        elif current_action == ActionType.TRAVELING:
            action = self._state_machine.handle_traveling(game_state)

        # Fallback
        else:
            action = self._state_machine.handle_idle(game_state)

        # Update memory
        update_memory(action, game_state, self._memory)

        # Apply anti-spam logic
        action, _ = self._anti_spam.apply(action, self._memory.action_type)

        return action