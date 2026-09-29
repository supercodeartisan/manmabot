"""Memory management for decision making."""
from __future__ import annotations

from app._03_world import GameState, MemoryState, Position, ActionType
from app._04_decision.types import ActionIntent


def update_memory(action: ActionIntent, game_state: GameState, memory: MemoryState) -> None:
    """Update persistent memory state (Lineage_bot style)."""
    memory.action_type = action.action

    target_obj = game_state.get_object(action.target_id) if action.target_id else None

    if action.action == ActionType.COMBAT:
        memory.enemy = target_obj
    elif action.action == ActionType.LOOTING:
        memory.item = target_obj

    memory.position = action.destination or (
        game_state.player.position if game_state.player else Position(x=0.0, y=0.0)
    )

    if not action.mid_act and action.action == ActionType.SEARCHING:
        memory.last_direction = action.destination or Position(x=0.0, y=0.0)