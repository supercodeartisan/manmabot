"""Perception buffer → ``_02_state`` conversion (world's only job)."""
from app._03_world.merge.apply_perception import (
    PerceptionApplyResult,
    apply_perception_buffer,
)
from app._03_world.merge.converter import handoff_to_perception, vision_to_perception
from app._03_world.merge.track import create_game_state

__all__ = [
    "PerceptionApplyResult",
    "apply_perception_buffer",
    "create_game_state",
    "handoff_to_perception",
    "vision_to_perception",
]
