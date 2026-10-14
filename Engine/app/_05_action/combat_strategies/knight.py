"""Knight combat: one left-click per attack tick when the cursor matches."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._05_action.cursor_verify import (
    attack_click_search,
    object_attack_screen_points,
)

if TYPE_CHECKING:
    from app._05_action.window_bounds import WindowBounds
    from app._03_world import WorldState
    from app._04_decision.types import ActionIntent
    from app._05_action.controller import ActionExecutor


class KnightCombatStrategy:
    """One left-click per attack tick once the attack cursor is found."""

    def attack(
        self,
        executor: "ActionExecutor",
        action: "ActionIntent",
        game_state: "WorldState",
        bounds: "WindowBounds",
        *,
        mid_act: bool,
    ) -> None:
        # New engage: Esc before the click so walk-cancel is never skipped.
        if not mid_act:
            executor._halt_before_attack(mid_act=False)

        now = time.time()

        from app._04_decision.clickgap import note_mouse, note_skip

        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            note_skip(f"attack id={action.target_id} why=no-object")
            return
        from app._04_decision.combat_query import memory_target_gone

        if memory_target_gone(game_state, target):
            note_skip(f"attack id={action.target_id} why=memory-gone")
            return

        points = object_attack_screen_points(executor, target, bounds)
        if not attack_click_search(
            executor,
            points,
            target_id=action.target_id,
            sticky=bool(mid_act),
        ):
            match = getattr(executor, "last_cursor_match", None)
            if match is not None and getattr(match, "label", "") == "arrow_lack":
                executor.last_arrow_lack = True
                note_skip(f"attack id={action.target_id} why=arrow-lack")
                return
            executor.last_cursor_reject_target_id = action.target_id
            reason = getattr(executor, "last_cursor_reject_reason", None) or "cursor"
            note_skip(f"attack id={action.target_id} why={reason}")
            return  # verify failed — skip click only
        match = getattr(executor, "last_cursor_match", None)
        label = getattr(match, "label", None) or "-"
        try:
            score = f"{float(getattr(match, 'score', 0.0)):.3f}"
        except (TypeError, ValueError):
            score = "-"
        note_mouse(f"attack id={action.target_id} cursor={label} score={score}")
        executor._last_elf_click = now
        executor._elf_click_gap = executor._sample_elf_gap()
        executor.last_attack_target_id = action.target_id
        executor._holding = False
