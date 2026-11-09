"""L2 sticky mode transitions (``begin_travel`` / ``begin_retreat`` / …).

Also hosts shared HP/MP ratio helpers used by L3/L5. Mode assignment should
go through these APIs. See ``Docs/architecture/DECISION_HIERARCHY.md``.
"""
from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Optional

from app._03_world import CharacterType, Position
from app._04_decision import farm_area
from app._04_decision.nav_config import (
    get_active_farm,
    get_home_tile,
    get_safe_areas,
    get_terrain_map,
    nearest_safe_area,
    safe_containing,
    safe_for_goal,
)
from app._04_decision import player_mode as pm
from app._04_decision.player_mode import PlayerMode

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

# Travel purpose tags stored on the blackboard.
PURPOSE_HOME = "home"
PURPOSE_NEXT_FARM = "next_farm"
PURPOSE_ENTER_FARM = "enter_farm"
PURPOSE_SAFE = "safe"
PURPOSE_PATROL = "patrol"

RETREAT_FOR_HP = "hp"
RETREAT_FOR_MP = "mp"
RETREAT_FOR_RETURN = "return"

# Death → respawn UI click (content UV on a 1280×960 reference).
DEATH_CONFIRM_SECONDS = 2.0
RESPAWN_CLICK_COOLDOWN = 5.0
RESPAWN_REF_W = 1280.0
RESPAWN_REF_H = 960.0
RESPAWN_PX_X = 1110.0
RESPAWN_PX_Y = 135.0
RESPAWN_PX_JITTER = 10.0

_SCRATCH_HP_ZERO_SINCE = "hp_zero_since"
_SCRATCH_RESPAWN_AT = "respawn_clicked_at"
_SCRATCH_WAS_DEAD = "was_confirmed_dead"


def hp_ratio(state: "GameState") -> Optional[float]:
    player = state.player
    if player is None or player.hp is None:
        return None
    if player.max_hp:
        return player.hp / player.max_hp
    return player.hp_ratio


def mp_ratio(state: "GameState") -> Optional[float]:
    """Current/max from memory. None when MP is not known — never assume 100%."""
    player = getattr(state, "player", None)
    if player is None:
        return None
    mp = player.mp
    max_mp = player.max_mp
    if mp is None or max_mp is None or int(max_mp) <= 0:
        return None
    return max(0.0, min(1.0, float(mp) / float(max_mp)))


def is_critical_hp(state: "GameState") -> bool:
    ratio = hp_ratio(state)
    return ratio is not None and ratio <= pm.HP_CRITICAL_RATIO


def is_idle_emergency_hp(state: "GameState") -> bool:
    """HP ≤ idle-emergency ratio (default 10%) — panic to another safe."""
    ratio = hp_ratio(state)
    return ratio is not None and ratio <= pm.HP_IDLE_EMERGENCY_RATIO


def is_low_hp(state: "GameState") -> bool:
    ratio = hp_ratio(state)
    return ratio is not None and ratio <= pm.HP_LOW_RATIO


def is_almost_full_hp(state: "GameState") -> bool:
    ratio = hp_ratio(state)
    return ratio is not None and ratio >= pm.HP_ALMOST_FULL_RATIO


def is_passive_recovered_hp(state: "GameState") -> bool:
    """True when HP reached the no-heal / no-potion retreat exit (default 50%)."""
    ratio = hp_ratio(state)
    return ratio is not None and ratio >= pm.HP_PASSIVE_RECOVER_RATIO


def is_full_hp(state: "GameState") -> bool:
    ratio = hp_ratio(state)
    return ratio is not None and ratio >= pm.HP_FULL_RATIO


def is_elf(state: "GameState") -> bool:
    player = state.player
    if player is not None and player.character_type is CharacterType.ELF:
        return True
    return getattr(state, "character_type", None) is CharacterType.ELF


