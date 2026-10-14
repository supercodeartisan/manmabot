"""Dungeon-mode combat policy (ported from dungeon combat tool, behavior-preserving).

Active only when ``is_dungeon_map()``. Island / non-dungeon paths unchanged.

HP recovery matches the field ladder (mother tree, talking scroll, teleport).
Dungeon-only rules that remain:
- Bag-count alone cannot open potion shop (arm required)
- Movement/combat unstick + confined escape OFF
- Blocked-tile / long-IDLE walkable nudges ON
- Emergency PK/surround teleport OFF
- After tree/shop retreat → world-nav re-enter (caller)
"""

from __future__ import annotations

import time
from typing import Any, Optional

from app.bot_log import get_logger

TREE_SHOP_RATIO = 0.30
TP_STEP = 0.05
BLOCKED_RADII = (2, 3)
BLOCKED_GAP_S = 0.5
IDLE_NUDGE_S = 1.5

SCRATCH_POTION_SHOP = "dungeon_allow_potion_shop"
_SCRATCH_BLOCKED_ORIGIN = "dungeon_blocked_origin"
_SCRATCH_BLOCKED_TRIED = "dungeon_blocked_tried"
_SCRATCH_BLOCKED_CLICK_AT = "dungeon_blocked_click_at"
_SCRATCH_IDLE_SINCE = "dungeon_idle_since"
_SCRATCH_IDLE_ORIGIN = "dungeon_idle_origin"
_SCRATCH_IDLE_TRIED = "dungeon_idle_tried"
_SCRATCH_IDLE_CLICK_AT = "dungeon_idle_click_at"

_tp_step_gate: Optional[float] = None
_log = get_logger("hp")


def dungeon_active() -> bool:
    try:
        from app._04_decision.dungeon import is_dungeon_map

        return bool(is_dungeon_map())
    except Exception:
        return False


def reset_tp_ladder() -> None:
    global _tp_step_gate
    _tp_step_gate = None


def arm_potion_shop(blackboard: Any) -> None:
    blackboard.needs_potion = True
    blackboard.scratch[SCRATCH_POTION_SHOP] = True


def _teleport_base_ratio(actions: list | None = None) -> Optional[float]:
    try:
        from app._04_decision import player_mode as pm
        from app._04_decision.hp_actions import action_threshold, normalize_hp_actions

        rows = actions if actions is not None else (pm.HP_ACTIONS or normalize_hp_actions(None))
        return action_threshold(rows, "teleport") or action_threshold(rows, "retreat")
    except Exception:
        return None


def sync_tp_ladder(ratio: Optional[float], actions: list | None = None) -> Optional[float]:
    global _tp_step_gate
    base = _teleport_base_ratio(actions)
    if ratio is None or base is None:
        return _tp_step_gate if _tp_step_gate is not None else base
    if ratio > base:
        _tp_step_gate = None
        return base
    return _tp_step_gate if _tp_step_gate is not None else base


def step_tp_ladder_after_cast(actions: list | None = None) -> None:
    """Kept for callers. Teleport is once per drop under the UI gate, not a ladder."""
    del actions
    return


def potion_restock_needed(state: Any, blackboard: Any) -> bool:
    try:
        from app._04_decision import shops as shops_mod
        from app._04_decision.shop_trip import needs_potion_restock
    except Exception:
        return False
    if not bool(getattr(shops_mod, "RESTOCK_POTIONS", False)):
        return False
    if bool(getattr(blackboard, "needs_potion", False)):
        return needs_potion_restock(blackboard)
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


def mother_tree_row_enabled(actions: list | None = None) -> bool:
    try:
        from app._04_decision import player_mode as pm
        from app._04_decision.behaviors.mode_actions import _hp_action_enabled
        from app._04_decision.hp_actions import normalize_hp_actions

        rows = actions if actions is not None else (pm.HP_ACTIONS or normalize_hp_actions(None))
        return bool(_hp_action_enabled(rows, "mother_tree"))
    except Exception:
        return False


