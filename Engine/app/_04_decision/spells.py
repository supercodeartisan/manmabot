"""Box-1 support spells: memory buffs, post-teleport heal, mana reserve.

After a danger teleport, heal repeats until HP ≥ 50% or MP drops below 20%.
Teleport is never gated by the reserve so it can always save the character.
HP potion is an item, not a spell, and is handled separately.

Buffs (armor_up / haste / power_up): when ``GameState.last_buff`` is live,
recast when the matching effect is missing or ``remain`` ≤
``BUFF_REMAIN_RECAST_S``. Otherwise fall back to wall-clock reuse (default
20 min; haste ~5 min). Magic cooldown (0.5 s) gates magic buffs only;
``haste`` is an item press.
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
    from app._02_state.player import StatusEffect
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

BUFF_POWER = "power_up"
BUFF_ARMOR = "armor_up"
BUFF_HASTE = "haste"
BUFF_LIGHT = "light"
# Startup order: shell, haste potion, then power-up. Light is not cast.
BUFF_ORDER = (BUFF_ARMOR, BUFF_HASTE, BUFF_POWER)
# Hunt assist toggle (default off). Only when True may haste potion cast.
USE_HASTE_POTION = False
# Optional bag item key imported from inventory (matches hotbar by name).
HASTE_POTION_ITEM = ""
# Hunt assist: name of the hotbar cell assigned as the antidote.
ANTIDOTE_POTION_ITEM = ""

# Recast holy weapon / shell this often after the first cast (timer fallback).
BUFF_COOLDOWN_S = 20.0 * 60.0
# Light stays up about 12 minutes; recast once per duration, not every loop.
LIGHT_REUSE_S = 12.0 * 60.0
# First-cast delays from bot start (shell/haste immediately, light 10s, power 10 min).
BUFF_START_DELAY_S = {
    BUFF_ARMOR: 0.0,
    BUFF_HASTE: 0.0,
    BUFF_LIGHT: 10.0,
    BUFF_POWER: 10.0 * 60.0,
}
# Memory path: cast when remain is at/below this (cast motion / tick lag).
BUFF_REMAIN_RECAST_S = 10.0
# After a cast, wait for fingerprint rescan before treating "missing" as due again.
BUFF_CAST_GUARD_S = 3.0
# Role → live buff identity (skill id / strId / name needles). LC 9.30.
# armor_up: 실드 / 어스 스킨 / 아이언 스킨.
# haste: 초록/강화 초록 / 엘븐 와퍼 / 용기 / 헤이스트 계열.
# power_up: 홀리 웨폰 / 인챈트 웨폰.
_BUFF_MATCH: dict[str, dict[str, object]] = {
    BUFF_ARMOR: {
        "skills": frozenset({2, 150, 167}),
        "str_ids": frozenset({853}),
        "needles": ("실드", "어스 스킨", "아이언 스킨", "shield", "earth skin", "iron skin"),
    },
    BUFF_HASTE: {
        "skills": frozenset({42, 53}),
        "str_ids": frozenset(),
        "needles": (
            "가속 효과",
            "헤이스트",
            "가속",
            "속도향상",
            "haste",
            "自我加速",
            "용기의",
            "brave",
            "엘븐 와퍼",
            "elven wafer",
            "精靈餅乾",
        ),
    },
    BUFF_POWER: {
        "skills": frozenset({7, 11}),
        "str_ids": frozenset({685}),
        "needles": ("홀리 웨폰", "인챈트 웨폰", "holy weapon", "enchant weapon"),
    },
}
# Survive pause/resume and blackboard.reset within the same process.
_persisted_buff_last_cast: dict[str, float] = {}
_persisted_buff_session_at: float = 0.0
# Do not spend mana on buffs / heal / attack spells below this ratio.
SPELL_MANA_RESERVE_RATIO = 0.20
# When mother tree is on, non-exempt magic must leave at least this much MP.
MOTHER_TREE_MANA_FLOOR = 15
# These roles may spend below the mother-tree floor (tree cast / MP recover).
_MOTHER_TREE_MANA_EXEMPT = frozenset({"mother_tree", "hp_to_mp"})
# After a danger teleport, keep healing until HP reaches this ratio.
HEAL_UNTIL_HP_RATIO = 0.50
# Min seconds between unstick teleports (travel / search).
UNSTICK_TELEPORT_COOLDOWN_S = 20.0
# 세계수의 가호 (LC 9.30 strId 993). Perpetual while standing in the aura.
# Body to Mind is allowed only while this effect is on the character.
WORLD_TREE_BLESSING_STR_ID = 993
WORLD_TREE_BLESSING_NEEDLES = ("세계수의 가호", "沐浴在森林之母")


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
    # Buff cadence is due_buff (memory remain / timer). Only a short post-cast
    # guard lives here so mark_slot_used cannot re-impose the 20 min reuse.
    if name in BUFF_ORDER:
        reuse = BUFF_CAST_GUARD_S
    else:
        reuse = slot_reuse_s(name)
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


def can_cast_spell(
    state: "GameState",
    *,
    role: Optional[str] = None,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when a non-teleport spell may spend mana (reserve kept for TP).

    Unknown MP does not cast. At or below the reserve (default 20%) the bot
    keeps that mana for teleport. When mother tree is on and ``role`` is set,
    also refuse casts that would leave MP below ``MOTHER_TREE_MANA_FLOOR``.
    """
    ratio = mp_ratio(state)
    if ratio is None:
        return False
    if ratio <= SPELL_MANA_RESERVE_RATIO:
        return False
    if role and mother_tree_mana_blocks(state, role, blackboard):
        return False
    return True


