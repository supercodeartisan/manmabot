"""Royal combat: placeholder — same timed clicks as knight until developed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._05_action.combat_strategies.knight import KnightCombatStrategy

if TYPE_CHECKING:
    from app._01_capture.window_bounds import WindowBounds
    from app._03_world import WorldState
    from app._04_decision.types import ActionIntent
    from app._05_action.controller import ActionExecutor


class RoyalCombatStrategy(KnightCombatStrategy):
    """TODO: royal-specific combat; currently inherits knight timed clicks."""

    def attack(
        self,
        executor: "ActionExecutor",
        action: "ActionIntent",
        game_state: "WorldState",
        bounds: "WindowBounds",
        *,
        mid_act: bool,
    ) -> None:
        super().attack(
            executor, action, game_state, bounds, mid_act=mid_act
        )