def elf_uses_mother_tree(
    state: "GameState",
    blackboard: "Blackboard | None" = None,
) -> bool:
    """True when this elf can use Return to Mother Tree.

    Requires the Setup slot on, plus the live hotbar name when a hotbar
    snapshot is already available (same unread→allow pattern as teleport).
    """
    from app._04_decision.spells import mother_tree_on_live_hotbar
    from app._05_action.spell_box import slot_is_enabled

    if not (
        bool(pm.ELF_MOTHER_TREE)
        and is_elf(state)
        and slot_is_enabled("mother_tree")
    ):
        return False
    snap = getattr(state, "last_hotbar", None)
    if not isinstance(snap, dict) and blackboard is not None:
        snap = blackboard.scratch.get("live_hotbar")
    if isinstance(snap, dict) and isinstance(snap.get("slots"), list) and snap.get("slots"):
        return mother_tree_on_live_hotbar(state, blackboard)
    return True


def vitals_full_at_mother_tree(state: "GameState") -> bool:
    """Stand at the tree until HP is full and MP is recovered (if known)."""
    hp = hp_ratio(state)
    if hp is None or hp < pm.HP_FULL_RATIO:
        return False
    mp = mp_ratio(state)
    if mp is not None and mp < pm.MP_RECOVERED_RATIO:
        return False
    return True


def is_mage(state: "GameState") -> bool:
    player = state.player
    if player is not None and player.character_type is CharacterType.MAGE:
        return True
    return getattr(state, "character_type", None) is CharacterType.MAGE


def is_low_mp(state: "GameState") -> bool:
    ratio = mp_ratio(state)
    return ratio is not None and ratio <= pm.MP_LOW_RATIO


def is_mp_recovered(state: "GameState") -> bool:
    ratio = mp_ratio(state)
    return ratio is not None and ratio >= pm.MP_RECOVERED_RATIO


def is_mage_low_mp(state: "GameState") -> bool:
    """Mage with MP at or below the safe-return threshold."""
    if not pm.MP_ESCAPE_ENABLED:
        return False
    return is_mage(state) and is_low_mp(state)


def needs_return_hp(state: "GameState") -> bool:
    """Fix/Return: HP at or below the configured 귀환 ratio."""
    if not pm.RETURN_HP_ENABLED:
        return False
    ratio = hp_ratio(state)
    return ratio is not None and ratio <= pm.RETURN_HP_RATIO


def needs_return_mp(state: "GameState") -> bool:
    """Fix/Return: mage MP at or below the configured 귀환 ratio."""
    if not pm.RETURN_MP_ENABLED:
        return False
    if not is_mage(state):
        return False
    ratio = mp_ratio(state)
    return ratio is not None and ratio <= pm.RETURN_MP_RATIO


def needs_return_vitals(state: "GameState") -> bool:
    return needs_return_hp(state) or needs_return_mp(state)


def memory_vitals_loaded(state: "GameState") -> bool:
    """True when the monitor has loaded character level (real memory read)."""
    player = state.player
    return player is not None and player.level is not None and player.level > 0


def is_hp_zero(state: "GameState") -> bool:
    """Raw HP≤0 from memory (does not prove death by itself)."""
    player = getattr(state, "player", None)
    return player is not None and player.hp is not None and player.hp <= 0


def arm_post_respawn_retreat(
    blackboard: "Blackboard", state: "GameState"
) -> None:
    """After revive: RETREATING to recover, then world_nav back to the farm.

    Spawn is already off the combat map. Prefer Mother Tree when the elf
    slot is available. Without that spell, heal at the spawn tile until
    ``retreat_exit_ready``, then ``finish_retreat``. A character with no
    talking scroll still walks to the nearest safe.
    """
    from app.bot_log import get_logger
    from app._04_decision.talking_scroll import (
        SCRATCH_POST_RESPAWN_RETREAT,
        SCRATCH_POST_RESPAWN_SCROLL,
        talking_scroll_available,
    )

    blackboard.scratch[SCRATCH_POST_RESPAWN_RETREAT] = True
    # Retreat owns the return trip; farming-column spellbook arm is unused.
    blackboard.scratch.pop(SCRATCH_POST_RESPAWN_SCROLL, None)

    if elf_uses_mother_tree(state, blackboard):
        begin_retreat(
            blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True
        )
        blackboard.scratch["hp_retreat_kind"] = "mother_tree"
        get_logger("hp").info("post-respawn → retreating (mother_tree)")
        return

    if talking_scroll_available():
        # No Mother Tree: stand on the spawn tile and heal. Do not scroll
        # to a safe NPC first — that landing is what walked into the hunt
        # still recovering. The tree branch above is unchanged.
        begin_retreat(
            blackboard,
            reason=RETREAT_FOR_HP,
            teleport=False,
            allow_teleport=False,
            allow_scroll=False,
            walk_to_safe=False,
        )
        from app._04_decision.behaviors.travel import clear_travel

        clear_travel(blackboard)
        blackboard.travel_purpose = None
        blackboard.retreat_teleport_pending = False
        blackboard.scratch["hp_retreat_kind"] = "spawn_heal"
        get_logger("hp").info("post-respawn → retreating (heal at spawn)")
        return

    begin_retreat(
        blackboard,
        reason=RETREAT_FOR_HP,
        teleport=False,
        allow_teleport=False,
        walk_to_safe=True,
    )
    get_logger("hp").info("post-respawn → retreating (heal at/near safe)")


