"""Reusable combat / loot / potion ticks for mode policies."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world import ActionType, ObjectType
from app._04_decision.attack_feedback import excluded_target_ids
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.combat import (
    GIVE_UP_COOLDOWN_TICKS,
    begin_engage,
    clear_engage_state,
    continue_sticky_combat,
    note_attack_attempt,
    rebind_sticky_target,
    sticky_target_alive,
)
from app._04_decision.behaviors.unstick import (
    try_combat_blocked_unstick,
    try_combat_wall_detour,
)
from app._04_decision.behaviors.loot_hop import (
    begin_loot_item,
    clear_loot_hop,
    loot_awaiting_memory_gone,
    recently_clicked_loot,
    tick_loot_item,
    try_finish_pending_pickup,
)
from app._04_decision.combat_query import (
    in_near_monster_box,
    is_adena,
    memory_target_gone,
    nearest_attackable,
    nearest_lootable,
    object_absolute_tile,
    tile_distance_from_player,
)
from app._04_decision.nav_config import get_active_farm, get_loot_mode
from app._04_decision import player_mode as pm
from app._04_decision.player_mode import LOOT_MODE_ADENA

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.farm_area import FarmRect


def _effective_loot_mode(state: "GameState") -> str:
    """Config loot mode, forced to adena-only when weight exceeds threshold."""
    mode = get_loot_mode()
    player = state.player
    if player is not None and player.inventory.weight_ratio > pm.LOOT_ADENA_WEIGHT_RATIO:
        return LOOT_MODE_ADENA
    return mode


def _farm_loot_bounds(
    blackboard: "Blackboard",
) -> tuple["FarmRect | None", "WorldOrigin | None"]:
    """Active farm + origin for in-farm loot filtering; (None, None) if no farm."""
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is None:
        return None, None
    return farm, blackboard.world_origin


def emit_potion(
    blackboard: "Blackboard",
    *,
    reason: str = "low hp",
    item_key: str = "",
    hotbar_box: int | None = None,
    hotbar_key: str = "",
) -> Status:
    from app._04_decision.spells import mark_slot_used, slot_ready

    if (
        not item_key
        and hotbar_box is None
        and not slot_ready(blackboard, "hp_potion", urgent=True)
    ):
        return Status.FAILURE
    mark_slot_used(blackboard, "hp_potion")
    blackboard.current_goal = "survival_potion"
    blackboard.emit(
        ActionType.USE_HP_POTION,
        priority=0.9,
        reason=reason,
        item_key=item_key or None,
        hotbar_box=hotbar_box,
        hotbar_key=str(hotbar_key or "").strip().lower() or None,
    )
    return Status.SUCCESS


def emit_heal(blackboard: "Blackboard", *, reason: str = "low hp") -> Status:
    from app._04_decision.spells import mark_slot_used, slot_ready

    if not slot_ready(blackboard, "heal", urgent=True):
        return Status.FAILURE
    mark_slot_used(blackboard, "heal")
    blackboard.current_goal = "heal"
    blackboard.emit(ActionType.HEAL, priority=0.92, reason=reason)
    return Status.SUCCESS


def emit_mp_potion(blackboard: "Blackboard", *, reason: str = "low mp") -> Status:
    from app._04_decision.spells import mark_slot_used, slot_ready

    if not slot_ready(blackboard, "mp_potion"):
        return Status.FAILURE
    mark_slot_used(blackboard, "mp_potion")
    blackboard.current_goal = "mp_potion"
    blackboard.emit(ActionType.USE_MP_POTION, priority=0.88, reason=reason)
    return Status.SUCCESS


_POISON_NEEDLES = ("poison", "포이즌", "중독", "中毒")
_POISON_SKIP = ("cure", "큐어", "解毒術", "解毒术")
_POISON_IDS = frozenset({"10"})


def _effect_blob(effect: object) -> str:
    return str(getattr(effect, "name", "") or "").strip().lower()


def player_is_poisoned(state: "GameState") -> bool:
    """True when memory buffs/debuffs look like poison (not cure-poison)."""
    player = getattr(state, "player", None)
    if player is None:
        return False
    if bool(getattr(player, "poisoned", False)):
        return True
    effects = list(getattr(player, "buffs", None) or [])
    effects.extend(getattr(player, "debuffs", None) or [])
    for effect in effects:
        blob = _effect_blob(effect)
        if not blob:
            continue
        if blob in _POISON_IDS:
            return True
        if any(skip in blob for skip in _POISON_SKIP):
            continue
        if any(needle in blob for needle in _POISON_NEEDLES):
            return True
    return False


def maybe_use_antidote(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Drink a bag/hotbar antidote when Hunt/Attack auto-use is on."""
    if not pm.ANTIDOTE_AUTO:
        return None
    if not player_is_poisoned(state):
        return None
    from app._04_decision.spells import mark_slot_used, slot_ready
    from app._05_action.spell_box import slot_is_enabled

    if not slot_is_enabled("depoison") or not slot_ready(blackboard, "depoison"):
        return None
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is not None and bool(getattr(inv, "bag_ready", False)):
        try:
            if int(getattr(inv, "depoison", 0) or 0) <= 0:
                return None
        except (TypeError, ValueError):
            return None
    mark_slot_used(blackboard, "depoison")
    blackboard.current_goal = "antidote"
    blackboard.emit(ActionType.USE_DEPOISON, priority=0.93, reason="poisoned")
    return Status.SUCCESS


def heal_blocked_by_mana(state: "GameState") -> bool:
    """True when MP is known and too low for heal/teleport.

    Blocks at the spell reserve (default 20%) or when current MP is under 5.
    """
    from app._04_decision.mode_control import mp_ratio
    from app._04_decision.spells import SPELL_MANA_RESERVE_RATIO

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


def _hp_recovery_allowed() -> bool:
    from app._04_decision import player_mode as pm

    return bool(pm.HP_RECOVER_ENABLED)