def filter_hp_availability(
    can: dict[str, Any],
    state: Any,
    blackboard: Any,
    *,
    retreat_starters: bool,
) -> dict[str, Any]:
    """Dungeon uses the field HP ladder. Availability is not rewritten."""
    del state, blackboard, retreat_starters
    return dict(can)


def try_tree_or_shop(state: Any, blackboard: Any, ratio: float) -> Any:
    """HP≤30% + potion restock → mother tree else arm potion shop."""
    from app._04_decision.behaviors.mode_actions import HP_RETREAT_STARTED
    from app._04_decision.behavior_tree import Status
    from app._04_decision.mode_control import (
        RETREAT_FOR_HP,
        begin_retreat,
        elf_uses_mother_tree,
    )
    from app._04_decision.shop_trip import tick_shop_trip

    if ratio > TREE_SHOP_RATIO:
        return None
    if not potion_restock_needed(state, blackboard):
        return None
    if mother_tree_row_enabled() and elf_uses_mother_tree(state, blackboard):
        if begin_retreat(blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True):
            blackboard.scratch["hp_retreat_kind"] = "mother_tree"
            _log.info("[던전HP] HP≤30%% + 물약보충 → 월드트리")
            return HP_RETREAT_STARTED
    arm_potion_shop(blackboard)
    _log.info("[던전HP] HP≤30%% + 물약보충 → 상점 출동")
    shop = tick_shop_trip(state, blackboard)
    if shop is not None:
        return shop
    try:
        blackboard.note_no_intent("dungeon HP≤30% shop armed but tick_shop_trip idle")
    except Exception:
        pass
    return Status.SUCCESS


def execute_teleport_dungeon(state: Any, blackboard: Any) -> Any:
    from app._04_decision.behaviors.mode_actions import HP_RETREAT_STARTED
    from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat

    ok = begin_retreat(
        blackboard,
        reason=RETREAT_FOR_HP,
        teleport=True,
        use_mother_tree=False,
        walk_to_safe=False,
    )
    if ok:
        blackboard.scratch["hp_retreat_kind"] = "teleport"
        return HP_RETREAT_STARTED
    return None


def wrap_shop_trip(orig_maybe_shop, state: Any, blackboard: Any) -> Any:
    """Suppress bag-count potion shop unless armed; mid-trip / arrows / sell stay."""
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

    mid = bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))
    armed = bool(blackboard.scratch.get(SCRATCH_POTION_SHOP))
    saved: bool | None = None
    if not mid and not armed:
        saved = bool(getattr(blackboard, "needs_potion", False))
        blackboard.needs_potion = False
    try:
        return orig_maybe_shop(state, blackboard)
    finally:
        if saved is not None:
            blackboard.needs_potion = saved
        if (
            armed
            and not bool(getattr(blackboard, "needs_potion", False))
            and not bool(blackboard.scratch.get(SCRATCH_SHOP_TRIP))
        ):
            blackboard.scratch.pop(SCRATCH_POTION_SHOP, None)


def block_hp_retreat_scroll(blackboard: Any, orig_retreat_scroll) -> Any:
    """Spellbook retreat scrolls stay off. HP safe scroll uses the field path."""
    from app._04_decision.talking_scroll import (
        PURPOSE_SPELLBOOK,
        SCRATCH_RETREAT_SCROLL,
    )

    purpose = str(blackboard.scratch.get(SCRATCH_RETREAT_SCROLL) or "")
    if purpose in {PURPOSE_SPELLBOOK, "spellbook"}:
        blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
        return None
    return orig_retreat_scroll(blackboard)


# ---- blocked / idle nudges -------------------------------------------------

def _pick_walkable(
    terrain: Any,
    origin: tuple[int, int],
    tried: set[tuple[int, int]],
    *,
    radii: tuple[int, ...],
) -> tuple[int, int] | None:
    from app._04_decision.behaviors.unstick import walkable_around

    candidates: list[tuple[int, int]] = []
    for radius in radii:
        for tile in walkable_around(terrain, origin, radius):
            if tile not in tried and tile not in candidates:
                candidates.append(tile)
    if not candidates:
        tried.clear()
        for radius in radii:
            for tile in walkable_around(terrain, origin, radius):
                if tile not in candidates:
                    candidates.append(tile)
    return candidates[0] if candidates else None


