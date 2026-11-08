"""Mage combat: find the attack (knife) cursor like elf, then cast there."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world.space.world_coords import in_mage_spell_range
from app._05_action import humanize as hz
from app._05_action.cursor_verify import (
    find_attack_aim_point,
    mage_cast_at_point,
    object_attack_screen_points,
)
from app._05_action import spell_box as sb

if TYPE_CHECKING:
    from app._05_action.window_bounds import WindowBounds
    from app._03_world import WorldState
    from app._04_decision.types import ActionIntent
    from app._05_action.controller import ActionExecutor


class MageCombatStrategy:
    """Cast loop: knife-aim first (same ring as elf), then spell key + click."""

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

        named = bool(getattr(action, "hotbar_box", None) and getattr(action, "hotbar_key", None))
        if not named and not sb.slot_is_enabled("mage_attack"):
            return
        if not can_cast_spell(game_state, role="mage_attack"):
            return

        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            return
        from app._04_decision.combat_query import memory_target_gone

        if memory_target_gone(game_state, target):
            return
        if not in_mage_spell_range(target.position.x, target.position.y):
            return

        # 1) Same body ring as elf — require attack cursor (arrow/fist/sword).
        #    Do not press the spell key until the knife is on the monster.
        points = object_attack_screen_points(executor, target, bounds)
        aim = find_attack_aim_point(
            executor,
            points,
            target_id=action.target_id,
            sticky=bool(mid_act),
        )
        if aim is None:
            # A bad spell circle was cancelled. Do not count it as a miss.
            if getattr(executor, "spell_aim_suppressed", False):
                return
            executor.last_cursor_reject_target_id = action.target_id
            if not executor.last_cursor_reject_reason:
                executor.last_cursor_reject_reason = "no attack cursor on target"
            return

        # 2) Spell key, unless the circle is already on this pixel, then click.
        hold = (
            hz.uniform(hz.MAGE_KEY_HOLD, executor._rng)
            if executor.humanize
            else hz.MAGE_KEY_HOLD[0]
        )
        already_armed = bool(getattr(executor, "mage_spell_ready", False))
        if not already_armed:
            if named:
                executor._press_box_skill(
                    int(action.hotbar_box),
                    str(action.hotbar_key).strip().lower(),
                    duration=hold,
                )
                pressed = time.time()
                executor._last_magic_at = pressed
                executor._last_mage_cast = pressed
                from app._04_decision.solo_mage import note_solo_mage_attack_pressed

                note_solo_mage_attack_pressed(getattr(executor, "_blackboard", None))
            else:
                executor._press_assigned_skill("mage_attack", duration=hold)
        if not mage_cast_at_point(
            executor,
            aim[0],
            aim[1],
            target_id=action.target_id,
        ):
            label = str(
                getattr(getattr(executor, "last_cursor_match", None), "label", "")
                or ""
            )
            if label in ("spell", "spell_out_range", "spell_disable"):
                from app._05_action.cursor_verify import cancel_spell_aim

                cancel_spell_aim(executor, reason="cast miss")
                return
            executor.last_cursor_reject_target_id = action.target_id
            try:
                executor.keyboard.press("esc")
            except Exception:
                pass
            return
        executor._mage_cast_gap = executor._sample_mage_gap()
        executor.last_cast_target_id = action.target_id
