"""Standalone dungeon combat GUI — dungeon floors, patrol edit, Home/End.

Combat-only session: reuses BotController + dungeon farming, but does not
change the main schedule/operator pipeline. While this tool is running:

- talking-scroll hunt / respawn return is disabled; shop trip + return allowed
- HP order: items + heal + teleport by user %/order
- teleport re-fires on a −5% ladder until HP recovers above the user base %
- at HP ≤ 30%: world tree (if available) then wait HP/MP full → always potion
  shop; else shop directly when potion restock is due (≤30% gate only)
- bag HP-potion ≤ Return limit does NOT open shop by itself (arrows/sell OK)
- talking scroll for HP escape is OFF (shop scroll paths stay on)
- movement / combat unstick is disabled
- if origin is on a blocked map tile: click nearest walkable (r=2..3) only
- if ActionType.IDLE lasts ≥1.5s on a walkable tile: same nearby walkable clicks
  (shop trip / retreat / world-tree stand skipped)
- 13s / 3-tile confined escape teleport is disabled
- no teleport→talking-scroll escalate after a TP hop

Hotkeys: Home = start, End = stop.

Launch::

    python run.py --dungeon-combat
"""
from __future__ import annotations

import importlib
import json
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Optional

from PIL import Image, ImageDraw, ImageTk

from common.bootstrap import bootstrap
from dungeon.dungeon_combat_maps import (
    CombatMapEntry,
    discover_combat_maps,
    filter_combat_maps,
)
from session.bot_controller import BotController, RunState
from settings.dungeon_assets import (
    load_pack_meta,
    pack_dir_for,
    save_patrol_overlay,
)
from settings.hp_actions import (
    DEFAULT_INPLACE_PCT,
    DEFAULT_RETREAT_PCT,
    canonical_action_id,
    inventory_item_key_for_hp_action,
    is_item_action,
    item_action_id,
    item_key_from_action,
)
from session.paths import USERDATA, ensure_userdata, map_overlay_slug
from session.probes import list_patrol_entries
from settings.profile import Profile, load_profile
from i18n.strings import (
    LANG_EN,
    LANGUAGE_CHOICES,
    normalize_language,
)
from ui.design_system import (
    BG,
    BORDER,
    FONT_BODY,
    FONT_SECTION,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    apply_classic_style,
)

HP_SETTINGS_PATH = USERDATA / "dungeon_combat_hp.json"
UI_SETTINGS_PATH = USERDATA / "dungeon_combat_ui.json"
LOOT_MODE_ALL = "all_items"
LOOT_MODE_ADENA = "adena_only"
_LOOT_MODES = frozenset({LOOT_MODE_ALL, LOOT_MODE_ADENA})
_HP_LABELS = {
    "heal": "Heal skill",
    "teleport": "Teleport (−5% ladder after each use)",
    "safe_zone": "Talking scroll (HP escape OFF)",
    "mother_tree": "World Tree (≤30% + potion restock)",
}
_DUNGEON_TREE_SHOP_RATIO = 0.30
_DUNGEON_TP_STEP = 0.05

# Prefer familiar starter floors when present; else first discovered pack.
_DEFAULT_MAP_IDS: tuple[str, ...] = (
    "talking_island_dungeon_F1",
    "gludio_dungeon_F1",
    "giran_dungeon_F1",
)

# Always skip in this tool (merged into the session blacklist).
_DUNGEON_SKIP_SPECIES: tuple[str, ...] = (
    "monster_돌 골렘",
    "monster_아이스 골렘",
    "monster_아이언 골렘",
    "monster_라바 골렘",
    "monster_괴물 눈",
    "괴물 눈",
    "괴물눈",
)
_DUNGEON_SKIP_NEEDLES: tuple[str, ...] = ("골렘", "괴물눈")

_ZOOM_MIN = 0.5
_ZOOM_MAX = 16.0
_HIT_R = 6
_START_HOTKEY = "home"
_STOP_HOTKEY = "end"


def _dungeon_skip_species() -> list[str]:
    """Catalog keys / aliases for 골렘* and 괴물눈."""
    keys = list(_DUNGEON_SKIP_SPECIES)
    try:
        from app._03_world.catalog.game_catalog import list_monster_rows

        for row in list_monster_rows():
            compact = "".join(str(row.name_ko or "").split()).lower()
            if any(needle in compact for needle in _DUNGEON_SKIP_NEEDLES):
                keys.append(row.key)
    except Exception:
        pass
    return list(dict.fromkeys(keys))

# (module, attr, factory) — factory builds the replacement callable.
# Shop trip + post-shop return stay live. Hunt-map / respawn scrolls stay off.
_PATCH_SPECS: tuple[tuple[str, str, str], ...] = (
    ("app._04_decision.behaviors.mode_ticks", "_maybe_scroll_to_hunt_map", "none"),
    ("app._04_decision.behaviors.mode_ticks", "_maybe_post_respawn_spellbook", "none"),
    # 3-tile / 13 s pocket TP — dungeon combat only; main Manmabot unchanged.
    ("app._04_decision.behaviors.mode_ticks", "_maybe_confined_escape", "none"),
    ("app._04_decision.behaviors.unstick", "try_confined_escape", "false"),
    ("app._04_decision.behaviors.unstick", "try_movement_unstick", "false"),
    ("app._04_decision.behaviors.unstick", "try_combat_blocked_unstick", "false"),
    ("app._04_decision.behaviors.travel", "try_movement_unstick", "false"),
    ("app._04_decision.behaviors.search_hop", "try_movement_unstick", "false"),
    ("app._04_decision.behaviors.mode_actions", "try_combat_blocked_unstick", "false"),
    # After TP, main bot may escalate to talking scroll — block in dungeon only.
    ("app._04_decision.behaviors.mode_actions", "maybe_escalate_teleport_to_safe", "false"),
    ("app._04_decision.behaviors.mode_ticks", "maybe_escalate_teleport_to_safe", "false"),
    # HP escape talking-scroll fallback (keep shop scroll elsewhere).
    ("app._04_decision.behaviors.mode_actions", "arm_hp_escape_fallback", "none"),
)

# Catalog key is 빨간 물약; 상쾌한 빨간 물약 is a live/event alias only.
# Dungeon HP order does NOT seed any potion row — users add from the bag.
_HP_LOG_THROTTLE_S = 1.0
_hp_log_last: dict[str, float] = {}
# Current teleport gate after a cast; None means use the user-configured base %.
_tp_step_gate: Optional[float] = None
_DUNGEON_SKILL_DEFAULTS: tuple[tuple[str, bool, int], ...] = (
    ("heal", True, DEFAULT_INPLACE_PCT),
    ("teleport", True, DEFAULT_RETREAT_PCT),
    ("mother_tree", True, 30),
)


def _dungeon_hp_log(message: str, *, key: str = "", throttle_s: float = 0.0) -> None:
    """Realtime HP diagnostics → session UI log + hp logger."""
    text = f"[던전HP] {message}"
    if throttle_s > 0 and key:
        now = time.time()
        prev = float(_hp_log_last.get(key, 0.0) or 0.0)
        if now - prev < float(throttle_s):
            return
        _hp_log_last[key] = now
    try:
        from app.bot_log import get_logger

        get_logger("hp").info("%s", text)
    except Exception:
        pass


def _dungeon_hp_ratio_pct(state: Any) -> str:
    try:
        from app._04_decision.mode_control import hp_ratio, mp_ratio

        hp = hp_ratio(state)
        mp = mp_ratio(state)
    except Exception:
        return "HP=? MP=?"
    hp_s = "?" if hp is None else f"{hp * 100.0:.1f}%"
    mp_s = "?" if mp is None else f"{mp * 100.0:.1f}%"
    return f"HP={hp_s} MP={mp_s}"


def _dungeon_recover_detail(state: Any) -> str:
    """Why heal / potions are usable or not (for live debug)."""
    try:
        from app._04_decision.behaviors import mode_actions as ma
        from app._04_decision.hp_actions import hp_item_keys
    except Exception as exc:
        return f"recover=? ({exc})"
    heal_ok = False
    heal_why = "n/a"
    try:
        heal_ok = bool(ma._can_heal_now(state))
        if heal_ok:
            heal_why = "ok"
        elif ma.heal_blocked_by_mana(state):
            heal_why = "mp_blocked"
        else:
            heal_why = "unavailable"
    except Exception as exc:
        heal_why = f"err:{exc}"
    potion_bits: list[str] = []
    try:
        keys = list(hp_item_keys() or ()) or ["빨간 물약"]
        for key in keys:
            try:
                count = ma._hp_item_count(state, key)
            except Exception:
                count = None
            ready = False
            try:
                ready = bool(ma._can_item_now(state, key))
            except Exception:
                ready = False
            potion_bits.append(f"{key}:count={count}:ready={int(ready)}")
    except Exception as exc:
        potion_bits.append(f"items_err:{exc}")
    recover = False
    try:
        recover = bool(ma.can_active_hp_recover(state))
    except Exception:
        recover = bool(heal_ok)
    return (
        f"recover={int(recover)} heal={int(heal_ok)}({heal_why}) "
        + " ".join(potion_bits)
    )


def _reset_dungeon_tp_ladder() -> None:
    global _tp_step_gate
    _tp_step_gate = None


def _teleport_base_ratio(actions: list | None = None) -> Optional[float]:
    try:
        from app._04_decision import player_mode as pm
        from app._04_decision.hp_actions import action_threshold, normalize_hp_actions

        rows = actions if actions is not None else (pm.HP_ACTIONS or normalize_hp_actions(None))
        return action_threshold(rows, "teleport")
    except Exception:
        return None


def _sync_tp_ladder(ratio: Optional[float], actions: list | None = None) -> Optional[float]:
    """Reset ladder when HP recovers above user base; return current gate."""
    global _tp_step_gate
    base = _teleport_base_ratio(actions)
    if ratio is None or base is None:
        return _tp_step_gate if _tp_step_gate is not None else base
    if ratio > base:
        if _tp_step_gate is not None:
            _dungeon_hp_log(
                f"TP 계단 리셋: HP={ratio * 100.0:.1f}% > 설정 {base * 100.0:.0f}%",
                key="tp_reset",
                throttle_s=_HP_LOG_THROTTLE_S,
            )
        _tp_step_gate = None
        return base
    return _tp_step_gate if _tp_step_gate is not None else base


def _step_tp_ladder_after_cast(actions: list | None = None) -> None:
    global _tp_step_gate
    base = _teleport_base_ratio(actions)
    if base is None:
        return
    current = _tp_step_gate if _tp_step_gate is not None else base
    nxt = max(0.05, round(float(current) - _DUNGEON_TP_STEP, 2))
    _tp_step_gate = nxt
    _dungeon_hp_log(
        f"TP 계단: 다음 게이트 {nxt * 100.0:.0f}% (이전 {current * 100.0:.0f}%)"
    )


def _dungeon_potion_restock_needed(state: Any, blackboard: Any) -> bool:
    """True when Fix/Return-style potion restock is due (same as main shop)."""
    try:
        from app._04_decision import shops as shops_mod
        from app._04_decision.shop_trip import needs_potion_restock
    except Exception:
        return False
    if not bool(getattr(shops_mod, "RESTOCK_POTIONS", False)):
        return False
    if bool(getattr(blackboard, "needs_potion", False)):
        return needs_potion_restock(blackboard)
    # Arm from live counts when threshold is known.
    try:
        from app._04_decision.behaviors.mode_actions import _hp_potion_count

        count = _hp_potion_count(state)
    except Exception:
        count = None
    if count is None:
        return needs_potion_restock(blackboard)
    limit = int(getattr(shops_mod, "RETURN_POTION_COUNT", 20) or 0)
    if bool(getattr(shops_mod, "RETURN_POTION_ENABLED", True)) and count <= limit:
        blackboard.needs_potion = True
        return needs_potion_restock(blackboard)
    return False


def _mother_tree_row_enabled(actions: list | None = None) -> bool:
    try:
        from app._04_decision import player_mode as pm
        from app._04_decision.hp_actions import normalize_hp_actions
        from app._04_decision.behaviors.mode_actions import _hp_action_enabled

        rows = actions if actions is not None else (pm.HP_ACTIONS or normalize_hp_actions(None))
        return bool(_hp_action_enabled(rows, "mother_tree"))
    except Exception:
        return False


# When memory origin sits on a blocked PNG tile, A* cannot start → idle.
# Dungeon-only: click nearest walkable (r=2 then 3). No TP / scroll escape.
# Also: continuous ActionType.IDLE ≥1.5s on a walkable tile → same nearby clicks.
_SCRATCH_BLOCKED_ORIGIN = "dungeon_blocked_origin"
_SCRATCH_BLOCKED_TRIED = "dungeon_blocked_tried"
_SCRATCH_BLOCKED_CLICK_AT = "dungeon_blocked_click_at"
_SCRATCH_IDLE_SINCE = "dungeon_idle_since"
_SCRATCH_IDLE_NUDGE_ORIGIN = "dungeon_idle_nudge_origin"
_SCRATCH_IDLE_NUDGE_TRIED = "dungeon_idle_nudge_tried"
_SCRATCH_IDLE_NUDGE_CLICK_AT = "dungeon_idle_nudge_click_at"
# Armed by HP≤30% shop / post-world-tree shop so farm-tick shop_trip may run
# even while inventory Return-limit potion trips stay suppressed.
_SCRATCH_DUNGEON_POTION_SHOP = "dungeon_allow_potion_shop"
_DUNGEON_BLOCKED_RADII = (2, 3)
_DUNGEON_BLOCKED_GAP_S = 0.5
# Session panel + long-idle walk nudge share this threshold.
_LONG_IDLE_S = 1.5


def _arm_dungeon_potion_shop(blackboard: Any) -> None:
    """Allow potion shop_trip from farm ticks (UI NPC + buy qty)."""
    blackboard.needs_potion = True
    blackboard.scratch[_SCRATCH_DUNGEON_POTION_SHOP] = True


def _clear_dungeon_idle_nudge(blackboard: Any) -> None:
    blackboard.scratch.pop(_SCRATCH_IDLE_SINCE, None)
    blackboard.scratch.pop(_SCRATCH_IDLE_NUDGE_ORIGIN, None)
    blackboard.scratch.pop(_SCRATCH_IDLE_NUDGE_TRIED, None)
    blackboard.scratch.pop(_SCRATCH_IDLE_NUDGE_CLICK_AT, None)


def _dungeon_pick_walkable_neighbor(
    terrain: Any,
    origin: tuple[int, int],
    tried: set[tuple[int, int]],
    *,
    radii: tuple[int, ...] | None = None,
) -> tuple[int, int] | None:
    """Next walkable tile in radii (default r=2..3), cycling tried when exhausted."""
    from app._04_decision.behaviors.unstick import walkable_around

    use_radii = radii if radii is not None else _DUNGEON_BLOCKED_RADII
    candidates: list[tuple[int, int]] = []
    for radius in use_radii:
        for tile in walkable_around(terrain, origin, radius):
            if tile not in tried and tile not in candidates:
                candidates.append(tile)
    if not candidates:
        tried.clear()
        for radius in use_radii:
            for tile in walkable_around(terrain, origin, radius):
                if tile not in candidates:
                    candidates.append(tile)
    return candidates[0] if candidates else None


def _emit_dungeon_walkable_step(
    blackboard: Any,
    *,
    origin: tuple[int, int],
    tile: tuple[int, int],
    goal: str,
    reason: str,
    log_tag: str,
) -> Any:
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.pathfinding import waypoint_to_content

    content = waypoint_to_content(tile, blackboard.world_origin)
    blackboard.current_goal = goal
    blackboard.nav_waypoint = tile
    blackboard.emit(
        ActionType.TRAVELING,
        destination=content,
        priority=0.7,
        reason=reason,
        mid_act=False,
    )
    try:
        from app.bot_log import event

        event("travel", "%s origin=%s -> %s", log_tag, origin, tile)
    except Exception:
        pass
    return Status.SUCCESS


