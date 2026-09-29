"""Knight combat: click target on a 90–140 ms wall-clock cadence (no mouse hold)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._05_action.cursor_verify import (
    attack_click_search,
    object_attack_screen_points,
)

if TYPE_CHECKING:
    from app._01_capture.window_bounds import WindowBounds
    from app._03_world import WorldState
    from app._04_decision.types import ActionIntent
    from app._05_action.controller import ActionExecutor


class KnightCombatStrategy:
    """Timed left-clicks once the attack cursor is found near the target."""

    def attack(
        self,
        executor: "ActionExecutor",
        action: "ActionIntent",
        game_state: "WorldState",
        bounds: "WindowBounds",
        *,
        mid_act: bool,
    ) -> None:
        # New engage: Esc before cadence gate so walk-cancel is never skipped.
        if not mid_act:
            executor._halt_before_attack(mid_act=False)

        now = time.time()
        if now - executor._last_elf_click < executor._elf_click_gap:
            return

        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            return
        from app._04_decision.combat_query import memory_target_gone

        if memory_target_gone(game_state, target):
            return

        points = object_attack_screen_points(executor, target, bounds)
        if not attack_click_search(executor, points):
            match = getattr(executor, "last_cursor_match", None)
            if match is not None and getattr(match, "label", "") == "arrow_lack":
                executor.last_arrow_lack = True
                return
            executor.last_cursor_reject_target_id = action.target_id
            return  # verify failed — skip click only
        executor._last_elf_click = now
        executor._elf_click_gap = executor._sample_elf_gap()
        executor.last_attack_target_id = action.target_id
        executor._holding = False
