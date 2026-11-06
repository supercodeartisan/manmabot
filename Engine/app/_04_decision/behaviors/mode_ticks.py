"""L3 mode ladders: traveling / farming / retreating priority order.

Does not emit intents itself except by calling L4/L5. Hierarchy:
``Docs/architecture/DECISION_HIERARCHY.md``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.mode_actions import (
    HP_RETREAT_STARTED,
    apply_hp_actions,
    apply_inplace_hp_support,
    SCRATCH_APPROACH_HOLD_FIRE,
    approach_counterattack,
    clear_approach_hold_tick,
    continue_or_start_loot,
    farm_loot_or_combat,
    hold_fire_outside_hunt,
    maybe_escalate_teleport_to_safe,
    maybe_heal_mp_to_hp_at_tree,
    maybe_mother_tree_before_passive_wait,
    retreat_loot_if_clear,
)
from app._04_decision.behaviors import search as search_beh
from app._04_decision.behaviors.hold_ground import step_party_hold_ground
from app._04_decision.behaviors.party_turret import (
    step_party_turret_idle,
    step_party_turret_leash,
)
from app._04_decision.behaviors.search_hop import emit_search_hop
from app._04_decision.behaviors.travel import (
    clear_travel,
    emit_travel_hop,
    travel_arrived,
)
from app._04_decision import farm_area
from app._04_decision.farm_tour import advance_farm_tour, ensure_farm_tour
from app._04_decision.farm_time import (
    FARM_DURATION_LIMIT,
    farm_time_exceeded,
    reset_farm_timer,
)
from app._04_decision.mode_control import (
    PURPOSE_ENTER_FARM,
    PURPOSE_NEXT_FARM,
    RETREAT_FOR_HP,
    RETREAT_FOR_MP,
    RETREAT_FOR_RETURN,
    begin_retreat,
    begin_travel,
    complete_travel_arrival,
    finish_retreat,
    is_hp_zero,
    is_idle_emergency_hp,
    is_mage_low_mp,
    mark_respawn_clicked,
    needs_return_vitals,
    retreat_exit_ready,
    sample_respawn_click,
    set_mode,
    should_emit_respawn,
    update_death_timer,
    waiting_for_respawn,
)
from app._04_decision.nav_config import (
    get_active_farm,
    get_farm_areas,
    get_terrain_map,
)
from app._04_decision.player_mode import PlayerMode
from app._04_decision import player_mode as pm

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

INVENTORY_FULL_RATIO = 0.50
# After an emergency TELEPORT intent, wait before trying again (visible player).
SCRATCH_EMERGENCY_TP_AT = "emergency_tp_at"
EMERGENCY_TP_COOLDOWN_S = 8.0


def _emit_escape_teleport(
    blackboard: "Blackboard",
    reason: str,
    state: "GameState | None" = None,
) -> Status | None:
    """Emit escape TELEPORT only when the skill can spend mana now.

    Matches HP-path teleport readiness (slot, live hotbar, mana reserve).
    Returns None when the cast would fail a pre-check so callers can fall
    through to talking scroll or another recovery path.
    """
    from app._04_decision.behaviors.mode_actions import _can_teleport_now
    from app._04_decision.spells import mark_slot_used, request_heal_after_teleport

    if not _can_teleport_now(state, blackboard):
        blackboard.retreat_teleport_pending = False
        return None
    from app.bot_log import event

    blackboard.retreat_teleport_pending = False
    request_heal_after_teleport(blackboard)
    mark_slot_used(blackboard, "teleport")
    event("hp", "escape teleport emit: %s", reason)
    blackboard.emit(
        ActionType.TELEPORT,
        priority=0.95,
        reason=reason,
    )
    return Status.SUCCESS


def _note_combat_activity(blackboard: "Blackboard") -> None:
    import time

    from app._04_decision.talking_scroll import SCRATCH_LAST_COMBAT_AT

    blackboard.scratch[SCRATCH_LAST_COMBAT_AT] = time.time()


def _refresh_combat_activity(
    state: "GameState",
    blackboard: "Blackboard",
) -> None:
    """Stamp last-combat time while fighting or near attackable mobs."""
    import time

    from app._04_decision.combat_query import count_attackable
    from app._04_decision.talking_scroll import SCRATCH_LAST_COMBAT_AT

    if blackboard.current_target_id is not None:
        _note_combat_activity(blackboard)
        return
    try:
        n = count_attackable(
            state, origin=blackboard.world_origin, check_path=False,
        )
    except Exception:
        n = 0
    if n > 0:
        _note_combat_activity(blackboard)
        return
    if blackboard.scratch.get(SCRATCH_LAST_COMBAT_AT) is None:
        blackboard.scratch[SCRATCH_LAST_COMBAT_AT] = time.time()


def _maybe_emergency_teleport(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """PK / surround escape via teleport skill (Teleport card).

    A live Player in ``attacks_me`` always tries TELEPORT (hotbar slot
    ready). Visible-player / surround still need the Teleport card flags.
    Survival absolute: shop_trip does not block this path. Failed or
    repeated attempts share a short cooldown so one visible player cannot
    spam TELEPORT every tick ahead of HP actions.
    """
    import time

    from app._04_decision.combat_query import player_attacking_me
    from app._04_decision.dungeon_policy import emergency_teleport_disabled

    pk = None
    try:
        pk = player_attacking_me(state)
    except Exception:
        pk = None

    reason = ""
    if pk:
        name = str(pk.get("name") or "").strip() or "?"
        reason = f"escape teleport (player attacking me {name})"
    else:
        if emergency_teleport_disabled():
            return None
        if not pm.RANDOM_TELEPORT_ENABLED:
            return None
        if not (pm.TELEPORT_ON_PLAYER or pm.TELEPORT_WHEN_SURROUNDED):
            return None
        if pm.TELEPORT_ON_PLAYER:
            try:
                players = state.players()
            except Exception:
                players = []
            if players:
                reason = "escape teleport (other player visible)"
        if not reason and pm.TELEPORT_WHEN_SURROUNDED:
            from app._04_decision.combat_query import count_monsters_within_tiles

            try:
                n = count_monsters_within_tiles(state, int(pm.SURROUND_TILES))
            except Exception:
                n = 0
            if n >= int(pm.SURROUND_MONSTER_COUNT):
                reason = f"escape teleport (surrounded x{n})"
        if not reason:
            return None

    from app._05_action.spell_box import slot_is_enabled

    if not slot_is_enabled("teleport"):
        return None

    now = time.time()
    last = float(blackboard.scratch.get(SCRATCH_EMERGENCY_TP_AT) or 0.0)
    if last and (now - last) < float(EMERGENCY_TP_COOLDOWN_S):
        from app.bot_log import get_logger

        get_logger("hp").debug(
            "emergency TP on cooldown remain=%.1fs",
            float(EMERGENCY_TP_COOLDOWN_S) - (now - last),
        )
        return None
    from app.bot_log import get_logger

    result = _emit_escape_teleport(blackboard, reason, state)
    if result is Status.SUCCESS:
        blackboard.scratch[SCRATCH_EMERGENCY_TP_AT] = now
        get_logger("hp").info("emergency TP fired: %s", reason)
    else:
        get_logger("hp").warning(
            "emergency TP skipped (mana/hotbar/slot): %s", reason
        )
    return result


def _maybe_return_on_vitals(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """Fix/Return HP/MP 귀환 — prefer talking scroll, never random TP."""
    if blackboard.player_mode is PlayerMode.RETREATING:
        return False
    from app._04_decision.shop_trip import shopping_blocks_teleport

    if shopping_blocks_teleport(blackboard):
        return False
    if not needs_return_vitals(state):
        return False
    begin_retreat(
        blackboard,
        reason=RETREAT_FOR_RETURN,
        prefer_scroll=True,
        allow_teleport=False,
        use_mother_tree=False,
    )
    return True


def _maybe_return_on_idle(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """Fix/Return after configured seconds out of combat."""
    import time

    if not pm.RETURN_IDLE_ENABLED:
        return False
    if blackboard.player_mode is PlayerMode.RETREATING:
        return False
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app._04_decision.talking_scroll import (
        SCRATCH_LAST_COMBAT_AT,
        SCRATCH_POST_SHOP_RETURN,
        SCRATCH_SHOP_TRIP,
    )

    if shopping_blocks_teleport(blackboard):
        return False
    if blackboard.scratch.get(SCRATCH_SHOP_TRIP) or blackboard.scratch.get(
        SCRATCH_POST_SHOP_RETURN
    ):
        return False
    _refresh_combat_activity(state, blackboard)
    last = blackboard.scratch.get(SCRATCH_LAST_COMBAT_AT)
    if last is None:
        return False
    if time.time() - float(last) < float(pm.RETURN_IDLE_SECONDS):
        return False
    begin_retreat(
        blackboard,
        reason=RETREAT_FOR_RETURN,
        prefer_scroll=True,
        allow_teleport=False,
        use_mother_tree=False,
    )
    # Reset so a failed retreat does not spam every tick.
    blackboard.scratch[SCRATCH_LAST_COMBAT_AT] = time.time()
    return True


def _drive_world_nav(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Advance world-nav session; walk phase may yield to combat/loot.

    During ``walk``, combat/loot runs *before* nav hop advance so sticky
    engage is not starved by world-nav waypoint clicks every tick.
    A hunt-rect or dungeon-entrance arrival finishes before that, so the
    leftover walk to the center never starts.
    """
    from app._04_decision.world_nav.hooks import finish_hunt_edge_arrival

    if finish_hunt_edge_arrival(state, blackboard):
        return None
    from app._04_decision.world_nav import (
        SCRATCH_NEED_WORLD_NAV,
        SCRATCH_ROUTINE_KIND,
        SCRATCH_WORLD_NAV,
        ensure_world_nav_mode,
        leave_world_nav_mode_if_idle,
        tick_world_nav,
    )

    session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)
    phase = getattr(session, "phase", None) if session is not None else None
    if phase == "walk" or (
        phase == "gate_approach" and hold_fire_outside_hunt(state, blackboard)
    ):
        if hold_fire_outside_hunt(state, blackboard):
            fought = approach_counterattack(state, blackboard)
        else:
            fought = farm_loot_or_combat(
                state, blackboard, restrict_to_farm=False
            )
        if fought is not None:
            if session is not None or need:
                ensure_world_nav_mode(blackboard)
            return fought

    status = tick_world_nav(state, blackboard)
    session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)
    if session is not None or need:
        ensure_world_nav_mode(blackboard)
    phase = getattr(session, "phase", None) if session is not None else None
    # ready→walk this tick: overlay once after the first hop is armed.
    if phase == "walk":
        if hold_fire_outside_hunt(state, blackboard):
            fought = approach_counterattack(state, blackboard)
        else:
            fought = farm_loot_or_combat(
                state, blackboard, restrict_to_farm=False
            )
        if fought is not None:
            return fought
    if status is not None:
        return status
    if str(blackboard.scratch.get(SCRATCH_ROUTINE_KIND) or "") == "break":
        blackboard.current_goal = "routine_break"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="routine break wait",
        )
        return Status.SUCCESS
    leave_world_nav_mode_if_idle(blackboard)
    return None