def _try_dungeon_blocked_step(blackboard: Any) -> Any:
    """If on a blocked tile, emit one walk click to a nearby walkable cell."""
    import time

    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.nav_config import get_terrain_map

    terrain = get_terrain_map()
    if terrain is None:
        return None
    try:
        ox = int(blackboard.world_origin.x)
        oy = int(blackboard.world_origin.y)
    except Exception:
        return None
    origin = (ox, oy)
    if terrain.is_walkable(ox, oy):
        blackboard.scratch.pop(_SCRATCH_BLOCKED_ORIGIN, None)
        blackboard.scratch.pop(_SCRATCH_BLOCKED_TRIED, None)
        blackboard.scratch.pop(_SCRATCH_BLOCKED_CLICK_AT, None)
        return None

    prev = blackboard.scratch.get(_SCRATCH_BLOCKED_ORIGIN)
    if prev is None or tuple(prev) != origin:
        blackboard.scratch[_SCRATCH_BLOCKED_ORIGIN] = list(origin)
        blackboard.scratch[_SCRATCH_BLOCKED_TRIED] = []
        blackboard.scratch.pop(_SCRATCH_BLOCKED_CLICK_AT, None)

    now = time.time()
    last = float(blackboard.scratch.get(_SCRATCH_BLOCKED_CLICK_AT) or 0.0)
    if last > 0.0 and (now - last) < _DUNGEON_BLOCKED_GAP_S:
        blackboard.current_goal = "blocked_step"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.55,
            reason=f"blocked tile ({ox},{oy}), waiting next walkable click",
        )
        return Status.SUCCESS

    tried = {tuple(item) for item in (blackboard.scratch.get(_SCRATCH_BLOCKED_TRIED) or [])}
    tile = _dungeon_pick_walkable_neighbor(terrain, origin, tried)
    if tile is None:
        blackboard.current_goal = "blocked_step"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.4,
            reason=f"blocked tile ({ox},{oy}), no walkable neighbor r<=3",
        )
        try:
            blackboard.note_no_intent(
                f"blocked tile ({ox},{oy}), no walkable in r=2..3"
            )
        except Exception:
            pass
        return Status.SUCCESS

    tried.add(tile)
    blackboard.scratch[_SCRATCH_BLOCKED_TRIED] = [list(item) for item in tried]
    blackboard.scratch[_SCRATCH_BLOCKED_CLICK_AT] = now
    return _emit_dungeon_walkable_step(
        blackboard,
        origin=origin,
        tile=tile,
        goal="blocked_step",
        reason=f"blocked tile ({ox},{oy}) -> walkable {tile}",
        log_tag="dungeon blocked step",
    )


def _try_dungeon_long_idle_step(blackboard: Any) -> Any:
    """After continuous no-intent / IDLE ≥1.5s, click a nearby walkable.

    ``DecisionManager`` synthesizes ``reason=no intent | …`` only *after*
    ``tick_mode`` returns with ``intent is None``. Treat None like that IDLE
    so the nudge can run before the fallback is built.
    """
    import time

    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

    intent = getattr(blackboard, "intent", None)
    action = getattr(intent, "action", None) if intent is not None else None
    reason = str(getattr(intent, "reason", "") or "") if intent is not None else ""
    # Primary stuck case: mode tick returned without emit → manager "no intent".
    is_no_intent = intent is None or reason.startswith("no intent")
    is_idle = action is ActionType.IDLE
    if not (is_no_intent or is_idle):
        _clear_dungeon_idle_nudge(blackboard)
        return None

    # Do not nudge off shop landing / HP retreat stands.
    if blackboard.player_mode is PlayerMode.RETREATING:
        _clear_dungeon_idle_nudge(blackboard)
        return None
    if blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        return None
    if blackboard.scratch.get("mother_tree_trip"):
        return None

    now = time.time()
    since = blackboard.scratch.get(_SCRATCH_IDLE_SINCE)
    if since is None:
        blackboard.scratch[_SCRATCH_IDLE_SINCE] = now
        return None
    if (now - float(since)) < _LONG_IDLE_S:
        return None

    terrain = get_terrain_map()
    if terrain is None:
        return None
    try:
        ox = int(blackboard.world_origin.x)
        oy = int(blackboard.world_origin.y)
    except Exception:
        return None
    origin = (ox, oy)
    # Blocked tiles are handled immediately by ``_try_dungeon_blocked_step``.
    if not terrain.is_walkable(ox, oy):
        return None

    prev = blackboard.scratch.get(_SCRATCH_IDLE_NUDGE_ORIGIN)
    if prev is None or tuple(prev) != origin:
        blackboard.scratch[_SCRATCH_IDLE_NUDGE_ORIGIN] = list(origin)
        blackboard.scratch[_SCRATCH_IDLE_NUDGE_TRIED] = []
        blackboard.scratch.pop(_SCRATCH_IDLE_NUDGE_CLICK_AT, None)

    tag = "no intent" if is_no_intent else "long idle"
    last = float(blackboard.scratch.get(_SCRATCH_IDLE_NUDGE_CLICK_AT) or 0.0)
    if last > 0.0 and (now - last) < _DUNGEON_BLOCKED_GAP_S:
        blackboard.current_goal = "idle_nudge"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.55,
            reason=f"{tag} at ({ox},{oy}), waiting next walkable click",
        )
        return Status.SUCCESS

    tried = {
        tuple(item) for item in (blackboard.scratch.get(_SCRATCH_IDLE_NUDGE_TRIED) or [])
    }
    # No-intent escape: search a bit farther (still no TP/scroll).
    radii = (2, 3, 4, 5) if is_no_intent else _DUNGEON_BLOCKED_RADII
    tile = _dungeon_pick_walkable_neighbor(terrain, origin, tried, radii=radii)
    if tile is None:
        blackboard.current_goal = "idle_nudge"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.4,
            reason=f"{tag} at ({ox},{oy}), no walkable neighbor r<={radii[-1]}",
        )
        try:
            blackboard.note_no_intent(
                f"{tag} ({ox},{oy}), no walkable in r=2..{radii[-1]}"
            )
        except Exception:
            pass
        return Status.SUCCESS

    tried.add(tile)
    blackboard.scratch[_SCRATCH_IDLE_NUDGE_TRIED] = [list(item) for item in tried]
    blackboard.scratch[_SCRATCH_IDLE_NUDGE_CLICK_AT] = now
    # Keep idle clock so we keep nudging until a real non-idle intent wins.
    return _emit_dungeon_walkable_step(
        blackboard,
        origin=origin,
        tile=tile,
        goal="idle_nudge",
        reason=f"{tag} ({ox},{oy}) -> walkable {tile}",
        log_tag=f"dungeon {tag} nudge",
    )


def _install_dungeon_hp_policy(saved: list[tuple[Any, str, Any]]) -> None:
    """Dungeon HP: TP ladder, ≤30% tree/shop; HP-escape talking scroll OFF."""
    import app._04_decision.behaviors.mode_actions as mode_actions
    import app._04_decision.behaviors.mode_ticks as mode_ticks

    global _tp_step_gate
    _tp_step_gate = None

    orig_avail = mode_actions._hp_action_availability
    orig_execute = mode_actions._execute_hp_action
    orig_apply = mode_actions.apply_hp_actions
    orig_inplace = mode_actions.apply_inplace_hp_support
    orig_tree = mode_ticks._tick_mother_tree_retreat
    orig_retreat_scroll = mode_ticks._maybe_retreat_talking_scroll
    orig_maybe_shop = mode_ticks._maybe_shop_trip

    def _maybe_shop(state: Any, blackboard: Any) -> Any:
        """No inventory Return-limit potion shop; mid-trip / arrows / sell stay.

        Post-world-tree and HP≤30% paths arm ``dungeon_allow_potion_shop`` so
        farm ticks can continue ``tick_shop_trip`` (UI NPC + buy qty). Bag-count
        alone still cannot open the potion shop.
        """
        from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

        mid = bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))
        armed = bool(blackboard.scratch.get(_SCRATCH_DUNGEON_POTION_SHOP))
        saved: bool | None = None
        if not mid and not armed:
            saved = bool(getattr(blackboard, "needs_potion", False))
            blackboard.needs_potion = False
        try:
            return orig_maybe_shop(state, blackboard)
        finally:
            if saved is not None:
                blackboard.needs_potion = saved
            # Drop the arm once buy finished and no trip is in progress.
            if (
                armed
                and not bool(getattr(blackboard, "needs_potion", False))
                and not bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))
            ):
                blackboard.scratch.pop(_SCRATCH_DUNGEON_POTION_SHOP, None)

    def _avail(state: Any, blackboard: Any, *, retreat_starters: bool = False) -> dict:
        from app._04_decision import player_mode as pm
        from app._04_decision.hp_actions import normalize_hp_actions
        from app._04_decision.mode_control import hp_ratio

        can = orig_avail(state, blackboard, retreat_starters=retreat_starters)
        # HP-escape talking scroll is fully off in dungeon combat.
        can["safe_zone"] = False
        actions = pm.HP_ACTIONS or normalize_hp_actions(None)
        ratio = hp_ratio(state)
        gate = _sync_tp_ladder(ratio, actions)
        if (
            ratio is not None
            and gate is not None
            and ratio > gate
            and can.get("teleport")
        ):
            can["teleport"] = False
        # World tree row % ignored — fixed ≤30% + potion restock + elf.
        if retreat_starters:
            try:
                from app._04_decision.mode_control import elf_uses_mother_tree

                tree_ok = (
                    ratio is not None
                    and ratio <= _DUNGEON_TREE_SHOP_RATIO
                    and _mother_tree_row_enabled(actions)
                    and elf_uses_mother_tree(state, blackboard)
                    and _dungeon_potion_restock_needed(state, blackboard)
                )
                can["mother_tree"] = bool(tree_ok)
            except Exception:
                can["mother_tree"] = False
        try:
            recover = bool(mode_actions.can_active_hp_recover(state))
        except Exception:
            recover = True
        _dungeon_hp_log(
            f"가용성 {_dungeon_hp_ratio_pct(state)} "
            f"heal={int(bool(can.get('heal')))} "
            f"teleport={int(bool(can.get('teleport')))} "
            f"gate={('?' if gate is None else f'{gate * 100.0:.0f}%')} "
            f"tree={int(bool(can.get('mother_tree')))} "
            f"potion={int(bool(can.get('hp_potion')))} "
            f"scroll_hp=OFF recover={int(recover)} "
            f"{_dungeon_recover_detail(state)}",
            key="avail",
            throttle_s=_HP_LOG_THROTTLE_S,
        )
        return can

    def _execute(action_id: str, state: Any, blackboard: Any) -> Any:
        from app._04_decision.behaviors.mode_actions import HP_RETREAT_STARTED
        from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat

        key = str(action_id or "")
        situation = f"{_dungeon_hp_ratio_pct(state)} {_dungeon_recover_detail(state)}"
        if key == "teleport":
            ok = begin_retreat(
                blackboard,
                reason=RETREAT_FOR_HP,
                teleport=True,
                use_mother_tree=False,
                walk_to_safe=False,
            )
            if ok:
                blackboard.scratch["hp_retreat_kind"] = "teleport"
                _step_tp_ladder_after_cast()
                _dungeon_hp_log(f"실행 OK action=teleport → 후퇴시작 | {situation}")
                return HP_RETREAT_STARTED
            _dungeon_hp_log(f"실행실패 action=teleport (begin_retreat 거부) | {situation}")
            return None
        if key == "safe_zone":
            _dungeon_hp_log(
                f"실행차단 action=safe_zone (던전 HP탈출 스크롤 OFF) | {situation}",
                key="safe_zone_off",
                throttle_s=_HP_LOG_THROTTLE_S,
            )
            return None
        result = orig_execute(action_id, state, blackboard)
        label = "없음"
        try:
            from app._04_decision.behavior_tree import Status as _Status

            if result is _Status.FAILURE:
                label = "FAILURE"
            elif result is _Status.SUCCESS:
                label = "SUCCESS"
            elif result is not None:
                label = "OK"
        except Exception:
            label = "OK" if result is not None else "없음"
        _dungeon_hp_log(
            f"실행 {label} action={key} result={result!r} | {situation}"
        )
        return result

    def _force(
        state: Any, blackboard: Any, ratio: float, actions: list, can: dict
    ) -> Any:
        del state, blackboard, ratio, actions, can
        _dungeon_hp_log(
            "자동스크롤 차단: 던전 HP탈출 토킹스크롤 OFF (상점 스크롤은 유지)",
            key="force_off",
            throttle_s=_HP_LOG_THROTTLE_S,
        )
        return None

    def _retreat_scroll(blackboard: Any) -> Any:
        """Block HP-safe / spellbook retreat scrolls; leave other purposes alone."""
        from app._04_decision.talking_scroll import (
            HP_SAFE_SCROLL_PURPOSE,
            PURPOSE_SPELLBOOK,
            SCRATCH_RETREAT_SCROLL,
        )

        purpose = str(blackboard.scratch.get(SCRATCH_RETREAT_SCROLL) or "")
        if purpose in {HP_SAFE_SCROLL_PURPOSE, PURPOSE_SPELLBOOK, "safe", "spellbook"}:
            blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
            _dungeon_hp_log(
                f"후퇴스크롤 차단: HP탈출 purpose={purpose or '-'} OFF",
                key="retreat_scroll_off",
                throttle_s=_HP_LOG_THROTTLE_S,
            )
            return None
        return orig_retreat_scroll(blackboard)

    def _try_tree_or_shop(state: Any, blackboard: Any, ratio: float) -> Any:
        from app._04_decision.behaviors.mode_actions import HP_RETREAT_STARTED
        from app._04_decision.mode_control import (
            RETREAT_FOR_HP,
            begin_retreat,
            elf_uses_mother_tree,
        )

        if ratio > _DUNGEON_TREE_SHOP_RATIO:
            return None
        if not _dungeon_potion_restock_needed(state, blackboard):
            return None
        situation = f"{_dungeon_hp_ratio_pct(state)} {_dungeon_recover_detail(state)}"
        if _mother_tree_row_enabled() and elf_uses_mother_tree(state, blackboard):
            if begin_retreat(
                blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True
            ):
                blackboard.scratch["hp_retreat_kind"] = "mother_tree"
                _dungeon_hp_log(
                    f"HP≤30% + 물약보충 → 월드트리 | {situation}"
                )
                return HP_RETREAT_STARTED
        blackboard.needs_potion = True
        _arm_dungeon_potion_shop(blackboard)
        _dungeon_hp_log(
            f"HP≤30% + 물약보충 → 상점 출동(월드트리 불가) | {situation}"
        )
        try:
            from app._04_decision.behavior_tree import Status
            from app._04_decision.shop_trip import tick_shop_trip

            shop = tick_shop_trip(state, blackboard)
            if shop is not None:
                return shop
            # Armed for shop — do not fall through to TP/heal retreat this tick.
            try:
                blackboard.note_no_intent(
                    "dungeon HP≤30% shop armed but tick_shop_trip idle"
                )
            except Exception:
                pass
            return Status.SUCCESS
        except Exception as exc:
            _dungeon_hp_log(f"상점 출동 실패: {exc}")
            return None

    def _apply(state: Any, blackboard: Any) -> Any:
        from app._04_decision.mode_control import hp_ratio

        situation = f"{_dungeon_hp_ratio_pct(state)} {_dungeon_recover_detail(state)}"
        try:
            ratio = hp_ratio(state)
            spike = bool(mode_actions.hp_spike_drop(blackboard)) and bool(
                mode_actions._combat_hp_threat(state, blackboard)
            )
        except Exception:
            ratio = None
            spike = False
        _sync_tp_ladder(ratio)
        if ratio is not None:
            early = _try_tree_or_shop(state, blackboard, ratio)
            if early is not None:
                return early
        if ratio is not None and (spike or ratio <= 0.55):
            _dungeon_hp_log(
                f"apply 진입 spike={int(spike)} ratio="
                f"{'?' if ratio is None else f'{ratio * 100.0:.1f}%'} | {situation}",
                key="apply_enter",
                throttle_s=_HP_LOG_THROTTLE_S,
            )
        result = orig_apply(state, blackboard)
        if result is not None:
            _dungeon_hp_log(f"apply 결과 result={result!r} | {situation}")
        return result

    def _inplace(
        state: Any,
        blackboard: Any,
        *,
        until_ratio: float | None = None,
    ) -> Any:
        from app._04_decision.mode_control import hp_ratio

        _sync_tp_ladder(hp_ratio(state))
        situation = f"{_dungeon_hp_ratio_pct(state)} {_dungeon_recover_detail(state)}"
        result = orig_inplace(state, blackboard, until_ratio=until_ratio)
        if result is not None:
            _dungeon_hp_log(f"후퇴중 HP지원 결과 result={result!r} | {situation}")
        return result

    def _tree_tick(state: Any, blackboard: Any) -> Any:
        from app._04_decision.behavior_tree import Status
        from app._04_decision.mode_control import finish_retreat, vitals_full_at_mother_tree

        stage = blackboard.scratch.get("mother_tree_trip")
        if stage == "recharge" and vitals_full_at_mother_tree(state):
            # B: after HP/MP full at the tree, always open the potion shop
            # (same wait-then-shop pattern as main; dungeon uses potion NPC).
            finish_retreat(blackboard)
            _arm_dungeon_potion_shop(blackboard)
            _dungeon_hp_log(
                "월드트리 회복완료(HP/MP풀) → 물약 상점 출동 "
                "(UI Shop NPC + Buy qty)"
            )
            try:
                from app._04_decision.shop_trip import tick_shop_trip

                shop = tick_shop_trip(state, blackboard)
                if shop is not None:
                    return shop
            except Exception as exc:
                _dungeon_hp_log(f"상점 시작 실패: {exc}")
            return Status.FAILURE
        return orig_tree(state, blackboard)

    orig_tick_mode = mode_ticks.tick_mode

    def _tick_mode(state: Any, blackboard: Any) -> Any:
        # Death first (same as tick_mode). Then step off blocked tiles so
        # A* idle from an unwalkable origin cannot starve the tick.
        try:
            death = mode_ticks._maybe_death(state, blackboard)
            if death is not None:
                return death
        except Exception:
            pass
        try:
            dungeon_death = mode_ticks._maybe_dungeon_death(state, blackboard)
            if dungeon_death is not None:
                return dungeon_death
        except Exception:
            pass
        early = _try_dungeon_blocked_step(blackboard)
        if early is not None:
            return early
        result = orig_tick_mode(state, blackboard)
        nudge = _try_dungeon_long_idle_step(blackboard)
        if nudge is not None:
            return nudge
        return result

    for mod, attr, replacement in (
        (mode_actions, "_hp_action_availability", _avail),
        (mode_actions, "_execute_hp_action", _execute),
        (mode_actions, "_force_safe_scroll_if_due", _force),
        (mode_actions, "apply_hp_actions", _apply),
        (mode_actions, "apply_inplace_hp_support", _inplace),
        (mode_ticks, "_tick_mother_tree_retreat", _tree_tick),
        (mode_ticks, "_maybe_retreat_talking_scroll", _retreat_scroll),
        (mode_ticks, "_maybe_shop_trip", _maybe_shop),
        (mode_ticks, "tick_mode", _tick_mode),
    ):
        saved.append((mod, attr, getattr(mod, attr)))
        setattr(mod, attr, replacement)

    # DecisionManager does ``from …mode_ticks import tick_mode`` — a module-local
    # binding — so patching mode_ticks.tick_mode alone never reaches decide().
    import app._04_decision.manager as decision_manager

    if getattr(decision_manager, "tick_mode", None) is not _tick_mode:
        saved.append(
            (decision_manager, "tick_mode", getattr(decision_manager, "tick_mode"))
        )
        setattr(decision_manager, "tick_mode", _tick_mode)


