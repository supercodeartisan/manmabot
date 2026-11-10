"""L1 decide orchestrator: sticky PlayerMode policy → one ActionIntent.

Runs ``tick_mode`` (L3) up to 3 handoffs per tick. Hierarchy:
``Docs/architecture/DECISION_HIERARCHY.md``.
"""
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
        from app._04_decision.decide_spans import begin_tick, span
        from app._04_decision.farm_time import sample_farm_presence

        begin_tick()
        from app._04_decision.doors import refresh_live_doors

        refresh_live_doors(getattr(game_state, "last_print_state", None))
        self.blackboard.tick_count += 1
        from app._04_decision.behaviors.combat import sample_kill_progress

        with span("kill progress"):
            sample_kill_progress(game_state, self.blackboard)
        self.blackboard.scratch["live_hotbar"] = getattr(
            game_state, "last_hotbar", None
        )
        with span("farm presence"):
            sample_farm_presence(self.blackboard)
        from app._04_decision.world_nav.routine import sample_routine_zone_clock

        with span("routine clock"):
            sample_routine_zone_clock(self.blackboard)

        from app._04_decision.species_rules import sync_sleeping_golem_hazards

        with span("golem hazards"):
            sync_sleeping_golem_hazards(game_state, self.blackboard)

        # Attack blacklist probes disconnected from the live loop.
        # evaluate_attack_probes(game_state, self.blackboard)

        self.blackboard.intent = None
        self.blackboard.side_intents.clear()
        self.blackboard.current_goal = None
        self.blackboard.scratch.pop("no_intent_why", None)
        self.blackboard.scratch.pop("travel_hop_miss", None)
        legs_before = len(self.blackboard.leg_history)

        status = Status.FAILURE
        handoffs: list[str] = []
        # Allow one mode hand-off in the same tick (arrive → farm, etc.).
        with span("mode handoff"):
            for _ in range(3):
                mode_before = self.blackboard.player_mode.value
                status = tick_mode(game_state, self.blackboard)
                has_intent = self.blackboard.intent is not None
                handoffs.append(
                    f"{mode_before}->{self.blackboard.player_mode.value}/"
                    f"{status.value}/emit={int(has_intent)}"
                )
                if has_intent:
                    break

        from app._04_decision.loot_sides import arm_loot_side_intent
        from app._04_decision.potion_sides import arm_potion_side_intents

        with span("potion sides"):
            arm_potion_side_intents(game_state, self.blackboard)
        with span("loot sides"):
            arm_loot_side_intent(game_state, self.blackboard)

        intent = self.blackboard.intent
        if intent is None:
            intent = ActionIntent(
                action=ActionType.IDLE,
                priority=0.0,
                reason=self._no_intent_reason(status, handoffs),
            )
        self._log_decision(status, intent)
        self._log_new_legs(legs_before)
        # The tick may have crossed into the hunt zone after the opening sample.
        sample_routine_zone_clock(self.blackboard)
        return intent

    def _no_intent_reason(self, status: Status, handoffs: list[str]) -> str:
        """Explain which intended action stalled and why emit never ran."""
        bb = self.blackboard
        mode = bb.player_mode.value
        goal = bb.current_goal or "-"
        purpose = bb.travel_purpose or "-"
        nav = bb.nav_goal
        nav_s = f"({int(nav[0])},{int(nav[1])})" if nav is not None else "-"
        wp = bb.nav_waypoint
        wp_s = f"({int(wp[0])},{int(wp[1])})" if wp is not None else "-"
        # What the bot was trying to do (not the IDLE fallback action).
        if purpose not in (None, "", "-"):
            trying = f"traveling/{purpose}"
        elif goal not in (None, "", "-", "?"):
            trying = f"{mode}/{goal}"
        else:
            trying = str(mode)
        whys = bb.scratch.get("no_intent_why")
        if isinstance(whys, list) and whys:
            why_s = " | ".join(str(x) for x in whys[-4:])
        else:
            miss = bb.scratch.get("travel_hop_miss")
            why_s = (
                f"travel_hop_miss={miss}"
                if miss
                else "mode tick returned without blackboard.emit"
            )
        hops = ",".join(handoffs) if handoffs else "-"
        return (
            f"no intent | trying={trying} action=idle "
            f"mode={mode} goal={goal} purpose={purpose} "
            f"nav={nav_s} wp={wp_s} status={status.value} | "
            f"why={why_s} | handoff={hops}"
        )

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
        sides = ",".join(
            s.action.value for s in (self.blackboard.side_intents or [])
        ) or "-"
        line = (
            f"mode={mode} goal={goal} action={action} target={target} "
            f"sticky={sticky if sticky is not None else '-'} "
            f"origin=({int(origin.x)},{int(origin.y)}) "
            f"shop={int(shop)} scrolled={int(scrolled)} "
            f"sides={sides} "
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
        name: str = "",
        cursor_label: str = "",
        cursor_category: str = "",
        cursor_score: float | None = None,
        need_score: float | None = None,
    ) -> bool:
        """After 5 monster cursor rejects, skip that id for 4 seconds. Items still count misses."""
        return note_cursor_verify_fail(
            self.blackboard,
            track_id,
            reason=reason,
            is_item=is_item,
            name=name,
            cursor_label=cursor_label,
            cursor_category=cursor_category,
            cursor_score=cursor_score,
            need_score=need_score,
        )

    @staticmethod
    def _object_display_name(state: object | None, track_id: int) -> str:
        if state is None:
            return ""
        getter = getattr(state, "get_object", None)
        if not callable(getter):
            return ""
        try:
            obj = getter(int(track_id))
        except (TypeError, ValueError):
            return ""
        if obj is None:
            return ""
        ident = getattr(obj, "identity", None)
        name = (
            getattr(obj, "species_name", None)
            or getattr(obj, "label", None)
            or getattr(ident, "name", None)
            or getattr(obj, "detail_classification", None)
        )
        return str(name or "").strip()

    @staticmethod
    def _cursor_match_meta(executor: object) -> dict[str, object]:
        match = getattr(executor, "last_cursor_match", None)
        thr = None
        try:
            from app._05_action.cursor_match import get_cursor_matcher

            thr = float(get_cursor_matcher().min_score)
        except Exception:
            thr = None
        if match is None:
            return {
                "cursor_label": "",
                "cursor_category": "",
                "cursor_score": None,
                "need_score": thr,
            }
        category = getattr(match, "category", None)
        cat = getattr(category, "value", category)
        score = getattr(match, "score", None)
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        return {
            "cursor_label": str(getattr(match, "label", "") or ""),
            "cursor_category": str(cat or ""),
            "cursor_score": score_f,
            "need_score": thr,
        }

    def _log_travel_cursor_outcome(
        self,
        executor: object,
        *,
        ok: bool,
        abs_tile: tuple[int, int] | None,
    ) -> None:
        """Log travel/search cursor verify for dialog mis-click analysis.

        Dialog-open detection is not wired yet; these lines record whether
        NORMAL was accepted (or the ring failed) and how often dialog was seen.
        """
        meta = self._cursor_match_meta(executor)
        stats = getattr(executor, "last_travel_cursor_stats", None) or {}
        if not isinstance(stats, dict):
            stats = {}
        labels = stats.get("labels_seen") or []
        if isinstance(labels, list):
            labels_s = ",".join(str(x) for x in labels) or "-"
        else:
            labels_s = str(labels or "-")
        intent_reason = str(stats.get("intent_reason") or "")
        if not intent_reason:
            intent = getattr(self.blackboard, "intent", None)
            intent_reason = str(getattr(intent, "reason", "") or "") or "-"
        tile_s = (
            f"({int(abs_tile[0])},{int(abs_tile[1])})"
            if abs_tile is not None
            else "-"
        )
        if ok:
            from app._04_decision.clickgap import note_mouse

            note_mouse(f"travel tile={tile_s} reason={intent_reason}")
            _log_action.info(
                "travel click ok tile=%s cursor=%s/%s score=%s need=%s "
                "probes=%s dialog_seen=%s labels=%s door=%s reason=%r "
                "travel=%s search=%s loot=%s",
                tile_s,
                meta.get("cursor_label") or stats.get("click_label") or "-",
                meta.get("cursor_category") or "-",
                meta.get("cursor_score"),
                meta.get("need_score"),
                int(stats.get("probes") or 0),
                int(stats.get("dialog_seen") or 0),
                labels_s,
                stats.get("door") or "-",
                intent_reason,
                bool(self.blackboard.travel_hop_active),
                bool(self.blackboard.search_hop_active),
                bool(self.blackboard.loot_approach_active),
            )
            return
        label = str(meta.get("cursor_label") or "").strip().lower()
        category = str(meta.get("cursor_category") or "").strip().lower()
        if label.startswith("spell") or category == "spell":
            # Cast-target circle left after buff/heal/mage — travel needs NORMAL.
            now = time.monotonic()
            last = float(getattr(executor, "_last_spell_circle_log_at", 0.0) or 0.0)
            if now - last >= 1.0:
                setattr(executor, "_last_spell_circle_log_at", now)
                _log_action.info(
                    "spell circle cursor seen label=%s/%s score=%s need=%s "
                    "probes=%s blocks travel reason=%r",
                    label or "-",
                    category or "-",
                    meta.get("cursor_score"),
                    meta.get("need_score"),
                    int(stats.get("probes") or 0),
                    intent_reason,
                )
        from app._04_decision.clickgap import note_skip

        note_skip(
            f"travel tile={tile_s} cursor={label or '-'}/{category or '-'} "
            f"reason={intent_reason}"
        )
        _log_action.info(
            "travel click failed tile=%s cursor=%s/%s score=%s need=%s "
            "probes=%s dialog_seen=%s labels=%s door=%s last_reject=%r reason=%r "
            "travel=%s search=%s loot=%s",
            tile_s,
            meta.get("cursor_label") or "-",
            meta.get("cursor_category") or "-",
            meta.get("cursor_score"),
            meta.get("need_score"),
            int(stats.get("probes") or 0),
            int(stats.get("dialog_seen") or 0),
            labels_s,
            stats.get("door") or "-",
            str(
                stats.get("last_reject")
                or getattr(executor, "last_cursor_reject_reason", None)
                or ""
            ),
            intent_reason,
            bool(self.blackboard.travel_hop_active),
            bool(self.blackboard.search_hop_active),
            bool(self.blackboard.loot_approach_active),
        )

    def _click_feedback_origin(self, executor: object):
        """Origin the ground click was aimed with, else the live origin."""
        pinned = getattr(executor, "last_travel_click_origin", None)
        if pinned is None:
            return self.blackboard.world_origin
        from app._02_state.geometry import WorldOrigin

        return WorldOrigin(x=int(pinned[0]), y=int(pinned[1]))

    def _ground_click_shift_reason(
        self,
        planned: tuple[int, int],
        clicked: tuple[int, int],
        state: object | None,
        kind: str,
        origin: object | None = None,
    ) -> str | None:
        """Why ``clicked`` must not become the arrival tile.

        The cursor ring may land on a neighbor. A tile past that ring, a wall,
        or a straight line the client cannot walk is an origin shift, not a
        real click. A travel neighbor farther from ``nav_goal`` than the
        planned tile keeps the planned arrival point (``back``). ``None``
        means the tile may replace the planned hop.
        """
        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision import player_mode as pm
        from app._04_decision.avoidance import click_clear, collect_body_tiles
        from app._04_decision.nav_config import get_terrain_map

        px, py = int(planned[0]), int(planned[1])
        cx, cy = int(clicked[0]), int(clicked[1])
        if tile_chebyshev(px, py, cx, cy) > int(pm.TRAVEL_CURSOR_FALLBACK_RADIUS):
            return "far"
        terrain = get_terrain_map()
        if terrain is None:
            return None
        if not terrain.is_walkable(cx, cy):
            return "wall"
        if origin is None:
            origin = self.blackboard.world_origin
        start = (int(origin.x), int(origin.y))
        bodies = collect_body_tiles(state, origin) if state is not None else set()
        if not click_clear(terrain, bodies, start, (cx, cy)):
            return "line"
        if kind == "travel":
            goal = getattr(self.blackboard, "nav_goal", None)
            if goal is not None and len(goal) >= 2:
                gx, gy = int(goal[0]), int(goal[1])
                if tile_chebyshev(cx, cy, gx, gy) > tile_chebyshev(px, py, gx, gy):
                    return "back"
        return None

    def _adopt_ground_click_tile(
        self,
        kind: str,
        planned: tuple[int, int] | None,
        clicked: tuple[int, int],
        state: object | None,
        origin: object | None = None,
    ) -> bool:
        """Store ``clicked`` as the arrival tile, or drop the hop.

        Returns True when the planned hop stays active.
        """
        if planned is not None:
            reason = self._ground_click_shift_reason(
                planned, clicked, state, kind, origin
            )
            if reason is not None:
                from app.bot_log import event

                event(
                    "avoid",
                    "click tile rejected kind=%s planned=%s got=%s reason=%s",
                    kind,
                    (int(planned[0]), int(planned[1])),
                    (int(clicked[0]), int(clicked[1])),
                    reason,
                )
                # Farther from the goal: the mouse already landed, but the
                # arrival tile stays the planned hop.
                if reason == "back":
                    return True
                return False
        if kind == "travel":
            self.blackboard.nav_waypoint = clicked
        elif kind == "search":
            self.blackboard.search_waypoint = clicked
        elif kind == "loot":
            self.blackboard.loot_approach_waypoint = clicked
        return True

    def _drop_travel_click_hop(self) -> None:
        self.blackboard.travel_hop_active = False
        self.blackboard.nav_waypoint = None
        self.blackboard.travel_destination = None
        self.blackboard.travel_unstick_active = False

    def _drop_search_click_hop(self) -> None:
        self.blackboard.search_hop_active = False
        self.blackboard.search_waypoint = None
        self.blackboard.search_destination = None
        self.blackboard.search_leg_goal = None
        self.blackboard.search_click_at = 0.0

    def _drop_loot_click_hop(self) -> None:
        self.blackboard.loot_approach_active = False
        self.blackboard.loot_approach_waypoint = None
        self.blackboard.loot_approach_destination = None

    def apply_cursor_verify_feedback(
        self, executor: object, state: object | None = None
    ) -> None:
        """Update verify probation from this tick's action-layer result."""
        from app._03_world.space.world_coords import relative_to_absolute

        result = getattr(executor, "result", None)
        if result is not None and bool(getattr(result, "shop_ok", False)):
            bid = str(getattr(result, "shop_behavior_id", "") or "").strip()
            from app._04_decision.shop_trip import advance_sell_trip, clear_shop_trip
            from app._04_decision.shops import (
                POTION_SUPPRESS_S,
                is_arrow_behavior,
                is_depoison_behavior,
                is_hp_potion_behavior,
                is_sell_behavior,
                is_store_behavior,
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
            if is_sell_behavior(bid) or is_store_behavior(bid):
                advance_sell_trip(self.blackboard, state)
                from app._04_decision.talking_scroll import (
                    SCRATCH_SHOP_TRIP,
                    mark_post_shop_return,
                )

                # Sell queue finished → clear_shop_trip already ran inside advance.
                # A pre-retreat sell must retreat, not world-nav back to the farm.
                from app._04_decision.shop_trip import SCRATCH_HP_SELL_BEFORE_RETREAT

                if (
                    not self.blackboard.scratch.get(SCRATCH_SHOP_TRIP)
                    and self.blackboard.scratch.get(SCRATCH_HP_SELL_BEFORE_RETREAT)
                    != "retreat"
                ):
                    if self.blackboard.scratch.get("party_shopkeeper_arrow"):
                        self.blackboard.scratch["party_join_leader"] = True
                        self.blackboard.scratch.pop("party_pin_shop_behavior", None)
                    else:
                        mark_post_shop_return(self.blackboard)
            else:
                from app._04_decision.shops import is_teleporter_behavior
                from app._04_decision.world_nav.hooks import apply_npc_teleporter_result

                # World-nav NPC teleporter: settle+live pose owned by session.
                if is_teleporter_behavior(bid) and apply_npc_teleporter_result(
                    self.blackboard, behavior_id=bid
                ):
                    clear_shop_trip(self.blackboard)
                elif self.blackboard.scratch.get("party_shopkeeper_arrow"):
                    clear_shop_trip(self.blackboard)
                    from app._06_party.arrow_duty import (
                        note_supply_shop_finished,
                        release_finished_party_shop,
                    )

                    if not note_supply_shop_finished(self.blackboard):
                        self.blackboard.scratch["party_join_leader"] = True
                        self.blackboard.scratch.pop("party_pin_shop_behavior", None)
                    release_finished_party_shop(self.blackboard)
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
            mon_name = self._object_display_name(state, int(reject_target))
            meta = self._cursor_match_meta(executor)
            _log_action.info(
                "cursor reject id=%s name=%s item=false reason=%s score=%s need=%s",
                reject_target,
                mon_name or "-",
                reason,
                meta.get("cursor_score"),
                meta.get("need_score"),
            )
            if self.note_cursor_verify_fail(
                reject_target,
                reason=reason,
                is_item=False,
                name=mon_name,
                cursor_label=str(meta.get("cursor_label") or ""),
                cursor_category=str(meta.get("cursor_category") or ""),
                cursor_score=meta.get("cursor_score"),  # type: ignore[arg-type]
                need_score=meta.get("need_score"),  # type: ignore[arg-type]
            ):
                _log_action.info(
                    "cursor give-up id=%s name=%s item=false reason=%s",
                    reject_target,
                    mon_name or "-",
                    reason,
                )
            return
        if reject_item is not None:
            item_name = self._object_display_name(state, int(reject_item))
            meta = self._cursor_match_meta(executor)
            self.blackboard.scratch["loot_click_failed"] = True
            _log_action.info(
                "cursor reject id=%s name=%s item=true reason=%s score=%s need=%s",
                reject_item,
                item_name or "-",
                reason,
                meta.get("cursor_score"),
                meta.get("need_score"),
            )
            if self.note_cursor_verify_fail(
                reject_item,
                reason=reason,
                is_item=True,
                name=item_name,
                cursor_label=str(meta.get("cursor_label") or ""),
                cursor_category=str(meta.get("cursor_category") or ""),
                cursor_score=meta.get("cursor_score"),  # type: ignore[arg-type]
                need_score=meta.get("need_score"),  # type: ignore[arg-type]
            ):
                _log_action.info(
                    "cursor give-up id=%s name=%s item=true reason=%s",
                    reject_item,
                    item_name or "-",
                    reason,
                )
            return

        rel = getattr(executor, "last_travel_click_relative", None)
        if rel is not None:
            origin = self._click_feedback_origin(executor)
            ax, ay = relative_to_absolute(rel[0], rel[1], origin)
            abs_tile = (ax, ay)
            from app._04_decision.behaviors.unstick import note_confined_actual_click

            note_confined_actual_click(self.blackboard, abs_tile)
            # Cursor-ring neighbors stay. A shifted or walled tile is not
            # the arrival point; the next tick plans a new hop. The origin
            # is the one used to aim the click, so a later pose pulse does
            # not slide that tile onto a wall.
            if self.blackboard.travel_hop_active and not self._adopt_ground_click_tile(
                "travel", self.blackboard.nav_waypoint, abs_tile, state, origin
            ):
                self._drop_travel_click_hop()
            if self.blackboard.search_hop_active and not self._adopt_ground_click_tile(
                "search", self.blackboard.search_waypoint, abs_tile, state, origin
            ):
                self._drop_search_click_hop()
            if self.blackboard.loot_approach_active and not self._adopt_ground_click_tile(
                "loot", self.blackboard.loot_approach_waypoint, abs_tile, state, origin
            ):
                self._drop_loot_click_hop()
            self._log_travel_cursor_outcome(executor, ok=True, abs_tile=abs_tile)
            return

        if getattr(executor, "last_travel_click_failed", False):
            # No NORMAL cursor in the ring — drop hop so next tick replans.
            self._log_travel_cursor_outcome(executor, ok=False, abs_tile=None)
            if self.blackboard.travel_hop_active:
                self.blackboard.travel_hop_active = False
                self.blackboard.nav_waypoint = None
                self.blackboard.travel_destination = None
            if self.blackboard.search_hop_active:
                self.blackboard.search_hop_active = False
                self.blackboard.search_waypoint = None
                self.blackboard.search_destination = None
                self.blackboard.search_leg_goal = None
                self.blackboard.search_click_at = 0.0
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

            mark_loot_clicked(self.blackboard, int(loot_id), state)

    def reset(self) -> None:
        """Clear decision memory (new session / tests)."""
        self.blackboard.reset()
        self._last_goal = None
        self._last_target = None
        self._last_mode = None
        self._last_action = None
        self._repeat_log_count = 0


__all__ = ["DecisionManager"]
