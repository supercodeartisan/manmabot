"""Converts decisions into actual game actions (Lineage_bot ActionExecutor port)."""
from __future__ import annotations

import math
import random
import time
from typing import Optional

from app._01_capture.window_bounds import WindowBounds
from app._04_decision.types import ActionIntent
from app._03_world import WorldState, CharacterType, ActionType, ObjectType
from app._03_world.battle_area import get_battle_area
from app._05_action import humanize as hz
from app._05_action.combat_strategies import CombatStrategy, combat_strategy_for
from app._05_action.coordinates import game_to_screen
from app._05_action.mouse import MouseController
from app._05_action.keyboard import KeyboardController
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
            enabled=enabled, humanize=humanize, rng=self._rng
        )

        self._act_counter = 0
        self._holding = False
        self._last_mage_cast = 0.0
        self._last_magic_at = 0.0
        self._mage_cast_gap = self._sample_mage_gap()
        self._last_elf_click = 0.0
        self._elf_click_gap = self._sample_elf_gap()
        self._last_loot_click = 0.0
        self._loot_click_gap = self._sample_loot_gap()
        self._stuck_limit = self._sample_stuck_limit(ActionType.IDLE)
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
        self.last_arrow_lack: bool = False
        self.last_shop_buy_ok: bool = False
        self.last_shop_behavior_id: str = ""
        self.hotbar_layout: dict = {}
        self.last_hp_potion_used: bool = False
        self._perception_capture = None
        # Set when a loot click actually lands this execute() call.
        self.last_loot_target_id: Optional[int] = None
        # Box 1 is selected with F1 on the first execute().
        # Every spell/potion press also taps Fi for its box before F5–F12.
        # Slots (box + F5–F12) come from ``spell_box.configure_spell_box``.
        self._skill_box: int = 1
        self._skill_box_ready: bool = False
        # Periodic Esc closes conversation / UI opened by bad clicks.
        # Disabled until vision can detect windows (Esc was canceling walks).
        self._dismiss_ui_enabled = False
        self._last_dismiss_ui = time.time()
        self._dismiss_ui_gap = self._sample_dismiss_ui_gap()

    def set_character(self, character: CharacterType) -> None:
        """Switch class and reload the combat strategy."""
        self.character = character
        self._combat = combat_strategy_for(character)
        self._stuck_limit = self._sample_stuck_limit(self._last_action_type)

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

    def _sample_stuck_limit(self, action_type: ActionType) -> int:
        # SEARCHING / TRAVELING: Decision already throttles clicks via mid_act
        # + leg timers; do not force re-clicks here.
        # Elf/mage combat and loot use wall-clock intervals — no stuck re-engage.
        if action_type in (ActionType.LOOTING, ActionType.PICKUP):
            return 0
        if self.character in (
            CharacterType.KNIGHT,
            CharacterType.ROYAL,
            CharacterType.ELF,
            CharacterType.MAGE,
        ):
            if action_type in (ActionType.COMBAT, ActionType.ATTACK):
                return 0
        base = {
            ActionType.COMBAT: 20,
            ActionType.ATTACK: 20,
        }.get(action_type, 0)
        if base <= 0:
            return 0
        if not self.humanize:
            return base
        return hz.randint(hz.STUCK_TICKS, self._rng)

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

    def execute(
        self,
        game_state: WorldState,
        action: ActionIntent,
        bounds: Optional[WindowBounds] = None,
    ) -> None:
        """Execute action based on current game state."""
        self._world = game_state
        self.last_cast_target_id = None
        self.last_attack_target_id = None
        self.last_loot_target_id = None
        self.last_cursor_reject_reason = None
        self.last_cursor_reject_target_id = None
        self.last_cursor_reject_item_id = None
        self.last_travel_click_relative = None
        self.last_travel_click_failed = False
        self.last_arrow_lack = False
        self.last_shop_buy_ok = False
        self.last_shop_behavior_id = ""
        self.last_hp_potion_used = False
        if bounds is None or not bounds.valid:
            return
        self._ensure_skill_box()
        clicks_before = getattr(self.mouse, "button_events", 0)

        # Close stray NPC/dialog windows from mis-clicks (Esc every 3–5s).
        if action.action not in (
            ActionType.ESCAPE,
            ActionType.TELEPORT,
            ActionType.RETURN_TO_MOTHER_TREE,
            ActionType.HP_TO_MP,
            ActionType.USE_TALKING_SCROLL,
            ActionType.SHOP_BUY_ARROWS,
            ActionType.SHOP_STOP,
            ActionType.DISMISS_LEVEL_UP,
            ActionType.RESPAWN,
        ):
            self._maybe_dismiss_ui()

        # Anti-spam: if same action repeated too long, reset
        if action.action == self._last_action_type:
            self._act_counter += 1
            threshold = self._stuck_limit
            if threshold and self._act_counter >= threshold:
                action.mid_act = False
        else:
            self._act_counter = 0
            action.mid_act = False
            self._stuck_limit = self._sample_stuck_limit(action.action)

        is_combat = action.action in (ActionType.COMBAT, ActionType.ATTACK)
        is_loot = action.action in (ActionType.LOOTING, ActionType.PICKUP)

        # Execute new action
        if not action.mid_act:
            self._act_counter = 0
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

            elif action.action == ActionType.RETREATING:
                self._retreat(action, game_state, bounds)

            elif action.action == ActionType.TRAVELING:
                self._travel(action, bounds)

            elif action.action == ActionType.USE_HP_POTION:
                self._use_hp_potion(action)

            elif action.action == ActionType.USE_MP_POTION:
                self._use_mp_potion()

            elif action.action == ActionType.USE_DEPOISON:
                self._use_depoison()

            elif action.action == ActionType.HEAL:
                self._heal(bounds)

            elif action.action == ActionType.BUFF:
                self._buff(action.reason)

            elif action.action == ActionType.ESCAPE:
                self._escape(action, game_state, bounds)

            elif action.action == ActionType.TELEPORT:
                self._teleport()

            elif action.action == ActionType.RETURN_TO_MOTHER_TREE:
                self._return_to_mother_tree()

            elif action.action == ActionType.HP_TO_MP:
                self._hp_to_mp()

            elif action.action == ActionType.USE_TALKING_SCROLL:
                self._use_talking_scroll(action, bounds)

            elif action.action == ActionType.SHOP_STOP:
                self._shop_stop()

            elif action.action == ActionType.DISMISS_LEVEL_UP:
                self._dismiss_level_up()

            elif action.action == ActionType.SHOP_BUY_ARROWS:
                self._shop_buy_arrows(action, bounds)

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

        self._maybe_init_skill_box(clicks_before)
        self._last_action_type = action.action

    def _maybe_dismiss_ui(self) -> None:
        """Tap Esc on a jittered 3–5s cadence to close conversation/UI popups.

        No-op until window detection exists (``_dismiss_ui_enabled``).
        """
        if not self._dismiss_ui_enabled:
            return
        now = time.time()
        if now - self._last_dismiss_ui < self._dismiss_ui_gap:
            return
        self.keyboard.press("esc")
        self._last_dismiss_ui = now
        self._dismiss_ui_gap = self._sample_dismiss_ui_gap()

    def _get_stuck_threshold(self, action_type: ActionType) -> int:
        """Consecutive same-action ticks before a forced re-click.

        SEARCHING / TRAVELING have no threshold: the decision module already
        throttles those clicks (mid_act + leg timers), so the controller must not
        force extra clicks or jitter the destination.
        """
        return self._sample_stuck_limit(action_type)

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
        from app._03_world.objects import Position

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
        from app._05_action.cursor_verify import travel_click
        from app._05_action.travel_click import (
            content_destinations_ring,
            relative_tile_of_content,
        )

        dests = list(content_destinations_ring(action.destination))
        for content in dests:
            x, y = self._screen_point(content.x, content.y, bounds)
            if travel_click(self, x, y):
                self.last_travel_click_relative = relative_tile_of_content(content)
                return
        self.last_travel_click_failed = True

    def _retreat(
        self,
        action: ActionIntent,
        game_state: WorldState,
        bounds: WindowBounds,
    ) -> None:
        """Click away from enemy; require NORMAL cursor (skip dialog / NPC)."""
        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            return

        ex = target.position.x
        ey = target.position.y

        # Vector pointing away from enemy (enemy -> player anchor, then extended)
        anchor = get_battle_area().player_position
        dx = anchor.x - ex
        dy = anchor.y - ey

        length = math.sqrt(dx * dx + dy * dy)
        offset = random.uniform(0.1, 0.15)  # normalized

        if length > 0:
            dx = dx / length * offset + random.uniform(-0.03, 0.03)
            dy = dy / length * offset + random.uniform(-0.03, 0.03)
        else:
            dx = offset + random.uniform(-0.03, 0.03)
            dy = random.uniform(-0.03, 0.03)

        dest = get_battle_area().clamp(ex + dx, ey + dy)
        from app._05_action.cursor_verify import travel_click
        from app._05_action.travel_click import (
            content_destinations_ring,
            relative_tile_of_content,
        )

        for content in content_destinations_ring(dest):
            x, y = self._screen_point(content.x, content.y, bounds)
            if travel_click(self, x, y):
                self.last_travel_click_relative = relative_tile_of_content(content)
                return
        self.last_travel_click_failed = True

    def _loot(
        self,
        action: ActionIntent,
        game_state: WorldState,
        bounds: WindowBounds,
    ) -> None:
        """Click the pile UV and memory cell only. Neighbor NORMAL clicks walk."""
        from app._05_action.cursor_verify import (
            loot_click_search,
            object_loot_screen_points,
        )

        now = time.time()
        if now - self._last_loot_click < self._loot_click_gap:
            return

        target = game_state.get_object(action.target_id) if action.target_id else None
        if target is None:
            return
        missing = getattr(game_state, "missing_frames", None)
        if callable(missing) and int(missing(target.track_id) or 0) >= 1:
            return

        x, y = self._screen_point(target.position.x, target.position.y, bounds)
        points = object_loot_screen_points(self, target, bounds)
        if not points:
            points = [(x, y)]
        if not loot_click_search(self, points):
            self.last_cursor_reject_item_id = action.target_id
            return  # verify failed — skip click only
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
        """Prefer the live hotbar cell for this role; Setup slot if unread."""
        snap = getattr(getattr(self, "_world", None), "last_hotbar", None)
        slots = snap.get("slots") if isinstance(snap, dict) else None
        if isinstance(slots, list) and slots:
            from manmabot_v1.hotbar.inspect import find_role_on_hotbar

            found = find_role_on_hotbar(snap, name)
            if found is None:
                return None, ""
            return found
        return sb.slot_press(name)

    def _press_assigned_skill(self, name: str, duration: float | None = None) -> None:
        if not sb.slot_is_enabled(name):
            return
        if sb.slot_is_magic(name) and name not in ("teleport", "mother_tree"):
            from app._04_decision.mode_control import mp_ratio
            from app._04_decision.spells import SPELL_MANA_RESERVE_RATIO, can_cast_spell

            world = getattr(self, "_world", None)
            if world is not None:
                # Heal may fire while MP is still unknown. Known MP at/below
                # the reserve is kept for teleport.
                if name == "heal":
                    ratio = mp_ratio(world)
                    if ratio is not None and ratio <= SPELL_MANA_RESERVE_RATIO:
                        return
                elif not can_cast_spell(world):
                    return
        if sb.slot_is_magic(name):
            wait = sb.MAGIC_COOLDOWN_S - (time.time() - self._last_magic_at)
            if self._last_magic_at > 0 and wait > 0:
                time.sleep(wait)
        box, key = self._live_or_assigned_slot(name)
        if box is None or not key:
            return
        self._press_box_skill(box, key, duration=duration)
        if sb.slot_is_double(name):
            if self.humanize:
                hz.sleep_range(hz.HEAL_DOUBLE_GAP, self._rng)
            else:
                time.sleep(0.05)
            self.keyboard.press(key)
        if sb.slot_is_magic(name):
            now = time.time()
            self._last_magic_at = now
            if name == "mage_attack":
                self._last_mage_cast = now

    def _heal(self, bounds: WindowBounds) -> None:
        """Self-heal: press (or double-press) the live hotbar key. No click."""
        del bounds
        self._press_assigned_skill("heal")

    def _buff(self, which: str) -> None:
        """Self buff: power-up / armor / light at the assigned slot."""
        name = str(which or "")
        if name not in ("power_up", "armor_up", "light"):
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
        self.select_skill_box(int(box), force=True)
        self._fixed_wait(hz.TALKING_SCROLL_BOX_S)
        self.keyboard.press(str(key))
        self._fixed_wait(hz.TALKING_SCROLL_KEY_S)
        click_bounds = bounds
        capture = getattr(self, "_perception_capture", None)
        if capture is not None:
            try:
                from manmabot_v1.perception_capture import grab_perception_frame

                grab_perception_frame(capture, retries=8, wait_s=0.05)
            except Exception:
                pass
            fresh = getattr(capture, "content_bounds", None)
            if fresh is not None and getattr(fresh, "valid", False):
                click_bounds = fresh
        x, y = game_to_screen(action.destination.x, action.destination.y, click_bounds)
        self.mouse.move_and_click(x, y, snap=True)
        self._fixed_wait(hz.TALKING_SCROLL_AFTER_CLICK_S)
        self.select_skill_box(sb.START_BOX, force=True)
        if self._talking_scroll_is_shop(action):
            self._fixed_wait(hz.TALKING_SCROLL_SHOP_WAIT_S)

    @staticmethod
    def _talking_scroll_is_shop(action) -> bool:
        """True for shop hops (shops.yaml *or* calibrated behavior scroll rows).

        ``maps/shops.yaml`` only lists Talking Island. Mainland Giran rows
        must still get the 2s land-settle wait that Practice always uses.
        """
        reason = str(getattr(action, "reason", "") or "").lower()
        if "shop" in reason:
            return True
        dest = getattr(action, "destination", None)
        if dest is None:
            return False
        from app._04_decision.shops import get_shops
        from app._04_decision.talking_scroll import click_uv_for_id

        for shop in get_shops():
            uv = shop.scroll_click_uv()
            if uv is not None and uv.x == dest.x and uv.y == dest.y:
                return True
        try:
            from manmabot_v1.shopping.behaviors import load_behaviors

            for behavior in load_behaviors():
                spot = str(getattr(behavior, "scroll_spot", "") or "")
                uv = click_uv_for_id(spot) if spot else None
                if uv is not None and uv.x == dest.x and uv.y == dest.y:
                    return True
        except Exception:
            return False
        return False

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

    @staticmethod
    def _adena_from_world(world: object | None) -> int | None:
        player = getattr(world, "player", None) if world is not None else None
        inv = getattr(player, "inventory", None) if player is not None else None
        if inv is None or not bool(getattr(inv, "bag_ready", False)):
            return None
        try:
            return max(0, int(getattr(inv, "adena", 0) or 0))
        except (TypeError, ValueError):
            return None

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

    def _shop_buy_arrows(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Run calibrated shopping behavior, or recover stub for arrows."""
        from app._04_decision.shops import (
            ARROW_BUY_QTY,
            SHOP_NPC_SEARCH_PX,
            SILVER_ARROW_BUY_QTY,
            shop_ui_clicks,
        )
        from app._05_action.cursor_verify import dialog_click_ring

        self.last_shop_buy_ok = False
        self.last_shop_behavior_id = ""
        if action.destination is None:
            return

        behavior_id = str(getattr(action, "shop_behavior_id", None) or "").strip()
        if behavior_id:
            ok = self._shop_run_behavior(action, bounds, behavior_id)
            if ok:
                self.last_shop_buy_ok = True
                self.last_shop_behavior_id = behavior_id
                self._equip_bought_arrows(behavior_id)
            elif "arrow" in behavior_id:
                # Calibrated buy failed → recover hardcoded arrow UI.
                self._shop_buy_arrows_recover(action, bounds)
            return

        self._shop_buy_arrows_recover(action, bounds)

    def _shop_run_behavior(
        self, action: ActionIntent, bounds: WindowBounds, behavior_id: str
    ) -> bool:
        from manmabot_v1.shopping.runtime import (
            execute_calibrated_buy,
            execute_calibrated_sell,
            open_shop_npc,
            player_origin_from_executor,
            resolve_behavior,
        )

        behavior = resolve_behavior(behavior_id)
        if behavior is None:
            return False
        if not behavior.ui.calibrated(action=behavior.action):
            return False

        if behavior.action == "sell":
            capture = getattr(self, "_perception_capture", None)
            if capture is None:
                return False

            def _grab():
                from manmabot_v1.perception_capture import grab_perception_frame

                return grab_perception_frame(capture, retries=15, wait_s=0.05)

            return execute_calibrated_sell(
                self,
                bounds,
                behavior,
                grab_frame=_grab,
                npc_uv=action.destination,
            )

        from app._04_decision.shops import (
            HP_POTION_BUY_QTY,
            affordable_hp_potion_qty,
            buy_qty_for_behavior,
            is_hp_potion_behavior,
        )

        qty = buy_qty_for_behavior(behavior_id)
        if is_hp_potion_behavior(behavior_id):
            qty = affordable_hp_potion_qty(
                qty if qty is not None else HP_POTION_BUY_QTY,
                self._adena_from_world(getattr(self, "_world", None)),
            )
            if qty < 1:
                # Cannot afford one potion — end the trip instead of typing 0.
                return True

        # Same NPC open as Start Shopping Practice (catalog UV + 20px ring).
        if not open_shop_npc(self, bounds, behavior, player_origin_from_executor(self)):
            return False
        return execute_calibrated_buy(self, bounds, behavior, qty=qty)

    def _shop_buy_arrows_recover(
        self, action: ActionIntent, bounds: WindowBounds
    ) -> None:
        """Legacy hardcoded buy-arrows UI (worse-case recover stub)."""
        from app._04_decision.shops import (
            ARROW_BUY_QTY,
            SHOP_NPC_SEARCH_PX,
            shop_ui_clicks,
        )
        from app._05_action.cursor_verify import dialog_click_ring

        self.last_shop_buy_ok = False
        if action.destination is None:
            return
        if not dialog_click_ring(
            self,
            action.destination,
            lambda u, v: self._screen_point(u, v, bounds),
            radius_px=SHOP_NPC_SEARCH_PX,
            step_s=hz.SHOP_NPC_SEARCH_STEP_S,
        ):
            return
        time.sleep(hz.SHOP_AFTER_NPC_WAIT_S)

        clicks = shop_ui_clicks()
        sx, sy = game_to_screen(clicks.buy_tab.x, clicks.buy_tab.y, bounds)
        self.mouse.move_and_click(sx, sy, snap=True)
        time.sleep(hz.SHOP_AFTER_TAB_WAIT_S)
        sx, sy = game_to_screen(clicks.arrow_row.x, clicks.arrow_row.y, bounds)
        self.mouse.move_and_click(sx, sy, snap=True)
        self._shop_ui_wait()

        qty = max(1, min(999, int(ARROW_BUY_QTY)))
        self.keyboard.tap("backspace", count=3)
        for digit in str(qty):
            self.keyboard.press(digit)
        self._shop_ui_wait()

        confirm = clicks.confirm
        cx, cy = game_to_screen(confirm.x, confirm.y, bounds)
        self.mouse.move_and_click(cx, cy, snap=True)
        self._shop_ui_wait()
        self.last_shop_buy_ok = True
        self.last_shop_behavior_id = ""
        self._equip_bought_arrows("normal_arrows")

    def _equip_bought_arrows(self, behavior_id: str) -> None:
        """Press the bought arrow stack on the F-key bar so it becomes the active ammo.

        Silver buy turns that stack on (and off normal). Normal buy does the reverse.
        """
        bid = str(behavior_id or "").lower()
        if "silver" in bid:
            kind = "silver"
        elif "arrow" in bid or bid == "":
            kind = "normal"
        else:
            return
        from manmabot_v1.hotbar.inspect import hotbar_arrow_slot

        slot = hotbar_arrow_slot(getattr(self, "hotbar_layout", None), kind)
        if slot is None:
            return
        box, key = slot
        self._shop_ui_wait()
        self._press_box_skill(box, key)

    def _escape(
        self,
        action: ActionIntent,
        game_state: WorldState,
        bounds: WindowBounds,
    ) -> None:
        """Emergency escape — teleport, then optional run-away click."""
        self._press_assigned_skill("teleport")
        if self.humanize:
            hz.sleep_range(hz.ESCAPE_WAIT, self._rng)
        else:
            time.sleep(0.5)
        if game_state.player:
            x = game_state.player.position.x + random.uniform(-0.2, 0.2)
            y = game_state.player.position.y + random.uniform(-0.2, 0.2)
            dest = get_battle_area().clamp(x, y)
            sx, sy = self._screen_point(dest.x, dest.y, bounds)
            self.mouse.move_and_click(sx, sy)

    def _respawn(self, action: ActionIntent, bounds: WindowBounds) -> None:
        """Click the death-screen restart control (content UV, no aim jitter)."""
        if action.destination is None:
            return
        # Exact UV already includes ±10px jitter from decision; do not add more.
        x, y = game_to_screen(action.destination.x, action.destination.y, bounds)
        self.mouse.move_and_click(x, y)

    _last_action_type: ActionType = ActionType.IDLE