def _maybe_world_nav(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Farming entry: duration/need → hand off to ``PlayerMode.WORLD_NAV``."""
    from app._04_decision.world_nav import (
        SCRATCH_NEED_WORLD_NAV,
        SCRATCH_ROUTINE_KIND,
        SCRATCH_WORLD_NAV,
        ensure_world_nav_mode,
        tick_world_nav,
    )

    status = tick_world_nav(state, blackboard)
    session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)
    if session is not None or need:
        ensure_world_nav_mode(blackboard)
        if blackboard.intent is not None:
            return Status.SUCCESS
        if status is not None:
            return status
        return Status.FAILURE
    if str(blackboard.scratch.get(SCRATCH_ROUTINE_KIND) or "") == "break":
        blackboard.current_goal = "routine_break"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="routine break wait",
        )
        return Status.SUCCESS
    return None


def _maybe_post_shop_farm_return(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """After buying goods: world-nav back to active routine hunt entry."""
    from app._04_decision.talking_scroll import SCRATCH_POST_SHOP_RETURN
    from app._04_decision.world_nav import begin_world_nav

    del state
    if not blackboard.scratch.get(SCRATCH_POST_SHOP_RETURN):
        return None
    farm = get_active_farm(blackboard.farm_area_index)
    ox, oy = blackboard.world_origin.x, blackboard.world_origin.y
    if farm is not None and farm.contains(ox, oy):
        blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
        return None

    blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
    begin_world_nav(blackboard, "post_shop")
    return Status.FAILURE


def _maybe_scroll_to_hunt_map(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Off hunt map → enter ``WORLD_NAV`` toward active routine destination."""
    from app._04_decision.nav_config import navigation_configure_in_progress
    from app._04_decision.talking_scroll import (
        SCRATCH_SCROLL_ARRIVAL,
        SCRATCH_SHOP_TRIP,
        player_on_selected_map,
    )
    from app._04_decision.world_nav import (
        SCRATCH_WORLD_NAV,
        begin_world_nav,
    )

    del state
    if blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        return None
    if blackboard.scratch.get("mother_tree_trip"):
        return None
    if blackboard.scratch.get(SCRATCH_SCROLL_ARRIVAL):
        return None
    if blackboard.scratch.get(SCRATCH_WORLD_NAV) is not None:
        return None
    if navigation_configure_in_progress():
        return None
    if player_on_selected_map(blackboard):
        return None
    from app._04_decision.dungeon_floor_route import inside_target_dungeon

    # Same complex, deeper floor: floor route owns the walk. Other maps still
    # arm world nav.
    if inside_target_dungeon(blackboard):
        return None
    begin_world_nav(blackboard, "hunt_map")
    return Status.FAILURE


def _maybe_support_spells(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    allow_buffs: bool,
) -> Status | None:
    from app._04_decision.spells import maybe_cast_buff, maybe_heal_after_teleport

    heal = maybe_heal_after_teleport(state, blackboard)
    if heal is not None:
        return heal
    if not allow_buffs:
        return None
    return maybe_cast_buff(state, blackboard)


def _maybe_low_mp_to_safe(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """Mage MP ≤ 15% → talking-scroll to a safe landing, or teleport + walk.

    Elves do not retreat on low MP (Mother Tree is critical HP only).
    """
    if blackboard.player_mode is PlayerMode.RETREATING:
        return False
    from app._04_decision.shop_trip import shopping_blocks_teleport

    if shopping_blocks_teleport(blackboard):
        return False
    if not is_mage_low_mp(state):
        return False
    begin_retreat(
        blackboard,
        reason=RETREAT_FOR_MP,
        use_mother_tree=False,
    )
    return True


# Wall-clock of the last Teleport to Mother press. Buff absence is judged
# only after this settle, so a slow buff_listen read is not a miss.
_SCRATCH_MOTHER_TREE_CAST_AT = "mother_tree_cast_at"
_MOTHER_TREE_BUFF_SETTLE_S = 2.0
# Catalog cost of 텔레포트 투 마더. Used when the cost table has no row.
_MOTHER_TREE_RECAST_MP = 10


def _emit_return_to_mother_tree(
    blackboard: "Blackboard",
    state: "GameState | None" = None,
    *,
    remember_depart: bool = False,
) -> Status:
    """Press Teleport to Mother once and start the 2 s buff settle."""
    import time

    from app._04_decision.spells import mark_slot_used
    from app._04_decision.world_nav.hooks import remember_mother_tree_depart

    if remember_depart and state is not None:
        remember_mother_tree_depart(blackboard, state)
    mark_slot_used(blackboard, "mother_tree")
    blackboard.scratch[_SCRATCH_MOTHER_TREE_CAST_AT] = time.time()
    blackboard.scratch["mother_tree_trip"] = "recharge"
    blackboard.current_goal = "mother_tree"
    blackboard.emit(
        ActionType.RETURN_TO_MOTHER_TREE,
        priority=0.95,
        reason="return to mother tree",
    )
    return Status.SUCCESS


def _mother_tree_idle(blackboard: "Blackboard", reason: str) -> Status:
    blackboard.current_goal = "mother_tree"
    blackboard.emit(ActionType.IDLE, priority=0.95, reason=reason)
    return Status.SUCCESS


def _mother_tree_recast_mp_ok(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """True when current MP can pay another Teleport to Mother."""
    from app._04_decision.behaviors.mode_actions import current_mp
    from app._04_decision.spells import spell_mp_cost_for_role

    mp = current_mp(state)
    if mp is None:
        return False
    cost = spell_mp_cost_for_role("mother_tree", state, blackboard)
    if cost is None:
        cost = _MOTHER_TREE_RECAST_MP
    return int(mp) >= int(cost)


def _hold_until_world_tree_blessing(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Recast Teleport to Mother until 세계수의 가호 is on a settled buff read.

    Arrival is buff-gated (not live xy). None when the aura is up, or the
    skill can no longer be used, so the caller continues heal / Body to Mind /
    standing. Low MP waits on this retreat. It does not clear the trip.
    """
    import time

    from app._04_decision.mode_control import elf_uses_mother_tree
    from app._04_decision.spells import _memory_buffs_ready, world_tree_blessing_active
    from app.bot_log import get_logger

    if world_tree_blessing_active(state):
        return None
    if not elf_uses_mother_tree(state, blackboard):
        return None

    cast_at = blackboard.scratch.get(_SCRATCH_MOTHER_TREE_CAST_AT)
    try:
        cast_at_f = float(cast_at) if cast_at is not None else None
    except (TypeError, ValueError):
        cast_at_f = None
    if cast_at_f is None or (time.time() - cast_at_f) < _MOTHER_TREE_BUFF_SETTLE_S:
        return _mother_tree_idle(blackboard, "waiting for world tree blessing")
    if not _memory_buffs_ready(state):
        return _mother_tree_idle(blackboard, "waiting for world tree blessing")
    if not _mother_tree_recast_mp_ok(state, blackboard):
        return _mother_tree_idle(blackboard, "waiting for mother tree mp")
    get_logger("hp").info("mother tree blessing missing, recast teleport to mother")
    return _emit_return_to_mother_tree(blackboard, state)


def _tick_mother_tree_retreat(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Elf Mother Tree: cast, confirm 세계수의 가호, then recharge until HP≥95%.

    One press is not arrival. Until HP is high enough to leave, a settled
    buff read with no blessing presses Teleport to Mother again while MP
    can pay it. MP below that cost waits. HP≥95% leaves even without the aura.
    """
    stage = blackboard.scratch.get("mother_tree_trip")
    if not stage:
        return None

    if stage == "scroll":
        finish_retreat(blackboard)
        return Status.FAILURE

    from app._04_decision.spells import maybe_hp_to_mp_at_tree
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import hp_ratio

    if stage == "cast":
        from app._04_decision.world_nav.hooks import SCRATCH_MOTHER_TREE_DEPART

        # First press of this retreat. A recast must not replace the hunt pose.
        blackboard.scratch.pop(SCRATCH_MOTHER_TREE_DEPART, None)
        return _emit_return_to_mother_tree(
            blackboard, state, remember_depart=True
        )

    # Recovered HP ends the retreat before another mother-tree press.
    ratio = hp_ratio(state)
    if ratio is not None and ratio >= float(pm.HP_ALMOST_FULL_RATIO):
        finish_retreat(blackboard)
        return Status.FAILURE

    held = _hold_until_world_tree_blessing(state, blackboard)
    if held is not None:
        return held

    # Aura is up (or the skill can no longer be used): heal / Body to Mind.
    healed = maybe_heal_mp_to_hp_at_tree(state, blackboard)
    if healed is not None:
        return healed

    convert = maybe_hp_to_mp_at_tree(state, blackboard)
    if convert is not None:
        return convert

    blackboard.current_goal = "mother_tree"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.95,
        reason="recharging at mother tree",
    )
    return Status.SUCCESS


def _maybe_retreat_talking_scroll(
    blackboard: "Blackboard",
) -> Status | None:
    """Emit one talking-scroll hop to a safe list landing, then stand still."""
    from app._04_decision.dungeon_policy import dungeon_active
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        PURPOSE_SPELLBOOK,
        PURPOSE_TRAINING,
        RETREAT_SCROLL_LABELS,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_RETREAT_SCROLL,
        emit_talking_scroll,
        pick_hp_safe_scroll_spot,
        talking_scroll_available,
    )

    purpose = blackboard.scratch.get(SCRATCH_RETREAT_SCROLL)
    if not purpose:
        return None
    # Spellbook / training retreat scrolls stay off in dungeons. HP safe scroll
    # follows the field ladder (mother tree, then talking scroll, then teleport).
    if dungeon_active() and str(purpose) in {
        PURPOSE_SPELLBOOK,
        PURPOSE_TRAINING,
        "spellbook",
    }:
        blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
        return None
    if not talking_scroll_available():
        blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
        return None
    label = RETREAT_SCROLL_LABELS.get(str(purpose), str(purpose))
    spot_id = None
    if str(purpose) == HP_SAFE_SCROLL_PURPOSE:
        spot_id = pick_hp_safe_scroll_spot(blackboard)
        label = str(spot_id)
    if emit_talking_scroll(
        blackboard,
        purpose=str(purpose),
        spot_id=spot_id,
        reason=f"retreat, {label}",
    ) is Status.SUCCESS:
        blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
        if str(purpose) == HP_SAFE_SCROLL_PURPOSE:
            blackboard.scratch[SCRATCH_HP_SAFE_SCROLLED] = True
        # Scroll changes map; do not resume a walk from the old farm.
        blackboard.scratch.pop("retreat_nav_goal", None)
        blackboard.scratch.pop("retreat_travel_purpose", None)
        clear_travel(blackboard)
        return Status.SUCCESS
    blackboard.current_goal = "talking_scroll"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.95,
        reason="waiting for talking scroll",
    )
    return Status.SUCCESS


def _maybe_death(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Death screen before heal / combat / travel on every mode.

    Island farming used to skip this: HP=0 looked like critical HP, so heal
    clicked the corpse (world origin) instead of 다시 시작.
    """
    update_death_timer(blackboard, state)
    if should_emit_respawn(blackboard, state):
        blackboard.current_goal = "respawn"
        mark_respawn_clicked(blackboard)
        blackboard.emit(
            ActionType.RESPAWN,
            destination=sample_respawn_click(),
            priority=1.0,
            reason="death confirmed, restart",
        )
        return Status.SUCCESS
    if waiting_for_respawn(blackboard, state) or is_hp_zero(state):
        blackboard.emit(
            ActionType.IDLE,
            priority=0.95,
            reason="waiting for respawn",
        )
        return Status.SUCCESS
    return None


def _maybe_dungeon_death(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Same death gate; kept so existing dungeon tests can patch this name."""
    return _maybe_death(state, blackboard)


def _step_survival_hp(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    hp_act = apply_hp_actions(state, blackboard)
    if hp_act is HP_RETREAT_STARTED:
        return tick_retreating(state, blackboard)
    return hp_act


def _step_handoff_retreat_if(
    predicate, state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    if predicate(state, blackboard):
        return tick_retreating(state, blackboard)
    return None


def _step_spell_support(
    state: "GameState", blackboard: "Blackboard", *, allow_buffs: bool
) -> Status | None:
    return _maybe_support_spells(state, blackboard, allow_buffs=allow_buffs)


def _step_farm_engage(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    if hold_fire_outside_hunt(state, blackboard):
        result = approach_counterattack(state, blackboard)
        if result is not None:
            _refresh_combat_activity(state, blackboard)
        return result
    result = farm_loot_or_combat(state, blackboard, restrict_to_farm=False)
    if result is not None:
        _refresh_combat_activity(state, blackboard)
    return result


def _step_retreat_teleport(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED

    blackboard.current_goal = "retreating"
    if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
        blackboard.retreat_teleport_pending = False
    if not blackboard.retreat_teleport_pending:
        return None
    from app._04_decision.behaviors.mode_actions import (
        _can_teleport_now,
        arm_hp_escape_fallback,
    )
    from app._05_action.spell_box import slot_is_enabled

    if shopping_blocks_teleport(blackboard):
        blackboard.retreat_teleport_pending = False
        return None
    if not slot_is_enabled("teleport") or not _can_teleport_now(state, blackboard):
        blackboard.retreat_teleport_pending = False
        fallback = arm_hp_escape_fallback(state, blackboard)
        if fallback is HP_RETREAT_STARTED:
            return _tick_mother_tree_retreat(state, blackboard)
        return fallback
    return _emit_escape_teleport(blackboard, "retreat teleport", state)


def _step_retreat_escalate(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    if maybe_escalate_teleport_to_safe(state, blackboard):
        return _maybe_retreat_talking_scroll(blackboard)
    return None


def _step_retreat_post_land_tree(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    post_land_tree = maybe_mother_tree_before_passive_wait(state, blackboard)
    if post_land_tree is HP_RETREAT_STARTED:
        return _tick_mother_tree_retreat(state, blackboard)
    return post_land_tree


def _step_retreat_inplace_hp(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    support = apply_inplace_hp_support(state, blackboard)
    if support is HP_RETREAT_STARTED:
        hop = _maybe_retreat_talking_scroll(blackboard)
        if hop is not None:
            return hop
        if blackboard.retreat_teleport_pending:
            hopped = _emit_escape_teleport(
                blackboard, "natural recover under attack", state
            )
            if hopped is not None:
                return hopped
            blackboard.retreat_teleport_pending = False
        if blackboard.nav_goal is not None and emit_travel_hop(
            blackboard, reason="retreat to safe area", priority=0.95
        ):
            return Status.SUCCESS
        return Status.SUCCESS
    return support


def _step_retreat_walk_safe(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    del state
    if blackboard.nav_goal is not None and emit_travel_hop(
        blackboard, reason="retreat to safe area", priority=0.95
    ):
        return Status.SUCCESS
    return None


def _step_retreat_idle_emergency(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app._04_decision.talking_scroll import talking_scroll_available

    if (
        not talking_scroll_available()
        and not shopping_blocks_teleport(blackboard)
        and not blackboard.scratch.get("mother_tree_trip")
        and is_idle_emergency_hp(state)
        and begin_retreat(
            blackboard,
            reason=RETREAT_FOR_HP,
            teleport=True,
            exclude_current_safe=True,
        )
    ):
        hop = _maybe_retreat_talking_scroll(blackboard)
        if hop is not None:
            return hop
        if blackboard.retreat_teleport_pending:
            hopped = _emit_escape_teleport(
                blackboard, "idle emergency teleport", state
            )
            if hopped is not None:
                return hopped
            blackboard.retreat_teleport_pending = False
        if blackboard.nav_goal is not None and emit_travel_hop(
            blackboard, reason="retreat to other safe", priority=0.95
        ):
            return Status.SUCCESS
    return None


def _step_retreat_wait(
    state: "GameState", blackboard: "Blackboard"
) -> Status:
    del state
    wait_reason = (
        "retreating, waiting for mp"
        if blackboard.scratch.get("retreat_for") == RETREAT_FOR_MP
        else "retreating, waiting for hp"
    )
    blackboard.emit(
        ActionType.IDLE,
        priority=0.95,
        reason=wait_reason,
    )
    return Status.SUCCESS


def _step_retreat_exit(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    from app._04_decision.behaviors.mode_actions import (
        HP_RETREAT_STARTED,
        maybe_hp_return_while_retreating,
    )

    started = maybe_hp_return_while_retreating(state, blackboard)
    if started is HP_RETREAT_STARTED:
        return _tick_mother_tree_retreat(state, blackboard)
    if started is not None:
        return started
    if retreat_exit_ready(blackboard, state):
        finish_retreat(blackboard)
        return Status.FAILURE
    return None


def _handlers_retreating() -> dict:
    return {
        "survival.death": _maybe_death,
        "retreat.mother_tree": _tick_mother_tree_retreat,
        "retreat.exit": _step_retreat_exit,
        "retreat.scroll": lambda s, b: _maybe_retreat_talking_scroll(b),
        "retreat.teleport": _step_retreat_teleport,
        "retreat.escalate_safe": _step_retreat_escalate,
        "retreat.post_land_tree": _step_retreat_post_land_tree,
        "spell.support": lambda s, b: _step_spell_support(s, b, allow_buffs=False),
        "survival.inplace_hp": _step_retreat_inplace_hp,
        "retreat.loot_if_clear": retreat_loot_if_clear,
        "retreat.walk_safe": _step_retreat_walk_safe,
        "retreat.idle_emergency": _step_retreat_idle_emergency,
        "retreat.wait": _step_retreat_wait,
    }


def tick_retreating(state: "GameState", blackboard: "Blackboard") -> Status:
    """L3 column ``RETREATING`` (Docs/architecture/DECISION_STEPS.md)."""
    from app._04_decision.steps import RETREATING, run_column

    status = run_column(RETREATING, _handlers_retreating(), state, blackboard)
    return status if status is not None else Status.FAILURE


def _enter_farm_travel(blackboard: "Blackboard") -> bool:
    """True when traveling to enter / rotate into a farm area."""
    return blackboard.travel_purpose in (PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM)


def _patrol_travel(blackboard: "Blackboard") -> bool:
    from app._04_decision.patrol import PURPOSE_PATROL

    return blackboard.travel_purpose == PURPOSE_PATROL


def _dungeon_floor_travel(blackboard: "Blackboard") -> bool:
    from app._04_decision.dungeon_floor_route import PURPOSE_DUNGEON_FLOOR

    return blackboard.travel_purpose == PURPOSE_DUNGEON_FLOOR


def _maybe_confined_escape(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Teleport / talking scroll after 13 s inside a 3-tile bubble.

    Movement / search / loot-walk only. Attacking a living sticky target
    clears the bubble clock so fight time does not count toward 13 s, and
    must not fire TP or talking scroll mid-fight.
    """
    from app._04_decision.behaviors.combat import continue_sticky_combat
    from app._04_decision.behaviors.unstick import (
        reset_confined_progress,
        try_confined_escape,
    )
    from app._04_decision.shop_trip import shopping_blocks_teleport

    if shopping_blocks_teleport(blackboard):
        reset_confined_progress(blackboard)
        return None
    if continue_sticky_combat(state, blackboard):
        # Pause: wall-clock must not accumulate while we are mid-kill.
        reset_confined_progress(blackboard)
        return None
    if try_confined_escape(blackboard, state):
        return Status.SUCCESS
    return None


# World-nav walks only. Scroll, settle, NPC teleporter, and gate click stand
# on purpose and must not burn a teleport.
_WORLD_NAV_CONFINE_HOLD = "world_nav_confine_hold"
_WORLD_NAV_CONFINE_PHASES = frozenset({"walk", "gate_approach"})
_WORLD_NAV_CONFINE_HOLD_S = 12.0


def _world_nav_confine_left(state: "GameState", blackboard: "Blackboard", hold: dict) -> bool:
    """True once the cast has left the 3-tile bubble or the map."""
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision import player_mode as pm
    from app._04_decision.world_nav.session import live_pose_from_state

    ax, ay = int(hold.get("x") or 0), int(hold.get("y") or 0)
    if tile_chebyshev(
        int(blackboard.world_origin.x),
        int(blackboard.world_origin.y),
        ax,
        ay,
    ) > int(pm.UNSTICK_CONFINED_TILES):
        return True
    pose = live_pose_from_state(state)
    anchor_map = hold.get("map_id")
    if (
        pose is not None
        and anchor_map is not None
        and int(pose.map_id) != int(anchor_map)
    ):
        return True
    return False


def _world_nav_at_hunt_edge(state: "GameState", blackboard: "Blackboard", session: object) -> bool:
    """Arrival belongs to the drive step. Do not teleport off the destination."""
    from app._04_decision.world_nav.hooks import SCRATCH_ROUTINE
    from app._04_decision.world_nav.routine import pose_hunt_arrival
    from app._04_decision.world_nav.session import live_pose_from_state

    if getattr(session, "phase", None) != "walk":
        return False
    cursor = blackboard.scratch.get(SCRATCH_ROUTINE)
    entry = cursor.active() if cursor is not None else None
    if entry is None:
        return False
    pose = live_pose_from_state(state)
    if pose is None:
        return False
    return bool(
        pose_hunt_arrival(
            pose, entry, blackboard, reason=str(getattr(session, "reason", "") or "")
        )
    )


def _maybe_world_nav_confined(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """13 s / 3 tiles during a world-nav walk, then the same teleport or scroll.

    The live plan is dropped. After the pose leaves that bubble the same
    routine reason is requested again, so the next plan starts from the
    landing and still aims at the row that was in progress. Scroll, NPC
    teleporter, and gate-click phases do not start the clock.
    """
    import time

    from app._04_decision.behaviors.unstick import reset_confined_progress
    from app._04_decision.dungeon_policy import unstick_disabled
    from app._04_decision.world_nav.hooks import (
        SCRATCH_WORLD_NAV,
        _drop_world_nav_session,
        request_world_nav,
    )
    from app._04_decision.world_nav.session import live_pose_from_state
    from app.bot_log import get_logger

    hold = blackboard.scratch.get(_WORLD_NAV_CONFINE_HOLD)
    if isinstance(hold, dict):
        since = float(hold.get("since") or 0.0)
        left = _world_nav_confine_left(state, blackboard, hold)
        timed_out = since > 0.0 and (time.time() - since) >= _WORLD_NAV_CONFINE_HOLD_S
        if left or timed_out:
            reason = str(hold.get("reason") or "start")
            blackboard.scratch.pop(_WORLD_NAV_CONFINE_HOLD, None)
            request_world_nav(blackboard, reason)
            get_logger("nav").info(
                "world nav confined resume reason=%s how=%s",
                reason,
                "land" if left else "timeout",
            )
            return None
        blackboard.current_goal = "world_nav"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.4,
            reason="world nav confined wait",
        )
        return Status.SUCCESS

    session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    if session is None:
        return None
    phase = str(getattr(session, "phase", "") or "")
    if phase not in _WORLD_NAV_CONFINE_PHASES or unstick_disabled():
        reset_confined_progress(blackboard)
        return None
    if _world_nav_at_hunt_edge(state, blackboard, session):
        return None
    status = _maybe_confined_escape(state, blackboard)
    if status is None:
        return None
    pose = live_pose_from_state(state)
    reason = str(getattr(session, "reason", "") or "start")
    blackboard.scratch[_WORLD_NAV_CONFINE_HOLD] = {
        "reason": reason,
        "map_id": None if pose is None else int(pose.map_id),
        "x": int(blackboard.world_origin.x),
        "y": int(blackboard.world_origin.y),
        "since": time.time(),
    }
    _drop_world_nav_session(blackboard)
    from app._04_decision.talking_scroll import SCRATCH_UNSTICK_SCROLL_RETURN

    # Farming reads this after a mainland unstick scroll. World nav already
    # resumes the same row, so leaving the flag would idle outside the farm.
    blackboard.scratch.pop(SCRATCH_UNSTICK_SCROLL_RETURN, None)
    get_logger("nav").info(
        "world nav confined escape reason=%s phase=%s anchor=(%s,%s) map=%s",
        reason,
        phase,
        int(blackboard.world_origin.x),
        int(blackboard.world_origin.y),
        "-" if pose is None else int(pose.map_id),
    )
    return Status.SUCCESS


def tick_traveling(state: "GameState", blackboard: "Blackboard") -> Status:
    """L3 column `TRAVELING` — implementation after farm-entry helpers."""
    return _tick_traveling_column(state, blackboard)


def _should_push_deeper_into_farm(blackboard: "Blackboard") -> bool:
    purpose = blackboard.travel_purpose
    if purpose not in (PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM):
        return False
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is None:
        return False
    ox, oy = blackboard.world_origin.x, blackboard.world_origin.y
    if farm.contains(ox, oy):
        return False
    # Only intervene when we would otherwise treat travel as finished.
    return blackboard.nav_goal is None or travel_arrived(blackboard)


def _retarget_farm_entry(blackboard: "Blackboard") -> bool:
    """Point nav_goal at an inset walkable tile; keep TRAVELING purpose."""
    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()
    if farm is None or terrain is None:
        return False
    start = (blackboard.world_origin.x, blackboard.world_origin.y)
    goal = farm.interior_walkable(terrain, start, margin=farm_area.ARRIVE_TILES)
    if goal is None:
        return False
    purpose = blackboard.travel_purpose or PURPOSE_ENTER_FARM
    reason = str(blackboard.scratch.get("travel_reason") or "enter farm area")
    begin_travel(blackboard, goal, purpose=purpose, reason=reason)
    return True



def _step_travel_training_done(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    from app._04_decision.species_rules import is_newbie_player
    from app._04_decision.talking_scroll import PURPOSE_TRAINING, SCRATCH_NEWBIE_TRAINING

    if blackboard.travel_purpose == PURPOSE_TRAINING and not is_newbie_player(state):
        clear_travel(blackboard)
        blackboard.travel_purpose = None
        blackboard.scratch.pop(SCRATCH_NEWBIE_TRAINING, None)
        set_mode(blackboard, PlayerMode.FARMING)
        blackboard.note_no_intent("training_done->farming (no emit)")
        return Status.FAILURE
    return None


def _step_travel_hunt_map(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    if (
        _enter_farm_travel(blackboard)
        or _patrol_travel(blackboard)
        or _dungeon_floor_travel(blackboard)
    ):
        return _maybe_scroll_to_hunt_map(state, blackboard)
    return None


def _step_travel_entered_farm(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Inside the hunt rect, farm search takes over. The center is not a goal."""
    del state
    if blackboard.travel_purpose not in (PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM):
        return None
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is None:
        return None
    ox, oy = int(blackboard.world_origin.x), int(blackboard.world_origin.y)
    if not farm.contains(ox, oy):
        return None
    complete_travel_arrival(blackboard)
    blackboard.note_no_intent("entered farm rect -> farming")
    return Status.FAILURE


def _step_travel_engage(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    if (
        _enter_farm_travel(blackboard)
        or _patrol_travel(blackboard)
        or _dungeon_floor_travel(blackboard)
    ):
        if _enter_farm_travel(blackboard) and hold_fire_outside_hunt(
            state, blackboard
        ):
            return approach_counterattack(state, blackboard)
        return farm_loot_or_combat(state, blackboard, restrict_to_farm=False)
    return None


def _step_travel_push_deeper(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    del state
    if not _should_push_deeper_into_farm(blackboard):
        return None
    if not _retarget_farm_entry(blackboard):
        return None
    reason = str(blackboard.scratch.get("travel_reason") or "enter farm area")
    blackboard.current_goal = "traveling"
    if emit_travel_hop(blackboard, reason=reason, priority=0.55):
        return Status.SUCCESS
    blackboard.current_goal = "enter_farm"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.55,
        reason="enter farm, path blocked",
    )
    return Status.SUCCESS


def _step_travel_arrive(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    del state
    if not (travel_arrived(blackboard) or blackboard.nav_goal is None):
        return None
    purpose = blackboard.travel_purpose
    prev_nav = blackboard.nav_goal
    complete_travel_arrival(blackboard)
    nxt = blackboard.nav_goal
    if nxt is not None:
        blackboard.note_no_intent(
            f"travel_arrived purpose={purpose} nav={prev_nav} "
            f"-> next_nav={nxt} (handoff, no emit yet)"
        )
    else:
        blackboard.note_no_intent(
            f"travel_arrived purpose={purpose} nav={prev_nav} "
            f"-> farming (handoff, no emit)"
        )
    return Status.FAILURE


def _step_travel_hop(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    reason = str(blackboard.scratch.get("travel_reason") or "traveling")
    blackboard.current_goal = "traveling"
    if emit_travel_hop(blackboard, reason=reason, priority=0.55, state=state):
        return Status.SUCCESS
    return None


def _step_travel_hop_fail(
    state: "GameState", blackboard: "Blackboard"
) -> Status:
    del state
    hop_miss = str(blackboard.scratch.get("travel_hop_miss") or "hop_false")
    reason = str(blackboard.scratch.get("travel_reason") or "traveling")
    if travel_arrived(blackboard):
        if _should_push_deeper_into_farm(blackboard) and _retarget_farm_entry(
            blackboard
        ):
            if emit_travel_hop(blackboard, reason=reason, priority=0.55):
                return Status.SUCCESS
            blackboard.emit(
                ActionType.IDLE,
                priority=0.55,
                reason="enter farm, path blocked",
            )
            return Status.SUCCESS
        purpose = blackboard.travel_purpose
        complete_travel_arrival(blackboard)
        blackboard.note_no_intent(
            f"emit_travel_hop miss={hop_miss} + arrived purpose={purpose} "
            f"-> complete_arrival (no emit)"
        )
    else:
        purpose = blackboard.travel_purpose
        clear_travel(blackboard)
        set_mode(blackboard, PlayerMode.FARMING)
        blackboard.note_no_intent(
            f"emit_travel_hop miss={hop_miss} purpose={purpose} "
            f"-> abandon_travel->farming (no emit)"
        )
    return Status.FAILURE


def _maybe_routine_duration(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """TRAVELING: schedule minutes up → drop patrol and arm the next routine row.

    Shopping must not call this (in-flight buy/sell stays until shop_ok). Sell
    after advance still runs via WORLD_NAV/TRAVELING ``shop.trip`` when the bag
    is overweight before a break stay.
    """
    del state
    from app._04_decision.world_nav import (
        SCRATCH_NEED_WORLD_NAV,
        SCRATCH_WORLD_NAV,
        ensure_world_nav_mode,
        take_next_routine_if_due,
    )

    if not take_next_routine_if_due(blackboard):
        return None
    ensure_world_nav_mode(blackboard)
    if blackboard.scratch.get(SCRATCH_WORLD_NAV) is not None or blackboard.scratch.get(
        SCRATCH_NEED_WORLD_NAV
    ):
        return Status.SUCCESS
    return Status.SUCCESS


def _handlers_traveling() -> dict:
    return {
        "survival.death": _maybe_death,
        "survival.emergency_tp": _maybe_emergency_teleport,
        "survival.hp": _step_survival_hp,
        "survival.mp_safe": lambda s, b: _step_handoff_retreat_if(
            _maybe_low_mp_to_safe, s, b
        ),
        "survival.return_vitals": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_vitals, s, b
        ),
        "party.hold_ground": step_party_hold_ground,
        "routine.duration": _maybe_routine_duration,
        "spell.support": lambda s, b: _step_spell_support(s, b, allow_buffs=False),
        "spell.buffs": lambda s, b: _step_spell_support(s, b, allow_buffs=True),
        "unstick.confined": _maybe_confined_escape,
        "shop.trip": _maybe_shop_trip,
        "travel.training_done": _step_travel_training_done,
        "nav.hunt_map": _step_travel_hunt_map,
        "travel.entered_farm": _step_travel_entered_farm,
        "farm.engage": _step_travel_engage,
        "travel.push_deeper_farm": _step_travel_push_deeper,
        "travel.arrive": _step_travel_arrive,
        "travel.hop": _step_travel_hop,
        "travel.hop_fail": _step_travel_hop_fail,
    }


def _tick_traveling_column(state: "GameState", blackboard: "Blackboard") -> Status:
    from app._04_decision.steps import TRAVELING, run_column

    status = run_column(TRAVELING, _handlers_traveling(), state, blackboard)
    return status if status is not None else Status.FAILURE




def _search_scarecrow_ground(
    state: "GameState", blackboard: "Blackboard"
) -> Status:
    """Walk nearby looking for 허수아비. Do not pull the bot into a farm rect."""
    player = state.player
    if player is None:
        return Status.FAILURE
    dest = blackboard.movement_planner.next_leg(
        blackboard, "search 허수아비", persist=True
    )
    blackboard.search_destination = dest
    blackboard.search_waypoint = None
    blackboard.search_hop_active = False
    blackboard.last_search_tick = blackboard.tick_count
    blackboard.current_goal = "newbie_training"
    blackboard.emit(
        ActionType.SEARCHING,
        destination=dest,
        priority=0.2,
        reason="search 허수아비",
        mid_act=False,
    )
    return Status.SUCCESS


def _maybe_post_respawn_spellbook(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Legacy: farming-column spellbook after death.

    Prefer ``arm_post_respawn_retreat`` (RETREATING → finish → world_nav).
    Kept only if ``SCRATCH_POST_RESPAWN_SCROLL`` is still armed. Newbies /
    slot-off: drop the flag so farming can resume.
    """
    from app._04_decision.species_rules import is_newbie_player
    from app._04_decision.talking_scroll import (
        PURPOSE_SPELLBOOK,
        SCRATCH_POST_RESPAWN_SCROLL,
        emit_talking_scroll,
        talking_scroll_available,
    )

    if not blackboard.scratch.get(SCRATCH_POST_RESPAWN_SCROLL):
        return None
    if is_newbie_player(state) or not talking_scroll_available():
        blackboard.scratch.pop(SCRATCH_POST_RESPAWN_SCROLL, None)
        return None
    if emit_talking_scroll(
        blackboard,
        purpose=PURPOSE_SPELLBOOK,
        reason="respawn, 마법서 상인",
    ) is Status.SUCCESS:
        blackboard.scratch.pop(SCRATCH_POST_RESPAWN_SCROLL, None)
        clear_travel(blackboard)
        from app._04_decision.world_nav import begin_world_nav

        begin_world_nav(blackboard, "post_respawn")
        return Status.SUCCESS
    blackboard.current_goal = "talking_scroll"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.7,
        reason="waiting for talking scroll",
    )
    return Status.SUCCESS


def _tick_newbie_training(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Level < 5: go to 허수아비 수련장 and hit scarecrows until 5.

    Talking scroll when the slot is on; otherwise walk to the dummy field.
    """
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.species_rules import is_newbie_player
    from app._04_decision.talking_scroll import (
        PURPOSE_TRAINING,
        SCARECROW_FIELD_TILE,
        SCRATCH_NEWBIE_TRAINING,
        emit_talking_scroll,
        talking_scroll_available,
    )

    if not is_newbie_player(state):
        blackboard.scratch.pop(SCRATCH_NEWBIE_TRAINING, None)
        return None

    combat = farm_loot_or_combat(state, blackboard, restrict_to_farm=False)
    if combat is not None:
        blackboard.scratch[SCRATCH_NEWBIE_TRAINING] = True
        return combat

    if blackboard.scratch.get(SCRATCH_NEWBIE_TRAINING):
        return _search_scarecrow_ground(state, blackboard)

    if (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            SCARECROW_FIELD_TILE[0],
            SCARECROW_FIELD_TILE[1],
        )
        <= farm_area.ARRIVE_TILES
    ):
        blackboard.scratch[SCRATCH_NEWBIE_TRAINING] = True
        return _search_scarecrow_ground(state, blackboard)

    if talking_scroll_available() and emit_talking_scroll(
        blackboard,
        purpose=PURPOSE_TRAINING,
        reason="newbie, 허수아비 수련장",
    ) is Status.SUCCESS:
        blackboard.scratch[SCRATCH_NEWBIE_TRAINING] = True
        clear_travel(blackboard)
        return Status.SUCCESS

    begin_travel(
        blackboard,
        SCARECROW_FIELD_TILE,
        purpose=PURPOSE_TRAINING,
        reason="walk to 허수아비 수련장",
    )
    from app._04_decision.nav_config import get_terrain_map

    if get_terrain_map() is not None:
        return tick_traveling(state, blackboard)
    blackboard.current_goal = "newbie_training"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.55,
        reason="walk to 허수아비 수련장",
    )
    return Status.SUCCESS


def _maybe_shop_trip(state: "GameState", blackboard: "Blackboard") -> Status | None:
    """Arrows gone → talking-scroll / walk to shop, then buy arrows."""
    from app._04_decision.dungeon_policy import dungeon_active, wrap_shop_trip
    from app._04_decision.shop_trip import tick_shop_trip

    if dungeon_active():
        return wrap_shop_trip(tick_shop_trip, state, blackboard)
    return tick_shop_trip(state, blackboard)


def _shop_before_world_nav(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Handoff to ``PlayerMode.SHOPPING`` when a buy/sell trip is needed.

    If an in-flight world_nav session exists, drop it and ``request_world_nav``
    (after_shop) without entering WORLD_NAV — shopping owns the mode until the
    trip clears, then ``leave_shopping_mode_if_idle`` re-arms world nav.
    """
    shop = _maybe_shop_trip(state, blackboard)
    if shop is None:
        return None
    from app._04_decision.shop_trip import ensure_shopping_mode
    from app._04_decision.world_nav import (
        SCRATCH_WORLD_NAV,
        clear_world_nav_run,
        request_world_nav,
    )

    if blackboard.scratch.get(SCRATCH_WORLD_NAV) is not None:
        clear_world_nav_run(blackboard)
        request_world_nav(blackboard, "after_shop")
    ensure_shopping_mode(blackboard)
    return shop


def _drive_shop(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Advance the sticky shop trip; leave mode when the trip clears."""
    from app._04_decision.dungeon_policy import dungeon_active, wrap_shop_trip
    from app._04_decision.shop_trip import (
        ensure_shopping_mode,
        leave_shopping_mode_if_idle,
        tick_shop_trip,
    )
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

    if dungeon_active():
        status = wrap_shop_trip(tick_shop_trip, state, blackboard)
    else:
        status = tick_shop_trip(state, blackboard)
    if blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        ensure_shopping_mode(blackboard)
    if status is not None:
        return status
    leave_shopping_mode_if_idle(blackboard)
    return None


def _try_farm_upkeep(state: "GameState", blackboard: "Blackboard") -> Status | None:
    """Inventory full / farm timer → travel. Returns Status if handled."""
    shop = _maybe_shop_trip(state, blackboard)
    if shop is not None:
        return shop

    from app._04_decision.player_mode import PlayerMode

    # A same-tick world-nav or fallback walk already owns this move.
    if blackboard.player_mode in (PlayerMode.WORLD_NAV, PlayerMode.TRAVELING):
        return Status.FAILURE

    farms = get_farm_areas()
    terrain = get_terrain_map()
    if not farms or terrain is None:
        return None
    from app._04_decision.hunt_area import rotate_reason

    reason = None
    if farm_time_exceeded(blackboard):
        reason = "farming time exceeded"
    else:
        reason = rotate_reason(state, blackboard)
    if not reason:
        return None

    next_index = advance_farm_tour(blackboard)
    reset_farm_timer(blackboard)
    farm = farms[next_index]
    from app._04_decision.player_mode import HUNT_MAP_ID
    from app._04_decision.world_nav import begin_world_nav
    from app._04_decision.world_nav.hooks import (
        FIELD_WORLD_NAV_PACKS,
        REASON_FARM_AREA,
    )
    from app.bot_log import get_logger

    pack = str(HUNT_MAP_ID or "").strip()
    if pack in FIELD_WORLD_NAV_PACKS:
        blackboard.farm_visit.clear()
        blackboard.scratch["changing_area"] = True
        get_logger("nav").info(
            "field world nav farm area pack=%s index=%s cause=%s",
            pack,
            next_index,
            reason,
        )
        begin_world_nav(blackboard, REASON_FARM_AREA)
        return Status.FAILURE

    start = (blackboard.world_origin.x, blackboard.world_origin.y)
    goal = farm.interior_walkable(terrain, start, margin=farm_area.ARRIVE_TILES)
    if goal is None:
        return None
    blackboard.farm_visit.clear()
    blackboard.scratch["changing_area"] = True
    begin_travel(
        blackboard,
        goal,
        purpose=PURPOSE_NEXT_FARM,
        reason=reason,
    )
    return tick_traveling(state, blackboard)


def _enter_farm_if_needed(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """If outside the active farm, TRAVEL to the nearest walkable entry.

    Never returns ``None`` while outside the farm so farming does not fall
    through to in-farm search with clamp-invented destinations.
    """
    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()
    if farm is None or terrain is None:
        return None
    ox, oy = blackboard.world_origin.x, blackboard.world_origin.y
    from app._04_decision.talking_scroll import (
        SCRATCH_SCROLL_ARRIVAL,
        SCRATCH_UNSTICK_SCROLL_RETURN,
    )

    if blackboard.scratch.get(SCRATCH_UNSTICK_SCROLL_RETURN):
        if blackboard.scratch.get(SCRATCH_SCROLL_ARRIVAL):
            if not farm.contains(ox, oy):
                return Status.SUCCESS
        elif farm.contains(ox, oy):
            blackboard.scratch.pop(SCRATCH_UNSTICK_SCROLL_RETURN, None)
        else:
            blackboard.scratch.pop(SCRATCH_UNSTICK_SCROLL_RETURN, None)
            from app._04_decision.world_nav import begin_world_nav

            begin_world_nav(blackboard, "unstick_return")
            return Status.FAILURE
    if farm.contains(ox, oy):
        return None
    from app.bot_log import event

    event("travel", "return/enter farm needed at (%s,%s)", ox, oy)
    hunt_map = _maybe_scroll_to_hunt_map(state, blackboard)
    if hunt_map is not None:
        return hunt_map
    if hold_fire_outside_hunt(state, blackboard):
        loot = approach_counterattack(state, blackboard)
    else:
        loot = continue_or_start_loot(
            state, blackboard, allow_new=True, restrict_to_farm=False
        )
    if loot is not None:
        return loot
    goal = farm.interior_walkable(terrain, (ox, oy), margin=farm_area.ARRIVE_TILES)
    if goal is None:
        blackboard.current_goal = "enter_farm"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.25,
            reason="enter farm, no walkable entry",
        )
        return Status.SUCCESS
    begin_travel(
        blackboard,
        goal,
        purpose=PURPOSE_ENTER_FARM,
        reason="enter farm area",
    )
    status = tick_traveling(state, blackboard)
    if blackboard.intent is not None:
        return status
    blackboard.current_goal = "enter_farm"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.25,
        reason="enter farm, path blocked",
    )
    return Status.SUCCESS


def _search_inside_farm(state: "GameState", blackboard: "Blackboard") -> Status:
    player = state.player
    if player is None:
        blackboard.note_no_intent("search_inside_farm: no player")
        return Status.FAILURE

    blackboard.current_goal = "search"
    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()
    if farm is None or terrain is None:
        # No farm rect / no terrain: fall back to legacy click-sparse spiral.
        if get_active_farm(blackboard.farm_area_index) is None:
            blackboard.virtual_position = player.position
        dest = blackboard.movement_planner.next_leg(
            blackboard, "search area", persist=True
        )
        blackboard.search_destination = dest
        blackboard.search_waypoint = None
        blackboard.search_leg_goal = None
        blackboard.search_hop_active = False
        blackboard.last_search_tick = blackboard.tick_count
        blackboard.emit(
            ActionType.SEARCHING,
            destination=dest,
            priority=0.2,
            reason="search area",
            mid_act=False,
        )
        return Status.SUCCESS

    emit_search_hop(
        blackboard,
        reason="search area",
        priority=0.2,
        max_leg_ticks=search_beh.LEG_TICKS,
        state=state,
    )
    if blackboard.intent is not None:
        return Status.SUCCESS

    # Farm hop failed (blocked / no in-view tile): keep moving via spiral.
    dest = blackboard.movement_planner.next_leg(
        blackboard, "search area fallback", persist=False, legacy_spiral=True
    )
    blackboard.search_destination = dest
    blackboard.search_waypoint = None
    blackboard.search_leg_goal = None
    blackboard.search_hop_active = False
    blackboard.last_search_tick = blackboard.tick_count
    blackboard.emit(
        ActionType.SEARCHING,
        destination=dest,
        priority=0.2,
        reason="search area fallback",
        mid_act=False,
    )
    return Status.SUCCESS


def _floor_idle(blackboard: "Blackboard", reason: str) -> Status:
    blackboard.emit(ActionType.IDLE, priority=0.2, reason=reason)
    return Status.SUCCESS


def _logical_cell_reached(blackboard: "Blackboard", cell: tuple[int, int]) -> bool:
    """True when travel's arrive radius covers the logical waypoint."""
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.dungeon import travel_arrive_tiles

    return (
        tile_chebyshev(
            int(blackboard.world_origin.x),
            int(blackboard.world_origin.y),
            int(cell[0]),
            int(cell[1]),
        )
        <= travel_arrive_tiles()
    )


def _plan_dungeon_floor_session(
    state: "GameState",
    blackboard: "Blackboard",
    target: str,
):
    """One route from the live cell. None when the caller already idled."""
    from app._03_world.space.map_pack import get_active_map_pack
    from app._04_decision.dungeon_floor_route import (
        SCRATCH_DUNGEON_FLOOR_ROUTE,
        FloorRouteSession,
        PickedPoint,
        RouteError,
        _snap,
        _terrain_from_nav,
        choice_for_raw_map,
        floor_of_pack,
        plan_floor_steps,
        same_dungeon_family,
    )
    from app._04_decision.world_nav.session import live_pose_from_state
    from app.bot_log import get_logger

    pose = live_pose_from_state(state)
    if pose is None:
        return _floor_idle(blackboard, "dungeon floor route wait pose")
    choice = choice_for_raw_map(int(pose.map_id))
    active = get_active_map_pack()
    if (
        choice is None
        or active is None
        or str(active.id) != choice.pack_id
        or not same_dungeon_family(choice.pack_id, target)
    ):
        get_logger("nav").info(
            "dungeon floor route unavailable map=%s target=%s",
            getattr(pose, "map_id", "-"),
            target,
        )
        failed = FloorRouteSession(
            target_pack=target,
            complex_name="",
            steps=[],
            phase="failed",
            fail_reason="dungeon floor route unavailable",
        )
        blackboard.scratch[SCRATCH_DUNGEON_FLOOR_ROUTE] = failed
        return _floor_idle(blackboard, "dungeon floor route unavailable")
    terrain = _terrain_from_nav(choice.nav_path, choice.pixel_scale)
    origin = (int(blackboard.world_origin.x), int(blackboard.world_origin.y))
    snapped = _snap(terrain, origin) if terrain is not None else origin
    if snapped is None:
        get_logger("nav").info(
            "dungeon floor route unavailable no walk tile target=%s",
            target,
        )
        failed = FloorRouteSession(
            target_pack=target,
            complex_name="",
            steps=[],
            phase="failed",
            fail_reason="dungeon floor route unavailable",
        )
        blackboard.scratch[SCRATCH_DUNGEON_FLOOR_ROUTE] = failed
        return _floor_idle(blackboard, "dungeon floor route unavailable")
    start = PickedPoint(choice=choice, nav_x=int(snapped[0]), nav_y=int(snapped[1]))
    try:
        steps = plan_floor_steps(start, target)
    except RouteError as exc:
        get_logger("nav").info(
            "dungeon floor route unavailable target=%s reason=%s",
            target,
            exc,
        )
        failed = FloorRouteSession(
            target_pack=target,
            complex_name="",
            steps=[],
            phase="failed",
            fail_reason="dungeon floor route unavailable",
        )
        blackboard.scratch[SCRATCH_DUNGEON_FLOOR_ROUTE] = failed
        return _floor_idle(blackboard, "dungeon floor route unavailable")
    if not steps:
        return _finish_dungeon_floor_route(blackboard, target)
    record = floor_of_pack(target)
    session = FloorRouteSession(
        target_pack=target,
        complex_name="" if record is None else record.complex_name,
        steps=steps,
    )
    blackboard.scratch[SCRATCH_DUNGEON_FLOOR_ROUTE] = session
    get_logger("nav").info(
        "dungeon floor route planned dungeon=%s current=%s target=%s steps=%s",
        session.complex_name or "-",
        choice.pack_id,
        target,
        len(steps),
    )
    return session


def _finish_dungeon_floor_route(blackboard: "Blackboard", target: str) -> None:
    """Target floor is confirmed. Load that floor's own patrol and start the clock."""
    from app._04_decision.dungeon_floor_route import SCRATCH_DUNGEON_FLOOR_ROUTE
    from app._04_decision.world_nav.hooks import (
        SCRATCH_ROUTINE,
        apply_routine_entry_runtime,
    )
    from app.bot_log import get_logger

    blackboard.scratch.pop(SCRATCH_DUNGEON_FLOOR_ROUTE, None)
    cursor = blackboard.scratch.get(SCRATCH_ROUTINE)
    entry = cursor.active() if cursor is not None and hasattr(cursor, "active") else None
    if cursor is not None and isinstance(entry, dict):
        from app._04_decision.world_nav.hooks import _arrival_resets_stay
        from app._04_decision.world_nav.routine import (
            ROUTINE_RETURN_REASON,
            release_dungeon_routine_clock,
        )

        reason = str(blackboard.scratch.pop(ROUTINE_RETURN_REASON, "") or "")
        resumed = release_dungeon_routine_clock(blackboard)
        cursor.mark_arrived(
            reset_clock=not (resumed or not _arrival_resets_stay(reason))
        )
        cursor.reset_fail_mask()
        apply_routine_entry_runtime(blackboard, entry, reason="dungeon_floor")
    get_logger("nav").info("dungeon floor route complete target=%s", target)


def _replan_dungeon_floor_route(
    state: "GameState",
    blackboard: "Blackboard",
    session,
    why: str,
) -> Status:
    """Ask the calculator again. The new cells still go only to existing travel."""
    from app._04_decision.dungeon_floor_route import SCRATCH_DUNGEON_FLOOR_ROUTE
    from app.bot_log import get_logger

    session.replans += 1
    if session.replans > 1:
        session.fail(f"dungeon floor route unavailable {why}")
        get_logger("nav").info(
            "dungeon floor route unavailable target=%s reason=%s",
            session.target_pack,
            why,
        )
        return _floor_idle(blackboard, "dungeon floor route unavailable")
    blackboard.scratch.pop(SCRATCH_DUNGEON_FLOOR_ROUTE, None)
    planned = _plan_dungeon_floor_session(state, blackboard, session.target_pack)
    if planned is None:
        return None
    if not isinstance(planned, type(session)):
        return planned
    planned.replans = session.replans
    return _drive_dungeon_floor_route(state, blackboard, session.target_pack)


def _drive_dungeon_floor_walk(state, blackboard, session, step) -> Status:
    from app._04_decision.dungeon_floor_route import PURPOSE_DUNGEON_FLOOR
    from app._04_decision.mode_control import begin_travel
    from app._04_decision.world_nav.session import (
        _remember_stale_exit_landing,
        live_pose_from_state,
    )
    from app.bot_log import get_logger

    cell = (int(step.nav_x), int(step.nav_y))
    pose = live_pose_from_state(state)
    if pose is not None and int(pose.map_id) != int(step.map_id):
        # Same one-shot landing the world-nav walk stores. hunt_map arms next.
        _remember_stale_exit_landing(blackboard, int(step.map_id), pose)
        return _replan_dungeon_floor_route(
            state, blackboard, session, "map left the walk step"
        )
    traveling = (
        blackboard.travel_purpose == PURPOSE_DUNGEON_FLOOR
        and tuple(blackboard.nav_goal) == cell
        if blackboard.nav_goal is not None
        else False
    )
    if session.phase == "walk" and session.walk_cell == cell:
        if traveling:
            return tick_traveling(state, blackboard)
        if _logical_cell_reached(blackboard, cell):
            session.index += 1
            session.phase = ""
            session.walk_cell = None
            return _drive_dungeon_floor_route(state, blackboard, session.target_pack)
        return _replan_dungeon_floor_route(
            state, blackboard, session, "travel failed the walk step"
        )
    begin_travel(
        blackboard,
        cell,
        purpose=PURPOSE_DUNGEON_FLOOR,
        reason=f"dungeon floor walk {cell[0]},{cell[1]}",
    )
    session.phase = "walk"
    session.walk_cell = cell
    session.expect_map_id = int(step.map_id)
    get_logger("nav").info(
        "dungeon floor step index=%s type=walk cell=(%s,%s)",
        session.index,
        cell[0],
        cell[1],
    )
    return tick_traveling(state, blackboard)


def _emit_floor_gate(blackboard, step) -> Status:
    blackboard.emit(
        ActionType.GATE,
        priority=0.55,
        reason="dungeon floor transition",
        gate_entrance=(int(step.entrance_world[0]), int(step.entrance_world[1])),
        gate_expect_map_id=int(step.to_map_id),
        gate_expect_xy=(int(step.landing_world[0]), int(step.landing_world[1])),
        gate_from_map_id=int(step.from_map_id),
        gate_edge=f"floor:{step.from_pack_id}->{step.to_pack_id}",
    )
    return Status.SUCCESS


def _floor_gate_sidestep(state, blackboard, session, step) -> Status:
    """One body-avoid step, then the same floor gate click."""
    from app._04_decision.behaviors.travel import clear_travel, emit_gate_sidestep
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    if not session.gate_sidestep_sent:
        if pose is None:
            return _floor_idle(blackboard, "dungeon floor gate sidestep")
        sent = emit_gate_sidestep(
            blackboard,
            state,
            player_abs=(int(pose.x), int(pose.y)),
            entrance_abs=(int(step.entrance_world[0]), int(step.entrance_world[1])),
            reason="dungeon floor gate sidestep",
        )
        session.gate_sidestep_sent = True
        session.gate_sidestep_from = (int(pose.x), int(pose.y))
        session.gate_sidestep_waits = 0
        if not sent:
            clear_travel(blackboard)
            session.phase = "transition"
            session.gate_seen = False
            session.gate_ok = False
            session.gate_error = ""
            return _emit_floor_gate(blackboard, step)
        return Status.SUCCESS
    session.gate_sidestep_waits = int(session.gate_sidestep_waits or 0) + 1
    origin = session.gate_sidestep_from
    moved = (
        pose is not None
        and origin is not None
        and (int(pose.x), int(pose.y)) != (int(origin[0]), int(origin[1]))
    )
    if not moved and session.gate_sidestep_waits < 3:
        return _floor_idle(blackboard, "dungeon floor gate sidestep")
    clear_travel(blackboard)
    session.phase = "transition"
    session.gate_seen = False
    session.gate_ok = False
    session.gate_error = ""
    return _emit_floor_gate(blackboard, step)


def _drive_dungeon_floor_transition(state, blackboard, session, step) -> Status:
    from app._04_decision.world_nav.session import live_pose_from_state
    from app.bot_log import get_logger

    if not step.gate_compatible:
        session.fail("dungeon floor route unavailable transition")
        get_logger("nav").info(
            "dungeon floor route unavailable target=%s kind=%s",
            session.target_pack,
            step.kind,
        )
        return _floor_idle(blackboard, "dungeon floor route unavailable")
    if session.phase == "sidestep":
        return _floor_gate_sidestep(state, blackboard, session, step)
    if session.phase != "transition":
        session.phase = "transition"
        session.gate_seen = False
        session.gate_ok = False
        session.gate_map_id = None
        session.gate_error = ""
        session.expect_map_id = int(step.to_map_id)
        get_logger("nav").info(
            "dungeon floor transition pending %s->%s cell=(%s,%s)",
            step.from_pack_id,
            step.to_pack_id,
            step.entrance_world[0],
            step.entrance_world[1],
        )
        return _emit_floor_gate(blackboard, step)
    if not session.gate_seen:
        return _floor_idle(blackboard, "dungeon floor transition pending")
    from app._04_decision.world_nav.gate import GATE_STUCK_POSE

    if (
        not session.gate_ok
        and session.gate_error == GATE_STUCK_POSE
        and not session.gate_sidestep_done
    ):
        session.gate_sidestep_done = True
        session.gate_sidestep_sent = False
        session.phase = "sidestep"
        get_logger("nav").info(
            "dungeon floor gate stuck — sidestep then retry %s->%s",
            step.from_pack_id,
            step.to_pack_id,
        )
        return _floor_gate_sidestep(state, blackboard, session, step)
    pose = live_pose_from_state(state)
    live_map = session.gate_map_id
    if live_map is None and pose is not None:
        live_map = int(pose.map_id)
    if session.gate_ok and live_map is not None and int(live_map) == int(step.to_map_id):
        get_logger("nav").info(
            "dungeon floor transition confirmed map=%s",
            int(live_map),
        )
        session.index += 1
        session.phase = ""
        session.gate_seen = False
        session.gate_ok = False
        session.gate_map_id = None
        return _drive_dungeon_floor_route(state, blackboard, session.target_pack)
    session.fail("dungeon floor route unavailable transition")
    get_logger("nav").info(
        "dungeon floor route unavailable target=%s transition map=%s want=%s",
        session.target_pack,
        live_map,
        step.to_map_id,
    )
    return _floor_idle(blackboard, "dungeon floor route unavailable")


def _drive_dungeon_floor_route(
    state: "GameState",
    blackboard: "Blackboard",
    target: str,
) -> Status | None:
    from app._04_decision.dungeon_floor_route import (
        SCRATCH_DUNGEON_FLOOR_ROUTE,
        FloorRouteSession,
        FloorTransition,
        FloorWalk,
    )

    from app._04_decision import player_mode as pm

    # Hunt id only. The target floor's terrain stays unloaded until arrival.
    if str(pm.HUNT_MAP_ID or "") != target:
        pm.HUNT_MAP_ID = target
    session = blackboard.scratch.get(SCRATCH_DUNGEON_FLOOR_ROUTE)
    if not isinstance(session, FloorRouteSession) or session.target_pack != target:
        planned = _plan_dungeon_floor_session(state, blackboard, target)
        if not isinstance(planned, FloorRouteSession):
            return Status.SUCCESS if planned is not None else None
        session = planned
    if session.phase == "failed":
        return _floor_idle(
            blackboard,
            session.fail_reason or "dungeon floor route unavailable",
        )
    step = session.current()
    if step is None:
        _finish_dungeon_floor_route(blackboard, target)
        return None
    if isinstance(step, FloorWalk):
        return _drive_dungeon_floor_walk(state, blackboard, session, step)
    if isinstance(step, FloorTransition):
        return _drive_dungeon_floor_transition(state, blackboard, session, step)
    session.fail("dungeon floor route unavailable")
    return _floor_idle(blackboard, "dungeon floor route unavailable")


def _step_dungeon_off_floor(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Wrong floor of the scheduled dungeon walks a calculated route.

    Entrance-floor hunts keep the old idle. The route only names logical
    cells; ``begin_travel`` / the existing gate executor perform them.
    """
    from app._04_decision.dungeon_floor_route import (
        SCRATCH_DUNGEON_FLOOR_ROUTE,
        inside_target_dungeon,
        needs_floor_route,
        routine_target_pack,
    )
    from app._04_decision.talking_scroll import (
        hunt_map_is_dungeon,
        player_on_selected_map,
    )

    target = routine_target_pack(blackboard)
    # Deeper floor, already inside that complex: route before any patrol,
    # even when HUNT_MAP has not been applied yet.
    if needs_floor_route(target) and inside_target_dungeon(blackboard):
        if not player_on_selected_map(blackboard):
            return _drive_dungeon_floor_route(state, blackboard, target)
    if player_on_selected_map(blackboard):
        blackboard.scratch.pop(SCRATCH_DUNGEON_FLOOR_ROUTE, None)
        return None
    if not hunt_map_is_dungeon():
        return None
    blackboard.emit(
        ActionType.IDLE,
        priority=0.2,
        reason="dungeon, off hunt floor",
    )
    return Status.SUCCESS


def _step_dungeon_blocked(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    del state
    from app._04_decision.dungeon_policy import try_blocked_step

    return try_blocked_step(blackboard)


def _step_dungeon_idle_nudge(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    from app._04_decision.dungeon_policy import try_idle_nudge

    _refresh_combat_activity(state, blackboard)
    return try_idle_nudge(blackboard, had_intent=False)


def _step_dungeon_patrol(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    from app._04_decision.patrol import begin_or_continue_patrol, get_patrol_waypoints

    if not get_patrol_waypoints():
        # Fall through to dungeon.idle_nudge (last on the ladder).
        return None

    if begin_or_continue_patrol(blackboard):
        return tick_traveling(state, blackboard)

    blackboard.emit(
        ActionType.IDLE,
        priority=0.2,
        reason="dungeon patrol idle",
    )
    return Status.SUCCESS


def _handlers_farming_island() -> dict:
    return {
        "survival.death": _maybe_death,
        "survival.emergency_tp": _maybe_emergency_teleport,
        "survival.hp": _step_survival_hp,
        "survival.mp_safe": lambda s, b: _step_handoff_retreat_if(
            _maybe_low_mp_to_safe, s, b
        ),
        "survival.return_vitals": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_vitals, s, b
        ),
        "party.hold_ground": step_party_hold_ground,
        "survival.return_idle": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_idle, s, b
        ),
        "shop.before_world_nav": _shop_before_world_nav,
        "nav.world": _maybe_world_nav,
        "spell.support": lambda s, b: _step_spell_support(s, b, allow_buffs=False),
        "spell.buffs": lambda s, b: _step_spell_support(s, b, allow_buffs=True),
        "unstick.confined": _maybe_confined_escape,
        "farm.newbie": _tick_newbie_training,
        "farm.post_respawn_spellbook": _maybe_post_respawn_spellbook,
        "farm.upkeep": _try_farm_upkeep,
        "farm.post_shop_return": _maybe_post_shop_farm_return,
        "nav.hunt_map": _maybe_scroll_to_hunt_map,
        "party.turret_leash": step_party_turret_leash,
        "farm.engage": _step_farm_engage,
        "party.turret_idle": step_party_turret_idle,
        "farm.enter": _enter_farm_if_needed,
        "farm.search": _search_inside_farm,
    }


def _handlers_farming_dungeon() -> dict:
    return {
        "survival.death": _maybe_dungeon_death,
        "survival.hp": _step_survival_hp,
        "survival.mp_safe": lambda s, b: _step_handoff_retreat_if(
            _maybe_low_mp_to_safe, s, b
        ),
        "survival.return_vitals": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_vitals, s, b
        ),
        "party.hold_ground": step_party_hold_ground,
        "survival.return_idle": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_idle, s, b
        ),
        "shop.before_world_nav": _shop_before_world_nav,
        "nav.world": _maybe_world_nav,
        "spell.support": lambda s, b: _step_spell_support(s, b, allow_buffs=False),
        "spell.buffs": lambda s, b: _step_spell_support(s, b, allow_buffs=True),
        "farm.post_respawn_spellbook": _maybe_post_respawn_spellbook,
        "farm.post_shop_return": _maybe_post_shop_farm_return,
        "nav.hunt_map": _maybe_scroll_to_hunt_map,
        "dungeon.off_floor": _step_dungeon_off_floor,
        "dungeon.blocked": _step_dungeon_blocked,
        "party.turret_leash": step_party_turret_leash,
        "farm.engage": _step_farm_engage,
        "party.turret_idle": step_party_turret_idle,
        "dungeon.idle_nudge": _step_dungeon_idle_nudge,
        "dungeon.patrol": _step_dungeon_patrol,
    }


def tick_farming(state: "GameState", blackboard: "Blackboard") -> Status:
    """L3 column ``FARMING_ISLAND`` or dungeon variant."""
    from app._04_decision.dungeon import is_dungeon_map
    from app._04_decision.steps import FARMING_ISLAND, run_column

    if is_dungeon_map():
        return _tick_dungeon_farming(state, blackboard)

    ensure_farm_tour(blackboard)
    status = run_column(
        FARMING_ISLAND, _handlers_farming_island(), state, blackboard
    )
    return status if status is not None else Status.FAILURE


def _tick_dungeon_farming(
    state: "GameState", blackboard: "Blackboard"
) -> Status:
    """L3 column ``FARMING_DUNGEON``."""
    from app._04_decision.steps import FARMING_DUNGEON, run_column

    status = run_column(
        FARMING_DUNGEON, _handlers_farming_dungeon(), state, blackboard
    )
    return status if status is not None else Status.FAILURE



_SCRATCH_SEEN_LEVEL = "seen_level"


def _maybe_dismiss_level_up(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """When memory level rises, Esc twice to close the congratulations window.

    First observation only records the level. Dead / missing vitals skip.
    """
    if is_hp_zero(state):
        return None
    player = state.player
    level = player.level if player is not None else None
    if level is None or level <= 0:
        return None
    seen = blackboard.scratch.get(_SCRATCH_SEEN_LEVEL)
    blackboard.scratch[_SCRATCH_SEEN_LEVEL] = level
    if seen is None or int(level) <= int(seen):
        return None
    blackboard.current_goal = "dismiss_level_up"
    blackboard.emit(
        ActionType.DISMISS_LEVEL_UP,
        priority=1.0,
        reason="level up, close dialog",
    )
    return Status.SUCCESS


def _handlers_world_nav() -> dict:
    return {
        "survival.death": _maybe_death,
        "survival.emergency_tp": _maybe_emergency_teleport,
        "survival.hp": _step_survival_hp,
        "survival.mp_safe": lambda s, b: _step_handoff_retreat_if(
            _maybe_low_mp_to_safe, s, b
        ),
        "survival.return_vitals": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_vitals, s, b
        ),
        "party.hold_ground": step_party_hold_ground,
        "shop.trip": _shop_before_world_nav,
        "spell.support": lambda s, b: _step_spell_support(s, b, allow_buffs=False),
        "spell.buffs": lambda s, b: _step_spell_support(s, b, allow_buffs=True),
        "unstick.confined": _maybe_world_nav_confined,
        "world_nav.drive": _drive_world_nav,
    }


def tick_world_navigating(state: "GameState", blackboard: "Blackboard") -> Status:
    """L3 column ``WORLD_NAV`` (cross-map routine session)."""
    from app._04_decision.steps import WORLD_NAV, run_column

    status = run_column(
        WORLD_NAV, _handlers_world_nav(), state, blackboard
    )
    return status if status is not None else Status.FAILURE


def _handlers_shopping() -> dict:
    return {
        "survival.death": _maybe_death,
        "survival.emergency_tp": _maybe_emergency_teleport,
        "survival.hp": _step_survival_hp,
        "survival.mp_safe": lambda s, b: _step_handoff_retreat_if(
            _maybe_low_mp_to_safe, s, b
        ),
        "survival.return_vitals": lambda s, b: _step_handoff_retreat_if(
            _maybe_return_on_vitals, s, b
        ),
        "shop.drive": _drive_shop,
    }


def tick_shopping(state: "GameState", blackboard: "Blackboard") -> Status:
    """L3 column ``SHOPPING`` (buy/sell trip)."""
    from app._04_decision.steps import SHOPPING, run_column

    status = run_column(SHOPPING, _handlers_shopping(), state, blackboard)
    return status if status is not None else Status.FAILURE


def tick_mode(state: "GameState", blackboard: "Blackboard") -> Status:
    """Dispatch GLOBAL column then the sticky PlayerMode column."""
    from app._04_decision.steps import GLOBAL, run_column

    clear_approach_hold_tick(blackboard)
    if hold_fire_outside_hunt(state, blackboard):
        blackboard.scratch[SCRATCH_APPROACH_HOLD_FIRE] = True
    prefix = run_column(
        GLOBAL,
        {
            "survival.death": _maybe_death,
            "ui.dismiss_level_up": _maybe_dismiss_level_up,
        },
        state,
        blackboard,
        require_terminal=False,
    )
    if prefix is not None:
        return prefix
    mode = blackboard.player_mode
    if mode is PlayerMode.RETREATING:
        return tick_retreating(state, blackboard)
    if mode is PlayerMode.SHOPPING:
        return tick_shopping(state, blackboard)
    if mode is PlayerMode.WORLD_NAV:
        return tick_world_navigating(state, blackboard)
    if mode is PlayerMode.TRAVELING:
        return tick_traveling(state, blackboard)
    return tick_farming(state, blackboard)


__all__ = [
    "INVENTORY_FULL_RATIO",
    "FARM_DURATION_LIMIT",
    "tick_mode",
    "tick_farming",
    "tick_traveling",
    "tick_retreating",
    "tick_world_navigating",
    "tick_shopping",
]

from app._04_decision.decide_spans import traced

tick_farming = traced(tick_farming)
tick_traveling = traced(tick_traveling)
tick_retreating = traced(tick_retreating)
tick_world_navigating = traced(tick_world_navigating)
tick_shopping = traced(tick_shopping)
_tick_dungeon_farming = traced(_tick_dungeon_farming)
_tick_newbie_training = traced(_tick_newbie_training)
_search_inside_farm = traced(_search_inside_farm)
_enter_farm_if_needed = traced(_enter_farm_if_needed)
_maybe_shop_trip = traced(_maybe_shop_trip)
_shop_before_world_nav = traced(_shop_before_world_nav)
_drive_shop = traced(_drive_shop)