def update_death_timer(blackboard: "Blackboard", state: "GameState") -> None:
    """Track sustained HP=0 only while level is loaded from memory."""
    if memory_vitals_loaded(state) and is_hp_zero(state):
        if blackboard.scratch.get(_SCRATCH_HP_ZERO_SINCE) is None:
            blackboard.scratch[_SCRATCH_HP_ZERO_SINCE] = time.time()
        return
    # Alive again after a confirmed death. Spawn is already safe.
    was_dead = bool(blackboard.scratch.pop(_SCRATCH_WAS_DEAD, False))
    blackboard.scratch.pop(_SCRATCH_HP_ZERO_SINCE, None)
    if not was_dead:
        return
    from app._04_decision.behaviors.travel import clear_travel
    from app._04_decision.talking_scroll import SCRATCH_RETREAT_SCROLL

    blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
    blackboard.retreat_teleport_pending = False
    if blackboard.travel_purpose == PURPOSE_SAFE:
        clear_travel(blackboard)
        blackboard.travel_purpose = None
    from app._04_decision.shop_trip import drop_hp_sell_before_retreat

    drop_hp_sell_before_retreat(blackboard)
    arm_post_respawn_retreat(blackboard, state)


def death_confirmed(blackboard: "Blackboard", state: "GameState") -> bool:
    """HP has been zero for ``DEATH_CONFIRM_SECONDS`` with level loaded."""
    if not memory_vitals_loaded(state) or not is_hp_zero(state):
        return False
    since = blackboard.scratch.get(_SCRATCH_HP_ZERO_SINCE)
    if since is None:
        return False
    return (time.time() - float(since)) >= DEATH_CONFIRM_SECONDS


def sample_respawn_click(*, rng: Optional[random.Random] = None) -> Position:
    """Random content UV for the death-screen restart control."""
    r = rng or random
    jx = r.uniform(-RESPAWN_PX_JITTER, RESPAWN_PX_JITTER)
    jy = r.uniform(-RESPAWN_PX_JITTER, RESPAWN_PX_JITTER)
    return Position(
        x=(RESPAWN_PX_X + jx) / RESPAWN_REF_W,
        y=(RESPAWN_PX_Y + jy) / RESPAWN_REF_H,
    )


def should_emit_respawn(blackboard: "Blackboard", state: "GameState") -> bool:
    """Death confirmed and respawn click cooldown elapsed."""
    from app._04_decision import player_mode as pm

    if not pm.RESURRECT_IF_DEAD:
        return False
    if not death_confirmed(blackboard, state):
        return False
    last = blackboard.scratch.get(_SCRATCH_RESPAWN_AT)
    if last is not None and (time.time() - float(last)) < RESPAWN_CLICK_COOLDOWN:
        return False
    return True


def waiting_for_respawn(blackboard: "Blackboard", state: "GameState") -> bool:
    """True while on the death screen (confirmed or post-click until HP returns)."""
    if death_confirmed(blackboard, state):
        return True
    if blackboard.scratch.get(_SCRATCH_WAS_DEAD) and is_hp_zero(state):
        return True
    return False


def mark_respawn_clicked(blackboard: "Blackboard") -> None:
    blackboard.scratch[_SCRATCH_RESPAWN_AT] = time.time()
    blackboard.scratch[_SCRATCH_WAS_DEAD] = True


def set_mode(blackboard: "Blackboard", mode: PlayerMode) -> None:
    blackboard.player_mode = mode


