"""Per-mode decision ticks (traveling / farming / retreating)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.mode_actions import (
    HP_RETREAT_STARTED,
    apply_hp_actions,
    apply_inplace_hp_support,
    continue_or_start_loot,
    farm_loot_or_combat,
    maybe_escalate_teleport_to_safe,
    maybe_mother_tree_before_passive_wait,
    retreat_loot_if_clear,
)
from app._04_decision.behaviors import search as search_beh
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
    vitals_full_at_mother_tree,
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

    Survival absolute: shop_trip does not block this path. Failed or
    repeated attempts share a short cooldown so one visible player cannot
    spam TELEPORT every tick ahead of HP actions.
    """
    import time

    if not pm.RANDOM_TELEPORT_ENABLED:
        return None
    if not (pm.TELEPORT_ON_PLAYER or pm.TELEPORT_WHEN_SURROUNDED):
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

    reason = ""
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


def _maybe_post_shop_farm_return(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """After buying goods: talking-scroll to farm-map NPC, else walk into farm."""
    from app._04_decision.talking_scroll import (
        SCRATCH_POST_SHOP_RETURN,
        emit_talking_scroll,
        farm_return_scroll_spot,
        talking_scroll_available,
    )

    if not blackboard.scratch.get(SCRATCH_POST_SHOP_RETURN):
        return None
    farm = get_active_farm(blackboard.farm_area_index)
    ox, oy = blackboard.world_origin.x, blackboard.world_origin.y
    if farm is not None and farm.contains(ox, oy):
        blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
        return None

    if talking_scroll_available():
        spot = farm_return_scroll_spot(pm.HUNT_MAP_ID)
        if spot:
            status = emit_talking_scroll(
                blackboard,
                spot_id=spot,
                reason="return to farm map after shop",
            )
            if status is Status.SUCCESS:
                blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
                return status
            blackboard.current_goal = "post_shop_return"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.55,
                reason="waiting talking scroll (farm return)",
            )
            return Status.SUCCESS

    # No scroll: fall through to walk via _enter_farm_if_needed.
    blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
    return None


