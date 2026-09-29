"""Box-1 support spells: timed buffs, post-teleport heal, mana reserve.

After a danger teleport, heal repeats until HP ≥ 50% or MP drops below 20%.
Teleport is never gated by the reserve so it can always save the character.
HP potion is an item, not a spell, and is handled separately.

Reuse time (per slot, default 20 min on buffs) is how often that skill must be
cast again. Magic cooldown (0.5 s) is the shared gap after any magic before the
next magic can be cast.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app._03_world import ActionType
from app._04_decision.behavior_tree import Status
from app._04_decision.mode_control import hp_ratio, mp_ratio
from app._05_action.spell_box import (
    MAGIC_COOLDOWN_S,
    slot_is_enabled,
    slot_is_magic,
    slot_reuse_s,
)

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

BUFF_POWER = "power_up"
BUFF_ARMOR = "armor_up"
BUFF_LIGHT = "light"
# Startup order: shell first, then light, then power-up (after start delays).
BUFF_ORDER = (BUFF_ARMOR, BUFF_LIGHT, BUFF_POWER)

# Recast holy weapon / shell this often after the first cast.
BUFF_COOLDOWN_S = 20.0 * 60.0
# Light stays up about 12 minutes; recast once per duration, not every loop.
LIGHT_REUSE_S = 12.0 * 60.0
# First-cast delays from bot start (shell immediately, light 10s, power-up 10 min).
BUFF_START_DELAY_S = {
    BUFF_ARMOR: 0.0,
    BUFF_LIGHT: 10.0,
    BUFF_POWER: 10.0 * 60.0,
}
# Survive pause/resume and blackboard.reset within the same process.
_persisted_buff_last_cast: dict[str, float] = {}
_persisted_buff_session_at: float = 0.0
# Do not spend mana on buffs / heal / attack spells below this ratio.
SPELL_MANA_RESERVE_RATIO = 0.20
# After a danger teleport, keep healing until HP reaches this ratio.
HEAL_UNTIL_HP_RATIO = 0.50
# Min seconds between unstick teleports (travel / search).
UNSTICK_TELEPORT_COOLDOWN_S = 20.0


def magic_ready(blackboard: "Blackboard") -> bool:
    """True when the shared 0.5 s magic cooldown has elapsed."""
    last = float(blackboard.magic_last_cast or 0.0)
    if last <= 0:
        return True
    return (time.time() - last) >= MAGIC_COOLDOWN_S


def slot_ready(
    blackboard: "Blackboard",
    name: str,
    *,
    urgent: bool = False,
) -> bool:
    if not slot_is_enabled(name):
        return False
    reuse = _buff_reuse_s(name) if name in BUFF_ORDER else slot_reuse_s(name)
    if reuse > 0:
        last = float(blackboard.spell_last_cast.get(name, 0.0) or 0.0)
        if name in blackboard.buff_last_cast:
            last = max(last, float(blackboard.buff_last_cast.get(name, 0.0) or 0.0))
        if last and (time.time() - last) < reuse:
            return False
    # Survival intents (heal / teleport / scroll) emit this tick; the
    # action layer still waits any leftover shared magic cooldown.
    if slot_is_magic(name) and not urgent and not magic_ready(blackboard):
        return False
    return True


def mark_slot_used(blackboard: "Blackboard", name: str) -> None:
    now = time.time()
    blackboard.spell_last_cast[name] = now
    if name in BUFF_ORDER:
        blackboard.buff_last_cast[name] = now
    if slot_is_magic(name):
        blackboard.magic_last_cast = now


def can_cast_spell(state: "GameState") -> bool:
    """True when a non-teleport spell may spend mana (reserve kept for TP).

    Unknown MP does not cast. At or below the reserve (default 20%) the bot
    keeps that mana for teleport.
    """
    ratio = mp_ratio(state)
    if ratio is None:
        return False
    return ratio > SPELL_MANA_RESERVE_RATIO


def request_heal_after_teleport(blackboard: "Blackboard") -> None:
    """After a danger teleport, heal until HP recovers or mana is reserved."""
    blackboard.heal_after_teleport = True


def maybe_heal_after_teleport(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional[Status]:
    from app._04_decision import player_mode as pm

    if not blackboard.heal_after_teleport:
        return None
    if not pm.HP_RECOVER_ENABLED or not pm.USE_HEAL:
        blackboard.heal_after_teleport = False
        return None
    hp = hp_ratio(state)
    if hp is not None and hp >= HEAL_UNTIL_HP_RATIO:
        blackboard.heal_after_teleport = False
        return None
    if not slot_is_enabled("heal"):
        blackboard.heal_after_teleport = False
        return None
    mp = mp_ratio(state)
    if mp is not None and mp <= SPELL_MANA_RESERVE_RATIO:
        blackboard.heal_after_teleport = False
        return None
    if not slot_ready(blackboard, "heal"):
        return None
    mark_slot_used(blackboard, "heal")
    blackboard.current_goal = "heal"
    blackboard.emit(
        ActionType.HEAL,
        priority=0.92,
        reason="heal after teleport",
    )
    return Status.SUCCESS


def maybe_hp_to_mp_at_tree(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional[Status]:
    """At Mother Tree: convert full HP into MP until MP is recovered."""
    from app._04_decision.mode_control import is_full_hp, is_mp_recovered

    if not slot_is_enabled("hp_to_mp"):
        return None
    if not is_full_hp(state):
        return None
    ratio = mp_ratio(state)
    if ratio is None or is_mp_recovered(state):
        return None
    if not slot_ready(blackboard, "hp_to_mp"):
        blackboard.current_goal = "mother_tree"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.95,
            reason="waiting for magic cooldown",
        )
        return Status.SUCCESS
    mark_slot_used(blackboard, "hp_to_mp")
    blackboard.current_goal = "mother_tree"
    blackboard.emit(
        ActionType.HP_TO_MP,
        priority=0.95,
        reason="hp to mp at mother tree",
    )
    return Status.SUCCESS


def _buff_reuse_s(name: str) -> float:
    if name == BUFF_LIGHT:
        return LIGHT_REUSE_S
    reuse = slot_reuse_s(name)
    return reuse if reuse > 0 else BUFF_COOLDOWN_S


def _live_hotbar_snap(
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> Optional[dict]:
    snap = getattr(state, "last_hotbar", None) if state is not None else None
    if not isinstance(snap, dict) and blackboard is not None:
        snap = blackboard.scratch.get("live_hotbar")
    return snap if isinstance(snap, dict) else None


def assigned_buff_on_live_hotbar(
    name: str,
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when that buff is on the live bar, or the bar has not been read yet."""
    snap = _live_hotbar_snap(state, blackboard)
    slots = snap.get("slots") if snap is not None else None
    if not isinstance(slots, list) or not slots:
        return True
    from manmabot_v1.hotbar.inspect import hotbar_has_role

    return hotbar_has_role(snap, name)


