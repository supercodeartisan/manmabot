"""Combat behavior (Priority 3): engage the best monster."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world import ActionType, ObjectStatus, ObjectType
from app._04_decision.attack_feedback import excluded_target_ids
from app._04_decision.behavior_tree import (
    ActionNode,
    ConditionNode,
    Node,
    Selector,
    Sequence,
    Status,
)
from app._04_decision.target_selector import is_target_valid, select_target

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

# Last-resort stuck timer. A living target is not dropped before this.
MAX_ENGAGE_SECONDS = 90.0
# Hunt/Attack "same monster N seconds then give up". Off = legacy sticky.
ABANDON_SAME_ENABLED = False
ABANDON_SECONDS = 20.0
# Only used when print_state is missing. A listed death / omit drops instantly.
STICKY_MISS_FRAMES = 1
# After giving up on a target, do not re-select it for this many ticks.
GIVE_UP_COOLDOWN_TICKS = 160
# When TrackIds remaps a heap pointer, keep the same mob within this radius.
STICKY_REBIND_TILES = 2
# Same world tile after this many attack clicks. Living sticky is not dropped.
ATTACK_STILL_TRIES = 5
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
    reset_attack_still(blackboard)


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


def begin_engage(state: "GameState", blackboard: "Blackboard", target_id: int) -> None:
    """Bind sticky combat to ``target_id`` and start the engage clock."""
    from app.bot_log import get_logger

    blackboard.current_target_id = target_id
    clear_engage_state(blackboard)
    blackboard.target_engage_started = time.time()
    obj = state.get_object(target_id)
    stamp_sticky_target(blackboard, obj)
    species = getattr(obj, "species_name", None) if obj is not None else None
    rx = getattr(obj, "world_rx", None) if obj is not None else None
    ry = getattr(obj, "world_ry", None) if obj is not None else None
    get_logger("combat").info(
        "engage id=%s species=%s rel=(%s,%s)",
        target_id,
        species or "?",
        rx if rx is not None else "?",
        ry if ry is not None else "?",
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
    range do not break a kill already in progress.
    """
    from app._04_decision.combat_query import fresh_memory_sweep, memory_target_gone

    obj = state.get_object(target_id)
    if obj is None or obj.object_type is not ObjectType.MONSTER:
        return False
    if obj.status is ObjectStatus.DEAD:
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
    from app._03_world.world_coords import distance_tiles_from_memory

    known = distance_tiles_from_memory(obj)
    if known is not None:
        return known
    from app._04_decision.combat_query import tile_distance_from_player

    try:
        return int(tile_distance_from_player(obj))  # type: ignore[arg-type]
    except Exception:
        return 10_000


def rebind_sticky_target(state: "GameState", blackboard: "Blackboard") -> object | None:
    """Keep the current kill: 2-tile rematch, else nearest same species.

    Death is confirmed only when the 2-tile window is empty and a dead
    monster of that species is seen there. A vanish with neither that
    signal nor a living same-species mob clears the lock so a new target
    can be chosen.
    """
    tid = blackboard.current_target_id
    if tid is not None and sticky_target_alive(state, tid):
        obj = state.get_object(tid)
        stamp_sticky_target(blackboard, obj)
        return obj
    found = _find_rebind_candidate(state, blackboard, window_only=True)
    if found is not None:
        blackboard.current_target_id = int(found.track_id)
        stamp_sticky_target(blackboard, found)
        if not blackboard.target_engage_started:
            blackboard.target_engage_started = time.time()
        return found
    if species_death_signal(state, blackboard):
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
        return None
    near = _find_rebind_candidate(state, blackboard, window_only=False)
    if near is not None:
        blackboard.current_target_id = int(near.track_id)
        stamp_sticky_target(blackboard, near)
        if not blackboard.target_engage_started:
            blackboard.target_engage_started = time.time()
        return near
    if sticky_identity(blackboard):
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
    return None


def continue_sticky_combat(state: "GameState", blackboard: "Blackboard") -> bool:
    """True while the kill lock should stay (attack or rematch).

    Drops on blacklist, confirmed species death in the 2-tile window,
    no living same-species rematch (so a new target can be chosen),
    wall/fence with no detour path, or the last-resort engage timeout.
    """
    tid = blackboard.current_target_id
    if tid is not None and tid in blackboard.blacklisted_target_ids:
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
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
            give_up_target(blackboard, int(tid))
            return False
        # Wall/fence: do not give up here. continue_or_start_combat tries
        # A* / sidestep detour first; blocked-unstick is the last resort.
    return advance_engage_or_give_up(state, blackboard)


def give_up_target(blackboard: "Blackboard", target_id: int) -> None:
    """Abandon ``target_id`` for the give-up cooldown window."""
    from app.bot_log import get_logger

    get_logger("combat").info(
        "give-up id=%s sticky_was=%s",
        target_id,
        blackboard.current_target_id,
    )
    blackboard.given_up_target_ids[target_id] = blackboard.tick_count
    if blackboard.current_target_id == target_id:
        blackboard.current_target_id = None
    clear_engage_state(blackboard)


def advance_engage_or_give_up(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """Return False if the sticky target was abandoned.

    A living rebound target is never dropped by the wall-clock. The engage
    timer is only a last-resort for a lock that already lost its identity.
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
        give_up_target(blackboard, tid)
        return False
    # Keep swinging until death / rebind miss. A 10s config used to abort
    # mid-kill and look like a single click.
    if elapsed >= MAX_ENGAGE_SECONDS and not (
        blackboard.current_target_species or blackboard.current_target_world
    ):
        give_up_target(blackboard, tid)
        return False
    return True


def _target_valid(state: "GameState", blackboard: "Blackboard") -> bool:
    return continue_sticky_combat(state, blackboard)


def _pick_target(state: "GameState", blackboard: "Blackboard") -> bool:
    active = excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS)
    target = select_target(state, exclude=active)
    if target is not None:
        begin_engage(state, blackboard, target.track_id)
        return True
    blackboard.current_target_id = None
    clear_engage_state(blackboard)
    return False


def _attack(
    state: "GameState",
    blackboard: "Blackboard",
    mid_act: bool,
) -> Status:
    del state
    blackboard.current_goal = "combat"
    blackboard.emit(
        ActionType.ATTACK,
        target_id=blackboard.current_target_id,
        priority=0.5,
        reason="engage target" if not mid_act else "attack target",
        mid_act=mid_act,
    )
    return Status.SUCCESS


def build_combat_node() -> Node:
    """Combat: keep attacking the remembered target, else pick a new one."""
    return Selector(
        children=[
            Sequence(
                children=[
                    ConditionNode(_target_valid, "target_valid"),
                    ActionNode(lambda s, b: _attack(s, b, True), "attack_current"),
                ],
                name="continue_combat",
            ),
            Sequence(
                children=[
                    ConditionNode(_pick_target, "target_found"),
                    ActionNode(lambda s, b: _attack(s, b, False), "attack_new"),
                ],
                name="engage_new",
            ),
        ],
        name="combat",
    )


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
    "continue_sticky_combat",
    "rebind_sticky_target",
    "stamp_sticky_target",
    "target_species_key",
    "object_world_cell",
    "build_combat_node",
    "clear_engage_state",
    "begin_engage",
    "give_up_target",
    "advance_engage_or_give_up",
    "ATTACK_STILL_TRIES",
    "note_attack_attempt",
    "attack_still_exhausted",
    "reset_attack_still",
]