def should_cast_heal(state: "GameState") -> bool:
    """Cast heal when Fix/Recovery allows it and HP is below the heal-until target."""
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import hp_ratio, is_critical_hp, is_low_hp
    from app._04_decision.spells import HEAL_UNTIL_HP_RATIO
    from app._05_action.spell_box import slot_is_enabled

    if not _hp_recovery_allowed() or not pm.USE_HEAL:
        return False
    if not slot_is_enabled("heal"):
        return False
    if heal_blocked_by_mana(state):
        return False
    ratio = hp_ratio(state)
    if ratio is None or ratio >= HEAL_UNTIL_HP_RATIO:
        return False
    # Prefer heal on critical; also allow while low HP toward heal-until.
    return is_critical_hp(state) or is_low_hp(state)


def should_drink_hp_potion(state: "GameState") -> bool:
    """Low HP potion, plus critical HP when heal cannot spend mana."""
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import is_critical_hp, is_low_hp
    from app._05_action.spell_box import slot_is_enabled

    if not _hp_recovery_allowed() or not pm.USE_HP_POTION:
        return False
    if not slot_is_enabled("hp_potion"):
        return False
    if not is_low_hp(state):
        return False
    if not is_critical_hp(state):
        return True
    # Critical: potion only when heal is off or cannot spend mana.
    if not pm.USE_HEAL:
        return True
    return heal_blocked_by_mana(state)


def should_drink_hp_potion_in_retreat(state: "GameState") -> bool:
    """While retreating, potion only if critical and heal is mana-blocked."""
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import is_critical_hp
    from app._05_action.spell_box import slot_is_enabled

    if not _hp_recovery_allowed() or not pm.USE_HP_POTION:
        return False
    if not slot_is_enabled("hp_potion"):
        return False
    if not is_critical_hp(state):
        return False
    if not pm.USE_HEAL:
        return True
    return heal_blocked_by_mana(state)