def _maybe_scroll_to_hunt_map(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Wrong map vs selected farm areas → 말하는 두루마리 to that map."""
    import time

    from app._04_decision.nav_config import navigation_configure_in_progress
    from app._04_decision.talking_scroll import (
        HUNT_MAP_SCROLL_COOLDOWN_S,
        SCRATCH_HUNT_MAP_SCROLL_AT,
        SCRATCH_POST_SHOP_RETURN,
        SCRATCH_SCROLL_ARRIVAL,
        SCRATCH_SHOP_TRIP,
        emit_talking_scroll,
        farm_return_scroll_spot,
        hunt_map_is_dungeon,
        on_dungeon_return_town,
        player_on_selected_map,
        talking_scroll_available,
    )

    del state
    if blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        return None
    if blackboard.scratch.get("mother_tree_trip"):
        return None
    if blackboard.scratch.get(SCRATCH_SCROLL_ARRIVAL):
        return None
    if navigation_configure_in_progress():
        return None
    if player_on_selected_map(blackboard):
        return None
    # Already at the town the dungeon hunt scrolls to — do not loop the list.
    if hunt_map_is_dungeon() and on_dungeon_return_town():
        return None
    if not talking_scroll_available():
        return None
    last = float(blackboard.scratch.get(SCRATCH_HUNT_MAP_SCROLL_AT) or 0.0)
    if last and time.time() - last < float(HUNT_MAP_SCROLL_COOLDOWN_S):
        blackboard.current_goal = "talking_scroll"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.55,
            reason="waiting talking scroll (hunt map)",
        )
        return Status.SUCCESS
    spot = farm_return_scroll_spot(pm.HUNT_MAP_ID)
    if not spot:
        return None
    status = emit_talking_scroll(
        blackboard,
        spot_id=spot,
        reason="return to selected hunt map",
    )
    if status is Status.SUCCESS:
        blackboard.scratch[SCRATCH_HUNT_MAP_SCROLL_AT] = time.time()
        blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
        clear_travel(blackboard)
        return status
    blackboard.current_goal = "talking_scroll"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.55,
        reason="waiting talking scroll (hunt map)",
    )
    return Status.SUCCESS


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


def _tick_mother_tree_retreat(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Elf Mother Tree: cast → HP_to_MP while HP is full → scroll to 마법서 상인."""
    stage = blackboard.scratch.get("mother_tree_trip")
    if not stage:
        return None

    if stage == "scroll":
        finish_retreat(blackboard)
        return Status.FAILURE

    from app._04_decision.spells import mark_slot_used, maybe_hp_to_mp_at_tree

    if stage == "cast":
        mark_slot_used(blackboard, "mother_tree")
        blackboard.scratch["mother_tree_trip"] = "recharge"
        blackboard.current_goal = "mother_tree"
        blackboard.emit(
            ActionType.RETURN_TO_MOTHER_TREE,
            priority=0.95,
            reason="return to mother tree",
        )
        return Status.SUCCESS

    # recharge: stand at the tree; no walk, loot, or heal-spell.
    # When HP is full and MP is still low, convert HP→MP (Box 2 F7).
    if vitals_full_at_mother_tree(state):
        from app._04_decision.talking_scroll import (
            PURPOSE_SPELLBOOK,
            SCRATCH_MOTHER_TREE_STAY,
            emit_talking_scroll,
        )

        if emit_talking_scroll(
            blackboard,
            purpose=PURPOSE_SPELLBOOK,
            reason="mother tree recovered, 마법서 상인",
        ) is Status.SUCCESS:
            blackboard.scratch["mother_tree_trip"] = "scroll"
            return Status.SUCCESS
        # No talking scroll: stay on mainland (where the tree is) and farm.
        blackboard.scratch[SCRATCH_MOTHER_TREE_STAY] = True
        finish_retreat(blackboard)
        return Status.FAILURE

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
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        RETREAT_SCROLL_LABELS,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_RETREAT_SCROLL,
        emit_talking_scroll,
        talking_scroll_available,
    )

    purpose = blackboard.scratch.get(SCRATCH_RETREAT_SCROLL)
    if not purpose:
        return None
    if not talking_scroll_available():
        blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
        return None
    label = RETREAT_SCROLL_LABELS.get(str(purpose), str(purpose))
    if emit_talking_scroll(
        blackboard,
        purpose=str(purpose),
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


def tick_retreating(state: "GameState", blackboard: "Blackboard") -> Status:
    update_death_timer(blackboard, state)

    # Confirmed death (HP=0 for 2s + level loaded) → click restart UI.
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

    mother = _tick_mother_tree_retreat(state, blackboard)
    if mother is not None:
        return mother

    if retreat_exit_ready(blackboard, state):
        finish_retreat(blackboard)
        # One more dispatch this tick via manager loop.
        return Status.FAILURE

    # Dead / death screen: do not talking-scroll or walk.
    if waiting_for_respawn(blackboard, state) or is_hp_zero(state):
        blackboard.emit(
            ActionType.IDLE,
            priority=0.95,
            reason="waiting for respawn",
        )
        return Status.SUCCESS

    scroll = _maybe_retreat_talking_scroll(blackboard)
    if scroll is not None:
        return scroll

    blackboard.current_goal = "retreating"
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED

    if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
        # Safe-zone scroll already landed this retreat — drop pending TP.
        blackboard.retreat_teleport_pending = False

    if blackboard.retreat_teleport_pending:
        from app._04_decision.behaviors.mode_actions import (
            _can_teleport_now,
            arm_hp_escape_fallback,
        )
        from app._05_action.spell_box import slot_is_enabled

        if shopping_blocks_teleport(blackboard):
            blackboard.retreat_teleport_pending = False
        elif not slot_is_enabled("teleport") or not _can_teleport_now(
            state, blackboard
        ):
            blackboard.retreat_teleport_pending = False
            # TP was chosen for HP but cannot cast (mana / hotbar) — escape now.
            fallback = arm_hp_escape_fallback(state, blackboard)
            if fallback is HP_RETREAT_STARTED:
                mother = _tick_mother_tree_retreat(state, blackboard)
                if mother is not None:
                    return mother
            elif fallback is not None:
                return fallback
        else:
            hopped = _emit_escape_teleport(blackboard, "retreat teleport", state)
            if hopped is not None:
                return hopped

    if maybe_escalate_teleport_to_safe(state, blackboard):
        hop = _maybe_retreat_talking_scroll(blackboard)
        if hop is not None:
            return hop

    # TP / 두루마리 착지 후 힐·물약 없고 HP<50% → 세계수 1회, 그다음 50% 대기.
    post_land_tree = maybe_mother_tree_before_passive_wait(state, blackboard)
    if post_land_tree is HP_RETREAT_STARTED:
        mother = _tick_mother_tree_retreat(state, blackboard)
        if mother is not None:
            return mother
    elif post_land_tree is not None:
        return post_land_tree

    healed = _maybe_support_spells(state, blackboard, allow_buffs=False)
    if healed is not None:
        return healed

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
    if support is not None:
        return support

    # No combat while retreating; loot only when no attackable enemy is around.
    loot = retreat_loot_if_clear(state, blackboard)
    if loot is not None:
        return loot

    if blackboard.nav_goal is not None and emit_travel_hop(
        blackboard, reason="retreat to safe area", priority=0.95
    ):
        return Status.SUCCESS

    # Idling while recovering: if HP tanks further (≤10%), teleport to another
    # painted safe. Talking-scroll landings are already safe — stand still.
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

    # No path / no goal: idle in place until HP/MP recovers enough to exit.
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


def _enter_farm_travel(blackboard: "Blackboard") -> bool:
    """True when traveling to enter / rotate into a farm area."""
    return blackboard.travel_purpose in (PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM)


def _patrol_travel(blackboard: "Blackboard") -> bool:
    from app._04_decision.patrol import PURPOSE_PATROL

    return blackboard.travel_purpose == PURPOSE_PATROL


def _maybe_confined_escape(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Teleport / talking scroll after 13 s inside a 5-tile bubble.

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
        from app.bot_log import event

        event("nav", "confined escape fired (bubble timeout)")
        return Status.SUCCESS
    return None


def tick_traveling(state: "GameState", blackboard: "Blackboard") -> Status:
    death = _maybe_death(state, blackboard)
    if death is not None:
        return death

    emergency = _maybe_emergency_teleport(state, blackboard)
    if emergency is not None:
        return emergency

    hp_act = apply_hp_actions(state, blackboard)
    if hp_act is HP_RETREAT_STARTED:
        return tick_retreating(state, blackboard)
    if hp_act is not None:
        return hp_act

    if _maybe_low_mp_to_safe(state, blackboard):
        return tick_retreating(state, blackboard)

    if _maybe_return_on_vitals(state, blackboard):
        return tick_retreating(state, blackboard)

    support = _maybe_support_spells(state, blackboard, allow_buffs=False)
    if support is not None:
        return support

    buff = _maybe_support_spells(state, blackboard, allow_buffs=True)
    if buff is not None:
        return buff

    confined = _maybe_confined_escape(state, blackboard)
    if confined is not None:
        return confined

    shop = _maybe_shop_trip(state, blackboard)
    if shop is not None:
        return shop

    from app._04_decision.species_rules import is_newbie_player
    from app._04_decision.talking_scroll import PURPOSE_TRAINING, SCRATCH_NEWBIE_TRAINING

    if blackboard.travel_purpose == PURPOSE_TRAINING and not is_newbie_player(state):
        clear_travel(blackboard)
        blackboard.travel_purpose = None
        blackboard.scratch.pop(SCRATCH_NEWBIE_TRAINING, None)
        set_mode(blackboard, PlayerMode.FARMING)
        return Status.FAILURE

    # Enter / next-farm / dungeon patrol: fight and loot on the way.
    if _enter_farm_travel(blackboard) or _patrol_travel(blackboard):
        hunt_map = _maybe_scroll_to_hunt_map(state, blackboard)
        if hunt_map is not None:
            return hunt_map
        result = farm_loot_or_combat(
            state, blackboard, restrict_to_farm=False
        )
        if result is not None:
            return result

    # Enter / next-farm travel is not done until we are actually inside the farm.
    # Near-edge goals + farm_area.ARRIVE_TILES can otherwise "arrive" while still outside,
    # which leaves farming with no intent (idle).
    if _should_push_deeper_into_farm(blackboard):
        if _retarget_farm_entry(blackboard):
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

    if travel_arrived(blackboard) or blackboard.nav_goal is None:
        complete_travel_arrival(blackboard)
        return Status.FAILURE

    reason = str(blackboard.scratch.get("travel_reason") or "traveling")
    blackboard.current_goal = "traveling"
    if emit_travel_hop(blackboard, reason=reason, priority=0.55):
        return Status.SUCCESS

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
        complete_travel_arrival(blackboard)
    else:
        clear_travel(blackboard)
        set_mode(blackboard, PlayerMode.FARMING)
    return Status.FAILURE


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
    """After death, talking-scroll to 마법서 상인 before walking into a farm.

    Newbies skip this and go to 허수아비 수련장 instead. Slot off: drop the
    flag so farming can resume (walk from spawn).
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
    from app._03_world.world_coords import tile_chebyshev
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
    from app._04_decision.shop_trip import tick_shop_trip

    return tick_shop_trip(state, blackboard)


def _try_farm_upkeep(state: "GameState", blackboard: "Blackboard") -> Status | None:
    """Inventory full / farm timer → travel. Returns Status if handled."""
    shop = _maybe_shop_trip(state, blackboard)
    if shop is not None:
        return shop

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
    farm = farms[next_index]
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
    if farm.contains(ox, oy):
        return None
    from app.bot_log import event

    event("travel", "return/enter farm needed at (%s,%s)", ox, oy)
    hunt_map = _maybe_scroll_to_hunt_map(state, blackboard)
    if hunt_map is not None:
        return hunt_map
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
    )
    if blackboard.intent is not None:
        return Status.SUCCESS

    # Farm hop failed (blocked / no in-view tile): keep moving via spiral.
    dest = blackboard.movement_planner.next_leg(
        blackboard, "search area fallback", persist=False, legacy_spiral=True
    )
    blackboard.search_destination = dest
    blackboard.search_waypoint = None
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


def tick_farming(state: "GameState", blackboard: "Blackboard") -> Status:
    from app._04_decision.dungeon import is_dungeon_map

    if is_dungeon_map():
        return _tick_dungeon_farming(state, blackboard)

    death = _maybe_death(state, blackboard)
    if death is not None:
        return death

    ensure_farm_tour(blackboard)

    emergency = _maybe_emergency_teleport(state, blackboard)
    if emergency is not None:
        return emergency

    hp_act = apply_hp_actions(state, blackboard)
    if hp_act is HP_RETREAT_STARTED:
        return tick_retreating(state, blackboard)
    if hp_act is not None:
        return hp_act

    if _maybe_low_mp_to_safe(state, blackboard):
        return tick_retreating(state, blackboard)

    if _maybe_return_on_vitals(state, blackboard):
        return tick_retreating(state, blackboard)

    if _maybe_return_on_idle(state, blackboard):
        return tick_retreating(state, blackboard)

    support = _maybe_support_spells(state, blackboard, allow_buffs=False)
    if support is not None:
        return support

    buff = _maybe_support_spells(state, blackboard, allow_buffs=True)
    if buff is not None:
        return buff

    confined = _maybe_confined_escape(state, blackboard)
    if confined is not None:
        return confined

    newbie = _tick_newbie_training(state, blackboard)
    if newbie is not None:
        return newbie

    post_death = _maybe_post_respawn_spellbook(state, blackboard)
    if post_death is not None:
        return post_death

    upkeep = _try_farm_upkeep(state, blackboard)
    if upkeep is not None:
        return upkeep

    post_shop = _maybe_post_shop_farm_return(state, blackboard)
    if post_shop is not None:
        return post_shop

    hunt_map = _maybe_scroll_to_hunt_map(state, blackboard)
    if hunt_map is not None:
        return hunt_map

    # Loot / finish a close kill before walking into the farm rect.
    result = farm_loot_or_combat(state, blackboard, restrict_to_farm=False)
    if result is not None:
        _refresh_combat_activity(state, blackboard)
        return result

    entering = _enter_farm_if_needed(state, blackboard)
    if entering is not None:
        return entering

    _refresh_combat_activity(state, blackboard)
    return _search_inside_farm(state, blackboard)


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


def _tick_dungeon_farming(
    state: "GameState", blackboard: "Blackboard"
) -> Status:
    """Dungeon: combat/loot, else patrol midpoints (no island search)."""
    from app._04_decision.patrol import begin_or_continue_patrol, get_patrol_waypoints
    from app._04_decision.talking_scroll import (
        hunt_map_is_dungeon,
        player_on_selected_map,
    )

    death = _maybe_dungeon_death(state, blackboard)
    if death is not None:
        return death

    emergency = _maybe_emergency_teleport(state, blackboard)
    if emergency is not None:
        return emergency

    hp_act = apply_hp_actions(state, blackboard)
    if hp_act is HP_RETREAT_STARTED:
        return tick_retreating(state, blackboard)
    if hp_act is not None:
        return hp_act

    if _maybe_low_mp_to_safe(state, blackboard):
        return tick_retreating(state, blackboard)

    if _maybe_return_on_vitals(state, blackboard):
        return tick_retreating(state, blackboard)

    if _maybe_return_on_idle(state, blackboard):
        return tick_retreating(state, blackboard)

    support = _maybe_support_spells(state, blackboard, allow_buffs=False)
    if support is not None:
        return support

    buff = _maybe_support_spells(state, blackboard, allow_buffs=True)
    if buff is not None:
        return buff

    confined = _maybe_confined_escape(state, blackboard)
    if confined is not None:
        return confined

    # Island tick still trains at 허수아비. Dungeon floors must not leave.
    post_death = _maybe_post_respawn_spellbook(state, blackboard)
    if post_death is not None:
        return post_death

    # Weight / potion / arrow shop — not inventory-full. No farm-timer rotation.
    shop = _maybe_shop_trip(state, blackboard)
    if shop is not None:
        return shop

    post_shop = _maybe_post_shop_farm_return(state, blackboard)
    if post_shop is not None:
        return post_shop

    hunt_map = _maybe_scroll_to_hunt_map(state, blackboard)
    if hunt_map is not None:
        return hunt_map

    if hunt_map_is_dungeon() and not player_on_selected_map(blackboard):
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="dungeon, off hunt floor",
        )
        return Status.SUCCESS

    result = farm_loot_or_combat(
        state, blackboard, restrict_to_farm=False
    )
    if result is not None:
        _refresh_combat_activity(state, blackboard)
        return result

    _refresh_combat_activity(state, blackboard)

    if not get_patrol_waypoints():
        blackboard.emit(
            ActionType.IDLE,
            priority=0.2,
            reason="dungeon, no patrol waypoints",
        )
        return Status.SUCCESS

    if begin_or_continue_patrol(blackboard):
        return tick_traveling(state, blackboard)

    blackboard.emit(
        ActionType.IDLE,
        priority=0.2,
        reason="dungeon patrol idle",
    )
    return Status.SUCCESS


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


def tick_mode(state: "GameState", blackboard: "Blackboard") -> Status:
    """Dispatch one mode tick. May change ``player_mode`` mid-call."""
    death = _maybe_death(state, blackboard)
    if death is not None:
        return death
    dismiss = _maybe_dismiss_level_up(state, blackboard)
    if dismiss is not None:
        return dismiss
    mode = blackboard.player_mode
    if mode is PlayerMode.RETREATING:
        return tick_retreating(state, blackboard)
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
]