def _emit_step(
    blackboard: Any,
    *,
    origin: tuple[int, int],
    tile: tuple[int, int],
    goal: str,
    reason: str,
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
    return Status.SUCCESS


def try_blocked_step(blackboard: Any) -> Any:
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
    if last > 0.0 and (now - last) < BLOCKED_GAP_S:
        from app._04_decision.behavior_tree import Status
        from app._03_world import ActionType

        blackboard.current_goal = "blocked_nudge"
        blackboard.emit(ActionType.IDLE, priority=0.4, reason="dungeon blocked gap")
        return Status.SUCCESS

    tried_raw = blackboard.scratch.get(_SCRATCH_BLOCKED_TRIED) or []
    tried = {tuple(t) for t in tried_raw if isinstance(t, (list, tuple)) and len(t) == 2}
    tile = _pick_walkable(terrain, origin, tried, radii=BLOCKED_RADII)
    if tile is None:
        return None
    tried.add(tile)
    blackboard.scratch[_SCRATCH_BLOCKED_TRIED] = [list(t) for t in tried]
    blackboard.scratch[_SCRATCH_BLOCKED_CLICK_AT] = now
    return _emit_step(
        blackboard,
        origin=origin,
        tile=tile,
        goal="blocked_nudge",
        reason=f"dungeon blocked ({ox},{oy}) -> {tile}",
    )


def try_idle_nudge(blackboard: Any, *, had_intent: bool) -> Any:
    """If stuck IDLE/no-intent ≥1.5s, click a nearby walkable tile."""
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.nav_config import get_terrain_map

    if had_intent:
        blackboard.scratch.pop(_SCRATCH_IDLE_SINCE, None)
        blackboard.scratch.pop(_SCRATCH_IDLE_ORIGIN, None)
        blackboard.scratch.pop(_SCRATCH_IDLE_TRIED, None)
        blackboard.scratch.pop(_SCRATCH_IDLE_CLICK_AT, None)
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
    now = time.time()
    since = float(blackboard.scratch.get(_SCRATCH_IDLE_SINCE) or 0.0)
    if since <= 0.0:
        blackboard.scratch[_SCRATCH_IDLE_SINCE] = now
        blackboard.scratch[_SCRATCH_IDLE_ORIGIN] = list(origin)
        blackboard.scratch[_SCRATCH_IDLE_TRIED] = []
        return None
    if (now - since) < IDLE_NUDGE_S:
        return None

    last = float(blackboard.scratch.get(_SCRATCH_IDLE_CLICK_AT) or 0.0)
    if last > 0.0 and (now - last) < BLOCKED_GAP_S:
        blackboard.current_goal = "idle_nudge"
        blackboard.emit(ActionType.IDLE, priority=0.2, reason="dungeon idle gap")
        return Status.SUCCESS

    tried_raw = blackboard.scratch.get(_SCRATCH_IDLE_TRIED) or []
    tried = {tuple(t) for t in tried_raw if isinstance(t, (list, tuple)) and len(t) == 2}
    # no-intent: allow slightly larger search
    radii = (2, 3, 4, 5)
    tile = _pick_walkable(terrain, origin, tried, radii=radii)
    if tile is None:
        return None
    tried.add(tile)
    blackboard.scratch[_SCRATCH_IDLE_TRIED] = [list(t) for t in tried]
    blackboard.scratch[_SCRATCH_IDLE_CLICK_AT] = now
    return _emit_step(
        blackboard,
        origin=origin,
        tile=tile,
        goal="idle_nudge",
        reason=f"dungeon idle ({ox},{oy}) -> {tile}",
    )


def unstick_disabled() -> bool:
    return dungeon_active()


def emergency_teleport_disabled() -> bool:
    return dungeon_active()
