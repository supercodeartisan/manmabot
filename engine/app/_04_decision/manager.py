"""Decision Manager: runs the sticky PlayerMode policy each tick."""
from __future__ import annotations

import time

from app.bot_log import get_logger
from app._03_world import ActionType, GameState
from app._04_decision.attack_feedback import (
    # evaluate_attack_probes,  # re-enable in decide() to restore blacklist probes
    note_attack_delivered,
    note_cursor_verify_fail,
    note_cursor_verify_ok,
    note_mage_cast_attempt,
)
from app._04_decision.blackboard import Blackboard
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.mode_ticks import tick_mode
from app._04_decision.behaviors.navigation import MovementLeg
from app._04_decision.player_mode import PlayerMode
from app._04_decision.types import ActionIntent

_log = get_logger("decision")
_log_action = get_logger("action")


class DecisionManager:
    """Owns the blackboard and produces one action intent per tick.

    Sticky ``PlayerMode`` (traveling / farming / retreating) selects the
    policy. Mode may transition once mid-tick (e.g. travel arrive → farm).
    """

    def __init__(self, debug: bool = True) -> None:
        self.blackboard = Blackboard()
        from app._04_decision.spells import restore_buff_timers

        restore_buff_timers(self.blackboard)
        self.debug = debug
        self._last_goal: str | None = None
        self._last_target: int | None = None
        self._last_mode: PlayerMode | None = None
        self._last_action: str | None = None
        self._repeat_log_count = 0
        self._repeat_log_every = 50

    def decide(self, game_state: GameState) -> ActionIntent:
        """Tick the active mode and return the chosen action intent."""
        from app._04_decision.farm_time import sample_farm_presence

        self.blackboard.tick_count += 1
        self.blackboard.scratch["live_hotbar"] = getattr(
            game_state, "last_hotbar", None
        )
        sample_farm_presence(self.blackboard)

        from app._04_decision.species_rules import sync_sleeping_golem_hazards

        sync_sleeping_golem_hazards(game_state, self.blackboard)

        # Attack blacklist probes disconnected from the live loop.
        # evaluate_attack_probes(game_state, self.blackboard)

        self.blackboard.intent = None
        self.blackboard.current_goal = None
        legs_before = len(self.blackboard.leg_history)

        status = Status.FAILURE
        # Allow one mode hand-off in the same tick (arrive → farm, etc.).
        for _ in range(3):
            status = tick_mode(game_state, self.blackboard)
            if self.blackboard.intent is not None:
                break

        intent = self.blackboard.intent or ActionIntent(
            action=ActionType.IDLE,
            priority=0.0,
            reason="no behavior produced an intent",
        )
        self._log_decision(status, intent)
        self._log_new_legs(legs_before)
        return intent

    def _log_decision(self, status: Status, intent: ActionIntent) -> None:
        if not self.debug:
            return
        goal = self.blackboard.current_goal or "?"
        mode = self.blackboard.player_mode.value
        action = intent.action.value
        target = intent.target_id if intent.target_id is not None else "-"
        origin = self.blackboard.world_origin
        sticky = self.blackboard.current_target_id
        shop = bool(self.blackboard.scratch.get("shop_trip"))
        scrolled = bool(self.blackboard.scratch.get("shop_scrolled"))
        line = (
            f"mode={mode} goal={goal} action={action} target={target} "
            f"sticky={sticky if sticky is not None else '-'} "
            f"origin=({int(origin.x)},{int(origin.y)}) "
            f"shop={int(shop)} scrolled={int(scrolled)} "
            f"reason={intent.reason!r} status={status.value}"
        )
        switched = (
            goal != self._last_goal
            or intent.target_id != self._last_target
            or self.blackboard.player_mode is not self._last_mode
            or action != self._last_action
        )
        if switched:
            self._repeat_log_count = 0
            _log.info(line)
        else:
            self._repeat_log_count += 1
            if self._repeat_log_count >= self._repeat_log_every:
                self._repeat_log_count = 0
                _log.info("%s (repeat x%s)", line, self._repeat_log_every)
        self._last_goal = goal
        self._last_target = intent.target_id
        self._last_mode = self.blackboard.player_mode
        self._last_action = action

    def _log_new_legs(self, legs_before: int) -> None:
        """Log any destination rolls made during this tick."""
        for leg in list(self.blackboard.leg_history)[legs_before:]:
            self._log_leg(leg)

    def _log_leg(self, leg: MovementLeg) -> None:
        if not self.debug:
            return
        _log.debug(
            "leg=%s bearing=%.0f° dist=%.2f click=(%.2f,%.2f) pos=(%.2f,%.2f)",
            leg.reason,
            leg.bearing_deg,
            leg.leg_distance,
            leg.click.x,
            leg.click.y,
            leg.virtual_position.x,
            leg.virtual_position.y,
        )

    def note_attack_delivered(self, game_state: GameState, target_id: int) -> None:
        """Start the no-move clock after a melee click actually lands."""
        note_attack_delivered(game_state, self.blackboard, target_id)

    def note_mage_cast(
        self,
        target_id: int,
        mp_before: int | None,
        game_state: GameState | None = None,
    ) -> None:
        """Record a spell cast attempt for the mage MP-blacklist rule."""
        note_mage_cast_attempt(
            self.blackboard,
            target_id=target_id,
            mp_before=mp_before,
            state=game_state,
        )

    def note_cursor_verify_ok(self, track_id: int) -> None:
        """Reset cursor-verify probation after a successful gated click."""
        note_cursor_verify_ok(self.blackboard, track_id)

    def note_cursor_verify_fail(
        self,
        track_id: int,
        *,
        reason: str = "cursor reject",
        is_item: bool = False,
    ) -> bool:
        """Count a verify fail; soft-give-up after consecutive fails on this id."""
        return note_cursor_verify_fail(
            self.blackboard,
            track_id,
            reason=reason,
            is_item=is_item,
        )

    def apply_cursor_verify_feedback(self, executor: object) -> None:
        """Update verify probation from this tick's action-layer result."""
        from app._03_world.world_coords import relative_to_absolute

        if getattr(executor, "last_shop_buy_ok", False):
            bid = str(getattr(executor, "last_shop_behavior_id", "") or "").strip()
            from app._04_decision.shop_trip import advance_sell_trip, clear_shop_trip
            from app._04_decision.shops import (
                POTION_SUPPRESS_S,
                is_arrow_behavior,
                is_depoison_behavior,
                is_hp_potion_behavior,
                is_sell_behavior,
            )

            if is_arrow_behavior(bid) or not bid:
                self.blackboard.needs_arrows = False
            if is_hp_potion_behavior(bid):
                self.blackboard.needs_potion = False
                self.blackboard.potion_suppress_until = time.time() + float(
                    POTION_SUPPRESS_S
                )
            if is_depoison_behavior(bid):
                self.blackboard.needs_depoison = False
                self.blackboard.depoison_suppress_until = time.time() + float(
                    POTION_SUPPRESS_S
                )
            if is_sell_behavior(bid):
                advance_sell_trip(self.blackboard)
                from app._04_decision.talking_scroll import (
                    SCRATCH_SHOP_TRIP,
                    mark_post_shop_return,
                )

                # Sell queue finished → clear_shop_trip already ran inside advance.
                if not self.blackboard.scratch.get(SCRATCH_SHOP_TRIP):
                    mark_post_shop_return(self.blackboard)
            else:
                clear_shop_trip(self.blackboard)
                from app._04_decision.talking_scroll import mark_post_shop_return

                mark_post_shop_return(self.blackboard)

        # Inventory Fix/Return thresholds own needs_arrows / needs_potion arming.
        # last_arrow_lack / last_hp_potion_used no longer set those flags.

        reject_target = getattr(executor, "last_cursor_reject_target_id", None)
        reject_item = getattr(executor, "last_cursor_reject_item_id", None)
        reason = getattr(executor, "last_cursor_reject_reason", None) or "cursor reject"
        if reject_target is not None:
            _log_action.info(
                "cursor reject id=%s item=false reason=%s",
                reject_target,
                reason,
            )
            if self.note_cursor_verify_fail(
                reject_target, reason=reason, is_item=False
            ):
                _log_action.info(
                    "cursor give-up id=%s item=false reason=%s",
                    reject_target,
                    reason,
                )
            return
        if reject_item is not None:
            self.blackboard.scratch["loot_click_failed"] = True
            _log_action.info(
                "cursor reject id=%s item=true reason=%s",
                reject_item,
                reason,
            )
            if self.note_cursor_verify_fail(
                reject_item, reason=reason, is_item=True
            ):
                _log_action.info(
                    "cursor give-up id=%s item=true reason=%s",
                    reject_item,
                    reason,
                )
            return

        rel = getattr(executor, "last_travel_click_relative", None)
        if rel is not None:
            ax, ay = relative_to_absolute(
                rel[0], rel[1], self.blackboard.world_origin
            )
            abs_tile = (ax, ay)
            # Keep arrival waits aligned with the tile that actually clicked.
            if self.blackboard.travel_hop_active:
                self.blackboard.nav_waypoint = abs_tile
            if self.blackboard.search_hop_active:
                self.blackboard.search_waypoint = abs_tile
            if self.blackboard.loot_approach_active:
                self.blackboard.loot_approach_waypoint = abs_tile
            return

        if getattr(executor, "last_travel_click_failed", False):
            # No NORMAL cursor in the ring — drop hop so next tick replans.
            _log_action.info(
                "travel click failed (no NORMAL in ring) travel=%s search=%s loot=%s",
                bool(self.blackboard.travel_hop_active),
                bool(self.blackboard.search_hop_active),
                bool(self.blackboard.loot_approach_active),
            )
            if self.blackboard.travel_hop_active:
                self.blackboard.travel_hop_active = False
                self.blackboard.nav_waypoint = None
                self.blackboard.travel_destination = None
            if self.blackboard.search_hop_active:
                self.blackboard.search_hop_active = False
                self.blackboard.search_waypoint = None
                self.blackboard.search_destination = None
            if self.blackboard.loot_approach_active:
                self.blackboard.loot_approach_active = False
                self.blackboard.loot_approach_waypoint = None
                self.blackboard.loot_approach_destination = None
            return

        ok_id = (
            getattr(executor, "last_attack_target_id", None)
            or getattr(executor, "last_cast_target_id", None)
            or getattr(executor, "last_loot_target_id", None)
        )
        if ok_id is not None:
            self.note_cursor_verify_ok(ok_id)
        loot_id = getattr(executor, "last_loot_target_id", None)
        if loot_id is not None:
            from app._04_decision.behaviors.loot_hop import mark_loot_clicked

            mark_loot_clicked(self.blackboard, int(loot_id))

    def reset(self) -> None:
        """Clear decision memory (new session / tests)."""
        self.blackboard.reset()
        self._last_goal = None
        self._last_target = None
        self._last_mode = None
        self._last_action = None
        self._repeat_log_count = 0


__all__ = ["DecisionManager"]
