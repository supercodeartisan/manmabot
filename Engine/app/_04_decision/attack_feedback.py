"""Attack feedback: post-attack blacklists + cursor-verify probation."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app._03_world import CharacterType
from app._03_world.constants import (
    ATTACK_MP_UNCHANGED_TICKS,
    ATTACK_NO_MOVE_SECONDS,
)
from app._03_world.space.world_coords import content_to_world

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._02_state.objects import WorldObject
    from app._04_decision.blackboard import Blackboard

# Consecutive attack-cursor misses on the same monster before the 4s skip.
CURSOR_VERIFY_FAIL_GIVE_UP = 5
# After one rejected attack cursor, skip that id for this many seconds.
CURSOR_REJECT_EXCLUDE_SECONDS = 4.0
# Consecutive loot-cursor misses on the same *item* before soft abandon
# (short loot cooldown — not the combat 160-tick map).
CURSOR_VERIFY_FAIL_GIVE_UP_ITEM = 4


def target_wcs_tile(obj: "WorldObject") -> tuple[int, int]:
    cx = getattr(obj, "world_cx", None)
    cy = getattr(obj, "world_cy", None)
    if cx is not None and cy is not None:
        return int(cx), int(cy)
    tile = content_to_world(obj.position.x, obj.position.y)
    return (int(tile.x), int(tile.y))


def note_cursor_verify_ok(blackboard: "Blackboard", track_id: int) -> None:
    """Reset the verify-fail streak after a successful gated click."""
    blackboard.cursor_verify_fail_streak.pop(track_id, None)


def note_cursor_verify_fail(
    blackboard: "Blackboard",
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
    """Count a consecutive verify fail.

    Combat: after :data:`CURSOR_VERIFY_FAIL_GIVE_UP` rejected attack cursors
    on the same id, release the sticky lock and exclude that id for
    :data:`CURSOR_REJECT_EXCLUDE_SECONDS`. An accepted cursor clears the
    streak and keeps the lock. Items: after
    :data:`CURSOR_VERIFY_FAIL_GIVE_UP_ITEM` loot-cursor misses → short loot
    cooldown abandon. Returns True when a target or pile was released.
    """
    streak = int(blackboard.cursor_verify_fail_streak.get(track_id, 0)) + 1
    blackboard.cursor_verify_fail_streak[track_id] = streak
    label = str(name or "").strip()
    score_f: float | None
    try:
        score_f = float(cursor_score) if cursor_score is not None else None
    except (TypeError, ValueError):
        score_f = None
    need_f: float | None
    try:
        need_f = float(need_score) if need_score is not None else None
    except (TypeError, ValueError):
        need_f = None
    blackboard.scratch["last_cursor_reject"] = {
        "id": track_id,
        "reason": reason,
        "streak": streak,
        "is_item": is_item,
        "name": label,
        "cursor_label": str(cursor_label or "").strip(),
        "cursor_category": str(cursor_category or "").strip(),
        "cursor_score": score_f,
        "need_score": need_f,
    }
    if is_item and streak >= CURSOR_VERIFY_FAIL_GIVE_UP_ITEM:
        from app._04_decision.behaviors.loot_hop import abandon_loot_item

        abandon_loot_item(blackboard, int(track_id))
        blackboard.cursor_verify_fail_streak.pop(int(track_id), None)
        return True
    if (not is_item) and streak >= CURSOR_VERIFY_FAIL_GIVE_UP:
        release_cursor_reject(
            blackboard,
            int(track_id),
            reason=str(reason or "cursor reject"),
            name=label,
            cursor_label=str(cursor_label or "").strip(),
            cursor_category=str(cursor_category or "").strip(),
            cursor_score=score_f,
            need_score=need_f,
        )
        return True
    return False


def release_cursor_reject(
    blackboard: "Blackboard",
    track_id: int,
    *,
    reason: str = "",
    name: str = "",
    cursor_label: str = "",
    cursor_category: str = "",
    cursor_score: float | None = None,
    need_score: float | None = None,
) -> None:
    """Drop the sticky lock and skip ``track_id`` for 4 seconds.

    The id is not written to the 160-tick give-up map. Dungeon wall release
    does not call this.
    """
    from app.bot_log import get_logger
    from app._04_decision.behaviors.combat import clear_engage_state
    from app._04_decision.clickgap import log_sticky_release

    tid = int(track_id)
    why = str(reason or "cursor reject").strip() or "cursor reject"
    until = time.time() + float(CURSOR_REJECT_EXCLUDE_SECONDS)
    blackboard.cursor_reject_until[tid] = until
    blackboard.cursor_verify_fail_streak.pop(tid, None)
    blackboard.finish_kill_ids.discard(tid)
    get_logger("combat").info(
        "cursor release id=%s name=%s exclude_s=%s reason=%s sticky_was=%s",
        tid,
        str(name or "").strip() or "-",
        int(CURSOR_REJECT_EXCLUDE_SECONDS),
        why,
        blackboard.current_target_id,
    )
    held = blackboard.current_target_id
    if held is not None and int(held) == tid:
        log_sticky_release(None, blackboard, "cursor reject 4s")
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
    blackboard.scratch["last_cursor_release"] = {
        "id": tid,
        "reason": why,
        "until": until,
        "name": str(name or "").strip(),
        "cursor_label": str(cursor_label or "").strip(),
        "cursor_category": str(cursor_category or "").strip(),
        "cursor_score": cursor_score,
        "need_score": need_score,
    }


def _active_cursor_reject_ids(blackboard: "Blackboard") -> set[int]:
    now = time.time()
    until_map = blackboard.cursor_reject_until
    expired = [tid for tid, until in until_map.items() if float(until) <= now]
    for tid in expired:
        until_map.pop(tid, None)
    return set(until_map)


def blacklist_target(blackboard: "Blackboard", track_id: int, *, reason: str) -> None:
    """Permanently exclude a track for this session and clear sticky combat."""
    from app._04_decision.behaviors.combat import clear_engage_state

    blackboard.blacklisted_target_ids.add(track_id)
    if blackboard.current_target_id == track_id:
        blackboard.current_target_id = None
        clear_engage_state(blackboard)
        _clear_attack_probe(blackboard)
    # Scratch for debug logs (optional consumers).
    blackboard.scratch["last_blacklist"] = {"id": track_id, "reason": reason}


def excluded_target_ids(blackboard: "Blackboard", cooldown_ticks: int) -> set[int]:
    """Give-up cooldown, 4s cursor-reject skips, and the session blacklist."""
    active = {
        tid
        for tid, t in blackboard.given_up_target_ids.items()
        if blackboard.tick_count - t < cooldown_ticks
    }
    return (
        active
        | _active_cursor_reject_ids(blackboard)
        | set(blackboard.blacklisted_target_ids)
        | set(blackboard.exp_kill_ids)
    )


def _clear_attack_probe(blackboard: "Blackboard") -> None:
    blackboard.attack_probe_target_id = None
    blackboard.attack_probe_wcs = None
    blackboard.attack_probe_started = 0.0
    blackboard.attack_probe_mp_before = None
    blackboard.attack_probe_awaiting_mp = False
    blackboard.attack_probe_mp_unchanged_ticks = 0


def _clear_mp_probe(blackboard: "Blackboard") -> None:
    blackboard.attack_probe_mp_before = None
    blackboard.attack_probe_awaiting_mp = False
    blackboard.attack_probe_mp_unchanged_ticks = 0


def begin_or_refresh_attack_probe(
    state: "GameState",
    blackboard: "Blackboard",
    target_id: int,
) -> None:
    """Bind the probe to the sticky target. Does not start the no-move clock.

    The 2s no-move window starts only after a real attack is delivered
    (mage bolt or melee click).
    """
    if blackboard.attack_probe_target_id == target_id:
        return
    obj = state.get_object(target_id)
    if obj is None:
        return
    blackboard.attack_probe_target_id = target_id
    blackboard.attack_probe_wcs = None
    blackboard.attack_probe_started = 0.0
    _clear_mp_probe(blackboard)


def note_attack_delivered(
    state: "GameState",
    blackboard: "Blackboard",
    target_id: int,
) -> None:
    """Start the no-move clock the first time an attack actually lands."""
    if blackboard.attack_probe_target_id != target_id:
        blackboard.attack_probe_target_id = target_id
        blackboard.attack_probe_wcs = None
        blackboard.attack_probe_started = 0.0
        _clear_mp_probe(blackboard)
    if blackboard.attack_probe_started > 0:
        return
    obj = state.get_object(target_id)
    blackboard.attack_probe_started = time.time()
    blackboard.attack_probe_wcs = target_wcs_tile(obj) if obj is not None else None


def note_mage_cast_attempt(
    blackboard: "Blackboard",
    *,
    target_id: int,
    mp_before: Optional[int],
    state: Optional["GameState"] = None,
) -> None:
    """Record that ActionExecutor attempted a spell on ``target_id``."""
    if state is not None:
        note_attack_delivered(state, blackboard, target_id)
    elif blackboard.attack_probe_target_id != target_id:
        blackboard.attack_probe_target_id = target_id
        blackboard.attack_probe_wcs = None
        blackboard.attack_probe_started = time.time()
    else:
        if blackboard.attack_probe_started <= 0:
            blackboard.attack_probe_started = time.time()
    if not blackboard.attack_probe_awaiting_mp:
        blackboard.attack_probe_mp_before = mp_before
        blackboard.attack_probe_mp_unchanged_ticks = 0
        blackboard.attack_probe_awaiting_mp = mp_before is not None
    elif mp_before is None:
        blackboard.attack_probe_awaiting_mp = False


def evaluate_attack_probes(state: "GameState", blackboard: "Blackboard") -> None:
    """Apply mage MP + no-move blacklists using the current world snapshot."""
    tid = blackboard.attack_probe_target_id
    if tid is None:
        return

    player = state.player
    # Mage: after a cast, MP must drop within ATTACK_MP_UNCHANGED_TICKS
    # attack ticks; else treat as a fake target.
    if (
        blackboard.attack_probe_awaiting_mp
        and player is not None
        and player.character_type is CharacterType.MAGE
        and blackboard.attack_probe_mp_before is not None
    ):
        mp_now = player.mp
        if mp_now is not None and mp_now >= blackboard.attack_probe_mp_before:
            if blackboard.current_target_id == tid:
                blackboard.attack_probe_mp_unchanged_ticks += 1
                if (
                    blackboard.attack_probe_mp_unchanged_ticks
                    >= ATTACK_MP_UNCHANGED_TICKS
                ):
                    blacklist_target(blackboard, tid, reason="mage cast mp unchanged")
                    return
        else:
            # MP dropped (or unknown) — clear the cast check; keep no-move probe.
            _clear_mp_probe(blackboard)

    # Any class: after a delivered attack, the target must leave its WCS
    # tile within ATTACK_NO_MOVE_SECONDS.
    if blackboard.attack_probe_started <= 0:
        return
    if time.time() - blackboard.attack_probe_started < ATTACK_NO_MOVE_SECONDS:
        return
    obj = state.get_object(tid)
    if obj is None:
        _clear_attack_probe(blackboard)
        return
    start = blackboard.attack_probe_wcs
    if start is None:
        blackboard.attack_probe_wcs = target_wcs_tile(obj)
        return
    if target_wcs_tile(obj) == start:
        blacklist_target(blackboard, tid, reason="target wcs unchanged")
        return
    # Moved — reset the no-move window from the new tile.
    blackboard.attack_probe_wcs = target_wcs_tile(obj)
    blackboard.attack_probe_started = time.time()


__all__ = [
    "CURSOR_VERIFY_FAIL_GIVE_UP",
    "CURSOR_VERIFY_FAIL_GIVE_UP_ITEM",
    "target_wcs_tile",
    "note_cursor_verify_ok",
    "note_cursor_verify_fail",
    "release_cursor_reject",
    "blacklist_target",
    "excluded_target_ids",
    "begin_or_refresh_attack_probe",
    "note_attack_delivered",
    "note_mage_cast_attempt",
    "evaluate_attack_probes",
]