def _buff_session_start(blackboard: "Blackboard", now: float) -> float:
    started = float(blackboard.buff_session_at or 0.0)
    if started <= 0.0:
        blackboard.buff_session_at = now
        return now
    return started


def due_buff(
    blackboard: "Blackboard",
    state: Optional["GameState"] = None,
) -> Optional[str]:
    now = time.time()
    started = _buff_session_start(blackboard, now)
    last = blackboard.buff_last_cast
    for name in BUFF_ORDER:
        if not slot_is_enabled(name):
            continue
        if not assigned_buff_on_live_hotbar(name, state, blackboard):
            continue
        prev = float(last.get(name, 0.0) or 0.0)
        if prev <= 0.0:
            delay = float(BUFF_START_DELAY_S.get(name, 0.0) or 0.0)
            if now - started < delay:
                continue
            return name
        if now - prev >= _buff_reuse_s(name):
            return name
    return None


def persist_buff_timers(blackboard: "Blackboard") -> None:
    """Keep buff wall-clock across pause/resume and DecisionManager recreate."""
    global _persisted_buff_last_cast, _persisted_buff_session_at
    _persisted_buff_last_cast = {
        str(k): float(v)
        for k, v in dict(blackboard.buff_last_cast or {}).items()
        if float(v or 0.0) > 0.0
    }
    _persisted_buff_session_at = float(blackboard.buff_session_at or 0.0)


def restore_buff_timers(blackboard: "Blackboard") -> None:
    """Apply persisted buff timers onto ``blackboard`` (no-op if empty)."""
    if _persisted_buff_last_cast:
        blackboard.buff_last_cast.update(_persisted_buff_last_cast)
    if _persisted_buff_session_at > 0.0 and float(blackboard.buff_session_at or 0.0) <= 0.0:
        blackboard.buff_session_at = _persisted_buff_session_at