def should_drink_mp_potion(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import mp_ratio
    from app._05_action.spell_box import slot_is_enabled

    if not pm.MP_RECOVER_ENABLED or not pm.USE_MP_POTION:
        return False
    if not slot_is_enabled("mp_potion"):
        return False
    ratio = mp_ratio(state)
    return ratio is not None and ratio <= float(pm.MP_POTION_RATIO)


def hp_potion_reason(state: "GameState") -> str:
    from app._04_decision.mode_control import is_critical_hp

    if is_critical_hp(state):
        return "critical hp, cannot heal"
    return "low hp"


HP_RETREAT_STARTED = object()
_SCRATCH_HP_RETREAT = "hp_retreat_kind"
# After HP TP / talking-scroll land: try mother tree once before 50% wait.
_SCRATCH_POST_LAND_TREE = "hp_post_land_tree_tried"


_HEAL_HOTBAR_ALIASES = frozenset(
    {
        "힐",
        "heal",
        "초급치유술",
        "初級治癒術",
        "初级治愈术",
        "익스트라힐",
        "extraheal",
        "중급치유술",
        "中級治癒術",
        "中级治愈术",
        "그레이터힐",
        "greaterheal",
        "고급치유술",
        "高級治癒術",
        "高级治愈术",
        "힐올",
        "healall",
        "풀힐",
        "fullheal",
        "全部治癒術",
        "全部治愈术",
        "體力回復術",
        "体力回复术",
        "네이쳐스터치",
        "生命之泉",
        "네이쳐스블레싱",
        "生命的祝福",
    }
)
_HEAL_BOOK_NEEDLES = ("마법서", "魔法書", "魔法书")


def _heal_on_live_hotbar(state: "GameState") -> bool:
    """True when a heal *skill* (not a spellbook) is on the live 24-slot bar."""
    snap = getattr(state, "last_hotbar", None)
    if not isinstance(snap, dict):
        return False
    from app._04_decision.hp_actions import _fold

    for raw in snap.get("slots") or []:
        if not isinstance(raw, dict):
            continue
        blob = " ".join(
            str(raw.get(key) or "")
            for key in ("name", "label", "name_tw", "name_cn", "kr_name")
        )
        folded = _fold(blob)
        if not folded or any(token in blob for token in _HEAL_BOOK_NEEDLES):
            continue
        if any(alias and alias in folded for alias in _HEAL_HOTBAR_ALIASES):
            return True
    return False


def _can_heal_now(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._05_action.spell_box import slot_is_enabled

    if not _hp_recovery_allowed() or not pm.USE_HEAL:
        return False
    if not slot_is_enabled("heal"):
        return False
    # Live bar present → require a heal *skill* name (skip unlearned / book).
    # No snapshot yet → allow like teleport when snap is missing.
    snap = getattr(state, "last_hotbar", None)
    if isinstance(snap, dict) and not _heal_on_live_hotbar(state):
        return False
    # Unknown MP still heals. Known MP at/below the reserve is kept for teleport.
    if heal_blocked_by_mana(state):
        return False
    return True


def _hp_item_count(state: "GameState", item_key: str) -> int | None:
    """Known count for one HP item, or None when unread.

    Live hotbar wins when the item is on the bar — including count 0 — so a
    stale bag total cannot keep selecting an empty hotbar slot.
    """
    from app._04_decision.hp_actions import _fold, _item_aliases

    aliases, ids = _item_aliases(item_key)
    snap = getattr(state, "last_hotbar", None)
    if isinstance(snap, dict):
        total = 0
        seen = False
        for raw in snap.get("slots") or []:
            if not isinstance(raw, dict):
                continue
            try:
                item_id = int(raw.get("id") or raw.get("item_id") or 0)
            except (TypeError, ValueError):
                item_id = 0
            blob = " ".join(
                str(raw.get(key) or "")
                for key in ("name", "label", "name_tw", "name_cn")
            )
            if item_id not in ids and not any(
                alias and alias in _fold(blob) for alias in aliases
            ) and _fold(blob) not in aliases:
                continue
            seen = True
            try:
                total += max(0, int(raw.get("count") or 0))
            except (TypeError, ValueError):
                continue
        if seen:
            return total

    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is not None and bool(getattr(inv, "bag_ready", False)):
        total = 0
        for item in list(getattr(inv, "items", None) or []):
            try:
                item_id = int(getattr(item, "item_id", 0) or 0)
            except (TypeError, ValueError):
                item_id = 0
            names = " ".join(
                str(getattr(item, field, "") or "")
                for field in ("name", "name_tw", "name_cn", "name_en")
            )
            if item_id not in ids and not any(
                alias and alias in _fold(names) for alias in aliases
            ) and _fold(names) not in aliases:
                continue
            try:
                total += max(0, int(getattr(item, "quantity", 0) or 0))
            except (TypeError, ValueError):
                continue
        if total:
            return total
        try:
            if item_key in {"빨간 물약", "체력 회복제"}:
                return max(0, int(getattr(inv, "hp_potion", 0) or 0))
        except (TypeError, ValueError):
            return 0
        return 0
    return None


def _hp_potion_count(state: "GameState") -> int | None:
    """Known bag/hotbar HP-potion count, or None when the bag is unread."""
    from app._04_decision.hp_actions import hp_item_keys

    if not hp_item_keys():
        return _hp_item_count(state, "빨간 물약")
    counts: list[int] = []
    unread = False
    for key in hp_item_keys():
        count = _hp_item_count(state, key)
        if count is None:
            unread = True
            continue
        counts.append(count)
    if counts:
        return sum(counts)
    return None if unread else 0


def _can_item_now(state: "GameState", item_key: str) -> bool:
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import find_hp_restore_hotbar

    if not _hp_recovery_allowed() or not pm.USE_HP_POTION:
        return False
    if find_hp_restore_hotbar(state, item_key) is None:
        return False
    count = _hp_item_count(state, item_key)
    return count is not None and count > 0


def _can_potion_now(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import hp_item_keys

    if not _hp_recovery_allowed() or not pm.USE_HP_POTION:
        return False
    keys = hp_item_keys() or ("빨간 물약",)
    return any(_can_item_now(state, key) for key in keys)


def can_active_hp_recover(state: "GameState") -> bool:
    """True when a heal skill or a restore item with count > 0 is usable."""
    return _can_heal_now(state) or _can_potion_now(state)


def retreat_recover_until_ratio(state: "GameState") -> float:
    """Heal/potion usable → 90%. Neither (or exhausted) → 50% natural wait."""
    if can_active_hp_recover(state):
        return float(pm.HP_ALMOST_FULL_RATIO)
    return float(pm.HP_PASSIVE_RECOVER_RATIO)


def _can_teleport_now(
    state: "GameState | None" = None,
    blackboard: "Blackboard | None" = None,
) -> bool:
    """True when the teleport skill can fire. No MP → skip to potion / scroll."""
    from app._04_decision.spells import teleport_on_live_hotbar
    from app._05_action.spell_box import slot_is_enabled

    if not slot_is_enabled("teleport"):
        return False
    if state is not None and heal_blocked_by_mana(state):
        return False
    snap = getattr(state, "last_hotbar", None) if state is not None else None
    if snap is None and blackboard is not None:
        snap = blackboard.scratch.get("live_hotbar")
    if snap is not None and not teleport_on_live_hotbar(state, blackboard):
        return False
    return True


def _can_safe_now(blackboard: "Blackboard") -> bool:
    from app._04_decision.nav_config import get_home_tile, get_safe_areas, nearest_safe_area
    from app._04_decision.talking_scroll import talking_scroll_available

    if talking_scroll_available():
        return True
    start = (blackboard.world_origin.x, blackboard.world_origin.y)
    if nearest_safe_area(start) is not None:
        return True
    if get_home_tile() is not None:
        return True
    return bool(get_safe_areas())


def _player_level(state: "GameState | None") -> int | None:
    if state is None:
        return None
    player = getattr(state, "player", None)
    level = getattr(player, "level", None) if player is not None else None
    try:
        value = int(level) if level is not None else None
    except (TypeError, ValueError):
        return None
    return value if value is not None and value > 0 else None


def is_low_level_hp_mode(state: "GameState | None") -> bool:
    """True when field HP must skip heal/potions (level 1..14)."""
    level = _player_level(state)
    return level is not None and level < int(pm.LOW_LEVEL_HP_CAP)


def _hp_action_availability(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    retreat_starters: bool,
) -> dict[str, bool]:
    from app._04_decision.hp_actions import (
        canonical_action_id,
        is_item_action,
        item_key_from_action,
        normalize_hp_actions,
    )
    from app._04_decision.mode_control import elf_uses_mother_tree
    from app._04_decision.player_mode import PlayerMode

    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    # Field (<15): never heal/potion in place. RETREATING (마법서 상인 /
    # mother-tree stand) may heal/items again.
    field_block_heal = (
        is_low_level_hp_mode(state)
        and blackboard.player_mode is not PlayerMode.RETREATING
    )
    can = {
        "heal": (
            False
            if field_block_heal
            else (_can_heal_now(state) and _hp_action_enabled(actions, "heal"))
        ),
        "hp_potion": False,
        "mother_tree": False,
        "teleport": False,
        "safe_zone": False,
    }
    for row in actions:
        key = str(row.get("id") or "")
        if not is_item_action(key):
            continue
        if field_block_heal:
            can[key] = False
            can[canonical_action_id(key)] = False
            continue
        ready = _can_item_now(state, item_key_from_action(key))
        enabled = _hp_action_enabled(actions, key)
        can[key] = ready and enabled
        can[canonical_action_id(key)] = ready and enabled
        if ready and enabled:
            can["hp_potion"] = True
    if retreat_starters:
        from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED

        can["mother_tree"] = (
            elf_uses_mother_tree(state)
            and _hp_action_enabled(actions, "mother_tree")
        )
        # Already landed via HP safe-zone scroll this retreat — do not yank
        # out with random teleport while recovering at that landing.
        safe_landed = bool(blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED))
        low = is_low_level_hp_mode(state)
        can["teleport"] = (
            not safe_landed
            and not low  # <15: mother tree or talking scroll only
            and _can_teleport_now(state, blackboard)
            and _hp_action_enabled(actions, "teleport")
        )
        can["safe_zone"] = (
            _can_safe_now(blackboard) and _hp_action_enabled(actions, "safe_zone")
        )
    return can


def _execute_hp_action(
    action_id: str,
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat
    from app.bot_log import get_logger

    get_logger("hp").info("hp action=%s", action_id)
    if action_id == "heal":
        return emit_heal(blackboard, reason="recover hp")
    from app._04_decision.hp_actions import is_item_action, item_key_from_action

    if is_item_action(action_id):
        from app._04_decision.hp_actions import find_hp_restore_hotbar

        item_key = item_key_from_action(action_id)
        slot = find_hp_restore_hotbar(state, item_key)
        if slot is None:
            return Status.FAILURE
        box, key = slot
        return emit_potion(
            blackboard,
            reason=hp_potion_reason(state),
            item_key=item_key,
            hotbar_box=box,
            hotbar_key=key,
        )
    if action_id == "mother_tree":
        if begin_retreat(
            blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "mother_tree"
            return HP_RETREAT_STARTED
        return None
    if action_id == "teleport":
        if begin_retreat(
            blackboard,
            reason=RETREAT_FOR_HP,
            teleport=True,
            use_mother_tree=False,
            walk_to_safe=False,
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "teleport"
            return HP_RETREAT_STARTED
        low_scroll = None
        if is_low_level_hp_mode(state):
            from app._04_decision.talking_scroll import PURPOSE_SPELLBOOK

            low_scroll = PURPOSE_SPELLBOOK
        if begin_retreat(
            blackboard,
            reason=RETREAT_FOR_HP,
            prefer_scroll=True,
            allow_teleport=False,
            use_mother_tree=False,
            walk_to_safe=True,
            scroll_purpose=low_scroll,
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "safe_zone"
            return HP_RETREAT_STARTED
        return None
    if action_id == "safe_zone":
        from app._04_decision.talking_scroll import (
            HP_SAFE_SCROLL_PURPOSE,
            PURPOSE_SPELLBOOK,
            SCRATCH_HP_SAFE_SCROLLED,
            SCRATCH_RETREAT_SCROLL,
            emit_talking_scroll,
            talking_scroll_available,
        )

        if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
            return None
        purpose = (
            PURPOSE_SPELLBOOK
            if is_low_level_hp_mode(state)
            else HP_SAFE_SCROLL_PURPOSE
        )
        if begin_retreat(
            blackboard,
            reason=RETREAT_FOR_HP,
            prefer_scroll=True,
            allow_teleport=False,
            use_mother_tree=False,
            walk_to_safe=True,
            scroll_purpose=purpose,
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "safe_zone"
            if talking_scroll_available():
                status = emit_talking_scroll(
                    blackboard,
                    purpose=purpose,
                    reason="hp safe zone, talking scroll",
                )
                if status is Status.SUCCESS:
                    blackboard.scratch[SCRATCH_HP_SAFE_SCROLLED] = True
                    blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
                    return status
            return HP_RETREAT_STARTED
        return None
    return None


_SCRATCH_HP_HIST = "hp_ratio_hist"
_HP_FALLING_WINDOW_S = 1.5
_HP_FALLING_DROP = 0.02


def _record_hp_ratio(blackboard: "Blackboard", ratio: float) -> None:
    now = time.time()
    hist = list(blackboard.scratch.get(_SCRATCH_HP_HIST) or [])
    hist.append((now, float(ratio)))
    window = max(float(pm.HP_SPIKE_WINDOW_S), _HP_FALLING_WINDOW_S)
    hist = [(t, r) for t, r in hist if now - float(t) <= window + 0.25]
    blackboard.scratch[_SCRATCH_HP_HIST] = hist


def hp_falling_under_fire(blackboard: "Blackboard") -> bool:
    """True when HP is net-down over ~1.5 s (hits during natural regen)."""
    hist = list(blackboard.scratch.get(_SCRATCH_HP_HIST) or [])
    if len(hist) < 2:
        return False
    now = float(hist[-1][0])
    current = float(hist[-1][1])
    peak = max(
        float(ratio)
        for stamp, ratio in hist
        if now - float(stamp) <= _HP_FALLING_WINDOW_S
    )
    return peak - current >= _HP_FALLING_DROP


def escape_natural_recover_under_attack(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """No heal/potion left, monsters still hitting → TP / scroll per HP order."""
    from app._04_decision.hp_actions import (
        canonical_action_id,
        normalize_hp_actions,
    )

    if can_active_hp_recover(state):
        return None
    if not _nearby_monster_threat(state):
        return None
    if not hp_falling_under_fire(blackboard):
        return None
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    can = _hp_action_availability(state, blackboard, retreat_starters=True)
    for row in actions:
        action_id = canonical_action_id(str(row.get("id") or ""))
        if action_id not in ("teleport", "safe_zone", "mother_tree"):
            continue
        if not row.get("enabled", True):
            continue
        if not can.get(action_id):
            continue
        result = _execute_hp_action(action_id, state, blackboard)
        if result is not None:
            return result
    return None


def hp_spike_drop(blackboard: "Blackboard") -> bool:
    """True when peak-to-current HP loss in ``HP_SPIKE_WINDOW_S`` is large.

    Default: lose ≥20% HP within 0.5 s (chips add up). A single 20% hit
    also qualifies because the previous sample is still in the window.
    """
    hist = list(blackboard.scratch.get(_SCRATCH_HP_HIST) or [])
    if len(hist) < 2:
        return False
    now = float(hist[-1][0])
    current = float(hist[-1][1])
    window = float(pm.HP_SPIKE_WINDOW_S)
    peak = max(
        float(ratio)
        for stamp, ratio in hist
        if now - float(stamp) <= window
    )
    return peak - current >= float(pm.HP_SPIKE_DROP)


def _hp_action_enabled(actions: list, action_id: str) -> bool:
    from app._04_decision.hp_actions import canonical_action_id

    wanted = canonical_action_id(action_id)
    for row in actions:
        if canonical_action_id(str(row.get("id") or "")) == wanted:
            return bool(row.get("enabled", True))
    return False


def _nearby_monster_threat(
    state: "GameState",
    *,
    tiles: int | None = None,
) -> bool:
    """True when any living monster is inside the 4×5 near box (or ``tiles``)."""
    from app._03_world import ObjectStatus
    from app._04_decision.species_rules import is_scarecrow_species

    for obj in state.monsters():
        if obj.status is ObjectStatus.DEAD:
            continue
        if is_scarecrow_species(obj):
            continue
        if tiles is not None:
            if tile_distance_from_player(obj) <= int(tiles):
                return True
        elif in_near_monster_box(obj):
            return True
    return False


def _combat_hp_threat(state: "GameState", blackboard: "Blackboard") -> bool:
    """True when a fight can explain a sharp HP drop (not only the 4×5 box)."""
    if _nearby_monster_threat(state):
        return True
    if _nearby_monster_threat(state, tiles=int(pm.ATTACK_CLICK_TILES)):
        return True
    return blackboard.current_target_id is not None


def _monster_close(obj: object | None, *, tiles: int | None = None) -> bool:
    if obj is None:
        return False
    if tiles is not None:
        return tile_distance_from_player(obj) <= int(tiles)
    return in_near_monster_box(obj)


def apply_hp_actions(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """Walk the operator HP order: heal → tree → red water → teleport → safe.

    A nearby HP spike skips heal/items/tree and tries teleport then talking
    scroll only. Configured rows still fire this same tick at their
    ``hp_below`` gate when there is no spike escape.
    """
    from app._04_decision.hp_actions import normalize_hp_actions, pick_hp_action
    from app._04_decision.mode_control import hp_ratio, is_hp_zero
    from app._04_decision.player_mode import PlayerMode

    if is_hp_zero(state):
        return None

    if blackboard.player_mode is PlayerMode.RETREATING:
        return apply_inplace_hp_support(state, blackboard)

    antidote = maybe_use_antidote(state, blackboard)
    if antidote is not None:
        return antidote

    ratio = hp_ratio(state)
    if ratio is None:
        if should_drink_mp_potion(state):
            return emit_mp_potion(blackboard, reason="low mp")
        return None
    _record_hp_ratio(blackboard, ratio)
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)

    can = _hp_action_availability(
        state,
        blackboard,
        # Survival: HP retreat (tree/TP/safe) still allowed mid shop trip.
        retreat_starters=True,
    )
    if hp_spike_drop(blackboard) and _combat_hp_threat(state, blackboard):
        # Sharp hit: escape only (no heal / potions).
        # All levels: teleport → mother tree → talking scroll.
        # Field <15 still blocks TP outside this spike path.
        from app._04_decision.hp_actions import canonical_action_id
        from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED

        preferred = ("teleport", "mother_tree", "safe_zone")
        by_id = {
            canonical_action_id(str(row.get("id") or "")): row for row in actions
        }
        spike_left = [by_id[key] for key in preferred if key in by_id]
        spike_can = dict(can)
        if is_low_level_hp_mode(state):
            safe_landed = bool(blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED))
            spike_can["teleport"] = (
                not safe_landed
                and _can_teleport_now(state, blackboard)
                and _hp_action_enabled(actions, "teleport")
            )
        while spike_left:
            chosen = pick_hp_action(0.0, spike_left, spike_can)
            if chosen is None:
                break
            result = _execute_hp_action(chosen, state, blackboard)
            if result is not None and result is not Status.FAILURE:
                return result
            chosen_key = canonical_action_id(chosen)
            spike_left = [
                row
                for row in spike_left
                if canonical_action_id(str(row.get("id") or "")) != chosen_key
            ]
    remaining = list(actions)
    while remaining:
        chosen = pick_hp_action(ratio, remaining, can)
        if chosen is None:
            break
        result = _execute_hp_action(chosen, state, blackboard)
        if result is not None and result is not Status.FAILURE:
            return result
        remaining = [row for row in remaining if str(row.get("id") or "") != chosen]
    forced = _force_safe_scroll_if_due(state, blackboard, ratio, actions, can)
    if forced is not None:
        return forced
    if should_drink_mp_potion(state):
        return emit_mp_potion(blackboard, reason="low mp")
    _log_hp_idle(blackboard, ratio, can, actions)
    return None


_SCRATCH_HP_IDLE_LOG_AT = "hp_idle_log_at"


def _log_hp_idle(
    blackboard: "Blackboard",
    ratio: float,
    can: dict[str, bool],
    actions: list,
) -> None:
    """Throttle-log when HP is under an enabled gate but nothing could fire."""
    from app._04_decision.hp_actions import action_threshold
    from app.bot_log import get_logger

    due = False
    for row in actions:
        if not row.get("enabled", True):
            continue
        key = str(row.get("id") or "")
        thr = action_threshold(actions, key)
        if thr is None:
            continue
        if ratio <= thr:
            due = True
            break
    if not due:
        return
    now = time.time()
    last = float(blackboard.scratch.get(_SCRATCH_HP_IDLE_LOG_AT) or 0.0)
    if last and (now - last) < 2.0:
        return
    blackboard.scratch[_SCRATCH_HP_IDLE_LOG_AT] = now
    ready = ",".join(k for k, ok in can.items() if ok) or "-"
    get_logger("hp").info(
        "hp idle ratio=%.2f can=%s", float(ratio), ready
    )


def maybe_mother_tree_before_passive_wait(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """After HP TP/scroll land with no heal/items and HP < 50%: world tree once.

    Escape order is unchanged. This only runs on the post-landing wait that
    would otherwise idle until ``HP_PASSIVE_RECOVER_RATIO``.
    """
    from app._04_decision.mode_control import (
        RETREAT_FOR_HP,
        begin_retreat,
        elf_uses_mother_tree,
        hp_ratio,
    )
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app.bot_log import get_logger

    if blackboard.player_mode is not PlayerMode.RETREATING:
        return None
    if blackboard.scratch.get("mother_tree_trip"):
        return None
    if blackboard.scratch.get(_SCRATCH_POST_LAND_TREE):
        return None
    if blackboard.scratch.get("retreat_for") != RETREAT_FOR_HP:
        return None
    if blackboard.scratch.get(_SCRATCH_HP_RETREAT) == "mother_tree":
        return None
    landed_scroll = bool(blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED))
    landed_tp = (
        blackboard.scratch.get(_SCRATCH_HP_RETREAT) == "teleport"
        and not bool(blackboard.retreat_teleport_pending)
    )
    if not landed_scroll and not landed_tp:
        return None
    if can_active_hp_recover(state):
        return None
    ratio = hp_ratio(state)
    if ratio is None or ratio >= float(pm.HP_PASSIVE_RECOVER_RATIO):
        return None
    if not elf_uses_mother_tree(state):
        blackboard.scratch[_SCRATCH_POST_LAND_TREE] = True
        return None
    blackboard.scratch[_SCRATCH_POST_LAND_TREE] = True
    if begin_retreat(blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True):
        blackboard.scratch[_SCRATCH_HP_RETREAT] = "mother_tree"
        get_logger("hp").info(
            "hp post-land mother tree (no heal/items, hp=%.2f)", float(ratio)
        )
        return HP_RETREAT_STARTED
    return None


def arm_hp_escape_fallback(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """After HP teleport cannot fire: talking scroll, else mother tree."""
    from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat, elf_uses_mother_tree
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        PURPOSE_SPELLBOOK,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_RETREAT_SCROLL,
        emit_talking_scroll,
        talking_scroll_available,
    )
    from app.bot_log import get_logger

    if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
        return None
    if talking_scroll_available():
        purpose = (
            PURPOSE_SPELLBOOK
            if is_low_level_hp_mode(state)
            else HP_SAFE_SCROLL_PURPOSE
        )
        blackboard.scratch[SCRATCH_RETREAT_SCROLL] = purpose
        status = emit_talking_scroll(
            blackboard,
            purpose=purpose,
            reason="hp escape fallback, talking scroll",
        )
        if status is Status.SUCCESS:
            blackboard.scratch[SCRATCH_HP_SAFE_SCROLLED] = True
            blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "safe_zone"
            get_logger("hp").info("hp escape fallback=safe_zone")
            return status
        return None
    if elf_uses_mother_tree(state) and not blackboard.scratch.get("mother_tree_trip"):
        if begin_retreat(
            blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "mother_tree"
            get_logger("hp").info("hp escape fallback=mother_tree")
            return HP_RETREAT_STARTED
    return None


def _heal_before_potion(actions: list) -> list:
    """Keep heal ahead of paid HP items so potions are last at the safe NPC."""
    from app._04_decision.hp_actions import is_item_action

    rows = [dict(row) for row in actions]
    items = [row for row in rows if is_item_action(str(row.get("id") or ""))]
    if not items:
        return rows
    result: list = []
    placed = False
    for row in rows:
        key = str(row.get("id") or "")
        if is_item_action(key):
            continue
        result.append(row)
        if key == "heal":
            result.extend(items)
            placed = True
    if not placed:
        result.extend(items)
    return result


def apply_inplace_hp_support(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    until_ratio: float | None = None,
) -> Status | object | None:
    """Honor Fix / HP action order at the operator ``hp_below`` gates.

    Heal and restore items fire only at their configured thresholds.
    Teleport / talking scroll / World Tree also follow that order when
    they are enabled and ready. ``until_ratio`` is ignored — retreat
    exit (90% with heal/potion, 50% without) is decided separately.
    """
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import (
        is_item_action,
        item_key_from_action,
        normalize_hp_actions,
        pick_hp_action,
    )
    from app._04_decision.mode_control import hp_ratio

    antidote = maybe_use_antidote(state, blackboard)
    if antidote is not None:
        return antidote

    ratio = hp_ratio(state)
    if ratio is None:
        if should_drink_mp_potion(state):
            return emit_mp_potion(blackboard, reason="low mp")
        return None
    _record_hp_ratio(blackboard, ratio)
    under_fire = escape_natural_recover_under_attack(state, blackboard)
    if under_fire is not None:
        return under_fire
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    remaining = list(actions)
    can = _hp_action_availability(
        state,
        blackboard,
        # Survival: HP retreat (tree/TP/safe) still allowed mid shop trip.
        retreat_starters=True,
    )
    while remaining:
        chosen = pick_hp_action(ratio, remaining, can)
        if chosen is None:
            break
        if chosen == "heal":
            result = emit_heal(blackboard, reason="recover hp")
            if result is not Status.FAILURE:
                return result
        elif is_item_action(chosen):
            from app._04_decision.hp_actions import find_hp_restore_hotbar

            item_key = item_key_from_action(chosen)
            slot = find_hp_restore_hotbar(state, item_key)
            if slot is None:
                result = Status.FAILURE
            else:
                result = emit_potion(
                    blackboard,
                    reason=hp_potion_reason(state),
                    item_key=item_key,
                    hotbar_box=slot[0],
                    hotbar_key=slot[1],
                )
            if result is not Status.FAILURE:
                return result
        else:
            result = _execute_hp_action(chosen, state, blackboard)
            if result is not None and result is not Status.FAILURE:
                return result
        remaining = [row for row in remaining if str(row.get("id") or "") != chosen]
    forced = _force_safe_scroll_if_due(state, blackboard, ratio, actions, can)
    if forced is not None:
        return forced
    if should_drink_mp_potion(state):
        return emit_mp_potion(blackboard, reason="low mp")
    return None


def _force_safe_scroll_if_due(
    state: "GameState",
    blackboard: "Blackboard",
    ratio: float,
    actions: list,
    can: dict[str, bool],
) -> Status | object | None:
    """HP ≤ safe-zone gate and nothing earlier can fire → talking scroll now."""
    from app._04_decision.hp_actions import (
        action_threshold,
        canonical_action_id,
        is_item_action,
    )
    from app._04_decision.talking_scroll import (
        SCRATCH_HP_SAFE_SCROLLED,
        talking_scroll_available,
    )

    if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
        return None
    if not talking_scroll_available():
        return None
    if not _hp_action_enabled(actions, "safe_zone"):
        return None
    threshold = action_threshold(actions, "safe_zone")
    if threshold is None or ratio > threshold:
        return None
    for row in actions:
        action_id = canonical_action_id(str(row.get("id") or ""))
        if action_id == "safe_zone":
            break
        if not row.get("enabled", True):
            continue
        if can.get(action_id) or can.get(str(row.get("id") or "")):
            return None
        if is_item_action(action_id) and can.get("hp_potion"):
            return None
    return _execute_hp_action("safe_zone", state, blackboard)


def maybe_escalate_teleport_to_safe(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """After a teleport-only hop, walk/scroll to safe if that action is still due."""
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat, hp_ratio

    if blackboard.scratch.get(_SCRATCH_HP_RETREAT) != "teleport":
        return False
    if blackboard.retreat_teleport_pending or blackboard.nav_goal is not None:
        return False
    if blackboard.scratch.get("mother_tree_trip"):
        return False
    ratio = hp_ratio(state)
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    threshold = action_threshold(actions, "safe_zone")
    if ratio is None or threshold is None or ratio > threshold:
        return False
    if not _can_safe_now(blackboard):
        return False
    if begin_retreat(
        blackboard,
        reason=RETREAT_FOR_HP,
        prefer_scroll=True,
        allow_teleport=False,
        use_mother_tree=False,
        walk_to_safe=True,
    ):
        blackboard.scratch[_SCRATCH_HP_RETREAT] = "safe_zone"
        return True
    return False


def maybe_recovery_support(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Heal / HP potion / MP potion gated by Fix/Recovery settings."""
    result = apply_inplace_hp_support(state, blackboard)
    if result is not None:
        return result
    if should_drink_mp_potion(state):
        return emit_mp_potion(blackboard, reason="low mp")
    return None


def continue_or_start_combat(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    allow_new: bool = True,
    near_box: bool = False,
    near_tiles: int | None = None,
    screen_only: bool = False,
) -> Status | None:
    """Sticky combat until death; returns None if no attack this tick."""
    origin = blackboard.world_origin
    if (
        blackboard.current_target_id is not None
        or blackboard.current_target_species
        or blackboard.current_target_world is not None
    ):
        if continue_sticky_combat(state, blackboard):
            tid = blackboard.current_target_id
            obj = state.get_object(tid) if tid is not None else None
            if obj is not None:
                from app._04_decision.combat_query import can_engage_target

                if not can_engage_target(obj, origin):
                    if try_combat_wall_detour(state, blackboard):
                        blackboard.current_goal = "combat"
                        return Status.SUCCESS
                    if try_combat_blocked_unstick(state, blackboard):
                        blackboard.current_goal = "combat"
                        return Status.SUCCESS
                    # Still sticky: wait one tick instead of shooting through wall.
                    from app.bot_log import get_logger

                    get_logger("combat").info(
                        "wall/fence — hold sticky id=%s (detour pending)",
                        tid,
                    )
                    blackboard.current_goal = "combat"
                    blackboard.emit(
                        ActionType.IDLE,
                        priority=0.45,
                        reason="wall detour pending",
                        target_id=tid,
                    )
                    return Status.SUCCESS
            if try_combat_blocked_unstick(state, blackboard):
                blackboard.current_goal = "combat"
                return Status.SUCCESS
            tid = blackboard.current_target_id
            obj = state.get_object(tid) if tid is not None else None
            if tid is None or obj is None or not sticky_target_alive(state, int(tid)):
                if not allow_new:
                    return None
            else:
                note_attack_attempt(blackboard, obj)
                blackboard.current_goal = "combat"
                blackboard.emit(
                    ActionType.ATTACK,
                    target_id=tid,
                    priority=0.5,
                    reason="attack target",
                    mid_act=True,
                )
                return Status.SUCCESS

    if not allow_new:
        return None

    target = nearest_attackable(
        state,
        exclude=excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS),
        origin=origin,
        near_box=near_box,
        near_tiles=near_tiles,
        screen_only=screen_only,
    )
    if target is None:
        blackboard.target_select_until = 0.0
        blackboard.target_select_id = None
        return None
    if pm.TARGET_DELAY_ENABLED:
        import random

        pending = blackboard.target_select_id
        until = float(blackboard.target_select_until or 0.0)
        now = time.time()
        if pending != target.track_id or until <= 0:
            lo = min(int(pm.TARGET_DELAY_MIN_MS), int(pm.TARGET_DELAY_MAX_MS))
            hi = max(int(pm.TARGET_DELAY_MIN_MS), int(pm.TARGET_DELAY_MAX_MS))
            wait = random.uniform(lo, hi) / 1000.0
            blackboard.target_select_id = target.track_id
            blackboard.target_select_until = now + wait
            blackboard.current_goal = "combat"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.45,
                reason="target delay",
            )
            return Status.SUCCESS
        if now < until:
            blackboard.current_goal = "combat"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.45,
                reason="target delay",
            )
            return Status.SUCCESS
        blackboard.target_select_until = 0.0
        blackboard.target_select_id = None
    begin_engage(state, blackboard, target.track_id)
    clear_loot_hop(blackboard)
    blackboard.current_item_id = None
    blackboard.current_goal = "combat"
    if near_tiles is not None and int(near_tiles) <= int(pm.LOOT_APPROACH_THREAT_TILES):
        engage_reason = "threat5 engage"
    elif screen_only:
        engage_reason = "screen engage"
    else:
        engage_reason = "engage target"
    blackboard.emit(
        ActionType.ATTACK,
        target_id=target.track_id,
        priority=0.5,
        reason=engage_reason,
        mid_act=False,
    )
    return Status.SUCCESS


def continue_or_start_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    allow_new: bool = True,
    restrict_to_farm: bool = True,
    screen_only: bool = True,
) -> Status | None:
    """Sticky loot as walk-to-item then pickup; None if no loot this tick."""
    # Clicked pile still in memory: re-click / walk back — do not roam away.
    pending = try_finish_pending_pickup(state, blackboard)
    if pending is not None:
        return pending

    loot_mode = _effective_loot_mode(state)
    farm, _farm_origin = (
        _farm_loot_bounds(blackboard) if restrict_to_farm else (None, None)
    )
    origin = blackboard.world_origin
    if blackboard.current_item_id is not None:
        sticky = state.get_object(blackboard.current_item_id)
        if (
            sticky is None
            or sticky.object_type is not ObjectType.ITEM
            or memory_target_gone(state, sticky)
            or recently_clicked_loot(blackboard, sticky.track_id)
        ):
            clear_loot_hop(blackboard)
            blackboard.current_item_id = None
        else:
            drop = False
            if loot_mode == LOOT_MODE_ADENA and not is_adena(sticky):
                drop = True
            elif farm is not None:
                from app._04_decision.combat_query import _loot_in_farm

                if not _loot_in_farm(sticky, farm, origin):
                    drop = True
            if drop:
                clear_loot_hop(blackboard)
                blackboard.current_item_id = None
            else:
                status = tick_loot_item(
                    state, blackboard, sticky, fresh=False
                )
                if status is Status.SUCCESS:
                    return Status.SUCCESS
                # Walk blocked → fall through to the next live memory item.

    if not allow_new:
        return None

    skip = set(excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )
    item = nearest_lootable(
        state,
        loot_mode=loot_mode,
        farm=farm,
        origin=origin,
        exclude=skip,
        screen_only=screen_only,
    )
    if item is None:
        return None
    begin_loot_item(blackboard, item.track_id)
    status = tick_loot_item(state, blackboard, item, fresh=True)
    if status is Status.SUCCESS:
        return Status.SUCCESS
    return None


def farm_loot_or_combat(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    restrict_to_farm: bool = True,
) -> Status | None:
    """Loot first; unfinished sticky kill is the only combat that beats loot.

    1. A living sticky target is finished before any new loot click.
       Vanish without a same-species rematch or death signal drops the lock
       so a new target can be chosen.
    2. Else pick up on-screen (or memory-near) ground items — loot is priority
       over nearby threats (no 5-tile interrupt).
    3. A missed loot cursor last tick yields to an attackable monster when
       there is nothing left to loot.
    4. After a pickup click, while that pile remains in memory re-click or
       walk back (do not roam). Short timeout (~0.8s) then continue.
    5. Else engage the nearest on-screen monster.
    """
    from app.bot_log import event
    from app._04_decision.combat_query import tile_distance_from_player
    from app._04_decision.mode_control import is_hp_zero

    def _dist(obj: object | None) -> str:
        if obj is None:
            return "?"
        try:
            return str(int(tile_distance_from_player(obj)))
        except (TypeError, ValueError):
            return "?"

    if is_hp_zero(state):
        return None
    origin = blackboard.world_origin
    exclude = excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS)
    sticky = rebind_sticky_target(state, blackboard)

    if sticky is not None or continue_sticky_combat(state, blackboard):
        tid = getattr(sticky, "track_id", None) or blackboard.current_target_id
        event(
            "combat",
            "farm branch=sticky id=%s dist=%s",
            tid,
            _dist(sticky),
        )
        result = continue_or_start_combat(state, blackboard, allow_new=False)
        if result is not None:
            return result
        if rebind_sticky_target(state, blackboard) is not None:
            return None
        if continue_sticky_combat(state, blackboard):
            return None

    loot = continue_or_start_loot(
        state,
        blackboard,
        allow_new=True,
        restrict_to_farm=restrict_to_farm,
        screen_only=True,
    )
    if loot is not None:
        item_id = blackboard.current_item_id
        event("loot", "farm branch=loot item_id=%s", item_id)
        return loot

    loot_click_missed = bool(blackboard.scratch.pop("loot_click_failed", False))
    if loot_click_missed:
        enemy = nearest_attackable(state, exclude=exclude, origin=origin)
        if enemy is not None:
            event(
                "combat",
                "farm branch=loot_miss_combat id=%s dist=%s",
                enemy.track_id,
                _dist(enemy),
            )
            return continue_or_start_combat(state, blackboard, allow_new=True)

    enemy = nearest_attackable(
        state, exclude=exclude, origin=origin, screen_only=True
    )
    if enemy is not None:
        event(
            "combat",
            "farm branch=screen_combat id=%s dist=%s",
            enemy.track_id,
            _dist(enemy),
        )
        return continue_or_start_combat(
            state, blackboard, allow_new=True, screen_only=True
        )
    event("search", "farm branch=none (wander/search next)")
    return None


def retreat_loot_if_clear(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """While retreating: never fight; loot only when no attackable enemy is up."""
    # Drop sticky combat — retreat never engages.
    if blackboard.current_target_id is not None:
        blackboard.current_target_id = None
        clear_engage_state(blackboard)

    exclude = excluded_target_ids(blackboard, GIVE_UP_COOLDOWN_TICKS)
    if nearest_attackable(
        state, exclude=exclude, origin=blackboard.world_origin
    ) is not None:
        # Enemy present: cancel sticky loot and keep running.
        clear_loot_hop(blackboard)
        blackboard.current_item_id = None
        return None

    return continue_or_start_loot(
        state, blackboard, allow_new=True, restrict_to_farm=False
    )


__all__ = [
    "emit_potion",
    "emit_heal",
    "emit_mp_potion",
    "player_is_poisoned",
    "maybe_use_antidote",
    "should_drink_hp_potion",
    "should_drink_hp_potion_in_retreat",
    "should_cast_heal",
    "should_drink_mp_potion",
    "maybe_recovery_support",
    "apply_hp_actions",
    "hp_spike_drop",
    "is_low_level_hp_mode",
    "hp_falling_under_fire",
    "escape_natural_recover_under_attack",
    "apply_inplace_hp_support",
    "can_active_hp_recover",
    "retreat_recover_until_ratio",
    "maybe_escalate_teleport_to_safe",
    "arm_hp_escape_fallback",
    "maybe_mother_tree_before_passive_wait",
    "HP_RETREAT_STARTED",
    "hp_potion_reason",
    "heal_blocked_by_mana",
    "continue_or_start_combat",
    "continue_or_start_loot",
    "farm_loot_or_combat",
    "retreat_loot_if_clear",
]
