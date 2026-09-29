"""Mage combat: spell key then click target (spell-range gated)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world.world_coords import in_mage_spell_range
from app._05_action import humanize as hz
from app._05_action.cursor_verify import (
    mage_cast_click_search,
    object_attack_screen_points,
)
from app._05_action import spell_box as sb

if TYPE_CHECKING:
    from app._01_capture.window_bounds import WindowBounds
    from app._03_world import WorldState
    from app._04_decision.types import ActionIntent
    from app._05_action.controller import ActionExecutor


class MageCombatStrategy:
    """Cast loop on every attack tick, throttled by ``MAGE_CAST_INTERVAL``."""

    def attack(
        self,
        executor: "ActionExecutor",
        action: "ActionIntent",
        game_state: "WorldState",
        bounds: "WindowBounds",
        *,
        mid_act: bool,
    ) -> None:
        # New engage: Esc before cast cadence so walk-cancel is never skipped.
        if not mid_act:
            executor._halt_before_attack(mid_act=False)

        now = time.time()
        gap = max(executor._mage_cast_gap, sb.MAGIC_COOLDOWN_S)
        last_magic = float(getattr(executor, "_last_magic_at", 0.0) or 0.0)
        last = max(executor._last_mage_cast, last_magic)
        if now - last < gap:
            return

        from app._04_decision.spells import can_cast_spell

        if not sb.slot_is_enabled("mage_attack"):
            return
        if not can_cast_spell(game_state):
            return

        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            return
        from app._04_decision.combat_query import memory_target_gone

        if memory_target_gone(game_state, target):
            return
        if not in_mage_spell_range(target.position.x, target.position.y):
            return

        points = object_attack_screen_points(executor, target, bounds)
        hold = (
            hz.uniform(hz.MAGE_KEY_HOLD, executor._rng)
            if executor.humanize
            else hz.MAGE_KEY_HOLD[0]
        )
        executor._press_assigned_skill("mage_attack", duration=hold)
        if not mage_cast_click_search(executor, points):
            executor.last_cursor_reject_target_id = action.target_id
            return  # verify failed — skip click only
        executor._mage_cast_gap = executor._sample_mage_gap()
        executor.last_cast_target_id = action.target_id