def begin_travel(
    blackboard: "Blackboard",
    goal: tuple[int, int],
    *,
    purpose: str,
    reason: str,
) -> None:
    """Enter TRAVELING toward ``goal`` without clearing resume_mode."""
    from app._04_decision.behaviors.travel import start_travel

    start_travel(blackboard, goal, reason=reason)
    blackboard.travel_purpose = purpose
    set_mode(blackboard, PlayerMode.TRAVELING)


def begin_retreat(
    blackboard: "Blackboard",
    *,
    reason: str = RETREAT_FOR_HP,
    teleport: Optional[bool] = None,
    exclude_current_safe: bool = False,
    use_mother_tree: bool = False,
    prefer_scroll: bool = False,
    allow_teleport: Optional[bool] = None,
    allow_scroll: Optional[bool] = None,
    walk_to_safe: bool = True,
    scroll_purpose: Optional[str] = None,
) -> bool:
    """Switch to RETREATING.

    Talking scroll (when the slot is on): HP safe-zone hops to one random
    wheel-0 list NPC except 마법서 상인, picked once per retreat. Other
    retreats rotate 마법서 상인 / 허수아비 수련장 / 펫 관리인.

    Otherwise escape-teleport once and walk toward the nearest safe (home
    fallback). Elves with Mother Tree skip the random teleport and stand at
    the tree. When ``exclude_current_safe`` is set (idle emergency), skips
    the safe we are already inside or currently traveling toward.

    ``prefer_scroll`` / ``allow_teleport=False`` are used for Fix/Return 귀환
    so the bot goes to town without random escape teleport.
    ``allow_scroll=False`` forces the teleport+walk path even if a talking
    scroll is equipped.

    Returns False if no destination is available (still enters RETREATING
    unless ``exclude_current_safe`` found no alternate — then unchanged).
    """
    if allow_teleport is False:
        teleport = False
    elif teleport is None:
        teleport = not use_mother_tree

    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        SCRATCH_RETREAT_SCROLL,
        next_retreat_scroll_purpose,
        pick_hp_safe_scroll_spot,
        talking_scroll_available,
    )

    use_scroll = False
    if not use_mother_tree and allow_scroll is not False:
        use_scroll = talking_scroll_available()
        if prefer_scroll:
            use_scroll = talking_scroll_available()

    start = (blackboard.world_origin.x, blackboard.world_origin.y)
    terrain = get_terrain_map()
    exclude = None
    found = None
    if not use_scroll:
        if exclude_current_safe:
            exclude = safe_containing(start) or safe_for_goal(blackboard.nav_goal)
            found = nearest_safe_area(start, terrain, exclude=exclude)
            if found is None:
                # No other safe configured — keep current retreat destination.
                return False
        else:
            found = nearest_safe_area(start, terrain)

    entering = blackboard.player_mode is not PlayerMode.RETREATING
    if entering:
        blackboard.resume_mode = blackboard.player_mode
        stash_trip_for_retreat(blackboard)
    blackboard.current_target_id = None
    blackboard.current_item_id = None
    from app._04_decision.behaviors.combat import clear_engage_state
    from app._04_decision.behaviors.loot_hop import clear_loot_hop
    from app.bot_log import get_logger

    clear_engage_state(blackboard)
    clear_loot_hop(blackboard)
    from app._04_decision.world_nav import clear_world_nav_run
    from app._04_decision.farm_tour import remember_return_farm

    remember_return_farm(blackboard)
    clear_world_nav_run(blackboard)
    if entering:
        from app._04_decision.world_nav.routine import hold_dungeon_routine_clock

        hold_dungeon_routine_clock(blackboard)

    set_mode(blackboard, PlayerMode.RETREATING)
    blackboard.scratch["retreat_for"] = reason
    get_logger("hp").info(
        "begin retreat reason=%s scroll=%s mother_tree=%s teleport=%s prefer_scroll=%s",
        reason,
        bool(use_scroll),
        bool(use_mother_tree),
        bool(teleport),
        bool(prefer_scroll),
    )
    if use_mother_tree:
        if not blackboard.scratch.get("mother_tree_trip"):
            blackboard.scratch["mother_tree_trip"] = "cast"
        blackboard.retreat_teleport_pending = False
        return True
    if not walk_to_safe:
        from app._05_action.spell_box import slot_is_enabled

        blackboard.retreat_teleport_pending = bool(teleport) and slot_is_enabled(
            "teleport"
        )
        if not blackboard.retreat_teleport_pending:
            return False
        from app._04_decision.behaviors.travel import clear_travel

        clear_travel(blackboard)
        blackboard.travel_purpose = None
        return True
    if use_scroll:
        from app._04_decision.behaviors.travel import clear_travel

        blackboard.retreat_teleport_pending = False
        if scroll_purpose:
            blackboard.scratch[SCRATCH_RETREAT_SCROLL] = scroll_purpose
        elif reason == RETREAT_FOR_HP:
            blackboard.scratch[SCRATCH_RETREAT_SCROLL] = HP_SAFE_SCROLL_PURPOSE
        else:
            blackboard.scratch[SCRATCH_RETREAT_SCROLL] = next_retreat_scroll_purpose(
                blackboard
            )
        if (
            reason == RETREAT_FOR_HP
            or blackboard.scratch.get(SCRATCH_RETREAT_SCROLL) == HP_SAFE_SCROLL_PURPOSE
        ):
            blackboard.scratch[SCRATCH_RETREAT_SCROLL] = HP_SAFE_SCROLL_PURPOSE
            pick_hp_safe_scroll_spot(blackboard)
        clear_travel(blackboard)
        blackboard.travel_purpose = None
        return True

    goal: Optional[tuple[int, int]] = None
    if found is not None:
        goal = found[1]
    if goal is None:
        home = get_home_tile()
        if home is not None:
            goal = home
    if goal is None and get_safe_areas():
        goal = get_safe_areas()[0].center()

    if teleport:
        from app._05_action.spell_box import slot_is_enabled

        blackboard.retreat_teleport_pending = slot_is_enabled("teleport")
    elif entering:
        blackboard.retreat_teleport_pending = False

    travel_reason = (
        "retreat to other safe (idle emergency)"
        if exclude_current_safe
        else (
            "return to town (fix/return)"
            if reason == RETREAT_FOR_RETURN
            else (
                "retreat to safe area (low mp)"
                if reason == RETREAT_FOR_MP
                else "retreat to safe area"
            )
        )
    )
    if goal is None:
        if blackboard.retreat_teleport_pending:
            from app._04_decision.behaviors.travel import clear_travel

            clear_travel(blackboard)
            blackboard.travel_purpose = None
            return True
        return False

    from app._04_decision.behaviors.travel import start_travel

    start_travel(blackboard, goal, reason=travel_reason)
    blackboard.travel_purpose = PURPOSE_SAFE
    return True


