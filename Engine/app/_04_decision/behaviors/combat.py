"""Combat behavior (Priority 3): engage the best monster."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world import ObjectStatus, ObjectType
from app._04_decision.clickgap import log_sticky_release

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

# Last-resort stuck timer. A living target is not dropped before this.
MAX_ENGAGE_SECONDS = 90.0
# Hunt/Attack "same monster N seconds then give up". Off = legacy sticky.
ABANDON_SAME_ENABLED = False
ABANDON_SECONDS = 30.0
# Only used when print_state is missing. A listed death / omit drops instantly.
STICKY_MISS_FRAMES = 1
# After giving up on a target, do not re-select it for this many ticks.
GIVE_UP_COOLDOWN_TICKS = 160
# When TrackIds remaps a heap pointer, keep the same mob within this radius.
STICKY_REBIND_TILES = 2
# Same world tile after this many attack clicks. Living sticky is not dropped.
ATTACK_STILL_TRIES = 5
# Exp rise releases the sticky kill. Off until the kill signal is trusted.
EXP_KILL_RELEASE_ENABLED = False
SCRATCH_STILL_TILE = "attack_still_tile"
SCRATCH_STILL_TRIES = "attack_still_tries"


def _strip_species_key(text: str) -> str:
    from app._03_world.constants import _strip_species_level_suffix

    return _strip_species_level_suffix(text.strip()).lower()


def target_species_key(obj: object) -> str:
    """Stable species token (level suffix stripped) for sticky rebind."""
    raw = (getattr(obj, "species_name", None) or "").strip()
    if raw:
        return _strip_species_key(raw)
    detail = (getattr(obj, "detail_classification", None) or "").strip()
    if detail:
        return _strip_species_key(detail)
    ident = getattr(obj, "identity", None)
    name = (getattr(ident, "name", None) or "").strip() if ident is not None else ""
    return _strip_species_key(name) if name else ""


def object_world_cell(obj: object) -> tuple[int, int] | None:
    """Absolute memory cell, else relative world_rx/ry used by tests."""
    cx = getattr(obj, "world_cx", None)
    cy = getattr(obj, "world_cy", None)
    if cx is not None and cy is not None:
        return (int(cx), int(cy))
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    if rx is not None and ry is not None:
        return (int(rx), int(ry))
    return None


def stamp_sticky_target(blackboard: "Blackboard", obj: object | None) -> None:
    """Remember species + last cell so a TrackId rematch can continue the kill."""
    if obj is None:
        return
    key = target_species_key(obj)
    if key:
        blackboard.current_target_species = key
    cell = object_world_cell(obj)
    if cell is not None:
        blackboard.current_target_world = cell
    try:
        from app._03_world.merge.item_sight import note_monster_cell

        note_monster_cell(obj, cell=cell)
    except Exception:
        pass


def clear_engage_state(blackboard: "Blackboard") -> None:
    """Reset sticky-engage timer and identity (call when the target is cleared)."""
    blackboard.target_engage_started = 0.0
    blackboard.current_target_species = None
    blackboard.current_target_world = None
    from app._04_decision.behaviors.unstick import (
        SCRATCH_BLOCK_AT,
        SCRATCH_BLOCK_SIDESTEP,
        SCRATCH_BLOCK_TID,
        SCRATCH_BLOCK_TILE,
    )

    blackboard.scratch.pop(SCRATCH_BLOCK_TID, None)
    blackboard.scratch.pop(SCRATCH_BLOCK_TILE, None)
    blackboard.scratch.pop(SCRATCH_BLOCK_AT, None)
    blackboard.scratch.pop(SCRATCH_BLOCK_SIDESTEP, None)
    blackboard.sticky_attacked_me = False
    reset_attack_still(blackboard)
    from app._04_decision.combat_query import SCRATCH_CURSOR_ENGAGE

    blackboard.scratch.pop(SCRATCH_CURSOR_ENGAGE, None)


def reset_attack_still(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(SCRATCH_STILL_TILE, None)
    blackboard.scratch.pop(SCRATCH_STILL_TRIES, None)


def note_attack_attempt(blackboard: "Blackboard", obj: object | None) -> None:
    """Count a click on ``obj``. Resets when its world tile changes."""
    cell = object_world_cell(obj) if obj is not None else None
    if cell is None:
        reset_attack_still(blackboard)
        return
    prev = blackboard.scratch.get(SCRATCH_STILL_TILE)
    if prev is None or tuple(prev) != cell:
        blackboard.scratch[SCRATCH_STILL_TILE] = list(cell)
        blackboard.scratch[SCRATCH_STILL_TRIES] = 1
        return
    blackboard.scratch[SCRATCH_STILL_TRIES] = int(
        blackboard.scratch.get(SCRATCH_STILL_TRIES) or 0
    ) + 1


def attack_still_exhausted(blackboard: "Blackboard", obj: object | None) -> bool:
    """True after ``ATTACK_STILL_TRIES`` clicks with no tile change."""
    cell = object_world_cell(obj) if obj is not None else None
    if cell is None:
        return False
    prev = blackboard.scratch.get(SCRATCH_STILL_TILE)
    if prev is None or tuple(prev) != cell:
        return False
    return int(blackboard.scratch.get(SCRATCH_STILL_TRIES) or 0) >= int(
        ATTACK_STILL_TRIES
    )


def _arm_finish_kill(
    blackboard: "Blackboard",
    obj: object | None,
    target_id: int,
) -> None:
    """Mark self-defense target for engage priority (attacks_me).

    Does not block give-up / abandon / max-engage sticky release.
    """
    if obj is None:
        return
    setattr(obj, "finish_kill_until_dead", True)
    blackboard.finish_kill_ids.add(int(target_id))


def _clear_finish_kill(
    state: "GameState | None",
    blackboard: "Blackboard",
    target_id: int | None,
) -> None:
    if target_id is None:
        return
    tid = int(target_id)
    blackboard.finish_kill_ids.discard(tid)
    if state is None:
        return
    obj = state.get_object(tid)
    if obj is None:
        return
    setattr(obj, "finish_kill_until_dead", False)
    if getattr(obj, "force_attacks_me", False):
        obj.status = ObjectStatus.DEAD


def begin_engage(
    state: "GameState",
    blackboard: "Blackboard",
    target_id: int,
    *,
    finish_kill: bool = False,
) -> None:
    """Bind sticky combat to ``target_id`` and start the engage clock."""
    from app.bot_log import get_logger

    prev = blackboard.current_target_id
    if prev is not None and int(prev) != int(target_id):
        blackboard.finish_kill_ids.discard(int(prev))
        prev_obj = state.get_object(int(prev))
        if prev_obj is not None:
            setattr(prev_obj, "finish_kill_until_dead", False)
    blackboard.current_target_id = target_id
    clear_engage_state(blackboard)
    blackboard.target_engage_started = time.time()
    obj = state.get_object(target_id)
    stamp_sticky_target(blackboard, obj)
    blackboard.sticky_attacked_me = bool(
        obj is not None and getattr(obj, "attacked_me", False)
    )
    if finish_kill or (
        obj is not None and getattr(obj, "force_attacks_me", False)
    ):
        _arm_finish_kill(blackboard, obj, int(target_id))
    species = getattr(obj, "species_name", None) if obj is not None else None
    rx = getattr(obj, "world_rx", None) if obj is not None else None
    ry = getattr(obj, "world_ry", None) if obj is not None else None
    get_logger("combat").info(
        "engage id=%s species=%s rel=(%s,%s) finish_kill=%s",
        target_id,
        species or "?",
        rx if rx is not None else "?",
        ry if ry is not None else "?",
        int(target_id) in blackboard.finish_kill_ids,
    )


def sticky_identity(blackboard: "Blackboard") -> bool:
    """True while a kill lock (id / species / last cell) is still held."""
    return bool(
        blackboard.current_target_id is not None
        or blackboard.current_target_species
        or blackboard.current_target_world is not None
    )


def sticky_target_alive(state: "GameState", target_id: int) -> bool:
    """True while this id is a living monster still listed this tick.

    A missing sweep row is not a death signal. Occlusion, path, and mage
    range do not break a kill already in progress. Dead / bait never stick.
    """
    from app._04_decision.combat_query import fresh_memory_sweep, memory_target_gone

    obj = state.get_object(target_id)
    if obj is None or obj.object_type is not ObjectType.MONSTER:
        return False
    if obj.status is ObjectStatus.DEAD:
        return False
    if bool(getattr(obj, "bait", False)):
        return False
    if memory_target_gone(state, obj):
        return False
    if fresh_memory_sweep(state):
        return True
    if state.missing_frames(target_id) > STICKY_MISS_FRAMES:
        return False
    return True


def _cell_in_track_window(
    cell: tuple[int, int] | None,
    last: object | None,
) -> bool:
    if last is None or cell is None:
        return True
    lx, ly = int(last[0]), int(last[1])
    return max(abs(cell[0] - lx), abs(cell[1] - ly)) <= int(STICKY_REBIND_TILES)


def species_death_signal(state: "GameState", blackboard: "Blackboard") -> bool:
    """True when a dead monster of the sticky species is seen in the 2-tile window."""
    species = (blackboard.current_target_species or "").strip().lower()
    last = blackboard.current_target_world
    if not species:
        tid = blackboard.current_target_id
        obj = state.get_object(tid) if tid is not None else None
        return bool(obj is not None and getattr(obj, "status", None) is ObjectStatus.DEAD)
    monsters = list(state.monsters()) if hasattr(state, "monsters") else []
    tid = blackboard.current_target_id
    if tid is not None:
        extra = state.get_object(tid)
        if extra is not None and extra not in monsters:
            monsters.append(extra)
    for obj in monsters:
        if obj is None or getattr(obj, "object_type", None) is not ObjectType.MONSTER:
            continue
        if getattr(obj, "status", None) is not ObjectStatus.DEAD:
            continue
        if target_species_key(obj) != species:
            continue
        if _cell_in_track_window(object_world_cell(obj), last):
            return True
    return False


def _living_same_species(
    state: "GameState",
    blackboard: "Blackboard",
    obj: object,
) -> bool:
    from app._04_decision.combat_query import memory_target_gone

    if obj is None or getattr(obj, "object_type", None) is not ObjectType.MONSTER:
        return False
    if getattr(obj, "status", None) is ObjectStatus.DEAD:
        return False
    if memory_target_gone(state, obj):
        return False
    tid = getattr(obj, "track_id", None)
    if tid is not None:
        blocked = set(blackboard.blacklisted_target_ids)
        blocked.update(blackboard.given_up_target_ids)
        if tid in blocked:
            return False
    species = (blackboard.current_target_species or "").strip().lower()
    if species and target_species_key(obj) != species:
        return False
    return True


def _find_rebind_candidate(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    window_only: bool = True,
) -> object | None:
    """Same-species living mob. ``window_only`` limits to the last-cell 2-tile track."""
    species = (blackboard.current_target_species or "").strip().lower()
    last = blackboard.current_target_world
    if not species and last is None:
        return None
    monsters = state.monsters() if hasattr(state, "monsters") else []
    scored: list[tuple[int, int, object]] = []
    for obj in monsters:
        if not _living_same_species(state, blackboard, obj):
            continue
        cell = object_world_cell(obj)
        if window_only and last is not None:
            if cell is None:
                continue
            last_dist = max(abs(cell[0] - last[0]), abs(cell[1] - last[1]))
            if last_dist > STICKY_REBIND_TILES:
                continue
        elif last is not None and cell is not None:
            last_dist = max(abs(cell[0] - last[0]), abs(cell[1] - last[1]))
        else:
            last_dist = 0
        scored.append((last_dist, _player_tiles(obj), obj))
    if not scored:
        return None
    if last is None and window_only and len(scored) != 1:
        return None
    if window_only:
        scored.sort(
            key=lambda pair: (
                pair[0],
                pair[1],
                int(getattr(pair[2], "track_id", 0)),
            )
        )
    else:
        scored.sort(
            key=lambda pair: (
                pair[1],
                pair[0],
                int(getattr(pair[2], "track_id", 0)),
            )
        )
    return scored[0][2]


def _player_tiles(obj: object) -> int:
    from app._03_world.space.world_coords import distance_tiles_from_memory

    known = distance_tiles_from_memory(obj)
    if known is not None:
        return known
    from app._04_decision.combat_query import tile_distance_from_player

    try:
        return int(tile_distance_from_player(obj))  # type: ignore[arg-type]
    except Exception:
        return 10_000


def _carry_cursor_engage(
    blackboard: "Blackboard",
    old_id: int | None,
    new_id: int,
) -> None:
    """Keep the client-cursor lock when the same mob gets a new track id."""
    from app._04_decision.combat_query import SCRATCH_CURSOR_ENGAGE

    held = blackboard.scratch.get(SCRATCH_CURSOR_ENGAGE)
    try:
        if held is not None and old_id is not None and int(held) == int(old_id):
            blackboard.scratch[SCRATCH_CURSOR_ENGAGE] = int(new_id)
    except (TypeError, ValueError):
        return


def rebind_sticky_target(state: "GameState", blackboard: "Blackboard") -> object | None:
    """Keep the current kill: 2-tile rematch, else nearest same species.

    Death is confirmed only when the 2-tile window is empty and a dead
    monster of that species is seen there. A vanish with neither that
    signal nor a living same-species mob clears the lock so a new target
    can be chosen.

    ``finish_kill`` (attacks_me self-defense) never far-rematches — only
    window rematch or confirmed death — so loot cannot steal the fight.
    """
    tid = blackboard.current_target_id
    finish = tid is not None and int(tid) in blackboard.finish_kill_ids
    if tid is not None and sticky_target_alive(state, tid):
        obj = state.get_object(tid)
        stamp_sticky_target(blackboard, obj)
        blackboard.sticky_attacked_me = bool(
            obj is not None and getattr(obj, "attacked_me", False)
        )
        return obj
    found = _find_rebind_candidate(state, blackboard, window_only=True)
    if found is not None:
        old = int(tid) if tid is not None else None
        if blackboard.sticky_attacked_me:
            found.attacked_me = True
        blackboard.current_target_id = int(found.track_id)
        stamp_sticky_target(blackboard, found)
        blackboard.sticky_attacked_me = bool(getattr(found, "attacked_me", False))
        if finish:
            if old is not None:
                blackboard.finish_kill_ids.discard(old)
            _arm_finish_kill(blackboard, found, int(found.track_id))
        if not blackboard.target_engage_started:
            blackboard.target_engage_started = time.time()
        _carry_cursor_engage(blackboard, old, int(found.track_id))
        return found
    if species_death_signal(state, blackboard):
        try:
            from app._03_world.merge.item_sight import note_monster_kill

            note_monster_kill(
                tid=int(tid) if tid is not None else None,
                species=blackboard.current_target_species,
                cell=blackboard.current_target_world,
            )
        except Exception:
            pass
        _clear_finish_kill(state, blackboard, tid)
        log_sticky_release(state, blackboard, "dead-window")
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
        return None
    if finish:
        # Keep swinging the last finish-kill id / cell; do not chase a far
        # same-species farm target while self-defense is unfinished.
        # Dead or bait clears immediately (no corpse / dormant swings).
        from app._04_decision.combat_query import memory_target_gone

        obj = state.get_object(tid) if tid is not None else None
        if (
            obj is not None
            and getattr(obj, "status", None) is not ObjectStatus.DEAD
            and not bool(getattr(obj, "bait", False))
            and not memory_target_gone(state, obj)
        ):
            stamp_sticky_target(blackboard, obj)
            blackboard.sticky_attacked_me = bool(getattr(obj, "attacked_me", False))
            return obj
        try:
            from app._03_world.merge.item_sight import note_monster_kill

            note_monster_kill(
                tid=int(tid) if tid is not None else None,
                species=blackboard.current_target_species,
                cell=blackboard.current_target_world,
            )
        except Exception:
            pass
        _clear_finish_kill(state, blackboard, tid)
        log_sticky_release(state, blackboard, "finish-gone")
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
        return None
    near = _find_rebind_candidate(state, blackboard, window_only=False)
    if near is not None:
        blackboard.current_target_id = int(near.track_id)
        stamp_sticky_target(blackboard, near)
        blackboard.sticky_attacked_me = bool(getattr(near, "attacked_me", False))
        if not blackboard.target_engage_started:
            blackboard.target_engage_started = time.time()
        return near
    if sticky_identity(blackboard):
        log_sticky_release(state, blackboard, "no-rematch")
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
    return None


def _kill_progress_pair(state: "GameState") -> tuple[str, int, float] | None:
    """(source, level, exp percent) for this tick.

    The monitor snapshot wins. ``player.exp_percent`` is only used when that
    snapshot has no ``expPct`` (tests, or a tick before the first monitor read).
    A missing pair is not stored, so a failed read cannot look like a drop.
    """
    snap = getattr(state, "last_memory_snapshot", None)
    raw = snap.get("player") if isinstance(snap, dict) else None
    if isinstance(raw, dict) and raw.get("expPct") is not None:
        try:
            level_i = int(raw.get("level", raw.get("lv")))
            exp_f = float(raw["expPct"])
        except (TypeError, ValueError):
            return None
        if level_i <= 0:
            return None
        return ("snap", level_i, exp_f)
    player = getattr(state, "player", None)
    if player is None:
        return None
    try:
        level_i = int(getattr(player, "level", None))
        exp_f = float(getattr(player, "exp_percent", None))
    except (TypeError, ValueError):
        return None
    if level_i <= 0:
        return None
    return ("player", level_i, exp_f)


def _prune_exp_kills(state: "GameState", blackboard: "Blackboard") -> None:
    """Drop exp-kill ids that are no longer on the monster list."""
    held = blackboard.exp_kill_ids
    if not held:
        return
    present: set[int] = set()
    monsters = state.monsters() if hasattr(state, "monsters") else []
    for obj in monsters:
        tid = getattr(obj, "track_id", None)
        if tid is None:
            continue
        try:
            present.add(int(tid))
        except (TypeError, ValueError):
            continue
    held.intersection_update(present)


def _progress_rose(
    blackboard: "Blackboard",
    source: str,
    level_i: int,
    exp_f: float,
) -> bool:
    prev_l = blackboard.kill_progress_level
    prev_e = blackboard.kill_progress_exp
    same_source = blackboard.kill_progress_source == source
    if not same_source or prev_l is None or prev_e is None:
        return False
    if not sticky_identity(blackboard):
        return False
    if level_i > int(prev_l):
        return True
    return level_i == int(prev_l) and exp_f > float(prev_e)


def _release_sticky_for_kill(state: "GameState", blackboard: "Blackboard") -> None:
    """Clear the kill lock without the give-up cooldown."""
    tid = blackboard.current_target_id
    try:
        from app._03_world.merge.item_sight import note_monster_kill

        note_monster_kill(
            tid=int(tid) if tid is not None else None,
            species=blackboard.current_target_species,
            cell=blackboard.current_target_world,
        )
    except Exception:
        pass
    log_sticky_release(state, blackboard, "exp")
    _clear_finish_kill(state, blackboard, tid)
    if tid is not None:
        blackboard.exp_kill_ids.add(int(tid))
    blackboard.current_target_id = None
    clear_engage_state(blackboard)


def sample_kill_progress(state: "GameState", blackboard: "Blackboard") -> None:
    """Compare this tick's (level, exp) with the previous tick.

    A rise while a sticky target is held means that monster was killed.
    The lock is cleared immediately. That id stays unselectable until it
    leaves the monster list, so a corpse still marked alive is not clicked
    again. The first pair, a missing read, and a source change only update
    the stored pair. While ``EXP_KILL_RELEASE_ENABLED`` is false a rise is
    logged and the lock stays.
    """
    from app.bot_log import event, get_logger

    if EXP_KILL_RELEASE_ENABLED:
        _prune_exp_kills(state, blackboard)
    pair = _kill_progress_pair(state)
    if pair is None:
        return
    source, level_i, exp_f = pair
    prev_l = blackboard.kill_progress_level
    prev_e = blackboard.kill_progress_exp
    rose = _progress_rose(blackboard, source, level_i, exp_f)
    blackboard.kill_progress_source = source
    blackboard.kill_progress_level = level_i
    blackboard.kill_progress_exp = exp_f
    if not rose:
        return
    tid = blackboard.current_target_id
    if not EXP_KILL_RELEASE_ENABLED:
        event(
            "clickgap",
            "exp rose while sticky id=%s level=%s->%s exp=%s->%s",
            tid if tid is not None else "-",
            prev_l,
            level_i,
            prev_e,
            exp_f,
        )
        return
    get_logger("combat").info(
        "exp-kill release id=%s level=%s->%s exp=%s->%s",
        tid if tid is not None else "-",
        prev_l,
        level_i,
        prev_e,
        exp_f,
    )
    _release_sticky_for_kill(state, blackboard)


def continue_sticky_combat(state: "GameState", blackboard: "Blackboard") -> bool:
    """True while the kill lock should stay (attack or rematch).

    Drops on blacklist, confirmed species death in the 2-tile window,
    no living same-species rematch (so a new target can be chosen),
    wall/fence with no detour path, or the last-resort engage timeout.
    An exp rise releases the lock earlier, in ``sample_kill_progress``.
    """
    tid = blackboard.current_target_id
    if tid is not None and tid in blackboard.blacklisted_target_ids:
        log_sticky_release(state, blackboard, "blacklist")
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
        return False
    if tid is not None:
        from app._04_decision.combat_query import _dungeon_ignores_blacklisted_attacker

        held = state.get_object(int(tid))
        if held is not None and _dungeon_ignores_blacklisted_attacker(held):
            log_sticky_release(state, blackboard, "species blacklist")
            blackboard.current_target_id = None
            clear_engage_state(blackboard)
            _clear_finish_kill(state, blackboard, int(tid))
            return False
    if not sticky_identity(blackboard):
        return False
    found = rebind_sticky_target(state, blackboard)
    if found is None:
        return False
    tid = blackboard.current_target_id
    obj = state.get_object(tid) if tid is not None else None
    if obj is not None:
        from app._04_decision.species_rules import scarecrow_blocked_by_player_level

        level = getattr(getattr(state, "player", None), "level", None)
        if scarecrow_blocked_by_player_level(obj, level):
            give_up_target(blackboard, int(tid), reason="scarecrow level")
            return False
        # Wall/fence: do not give up here. continue_or_start_combat tries
        # A* / sidestep detour first; blocked-unstick is the last resort.
    return advance_engage_or_give_up(state, blackboard)


def attacked_me_rank(obj: object) -> tuple[int, int, int]:
    """Sort key: known level ascending, unknown level after every known level."""
    from app._03_world.constants import monster_level_for_object

    level = monster_level_for_object(
        getattr(obj, "species_name", None),
        getattr(obj, "detail_classification", None),
    )
    try:
        tid = int(getattr(obj, "track_id", 0) or 0)
    except (TypeError, ValueError):
        tid = 0
    if level is None:
        return (1, 0, tid)
    return (0, int(level), tid)


def attacked_me_outranks(candidate: object, current: object) -> bool:
    """True when ``candidate`` should take a latched sticky from ``current``.

    A lower known level wins. The same level, and two unknown levels, stay
    on the current sticky. A known level wins over an unknown level.
    """
    current_rank = attacked_me_rank(current)
    candidate_rank = attacked_me_rank(candidate)
    if current_rank[0] == candidate_rank[0] and (
        current_rank[0] == 1 or current_rank[1] == candidate_rank[1]
    ):
        return False
    return candidate_rank < current_rank


def prefer_attacked_me_sticky(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    exclude: set[int] | None = None,
) -> bool:
    """Point sticky at the best monster that has attacked me.

    A sticky that has not attacked me yields immediately. A sticky that has
    yields only to a strictly lower known level. Same level keeps the lock.
    Does not give the previous target up.
    """
    from app._04_decision.combat_query import list_attacked_me_targets

    origin = getattr(blackboard, "world_origin", None)
    candidates = list_attacked_me_targets(
        state,
        exclude=exclude,
        origin=origin,
        check_path=True,
    )
    if not candidates:
        return False
    best = min(candidates, key=attacked_me_rank)
    tid = blackboard.current_target_id
    current = state.get_object(int(tid)) if tid is not None else None
    if (
        current is not None
        and int(getattr(current, "track_id", -1)) == int(best.track_id)
    ):
        return False
    if (
        current is not None
        and getattr(current, "attacked_me", False)
        and sticky_target_alive(state, int(current.track_id))
        and not attacked_me_outranks(best, current)
    ):
        return False
    begin_engage(
        state,
        blackboard,
        int(best.track_id),
        finish_kill=True,
    )
    return True


def give_up_target(
    blackboard: "Blackboard",
    target_id: int,
    *,
    reason: str = "",
    name: str = "",
    cursor_label: str = "",
    cursor_category: str = "",
    cursor_score: float | None = None,
    need_score: float | None = None,
) -> None:
    """Abandon ``target_id`` for the give-up cooldown window.

    ``finish_kill`` only affects target priority; it does not block this.
    """
    from app.bot_log import get_logger

    why = str(reason or "give-up").strip() or "give-up"
    mon = str(name or "").strip()
    tid = int(target_id)
    was_finish = tid in blackboard.finish_kill_ids
    blackboard.finish_kill_ids.discard(tid)
    get_logger("combat").info(
        "give-up id=%s name=%s reason=%s sticky_was=%s finish_kill=%s",
        target_id,
        mon or "-",
        why,
        blackboard.current_target_id,
        int(was_finish),
    )
    tick = int(blackboard.tick_count)
    blackboard.given_up_target_ids[tid] = tick
    event: dict = {
        "id": tid,
        "reason": why,
        "tick": tick,
        "name": mon,
        "cursor_label": str(cursor_label or "").strip(),
        "cursor_category": str(cursor_category or "").strip(),
        "cursor_score": cursor_score,
        "need_score": need_score,
        "finish_kill": was_finish,
    }
    blackboard.scratch["last_give_up"] = event
    hist = list(blackboard.scratch.get("give_up_history") or [])
    hist.append(event)
    blackboard.scratch["give_up_history"] = hist[-20:]
    if blackboard.current_target_id == target_id:
        log_sticky_release(None, blackboard, f"give-up {why}")
        blackboard.current_target_id = None
    clear_engage_state(blackboard)


def advance_engage_or_give_up(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """Return False if the sticky target was abandoned.

    A living rebound target is never dropped by the wall-clock. The engage
    timer is only a last-resort for a lock that already lost its identity.
    ``finish_kill`` does not exempt abandon / max-engage.
    """
    del state
    tid = blackboard.current_target_id
    if tid is None:
        return False
    started = float(blackboard.target_engage_started or 0.0)
    if started <= 0:
        blackboard.target_engage_started = time.time()
        return True
    elapsed = time.time() - started
    if ABANDON_SAME_ENABLED and elapsed >= float(ABANDON_SECONDS):
        give_up_target(blackboard, tid, reason="abandon same")
        return False
    # Keep swinging until death / rebind miss. A 10s config used to abort
    # mid-kill and look like a single click.
    if elapsed >= MAX_ENGAGE_SECONDS and not (
        blackboard.current_target_species or blackboard.current_target_world
    ):
        give_up_target(blackboard, tid, reason="max engage")
        return False
    return True


__all__ = [
    "MAX_ENGAGE_SECONDS",
    "ABANDON_SAME_ENABLED",
    "ABANDON_SECONDS",
    "STICKY_MISS_FRAMES",
    "GIVE_UP_COOLDOWN_TICKS",
    "STICKY_REBIND_TILES",
    "sticky_target_alive",
    "sticky_identity",
    "species_death_signal",
    "sample_kill_progress",
    "continue_sticky_combat",
    "rebind_sticky_target",
    "stamp_sticky_target",
    "target_species_key",
    "object_world_cell",
    "clear_engage_state",
    "begin_engage",
    "attacked_me_rank",
    "attacked_me_outranks",
    "prefer_attacked_me_sticky",
    "give_up_target",
    "advance_engage_or_give_up",
    "ATTACK_STILL_TRIES",
    "note_attack_attempt",
    "attack_still_exhausted",
    "reset_attack_still",
]
