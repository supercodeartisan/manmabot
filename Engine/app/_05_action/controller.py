"""Converts decisions into actual game actions (Lineage_bot ActionExecutor port)."""
from __future__ import annotations

import math
import random
import threading
import time
from typing import Any, Optional

from app._05_action.window_bounds import WindowBounds
from app._04_decision.types import ActionIntent
from app._03_world import WorldState, CharacterType, ActionType, ObjectType
from app._05_action import humanize as hz
from app._05_action.combat_strategies import CombatStrategy, combat_strategy_for
from app._05_action.coordinates import game_to_screen
from app._05_action.mouse import MouseController
from app._05_action.keyboard import KeyboardController
from app._05_action.result import ActionResult
from app._05_action import spell_box as sb


# Backward-compatible names: minimum of the humanized interval range.
MAGE_CAST_INTERVAL = hz.MAGE_CAST_INTERVAL[0]
ELF_ATTACK_INTERVAL = hz.ELF_ATTACK_INTERVAL[0]


class ActionExecutor:
    """Executes ActionIntent using mouse/keyboard input."""

    def __init__(
        self,
        enabled: bool = True,
        character: CharacterType = CharacterType.MAGE,
        humanize: bool = True,
        humanize_move: Optional[bool] = None,
        rng: Optional[random.Random] = None,
    ):
        self.character = character
        self.humanize = humanize
        self._rng = rng if rng is not None else random.Random()
        self._combat: CombatStrategy = combat_strategy_for(character)

        self.keyboard = KeyboardController(
            enabled=enabled, humanize=humanize, rng=self._rng
        )
        self.mouse = MouseController(
            enabled=enabled,
            humanize=humanize,
            humanize_move=humanize if humanize_move is None else bool(humanize_move),
            rng=self._rng,
        )

        self._holding = False
        self._last_mage_cast = 0.0
        self._last_magic_at = 0.0
        self._mage_cast_gap = self._sample_mage_gap()
        self._last_elf_click = 0.0
        self._elf_click_gap = self._sample_elf_gap()
        self._last_loot_click = 0.0
        self._loot_click_gap = self._sample_loot_gap()
        # Set when a mage spell cast actually runs this execute() call.
        self.last_cast_target_id: Optional[int] = None
        # Set when a melee/elf attack input actually runs this execute() call.
        self.last_attack_target_id: Optional[int] = None
        # Cursor verifier: last match / reject reason / which id was rejected.
        self.last_cursor_match = None
        self.last_cursor_reject_reason: Optional[str] = None
        self.last_cursor_reject_target_id: Optional[int] = None
        self.last_cursor_reject_item_id: Optional[int] = None
        # Travel/search: relative WCS tile clicked after NORMAL verify (or fail).
        self.last_travel_click_relative: Optional[tuple[int, int]] = None
        self.last_travel_click_failed: bool = False
        # Probe stats for travel/search cursor analysis (dialog mis-click hunt).
        self.last_travel_cursor_stats: dict = {}
        self.last_arrow_lack: bool = False
        self.hotbar_layout: dict = {}
        self.last_hp_potion_used: bool = False
        self.result: ActionResult = ActionResult()
        self._perception_capture = None
        # Attack/mage aim: sticky pixel lock + ring walk index across ticks.
        self._attack_aim_tid: Optional[int] = None
        self._attack_aim_idx: int = 0
        self._attack_aim_lock: Optional[tuple[int, float, float]] = None
        self._last_aim_click_xy: Optional[tuple[float, float]] = None
        # Set when a loot click actually lands this execute() call.
        self.last_loot_target_id: Optional[int] = None
        # Actual mouse result of the last execute() (not decision intent).
        self.last_mouse_outcome: dict = {
            "kind": "none",
            "clicked": False,
            "hovered": False,
        }
        # Box 1 is selected with F1 on the first execute().
        # Every spell/potion press also taps Fi for its box before F5–F12.
        # Slots (box + F5–F12) come from ``spell_box.configure_spell_box``.
        self._skill_box: int = 1
        self._skill_box_ready: bool = False
        # Esc closes unexpected uidialog OPEN windows (misclick recovery).
        # Toggled by action.yaml ``dismiss_ui_enabled`` (default True with uidialog).
        self._dismiss_ui_enabled = True
        self._last_dismiss_ui = time.time()
        self._dismiss_ui_gap = self._sample_dismiss_ui_gap()
        # Optional decide blackboard for live pose pulses during blocking acts.
        self._blackboard = None

    def set_character(self, character: CharacterType) -> None:
        """Switch class and reload the combat strategy."""
        self.character = character
        self._combat = combat_strategy_for(character)

    # Compat shims for pre-ActionResult readers (prefer ``self.result``).
    @property
    def last_shop_ok(self) -> bool:
        return bool(self.result.shop_ok)

    @property
    def last_shop_behavior_id(self) -> str:
        return str(self.result.shop_behavior_id or "")

    @property
    def last_gate_ok(self) -> bool:
        return bool(self.result.gate_ok)

    @property
    def last_gate_error(self) -> str:
        return str(self.result.gate_error or "")

    @property
    def last_gate_pose(self) -> Optional[tuple[int, int, int]]:
        return self.result.gate_pose

    def enable(self):
        self.keyboard.enable()
        self.mouse.enable()

    def disable(self):
        self.keyboard.disable()
        self.mouse.disable()

    def _sample_mage_gap(self) -> float:
        rng = self._rng if self.humanize else None
        sampled = hz.attack_gap(hz.MAGE_CAST_INTERVAL, rng)
        return max(sb.MAGIC_COOLDOWN_S, sampled)

    def _sample_elf_gap(self) -> float:
        rng = self._rng if self.humanize else None
        return hz.attack_gap(hz.ELF_ATTACK_INTERVAL, rng)

    def _sample_loot_gap(self) -> float:
        lo, hi = hz.LOOT_CLICK_INTERVAL
        if not self.humanize:
            return (lo + hi) / 2.0
        return hz.uniform(hz.LOOT_CLICK_INTERVAL, self._rng)

    def _sample_dismiss_ui_gap(self) -> float:
        lo, hi = hz.DISMISS_UI_INTERVAL
        if not self.humanize:
            return (lo + hi) / 2.0
        return hz.uniform(hz.DISMISS_UI_INTERVAL, self._rng)

    def _screen_point(self, nx: float, ny: float, bounds: WindowBounds) -> tuple[int, int]:
        """Map content coords to desktop pixels (no aim jitter).

        YOLO boxes and planned tile centers already carry positional noise;
        extra pixel jitter only drifts clicks off the intended target.
        """
        return game_to_screen(nx, ny, bounds)

    def _pause(self, lo_hi: tuple[float, float]) -> None:
        if self.humanize:
            hz.sleep_range(lo_hi, self._rng)

    def _halt_before_attack(self, *, mid_act: bool) -> None:
        """Esc to cancel walk before the first click on a monster.

        Sticky re-clicks skip this so melee can still close range. Knob:
        ``action.stop_before_attack`` / ``stop_before_attack_wait_s`` in
        ``config/action.yaml`` (wait 0 = press Esc instantly).
        """
        if mid_act or not hz.ATTACK_STOP_ENABLED:
            return
        self.keyboard.press("esc")
        wait = float(hz.ATTACK_STOP_WAIT_S or 0.0)
        if wait > 0:
            self._fixed_wait(wait)

    def drop_mouse(self) -> None:
        """Lift the left button once. Safe if it is already up."""
        try:
            self.mouse.release("left")
        except Exception:
            pass
        self._holding = False

    @staticmethod
    def _primary_is_mouse_click(action: ActionIntent) -> bool:
        """True when the primary intent's main input is a mouse click."""
        return action.action in (
            ActionType.ATTACK,
            ActionType.PICKUP,
            ActionType.SEARCHING,
            ActionType.TRAVELING,
            ActionType.GATE,
            ActionType.SHOP_RUN,
            ActionType.RESPAWN,
            ActionType.DISMISS_LEVEL_UP,
        )

    def _execute_potion_sides(self, side_intents: list[ActionIntent] | None) -> None:
        """Run potion side channel (HP / MP / depoison). No new ActionTypes."""
        if not side_intents:
            return
        for side in side_intents:
            if side is None:
                continue
            if side.action is ActionType.USE_HP_POTION:
                self._use_hp_potion(side)
            elif side.action is ActionType.USE_MP_POTION:
                self._use_mp_potion()
            elif side.action is ActionType.USE_DEPOISON:
                self._use_depoison()

    def _execute_loot_sides(
        self,
        side_intents: list[ActionIntent] | None,
        game_state: WorldState,
        bounds: WindowBounds,
    ) -> None:
        """F4 pickup for in-range loot sides (before primary)."""
        if not side_intents:
            return
        for side in side_intents:
            if side is None or side.action is not ActionType.PICKUP:
                continue
            self._loot(side, game_state, bounds)

    def execute(
        self,
        game_state: WorldState,
        action: ActionIntent,
        bounds: Optional[WindowBounds] = None,
        side_intents: Optional[list[ActionIntent]] = None,
        blackboard: Any = None,
    ) -> None:
        """Execute primary intent; loot/potion sides run in the same tick.

        In-range loot ``PICKUP`` sides F4 before the primary (so combat does
        not starve pickup). Mouse-click primary: potion keys overlap on a
        side thread. Keyboard-press primary: potion sides first, then key.

        While this call blocks (travel/shop/gate/scroll), a pose pulse thread
        keeps monitor mapId/xy on ``game_state`` / ``blackboard`` so the debug
        window and the next tick never see a frozen character cell.
        """
        self._world = game_state
        self._blackboard = blackboard
        self.last_cast_target_id = None
        self.last_attack_target_id = None
        self.last_loot_target_id = None
        self.last_cursor_reject_reason = None
        self.last_cursor_reject_target_id = None
        self.last_cursor_reject_item_id = None
        self.last_travel_click_relative = None
        self.last_travel_click_failed = False
        self.last_travel_cursor_stats = {}
        self.last_arrow_lack = False
        self.last_hp_potion_used = False
        self.result = ActionResult()
        if bounds is None or not bounds.valid:
            self.last_mouse_outcome = {
                "kind": "none",
                "clicked": False,
                "hovered": False,
                "detail": "no bounds",
            }
            return

        from app._03_world.merge.memory_sync import refresh_live_player_pose

        def _pose_pulse() -> None:
            refresh_live_player_pose(game_state, blackboard)

        self.mouse._pose_pulse = _pose_pulse
        pulse_stop = threading.Event()

        def _pulse_loop() -> None:
            while not pulse_stop.wait(0.1):
                try:
                    _pose_pulse()
                except Exception:
                    pass

        pulse_thread = threading.Thread(
            target=_pulse_loop, daemon=True, name="pose-pulse"
        )
        pulse_thread.start()
        try:
            self._execute_body(
                game_state,
                action,
                bounds=bounds,
                side_intents=side_intents,
            )
        finally:
            pulse_stop.set()
            pulse_thread.join(timeout=0.5)
            self.mouse._pose_pulse = None

    def _execute_body(
        self,
        game_state: WorldState,
        action: ActionIntent,
        bounds: WindowBounds,
        side_intents: Optional[list[ActionIntent]] = None,
    ) -> None:
        """Inner execute after pose-pulse wiring."""
        self._ensure_skill_box()
        clicks_before = getattr(self.mouse, "button_events", 0)
        moves_before = getattr(self.mouse, "move_events", 0)

        # Close stray uidialog windows from mis-clicks (memory open/closed).
        if action.action not in (
            ActionType.TELEPORT,
            ActionType.RETURN_TO_MOTHER_TREE,
            ActionType.HP_TO_MP,
            ActionType.USE_TALKING_SCROLL,
            ActionType.GATE,
            ActionType.SHOP_RUN,
            ActionType.SHOP_STOP,
            ActionType.DISMISS_LEVEL_UP,
            ActionType.RESPAWN,
        ):
            self._maybe_dismiss_ui()

        sides = list(side_intents or [])
        loot_sides = [
            s for s in sides if s is not None and s.action is ActionType.PICKUP
        ]
        potion_sides = [
            s
            for s in sides
            if s is not None
            and s.action
            in (
                ActionType.USE_HP_POTION,
                ActionType.USE_MP_POTION,
                ActionType.USE_DEPOISON,
            )
        ]
        # In-range loot before primary — never wait for combat to finish.
        if loot_sides and action.action is not ActionType.PICKUP:
            self._execute_loot_sides(loot_sides, game_state, bounds)

        mouse_primary = self._primary_is_mouse_click(action)
        side_thread: threading.Thread | None = None
        if mouse_primary and potion_sides:
            # Overlap potion keys with the mouse path — do not serialize.
            side_thread = threading.Thread(
                target=self._execute_potion_sides,
                args=(potion_sides,),
                daemon=True,
                name="potion-sides",
            )
            side_thread.start()
        elif not mouse_primary and potion_sides:
            # Keyboard / idle primary: potions before the primary key.
            self._execute_potion_sides(potion_sides)

        # ``mid_act`` is decide-owned (travel/search legs, combat sticky). Action
        # only reads it — never clears or forces it.
        is_combat = action.action is ActionType.ATTACK
        is_loot = action.action is ActionType.PICKUP

        # Execute new action
        if not action.mid_act:
            # Do not mouse-up on idle ticks: that cancels the operator's drag.
            # Still lift if we think a hold is down (legacy melee hold).
            if action.action is not ActionType.IDLE or self._holding:
                self.drop_mouse()
            self._holding = False

            if is_combat:
                pass  # class strategy runs below for every combat tick

            elif is_loot:
                pass  # loot cadence runs below every tick (like elf)

            elif action.action == ActionType.IDLE:
                self._idle()

            elif action.action == ActionType.SEARCHING:
                self._search(action, bounds)

            elif action.action == ActionType.TRAVELING:
                self._travel(action, bounds)

            elif action.action == ActionType.USE_HP_POTION:
                self._use_hp_potion(action)

            elif action.action == ActionType.USE_MP_POTION:
                self._use_mp_potion()

            elif action.action == ActionType.USE_DEPOISON:
                self._use_depoison()

            elif action.action == ActionType.HEAL:
                self._heal(bounds, action)

            elif action.action == ActionType.BUFF:
                self._buff(action.reason)

            elif action.action == ActionType.TELEPORT:
                self._teleport()

            elif action.action == ActionType.RETURN_TO_MOTHER_TREE:
                self._return_to_mother_tree()

            elif action.action == ActionType.HP_TO_MP:
                self._hp_to_mp()

            elif action.action == ActionType.USE_TALKING_SCROLL:
                self._use_talking_scroll(action, bounds)

            elif action.action == ActionType.GATE:
                self._gate(action, game_state, bounds)

            elif action.action == ActionType.SHOP_STOP:
                self._shop_stop()

            elif action.action == ActionType.DISMISS_LEVEL_UP:
                self._dismiss_level_up()

            elif action.action == ActionType.SHOP_RUN:
                self._shop_run(action, bounds)

            elif action.action == ActionType.RESPAWN:
                self._respawn(action, bounds)

        # Per-class combat (mage cast / knight+elf timed clicks / …).
        if is_combat:
            self._combat.attack(
                self,
                action,
                game_state,
                bounds,
                mid_act=bool(action.mid_act),
            )
        elif is_loot:
            self._loot(action, game_state, bounds)

        if side_thread is not None:
            side_thread.join(timeout=2.0)

        self._maybe_init_skill_box(clicks_before)
        clicks_after = int(getattr(self.mouse, "button_events", 0) or 0)
        moves_after = int(getattr(self.mouse, "move_events", 0) or 0)
        clicked = clicks_after > int(clicks_before or 0)
        hovered = moves_after > int(moves_before or 0)
        if clicked:
            pos = getattr(self.mouse, "_last_pos", None)
            if pos is not None:
                try:
                    from app._03_world.debug.field_clicks import note_screen_click

                    note_screen_click(
                        pos[0],
                        pos[1],
                        bounds,
                        clicks_after - int(clicks_before or 0),
                    )
                except Exception:
                    pass
        if clicked:
            kind = "click"
        elif hovered:
            kind = "hover"
        else:
            kind = "none"
        detail = ""
        if self.last_cursor_reject_target_id is not None:
            detail = (
                f"reject target={self.last_cursor_reject_target_id}"
                f" {self.last_cursor_reject_reason or ''}".rstrip()
            )
        elif self.last_cursor_reject_item_id is not None:
            detail = (
                f"reject item={self.last_cursor_reject_item_id}"
                f" {self.last_cursor_reject_reason or ''}".rstrip()
            )
        elif self.last_attack_target_id is not None:
            detail = f"attack id={self.last_attack_target_id}"
        elif self.last_cast_target_id is not None:
            detail = f"cast id={self.last_cast_target_id}"
        elif self.last_loot_target_id is not None:
            detail = f"loot id={self.last_loot_target_id}"
        elif self.last_travel_click_failed:
            stats = self.last_travel_cursor_stats or {}
            detail = (
                "travel verify failed"
                f" probes={int(stats.get('probes') or 0)}"
                f" dialog_seen={int(stats.get('dialog_seen') or 0)}"
                f" reject={stats.get('last_reject') or self.last_cursor_reject_reason or ''}"
            ).rstrip()
        elif self.last_travel_click_relative is not None:
            stats = self.last_travel_cursor_stats or {}
            match = self.last_cursor_match
            label = str(getattr(match, "label", "") or stats.get("click_label") or "")
            detail = (
                f"travel {self.last_travel_click_relative}"
                f" cursor={label or '-'}"
                f" probes={int(stats.get('probes') or 0)}"
                f" dialog_seen={int(stats.get('dialog_seen') or 0)}"
            )
        self.last_mouse_outcome = {
            "kind": kind,
            "clicked": clicked,
            "hovered": hovered,
            "detail": detail.strip(),
            "attack_id": self.last_attack_target_id,
            "cast_id": self.last_cast_target_id,
            "loot_id": self.last_loot_target_id,
            "reject_target_id": self.last_cursor_reject_target_id,
            "reject_item_id": self.last_cursor_reject_item_id,
            "reject_reason": self.last_cursor_reject_reason,
            "travel_cursor": dict(self.last_travel_cursor_stats or {}),
        }

    def _maybe_dismiss_ui(self) -> None:
        """Esc when a watched uidialog is OPEN unexpectedly (misclick recovery).

        Requires ``_dismiss_ui_enabled``. Skipped for shop/scroll/gate/teleport
        actions. Retry gap uses ``DISMISS_UI_INTERVAL``.
        """
        if not self._dismiss_ui_enabled:
            return
        from app._05_action.uidialog_gate import unexpected_open_labels

        snap = getattr(self._world, "last_uidialog", None)
        if not isinstance(snap, dict):
            try:
                from app._01_perception.sensors import shared_sensors

                snap = shared_sensors().capture_uidialog()
            except Exception:
                return
        if not unexpected_open_labels(snap, allowed=()):
            return
        now = time.time()
        if now - self._last_dismiss_ui < self._dismiss_ui_gap:
            return
        self.keyboard.press("esc")
        self._last_dismiss_ui = now
        self._dismiss_ui_gap = self._sample_dismiss_ui_gap()

    # --------------------------------------------------
    # Action implementations
    # --------------------------------------------------

    def _idle(self) -> None:
        pass

    def _loot_avoid_uv(self, action: ActionIntent) -> tuple[float, float] | None:
        """Item UV when this hop is a loot approach (do not click the pile)."""
        if not action.target_id:
            return None
        world = getattr(self, "_world", None)
        if world is None:
            return None
        obj = world.get_object(action.target_id)
        if obj is None or getattr(obj, "object_type", None) is not ObjectType.ITEM:
            return None
        pos = getattr(obj, "position", None)
        if pos is None:
            return None
        return float(pos.x), float(pos.y)

    def _offset_uv_from_item(self, dest, avoid: tuple[float, float]):
        from app._02_state.objects import Position

        dx = float(dest.x) - avoid[0]
        dy = float(dest.y) - avoid[1]
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            dx = 0.5 - avoid[0]
            dy = 0.5 - avoid[1]
            dist = max(math.hypot(dx, dy), 1e-6)
        scale = 0.04 / dist
        return Position(x=avoid[0] + dx * scale, y=avoid[1] + dy * scale)

    def _search(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Click a ground hop; require NORMAL cursor, else a small tile ring."""
        if action.destination is None:
            return
        from app._05_action.cursor_catalog import CursorCategory
        from app._05_action.cursor_verify import travel_click
        from app._05_action.travel_click import (
            content_destinations_ring,
            relative_tile_of_content,
        )

        dests = list(content_destinations_ring(action.destination))
        probes = 0
        dialog_seen = 0
        seen_labels: list[str] = []
        for content in dests:
            x, y = self._screen_point(content.x, content.y, bounds)
            probes += 1
            if travel_click(self, x, y):
                self.last_travel_click_relative = relative_tile_of_content(content)
                match = getattr(self, "last_cursor_match", None)
                label = str(getattr(match, "label", "") or "")
                self.last_travel_cursor_stats = {
                    "ok": True,
                    "probes": probes,
                    "dialog_seen": dialog_seen,
                    "labels_seen": seen_labels,
                    "click_label": label,
                    "intent_reason": str(getattr(action, "reason", "") or ""),
                }
                return
            match = getattr(self, "last_cursor_match", None)
            label = str(getattr(match, "label", "") or "")
            if label:
                if label not in seen_labels:
                    seen_labels.append(label)
                category = getattr(match, "category", None)
                if label == "dialog" or category is CursorCategory.DIALOG:
                    dialog_seen += 1
        self.last_travel_click_failed = True
        self.last_travel_cursor_stats = {
            "ok": False,
            "probes": probes,
            "dialog_seen": dialog_seen,
            "labels_seen": seen_labels,
            "last_reject": str(self.last_cursor_reject_reason or ""),
            "intent_reason": str(getattr(action, "reason", "") or ""),
        }

    def _loot(
        self,
        action: ActionIntent,
        game_state: WorldState,
        bounds: WindowBounds,
    ) -> None:
        """Near-range pickup.

        Temporary: F4 only (item click + NORMAL cursor gate disabled).
        Set ``LOOT_PICKUP_USE_F4 = False`` to restore click path; after F4
        proves out, delete the click branch entirely.
        """
        # TEMP: F4 pickup. Flip False to re-enable loot_click_search.
        LOOT_PICKUP_USE_F4 = True

        now = time.time()

        from app._04_decision.clickgap import note_mouse, note_skip

        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            note_skip(f"loot id={action.target_id} why=no-object")
            return
        missing = getattr(game_state, "missing_frames", None)
        if callable(missing) and int(missing(target.track_id) or 0) >= 1:
            note_skip(f"loot id={action.target_id} why=missing-frame")
            return

        if LOOT_PICKUP_USE_F4:
            del bounds
            # Leave leftover attack hover (corpse/empty arrow) before F4.
            from app._05_action.cursor_verify import clear_loot_attack_hover

            clear_loot_attack_hover(self)
            self.keyboard.press("f4")
            note_mouse(f"loot f4 id={action.target_id}")
            self._last_loot_click = now
            self._loot_click_gap = self._sample_loot_gap()
            self.last_loot_target_id = action.target_id
            return

        # Legacy: click pile UV / memory cell after NORMAL cursor verify.
        from app._05_action.cursor_verify import (
            loot_click_search,
            object_loot_screen_points,
        )

        x, y = self._screen_point(target.position.x, target.position.y, bounds)
        points = object_loot_screen_points(self, target, bounds)
        if not points:
            points = [(x, y)]
        if not loot_click_search(self, points):
            self.last_cursor_reject_item_id = action.target_id
            return
        self._last_loot_click = now
        self._loot_click_gap = self._sample_loot_gap()
        self.last_loot_target_id = action.target_id

    def _travel(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Move toward destination (same as search for now)."""
        self._search(action, bounds)

    def _use_hp_potion(self, action: ActionIntent | None = None) -> None:
        """Press the F1–F3 page and F5–F12 key where that HP item sits."""
        box = getattr(action, "hotbar_box", None) if action is not None else None
        key = str(getattr(action, "hotbar_key", "") or "").strip().lower()
        if box in (1, 2, 3) and key:
            self._press_box_skill(int(box), key)
            self.last_hp_potion_used = True
            return
        try:
            from app._04_decision import player_mode as pm
            from app._04_decision.hp_actions import action_row, assigned_hotbar_slot

            bound = assigned_hotbar_slot(
                action_row(getattr(pm, "HP_ACTIONS", None) or [], "hp_potion")
            )
        except Exception:
            bound = None
        if bound is not None:
            self._press_box_skill(bound[0], bound[1])
            self.last_hp_potion_used = True
            return
        item_key = str(getattr(action, "item_key", "") or "").strip()
        if item_key:
            from app._04_decision.hp_actions import find_hp_restore_hotbar

            slot = find_hp_restore_hotbar(
                getattr(self, "_world", None),
                item_key,
                layout=getattr(self, "hotbar_layout", None),
            )
            if slot is not None:
                self._press_box_skill(slot[0], slot[1])
                self.last_hp_potion_used = True
                return
        self._press_assigned_skill("hp_potion")
        self.last_hp_potion_used = True

    def _use_mp_potion(self) -> None:
        """MP potion item — press once or twice per slot cast setting."""
        self._press_assigned_skill("mp_potion")

    def _use_depoison(self) -> None:
        """Antidote item — press the bound hotbar slot."""
        self._press_assigned_skill("depoison")

    def _live_or_assigned_slot(self, name: str) -> tuple[int | None, str]:
        """Prefer the live hotbar cell for this role; Setup slot if unread.

        Haste: hunt hotbar assignment wins; checkbox-only uses CSV role.
        """
        snap = getattr(getattr(self, "_world", None), "last_hotbar", None)
        slots = snap.get("slots") if isinstance(snap, dict) else None
        if str(name) == "talking_scroll" and sb.talking_scroll_boot_active():
            if not sb.slot_is_enabled("talking_scroll"):
                return None, ""
            return sb.slot_press("talking_scroll")
        if str(name) == "haste":
            from app._04_decision.spells import HASTE_POTION_ITEM
            from settings.haste_potion import resolve_haste_press_slot

            assigned = sb.slot_press("haste") if sb.slot_is_enabled("haste") else None
            found = resolve_haste_press_slot(
                item_key=HASTE_POTION_ITEM,
                assigned_slot=assigned,
                live_snap=snap if isinstance(snap, dict) else None,
            )
            if found is None:
                return None, ""
            return found
        if str(name) in ("heal", "hp_potion"):
            try:
                from app._04_decision import player_mode as pm
                from app._04_decision.hp_actions import (
                    action_row,
                    assigned_hotbar_slot,
                )

                bound = assigned_hotbar_slot(
                    action_row(getattr(pm, "HP_ACTIONS", None) or [], name)
                )
            except Exception:
                bound = None
            if bound is not None:
                return bound
        if isinstance(slots, list) and slots:
            from hotbar.inspect import find_role_on_hotbar

            found = find_role_on_hotbar(snap, name)
            if found is None:
                if str(name) == "heal":
                    return sb.slot_press("heal")
                return None, ""
            return found
        return sb.slot_press(name)

    def _press_assigned_skill(
        self,
        name: str,
        duration: float | None = None,
        *,
        forced_slot: tuple[int, str] | None = None,
    ) -> None:
        # Heal was already accepted by decision. Action only presses the key.
        if name != "heal" and not sb.slot_is_enabled(name):
            return
        if sb.slot_is_magic(name) and name not in (
            "mother_tree",
            "hp_to_mp",
            "heal",
        ):
            from app._04_decision.spells import can_cast_spell, mother_tree_mana_blocks

            world = getattr(self, "_world", None)
            if world is not None:
                # Keep absolute MP for mother tree when that retreat is on.
                if mother_tree_mana_blocks(world, name):
                    return
                if name == "teleport":
                    pass  # percent reserve does not gate escape teleport
                elif not can_cast_spell(world, role=name):
                    return
        if sb.slot_is_magic(name):
            wait = sb.MAGIC_COOLDOWN_S - (time.time() - self._last_magic_at)
            if self._last_magic_at > 0 and wait > 0:
                time.sleep(wait)
        if forced_slot is not None:
            box, key = forced_slot
        else:
            box, key = self._live_or_assigned_slot(name)
            if name == "heal" and (box is None or not key):
                box, key = sb.slot_press("heal")
        if box is None or not key:
            return
        from app.bot_log import get_logger

        get_logger("action").info(
            "skill press name=%s box=%s key=%s double=%s",
            name,
            int(box),
            key,
            int(sb.slot_is_double(name)),
        )
        self._press_box_skill(box, key, duration=duration)
        if sb.slot_is_double(name):
            if self.humanize:
                hz.sleep_range(hz.HEAL_DOUBLE_GAP, self._rng)
            else:
                time.sleep(0.05)
            self.keyboard.press(key)
            get_logger("action").info(
                "skill press name=%s box=%s key=%s double=2",
                name,
                int(box),
                key,
            )
        if sb.slot_is_magic(name):
            now = time.time()
            self._last_magic_at = now
            if name == "mage_attack":
                self._last_mage_cast = now

    def _heal(self, bounds: WindowBounds, intent: ActionIntent | None = None) -> None:
        """Press the heal key decision already chose. No second veto."""
        del bounds
        forced: tuple[int, str] | None = None
        if intent is not None and intent.hotbar_box and intent.hotbar_key:
            forced = (int(intent.hotbar_box), str(intent.hotbar_key).strip().lower())
        self._press_assigned_skill("heal", forced_slot=forced)

    def _buff(self, which: str) -> None:
        """Self buff: power-up / armor / haste / light at the assigned slot."""
        name = str(which or "")
        if name not in ("power_up", "armor_up", "haste", "light"):
            return
        self._press_assigned_skill(name)

    def _ensure_skill_box(self) -> None:
        """Press F1 once when the bot starts acting so box 1 is selected."""
        if self._skill_box_ready:
            return
        self.select_skill_box(sb.START_BOX, force=True)
        self._skill_box_ready = True

    def _maybe_init_skill_box(self, clicks_before: int) -> None:
        """Re-assert F1 after the first mouse-down (game focus)."""
        if self._skill_box_ready and clicks_before > 0:
            return
        clicks_after = getattr(self.mouse, "button_events", 0)
        if clicks_after <= clicks_before:
            return
        self.select_skill_box(sb.START_BOX, force=True)
        self._skill_box_ready = True

    def select_skill_box(self, box: int, *, force: bool = False) -> None:
        """Switch shortcut box with F1 / F2 / F3 (skills themselves use F5–F12)."""
        if box not in (1, 2, 3):
            raise ValueError(f"skill box must be 1..3, got {box}")
        if not force and self._skill_box == box:
            return
        switched = self._skill_box != box
        key = ("f1", "f2", "f3")[box - 1]
        self.keyboard.press(key)
        self._skill_box = box
        # Full settle only when the page actually changes. Re-asserting the
        # same box is a tap so the following F5–F12 cannot hit the wrong page.
        if self.humanize and switched:
            hz.sleep_range(hz.BOX_SWITCH_WAIT, self._rng)

    def _press_box_skill(
        self,
        box: int,
        key: str,
        duration: float | None = None,
    ) -> None:
        """Press box key Fi, then the skill/item key (F5–F12)."""
        self.select_skill_box(box, force=True)
        self.keyboard.press(key, duration=duration)

    def _fixed_wait(self, seconds: float) -> None:
        """UI settle delay. Skipped in tests (humanize off)."""
        if not self.humanize:
            return
        time.sleep(seconds)

    def _use_talking_scroll(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Practice path: force box, wait for the list, click with live bounds."""
        if action.destination is None:
            return
        if not sb.slot_is_enabled("talking_scroll"):
            return
        box, key = self._live_or_assigned_slot("talking_scroll")
        if box is None or not key:
            return
        from app.bot_log import get_logger

        log = get_logger("scroll")
        self.select_skill_box(int(box), force=True)
        self._fixed_wait(hz.TALKING_SCROLL_BOX_S)
        self.keyboard.press(str(key))
        # Wheel only after TalkingScroll is OPEN. If the key did not open
        # the list within 2s, press the scroll key once more. No click until open.
        from app._05_action.uidialog_gate import (
            LABEL_TALKING_SCROLL,
            wait_uidialog_open,
        )

        _SCROLL_OPEN_WAIT_S = 2.0
        reason = getattr(action, "reason", "") or "-"

        def _wait_open() -> bool:
            opened_now = wait_uidialog_open(
                (LABEL_TALKING_SCROLL,),
                timeout_s=_SCROLL_OPEN_WAIT_S,
            )
            log.info(
                "talking scroll key=%s box=%s opened=%s wait=%.2fs reason=%s",
                key,
                box,
                opened_now,
                _SCROLL_OPEN_WAIT_S,
                reason,
            )
            return opened_now

        opened = _wait_open()
        if not opened:
            log.info(
                "talking scroll not open within %.2fs — press key again",
                _SCROLL_OPEN_WAIT_S,
            )
            self.select_skill_box(int(box), force=True)
            self._fixed_wait(hz.TALKING_SCROLL_BOX_S)
            self.keyboard.press(str(key))
            opened = _wait_open()
        if not opened:
            log.info("talking scroll still not open — skip wheel and click")
            return
        click_bounds = bounds
        capture = getattr(self, "_perception_capture", None)
        if capture is not None:
            try:
                capture.refresh_click_bounds()
            except Exception:
                pass
            fresh = getattr(capture, "content_bounds", None)
            if fresh is not None and getattr(fresh, "valid", False):
                click_bounds = fresh
        wheels = int(getattr(action, "scroll_times", 0) or 0)
        if wheels > 0:
            log.info("talking scroll open — wheel then click wheels=%d", wheels)
            # Hover list body (not camera), then wheel — same as Extra_data live.
            hover_u = min(0.18, max(0.06, float(action.destination.x)))
            hx, hy = game_to_screen(hover_u, 0.20, click_bounds)
            self.mouse.move(hx, hy, snap=True)
            time.sleep(0.2)
            try:
                from app._05_action.mouse import _ensure_captured, _get_interception

                _ensure_captured()
                ix = _get_interception()
                for i in range(wheels):
                    ix.scroll("down")
                    time.sleep(0.06 if i < 8 else 0.05)
                time.sleep(0.25)
            except Exception:
                pass
        x, y = game_to_screen(action.destination.x, action.destination.y, click_bounds)
        log.info(
            "talking scroll click uv=(%.3f,%.3f) screen=(%d,%d) wheels=%d",
            float(action.destination.x),
            float(action.destination.y),
            int(x),
            int(y),
            wheels,
        )
        self.mouse.move_and_click(x, y, snap=True)
        self._fixed_wait(hz.TALKING_SCROLL_AFTER_CLICK_S)
        self.select_skill_box(sb.START_BOX, force=True)
        if bool(getattr(action, "shop_land_wait", False)):
            self._fixed_wait(hz.TALKING_SCROLL_SHOP_WAIT_S)

    def use_talking_scroll(self) -> None:
        """Legacy helper: press the talking-scroll key only (no list click)."""
        self._press_assigned_skill("talking_scroll")
        self.select_skill_box(sb.START_BOX)

    def _teleport(self) -> None:
        """Escape teleport. Used at retreat start and unstick."""
        self._press_assigned_skill("teleport")
        if self.humanize:
            hz.sleep_range(hz.ESCAPE_WAIT, self._rng)
        else:
            time.sleep(0.4)

    def _return_to_mother_tree(self) -> None:
        """Box 2 F6 (elf spell) → warp to the tree → F1 back to magics."""
        self._press_assigned_skill("mother_tree")
        if self.humanize:
            hz.sleep_range(hz.ESCAPE_WAIT, self._rng)
        else:
            time.sleep(0.4)
        self.select_skill_box(sb.START_BOX, force=True)

    def _hp_to_mp(self) -> None:
        """Box 2 F7: convert full HP into MP at the Mother Tree, then F1."""
        self._press_assigned_skill("hp_to_mp")
        self.select_skill_box(sb.START_BOX, force=True)

    def _shop_ui_wait(self) -> None:
        """Shop window settle. Always sleep — Practice uses time.sleep too."""
        time.sleep(hz.SHOP_BUTTON_WAIT_S)

    def _shop_stop(self) -> None:
        """Esc cancels the post-scroll auto-walk (Practice uses 0.25s)."""
        self.keyboard.press("esc")
        time.sleep(0.25)

    def _dismiss_level_up(self) -> None:
        """Two Esc taps close the level-up congratulations window."""
        gap = (
            hz.uniform(hz.LEVEL_UP_ESC_GAP, self._rng)
            if self.humanize
            else 0.15
        )
        self.keyboard.tap("esc", count=2, interval=gap)

    def _gate(
        self,
        action: ActionIntent,
        game_state: WorldState,
        bounds: WindowBounds,
    ) -> None:
        """Map-gate cursor probe + click; land check via MapSubsystem pose."""
        from app._04_decision.world_nav.gate import run_gate_click
        from app._04_decision.world_nav.session import live_pose_from_state
        from app.bot_log import get_logger

        entrance = getattr(action, "gate_entrance", None)
        expect_map = getattr(action, "gate_expect_map_id", None)
        expect_xy = getattr(action, "gate_expect_xy", None)
        if (
            not isinstance(entrance, tuple)
            or len(entrance) != 2
            or expect_map is None
        ):
            self.result.gate_error = "gate intent incomplete"
            return

        def _read() -> tuple[int, int, int] | None:
            pose = live_pose_from_state(game_state, fresh=False)
            if pose is None:
                return None
            return int(pose.map_id), int(pose.x), int(pose.y)

        def _read_fresh() -> tuple[int, int, int] | None:
            pose = live_pose_from_state(game_state, fresh=True)
            if pose is None:
                return None
            return int(pose.map_id), int(pose.x), int(pose.y)

        pose = _read()
        if pose is None:
            self.result.gate_error = "no pose for gate"
            return
        land = (
            (int(expect_xy[0]), int(expect_xy[1]))
            if isinstance(expect_xy, tuple) and len(expect_xy) == 2
            else None
        )
        ok, msg = run_gate_click(
            actions=self,
            bounds=bounds,
            entrance_abs=(int(entrance[0]), int(entrance[1])),
            pose_abs=(pose[1], pose[2]),
            expect_map_id=int(expect_map),
            expect_xy=land,
            read_pose=_read,
            read_pose_fresh=_read_fresh,
            log=lambda s: get_logger("nav").info("%s", s),
        )
        live = _read_fresh() if ok else _read()
        if live is None and ok:
            live = _read()
        self.result.gate_ok = bool(ok)
        self.result.gate_error = "" if ok else (msg or "gate fail")
        self.result.gate_pose = live

    def _shop_run(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Execute SHOP_RUN via shop product module (Intent carries kind/qty)."""
        from shop.runtime import execute_shop_intent

        ok, behavior_id = execute_shop_intent(self, bounds, action)
        if not ok:
            return
        self.result.shop_ok = True
        self.result.shop_behavior_id = str(behavior_id or "")
        equip = str(getattr(action, "shop_equip", None) or "").strip().lower()
        if equip in ("silver", "normal"):
            self._equip_bought_arrows(equip)

    def _equip_bought_arrows(self, kind: str) -> None:
        """Press the bought arrow stack on the F-key bar (Intent ``shop_equip``)."""
        from hotbar.inspect import hotbar_arrow_slot

        slot = hotbar_arrow_slot(getattr(self, "hotbar_layout", None), kind)
        if slot is None:
            return
        box, key = slot
        self._shop_ui_wait()
        self._press_box_skill(box, key)

    def _respawn(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Click the death-screen restart control (content UV, no aim jitter)."""
        if action.destination is None:
            return
        # Exact UV already includes ±10px jitter from decision; do not add more.
        x, y = game_to_screen(action.destination.x, action.destination.y, bounds)
        self.mouse.move_and_click(x, y)