def _hp_action_label(action_id: str) -> str:
    key = str(action_id or "").strip()
    if key in _HP_LABELS:
        return _HP_LABELS[key]
    if is_item_action(key):
        return item_key_from_action(key) or key
    return key or "—"


def _clamp_hp_pct(raw: Any, fallback: int) -> int:
    try:
        return max(5, min(95, int(raw)))
    except (TypeError, ValueError):
        return max(5, min(95, int(fallback)))


def _dungeon_skill_base() -> dict[str, dict[str, Any]]:
    return {
        action_id: {
            "id": action_id,
            "enabled": enabled,
            "hp_below": pct,
        }
        for action_id, enabled, pct in _DUNGEON_SKILL_DEFAULTS
    }


def _finalize_dungeon_hp_actions(raw: Any) -> list[dict[str, Any]]:
    """Dungeon HP rows: skills by default; item rows only if present in ``raw``.

    Does not auto-seed 빨간 물약 / 상쾌한 빨간 물약. If the user adds a
    restore item from the bag (any live name), that ``item:*`` row is kept.
    HP-escape talking scroll (``safe_zone``) is omitted.
    """
    by_id = _dungeon_skill_base()
    ordered: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = canonical_action_id(str(item.get("id") or "").strip())
            if not key or key in ordered:
                continue
            if is_item_action(key):
                item_key = item_key_from_action(key)
                if not item_key:
                    continue
                by_id[key] = {
                    "id": item_action_id(item_key),
                    "enabled": bool(item.get("enabled", True)),
                    "hp_below": _clamp_hp_pct(
                        item.get("hp_below"), DEFAULT_INPLACE_PCT
                    ),
                }
                ordered.append(by_id[key]["id"])
                continue
            if key not in by_id:
                continue
            row = by_id[key]
            if "enabled" in item:
                row["enabled"] = bool(item["enabled"])
            if "hp_below" in item:
                row["hp_below"] = _clamp_hp_pct(item.get("hp_below"), row["hp_below"])
            ordered.append(key)
    if not ordered:
        ordered = [action_id for action_id, _, _ in _DUNGEON_SKILL_DEFAULTS]
    else:
        for action_id, _, _ in _DUNGEON_SKILL_DEFAULTS:
            if action_id not in ordered:
                ordered.append(action_id)
    # Drop HP-escape talking scroll from dungeon settings (UI + runtime list).
    ordered = [key for key in ordered if key != "safe_zone"]
    by_id.pop("safe_zone", None)
    return [dict(by_id[key]) for key in ordered if key in by_id]


def _visible_dungeon_hp_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """HP recovery UI rows. Talking-scroll escape is not shown (always OFF)."""
    return [
        dict(row)
        for row in actions
        if str(row.get("id") or "") != "safe_zone"
    ]


def _read_dungeon_settings() -> dict[str, Any]:
    path = Path(HP_SETTINGS_PATH)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_loot_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in _LOOT_MODES else LOOT_MODE_ALL


def _read_ui_settings() -> dict[str, Any]:
    path = Path(UI_SETTINGS_PATH)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_ui_settings(*, language: str, last_map_id: str = "") -> None:
    ensure_userdata()
    data = _read_ui_settings()
    data["language"] = normalize_language(language)
    mid = str(last_map_id or data.get("last_map_id") or "").strip()
    if mid:
        data["last_map_id"] = mid
    Path(UI_SETTINGS_PATH).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_ui_language() -> str:
    return normalize_language(str(_read_ui_settings().get("language") or LANG_EN))


def _load_last_map_id(maps: tuple[CombatMapEntry, ...]) -> str:
    prefer = str(_read_ui_settings().get("last_map_id") or "").strip()
    ids = {m.pack_id for m in maps}
    if prefer in ids:
        return prefer
    for mid in _DEFAULT_MAP_IDS:
        if mid in ids:
            return mid
    return maps[0].pack_id if maps else ""


def _load_dungeon_loot_mode() -> str:
    data = _read_dungeon_settings()
    if "loot_mode" in data:
        return _normalize_loot_mode(data.get("loot_mode"))
    return LOOT_MODE_ALL


def _load_dungeon_hp_actions() -> list[dict[str, Any]]:
    """Load dungeon HP order; never inherit profile's default red-water row.

    One-time migration: if saved settings still have the old seeded potion and
    ``potion_default_cleared`` is not set, drop that seed row so the UI matches
    the new default. User bag-adds after that are kept normally.
    """
    data = _read_dungeon_settings()
    raw: Any = data.get("hp_actions") if data else None
    cleared = bool(data.get("potion_default_cleared")) if data else False
    if isinstance(raw, list) and not cleared:
        seed_ids = {
            "hp_potion",
            "item:빨간 물약",
            "item:상쾌한 빨간 물약",
        }
        stripped = [
            row
            for row in raw
            if isinstance(row, dict)
            and canonical_action_id(str(row.get("id") or "")) not in seed_ids
        ]
        actions = _finalize_dungeon_hp_actions(stripped)
        try:
            _save_dungeon_settings(
                actions,
                loot_mode=_normalize_loot_mode(
                    (data or {}).get("loot_mode", LOOT_MODE_ALL)
                ),
                shop=_normalize_dungeon_shop((data or {}).get("shop")),
            )
        except Exception:
            pass
        return actions
    return _finalize_dungeon_hp_actions(raw)


def _default_dungeon_shop() -> dict[str, Any]:
    try:
        profile = load_profile()
    except Exception:
        profile = None
    return {
        "restock_potions": bool(
            getattr(profile, "restock_potions", True) if profile else True
        ),
        "return_potion_count": int(
            getattr(profile, "return_potion_count", 20) if profile else 20
        ),
        "hp_potion_buy_qty": int(
            getattr(profile, "hp_potion_buy_qty", 100) if profile else 100
        ),
        "hp_potion_npc": str(
            getattr(profile, "hp_potion_npc", "") if profile else ""
        ).strip(),
    }


def _normalize_dungeon_shop(raw: Any) -> dict[str, Any]:
    base = _default_dungeon_shop()
    data = raw if isinstance(raw, dict) else {}
    try:
        count = max(0, min(999, int(data.get("return_potion_count", base["return_potion_count"]))))
    except (TypeError, ValueError):
        count = int(base["return_potion_count"])
    try:
        qty = max(1, min(999, int(data.get("hp_potion_buy_qty", base["hp_potion_buy_qty"]))))
    except (TypeError, ValueError):
        qty = int(base["hp_potion_buy_qty"])
    return {
        "restock_potions": bool(data.get("restock_potions", base["restock_potions"])),
        "return_potion_count": count,
        "hp_potion_buy_qty": qty,
        "hp_potion_npc": str(data.get("hp_potion_npc", base["hp_potion_npc"]) or "").strip(),
    }


def _load_dungeon_shop() -> dict[str, Any]:
    data = _read_dungeon_settings()
    return _normalize_dungeon_shop(data.get("shop") if data else None)


def _shop_npc_choices(language: str | None = None) -> list[str]:
    try:
        from app._04_decision.talking_scroll import ROWS
        from i18n.localized_names import scroll_label_display
    except Exception:
        return []
    lang = language
    if not lang:
        try:
            lang = str(getattr(load_profile(), "game_language", "ko") or "ko")
        except Exception:
            lang = "ko"
    region = ""
    choices: list[str] = []
    for spot in ROWS:
        kind = spot.get("kind")
        if kind == "header" and spot.get("region") not in ("title", "favorites"):
            region = scroll_label_display(str(spot.get("label") or ""), lang)
            continue
        if kind != "spot" or "shop" not in (spot.get("roles") or ()):
            continue
        label = scroll_label_display(str(spot.get("label") or ""), lang)
        choices.append(f"{region} / {label}" if region else label)
    return choices