def retreat_exit_ready(blackboard: "Blackboard", state: "GameState") -> bool:
    """Leave retreating when recovered (HP or MP depending on cause)."""
    from app._04_decision.behaviors.travel import travel_arrived
    from app._04_decision.talking_scroll import SCRATCH_RETREAT_SCROLL

    trip = blackboard.scratch.get("mother_tree_trip")
    if trip == "cast":
        return False

    if blackboard.scratch.get("retreat_for") == RETREAT_FOR_MP:
        return is_mp_recovered(state)

    if blackboard.scratch.get("retreat_for") == RETREAT_FOR_RETURN:
        if is_full_hp(state):
            return True
        if travel_arrived(blackboard) and hp_ratio(state) is None:
            return True
        from app._04_decision.behaviors.mode_actions import can_active_hp_recover

        if can_active_hp_recover(state):
            return travel_arrived(blackboard) and is_almost_full_hp(state)
        return is_passive_recovered_hp(state)

    if blackboard.retreat_teleport_pending:
        return False
    if blackboard.scratch.get(SCRATCH_RETREAT_SCROLL):
        return False
    if blackboard.nav_goal is not None and not travel_arrived(blackboard):
        return False
    from app._04_decision.behaviors.mode_actions import resume_hunt_above_retreat_limit

    if resume_hunt_above_retreat_limit(state, blackboard):
        return True
    return is_almost_full_hp(state)


