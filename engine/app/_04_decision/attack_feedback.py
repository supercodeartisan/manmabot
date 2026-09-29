"""Attack feedback: post-attack blacklists + cursor-verify probation."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app._03_world import CharacterType
from app._03_world.constants import (
    ATTACK_MP_UNCHANGED_TICKS,
    ATTACK_NO_MOVE_SECONDS,
)
from app._03_world.world_coords import content_to_world

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._03_world.objects import WorldObject
    from app._04_decision.blackboard import Blackboard

# Consecutive aim+verify fails on the same *item* before soft give-up.
# Combat misses must not abort a living kill (adjacent sprites often need
# several pixel probes before the attack cursor appears).
CURSOR_VERIFY_FAIL_GIVE_UP = 4


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
) -> bool:
    """Count a consecutive verify fail. Never treats a miss as picked-up/dead.

    Combat stays on a living monster. A ground pile is abandoned after
    :data:`CURSOR_VERIFY_FAIL_GIVE_UP` loot-cursor misses (other player's
    drop / unlootable). Returns True only when that pile was given up.
    """
    streak = int(blackboard.cursor_verify_fail_streak.get(track_id, 0)) + 1
    blackboard.cursor_verify_fail_streak[track_id] = streak
    blackboard.scratch["last_cursor_reject"] = {
        "id": track_id,
        "reason": reason,
        "streak": streak,
        "is_item": is_item,
    }
    if is_item and streak >= CURSOR_VERIFY_FAIL_GIVE_UP:
        from app._04_decision.behaviors.loot_hop import abandon_loot_item

        abandon_loot_item(blackboard, int(track_id))
        blackboard.cursor_verify_fail_streak.pop(int(track_id), None)
        return True
    return False


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
    """Give-up cooldown union session blacklist."""
    active = {
        tid
        for tid, t in blackboard.given_up_target_ids.items()
        if blackboard.tick_count - t < cooldown_ticks
    }
    return active | set(blackboard.blacklisted_target_ids)


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
    "target_wcs_tile",
    "note_cursor_verify_ok",
    "note_cursor_verify_fail",
    "blacklist_target",
    "excluded_target_ids",
    "begin_or_refresh_attack_probe",
    "note_attack_delivered",
    "note_mage_cast_attempt",
    "evaluate_attack_probes",
]