def mark_buff_cast(blackboard: "Blackboard", name: str) -> None:
    blackboard.buff_last_cast[name] = time.time()
    persist_buff_timers(blackboard)


def note_buffs_active(blackboard: "Blackboard") -> None:
    """Record all three buffs as just applied (tests / skip startup recast)."""
    now = time.time()
    blackboard.buff_session_at = now
    for name in BUFF_ORDER:
        blackboard.buff_last_cast[name] = now
    persist_buff_timers(blackboard)

def maybe_cast_buff(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional[Status]:
    if not can_cast_spell(state):
        return None
    if not magic_ready(blackboard):
        return None
    name = due_buff(blackboard, state)
    if name is None:
        return None
    mark_buff_cast(blackboard, name)
    mark_slot_used(blackboard, name)
    blackboard.current_goal = "buff"
    blackboard.emit(ActionType.BUFF, priority=0.4, reason=name)
    return Status.SUCCESS


def teleport_on_live_hotbar(
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when the escape-teleport *skill* is on the live 24-slot bar."""
    snap = _live_hotbar_snap(state, blackboard)
    if snap is None:
        return False
    from manmabot_v1.hotbar.inspect import hotbar_has_role

    return hotbar_has_role(snap, "teleport")


def try_unstick_teleport(
    blackboard: "Blackboard",
    *,
    ignore_cooldown: bool = False,
    reason: str = "",
    state: Optional["GameState"] = None,
) -> bool:
    """Emit TELEPORT to break a stuck travel/search. No post-TP heal.

    Setup can leave the teleport slot on even when the character has no
    skill. Require the live hotbar name before treating teleport as ready.
    Same mana reserve as HP-path teleport: known MP at/below reserve (or
    under 5) refuses the intent so the caller can fall back to talking scroll.
    """
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app.bot_log import get_logger

    if shopping_blocks_teleport(blackboard):
        get_logger("nav").info("unstick TP blocked by shop trip")
        return False
    now = time.time()
    last = float(blackboard.unstick_teleport_at or 0.0)
    if (
        not ignore_cooldown
        and last
        and (now - last) < UNSTICK_TELEPORT_COOLDOWN_S
    ):
        return False
    if not slot_is_enabled("teleport"):
        get_logger("nav").info("unstick TP skipped: slot off")
        return False
    if not teleport_on_live_hotbar(state, blackboard):
        get_logger("nav").info("unstick TP skipped: not on live hotbar")
        return False
    if _mana_blocks_teleport(state):
        get_logger("nav").info("unstick TP skipped: mana reserve")
        return False
    blackboard.unstick_teleport_at = now
    mark_slot_used(blackboard, "teleport")
    blackboard.current_goal = "unstick"
    get_logger("nav").info("unstick TP emit reason=%s", reason or "unstick teleport")
    blackboard.emit(
        ActionType.TELEPORT,
        priority=0.85,
        reason=str(reason or "unstick teleport"),
    )
    return True


def _mana_blocks_teleport(state: Optional["GameState"]) -> bool:
    """True when known MP is too low to cast teleport (matches HP-path gate)."""
    if state is None:
        return False
    player = getattr(state, "player", None)
    if player is not None:
        try:
            mp = getattr(player, "mp", None)
            if mp is not None and int(mp) < 5:
                return True
        except (TypeError, ValueError):
            pass
    ratio = mp_ratio(state)
    if ratio is None:
        return False
    return ratio <= SPELL_MANA_RESERVE_RATIO


__all__ = [
    "BUFF_POWER",
    "BUFF_ARMOR",
    "BUFF_LIGHT",
    "BUFF_ORDER",
    "BUFF_COOLDOWN_S",
    "LIGHT_REUSE_S",
    "BUFF_START_DELAY_S",
    "SPELL_MANA_RESERVE_RATIO",
    "HEAL_UNTIL_HP_RATIO",
    "UNSTICK_TELEPORT_COOLDOWN_S",
    "magic_ready",
    "slot_ready",
    "mark_slot_used",
    "can_cast_spell",
    "request_heal_after_teleport",
    "maybe_heal_after_teleport",
    "maybe_hp_to_mp_at_tree",
    "assigned_buff_on_live_hotbar",
    "due_buff",
    "mark_buff_cast",
    "note_buffs_active",
    "persist_buff_timers",
    "restore_buff_timers",
    "maybe_cast_buff",
    "try_unstick_teleport",
    "teleport_on_live_hotbar",
]