def finish_retreat(blackboard: "Blackboard") -> None:
    """Exit retreat. A saved walk cell is not resumed.

    World nav plans from the live pose to the active routine row. That
    includes a traveling retreat whose landing is still judged on the
    selected map. Shop resume and post-respawn stay on their own branches.
    """
    from app.bot_log import get_logger

    stash = blackboard.scratch.pop("retreat_nav_goal", None)
    stash_purpose = blackboard.scratch.pop("retreat_travel_purpose", None)
    for_reason = blackboard.scratch.pop("retreat_for", None)
    blackboard.scratch.pop("mother_tree_trip", None)
    blackboard.scratch.pop("mother_tree_cast_at", None)
    blackboard.scratch.pop("hp_retreat_kind", None)
    blackboard.scratch.pop("hp_post_land_tree_tried", None)
    from app._04_decision.talking_scroll import (
        SCRATCH_HP_SAFE_REGEN,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_HP_SAFE_SPOT,
        SCRATCH_NAV_RELOAD_MAP,
        SCRATCH_POST_RESPAWN_RETREAT,
        SCRATCH_POST_RESPAWN_SCROLL,
        SCRATCH_RETREAT_SCROLL,
    )

    blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
    blackboard.scratch.pop(SCRATCH_HP_SAFE_REGEN, None)
    blackboard.scratch.pop(SCRATCH_HP_SAFE_SCROLLED, None)
    blackboard.scratch.pop(SCRATCH_HP_SAFE_SPOT, None)
    blackboard.scratch.pop(SCRATCH_NAV_RELOAD_MAP, None)
    resume = blackboard.resume_mode or PlayerMode.FARMING
    blackboard.resume_mode = None
    blackboard.retreat_teleport_pending = False
    get_logger("hp").info(
        "finish retreat was=%s resume=%s stash=%s purpose=%s",
        for_reason,
        resume.value if hasattr(resume, "value") else resume,
        stash,
        stash_purpose,
    )

    from app._04_decision.behaviors.travel import clear_travel

    clear_travel(blackboard)

    # Post-respawn recover finished: re-enter the farm via world nav (not
    # farm-from-spawn). Clear the legacy farming-column spellbook arm too.
    if blackboard.scratch.pop(SCRATCH_POST_RESPAWN_RETREAT, None):
        blackboard.scratch.pop(SCRATCH_POST_RESPAWN_SCROLL, None)
        set_mode(blackboard, PlayerMode.FARMING)
        from app._04_decision.world_nav import begin_world_nav

        begin_world_nav(blackboard, "post_respawn")
        return

    if blackboard.scratch.get(SCRATCH_POST_RESPAWN_SCROLL):
        set_mode(blackboard, PlayerMode.FARMING)
        return

    from app._04_decision.talking_scroll import (
        SCRATCH_SHOP_TRIP,
        player_on_selected_map,
    )
    from app._04_decision.shop_trip import begin_shopping
    from app._04_decision.world_nav import begin_world_nav

    # Resume an interrupted shop trip before re-arming world nav.
    if resume is PlayerMode.SHOPPING or blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        begin_shopping(blackboard, "post_retreat")
        return

    on_hunt = player_on_selected_map(blackboard)
    # Traveling resume used to walk the saved cell on this terrain. That cell
    # is the old trip's destination, so return through world nav instead.
    if on_hunt and resume is PlayerMode.TRAVELING and stash is not None:
        get_logger("hp").info(
            "retreat on hunt map — world nav return dropped stash=%s purpose=%s",
            stash,
            stash_purpose,
        )
        begin_world_nav(blackboard, "post_retreat")
        return

    # Mother tree / teleport / scroll: the saved cell belongs to the map we left.
    if not on_hunt:
        from app._04_decision.dungeon_floor_route import (
            SCRATCH_DUNGEON_FLOOR_ROUTE,
            inside_target_dungeon,
        )

        if inside_target_dungeon(blackboard):
            # Same complex, other floor: plan again from here. Do not walk
            # back to the entrance.
            blackboard.scratch.pop(SCRATCH_DUNGEON_FLOOR_ROUTE, None)
            get_logger("hp").info(
                "retreat inside dungeon family — floor route resume"
            )
            set_mode(blackboard, PlayerMode.FARMING)
            return
        get_logger("hp").info(
            "retreat off hunt map — world nav return dropped stash=%s purpose=%s",
            stash,
            stash_purpose,
        )
        begin_world_nav(blackboard, "post_retreat")
        return

    farm = get_active_farm(blackboard.farm_area_index)
    ox, oy = blackboard.world_origin.x, blackboard.world_origin.y
    from app._04_decision.dungeon import is_dungeon_map

    # Still on the hunt map, outside the farm (or a dungeon floor with no trip).
    if is_dungeon_map() or (farm is not None and not farm.contains(ox, oy)):
        begin_world_nav(blackboard, "post_retreat")
        return
    set_mode(blackboard, PlayerMode.FARMING)
    # Do not reset in-farm accumulator — retreat time outside does not count,
    # and returning to the same farm continues the same stay.