def _live_hotbar_snap(
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> Optional[dict]:
    snap = getattr(state, "last_hotbar", None) if state is not None else None
    if not isinstance(snap, dict) and blackboard is not None:
        snap = blackboard.scratch.get("live_hotbar")
    if isinstance(snap, dict) and isinstance(snap.get("slots"), list):
        return snap
    return None


def spell_mp_cost_for_role(
    role: str,
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> Optional[int]:
    """Catalog MP for a hotbar role (live name first, then role fallback)."""
    from settings.spell_mana_cost import mp_cost_by_spell_name, mp_cost_for_role_fallback

    wanted = str(role or "").strip()
    if not wanted:
        return None
    snap = _live_hotbar_snap(state, blackboard)
    if snap is not None:
        from hotbar.inspect import hotbar_spell_name_for_role

        name = hotbar_spell_name_for_role(snap, wanted)
        if name:
            cost = mp_cost_by_spell_name(name)
            if cost is not None:
                return cost
    return mp_cost_for_role_fallback(wanted)


def mother_tree_mana_blocks(
    state: Optional["GameState"],
    role: str,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when casting ``role`` would leave MP below the mother-tree floor.

    Active only while ``elf_uses_mother_tree``. ``mother_tree`` / ``hp_to_mp``
    are never blocked. Unknown MP does not block. Unknown cost blocks only
    when current MP is already below the floor.
    """
    wanted = str(role or "").strip()
    if not wanted or wanted in _MOTHER_TREE_MANA_EXEMPT:
        return False
    if state is None:
        return False
    from app._04_decision.mode_control import elf_uses_mother_tree

    if not elf_uses_mother_tree(state, blackboard):
        return False
    player = getattr(state, "player", None)
    mp_raw = getattr(player, "mp", None) if player is not None else None
    if mp_raw is None:
        return False
    try:
        mp = int(mp_raw)
    except (TypeError, ValueError):
        return False
    cost = spell_mp_cost_for_role(wanted, state, blackboard)
    if cost is None:
        return mp < MOTHER_TREE_MANA_FLOOR
    return (mp - int(cost)) < MOTHER_TREE_MANA_FLOOR


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
    from app._04_decision.behaviors.mode_actions import heal_blocked_by_mana

    if heal_blocked_by_mana(state, blackboard):
        blackboard.heal_after_teleport = False
        return None
    from app._04_decision.behaviors.mode_actions import (
        character_is_attacking,
        heal_press_slot,
    )

    if character_is_attacking(state, blackboard):
        return None
    if not slot_ready(blackboard, "heal"):
        return None
    slot = heal_press_slot(state)
    if slot is None:
        return None
    mark_slot_used(blackboard, "heal")
    blackboard.current_goal = "heal"
    box, key = slot
    blackboard.emit(
        ActionType.HEAL,
        priority=0.92,
        reason="heal after teleport",
        hotbar_box=box,
        hotbar_key=key,
    )
    return Status.SUCCESS


def world_tree_blessing_active(state: Optional["GameState"]) -> bool:
    """True when 세계수의 가호 is on the live buff list.

    That effect is the Mother Tree aura. A missing or untrusted buff snapshot
    is not treated as present.
    """
    if not _memory_buffs_ready(state):
        return False
    effects = list(getattr(getattr(state, "player", None), "buffs", None) or [])
    for effect in effects:
        try:
            str_id = int(getattr(effect, "str_id", 0) or 0)
        except (TypeError, ValueError):
            str_id = 0
        if str_id == WORLD_TREE_BLESSING_STR_ID:
            return True
        name = str(getattr(effect, "name", "") or "")
        if name and any(needle in name for needle in WORLD_TREE_BLESSING_NEEDLES):
            return True
    return False


def maybe_hp_to_mp(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    reason: str = "hp to mp",
) -> Optional[Status]:
    """Convert HP to MP when the World Tree blessing is up.

    HP must be at least ``HP_TO_MP_MIN_RATIO`` and MP at or under
    ``HP_TO_MP_MAX_MP_RATIO``. Both come from the mother-tree recovery
    settings (defaults 85% and 80%). Off when ``HP_TO_MP_ENABLED`` is false.

    Like heal / mother tree: when a live hotbar snapshot exists, require
    ``바디 투 마인드`` (role ``hp_to_mp``) on the bar before emitting.
    Field recovery and the Mother Tree stand both call this, so the skill
    stays off unless 세계수의 가호 is actually on the character.
    """
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import hp_ratio, mp_ratio

    if not bool(pm.HP_TO_MP_ENABLED):
        return None
    if not slot_is_enabled("hp_to_mp"):
        return None
    snap = _live_hotbar_snap(state, blackboard)
    slots = snap.get("slots") if isinstance(snap, dict) else None
    if isinstance(slots, list) and slots and not hp_to_mp_on_live_hotbar(
        state, blackboard
    ):
        return None
    if not world_tree_blessing_active(state):
        return None
    ratio = hp_ratio(state)
    if ratio is None or ratio < float(pm.HP_TO_MP_MIN_RATIO):
        return None
    mpr = mp_ratio(state)
    if mpr is None or mpr > float(pm.HP_TO_MP_MAX_MP_RATIO):
        return None
    if not slot_ready(blackboard, "hp_to_mp"):
        blackboard.current_goal = "hp_to_mp"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.95,
            reason="waiting for magic cooldown",
        )
        return Status.SUCCESS
    mark_slot_used(blackboard, "hp_to_mp")
    blackboard.current_goal = "hp_to_mp"
    blackboard.emit(
        ActionType.HP_TO_MP,
        priority=0.95,
        reason=reason,
    )
    return Status.SUCCESS


def maybe_hp_to_mp_at_tree(
    state: "GameState",
    blackboard: "Blackboard",
) -> Optional[Status]:
    """At Mother Tree: Body to Mind when the blessing is up, HP ≥ 85%, MP < 80%."""
    result = maybe_hp_to_mp(state, blackboard, reason="hp to mp at mother tree")
    if result is Status.SUCCESS:
        blackboard.current_goal = "mother_tree"
    return result


def hp_to_mp_on_live_hotbar(
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when Body to Mind (``hp_to_mp``) is on the live 24-slot bar."""
    snap = _live_hotbar_snap(state, blackboard)
    if snap is None:
        return False
    from hotbar.inspect import hotbar_has_role

    return hotbar_has_role(snap, "hp_to_mp")


def _buff_reuse_s(name: str) -> float:
    if name == BUFF_LIGHT:
        return LIGHT_REUSE_S
    reuse = slot_reuse_s(name)
    return reuse if reuse > 0 else BUFF_COOLDOWN_S


def assigned_buff_on_live_hotbar(
    name: str,
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when that buff is on the live bar, or the bar has not been read yet."""
    snap = _live_hotbar_snap(state, blackboard)
    slots = snap.get("slots") if snap is not None else None
    if name == BUFF_HASTE:
        from app._05_action.spell_box import slot_is_enabled, slot_press
        from settings.haste_potion import resolve_haste_press_slot

        assigned = slot_press("haste") if slot_is_enabled("haste") else None
        found = resolve_haste_press_slot(
            item_key=HASTE_POTION_ITEM,
            assigned_slot=assigned,
            live_snap=snap,
        )
        return found is not None
    if not isinstance(slots, list) or not slots:
        return True
    from hotbar.inspect import hotbar_has_role

    return hotbar_has_role(snap, name)


def _buff_session_start(blackboard: "Blackboard", now: float) -> float:
    started = float(blackboard.buff_session_at or 0.0)
    if started <= 0.0:
        blackboard.buff_session_at = now
        return now
    return started


def _memory_buffs_ready(state: Optional["GameState"]) -> bool:
    """True when buff_listen snapshot is trustworthy for missing/remain checks.

    ``cache>0`` with ``buffs: []`` is a false empty (STABLE/orphan filter) — fall
    back to the timer path instead of spam-casting every cast-guard window.
    """
    if state is None:
        return False
    snap = getattr(state, "last_buff", None)
    if not isinstance(snap, dict) or not isinstance(snap.get("buffs"), list):
        return False
    try:
        cache_n = int(snap.get("cache") or 0)
    except (TypeError, ValueError):
        cache_n = 0
    if cache_n > 0 and len(snap["buffs"]) == 0:
        return False
    return True


def _match_live_buff(
    role: str,
    effects: list,
) -> Optional["StatusEffect"]:
    spec = _BUFF_MATCH.get(role)
    if not spec:
        return None
    skills = spec["skills"]  # type: ignore[assignment]
    str_ids = spec["str_ids"]  # type: ignore[assignment]
    needles = spec["needles"]  # type: ignore[assignment]
    for effect in effects:
        if getattr(effect, "perpetual", False):
            continue
        try:
            skill = int(getattr(effect, "skill", 0) or 0)
        except (TypeError, ValueError):
            skill = 0
        try:
            str_id = int(getattr(effect, "str_id", 0) or 0)
        except (TypeError, ValueError):
            str_id = 0
        if skill and skill in skills:
            return effect
        if str_id and str_id in str_ids:
            return effect
        name = str(getattr(effect, "name", "") or "").lower()
        if name and any(n.lower() in name for n in needles):  # type: ignore[union-attr]
            return effect
    return None


def _buff_cast_guarded(blackboard: "Blackboard", name: str, now: float) -> bool:
    prev = float(blackboard.buff_last_cast.get(name, 0.0) or 0.0)
    return bool(prev and (now - prev) < BUFF_CAST_GUARD_S)


def due_buff(
    blackboard: "Blackboard",
    state: Optional["GameState"] = None,
) -> Optional[str]:
    """Next buff role to cast, or None.

    Prefer live memory remain when ``last_buff`` is present. Missing / remain
    ≤ ``BUFF_REMAIN_RECAST_S`` → due. Perpetual skipped. No snapshot → timer
    fallback (start delay + ``BUFF_COOLDOWN_S`` / slot reuse).
    """
    now = time.time()
    started = _buff_session_start(blackboard, now)
    last = blackboard.buff_last_cast
    memory_ok = _memory_buffs_ready(state)
    effects = list(getattr(getattr(state, "player", None), "buffs", None) or []) if memory_ok else []

    for name in BUFF_ORDER:
        if name == BUFF_HASTE and not USE_HASTE_POTION:
            continue
        if not slot_is_enabled(name):
            continue
        if not assigned_buff_on_live_hotbar(name, state, blackboard):
            continue
        if _buff_cast_guarded(blackboard, name, now):
            continue

        if memory_ok:
            live = _match_live_buff(name, effects)
            if live is None:
                prev = float(last.get(name, 0.0) or 0.0)
                if prev <= 0.0:
                    delay = float(BUFF_START_DELAY_S.get(name, 0.0) or 0.0)
                    if now - started < delay:
                        continue
                return name
            try:
                remain = float(getattr(live, "duration", 0.0) or 0.0)
            except (TypeError, ValueError):
                remain = 0.0
            if remain <= BUFF_REMAIN_RECAST_S:
                return name
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
    name = due_buff(blackboard, state)
    if name is None:
        return None
    # Haste potions are items — skip mana reserve / magic cooldown.
    if slot_is_magic(name):
        if not can_cast_spell(state, role=name, blackboard=blackboard):
            return None
        if not magic_ready(blackboard):
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
    from hotbar.inspect import hotbar_has_role

    return hotbar_has_role(snap, "teleport")


def mother_tree_on_live_hotbar(
    state: Optional["GameState"] = None,
    blackboard: Optional["Blackboard"] = None,
) -> bool:
    """True when Return to Mother Tree is on the live 24-slot bar."""
    snap = _live_hotbar_snap(state, blackboard)
    if snap is None:
        return False
    from hotbar.inspect import hotbar_has_role

    return hotbar_has_role(snap, "mother_tree")


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
    if _mana_blocks_teleport(state, blackboard):
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


def _mana_blocks_teleport(
    state: Optional["GameState"],
    blackboard: Optional["Blackboard"] = None,
) -> bool:
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
    if ratio is not None and ratio <= SPELL_MANA_RESERVE_RATIO:
        return True
    return mother_tree_mana_blocks(state, "teleport", blackboard)


__all__ = [
    "BUFF_POWER",
    "BUFF_ARMOR",
    "BUFF_HASTE",
    "BUFF_LIGHT",
    "BUFF_ORDER",
    "BUFF_COOLDOWN_S",
    "BUFF_REMAIN_RECAST_S",
    "BUFF_CAST_GUARD_S",
    "LIGHT_REUSE_S",
    "BUFF_START_DELAY_S",
    "SPELL_MANA_RESERVE_RATIO",
    "MOTHER_TREE_MANA_FLOOR",
    "HEAL_UNTIL_HP_RATIO",
    "UNSTICK_TELEPORT_COOLDOWN_S",
    "magic_ready",
    "slot_ready",
    "mark_slot_used",
    "can_cast_spell",
    "spell_mp_cost_for_role",
    "mother_tree_mana_blocks",
    "request_heal_after_teleport",
    "maybe_heal_after_teleport",
    "WORLD_TREE_BLESSING_STR_ID",
    "world_tree_blessing_active",
    "maybe_hp_to_mp",
    "maybe_hp_to_mp_at_tree",
    "hp_to_mp_on_live_hotbar",
    "assigned_buff_on_live_hotbar",
    "due_buff",
    "mark_buff_cast",
    "note_buffs_active",
    "persist_buff_timers",
    "restore_buff_timers",
    "maybe_cast_buff",
    "try_unstick_teleport",
    "teleport_on_live_hotbar",
    "mother_tree_on_live_hotbar",
]