def _save_dungeon_settings(
    actions: list[dict[str, Any]],
    *,
    loot_mode: str = LOOT_MODE_ALL,
    shop: dict[str, Any] | None = None,
) -> None:
    ensure_userdata()
    prev = _read_dungeon_settings()
    payload = {
        "hp_actions": _finalize_dungeon_hp_actions(actions),
        "loot_mode": _normalize_loot_mode(loot_mode),
        "shop": _normalize_dungeon_shop(
            shop if shop is not None else (prev.get("shop") if prev else None)
        ),
        "potion_default_cleared": True,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    Path(HP_SETTINGS_PATH).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _save_dungeon_hp_actions(actions: list[dict[str, Any]]) -> None:
    loot_mode = _load_dungeon_loot_mode()
    _save_dungeon_settings(actions, loot_mode=loot_mode, shop=_load_dungeon_shop())


def _noop_none(*_a: Any, **_k: Any) -> None:
    return None


def _noop_false(*_a: Any, **_k: Any) -> bool:
    return False


def _replacement(kind: str) -> Callable[..., Any]:
    if kind == "none":
        return _noop_none
    return _noop_false


def _tile_px(pixel_scale: int, zoom: float) -> float:
    return max(1.0, float(max(1, int(pixel_scale))) * float(zoom))


def _tile_center_px(
    tx: int, ty: int, *, pixel_scale: int, zoom: float
) -> tuple[float, float]:
    side = _tile_px(pixel_scale, zoom)
    return (tx + 0.5) * side, (ty + 0.5) * side


def _tile_box(
    tx: int, ty: int, *, pixel_scale: int, zoom: float
) -> list[float]:
    side = _tile_px(pixel_scale, zoom)
    x0 = tx * side
    y0 = ty * side
    return [x0, y0, x0 + side, y0 + side]


def _draw_tile_dot(
    draw: ImageDraw.ImageDraw,
    tx: int,
    ty: int,
    fill: tuple[int, int, int, int],
    *,
    pixel_scale: int,
    zoom: float,
    selected: bool = False,
) -> tuple[float, float, float]:
    box = _tile_box(tx, ty, pixel_scale=pixel_scale, zoom=zoom)
    alpha = int(fill[3]) if len(fill) > 3 else 255
    side = _tile_px(pixel_scale, zoom)
    edge = max(1, int(round(side * 0.18)))
    draw.rectangle(box, fill=fill, outline=(0, 0, 0, alpha), width=edge)
    if selected:
        inset = max(1.0, side * 0.18)
        draw.rectangle(
            [box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset],
            outline=(255, 255, 0, alpha),
            width=max(1, edge),
        )
    cx, cy = _tile_center_px(tx, ty, pixel_scale=pixel_scale, zoom=zoom)
    return cx, cy, side * 0.5


def _draw_label(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    fill: tuple[int, int, int, int],
) -> None:
    if not text:
        return
    alpha = int(fill[3]) if len(fill) > 3 else 255
    halo = (0, 0, 0, alpha)
    for dx, dy in (
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (1, -1),
        (-1, 1),
        (1, 1),
    ):
        draw.text((x + dx, y + dy), text, fill=halo)
    draw.text((x, y), text, fill=fill)


def _draw_label_lines(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    lines: list[str],
    fill: tuple[int, int, int, int],
    *,
    line_h: float = 12.0,
) -> None:
    for i, line in enumerate(lines):
        if line:
            _draw_label(draw, x, y + i * line_h, line, fill)


def _resolve_entity_display(
    kind: str,
    raw_name: str,
    *,
    detail: Any = None,
) -> tuple[str, Optional[int]]:
    """English display name + monster level (None when not a leveled monster)."""
    from app._03_world.constants import monster_level_for_object
    from i18n.localized_names import (
        item_catalog_display_name,
        memory_name_for_ui,
        species_display_name_ui,
    )

    raw = str(raw_name or "").strip() or "—"
    level: Optional[int] = None
    if kind == "monster":
        try:
            level = monster_level_for_object(raw, detail)
        except Exception:
            level = None
        try:
            name_en = species_display_name_ui(raw, "en") or raw
        except Exception:
            name_en = raw
    elif kind == "item":
        try:
            name_en = (
                item_catalog_display_name(raw, "en")
                or memory_name_for_ui(raw, "en")
                or raw
            )
        except Exception:
            name_en = raw
    else:
        try:
            name_en = memory_name_for_ui(raw, "en") or raw
        except Exception:
            name_en = raw
    # Default PIL bitmap font is Latin-only; keep ASCII fallbacks readable.
    try:
        name_en.encode("ascii")
    except UnicodeEncodeError:
        name_en = name_en.encode("ascii", "replace").decode("ascii")
    return str(name_en or "—").strip() or "—", level


def _entity_label_lines(ent: dict[str, Any]) -> list[str]:
    kind = str(ent.get("kind") or "other").strip().lower() or "other"
    name = str(ent.get("name_en") or ent.get("name") or "—").strip() or "—"
    lines = [kind, name]
    if kind == "monster":
        level = ent.get("level")
        if level is not None:
            try:
                lines.append(f"lv{int(level)}")
            except (TypeError, ValueError):
                pass
    eng = str(ent.get("engagement") or "").strip()
    if eng.startswith("path>") or eng in ("no", "blacklist") or eng.startswith(
        "give-up"
    ):
        lines.append(eng)
    return lines


_ENTITY_KINDS: tuple[str, ...] = ("monster", "npc", "player", "item", "other")


def _compose_map_frame(
    *,
    base: Image.Image,
    zoom: float,
    pixel_scale: int,
    show_path: bool,
    show_entities: bool,
    show_self: bool,
    entity_kinds: set[str],
    patrol: list[tuple[int, int, str]],
    paths: list[list[tuple[int, int]]],
    selected: Optional[int],
    player_tile: Optional[tuple[int, int]],
    entities: list[dict[str, Any]],
) -> Image.Image:
    """CPU-heavy map compose — safe to run off the Tk thread."""
    iw, ih = base.size
    dw = max(1, int(round(iw * zoom)))
    dh = max(1, int(round(ih * zoom)))
    shown = base.resize((dw, dh), Image.Resampling.NEAREST)
    overlay = Image.new("RGBA", shown.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    side = _tile_px(pixel_scale, zoom)
    if show_path:
        path_w = max(2, int(round(side * 0.35)))
        for path in paths:
            if len(path) < 2:
                continue
            pts = [
                _tile_center_px(tx, ty, pixel_scale=pixel_scale, zoom=zoom)
                for tx, ty in path
            ]
            draw.line(pts, fill=(0, 0, 0, 220), width=path_w + 2)
            draw.line(pts, fill=(0, 180, 255, 255), width=path_w)
        for i, (tx, ty, _name) in enumerate(patrol):
            fill = (255, 140, 0, 255) if selected == i else (255, 220, 0, 255)
            cx, cy, half = _draw_tile_dot(
                draw,
                tx,
                ty,
                fill,
                pixel_scale=pixel_scale,
                zoom=zoom,
                selected=selected == i,
            )
            _draw_label(draw, cx + half + 2, cy - half, str(i + 1), (255, 240, 0, 255))
    else:
        for i, (tx, ty, _name) in enumerate(patrol):
            fill = (255, 140, 0, 70) if selected == i else (255, 220, 0, 55)
            cx, cy, half = _draw_tile_dot(
                draw,
                tx,
                ty,
                fill,
                pixel_scale=pixel_scale,
                zoom=zoom,
                selected=selected == i,
            )
            _draw_label(draw, cx + half + 2, cy - half, str(i + 1), (255, 240, 0, 80))
    if show_entities:
        if show_self and player_tile is not None:
            cx, cy, half = _draw_tile_dot(
                draw,
                player_tile[0],
                player_tile[1],
                (255, 0, 220, 255),
                pixel_scale=pixel_scale,
                zoom=zoom,
            )
            _draw_label(draw, cx + half + 2, cy - half, "you", (255, 80, 255, 255))
        for ent in entities:
            tx, ty = int(ent["tx"]), int(ent["ty"])
            kind = str(ent.get("kind") or "other")
            if kind not in entity_kinds:
                continue
            eng = str(ent.get("engagement") or "—")
            if (
                eng.startswith("give-up")
                or eng == "blacklist"
                or eng.startswith("path>")
            ):
                fill = (140, 140, 140, 255)
                label_fill = (220, 220, 220, 255)
            elif eng == "engaged":
                fill = (255, 0, 0, 255)
                label_fill = (255, 60, 60, 255)
            elif kind == "monster" and eng == "yes":
                fill = (0, 220, 0, 255)
                label_fill = (40, 255, 40, 255)
            elif kind == "monster":
                fill = (255, 120, 0, 255)
                label_fill = (255, 160, 40, 255)
            elif kind == "item":
                fill = (0, 120, 255, 255)
                label_fill = (80, 180, 255, 255)
            elif kind == "player":
                fill = (255, 255, 0, 255)
                label_fill = (255, 255, 80, 255)
            else:
                fill = (180, 0, 255, 255)
                label_fill = (220, 120, 255, 255)
            cx, cy, half = _draw_tile_dot(
                draw, tx, ty, fill, pixel_scale=pixel_scale, zoom=zoom
            )
            _draw_label_lines(
                draw,
                cx + half + 2,
                cy - half,
                _entity_label_lines(ent),
                label_fill,
            )
    return Image.alpha_composite(shown.convert("RGBA"), overlay)


def _ids_equal(a: Any, b: Any) -> bool:
    if a is None or b is None or a == "" or b == "":
        return False
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _path_skip_by_id(decision: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = decision.get("path_cap_skips") or []
    by_id: dict[int, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return by_id
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            by_id[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return by_id


def _engagement_label(
    *,
    kind: str,
    oid: Any,
    tile: tuple[int, int],
    player: tuple[int, int],
    target_id: Any,
    item_id: Any,
    terrain: Any,
    give_up_by_id: dict[int, dict[str, Any]],
    blacklist_ids: set[int],
    path_skip_by_id: dict[int, dict[str, Any]] | None = None,
) -> str:
    try:
        oid_i = int(oid)
    except (TypeError, ValueError):
        oid_i = None
    if oid_i is not None and oid_i in blacklist_ids:
        return "blacklist"
    if oid_i is not None and oid_i in give_up_by_id:
        remain = give_up_by_id[oid_i].get("remain_ticks")
        return f"give-up:{remain}" if remain is not None else "give-up"
    if kind == "monster" and _ids_equal(oid, target_id):
        return "engaged"
    if kind == "item" and _ids_equal(oid, item_id):
        return "loot"
    if oid_i is not None and path_skip_by_id and oid_i in path_skip_by_id:
        row = path_skip_by_id[oid_i]
        reason = str(row.get("reason") or "").strip()
        if reason:
            return reason
        try:
            from app._04_decision.combat_query import path_cap_skip_reason

            return path_cap_skip_reason(
                row.get("steps"),
                limit=int(row.get("limit") or 30),
            )
        except Exception:
            return "path>30"
    if kind not in ("monster", "item"):
        return kind if kind in ("player", "npc") else "—"
    if terrain is None:
        return "yes" if kind == "monster" else kind
    from app._04_decision.dungeon import is_dungeon_map, line_of_sight_clear

    if is_dungeon_map():
        try:
            from app._04_decision import player_mode as pm
            from app._04_decision.combat_query import path_cap_skip_reason
            from app._04_decision.pathfinding import find_path

            limit = int(
                pm.DUNGEON_LOOT_MAX_PATH_TILES
                if kind == "item"
                else pm.DUNGEON_ENGAGE_MAX_PATH_TILES
            )
            chev = max(abs(player[0] - tile[0]), abs(player[1] - tile[1]))
            if chev > 1:
                path = find_path(terrain, player, tile)
                if not path:
                    return path_cap_skip_reason(None, limit=limit)
                steps = max(0, len(path) - 1)
                if steps > limit:
                    return path_cap_skip_reason(steps, limit=limit)
        except Exception:
            pass
    if kind == "item":
        return "item"
    return "yes" if line_of_sight_clear(terrain, player, tile) else "no"


def _parse_skip_sets(
    decision: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], set[int]]:
    give_ups = decision.get("give_ups") or []
    by_id: dict[int, dict[str, Any]] = {}
    if isinstance(give_ups, list):
        for row in give_ups:
            if not isinstance(row, dict):
                continue
            try:
                by_id[int(row["id"])] = row
            except (KeyError, TypeError, ValueError):
                continue
    banned: set[int] = set()
    for tid in decision.get("blacklisted_ids") or []:
        try:
            banned.add(int(tid))
        except (TypeError, ValueError):
            continue
    return by_id, banned


def _entities_from_snap(
    snap: dict[str, Any],
    *,
    terrain: Any,
    give_up_by_id: dict[int, dict[str, Any]],
    blacklist_ids: set[int],
) -> tuple[Optional[tuple[int, int]], list[dict[str, Any]]]:
    nav = snap.get("navigation") or {}
    origin_xy = nav.get("origin_xy")
    player: Optional[tuple[int, int]] = None
    if isinstance(origin_xy, (list, tuple)) and len(origin_xy) >= 2:
        try:
            player = (int(origin_xy[0]), int(origin_xy[1]))
        except (TypeError, ValueError):
            player = None
    if player is None:
        return None, []

    decision = snap.get("decision") or {}
    target_id = decision.get("target_id")
    item_id = decision.get("item_id")
    path_skips = _path_skip_by_id(decision)
    from app._03_world.space.world_coords import (
        WorldOrigin,
        content_to_world,
        relative_to_absolute,
    )

    origin = WorldOrigin(x=player[0], y=player[1])
    rows: list[dict[str, Any]] = []
    for obj in list((snap.get("world") or {}).get("objects") or []):
        if not isinstance(obj, dict):
            continue
        kind = str(obj.get("type") or "other").strip().lower()
        if kind == "other":
            continue
        try:
            sx = float(obj.get("x"))
            sy = float(obj.get("y"))
        except (TypeError, ValueError):
            continue
        if not (0.0 <= sx <= 1.0 and 0.0 <= sy <= 1.0):
            continue
        try:
            rel = content_to_world(sx, sy)
            tile = relative_to_absolute(rel.x, rel.y, origin)
        except Exception:
            continue
        if terrain is not None:
            tw, th = terrain.width, terrain.height
            if not (0 <= tile[0] < tw and 0 <= tile[1] < th):
                continue
        oid = obj.get("id")
        name = str(obj.get("name") or "—").strip() or "—"
        detail = obj.get("detail")
        name_en, level = _resolve_entity_display(kind, name, detail=detail)
        eng = _engagement_label(
            kind=kind,
            oid=oid,
            tile=tile,
            player=player,
            target_id=target_id,
            item_id=item_id,
            terrain=terrain,
            give_up_by_id=give_up_by_id,
            blacklist_ids=blacklist_ids,
            path_skip_by_id=path_skips,
        )
        rows.append(
            {
                "id": oid,
                "name": name,
                "name_en": name_en,
                "level": level,
                "kind": kind,
                "tx": tile[0],
                "ty": tile[1],
                "engagement": eng,
            }
        )
    return player, rows


def _entities_from_memory(
    snap: dict[str, Any],
    memory_rows: list[dict[str, Any]],
    *,
    terrain: Any,
    map_origin: tuple[int, int],
) -> tuple[Optional[tuple[int, int]], list[dict[str, Any]]]:
    """Nav tiles from print_state when the bot worker is not running."""
    from app._03_world.merge.memory_sync import game_to_nav, player_game_xy_from_snapshot

    player_xy = player_game_xy_from_snapshot(snap)
    if player_xy is None:
        return None, []
    player = game_to_nav(player_xy[0], player_xy[1], origin=map_origin)
    if terrain is not None:
        tw, th = terrain.width, terrain.height
        if not (0 <= player[0] < tw and 0 <= player[1] < th):
            # Still show entities; player marker may be off-map for wrong floor.
            pass
    rows: list[dict[str, Any]] = []
    for row in memory_rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("classification") or "other").strip().lower()
        if kind not in _ENTITY_KINDS or kind == "other":
            continue
        cx, cy = row.get("world_cx"), row.get("world_cy")
        if cx is None or cy is None:
            continue
        try:
            tile = game_to_nav(int(cx), int(cy), origin=map_origin)
        except (TypeError, ValueError):
            continue
        if terrain is not None:
            tw, th = terrain.width, terrain.height
            if not (0 <= tile[0] < tw and 0 <= tile[1] < th):
                continue
        name = (
            str(
                row.get("species_name")
                or row.get("memory_name")
                or row.get("detail_classification")
                or "—"
            ).strip()
            or "—"
        )
        detail = row.get("detail_classification")
        name_en, level = _resolve_entity_display(kind, name, detail=detail)
        oid = row.get("track_id")
        eng = _engagement_label(
            kind=kind,
            oid=oid,
            tile=tile,
            player=player,
            target_id=None,
            item_id=None,
            terrain=terrain,
            give_up_by_id={},
            blacklist_ids=set(),
        )
        rows.append(
            {
                "id": oid,
                "name": name,
                "name_en": name_en,
                "level": level,
                "kind": kind,
                "tx": tile[0],
                "ty": tile[1],
                "engagement": eng,
            }
        )
    return player, rows


class _IdleWorldFeed:
    """Live print_state poller for map/entity view while the bot is stopped.

    Exclusive with the bot's perception handles — close before start, reopen
    after a full stop.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sweep: Any = None
        self._map_origin: Optional[tuple[int, int]] = None

    def set_map_origin(self, ox: int, oy: int) -> None:
        origin = (int(ox), int(oy))
        with self._lock:
            self._map_origin = origin
        try:
            from app._03_world.merge.memory_sync import configure_map_origin

            configure_map_origin(
                {
                    "navigation": {
                        "map_origin_x": origin[0],
                        "map_origin_y": origin[1],
                    }
                }
            )
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            sweep = self._sweep
            self._sweep = None
        if sweep is None:
            return
        try:
            from app._01_perception.sensors import shared_sensors

            shared_sensors().release_entity_sweep()
        except Exception:
            try:
                sweep.close()
            except Exception:
                pass

    def poll(
        self, terrain: Any
    ) -> tuple[Optional[tuple[int, int]], list[dict[str, Any]]]:
        with self._lock:
            origin = self._map_origin
            if origin is None:
                return None, []
            if self._sweep is None:
                try:
                    from app._01_perception.sensors import shared_sensors

                    self._sweep = shared_sensors().ensure_entity_sweep(
                        log_interval_s=60.0
                    )
                except Exception:
                    return None, []
            sweep = self._sweep
        try:
            snap, memory_rows, _line = sweep.poll()
        except Exception:
            self.close()
            return None, []
        if not isinstance(snap, dict):
            return None, []
        return _entities_from_memory(
            snap,
            list(memory_rows or []),
            terrain=terrain,
            map_origin=origin,
        )


class _CombatPatches:
    """Process-local monkeypatches for this tool only."""

    def __init__(self) -> None:
        self._saved: list[tuple[Any, str, Any]] = []
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def install(self) -> None:
        if self._active:
            return
        for mod_name, attr, kind in _PATCH_SPECS:
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
            if not hasattr(mod, attr):
                continue
            self._saved.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, _replacement(kind))
        try:
            _install_dungeon_hp_policy(self._saved)
        except Exception:
            pass
        self._active = True

    def restore(self) -> None:
        while self._saved:
            mod, attr, original = self._saved.pop()
            try:
                setattr(mod, attr, original)
            except Exception:
                pass
        self._active = False
        _reset_dungeon_tp_ladder()


class DungeonCombatApp(tk.Tk):
    """Dungeon combat lab: pick floor, edit patrol, run combat loop."""

    def __init__(self) -> None:
        super().__init__()
        bootstrap()
        ensure_userdata()
        self.title("Dungeon Combat")
        self.geometry("1180x760")
        self.minsize(920, 600)
        self.configure(bg=BG)
        apply_classic_style(self)

        self._all_maps: tuple[CombatMapEntry, ...] = discover_combat_maps()
        if not self._all_maps:
            messagebox.showerror(
                "Dungeon Combat",
                "No dungeon map packs found under engine/maps.",
            )
            self._all_maps = ()
        self._filtered_maps: tuple[CombatMapEntry, ...] = self._all_maps
        self._ui_lang = _load_ui_language()
        self.map_id = _load_last_map_id(self._all_maps) or (
            self._all_maps[0].pack_id if self._all_maps else ""
        )
        self._base: Optional[Image.Image] = None
        self._terrain = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self.patrol: list[tuple[int, int, str]] = []
        self.paths: list[list[tuple[int, int]]] = []
        self.selected: Optional[int] = None
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._panning = False
        self._pan_start = (0, 0)
        self._pan_origin = [0.0, 0.0]
        self._dragging: Optional[int] = None
        self._dirty = False
        self._pixel_scale = 1
        self._closing = False
        self._hotkey_handles: list[Any] = []
        self._patches = _CombatPatches()
        self._player_tile: Optional[tuple[int, int]] = None
        self._live_entities: list[dict[str, Any]] = []
        self._give_up_by_id: dict[int, dict[str, Any]] = {}
        self._idle_since: Optional[float] = None
        self._long_idle_log_key: str = ""
        self._blacklist_ids: set[int] = set()
        self._last_give_up_key = ""
        self._last_cursor_reject_key = ""
        self._stopping = False
        self._state_lock = threading.Lock()
        self._render_wake = threading.Event()
        self._render_stop = threading.Event()
        self._render_out_lock = threading.Lock()
        self._render_frame: Optional[dict[str, Any]] = None
        self._render_status: Optional[dict[str, Any]] = None
        self._render_thread: Optional[threading.Thread] = None
        self._ui_lock = threading.Lock()
        self._ui_jobs: list[Callable[[], None]] = []
        self._idle_feed = _IdleWorldFeed()

        self.status_var = tk.StringVar(self, value="Stopped")
        self.map_var = tk.StringVar(self, value=self.map_id)
        self.map_lang_var = tk.StringVar(self, value=self._ui_lang)
        self.map_search_var = tk.StringVar(self, value="")
        self.map_count_var = tk.StringVar(self, value="")
        self.preview_var = tk.StringVar(self, value="")
        self.show_path_var = tk.BooleanVar(self, value=True)
        self.show_entities_var = tk.BooleanVar(self, value=True)
        self.show_self_var = tk.BooleanVar(self, value=True)
        self.kind_vars = {
            kind: tk.BooleanVar(self, value=True) for kind in _ENTITY_KINDS
        }
        # Plain flags for the render thread (avoid Tk var reads off the UI thread).
        self._show_path = True
        self._show_entities = True
        self._show_self = True
        self._entity_kinds = set(_ENTITY_KINDS)
        self.loot_mode_var = tk.StringVar(self, value=_load_dungeon_loot_mode())
        self.hint_var = tk.StringVar(self, value="")
        self._hp_actions = _load_dungeon_hp_actions()
        shop = _load_dungeon_shop()
        self.restock_potions_var = tk.BooleanVar(
            self, value=bool(shop.get("restock_potions", True))
        )
        self.return_potion_count_var = tk.IntVar(
            self, value=int(shop.get("return_potion_count", 20))
        )
        self.hp_potion_buy_qty_var = tk.IntVar(
            self, value=int(shop.get("hp_potion_buy_qty", 100))
        )
        self.hp_potion_npc_var = tk.StringVar(
            self, value=str(shop.get("hp_potion_npc") or "")
        )
        self._hp_action_rows: dict[str, tuple[tk.BooleanVar, Optional[tk.IntVar]]] = {}
        self._hp_action_hotbar_labels: dict[str, ttk.Label] = {}
        self._hp_inventory_raw: list[dict[str, Any]] = []
        self._hp_inventory_scanning = False
        self._sync_hint_loot()

        self.controller = BotController(
            on_log=self._on_log,
            on_state=self._on_bot_state,
        )
        self.controller.add_debug_watcher()

        self._build()
        if self.map_id:
            self._load_map(self.map_id)
        self._bind_hotkeys()
        self._start_render_thread()
        self.after(100, self._tick_ui)
        self.after(400, self._refresh_hp_inventory)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="Dungeon Combat", font=FONT_SECTION).pack(side="left")
        ttk.Label(header, textvariable=self.hint_var, foreground=TEXT_MUTED).pack(
            side="left", padx=(12, 0)
        )
        self.stop_btn = ttk.Button(
            header, text="Stop (End)", command=self.stop_bot, state="disabled"
        )
        self.stop_btn.pack(side="right", padx=(4, 0))
        self.start_btn = ttk.Button(header, text="Start (Home)", command=self.start_bot)
        self.start_btn.pack(side="right")

        left_host = ttk.Frame(outer)
        left_host.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left_host.rowconfigure(0, weight=1)
        left_host.columnconfigure(0, weight=1)

        self._left_canvas = tk.Canvas(
            left_host,
            highlightthickness=0,
            bg=BG,
            width=360,
            borderwidth=0,
        )
        left_scroll = ttk.Scrollbar(
            left_host, orient="vertical", command=self._left_canvas.yview
        )
        self._left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.grid(row=0, column=1, sticky="ns")
        self._left_canvas.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(self._left_canvas)
        self._left_window = self._left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _sync_left_scroll(_event: Any = None) -> None:
            self._left_canvas.configure(scrollregion=self._left_canvas.bbox("all"))

        def _sync_left_width(event: Any) -> None:
            self._left_canvas.itemconfigure(self._left_window, width=max(1, int(event.width)))

        left.bind("<Configure>", _sync_left_scroll)
        self._left_canvas.bind("<Configure>", _sync_left_width)

        def _left_wheel(event: Any) -> str:
            if getattr(event, "delta", 0):
                self._left_canvas.yview_scroll(int(-event.delta / 120), "units")
            elif getattr(event, "num", None) == 4:
                self._left_canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                self._left_canvas.yview_scroll(1, "units")
            return "break"

        def _wheel_on(_event: Any = None) -> None:
            self._left_canvas.bind_all("<MouseWheel>", _left_wheel)
            self._left_canvas.bind_all("<Button-4>", _left_wheel)
            self._left_canvas.bind_all("<Button-5>", _left_wheel)

        def _wheel_off(_event: Any = None) -> None:
            self._left_canvas.unbind_all("<MouseWheel>")
            self._left_canvas.unbind_all("<Button-4>")
            self._left_canvas.unbind_all("<Button-5>")

        left_host.bind("<Enter>", _wheel_on)
        left_host.bind("<Leave>", _wheel_off)
        self._left_canvas.bind("<Enter>", _wheel_on)
        left.bind("<Enter>", _wheel_on)

        maps = ttk.LabelFrame(left, text="Map", padding=8)
        maps.pack(fill="x")

        lang_row = ttk.Frame(maps)
        lang_row.pack(fill="x")
        ttk.Label(lang_row, text="Language").pack(side="left")
        for code, label in LANGUAGE_CHOICES:
            ttk.Radiobutton(
                lang_row,
                text=label,
                value=code,
                variable=self.map_lang_var,
                command=self._on_map_language,
            ).pack(side="left", padx=(8, 0))

        search_row = ttk.Frame(maps)
        search_row.pack(fill="x", pady=(6, 0))
        ttk.Label(search_row, text="Search").pack(side="left")
        self.map_search = ttk.Entry(search_row, textvariable=self.map_search_var)
        self.map_search.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.map_search_var.trace_add("write", self._on_map_search)

        ttk.Label(
            maps,
            text="Search EN / 한국어 / 简体中文 / pack id",
            foreground=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        self.map_combo = ttk.Combobox(
            maps,
            state="readonly",
            width=36,
            values=[],
        )
        self.map_combo.pack(fill="x", pady=(6, 0))
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_combo)
        ttk.Label(maps, textvariable=self.map_count_var, foreground=TEXT_MUTED).pack(
            anchor="w", pady=(4, 0)
        )
        self._refresh_map_combo(keep_map_id=self.map_id)

        preview = ttk.LabelFrame(left, text="Session", padding=8)
        preview.pack(fill="x", pady=(10, 0))
        ttk.Label(preview, textvariable=self.status_var).pack(anchor="w")
        ttk.Label(preview, textvariable=self.map_var, foreground=TEXT_MUTED).pack(
            anchor="w", pady=(2, 0)
        )
        self.session_info = ttk.Label(
            preview,
            textvariable=self.preview_var,
            foreground=TEXT_MUTED,
            justify="left",
            wraplength=360,
        )
        self.session_info.pack(anchor="w", pady=(6, 0))

        loot_box = ttk.LabelFrame(left, text="Loot", padding=8)
        loot_box.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(
            loot_box,
            text="전체 아이템 (아데나 우선)",
            value=LOOT_MODE_ALL,
            variable=self.loot_mode_var,
            command=self._on_loot_mode_change,
        ).pack(anchor="w")
        ttk.Radiobutton(
            loot_box,
            text="아데나만",
            value=LOOT_MODE_ADENA,
            variable=self.loot_mode_var,
            command=self._on_loot_mode_change,
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            loot_box,
            text="Start 시 적용. 가방이 거의 가득 차면 무게로 아데나만 강제될 수 있음.",
            foreground=TEXT_MUTED,
            wraplength=330,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        hp_box = ttk.LabelFrame(left, text="HP recovery", padding=8)
        hp_box.pack(fill="x", pady=(10, 0))
        ttk.Label(
            hp_box,
            text=(
                "Items/heal/teleport by %. Teleport reuses on a −5% ladder; "
                "resets when HP recovers above the teleport %. "
                "At HP ≤30% with potion restock due: World Tree (if available) "
                "then potion shop, else shop directly. Bag count alone does not "
                "open the potion shop. Add potions from the bag."
            ),
            foreground=TEXT_MUTED,
            wraplength=330,
            justify="left",
        ).pack(anchor="w")
        self._hp_action_body = ttk.Frame(hp_box)
        self._hp_action_body.pack(fill="x", pady=(6, 0))
        inv_row = ttk.Frame(hp_box)
        inv_row.pack(fill="x", pady=(8, 0))
        self._hp_inventory_status = ttk.Label(
            inv_row, text="Bag: —", foreground=TEXT_MUTED
        )
        self._hp_inventory_status.pack(side="left", fill="x", expand=True)
        ttk.Button(
            inv_row, text="Refresh bag", command=self._refresh_hp_inventory
        ).pack(side="right")
        inv_list = ttk.Frame(hp_box)
        inv_list.pack(fill="x", pady=(4, 0))
        self._hp_inventory_list = tk.Listbox(
            inv_list,
            height=5,
            exportselection=False,
            bg=SURFACE,
            fg=TEXT,
            font=FONT_BODY,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        inv_scroll = ttk.Scrollbar(
            inv_list, orient="vertical", command=self._hp_inventory_list.yview
        )
        self._hp_inventory_list.configure(yscrollcommand=inv_scroll.set)
        self._hp_inventory_list.pack(side="left", fill="both", expand=True)
        inv_scroll.pack(side="right", fill="y")
        ttk.Button(
            hp_box,
            text="Add selected bag item to HP order",
            command=self._add_selected_hp_item,
        ).pack(fill="x", pady=(4, 0))
        self._rebuild_hp_action_rows()

        shop_box = ttk.LabelFrame(
            left, text="Potion shop (after world tree / HP≤30%)", padding=8
        )
        shop_box.pack(fill="x", pady=(10, 0))
        ttk.Label(
            shop_box,
            text=(
                "After World Tree HP/MP full → always this shop (NPC + Buy qty). "
                "HP≤30% + low potions also uses it when tree is unavailable."
            ),
            foreground=TEXT_MUTED,
            wraplength=330,
            justify="left",
        ).pack(anchor="w")
        ttk.Checkbutton(
            shop_box,
            text="At HP≤30%, low potions (≤ limit) → tree/shop",
            variable=self.restock_potions_var,
            command=self._on_shop_setting_change,
        ).pack(anchor="w", pady=(4, 0))
        qty_row = ttk.Frame(shop_box)
        qty_row.pack(fill="x", pady=(4, 0))
        ttk.Label(qty_row, text="Return limit").pack(side="left")
        ttk.Spinbox(
            qty_row,
            from_=0,
            to=999,
            width=5,
            textvariable=self.return_potion_count_var,
            command=self._on_shop_setting_change,
        ).pack(side="left", padx=(6, 12))
        ttk.Label(qty_row, text="Buy qty").pack(side="left")
        ttk.Spinbox(
            qty_row,
            from_=1,
            to=999,
            width=5,
            textvariable=self.hp_potion_buy_qty_var,
            command=self._on_shop_setting_change,
        ).pack(side="left", padx=(6, 0))
        npc_row = ttk.Frame(shop_box)
        npc_row.pack(fill="x", pady=(6, 0))
        ttk.Label(npc_row, text="Shop NPC").pack(side="left")
        self._shop_npc_combo = ttk.Combobox(
            npc_row,
            textvariable=self.hp_potion_npc_var,
            values=_shop_npc_choices(),
            state="readonly",
            width=28,
        )
        self._shop_npc_combo.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self._shop_npc_combo.bind("<<ComboboxSelected>>", self._on_shop_setting_change)
        self.return_potion_count_var.trace_add("write", self._on_shop_setting_change)
        self.hp_potion_buy_qty_var.trace_add("write", self._on_shop_setting_change)
        ttk.Label(
            shop_box,
            text="Used after World Tree full recover, or directly at HP ≤30% "
            "when World Tree is unavailable.",
            foreground=TEXT_MUTED,
            wraplength=330,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        view = ttk.LabelFrame(left, text="Map view", padding=8)
        view.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(
            view,
            text="Show patrol path + points",
            variable=self.show_path_var,
            command=self._on_view_toggle,
        ).pack(anchor="w")
        ttk.Checkbutton(
            view,
            text="Show entities in sight",
            variable=self.show_entities_var,
            command=self._on_view_toggle,
        ).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(
            view,
            text="Self (you)",
            variable=self.show_self_var,
            command=self._on_view_toggle,
        ).pack(anchor="w", pady=(2, 0))
        kinds = ttk.Frame(view)
        kinds.pack(fill="x", pady=(4, 0))
        for i, kind in enumerate(_ENTITY_KINDS):
            ttk.Checkbutton(
                kinds,
                text=kind,
                variable=self.kind_vars[kind],
                command=self._on_view_toggle,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 8), pady=1)
        ttk.Label(
            view,
            text=(
                "label: type / English name / lv(monster) · "
                "engaged=red · eng:yes=lime · eng:no=orange · "
                "path>30=gray · give-up=gray · item=blue · you=magenta"
            ),
            foreground=TEXT_MUTED,
            wraplength=260,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        tools = ttk.LabelFrame(left, text="Patrol", padding=8)
        tools.pack(fill="x", pady=(10, 0))
        for text, cmd in (
            ("Delete selected", self._delete_selected),
            ("Clear all", self._clear_all),
            ("Reload", lambda: self._reload_patrol()),
            ("Save patrol", self.save_patrol),
        ):
            ttk.Button(tools, text=text, command=cmd).pack(fill="x", pady=2)

        list_row = ttk.Frame(tools)
        list_row.pack(fill="both", expand=True, pady=(8, 0))
        self.point_list = tk.Listbox(
            list_row,
            width=34,
            height=14,
            exportselection=False,
            bg=SURFACE,
            fg=TEXT,
            font=FONT_BODY,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        point_scroll = ttk.Scrollbar(
            list_row, orient="vertical", command=self.point_list.yview
        )
        self.point_list.configure(yscrollcommand=point_scroll.set)
        self.point_list.pack(side="left", fill="both", expand=True)
        point_scroll.pack(side="right", fill="y")
        self.point_list.bind("<<ListboxSelect>>", self._on_point_select)
        self.path_info = ttk.Label(
            tools, text="", foreground=TEXT_MUTED, wraplength=260, justify="left"
        )
        self.path_info.pack(anchor="w", pady=(6, 0))

        log_box = ttk.LabelFrame(left, text="Log", padding=4)
        log_box.pack(fill="x", pady=(10, 0))
        self.log = tk.Text(
            log_box,
            height=8,
            width=36,
            wrap="word",
            bg=SURFACE,
            fg=TEXT,
            font=FONT_BODY,
            relief="flat",
            state="disabled",
        )
        self.log.pack(fill="both", expand=True)

        right = ttk.Frame(outer)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        canvas_host = ttk.Frame(right, relief="solid", borderwidth=1)
        canvas_host.grid(row=0, column=0, sticky="nsew")
        canvas_host.rowconfigure(0, weight=1)
        canvas_host.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_host, bg="#1a1d23", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._request_redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_lmb)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas_status = ttk.Label(
            right, text="Click white tiles to place patrol points.", foreground=TEXT_MUTED
        )
        self.canvas_status.grid(row=1, column=0, sticky="w", pady=(6, 0))

    # ── map / patrol ──────────────────────────────────────────────────────

    def _on_map_language(self) -> None:
        self._ui_lang = normalize_language(self.map_lang_var.get())
        try:
            _save_ui_settings(language=self._ui_lang, last_map_id=self.map_id)
        except Exception:
            pass
        self._refresh_map_combo(keep_map_id=self.map_id)

    def _on_map_search(self, *_args: Any) -> None:
        self._refresh_map_combo(keep_map_id=self.map_id)

    def _refresh_map_combo(self, *, keep_map_id: str = "") -> None:
        query = self.map_search_var.get() if hasattr(self, "map_search_var") else ""
        filtered = filter_combat_maps(self._all_maps, query)
        self._filtered_maps = filtered
        lang = normalize_language(
            self.map_lang_var.get() if hasattr(self, "map_lang_var") else self._ui_lang
        )
        labels = [m.combo_label(lang) for m in filtered]
        self.map_combo.configure(values=labels)
        total = len(self._all_maps)
        shown = len(filtered)
        self.map_count_var.set(f"{shown} / {total} maps")
        want = str(keep_map_id or self.map_id or "").strip()
        idx = next((i for i, m in enumerate(filtered) if m.pack_id == want), -1)
        if idx >= 0:
            self.map_combo.current(idx)
        elif want:
            entry = next((m for m in self._all_maps if m.pack_id == want), None)
            if entry is not None:
                self.map_combo.set(entry.combo_label(lang))
            else:
                self.map_combo.set("")
        elif filtered:
            self.map_combo.current(0)
        else:
            self.map_combo.set("")

    def _on_map_combo(self, *_args: Any) -> None:
        if self._bot_busy():
            messagebox.showinfo(
                self.title(), "Stop the bot before switching maps.", parent=self
            )
            self._sync_combo_to_map()
            return
        if self._dirty and not self._confirm_discard():
            self._sync_combo_to_map()
            return
        idx = self.map_combo.current()
        if idx < 0 or idx >= len(self._filtered_maps):
            return
        self._load_map(self._filtered_maps[idx].pack_id)

    def _sync_combo_to_map(self) -> None:
        self._refresh_map_combo(keep_map_id=self.map_id)

    def _load_map(self, map_id: str) -> None:
        mid = map_overlay_slug(map_id)
        pack = pack_dir_for(mid)
        nav = pack / "nav.png"
        if not nav.is_file():
            messagebox.showerror(
                self.title(), f"Missing nav.png for {mid}:\n{nav}", parent=self
            )
            return
        meta = load_pack_meta(mid) or {}
        self.map_id = mid
        self.map_var.set(mid)
        try:
            _save_ui_settings(language=self._ui_lang, last_map_id=mid)
        except Exception:
            pass
        self._pixel_scale = max(1, int(meta.get("pixel_scale", 1) or 1))
        try:
            ox = int(meta.get("origin_x"))
            oy = int(meta.get("origin_y"))
            self._idle_feed.set_map_origin(ox, oy)
        except (TypeError, ValueError):
            pass
        try:
            self._base = Image.open(nav).convert("RGB")
        except OSError as exc:
            messagebox.showerror(self.title(), f"Could not open nav:\n{exc}", parent=self)
            return
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self.selected = None
        self._player_tile = None
        self._live_entities = []
        self._give_up_by_id = {}
        self._blacklist_ids = set()
        self._rebuild_terrain()
        self._reload_patrol(silent=True)
        self._dirty = False
        self._sync_combo_to_map()
        self._fit_view()
        self._request_redraw()
        self.canvas_status.configure(
            text=f"{mid}  ·  {self._base.size[0]}×{self._base.size[1]}  ·  "
            f"{len(self.patrol)} patrol points"
        )

    def _rebuild_terrain(self) -> None:
        self._terrain = None
        if self._base is None:
            return
        from app._03_world.space.terrain_map import TerrainMap
        import numpy as np

        ps = max(1, int(self._pixel_scale))
        pixels = np.asarray(self._base, dtype=np.uint8)
        walkable = (
            (pixels[:, :, 0] == 255)
            & (pixels[:, :, 1] == 255)
            & (pixels[:, :, 2] == 255)
        )
        if ps > 1:
            h, w = walkable.shape
            th, tw = h // ps, w // ps
            if th >= 1 and tw >= 1:
                blocks = walkable[: th * ps, : tw * ps]
                blocks = blocks.reshape(th, ps, tw, ps)
                walkable = blocks.mean(axis=(1, 3)) >= 0.5
        self._terrain = TerrainMap.from_array(walkable)

    def _reload_patrol(self, *, silent: bool = False) -> None:
        entries = list_patrol_entries(self.map_id)
        if not entries:
            pack_patrol = pack_dir_for(self.map_id) / "patrol.yaml"
            if pack_patrol.is_file():
                from app._04_decision.patrol import load_patrol_entries_from_yaml

                entries = load_patrol_entries_from_yaml(pack_patrol)
        self.patrol = list(entries)
        self.selected = None
        self._refresh_point_list()
        self._recompute_paths()
        self._request_redraw()
        if not silent:
            self.canvas_status.configure(text=f"Loaded {len(self.patrol)} patrol points")

    def save_patrol(self) -> None:
        if self._terrain is None:
            messagebox.showinfo(self.title(), "Load a map first.", parent=self)
            return
        bad = [
            (i, x, y)
            for i, (x, y, _n) in enumerate(self.patrol)
            if not self._is_walkable(x, y)
        ]
        if bad:
            messagebox.showerror(
                self.title(),
                f"{len(bad)} point(s) are not on walkable tiles.",
                parent=self,
            )
            return
        try:
            pts = [(x, y) for x, y, _n in self.patrol]
            names = [n for _x, _y, n in self.patrol]
            overlay = save_patrol_overlay(self.map_id, pts, names)
        except Exception as exc:
            messagebox.showerror(self.title(), str(exc), parent=self)
            return
        self._dirty = False
        self._recompute_paths()
        self.canvas_status.configure(
            text=f"Saved {len(self.patrol)} points → {overlay}"
        )
        self._append_log(f"Saved patrol ({len(self.patrol)} pts) for {self.map_id}")

    # ── canvas helpers ────────────────────────────────────────────────────

    def _tile_to_canvas(self, tx: int, ty: int) -> tuple[float, float]:
        ps = max(1, int(self._pixel_scale))
        return tx * ps * self._zoom + self._pan[0], ty * ps * self._zoom + self._pan[1]

    def _canvas_to_tile(self, cx: float, cy: float) -> tuple[int, int]:
        ps = max(1, int(self._pixel_scale))
        scale = max(self._zoom * ps, 1e-6)
        tx = int((cx - self._pan[0]) / scale)
        ty = int((cy - self._pan[1]) / scale)
        return self._clamp_tile(tx, ty)

    def _clamp_tile(self, tx: int, ty: int) -> tuple[int, int]:
        if self._terrain is None:
            return tx, ty
        return (
            max(0, min(tx, self._terrain.width - 1)),
            max(0, min(ty, self._terrain.height - 1)),
        )

    def _fit_view(self) -> None:
        if self._base is None:
            return
        self.update_idletasks()
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self._base.size
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, min(cw / iw, ch / ih) * 0.98))
        self._pan = [(cw - iw * self._zoom) / 2, (ch - ih * self._zoom) / 2]

    def _is_walkable(self, tx: int, ty: int) -> bool:
        return self._terrain is not None and self._terrain.is_walkable(tx, ty)

    def _recompute_paths(self) -> None:
        self.paths = []
        if self._terrain is None or len(self.patrol) < 2:
            self._update_path_info()
            return
        from app._04_decision.pathfinding import find_path

        for i in range(len(self.patrol) - 1):
            a = self.patrol[i][:2]
            b = self.patrol[i + 1][:2]
            self.paths.append(find_path(self._terrain, a, b))
        if len(self.patrol) >= 2:
            a = self.patrol[-1][:2]
            b = self.patrol[0][:2]
            self.paths.append(find_path(self._terrain, a, b))
        self._update_path_info()

    def _update_path_info(self) -> None:
        if not self.paths:
            self.path_info.configure(text="Place 2+ points for path preview.")
            return
        lines: list[str] = []
        for i, path in enumerate(self.paths):
            if i < len(self.patrol) - 1:
                label = f"{i + 1}→{i + 2}"
            else:
                label = f"{len(self.patrol)}→1"
            if not path:
                lines.append(f"{label}: blocked")
            else:
                lines.append(f"{label}: {len(path) - 1} steps")
        self.path_info.configure(text="\n".join(lines))

    # ── map render thread ─────────────────────────────────────────────────

    def _start_render_thread(self) -> None:
        if self._render_thread is not None and self._render_thread.is_alive():
            return
        self._render_stop.clear()
        self._render_thread = threading.Thread(
            target=self._render_loop,
            name="dungeon-combat-render",
            daemon=True,
        )
        self._render_thread.start()

    def _stop_render_thread(self) -> None:
        self._render_stop.set()
        self._render_wake.set()
        t = self._render_thread
        if t is not None and t.is_alive():
            t.join(timeout=1.5)
        self._render_thread = None

    def _on_view_toggle(self) -> None:
        self._show_path = bool(self.show_path_var.get())
        self._show_entities = bool(self.show_entities_var.get())
        self._show_self = bool(self.show_self_var.get())
        self._entity_kinds = {
            kind for kind, var in self.kind_vars.items() if bool(var.get())
        }
        self._request_redraw()

    def _request_redraw(self) -> None:
        """Wake the map/entity compose worker (coalesced)."""
        if self._closing:
            return
        self._render_wake.set()

    def _call_on_ui(self, fn: Callable[[], None]) -> None:
        """Queue a UI callback; drained only on the Tk thread."""
        with self._ui_lock:
            self._ui_jobs.append(fn)

    def _drain_ui_jobs(self) -> None:
        with self._ui_lock:
            jobs = list(self._ui_jobs)
            self._ui_jobs.clear()
        for fn in jobs:
            if self._closing:
                return
            try:
                fn()
            except Exception:
                pass

    def _capture_render_inputs(self) -> Optional[dict[str, Any]]:
        with self._state_lock:
            if self._base is None:
                return None
            stopped = self.controller.state == RunState.STOPPED
            bot_running = (
                not self._stopping
                and not self._closing
                and not stopped
            )
            # Idle memory feed only when the worker fully released print_state.
            idle_live = (
                not self._closing
                and not self._stopping
                and stopped
            )
            return {
                "base": self._base,
                "zoom": float(self._zoom),
                "pan": (float(self._pan[0]), float(self._pan[1])),
                "pixel_scale": int(self._pixel_scale),
                "show_path": bool(self._show_path),
                "show_entities": bool(self._show_entities),
                "show_self": bool(self._show_self),
                "entity_kinds": set(self._entity_kinds),
                "patrol": list(self.patrol),
                "paths": [list(p) for p in self.paths],
                "selected": self.selected,
                "terrain": self._terrain,
                "bot_running": bot_running,
                "idle_live": idle_live,
                "patrol_count": len(self.patrol),
                "patches_on": bool(self._patches.active),
            }

    def _render_loop(self) -> None:
        hold_player: Optional[tuple[int, int]] = None
        hold_entities: list[dict[str, Any]] = []
        while not self._render_stop.is_set():
            self._render_wake.wait(timeout=0.25)
            self._render_wake.clear()
            if self._render_stop.is_set():
                break
            # Coalesce bursts of pan/zoom/edit wakes.
            while self._render_wake.is_set():
                self._render_wake.clear()
            inputs = self._capture_render_inputs()
            if inputs is None:
                continue
            snap: dict[str, Any] = {}
            decision: dict[str, Any] = {}
            overview: dict[str, Any] = {}
            action_result: dict[str, Any] = {}
            player: Optional[tuple[int, int]] = None
            entities: list[dict[str, Any]] = []
            give_up_by_id: dict[int, dict[str, Any]] = {}
            blacklist_ids: set[int] = set()
            if inputs["bot_running"]:
                try:
                    snap = self.controller.debug_snapshot()
                    decision = snap.get("decision") or {}
                    overview = snap.get("overview") or {}
                    action_result = dict(snap.get("action_result") or {})
                    give_up_by_id, blacklist_ids = _parse_skip_sets(decision)
                    player, entities = _entities_from_snap(
                        snap,
                        terrain=inputs["terrain"],
                        give_up_by_id=give_up_by_id,
                        blacklist_ids=blacklist_ids,
                    )
                except Exception:
                    snap, decision, overview = {}, {}, {}
                    action_result = {}
                    player, entities = hold_player, list(hold_entities)
                    give_up_by_id, blacklist_ids = {}, set()
            elif inputs["idle_live"]:
                try:
                    player, entities = self._idle_feed.poll(inputs["terrain"])
                except Exception:
                    player, entities = hold_player, list(hold_entities)
            else:
                # Handoff while start/stop closes print_state — keep last view.
                player, entities = hold_player, list(hold_entities)
            if player is not None or entities:
                hold_player = player
                hold_entities = list(entities)
            try:
                image = _compose_map_frame(
                    base=inputs["base"],
                    zoom=inputs["zoom"],
                    pixel_scale=inputs["pixel_scale"],
                    show_path=inputs["show_path"],
                    show_entities=inputs["show_entities"],
                    show_self=inputs["show_self"],
                    entity_kinds=inputs["entity_kinds"],
                    patrol=inputs["patrol"],
                    paths=inputs["paths"],
                    selected=inputs["selected"],
                    player_tile=player,
                    entities=entities,
                )
            except Exception:
                continue
            status = {
                "decision": decision,
                "overview": overview,
                "action_result": action_result,
                "player_tile": player,
                "entities": entities,
                "give_up_by_id": give_up_by_id,
                "blacklist_ids": blacklist_ids,
                "patrol_count": inputs["patrol_count"],
                "patches_on": inputs["patches_on"],
                "idle_live": bool(inputs["idle_live"]),
            }
            with self._render_out_lock:
                self._render_frame = {"image": image, "pan": inputs["pan"]}
                self._render_status = status

    def _apply_render_outputs(self) -> None:
        if self._closing:
            return
        with self._render_out_lock:
            frame = self._render_frame
            status = self._render_status
            self._render_frame = None
            self._render_status = None
        if frame is not None:
            try:
                if not self.winfo_exists():
                    return
                self._photo = ImageTk.PhotoImage(frame["image"])
                self.canvas.delete("all")
                pan = frame["pan"]
                self.canvas.create_image(pan[0], pan[1], anchor="nw", image=self._photo)
            except Exception:
                pass
        if status is not None:
            self._player_tile = status.get("player_tile")
            self._live_entities = list(status.get("entities") or [])
            self._give_up_by_id = dict(status.get("give_up_by_id") or {})
            self._blacklist_ids = set(status.get("blacklist_ids") or set())
            try:
                self._update_session_panel(status)
            except Exception:
                pass

    @staticmethod
    def _format_cursor_check_line(
        decision: dict[str, Any],
        action_result: dict[str, Any],
        entities: list[dict[str, Any]] | None = None,
    ) -> str:
        """Session line for cursor-verify OK/FAIL, like the mouse click line."""
        ar = action_result or {}
        cf = decision.get("cursor_fail") or {}
        last = (
            cf.get("last_reject")
            if isinstance(cf, dict)
            else None
        ) or decision.get("last_cursor_reject")
        if not isinstance(last, dict):
            last = {}
        reject_tid = ar.get("reject_target_id")
        reject_iid = ar.get("reject_item_id")
        reject_reason = str(ar.get("reject_reason") or "").strip()
        this_tick_fail = bool(
            ar.get("verify_failed")
            or reject_tid is not None
            or reject_iid is not None
            or reject_reason
        )
        label = str(ar.get("cursor_label") or "").strip()
        category = str(ar.get("cursor_category") or "").strip()
        score = ar.get("cursor_score")
        match_bits: list[str] = []
        if label:
            match_bits.append(label)
        if category and category != label:
            match_bits.append(category)
        if score is not None:
            try:
                match_bits.append(f"{float(score):.3f}")
            except (TypeError, ValueError):
                pass
        match_s = "/".join(match_bits)

        streaks = cf.get("streaks") if isinstance(cf, dict) else None
        streak_by_id: dict[int, int] = {}
        if isinstance(streaks, list):
            for row in streaks:
                if not isinstance(row, dict):
                    continue
                try:
                    streak_by_id[int(row["id"])] = int(row["streak"])
                except (TypeError, ValueError, KeyError):
                    continue

        name_by_id: dict[int, str] = {}
        for row in entities or []:
            if not isinstance(row, dict):
                continue
            try:
                eid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            nm = str(
                row.get("name_en") or row.get("name") or ""
            ).strip()
            if nm and nm != "—":
                name_by_id[eid] = nm

        streak = None
        fail_id = None
        is_item = False
        reason = ""
        fail_name = ""
        stored_score = None
        stored_need = None
        stored_label = ""
        stored_category = ""
        if this_tick_fail:
            if reject_tid is not None:
                fail_id = reject_tid
                is_item = False
            elif reject_iid is not None:
                fail_id = reject_iid
                is_item = True
            reason = reject_reason
            if fail_id is not None:
                try:
                    streak = streak_by_id.get(int(fail_id))
                except (TypeError, ValueError):
                    streak = None
            if streak is None and last.get("id") is not None:
                try:
                    if fail_id is None or int(last.get("id")) == int(fail_id):
                        streak = int(last.get("streak"))
                except (TypeError, ValueError):
                    streak = None
            if last.get("id") is not None:
                try:
                    if fail_id is None or int(last.get("id")) == int(fail_id):
                        fail_name = str(last.get("name") or "").strip()
                        if not reason:
                            reason = str(last.get("reason") or "").strip()
                        stored_label = str(last.get("cursor_label") or "").strip()
                        stored_category = str(
                            last.get("cursor_category") or ""
                        ).strip()
                        stored_score = last.get("cursor_score")
                        stored_need = last.get("need_score")
                except (TypeError, ValueError):
                    pass
        elif streak_by_id:
            # Active streak only (scratch last_reject can be stale after OK).
            top_id, top_streak = max(
                streak_by_id.items(), key=lambda kv: (kv[1], -kv[0])
            )
            fail_id = top_id
            streak = top_streak
            try:
                if last.get("id") is not None and int(last.get("id")) == int(top_id):
                    is_item = bool(last.get("is_item"))
                    reason = str(last.get("reason") or "").strip()
                    fail_name = str(last.get("name") or "").strip()
                    stored_label = str(last.get("cursor_label") or "").strip()
                    stored_category = str(last.get("cursor_category") or "").strip()
                    stored_score = last.get("cursor_score")
                    stored_need = last.get("need_score")
            except (TypeError, ValueError):
                pass

        if fail_id is not None and not fail_name:
            try:
                fail_name = name_by_id.get(int(fail_id), "")
            except (TypeError, ValueError):
                fail_name = ""

        # Prefer live action_result match; fall back to last_reject fields.
        if score is None:
            score = stored_score
        if not label:
            label = stored_label
        if not category:
            category = stored_category
        need = stored_need
        if need is None and score is not None:
            need = 0.8

        active_fail = this_tick_fail or (
            streak is not None and int(streak) > 0
        )
        if not active_fail:
            if match_s:
                return f"cursor: OK · saw={match_s}"
            return "cursor: OK"

        bits = ["cursor: FAIL"]
        if fail_id is not None:
            bits.append(f"{'item' if is_item else 'id'}={fail_id}")
        if fail_name:
            bits.append(f"name={fail_name}")
        if streak is not None:
            bits.append(f"streak={streak}")
        # Explicit check result / confidence vs threshold.
        if label or category or score is not None:
            saw_bits: list[str] = []
            if label:
                saw_bits.append(label)
            if category and category != label:
                saw_bits.append(category)
            bits.append(f"saw={'/'.join(saw_bits) if saw_bits else '?'}")
        if score is not None:
            try:
                score_s = f"{float(score):.3f}"
            except (TypeError, ValueError):
                score_s = str(score)
            if need is not None:
                try:
                    need_s = f"{float(need):.2f}"
                except (TypeError, ValueError):
                    need_s = str(need)
                bits.append(f"conf={score_s}/{need_s}")
            else:
                bits.append(f"score={score_s}")
        elif need is not None:
            try:
                bits.append(f"need>={float(need):.2f}")
            except (TypeError, ValueError):
                bits.append(f"need>={need}")
        if reason:
            bits.append(f"reason={reason}")
        return " · ".join(bits)

    def _update_session_panel(self, status: dict[str, Any]) -> None:
        decision = status.get("decision") or {}
        overview = status.get("overview") or {}
        tick_ms = overview.get("tick_ms")
        fps = overview.get("fps")
        tick_count = decision.get("tick_count")
        if tick_ms is None:
            tick_line = "tick: —"
        else:
            try:
                tick_line = f"tick: {float(tick_ms):.1f} ms"
            except (TypeError, ValueError):
                tick_line = f"tick: {tick_ms} ms"
            if fps not in (None, ""):
                try:
                    tick_line += f" · {float(fps):.1f} fps"
                except (TypeError, ValueError):
                    pass
            if tick_count not in (None, ""):
                tick_line += f" · #{tick_count}"
        live_src = (
            "idle memory"
            if status.get("idle_live")
            else ("bot snapshot" if self._bot_busy() else "hold")
        )
        lines = [
            tick_line,
            f"patrol: {status.get('patrol_count', len(self.patrol))} points",
            f"no-unstick / HP-scroll=OFF: {'on' if status.get('patches_on') else 'off'}",
            "skip attack: 골렘, 괴물눈",
            "loot: all items",
            f"render: background · {live_src}",
        ]
        mode = decision.get("mode") or "—"
        goal = decision.get("goal") or "—"
        action = decision.get("action") or "—"
        reason = str(decision.get("reason") or "").strip() or "—"
        target = decision.get("target_id")
        item_id = decision.get("item_id")
        target_s = "—" if target in (None, "", 0) else str(target)
        mid_act = bool(decision.get("mid_act"))
        click_uv = str(decision.get("click") or "").strip()
        decision_bits = [str(action)]
        if target_s != "—":
            decision_bits.append(f"target={target_s}")
        if item_id not in (None, "", 0):
            decision_bits.append(f"item={item_id}")
        if mid_act:
            decision_bits.append("mid_act")
        if click_uv and click_uv != "—":
            decision_bits.append(f"click=({click_uv})")
        lines.extend(
            [
                f"mode: {mode}",
                f"goal: {goal}",
                f"decision: {' · '.join(decision_bits)}",
            ]
        )
        # Split rich "no intent | trying=… | why=…" so Session stays readable.
        if reason != "—" and " | " in reason:
            for part in reason.split(" | "):
                part = part.strip()
                if part:
                    lines.append(f"reason: {part}")
        else:
            lines.append(f"reason: {reason}")

        action_key = str(action or "").strip().lower()
        now = time.time()
        if action_key == "idle":
            if self._idle_since is None:
                self._idle_since = now
            idle_for = max(0.0, now - float(self._idle_since))
        else:
            self._idle_since = None
            self._long_idle_log_key = ""
            idle_for = 0.0

        if idle_for >= _LONG_IDLE_S:
            diag = decision.get("idle_diag")
            if not isinstance(diag, dict):
                diag = {}
            detail_lines = [
                f"*** LONG IDLE {idle_for:.1f}s ***",
                f"idle_reason: {reason}",
                f"mode/goal: {mode} / {goal}",
            ]
            origin = diag.get("world_origin") or "—"
            nav = diag.get("nav_goal") or "—"
            wp = diag.get("nav_waypoint") or "—"
            purpose = diag.get("travel_purpose") or "—"
            hop = str(diag.get("travel_hop_miss") or "").strip()
            detail_lines.append(f"origin: {origin}  nav: {nav}  wp: {wp}")
            detail_lines.append(f"travel_purpose: {purpose}")
            if hop:
                detail_lines.append(f"travel_hop_miss: {hop}")
            blocked = diag.get("dungeon_blocked_origin")
            if blocked not in (None, "", []):
                tried_n = diag.get("dungeon_blocked_tried_n")
                detail_lines.append(
                    f"blocked_origin: {blocked}  tried={tried_n}"
                )
            whys = diag.get("no_intent_why") or []
            if isinstance(whys, list) and whys:
                detail_lines.append("no_intent_why (recent):")
                for why in whys[-6:]:
                    detail_lines.append(f"  - {why}")
            lines.extend(detail_lines)
            log_key = f"{reason}|{hop}|{blocked}|{purpose}"
            if log_key != self._long_idle_log_key:
                self._long_idle_log_key = log_key
                self._append_log(
                    f"LONG IDLE {idle_for:.1f}s — {reason}"
                    + (f" | hop={hop}" if hop else "")
                    + (f" | blocked={blocked}" if blocked not in (None, "", []) else "")
                )
                for why in (whys[-4:] if isinstance(whys, list) else []):
                    self._append_log(f"  no_intent: {why}")

        # Keep the top status line in sync with the live intent reason.
        try:
            from session.bot_controller import RunState as _RS

            state = self.controller.state
            short_reason = reason
            if reason.startswith("no intent"):
                # Prefer trying=… for the one-line status header.
                for part in reason.split(" | "):
                    p = part.strip()
                    if p.startswith("trying="):
                        short_reason = p
                        break
                    if p.startswith("why="):
                        short_reason = p
            if idle_for >= _LONG_IDLE_S:
                short_reason = f"LONG IDLE {idle_for:.0f}s — {short_reason}"
            if state == _RS.RUNNING:
                self.status_var.set(f"Running — {action}: {short_reason}")
            elif state == _RS.PAUSED:
                self.status_var.set(f"Paused — {action}: {short_reason}")
        except Exception:
            pass
        ar = status.get("action_result") or {}
        kind = str(ar.get("kind") or "none").strip().lower() or "none"
        if kind == "click":
            mouse_line = "mouse: CLICK"
        elif kind == "hover":
            mouse_line = "mouse: HOVER (no click)"
        else:
            mouse_line = "mouse: none"
        detail = str(ar.get("detail") or "").strip()
        if detail:
            mouse_line = f"{mouse_line} · {detail}"
        lines.append(mouse_line)
        cursor_line = self._format_cursor_check_line(
            decision, ar, status.get("entities") or []
        )
        lines.append(cursor_line)
        cf = decision.get("cursor_fail") or {}
        last_rej = (
            cf.get("last_reject") if isinstance(cf, dict) else None
        ) or decision.get("last_cursor_reject")
        if isinstance(last_rej, dict) and last_rej.get("id") is not None:
            rej_key = (
                f"{last_rej.get('id')}:{last_rej.get('streak')}:"
                f"{last_rej.get('reason')}:{last_rej.get('name')}"
            )
            if rej_key != self._last_cursor_reject_key and not bool(
                last_rej.get("is_item")
            ):
                self._last_cursor_reject_key = rej_key
                nm = str(last_rej.get("name") or "").strip() or "?"
                self._append_log(
                    f"cursor reject id={last_rej.get('id')} name={nm} "
                    f"streak={last_rej.get('streak')} "
                    f"conf={last_rej.get('cursor_score')}/{last_rej.get('need_score')} "
                    f"reason={last_rej.get('reason') or 'cursor reject'}"
                )
        player = status.get("player_tile")
        if player is not None:
            lines.append(f"you: {player[0]}, {player[1]}")
        visible = [
            e
            for e in (status.get("entities") or [])
            if str(e.get("kind") or "other") in self._entity_kinds
        ]
        lines.append(f"sight: {len(visible)}/{len(status.get('entities') or [])}")
        give_ups = list((status.get("give_up_by_id") or {}).values())
        if give_ups:
            lines.append(f"give-up active: {len(give_ups)}")
            for row in sorted(
                give_ups, key=lambda r: int(r.get("remain_ticks") or 0)
            )[:6]:
                bits = [f"  id={row.get('id')}"]
                nm = str(row.get("name") or "").strip()
                if not nm:
                    try:
                        oid = int(row.get("id"))
                    except (TypeError, ValueError):
                        oid = None
                    if oid is not None:
                        for ent in status.get("entities") or []:
                            if not isinstance(ent, dict):
                                continue
                            try:
                                if int(ent.get("id")) != oid:
                                    continue
                            except (TypeError, ValueError):
                                continue
                            nm = str(
                                ent.get("name_en") or ent.get("name") or ""
                            ).strip()
                            if nm and nm != "—":
                                break
                if nm and nm != "—":
                    bits.append(f"name={nm}")
                saw_bits: list[str] = []
                cl = str(row.get("cursor_label") or "").strip()
                cc = str(row.get("cursor_category") or "").strip()
                if cl:
                    saw_bits.append(cl)
                if cc and cc != cl:
                    saw_bits.append(cc)
                if saw_bits:
                    bits.append(f"saw={'/'.join(saw_bits)}")
                score = row.get("cursor_score")
                need = row.get("need_score")
                if score is not None:
                    try:
                        score_s = f"{float(score):.3f}"
                    except (TypeError, ValueError):
                        score_s = str(score)
                    if need is not None:
                        try:
                            need_s = f"{float(need):.2f}"
                        except (TypeError, ValueError):
                            need_s = str(need)
                        bits.append(f"conf={score_s}/{need_s}")
                    else:
                        bits.append(f"score={score_s}")
                reason = str(row.get("reason") or "give-up").strip() or "give-up"
                bits.append(f"reason={reason}")
                bits.append(f"({row.get('remain_ticks')}t left)")
                lines.append(" · ".join(bits))
        path_skips = [
            row
            for row in (decision.get("path_cap_skips") or [])
            if isinstance(row, dict)
        ]
        if path_skips:
            lines.append(f"path cap skip: {len(path_skips)}")
            for row in path_skips[:6]:
                reason = str(row.get("reason") or "path>30").strip() or "path>30"
                lines.append(
                    f"  id={row.get('id')} {row.get('kind') or '?'} {reason}"
                )
            newest = path_skips[-1]
            skip_key = (
                f"{newest.get('id')}:{newest.get('kind')}:{newest.get('reason')}:"
                f"{newest.get('steps')}"
            )
            if skip_key != getattr(self, "_last_path_cap_key", ""):
                self._last_path_cap_key = skip_key
                self._append_log(
                    f"path cap skip id={newest.get('id')} "
                    f"kind={newest.get('kind') or '?'} "
                    f"reason={newest.get('reason') or 'path>30'}"
                )
        last = decision.get("last_give_up")
        if isinstance(last, dict) and last.get("id") is not None:
            key = f"{last.get('tick')}:{last.get('id')}:{last.get('reason')}"
            if key != self._last_give_up_key:
                self._last_give_up_key = key
                nm = str(last.get("name") or "").strip() or "?"
                self._append_log(
                    f"give-up id={last.get('id')} name={nm} "
                    f"conf={last.get('cursor_score')}/{last.get('need_score')} "
                    f"reason={last.get('reason') or 'give-up'}"
                )
            if not give_ups:
                bits = [f"last give-up: id={last.get('id')}"]
                nm = str(last.get("name") or "").strip()
                if nm:
                    bits.append(f"name={nm}")
                score = last.get("cursor_score")
                need = last.get("need_score")
                if score is not None:
                    try:
                        score_s = f"{float(score):.3f}"
                    except (TypeError, ValueError):
                        score_s = str(score)
                    if need is not None:
                        try:
                            need_s = f"{float(need):.2f}"
                        except (TypeError, ValueError):
                            need_s = str(need)
                        bits.append(f"conf={score_s}/{need_s}")
                    else:
                        bits.append(f"score={score_s}")
                bits.append(f"reason={last.get('reason') or 'give-up'}")
                lines.append(" · ".join(bits))
        banned = status.get("blacklist_ids") or set()
        if banned:
            lines.append(f"session blacklist: {sorted(banned)}")
        self.preview_var.set("\n".join(lines))

    def _refresh_point_list(self) -> None:
        self.point_list.delete(0, "end")
        for i, (x, y, name) in enumerate(self.patrol):
            self.point_list.insert("end", f"{i + 1}. {name}  ({x}, {y})")
        if self.selected is not None and 0 <= self.selected < len(self.patrol):
            self.point_list.selection_set(self.selected)
            self.point_list.see(self.selected)

    def _on_point_select(self, *_args: Any) -> None:
        sel = self.point_list.curselection()
        if not sel:
            return
        self.selected = int(sel[0])
        self._request_redraw()

    def _hit_patrol(self, tx: int, ty: int) -> Optional[int]:
        best = None
        best_d = None
        for i, (x, y, _n) in enumerate(self.patrol):
            d = max(abs(x - tx), abs(y - ty))
            if d <= _HIT_R and (best_d is None or d < best_d):
                best_d = d
                best = i
        return best

    def _on_lmb(self, event: tk.Event) -> None:
        if self._bot_busy():
            return
        if self._terrain is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        hit = self._hit_patrol(tx, ty)
        if hit is not None:
            self.selected = hit
            self._dragging = hit
            self._refresh_point_list()
            self._request_redraw()
            return
        if not self._is_walkable(tx, ty):
            self.canvas_status.configure(text="Not walkable (need white).")
            return
        name = f"mid_{len(self.patrol) + 1}"
        self.patrol.append((tx, ty, name))
        self.selected = len(self.patrol) - 1
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()
        self._request_redraw()
        self.canvas_status.configure(text=f"Added {name} at ({tx}, {ty})")

    def _on_drag(self, event: tk.Event) -> None:
        if self._bot_busy() or self._dragging is None or self._terrain is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        if not self._is_walkable(tx, ty):
            return
        idx = self._dragging
        _x, _y, name = self.patrol[idx]
        self.patrol[idx] = (tx, ty, name)
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()
        self._request_redraw()

    def _on_release(self, _event: tk.Event) -> None:
        self._dragging = None

    def _on_pan_start(self, event: tk.Event) -> None:
        self._panning = True
        self._pan_start = (event.x, event.y)
        self._pan_origin = list(self._pan)

    def _on_pan_move(self, event: tk.Event) -> None:
        if not self._panning:
            return
        self._pan = [
            self._pan_origin[0] + (event.x - self._pan_start[0]),
            self._pan_origin[1] + (event.y - self._pan_start[1]),
        ]
        self._request_redraw()

    def _on_wheel(self, event: tk.Event) -> None:
        if self._base is None:
            return
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        new_zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        tx = (event.x - self._pan[0]) / max(self._zoom, 1e-6)
        ty = (event.y - self._pan[1]) / max(self._zoom, 1e-6)
        self._zoom = new_zoom
        self._pan = [event.x - tx * self._zoom, event.y - ty * self._zoom]
        self._request_redraw()

    def _on_motion(self, event: tk.Event) -> None:
        if self._terrain is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        walk = "walkable" if self._is_walkable(tx, ty) else "blocked"
        self.canvas_status.configure(text=f"tile ({tx}, {ty}) · {walk}")

    def _delete_selected(self) -> None:
        if self._bot_busy():
            return
        if self.selected is None or not (0 <= self.selected < len(self.patrol)):
            return
        self.patrol.pop(self.selected)
        self.selected = None
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()
        self._request_redraw()

    def _clear_all(self) -> None:
        if self._bot_busy() or not self.patrol:
            return
        if not messagebox.askyesno(
            self.title(), "Delete all patrol points on this map?", parent=self
        ):
            return
        self.patrol.clear()
        self.selected = None
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()
        self._request_redraw()

    def _confirm_discard(self) -> bool:
        return bool(
            messagebox.askyesno(
                self.title(),
                "Patrol edits are unsaved. Discard them?",
                parent=self,
            )
        )

    # ── HP recovery panel ─────────────────────────────────────────────────

    def _snapshot_hp_actions_from_rows(self) -> None:
        visible = _visible_dungeon_hp_actions(self._hp_actions)
        updated: list[dict[str, Any]] = []
        for row in visible:
            key = str(row.get("id") or "")
            pair = self._hp_action_rows.get(key)
            if pair is None:
                updated.append(dict(row))
                continue
            enabled, percent = pair
            if key == "mother_tree" or percent is None:
                # Auto gate — keep dummy % for normalize only.
                try:
                    hp_below = int(row.get("hp_below", 30))
                except (TypeError, ValueError):
                    hp_below = 30
            else:
                try:
                    hp_below = max(5, min(95, int(percent.get())))
                except (TypeError, ValueError, tk.TclError):
                    hp_below = int(row.get("hp_below", DEFAULT_INPLACE_PCT))
            updated.append(
                {
                    "id": key,
                    "enabled": bool(enabled.get()),
                    "hp_below": hp_below,
                }
            )
        self._hp_actions = _finalize_dungeon_hp_actions(updated)

    def _current_shop_settings(self) -> dict[str, Any]:
        try:
            limit = max(0, min(999, int(self.return_potion_count_var.get())))
        except (TypeError, ValueError, tk.TclError):
            limit = 20
        try:
            qty = max(1, min(999, int(self.hp_potion_buy_qty_var.get())))
        except (TypeError, ValueError, tk.TclError):
            qty = 100
        return {
            "restock_potions": bool(self.restock_potions_var.get()),
            "return_potion_count": limit,
            "hp_potion_buy_qty": qty,
            "hp_potion_npc": str(self.hp_potion_npc_var.get() or "").strip(),
        }

    def _persist_hp_actions(self) -> None:
        self._snapshot_hp_actions_from_rows()
        try:
            _save_dungeon_settings(
                self._hp_actions,
                loot_mode=self._current_loot_mode(),
                shop=self._current_shop_settings(),
            )
        except Exception as exc:
            self._append_log(f"HP settings save failed: {exc}")

    def _current_loot_mode(self) -> str:
        return _normalize_loot_mode(self.loot_mode_var.get())

    def _sync_hint_loot(self) -> None:
        loot = (
            "loot all"
            if self._current_loot_mode() == LOOT_MODE_ALL
            else "loot adena only"
        )
        self.hint_var.set(
            "Home=start · End=stop · TP −5% ladder · ≤30% tree/shop · "
            "no unstick · no 13s confined TP · HP-scroll=OFF · "
            f"skip 골렘/괴물눈 · {loot}"
        )

    def _on_loot_mode_change(self) -> None:
        self._sync_hint_loot()
        try:
            _save_dungeon_settings(
                self._hp_actions,
                loot_mode=self._current_loot_mode(),
                shop=self._current_shop_settings(),
            )
        except Exception as exc:
            self._append_log(f"Loot settings save failed: {exc}")

    def _on_shop_setting_change(self, *_args: Any) -> None:
        try:
            _save_dungeon_settings(
                self._hp_actions,
                loot_mode=self._current_loot_mode(),
                shop=self._current_shop_settings(),
            )
        except Exception as exc:
            self._append_log(f"Shop settings save failed: {exc}")

    def _on_hp_action_change(self, *_args: Any) -> None:
        self._persist_hp_actions()

    def _rebuild_hp_action_rows(self) -> None:
        body = getattr(self, "_hp_action_body", None)
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()
        self._hp_action_rows = {}
        self._hp_action_hotbar_labels = {}
        body.columnconfigure(1, weight=1)
        compact = {"width": 3, "padding": (1, 0)}
        visible = _visible_dungeon_hp_actions(self._hp_actions)
        for index, row in enumerate(visible):
            key = str(row["id"])
            enabled = tk.BooleanVar(self, value=bool(row.get("enabled", True)))
            percent: Optional[tk.IntVar]
            if key == "mother_tree":
                percent = None
            else:
                percent = tk.IntVar(self, value=int(row.get("hp_below", 30)))
            cb = ttk.Checkbutton(body, variable=enabled)
            cb.grid(row=index, column=0, sticky="w", pady=1)
            ttk.Label(body, text=_hp_action_label(key)).grid(
                row=index, column=1, sticky="ew", padx=(4, 4)
            )
            hotbar = ttk.Label(
                body, text=self._hp_action_hotbar_text(key), foreground=TEXT_MUTED
            )
            hotbar.grid(row=index, column=2, sticky="w", padx=(0, 4))
            self._hp_action_hotbar_labels[key] = hotbar
            if key == "mother_tree":
                ttk.Label(
                    body,
                    text="≤30%",
                    foreground=TEXT_MUTED,
                ).grid(row=index, column=3, columnspan=2, sticky="w", padx=(0, 4))
            else:
                spin = ttk.Spinbox(
                    body, from_=5, to=95, width=4, textvariable=percent
                )
                spin.grid(row=index, column=3, sticky="w")
                ttk.Label(body, text="%").grid(
                    row=index, column=4, sticky="w", padx=(2, 4)
                )
            moves = ttk.Frame(body)
            up = ttk.Button(
                moves,
                text="↑",
                command=lambda i=index: self._move_hp_action(i, -1),
                **compact,
            )
            down = ttk.Button(
                moves,
                text="↓",
                command=lambda i=index: self._move_hp_action(i, 1),
                **compact,
            )
            up.pack(side="left", padx=(0, 2))
            down.pack(side="left")
            moves.grid(row=index, column=5, sticky="e")
            if is_item_action(key):
                ttk.Button(
                    body,
                    text="×",
                    command=lambda i=index: self._remove_hp_action(i),
                    **compact,
                ).grid(row=index, column=6, sticky="e", padx=(4, 0))
            if index == 0:
                up.configure(state="disabled")
            if index == len(visible) - 1:
                down.configure(state="disabled")
            enabled.trace_add("write", self._on_hp_action_change)
            if percent is not None:
                percent.trace_add("write", self._on_hp_action_change)
            self._hp_action_rows[key] = (enabled, percent)
        self._refresh_hp_action_hotbar_keys()

    def _move_hp_action(self, index: int, delta: int) -> None:
        self._snapshot_hp_actions_from_rows()
        visible = _visible_dungeon_hp_actions(self._hp_actions)
        dest = index + delta
        if dest < 0 or dest >= len(visible):
            return
        visible[index], visible[dest] = visible[dest], visible[index]
        self._hp_actions = _finalize_dungeon_hp_actions(visible)
        self._rebuild_hp_action_rows()
        self._persist_hp_actions()

    def _remove_hp_action(self, index: int) -> None:
        self._snapshot_hp_actions_from_rows()
        visible = _visible_dungeon_hp_actions(self._hp_actions)
        if index < 0 or index >= len(visible):
            return
        key = str(visible[index].get("id") or "")
        if not is_item_action(key):
            return
        visible.pop(index)
        self._hp_actions = _finalize_dungeon_hp_actions(visible)
        self._rebuild_hp_action_rows()
        self._persist_hp_actions()

    def _add_selected_hp_item(self) -> None:
        listbox = getattr(self, "_hp_inventory_list", None)
        if listbox is None:
            return
        sel = listbox.curselection()
        if not sel:
            self._hp_inventory_status.configure(text="Bag: select an item first")
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._hp_inventory_raw):
            return
        item = self._hp_inventory_raw[idx]
        key = inventory_item_key_for_hp_action(item)
        if not key:
            self._hp_inventory_status.configure(text="Bag: could not read item name")
            return
        action_id = item_action_id(key)
        self._snapshot_hp_actions_from_rows()
        visible = _visible_dungeon_hp_actions(self._hp_actions)
        for row in visible:
            if str(row.get("id") or "") == action_id:
                row["enabled"] = True
                self._hp_actions = _finalize_dungeon_hp_actions(visible)
                self._rebuild_hp_action_rows()
                self._persist_hp_actions()
                self._hp_inventory_status.configure(
                    text=f"Bag: already in order ({key})"
                )
                return
        insert_at = len(visible)
        for i, row in enumerate(visible):
            if str(row.get("id") or "") in {"teleport", "safe_zone", "mother_tree"}:
                insert_at = i
                break
        visible.insert(
            insert_at,
            {
                "id": action_id,
                "enabled": True,
                "hp_below": DEFAULT_INPLACE_PCT,
            },
        )
        self._hp_actions = _finalize_dungeon_hp_actions(visible)
        self._rebuild_hp_action_rows()
        self._persist_hp_actions()
        self._hp_inventory_status.configure(text=f"Bag: added {key}")

    def _refresh_hp_inventory(self) -> None:
        if self._closing or self._hp_inventory_scanning:
            return
        self._hp_inventory_scanning = True
        try:
            self._hp_inventory_status.configure(text="Bag: refreshing…")
        except Exception:
            pass

        def work() -> None:
            rows: list[dict[str, Any]] = []
            error = ""
            try:
                from app._01_perception.inventory_listen_reader import shared_inventory

                snap = shared_inventory().snapshot()
                raw = snap.get("items") if isinstance(snap, dict) else None
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict):
                            rows.append(item)
            except Exception as exc:
                error = str(exc)
            self._call_on_ui(lambda: self._finish_hp_inventory(rows, error))

        threading.Thread(target=work, name="dungeon-hp-inv", daemon=True).start()

    def _finish_hp_inventory(
        self, rows: list[dict[str, Any]], error: str
    ) -> None:
        self._hp_inventory_scanning = False
        if self._closing:
            return
        self._hp_inventory_raw = list(rows)
        listbox = getattr(self, "_hp_inventory_list", None)
        if listbox is not None:
            listbox.delete(0, "end")
            for item in rows:
                name = (
                    item.get("name")
                    or item.get("name_tw")
                    or item.get("name_en")
                    or "?"
                )
                count = item.get("count")
                suffix = f" ×{count}" if count not in (None, "") else ""
                listbox.insert("end", f"{name}{suffix}")
        if error:
            self._hp_inventory_status.configure(text=f"Bag: {error}")
        else:
            self._hp_inventory_status.configure(text=f"Bag: {len(rows)} items")
        self._refresh_hp_action_hotbar_keys()

    def _hp_action_hotbar_text(self, action_id: str) -> str:
        try:
            from app._04_decision.hp_actions import (
                find_hp_restore_hotbar,
                format_hotbar_binding,
            )
            from hotbar.inspect import find_role_on_hotbar
        except Exception:
            return "no hotbar"

        snap = None
        try:
            from app._01_perception.sensors import shared_sensors

            snap = shared_sensors().capture_hotbar(force=True)
        except Exception:
            snap = None
        world = type("HotbarWorld", (), {"last_hotbar": snap})()
        layout = getattr(load_profile(), "hotbar_layout", {}) or {}
        slot = None
        extra = ""
        if is_item_action(action_id):
            slot = find_hp_restore_hotbar(
                world, item_key_from_action(action_id), layout=layout
            )
            if slot is not None and isinstance(snap, dict):
                for raw in snap.get("slots") or []:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        box = int(raw.get("box") or 0)
                    except (TypeError, ValueError):
                        box = 0
                    key = str(raw.get("key") or "").strip().lower()
                    if (box, key) != slot:
                        continue
                    count = raw.get("count")
                    if count not in (None, ""):
                        extra = f" ×{count}"
                    break
        else:
            role = {
                "heal": "heal",
                "teleport": "teleport",
                "safe_zone": "talking_scroll",
                "mother_tree": "mother_tree",
            }.get(str(action_id))
            if role and isinstance(snap, dict):
                try:
                    slot = find_role_on_hotbar(snap, role)
                except Exception:
                    slot = None
            if slot is None and role:
                slots = getattr(load_profile(), "spell_slots", {}) or {}
                # role matches Setup spell_slots keys (talking_scroll / mother_tree).
                spec = slots.get(role) if isinstance(slots, dict) else None
                if isinstance(spec, dict) and spec.get("enabled", True):
                    try:
                        box = int(spec.get("box") or 0)
                    except (TypeError, ValueError):
                        box = 0
                    key = str(spec.get("key") or "").strip().lower()
                    if box in (1, 2, 3) and key:
                        slot = (box, key)
        shown = format_hotbar_binding(slot)
        return f"{shown}{extra}" if shown else "no hotbar"

    def _refresh_hp_action_hotbar_keys(self) -> None:
        labels = getattr(self, "_hp_action_hotbar_labels", None)
        if not labels:
            return
        for action_id, label in labels.items():
            try:
                label.configure(text=self._hp_action_hotbar_text(action_id))
            except tk.TclError:
                continue

    # ── bot session ───────────────────────────────────────────────────────

    def _bot_busy(self) -> bool:
        return self.controller.state != RunState.STOPPED

    def _make_profile(self) -> Profile:
        base = load_profile()
        blocked = list(base.species_blacklist or [])
        for key in _dungeon_skip_species():
            if key not in blocked:
                blocked.append(key)
        self._snapshot_hp_actions_from_rows()
        hp_actions = _finalize_dungeon_hp_actions(self._hp_actions)
        shop = self._current_shop_settings()
        return replace(
            base,
            active_map=self.map_id,
            map_style="dungeon",
            selected_farms=[],
            species_filter_mode="blacklist",
            species_blacklist=blocked,
            loot_mode=self._current_loot_mode(),
            item_pickup_mode="all",
            item_pickup_names=[],
            # Delay weight→adena-only until nearly full (profile default is 0.30).
            loot_adena_weight_ratio=0.95,
            hp_actions=hp_actions,
            restock_potions=bool(shop.get("restock_potions", True)),
            return_potion_enabled=bool(shop.get("restock_potions", True)),
            return_potion_count=int(shop.get("return_potion_count", 20)),
            hp_potion_buy_qty=int(shop.get("hp_potion_buy_qty", 100)),
            hp_potion_npc=str(shop.get("hp_potion_npc") or ""),
        )

    def start_bot(self) -> None:
        if self._closing or self._stopping:
            return
        if self._bot_busy():
            return
        if self._dirty:
            if messagebox.askyesno(
                self.title(),
                "Patrol has unsaved edits. Save before start?",
                parent=self,
            ):
                self.save_patrol()
            else:
                return
        if not self.patrol and not list_patrol_entries(self.map_id):
            messagebox.showerror(
                self.title(),
                "No patrol points. Place and save waypoints first.",
                parent=self,
            )
            return
        profile = self._make_profile()
        self._stopping = False
        _reset_dungeon_tp_ladder()
        # Release idle print_state before the bot worker opens its own sweep.
        self._idle_feed.close()
        self._patches.install()
        err = self.controller.start(profile, unattended=True)
        if err:
            self._patches.restore()
            messagebox.showerror(self.title(), f"Start failed: {err}", parent=self)
            self._request_redraw()
            return
        self._persist_hp_actions()
        self._append_log(
            f"Started dungeon combat on {self.map_id} "
            "(TP −5% ladder · ≤30% tree/shop · HP-scroll=OFF · [던전HP] logs)"
        )
        _hp_log_last.clear()
        _dungeon_hp_log(
            f"세션 시작 map={self.map_id} — TP 계단/≤30% 월드트리·상점/"
            "힐·물약·스크롤 자동 정책 ON"
        )
        self._refresh_buttons()
        self._request_redraw()

    def stop_bot(self) -> None:
        """Stop combat; safe from Home/End hotkey queue (Tk thread only)."""
        if self._closing:
            return
        try:
            if self._stopping:
                return
            if self.controller.state == RunState.STOPPED:
                self._patches.restore()
                self._stopping = False
                self._refresh_buttons()
                self._request_redraw()
                return
            self._stopping = True
            # Pause idle reopen until the worker closes print_state.
            self._idle_feed.close()
            self._request_redraw()
            self.controller.stop(reason="dungeon combat stop")
            self._append_log("Stop requested")
            self._refresh_buttons()
            threading.Thread(
                target=self._wait_stop_cleanup,
                name="dungeon-combat-stop",
                daemon=True,
            ).start()
        except Exception as exc:
            self._stopping = False
            try:
                self._append_log(f"Stop error: {exc}")
            except Exception:
                pass

    def _wait_stop_cleanup(self) -> None:
        try:
            self.controller.wait_stopped(timeout=8.0)
        except Exception:
            pass
        try:
            self._patches.restore()
        except Exception:
            pass
        # Never call Tk.after from this thread — queue for _tick_ui.
        def _done() -> None:
            self._stopping = False
            if self._closing:
                return
            self._refresh_buttons()
            self._request_redraw()
            self._append_log("Stopped — map/entities keep updating")
            self._idle_since = None
            self._long_idle_log_key = ""

        self._call_on_ui(_done)

    def _refresh_buttons(self) -> None:
        if self._closing:
            return
        try:
            running = self._bot_busy()
            busy = running or self._stopping
            self.start_btn.configure(state="disabled" if busy else "normal")
            self.stop_btn.configure(
                state="normal" if (running and not self._stopping) else "disabled"
            )
            self.map_combo.configure(state="disabled" if busy else "readonly")
        except Exception:
            pass

    def _on_bot_state(self, state: RunState, reason: str) -> None:
        text = state.value.title()
        if reason:
            text = f"{text} — {reason}"

        def _apply() -> None:
            if self._closing:
                return
            self.status_var.set(text)
            self._refresh_buttons()

        self._call_on_ui(_apply)

    def _on_log(self, msg: str) -> None:
        text = str(msg)
        self._call_on_ui(lambda: self._append_log(text))

    def _append_log(self, msg: str) -> None:
        if self._closing:
            return
        try:
            stamp = time.strftime("%H:%M:%S")
            self.log.configure(state="normal")
            self.log.insert("end", f"[{stamp}] {msg}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        except Exception:
            pass

    def _tick_ui(self) -> None:
        if self._closing:
            return
        self._drain_ui_jobs()
        if not self._stopping:
            try:
                self.controller.auto_pause_tick()
            except Exception:
                pass
        # Snapshot + map compose stay off this thread.
        self._request_redraw()
        self._apply_render_outputs()
        try:
            now = time.time()
            last = float(getattr(self, "_hp_hotbar_refresh_at", 0.0) or 0.0)
            if now - last >= 1.0:
                self._hp_hotbar_refresh_at = now
                self._refresh_hp_action_hotbar_keys()
        except Exception:
            pass
        self.after(100, self._tick_ui)

    # ── hotkeys ───────────────────────────────────────────────────────────

    def _bind_hotkeys(self) -> None:
        try:
            import keyboard
        except Exception as exc:
            self._append_log(f"Hotkeys unavailable: {exc}")
            return

        def _start(_e: Any = None) -> None:
            # keyboard hook thread — do not touch Tk here.
            self._call_on_ui(self.start_bot)

        def _stop(_e: Any = None) -> None:
            self._call_on_ui(self.stop_bot)

        try:
            self._hotkey_handles.append(
                keyboard.add_hotkey(_START_HOTKEY, _start, suppress=False)
            )
            self._hotkey_handles.append(
                keyboard.add_hotkey(_STOP_HOTKEY, _stop, suppress=False)
            )
            self._append_log("Hotkeys: Home=start, End=stop")
        except Exception as exc:
            self._append_log(f"Hotkey bind failed: {exc}")

    def _unbind_hotkeys(self) -> None:
        try:
            import keyboard
        except Exception:
            return
        for handle in self._hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self._hotkey_handles.clear()

    def _on_close(self) -> None:
        self._closing = True
        self._stopping = True
        self._stop_render_thread()
        try:
            self._idle_feed.close()
        except Exception:
            pass
        self._unbind_hotkeys()
        try:
            self.controller.remove_debug_watcher()
        except Exception:
            pass
        if self.controller.state != RunState.STOPPED:
            try:
                self.controller.stop(reason="window closed")
            except Exception:
                pass
            threading.Thread(
                target=lambda: (
                    self.controller.wait_stopped(timeout=5.0),
                    self._patches.restore(),
                ),
                daemon=True,
            ).start()
        else:
            try:
                self._patches.restore()
            except Exception:
                pass
        try:
            self.destroy()
        except Exception:
            pass


def run_dungeon_combat() -> int:
    app = DungeonCombatApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_dungeon_combat())