def stash_trip_for_retreat(blackboard: "Blackboard") -> None:
    """Remember active trip so retreat can restore it."""
    if blackboard.nav_goal is not None:
        blackboard.scratch["retreat_nav_goal"] = blackboard.nav_goal
        blackboard.scratch["retreat_travel_purpose"] = blackboard.travel_purpose


def complete_travel_arrival(blackboard: "Blackboard") -> None:
    """Called when ``nav_goal`` is reached outside retreating."""
    from app._04_decision.behaviors.travel import clear_travel

    purpose = blackboard.travel_purpose
    clear_travel(blackboard)
    blackboard.travel_purpose = None
    if purpose == PURPOSE_HOME:
        set_mode(blackboard, PlayerMode.FARMING)
        return
    from app._04_decision.talking_scroll import (
        PURPOSE_TRAINING,
        SCRATCH_NEWBIE_TRAINING,
    )

    if purpose == PURPOSE_TRAINING:
        blackboard.scratch[SCRATCH_NEWBIE_TRAINING] = True
        set_mode(blackboard, PlayerMode.FARMING)
        return
    from app._04_decision.talking_scroll import PURPOSE_SHOP

    if purpose == PURPOSE_SHOP:
        # Stall open is owned by PlayerMode.SHOPPING / tick_shop_trip.
        from app._04_decision.shop_trip import ensure_shopping_mode

        ensure_shopping_mode(blackboard)
        return
    if purpose == PURPOSE_PATROL:
        from app._04_decision.patrol import (
            PURPOSE_PATROL as _PP,
            advance_patrol,
        )

        del _PP
        nxt = advance_patrol(blackboard)
        if nxt is not None:
            begin_travel(
                blackboard,
                nxt,
                purpose=PURPOSE_PATROL,
                reason=f"patrol waypoint {int(blackboard.patrol_index)}",
            )
            return
        set_mode(blackboard, PlayerMode.FARMING)
        return
    if purpose in (PURPOSE_NEXT_FARM, PURPOSE_ENTER_FARM, None):
        # The stay clock already started when the character entered the rect.
        # Arriving at the center must not zero it.
        blackboard.farm_visit.clear()
        blackboard.scratch.pop("changing_area", None)
        set_mode(blackboard, PlayerMode.FARMING)
        return
    set_mode(blackboard, PlayerMode.FARMING)


__all__ = [
    "PURPOSE_HOME",
    "PURPOSE_NEXT_FARM",
    "PURPOSE_ENTER_FARM",
    "PURPOSE_SAFE",
    "PURPOSE_PATROL",
    "RETREAT_FOR_HP",
    "RETREAT_FOR_MP",
    "RETREAT_FOR_RETURN",
    "DEATH_CONFIRM_SECONDS",
    "RESPAWN_CLICK_COOLDOWN",
    "hp_ratio",
    "mp_ratio",
    "is_critical_hp",
    "is_idle_emergency_hp",
    "is_low_hp",
    "is_almost_full_hp",
    "is_passive_recovered_hp",
    "is_full_hp",
    "is_mage",
    "is_elf",
    "elf_uses_mother_tree",
    "vitals_full_at_mother_tree",
    "is_low_mp",
    "is_mp_recovered",
    "is_mage_low_mp",
    "needs_return_hp",
    "needs_return_mp",
    "needs_return_vitals",
    "memory_vitals_loaded",
    "is_hp_zero",
    "arm_post_respawn_retreat",
    "update_death_timer",
    "death_confirmed",
    "sample_respawn_click",
    "should_emit_respawn",
    "waiting_for_respawn",
    "mark_respawn_clicked",
    "set_mode",
    "begin_travel",
    "begin_retreat",
    "retreat_exit_ready",
    "finish_retreat",
    "stash_trip_for_retreat",
    "complete_travel_arrival",
]
