"""L5 emitters: HP execute, farm_loot_or_combat, retreat support.

Called from L3 ladders (``mode_ticks``). Schema/tables stay in L6
(``hp_actions``, ``combat_query``). See ``Docs/architecture/DECISION_HIERARCHY.md``.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world import ActionType, ObjectType
from app._04_decision.attack_feedback import excluded_target_ids
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.combat import (
    begin_engage,
    clear_engage_state,
    continue_sticky_combat,
    prefer_attacked_me_sticky,
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
    describe_attackable_filter_skips,
    in_near_monster_box,
    is_adena,
    memory_target_gone,
    nearest_attackable,
    nearest_attacks_me_force,
    nearest_lootable,
    sync_attacks_me_force_targets,
    tile_distance_from_player,
)
from app._04_decision.nav_config import get_active_farm, get_loot_mode
from app._04_decision import player_mode as pm
from app._04_decision.player_mode import LOOT_MODE_ADENA

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState, WorldObject
    from app._03_world.space.world_coords import WorldOrigin
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


def character_is_attacking(state: "GameState", blackboard: "Blackboard") -> bool:
    """True while the held target is still a living monster.

    A living lock means this tick would keep shooting. Heal waits until that
    target is dead or the lock is gone, then the next decision can top up.
    """
    tid = getattr(blackboard, "current_target_id", None)
    if tid is None:
        return False
    from app._04_decision.behaviors.combat import sticky_target_alive

    try:
        return sticky_target_alive(state, int(tid))
    except (TypeError, ValueError):
        return False


def emit_heal(
    blackboard: "Blackboard",
    state: "GameState | None" = None,
    *,
    reason: str = "low hp",
) -> Status:
    from app._04_decision.spells import mark_slot_used, slot_ready

    if state is not None and character_is_attacking(state, blackboard):
        return Status.FAILURE
    if not slot_ready(blackboard, "heal", urgent=True):
        return Status.FAILURE
    mark_slot_used(blackboard, "heal")
    blackboard.current_goal = "heal"
    box, key = (None, None)
    if state is not None:
        slot = heal_press_slot(state)
        if slot is not None:
            box, key = slot
    blackboard.emit(
        ActionType.HEAL,
        priority=0.92,
        reason=reason,
        hotbar_box=box,
        hotbar_key=key,
    )
    return Status.SUCCESS


def maybe_heal_mp_to_hp_at_tree(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Mother-tree recharge: heal while HP ≤ 40% and MP ≥ 80%.

    Slot choice, mana floor, and cooldown are the field heal path
    (``heal_press_slot``, ``heal_blocked_by_mana``, ``emit_heal``).
    None when the band is closed or the cast cannot start, so the tree
    tick keeps standing and checks the ratios again next tick.
    """
    if blackboard.scratch.get("mother_tree_trip") != "recharge":
        return None
    from app._04_decision import player_mode as pm
    from app._04_decision.mode_control import hp_ratio, mp_ratio

    from app._06_party.recovery import active

    party = active()
    if party is not None:
        if not party.tree_heal:
            return None
        max_hp = float(party.tree_heal_hp) / 100.0
        min_mp = float(party.tree_heal_mp) / 100.0
    else:
        if not bool(pm.MP_TO_HP_ENABLED):
            return None
        max_hp = float(pm.MP_TO_HP_MAX_HP_RATIO)
        min_mp = float(pm.MP_TO_HP_MIN_MP_RATIO)
    ratio = hp_ratio(state)
    mpr = mp_ratio(state)
    if ratio is None or mpr is None:
        return None
    if ratio > max_hp:
        return None
    if mpr < min_mp:
        return None
    if heal_blocked_by_mana(state, blackboard, role="heal"):
        return None
    if heal_press_slot(state) is None:
        return None
    result = emit_heal(blackboard, state, reason="mp to hp at mother tree")
    if result is not Status.SUCCESS:
        return None
    blackboard.current_goal = "mother_tree"
    return result


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


# Curse-paralyze string ids from data_string.csv.
# 212 / 291 = 석화 상태(진행 중) / 你的身體漸漸麻痺 — drink.
# 111 / 213 = 석화 상태(마비) / 你的身體慢慢石化 — too late.
_CURE_PARALYZE_STR_IDS = frozenset({212, 291})
_CURE_PARALYZE_NEEDLES = (
    "석화 상태(진행 중)",
    "석화상태(진행 중)",
    "석화상태(진행중)",
    "你的身體漸漸麻痺",
    "你的身体渐渐麻痹",
)
_LOCKED_PARALYZE_STR_IDS = frozenset({111, 213})
_LOCKED_PARALYZE_NEEDLES = (
    "석화 상태(마비)",
    "석화상태(마비)",
    "你的身體慢慢石化",
    "你的身体慢慢石化",
)


def _effect_str_id(effect: object) -> int:
    try:
        return int(getattr(effect, "str_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _player_effects(state: "GameState") -> list[object]:
    player = getattr(state, "player", None)
    if player is None:
        return []
    effects = list(getattr(player, "buffs", None) or [])
    effects.extend(getattr(player, "debuffs", None) or [])
    return effects


def _effect_matches(effect: object, str_ids: frozenset[int], needles: tuple[str, ...]) -> bool:
    if _effect_str_id(effect) in str_ids:
        return True
    blob = _effect_blob(effect)
    return bool(blob and any(needle.lower() in blob for needle in needles))


def player_has_locked_paralyze(state: "GameState") -> bool:
    """True for petrify-(마비). The antidote no longer works."""
    return any(
        _effect_matches(effect, _LOCKED_PARALYZE_STR_IDS, _LOCKED_PARALYZE_NEEDLES)
        for effect in _player_effects(state)
    )


def player_has_curable_paralyze(state: "GameState") -> bool:
    """True for petrify in progress. Locked petrify does not match."""
    if player_has_locked_paralyze(state):
        return False
    return any(
        _effect_matches(effect, _CURE_PARALYZE_STR_IDS, _CURE_PARALYZE_NEEDLES)
        for effect in _player_effects(state)
    )


def player_should_drink_antidote(state: "GameState") -> bool:
    """In-progress petrify, or poison. Locked petrify (마비) is too late."""
    if player_has_locked_paralyze(state):
        return False
    if player_has_curable_paralyze(state):
        return True
    return player_is_poisoned(state)


def maybe_use_antidote(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Antidote is a potion side-intent — never wins the exclusive ladder."""
    del state, blackboard
    return None


# Heal and teleport skills spend mana only at this absolute MP, not a percent.
HP_SKILL_MIN_MP = 20


def current_mp(state: "GameState | None") -> int | None:
    player = getattr(state, "player", None) if state is not None else None
    if player is None:
        return None
    mp = getattr(player, "mp", None)
    if mp is None:
        return None
    try:
        return int(mp)
    except (TypeError, ValueError):
        return None


def heal_blocked_by_mana(
    state: "GameState",
    blackboard: "Blackboard | None" = None,
    *,
    role: str = "heal",
) -> bool:
    """True when current MP is known and below 20.

    Unknown MP does not block. The check is the point value, not a percent
    of max MP. When mother tree is on, also block if casting ``role`` would
    leave MP below the mother-tree floor (catalog cost).
    """
    mp = current_mp(state)
    if mp is not None and mp < HP_SKILL_MIN_MP:
        return True
    from app._04_decision.spells import mother_tree_mana_blocks

    return mother_tree_mana_blocks(state, role, blackboard)


def _hp_recovery_allowed() -> bool:
    from app._04_decision import player_mode as pm
    from app._06_party.recovery import party_on

    if party_on():
        return True
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
    if heal_blocked_by_mana(state, role="heal"):
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
_SCRATCH_HP_TP_ONCE = "hp_teleport_once_fired"
# After HP TP / talking-scroll land: try mother tree once before passive wait.
_SCRATCH_POST_LAND_TREE = "hp_post_land_tree_tried"
# Dungeon escape teleport only. The retreat row (default 30%) stays the
# sell / world-tree return on every map. This band is above that row.
DUNGEON_TELEPORT_HP_RATIO = 0.50


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


def _hotbar_cell_press(raw: dict) -> tuple[int, str] | None:
    from app._05_action.spell_box import SKILL_KEYS
    from hotbar.inspect import slot_to_box_key

    try:
        box = int(raw.get("box") or 0)
    except (TypeError, ValueError):
        box = 0
    key = str(raw.get("key") or "").strip().lower()
    if box in (1, 2, 3) and key in SKILL_KEYS:
        return box, key
    try:
        index = int(raw.get("slot", -1))
    except (TypeError, ValueError):
        index = -1
    if 0 <= index <= 23:
        return slot_to_box_key(index)
    return None


def heal_press_slot(state: "GameState | None") -> tuple[int, str] | None:
    """Box and key decision has chosen for a heal press.

    A pinned HP-row cell wins. A live bar must contain a heal role or a heal
    skill name. With no bar yet, the configured heal slot is the press.
    """
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import _fold, action_row, assigned_hotbar_slot
    from app._05_action.spell_box import slot_press
    from hotbar.inspect import find_role_on_hotbar

    assigned = assigned_hotbar_slot(action_row(pm.HP_ACTIONS or [], "heal"))
    if assigned is not None:
        return assigned
    snap = getattr(state, "last_hotbar", None) if state is not None else None
    if not isinstance(snap, dict):
        return slot_press("heal")
    found = find_role_on_hotbar(snap, "heal")
    if found is not None:
        return found
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
        if not any(alias and alias in folded for alias in _HEAL_HOTBAR_ALIASES):
            continue
        press = _hotbar_cell_press(raw)
        if press is not None:
            return press
    return None


def _can_heal_now(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._05_action.spell_box import slot_is_enabled

    from app._06_party.recovery import party_on

    if not _hp_recovery_allowed() or not (pm.USE_HEAL or party_on()):
        return False
    if not slot_is_enabled("heal"):
        return False
    if heal_press_slot(state) is None:
        return False
    if heal_blocked_by_mana(state):
        return False
    return True


def _hp_item_count(state: "GameState", item_key: str) -> int | None:
    """Known count for one HP item, or None when unread.

    Live hotbar wins when the item is on the bar — including count 0 — so a
    stale bag total cannot keep selecting an empty hotbar slot.
    Matching prefers exact live names; catalog ids are unioned with ids
    discovered from hotbar/inventory when names match.
    """
    from app._04_decision.hp_actions import (
        _BAG_NAME_FIELDS,
        _HOTBAR_NAME_FIELDS,
        _any_name_matches,
        _live_catalog_id,
        _names_match,
        item_match_sets,
    )

    aliases, ids = item_match_sets(state, item_key)
    snap = getattr(state, "last_hotbar", None)
    if isinstance(snap, dict):
        total = 0
        seen = False
        for raw in snap.get("slots") or []:
            if not isinstance(raw, dict):
                continue
            item_id = _live_catalog_id(raw)
            if item_id not in ids and not _any_name_matches(
                raw, aliases, _HOTBAR_NAME_FIELDS
            ):
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
                item_id = int(getattr(item, "item_id", 0) or getattr(item, "id", 0) or 0)
            except (TypeError, ValueError):
                item_id = 0
            if item_id not in ids and not _any_name_matches(
                item, aliases, _BAG_NAME_FIELDS
            ):
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
    from app._04_decision.hp_actions import (
        action_row,
        assigned_hotbar_slot,
        find_hp_restore_hotbar,
    )
    if not _hp_recovery_allowed() or not pm.USE_HP_POTION:
        return False
    if assigned_hotbar_slot(action_row(pm.HP_ACTIONS or [], "hp_potion")) is not None:
        return True
    if find_hp_restore_hotbar(state, item_key) is None:
        return False
    count = _hp_item_count(state, item_key)
    return count is not None and count > 0


def _can_potion_now(state: "GameState") -> bool:
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import (
        action_row,
        assigned_hotbar_slot,
        hp_item_keys,
    )
    if not _hp_recovery_allowed() or not pm.USE_HP_POTION:
        return False
    if assigned_hotbar_slot(action_row(pm.HP_ACTIONS or [], "hp_potion")) is not None:
        return True
    keys = hp_item_keys() or ("빨간 물약",)
    return any(_can_item_now(state, key) for key in keys)


def can_active_hp_recover(state: "GameState") -> bool:
    """True when a heal skill or a restore item with count > 0 is usable."""
    return _can_heal_now(state) or _can_potion_now(state)


def retreat_recover_until_ratio(state: "GameState") -> float:
    """HP retreat waits until this ratio (default 95%), keep mode otherwise."""
    del state
    return float(pm.HP_ALMOST_FULL_RATIO)


def retreat_fill_until_ratio(blackboard: "Blackboard") -> float | None:
    """Safe-zone HP retreat keeps heal and potions up to the resume ratio.

    None while hunting, on a mother-tree trip, or on an MP/return retreat.
    Those keep the Recovery-tab percents.
    """
    from app._04_decision.mode_control import RETREAT_FOR_HP
    from app._04_decision.player_mode import PlayerMode

    if blackboard.player_mode is not PlayerMode.RETREATING:
        return None
    if blackboard.scratch.get("mother_tree_trip"):
        return None
    if blackboard.scratch.get("retreat_for") != RETREAT_FOR_HP:
        return None
    return float(pm.HP_ALMOST_FULL_RATIO)


def _can_teleport_now(
    state: "GameState | None" = None,
    blackboard: "Blackboard | None" = None,
) -> bool:
    """True when the teleport skill can fire. No MP → skip to potion / scroll."""
    from app._04_decision.spells import teleport_on_live_hotbar
    from app._05_action.spell_box import slot_is_enabled

    if not slot_is_enabled("teleport"):
        return False
    if state is not None and heal_blocked_by_mana(
        state, blackboard, role="teleport"
    ):
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
    from app._06_party.recovery import active

    scroll = talking_scroll_available()
    start = (blackboard.world_origin.x, blackboard.world_origin.y)
    dest = (
        nearest_safe_area(start) is not None
        or get_home_tile() is not None
        or bool(get_safe_areas())
    )
    party = active()
    if party is None:
        return scroll or dest
    if scroll:
        return True
    return bool(party.safe_zone and dest)


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
    """Level gate is off. Fix/HP runs the same way at every level."""
    del state
    return False


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
    # Field (<15): never heal/potion in place. RETREATING (HP-safe scroll /
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

        retreat_on = _hp_action_enabled(actions, "retreat")
        can["mother_tree"] = (
            retreat_on
            and elf_uses_mother_tree(state, blackboard)
        )
        # Already landed via HP safe-zone scroll this retreat — do not yank
        # out with random teleport while recovering at that landing.
        safe_landed = bool(blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED))
        low = is_low_level_hp_mode(state)
        can["teleport"] = (
            retreat_on
            and not safe_landed
            and not low  # <15: mother tree or talking scroll only
            and _can_teleport_now(state, blackboard)
        )
        can["safe_zone"] = retreat_on and _can_safe_now(blackboard)
    _apply_teleport_once_gate(state, blackboard, actions, can)
    if _mother_tree_low_mp(state, actions):
        can["teleport"] = False
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
        return emit_heal(blackboard, state, reason="recover hp")
    from app._04_decision.hp_actions import is_item_action, item_key_from_action

    if is_item_action(action_id):
        # HP potions are armed on blackboard.side_intents (parallel channel).
        return None
    if action_id == "mother_tree":
        if begin_retreat(
            blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "mother_tree"
            return HP_RETREAT_STARTED
        return None
    if action_id == "teleport":
        started = _begin_hp_teleport_retreat(blackboard)
        if started is not None:
            return started
        if begin_retreat(
            blackboard,
            reason=RETREAT_FOR_HP,
            prefer_scroll=True,
            allow_teleport=False,
            use_mother_tree=False,
            walk_to_safe=True,
        ):
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "safe_zone"
            return HP_RETREAT_STARTED
        return None
    if action_id == "safe_zone":
        from app._04_decision.talking_scroll import (
            HP_SAFE_SCROLL_PURPOSE,
            SCRATCH_HP_SAFE_SCROLLED,
            SCRATCH_RETREAT_SCROLL,
            emit_talking_scroll,
            pick_hp_safe_scroll_spot,
            talking_scroll_available,
        )

        if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
            return None
        purpose = HP_SAFE_SCROLL_PURPOSE
        spot_id = pick_hp_safe_scroll_spot(blackboard)
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
                    spot_id=spot_id,
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
    from app._04_decision.hp_actions import normalize_hp_actions

    if can_active_hp_recover(state):
        return None
    if not _nearby_monster_threat(state):
        return None
    if not hp_falling_under_fire(blackboard):
        return None
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    can = _hp_action_availability(state, blackboard, retreat_starters=True)
    from app._04_decision.hp_actions import RETREAT_METHOD_ORDER

    for action_id in RETREAT_METHOD_ORDER:
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
    from app._06_party.recovery import active

    wanted = canonical_action_id(action_id)
    party = active()
    if party is not None:
        if wanted in ("heal", "retreat"):
            return True
        if wanted == "safe_zone":
            return bool(party.safe_zone or party.talking_scroll)
        if wanted == "mother_tree":
            return bool(party.mother_tree)
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


def _known_hp_ratio(state: "GameState") -> float | None:
    from app._04_decision.mode_control import hp_ratio

    player = getattr(state, "player", None)
    if player is None or getattr(player, "hp", None) is None:
        return None
    try:
        return hp_ratio(state)
    except (AttributeError, TypeError, ZeroDivisionError):
        return None


def _apply_teleport_once_gate(
    state: "GameState",
    blackboard: "Blackboard",
    actions: list,
    can: dict[str, bool],
) -> None:
    """One escape teleport stays spent until HP rises above the dungeon line.

    The retreat row is lower (default 30%). Clearing the flag there made a
    dungeon teleport at 50% fire again as soon as HP was back above 30%.
    """
    del actions
    ratio = _known_hp_ratio(state)
    if ratio is not None and ratio > DUNGEON_TELEPORT_HP_RATIO:
        blackboard.scratch.pop(_SCRATCH_HP_TP_ONCE, None)
    if blackboard.scratch.get(_SCRATCH_HP_TP_ONCE):
        can["teleport"] = False
    if can.get("teleport") and _can_potion_now(state):
        can["teleport"] = False


def _mother_tree_low_mp(state: "GameState", actions: list) -> bool:
    """HP at or under the World Tree row and current MP under 20."""
    from app._04_decision.hp_actions import action_threshold

    if not _hp_action_enabled(actions, "mother_tree"):
        return False
    ratio = _known_hp_ratio(state)
    threshold = action_threshold(actions, "mother_tree")
    mp = current_mp(state)
    if ratio is None or threshold is None or mp is None:
        return False
    return ratio <= threshold and mp < HP_SKILL_MIN_MP


def _shop_when_tree_blocked(
    state: "GameState",
    blackboard: "Blackboard",
    actions: list,
    can: dict[str, bool],
):
    """World Tree is due but cannot start → arm a potion shop trip."""
    if not _mother_tree_low_mp(state, actions):
        return None
    if can.get("mother_tree"):
        return None
    from app._04_decision.shop_trip import tick_shop_trip
    from app.bot_log import get_logger

    blackboard.needs_potion = True
    get_logger("hp").info("hp world-tree blocked, mp<%s → shop", HP_SKILL_MIN_MP)
    return tick_shop_trip(state, blackboard)


def _maybe_sell_then_hp_retreat(
    state: "GameState",
    blackboard: "Blackboard",
    can: dict[str, bool],
) -> Status | object | None:
    """HP retreat gate: weight >= 50% sells first, then the same retreat.

    Below 50% the shop trip is dropped and retreat starts on this tick.
    Exactly 50% sells first.
    """
    from app._04_decision.shop_trip import (
        HP_RETREAT_SELL_WEIGHT,
        SCRATCH_HP_SELL_BEFORE_RETREAT,
        SCRATCH_SHOP_TRIP,
        arm_sell_before_hp_retreat,
        bag_weight_ratio,
        clear_shop_trip,
        tick_shop_trip,
    )

    weight = bag_weight_ratio(state)
    if weight >= HP_RETREAT_SELL_WEIGHT and arm_sell_before_hp_retreat(blackboard):
        status = tick_shop_trip(state, blackboard)
        phase = blackboard.scratch.get(SCRATCH_HP_SELL_BEFORE_RETREAT)
        if phase == "selling":
            return status if status is not None else Status.SUCCESS
        if phase == "retreat":
            blackboard.scratch.pop(SCRATCH_HP_SELL_BEFORE_RETREAT, None)
        return _execute_hp_retreat_layers(state, blackboard, can)

    if blackboard.scratch.get(SCRATCH_SHOP_TRIP):
        blackboard.scratch.pop(SCRATCH_HP_SELL_BEFORE_RETREAT, None)
        clear_shop_trip(blackboard)
    return _execute_hp_retreat_layers(state, blackboard, can)


def _execute_hp_retreat_layers(
    state: "GameState",
    blackboard: "Blackboard",
    can: dict[str, bool],
) -> Status | object | None:
    """HP ≤ L_0: mother tree, then talking scroll, then teleport. Not UI order."""
    from app._04_decision.hp_actions import RETREAT_METHOD_ORDER

    for action_id in RETREAT_METHOD_ORDER:
        if not can.get(action_id):
            continue
        result = _execute_hp_action(action_id, state, blackboard)
        if result is not None and result is not Status.FAILURE:
            return result
    return None


def _begin_hp_teleport_retreat(blackboard: "Blackboard") -> Status | object | None:
    """One HP-retreat teleport. Callers decide when this is allowed."""
    from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat

    if not begin_retreat(
        blackboard,
        reason=RETREAT_FOR_HP,
        teleport=True,
        use_mother_tree=False,
        allow_scroll=False,
        walk_to_safe=True,
    ):
        return None
    blackboard.scratch[_SCRATCH_HP_RETREAT] = "teleport"
    blackboard.scratch[_SCRATCH_HP_TP_ONCE] = True
    return HP_RETREAT_STARTED


def _release_lock_for_heal(state: "GameState", blackboard: "Blackboard") -> None:
    """Drop the combat lock so a heal can cast. The id is not excluded."""
    from app._04_decision.behaviors.combat import clear_engage_state
    from app._04_decision.clickgap import log_sticky_release

    tid = blackboard.current_target_id
    if tid is not None:
        log_sticky_release(state, blackboard, "heal in place")
        try:
            blackboard.finish_kill_ids.discard(int(tid))
        except (TypeError, ValueError):
            pass
        blackboard.current_target_id = None
    clear_engage_state(blackboard)


def _retreat_hp_under_fire(
    state: "GameState",
    blackboard: "Blackboard",
    can: dict[str, bool],
) -> Status | object | None:
    """Dungeon band above the retreat line: teleport once while hit, else heal.

    None means this tick does not leave. The sell / world-tree ladder is the
    retreat-line path and is not started here.
    """
    from app._04_decision.combat_query import monster_hitting_me
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app.bot_log import get_logger

    if monster_hitting_me(state):
        if blackboard.scratch.get(_SCRATCH_HP_TP_ONCE):
            return None
        if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
            return None
        if not _can_teleport_now(state, blackboard):
            return None
        get_logger("hp").info("hp teleport under attack")
        return _begin_hp_teleport_retreat(blackboard)

    if not can.get("heal"):
        return None
    _release_lock_for_heal(state, blackboard)
    result = emit_heal(blackboard, state, reason="recover hp in place")
    if result is not Status.FAILURE:
        return result
    blackboard.current_goal = "heal"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.92,
        reason="recover hp, heal cooling",
    )
    return Status.SUCCESS


def maybe_hp_return_while_retreating(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """Open teleport retreat that falls to the retreat line: sell, then world tree.

    A mother-tree trip already owns the character. Other retreat kinds keep
    their own exit. This is the dungeon 50% teleport that keeps being hit.
    """
    from app._04_decision.mode_control import RETREAT_FOR_HP, hp_ratio
    from app._04_decision.player_mode import PlayerMode
    from app.bot_log import get_logger

    if blackboard.player_mode is not PlayerMode.RETREATING:
        return None
    if blackboard.scratch.get("mother_tree_trip"):
        return None
    if blackboard.scratch.get("retreat_for") != RETREAT_FOR_HP:
        return None
    if blackboard.scratch.get(_SCRATCH_HP_RETREAT) != "teleport":
        return None
    ratio = hp_ratio(state)
    limit = _retreat_limit_ratio()
    if ratio is None or limit is None or ratio > limit:
        return None
    can = _hp_action_availability(state, blackboard, retreat_starters=True)
    get_logger("hp").info(
        "hp return while retreating ratio=%.2f limit=%.2f",
        float(ratio),
        float(limit),
    )
    return _maybe_sell_then_hp_retreat(state, blackboard, can)


def apply_hp_actions(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """HP layers: potion side, heal keep-mode, retreat-line return, dungeon teleport."""
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio, is_hp_zero
    from app._04_decision.player_mode import PlayerMode

    if is_hp_zero(state):
        return None

    from app._04_decision.shop_trip import SCRATCH_HP_SELL_BEFORE_RETREAT

    sell_phase = blackboard.scratch.get(SCRATCH_HP_SELL_BEFORE_RETREAT)
    if sell_phase == "selling":
        # Shop owns this character until the sell queue ends.
        return None
    if sell_phase == "retreat":
        blackboard.scratch.pop(SCRATCH_HP_SELL_BEFORE_RETREAT, None)
        from app._04_decision.talking_scroll import SCRATCH_POST_SHOP_RETURN

        blackboard.scratch.pop(SCRATCH_POST_SHOP_RETURN, None)
        can = _hp_action_availability(
            state, blackboard, retreat_starters=True
        )
        started = _execute_hp_retreat_layers(state, blackboard, can)
        if started is not None:
            return started
        return None

    if blackboard.player_mode is PlayerMode.RETREATING:
        started = maybe_hp_return_while_retreating(state, blackboard)
        if started is not None:
            return started
        return apply_inplace_hp_support(state, blackboard)

    ratio = hp_ratio(state)
    if ratio is None:
        return None
    _record_hp_ratio(blackboard, ratio)
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)

    can = _hp_action_availability(
        state,
        blackboard,
        retreat_starters=True,
    )
    shop = _shop_when_tree_blocked(state, blackboard, actions, can)
    if shop is not None:
        return shop

    retreat_th = action_threshold(actions, "retreat")
    if (
        retreat_th is not None
        and _hp_action_enabled(actions, "retreat")
        and ratio <= retreat_th
    ):
        # Both maps: sell when weight is at least 50%, then world tree.
        # Under-fire teleport does not run on this line.
        started = _maybe_sell_then_hp_retreat(state, blackboard, can)
        if started is not None:
            return started
    elif _dungeon_teleport_ratio_due(state, blackboard):
        branched = _retreat_hp_under_fire(state, blackboard, can)
        if branched is not None:
            return branched

    heal_th = action_threshold(actions, "heal")
    if (
        heal_th is not None
        and can.get("heal")
        and ratio <= heal_th
    ):
        result = emit_heal(blackboard, state, reason="recover hp")
        if result is not Status.FAILURE:
            return result

    from app._04_decision.spells import maybe_hp_to_mp

    convert = maybe_hp_to_mp(state, blackboard)
    if convert is not None:
        return convert
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


def _live_nav_pack(blackboard: "Blackboard") -> str:
    """Pack synced from MapSubsystem mapId, else the pack already loaded."""
    from app._03_world.space.map_pack import get_active_map_pack
    from app._04_decision.live_map_pack import SCRATCH_LIVE_MAP_PACK

    pack = str(blackboard.scratch.get(SCRATCH_LIVE_MAP_PACK) or "").strip()
    if pack:
        return pack
    active = get_active_map_pack()
    return str(getattr(active, "id", "") or "").strip()


def _retreat_limit_ratio() -> float | None:
    """Operator retreat percent. None when that row is off."""
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions

    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    limit = action_threshold(actions, "retreat")
    if limit is None:
        return None
    return float(limit)


def _outside_field_pack(blackboard: "Blackboard") -> bool:
    """True on a live pack that is not Talking Island or the mainland."""
    from app._04_decision.world_nav.hooks import FIELD_WORLD_NAV_PACKS

    pack = _live_nav_pack(blackboard)
    return bool(pack) and pack not in FIELD_WORLD_NAV_PACKS


def _dungeon_teleport_ratio_due(
    state: "GameState", blackboard: "Blackboard"
) -> bool:
    """Dungeon escape band: above the retreat row and at or under 50%."""
    from app._04_decision.mode_control import hp_ratio

    if not _outside_field_pack(blackboard):
        return False
    ratio = hp_ratio(state)
    limit = _retreat_limit_ratio()
    if ratio is None or limit is None or ratio <= limit:
        return False
    return ratio <= DUNGEON_TELEPORT_HP_RATIO


def _dungeon_teleport_mother_tree_due(
    state: "GameState", blackboard: "Blackboard"
) -> bool:
    """After an escape teleport off Talking Island and the mainland.

    HP is still under the operator retreat percent, heal cannot spend MP,
    and no HP potion can be used. Field packs keep the 50% scroll/teleport rule.
    """
    from app._04_decision.mode_control import hp_ratio
    from app._04_decision.world_nav.hooks import FIELD_WORLD_NAV_PACKS

    pack = _live_nav_pack(blackboard)
    if not pack or pack in FIELD_WORLD_NAV_PACKS:
        return False
    ratio = hp_ratio(state)
    limit = _retreat_limit_ratio()
    if ratio is None or limit is None or ratio >= limit:
        return False
    if not heal_blocked_by_mana(state, blackboard, role="heal"):
        return False
    if _can_potion_now(state):
        return False
    return True


def _hp_safe_natural_wait(blackboard: "Blackboard") -> bool:
    """HP safe-zone scroll is in flight, or its landing was confirmed.

    ``retreat_exit_ready`` then uses almost-full HP. A scroll that times out
    never sets the regen mark, so the retreat-line exit still applies in the hunt.
    """
    from app._04_decision.talking_scroll import (
        SCRATCH_HP_SAFE_REGEN,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_HP_SAFE_SPOT,
        SCRATCH_SCROLL_ARRIVAL,
        SCRATCH_SCROLL_SPOT,
    )

    if not blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
        return False
    if blackboard.scratch.get(SCRATCH_HP_SAFE_REGEN):
        return True
    if not blackboard.scratch.get(SCRATCH_SCROLL_ARRIVAL):
        return False
    spot = str(blackboard.scratch.get(SCRATCH_SCROLL_SPOT) or "")
    safe = str(blackboard.scratch.get(SCRATCH_HP_SAFE_SPOT) or "")
    return bool(safe) and spot == safe


def resume_hunt_above_retreat_limit(
    state: "GameState", blackboard: "Blackboard"
) -> bool:
    """Leave an HP retreat when recovery items cannot run and HP is above the retreat line.

    Under 95% is still a retreat while heal or a potion can be used, while a
    mother-tree trip is in progress, and while an HP safe-zone scroll is in
    flight or has landed. That landing waits for natural regen to 95%. MP and
    return retreats do not use this.
    """
    from app._04_decision.mode_control import RETREAT_FOR_HP, hp_ratio
    from app.bot_log import get_logger

    if blackboard.scratch.get("retreat_for") != RETREAT_FOR_HP:
        return False
    if blackboard.scratch.get("mother_tree_trip"):
        return False
    if _hp_safe_natural_wait(blackboard):
        return False
    ratio = hp_ratio(state)
    limit = _retreat_limit_ratio()
    if ratio is None or limit is None or ratio <= limit:
        return False
    if ratio >= float(pm.HP_ALMOST_FULL_RATIO):
        return False
    if can_active_hp_recover(state):
        return False
    get_logger("hp").info(
        "hp retreat resume hunt (no heal/potion, hp=%.2f limit=%.2f)",
        float(ratio),
        float(limit),
    )
    return True


def _arm_post_land_mother_tree(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    detail: str,
) -> Status | object | None:
    from app._04_decision.mode_control import (
        RETREAT_FOR_HP,
        begin_retreat,
        elf_uses_mother_tree,
    )
    from app.bot_log import get_logger

    if not elf_uses_mother_tree(state, blackboard):
        blackboard.scratch[_SCRATCH_POST_LAND_TREE] = True
        return None
    blackboard.scratch[_SCRATCH_POST_LAND_TREE] = True
    if begin_retreat(blackboard, reason=RETREAT_FOR_HP, use_mother_tree=True):
        blackboard.scratch[_SCRATCH_HP_RETREAT] = "mother_tree"
        get_logger("hp").info("%s", detail)
        return HP_RETREAT_STARTED
    return None


def maybe_mother_tree_before_passive_wait(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """After HP TP/scroll land, world tree once when in-place recovery cannot run.

    A dungeon escape teleport uses the operator retreat percent when MP blocks
    heal and no potion remains. Scroll landings, and field teleports, still use
    HP under ``HP_PASSIVE_RECOVER_RATIO`` with no heal and no potion.
    """
    from app._04_decision.mode_control import RETREAT_FOR_HP, hp_ratio
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED

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
    if landed_tp and _dungeon_teleport_mother_tree_due(state, blackboard):
        ratio = hp_ratio(state)
        limit = _retreat_limit_ratio()
        return _arm_post_land_mother_tree(
            state,
            blackboard,
            detail=(
                "hp post-teleport mother tree (mp blocked, no potion, hp=%.2f limit=%.2f)"
                % (float(ratio or 0.0), float(limit or 0.0))
            ),
        )
    if can_active_hp_recover(state):
        return None
    ratio = hp_ratio(state)
    if ratio is None or ratio >= float(pm.HP_PASSIVE_RECOVER_RATIO):
        return None
    return _arm_post_land_mother_tree(
        state,
        blackboard,
        detail="hp post-land mother tree (no heal/items, hp=%.2f)" % float(ratio),
    )


def arm_hp_escape_fallback(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | object | None:
    """After HP teleport cannot fire: talking scroll, else mother tree."""
    from app._04_decision.mode_control import RETREAT_FOR_HP, begin_retreat, elf_uses_mother_tree
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_RETREAT_SCROLL,
        emit_talking_scroll,
        pick_hp_safe_scroll_spot,
        talking_scroll_available,
    )
    from app.bot_log import get_logger

    if blackboard.scratch.get(SCRATCH_HP_SAFE_SCROLLED):
        return None
    if talking_scroll_available():
        purpose = HP_SAFE_SCROLL_PURPOSE
        spot_id = pick_hp_safe_scroll_spot(blackboard)
        blackboard.scratch[SCRATCH_RETREAT_SCROLL] = purpose
        status = emit_talking_scroll(
            blackboard,
            purpose=purpose,
            spot_id=spot_id,
            reason="hp escape fallback, talking scroll",
        )
        if status is Status.SUCCESS:
            blackboard.scratch[SCRATCH_HP_SAFE_SCROLLED] = True
            blackboard.scratch.pop(SCRATCH_RETREAT_SCROLL, None)
            blackboard.scratch[_SCRATCH_HP_RETREAT] = "safe_zone"
            get_logger("hp").info("hp escape fallback=safe_zone")
            return status
        return None
    if elf_uses_mother_tree(state, blackboard) and not blackboard.scratch.get(
        "mother_tree_trip"
    ):
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
    """Heal while retreating. Potions stay on side_intents. No scroll ladder.

    A safe-zone HP retreat (no mother-tree trip) heals until the hunt-resume
    ratio. Other retreats stop at the Recovery-tab heal percent.
    """
    del until_ratio
    from app._04_decision import player_mode as pm
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions
    from app._04_decision.mode_control import hp_ratio

    ratio = hp_ratio(state)
    if ratio is None:
        return None
    _record_hp_ratio(blackboard, ratio)
    under_fire = escape_natural_recover_under_attack(state, blackboard)
    if under_fire is not None:
        return under_fire
    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    can = _hp_action_availability(
        state,
        blackboard,
        retreat_starters=True,
    )
    shop = _shop_when_tree_blocked(state, blackboard, actions, can)
    if shop is not None:
        return shop
    fill_until = retreat_fill_until_ratio(blackboard)
    heal_th = action_threshold(actions, "heal")
    heal_cap = fill_until if fill_until is not None else heal_th
    heal_due = (
        heal_cap is not None
        and can.get("heal")
        and (ratio < heal_cap if fill_until is not None else ratio <= heal_cap)
    )
    if heal_due:
        result = emit_heal(
            blackboard,
            state,
            reason=(
                "recover hp until resume"
                if fill_until is not None
                else "recover hp"
            ),
        )
        if result is not Status.FAILURE:
            return result
    from app._04_decision.spells import maybe_hp_to_mp

    return maybe_hp_to_mp(state, blackboard)


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
    """Heal / retreat support. Potions are armed on ``side_intents``."""
    return apply_inplace_hp_support(state, blackboard)


def _solo_mage_attack_fields(state: "GameState", blackboard: "Blackboard") -> dict:
    from app._04_decision.solo_mage import solo_mage_attack_fields

    return solo_mage_attack_fields(state, blackboard)


def continue_or_start_combat(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    allow_new: bool = True,
    near_box: bool = False,
    near_tiles: int | None = None,
    screen_only: bool = False,
    chosen: WorldObject | None = None,
    reason: str | None = None,
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
                    from app._04_decision.dungeon import is_dungeon_map

                    if is_dungeon_map():
                        # No wall detour in dungeons — release sticky without
                        # give-up cooldown so the mob stays selectable when LOS
                        # clears. nearest_attackable already skips no-LOS.
                        from app._04_decision.combat_query import attack_line_block
                        from app.bot_log import get_logger

                        blocked = attack_line_block(obj, origin)
                        if blocked:
                            from app._04_decision.combat_query import (
                                attack_line_refusal_text,
                            )

                            record = attack_line_refusal_text(obj, origin, state)
                            if record is not None:
                                info, segment = record
                                get_logger("combat").info(
                                    "dungeon skip %s (no give-up)",
                                    info,
                                )
                                get_logger("combat").debug(
                                    "dungeon skip %s",
                                    segment,
                                )
                            else:
                                get_logger("combat").info(
                                    "wall/fence — dungeon skip id=%s %s (no give-up)",
                                    tid,
                                    blocked,
                                )
                        else:
                            get_logger("combat").info(
                                "wall/fence — dungeon skip id=%s (no give-up)",
                                tid,
                            )
                        from app._04_decision.clickgap import log_sticky_release

                        log_sticky_release(state, blackboard, "dungeon-wall")
                        blackboard.current_target_id = None
                        clear_engage_state(blackboard)
                    else:
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
                    **_solo_mage_attack_fields(state, blackboard),
                )
                return Status.SUCCESS

    if not allow_new:
        return None

    if chosen is not None:
        target = chosen
    else:
        target = nearest_attackable(
            state,
            exclude=excluded_target_ids(blackboard),
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
    engage_reason = ""
    if reason:
        engage_reason = reason
    elif near_tiles is not None and int(near_tiles) <= int(pm.LOOT_APPROACH_THREAT_TILES):
        engage_reason = "threat5 engage"
    elif screen_only:
        engage_reason = "screen engage"
    else:
        engage_reason = "engage target"
    begin_engage(
        state,
        blackboard,
        target.track_id,
        finish_kill=(
            engage_reason == "attacks_me engage"
            or bool(getattr(target, "force_attacks_me", False))
        ),
    )
    clear_loot_hop(blackboard)
    blackboard.current_item_id = None
    blackboard.current_goal = "combat"
    blackboard.emit(
        ActionType.ATTACK,
        target_id=target.track_id,
        priority=0.5,
        reason=engage_reason,
        mid_act=False,
        **_solo_mage_attack_fields(state, blackboard),
    )
    return Status.SUCCESS


_LOOT_TRACK_HOLD_S = 2.0
_SCRATCH_LOOT_TRACK_GUID = "loot_track_guid"
_SCRATCH_LOOT_TRACK_KIND = "loot_track_kind"
_SCRATCH_LOOT_TRACK_CELL = "loot_track_cell"
_SCRATCH_LOOT_TRACK_SINCE = "loot_track_since"
_LOOT_TRACK_HOLD = "hold"
_LOOT_TRACK_RELEASE = "release"


def _quiet_search_click(blackboard: "Blackboard") -> None:
    """Drop a search hop that would click the other way during loot.

    Does not call ``clear_search_hop``. That helper resets the 5 s unstick sweep.
    """
    blackboard.search_hop_active = False
    blackboard.search_waypoint = None


def _quiet_route_click(blackboard: "Blackboard") -> None:
    """Drop an armed route hop so it cannot click away from the pile.

    The route goal and the world-nav session stay. The 5 s unstick sweep
    is not reset.
    """
    blackboard.travel_hop_active = False
    blackboard.nav_waypoint = None
    blackboard.travel_destination = None
    blackboard.travel_unstick_active = False


def _loot_guid(obj: object) -> str:
    return str(getattr(obj, "memory_guid", None) or "").strip()


def _loot_kind(obj: object) -> str:
    return str(getattr(obj, "species_name", None) or "").strip()


def _loot_cell(obj: object) -> tuple[int, int] | None:
    cx = getattr(obj, "world_cx", None)
    cy = getattr(obj, "world_cy", None)
    if cx is None or cy is None:
        return None
    try:
        return (int(cx), int(cy))
    except (TypeError, ValueError):
        return None


def _store_loot_identity(blackboard: "Blackboard", obj: object) -> None:
    guid = _loot_guid(obj)
    kind = _loot_kind(obj)
    cell = _loot_cell(obj)
    if not guid or not kind or cell is None:
        return
    blackboard.scratch[_SCRATCH_LOOT_TRACK_GUID] = guid
    blackboard.scratch[_SCRATCH_LOOT_TRACK_KIND] = kind
    blackboard.scratch[_SCRATCH_LOOT_TRACK_CELL] = cell


def _clear_loot_track(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(_SCRATCH_LOOT_TRACK_GUID, None)
    blackboard.scratch.pop(_SCRATCH_LOOT_TRACK_KIND, None)
    blackboard.scratch.pop(_SCRATCH_LOOT_TRACK_CELL, None)
    blackboard.scratch.pop(_SCRATCH_LOOT_TRACK_SINCE, None)


def _loot_identity_ready(blackboard: "Blackboard") -> bool:
    guid = str(blackboard.scratch.get(_SCRATCH_LOOT_TRACK_GUID) or "").strip()
    kind = str(blackboard.scratch.get(_SCRATCH_LOOT_TRACK_KIND) or "").strip()
    cell = blackboard.scratch.get(_SCRATCH_LOOT_TRACK_CELL)
    return bool(guid and kind and isinstance(cell, tuple) and len(cell) == 2)


def _same_loot_pile(blackboard: "Blackboard", obj: object) -> bool:
    if not _loot_identity_ready(blackboard):
        return False
    if _loot_guid(obj) != str(blackboard.scratch.get(_SCRATCH_LOOT_TRACK_GUID) or ""):
        return False
    if _loot_kind(obj) != str(blackboard.scratch.get(_SCRATCH_LOOT_TRACK_KIND) or ""):
        return False
    return _loot_cell(obj) == tuple(blackboard.scratch.get(_SCRATCH_LOOT_TRACK_CELL))


def _find_same_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    skip: int | None,
) -> object | None:
    for obj in state.items():
        tid = int(getattr(obj, "track_id", -1))
        if skip is not None and tid == int(skip):
            continue
        if memory_target_gone(state, obj):
            continue
        if _same_loot_pile(blackboard, obj):
            return obj
    return None


def _loot_row_missing(state: "GameState", sticky: object | None) -> bool:
    if sticky is None or getattr(sticky, "object_type", None) is not ObjectType.ITEM:
        return True
    return memory_target_gone(state, sticky)


def _resolve_loot_gap(
    state: "GameState",
    blackboard: "Blackboard",
    sticky: object | None,
    *,
    f4_pause: bool,
) -> object:
    """Keep a blinked pile, rebind it, or release it.

    A live row returns itself. ``hold`` means the same GUID, kind, and cell
    are not in this sweep yet and the 2 s window is still open. ``release``
    is an F4 pause, a finished pickup, a dead row, a deleted row with no
    twin, an unverifiable pile, or a blink that lasted 2 s.
    """
    from app._02_state.objects import ObjectStatus
    from app._04_decision.behaviors.loot_hop import _bag_rose

    if (
        sticky is not None
        and not _loot_row_missing(state, sticky)
        and not f4_pause
    ):
        return sticky
    if f4_pause or _bag_rose(state, blackboard, sticky):
        return _LOOT_TRACK_RELEASE
    if sticky is not None and getattr(sticky, "status", None) is ObjectStatus.DEAD:
        return _LOOT_TRACK_RELEASE
    if sticky is not None:
        _store_loot_identity(blackboard, sticky)
    if not _loot_identity_ready(blackboard):
        return _LOOT_TRACK_RELEASE
    skip = int(getattr(sticky, "track_id", -1)) if sticky is not None else None
    match = _find_same_loot(state, blackboard, skip=skip)
    if match is not None:
        blackboard.scratch.pop(_SCRATCH_LOOT_TRACK_SINCE, None)
        return match
    if sticky is None:
        return _LOOT_TRACK_RELEASE
    since = blackboard.scratch.get(_SCRATCH_LOOT_TRACK_SINCE)
    now = time.time()
    if since is None:
        blackboard.scratch[_SCRATCH_LOOT_TRACK_SINCE] = now
        since = now
    try:
        elapsed = now - float(since)
    except (TypeError, ValueError):
        elapsed = _LOOT_TRACK_HOLD_S
    if elapsed >= _LOOT_TRACK_HOLD_S:
        return _LOOT_TRACK_RELEASE
    return _LOOT_TRACK_HOLD


def open_loot_pile(state: "GameState", blackboard: "Blackboard") -> object | None:
    """The current loot row when it is still an item in memory."""
    item_id = getattr(blackboard, "current_item_id", None)
    if item_id is None:
        return None
    try:
        obj = state.get_object(int(item_id))
    except (TypeError, ValueError):
        return None
    if obj is None or getattr(obj, "object_type", None) is not ObjectType.ITEM:
        return None
    if memory_target_gone(state, obj):
        return None
    return obj


def party_leader_pile_ok(blackboard: "Blackboard", obj: object | None) -> bool:
    """Solo loot is unchanged. A party leader starts an on-screen pile inside the near radius.

    The radius is ``LOOT_MAX_TILES`` (``farm.loot_max_tiles``). A pile already
    chosen is not dropped when it leaves that radius.
    """
    if not blackboard.scratch.get("party_leader_no_loot"):
        return obj is not None
    if obj is None:
        return False
    from app._04_decision import player_mode as pm
    from app._04_decision.combat_query import object_on_screen, tile_distance_from_player

    if not object_on_screen(obj):
        return False
    try:
        return int(tile_distance_from_player(obj)) <= max(1, int(pm.LOOT_MAX_TILES))
    except (TypeError, ValueError):
        return False


def continue_or_start_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    allow_new: bool = True,
    restrict_to_farm: bool = True,
    screen_only: bool = True,
) -> Status | None:
    """Sticky loot as walk-to-item then pickup; None if no loot this tick.

    A party leader starts only an on-screen pile within ``LOOT_MAX_TILES``.
    A pile already chosen stays until it leaves memory, the bag count rises,
    the pickup give-up fires, or the path abandon clears it. Screen, farm,
    ownership, and a second pile do not drop it first.
    """
    leader_near = bool(blackboard.scratch.get("party_leader_no_loot"))
    # Clicked pile still in memory: re-click / walk back — do not roam away.
    pending = try_finish_pending_pickup(state, blackboard)
    if pending is not None:
        return pending

    loot_mode = _effective_loot_mode(state)
    farm, _farm_origin = (
        (None, None)
        if leader_near
        else (_farm_loot_bounds(blackboard) if restrict_to_farm else (None, None))
    )
    origin = blackboard.world_origin
    if blackboard.current_item_id is not None:
        sticky = state.get_object(blackboard.current_item_id)
        f4_pause = (
            sticky is not None
            and getattr(sticky, "object_type", None) is ObjectType.ITEM
            and recently_clicked_loot(blackboard, sticky.track_id)
        )
        resolved = _resolve_loot_gap(
            state, blackboard, sticky, f4_pause=f4_pause
        )
        if resolved == _LOOT_TRACK_HOLD:
            _quiet_search_click(blackboard)
            _quiet_route_click(blackboard)
            blackboard.current_goal = "loot"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.3,
                reason="loot track hold",
            )
            return Status.SUCCESS
        if resolved == _LOOT_TRACK_RELEASE:
            clear_loot_hop(blackboard)
            blackboard.current_item_id = None
            _clear_loot_track(blackboard)
            sticky = None
        else:
            if int(getattr(resolved, "track_id", -1)) != int(
                blackboard.current_item_id
            ):
                blackboard.current_item_id = int(resolved.track_id)
            sticky = resolved
            blackboard.scratch.pop(_SCRATCH_LOOT_TRACK_SINCE, None)
            _store_loot_identity(blackboard, sticky)
        if sticky is not None and blackboard.current_item_id is not None:
            # Confirmed pile: walk and pick it up. Do not clear it for range,
            # farm, ownership, or a nearer adena. Path abandon returns FAILURE
            # after clearing the id, and the search below may start the next pile.
            _quiet_search_click(blackboard)
            _quiet_route_click(blackboard)
            status = tick_loot_item(
                state, blackboard, sticky, fresh=False
            )
            if status is Status.SUCCESS:
                return Status.SUCCESS

    if not allow_new:
        return None

    skip = set(excluded_target_ids(blackboard))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )
    if leader_near:
        from app._04_decision.combat_query import list_lootable, tile_distance_from_player

        near = [
            obj
            for obj in list_lootable(
                state,
                loot_mode=loot_mode,
                farm=None,
                origin=origin,
                exclude=skip,
                screen_only=True,
                ownership_filter=False,
            )
            if party_leader_pile_ok(blackboard, obj)
        ]
        item = (
            min(
                near,
                key=lambda obj: (
                    tile_distance_from_player(obj),
                    int(getattr(obj, "track_id", 0) or 0),
                ),
            )
            if near
            else None
        )
    else:
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
    begin_loot_item(blackboard, item.track_id, item)
    _quiet_search_click(blackboard)
    _quiet_route_click(blackboard)
    status = tick_loot_item(state, blackboard, item, fresh=True)
    if status is Status.SUCCESS:
        return Status.SUCCESS
    return None


SCRATCH_APPROACH_HOLD_FIRE = "approach_hold_fire"
SCRATCH_APPROACH_CORPSE_IDS = "approach_corpse_ids"
SCRATCH_APPROACH_CORPSES = "approach_corpses"
SCRATCH_APPROACH_KILL_ID = "approach_kill_id"
SCRATCH_APPROACH_KILL_CELL = "approach_kill_cell"
SCRATCH_APPROACH_SEEN_ITEMS = "approach_seen_items"
_CORPSE_LOOT_S = 4.0
_CORPSE_CHEB = 3


def clear_approach_hold_tick(blackboard: "Blackboard") -> None:
    """Drop the per-tick hold so a later mode in this tick can loot normally."""
    blackboard.scratch.pop(SCRATCH_APPROACH_HOLD_FIRE, None)
    blackboard.scratch[SCRATCH_APPROACH_CORPSE_IDS] = []


def hold_fire_outside_hunt(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """True when the hunt-tab switch is on and the pose is still outside.

    Break rows keep today's combat. A missing pose falls back to the active
    farm rect. No rect and no routine row leaves combat unchanged.
    """
    if not pm.APPROACH_NO_ENGAGE:
        return False
    from app._04_decision.world_nav.hooks import SCRATCH_ROUTINE, SCRATCH_WORLD_NAV
    from app._04_decision.world_nav.routine import pose_hunt_arrival
    from app._04_decision.world_nav.session import live_pose_from_state

    cursor = blackboard.scratch.get(SCRATCH_ROUTINE)
    entry = cursor.active() if cursor is not None and hasattr(cursor, "active") else None
    if isinstance(entry, dict) and str(entry.get("kind") or "").strip().lower() == "break":
        return False
    session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    reason = str(getattr(session, "reason", "") or "") if session is not None else ""
    pose = live_pose_from_state(state) if state is not None else None
    if pose is not None and isinstance(entry, dict):
        return not pose_hunt_arrival(pose, entry, blackboard, reason=reason)
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is None:
        return False
    try:
        ox = int(blackboard.world_origin.x)
        oy = int(blackboard.world_origin.y)
    except (TypeError, ValueError, AttributeError):
        return False
    return not farm.contains(ox, oy)


def _counter_sticky(state: "GameState", blackboard: "Blackboard") -> bool:
    tid = blackboard.current_target_id
    if tid is None:
        return False
    try:
        tid_i = int(tid)
    except (TypeError, ValueError):
        return False
    if tid_i in blackboard.finish_kill_ids:
        return True
    if blackboard.sticky_attacked_me:
        return True
    obj = state.get_object(tid_i)
    if obj is None:
        return False
    return bool(
        getattr(obj, "attacked_me", False) or getattr(obj, "force_attacks_me", False)
    )


def _seen_item_ids(state: "GameState") -> list[int]:
    ids: list[int] = []
    for obj in state.items():
        try:
            ids.append(int(obj.track_id))
        except (TypeError, ValueError, AttributeError):
            continue
    return ids


def _remember_counter_cell(state: "GameState", blackboard: "Blackboard") -> None:
    tid = blackboard.current_target_id
    if tid is None:
        return
    from app._04_decision.behaviors.combat import object_world_cell

    obj = state.get_object(int(tid))
    cell = object_world_cell(obj) if obj is not None else None
    if cell is None:
        return
    blackboard.scratch[SCRATCH_APPROACH_KILL_ID] = int(tid)
    blackboard.scratch[SCRATCH_APPROACH_KILL_CELL] = [int(cell[0]), int(cell[1])]


def _open_corpse_if_dead(state: "GameState", blackboard: "Blackboard") -> None:
    raw = blackboard.scratch.get(SCRATCH_APPROACH_KILL_ID)
    if raw is None:
        return
    try:
        tid = int(raw)
    except (TypeError, ValueError):
        return
    if sticky_target_alive(state, tid):
        return
    rows = [
        row
        for row in (blackboard.scratch.get(SCRATCH_APPROACH_CORPSES) or [])
        if isinstance(row, dict)
    ]
    rows.append(
        {
            "id": tid,
            "cell": blackboard.scratch.get(SCRATCH_APPROACH_KILL_CELL),
            "seen": list(blackboard.scratch.get(SCRATCH_APPROACH_SEEN_ITEMS) or []),
            "until": time.time() + _CORPSE_LOOT_S,
        }
    )
    blackboard.scratch[SCRATCH_APPROACH_CORPSES] = rows[-4:]
    blackboard.scratch.pop(SCRATCH_APPROACH_KILL_ID, None)
    blackboard.scratch.pop(SCRATCH_APPROACH_KILL_CELL, None)
    blackboard.scratch.pop(SCRATCH_APPROACH_SEEN_ITEMS, None)


def _live_corpses(blackboard: "Blackboard") -> list[dict]:
    now = time.time()
    rows = []
    for row in blackboard.scratch.get(SCRATCH_APPROACH_CORPSES) or []:
        if not isinstance(row, dict):
            continue
        try:
            until = float(row.get("until") or 0)
        except (TypeError, ValueError):
            continue
        if until >= now:
            rows.append(row)
    blackboard.scratch[SCRATCH_APPROACH_CORPSES] = rows
    return rows


def _matches_corpse(item: object, corpse: dict, now: float) -> bool:
    """True when this pile showed up from that counterattack kill."""
    from app._03_world.merge.item_sight import item_sight_row
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.behaviors.combat import object_world_cell

    try:
        until = float(corpse.get("until") or 0)
    except (TypeError, ValueError):
        return False
    if until < now:
        return False
    try:
        tid = int(getattr(item, "track_id"))
    except (TypeError, ValueError):
        return False
    seen = {int(x) for x in (corpse.get("seen") or [])}
    if tid in seen:
        return False
    row = item_sight_row(tid)
    drop_id = None if row is None else row.get("drop_id")
    cid = corpse.get("id")
    if drop_id is not None and cid is not None:
        try:
            return int(drop_id) == int(cid)
        except (TypeError, ValueError):
            return False
    cell = corpse.get("cell")
    abs_xy = None if row is None else row.get("abs")
    if abs_xy is None:
        abs_xy = object_world_cell(item)
    if not cell or abs_xy is None or len(cell) < 2:
        return False
    try:
        return (
            tile_chebyshev(
                int(abs_xy[0]), int(abs_xy[1]), int(cell[0]), int(cell[1])
            )
            <= _CORPSE_CHEB
        )
    except (TypeError, ValueError):
        return False


def _publish_corpse_ids(blackboard: "Blackboard", ids: list[int]) -> None:
    blackboard.scratch[SCRATCH_APPROACH_CORPSE_IDS] = [int(i) for i in ids]


def _loot_counter_drops(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Pick up piles from counterattack kills, using the hunt loot mode."""
    from app._04_decision.combat_query import list_lootable

    corpses = _live_corpses(blackboard)
    if not corpses and blackboard.current_item_id is None:
        _publish_corpse_ids(blackboard, [])
        return None
    now = time.time()
    loot_mode = _effective_loot_mode(state)
    origin = blackboard.world_origin
    skip = set(excluded_target_ids(blackboard))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )
    piles = list_lootable(
        state,
        loot_mode=loot_mode,
        farm=None,
        origin=origin,
        exclude=skip,
        screen_only=False,
    )
    matched = [
        item
        for item in piles
        if any(_matches_corpse(item, corpse, now) for corpse in corpses)
    ]
    allowed = [int(item.track_id) for item in matched]
    if blackboard.current_item_id is not None:
        allowed.append(int(blackboard.current_item_id))
    _publish_corpse_ids(blackboard, allowed)
    if blackboard.current_item_id is not None:
        sticky = state.get_object(int(blackboard.current_item_id))
        if sticky is not None and any(
            _matches_corpse(sticky, corpse, now) for corpse in corpses
        ):
            status = tick_loot_item(state, blackboard, sticky, fresh=False)
            if status is Status.SUCCESS:
                return Status.SUCCESS
        else:
            clear_loot_hop(blackboard)
            blackboard.current_item_id = None
    if not matched:
        return None
    matched.sort(
        key=lambda item: (
            0 if is_adena(item) else 1,
            tile_distance_from_player(item),
            int(item.track_id),
        )
    )
    item = matched[0]
    begin_loot_item(blackboard, item.track_id, item)
    status = tick_loot_item(state, blackboard, item, fresh=True)
    if status is Status.SUCCESS:
        return Status.SUCCESS
    return None


def _abandon_proactive_target(state: "GameState", blackboard: "Blackboard") -> None:
    tid = blackboard.current_target_id
    if tid is None or _counter_sticky(state, blackboard):
        return
    try:
        blackboard.finish_kill_ids.discard(int(tid))
    except (TypeError, ValueError):
        pass
    blackboard.current_target_id = None
    clear_engage_state(blackboard)


def approach_counterattack(
    state: "GameState",
    blackboard: "Blackboard",
) -> Status | None:
    """Counterattack only, then loot that kill. Other mobs and piles wait.

    Attack clicks go through ``continue_or_start_combat``. Loot uses the
    hunt mode (adena only, every item, small-adena skip, weight adena).
    """
    from app._04_decision.behaviors.combat import object_world_cell
    from app._04_decision.mode_control import is_hp_zero

    blackboard.scratch[SCRATCH_APPROACH_HOLD_FIRE] = True
    if is_hp_zero(state):
        return None
    try:
        sync_attacks_me_force_targets(state)
    except Exception:
        pass
    _open_corpse_if_dead(state, blackboard)
    _abandon_proactive_target(state, blackboard)
    if _counter_sticky(state, blackboard):
        if blackboard.scratch.get(SCRATCH_APPROACH_SEEN_ITEMS) is None:
            blackboard.scratch[SCRATCH_APPROACH_SEEN_ITEMS] = _seen_item_ids(state)
        _remember_counter_cell(state, blackboard)
        result = continue_or_start_combat(state, blackboard, allow_new=False)
        if result is not None:
            return result
        if blackboard.current_target_id is not None and sticky_target_alive(
            state, int(blackboard.current_target_id)
        ):
            blackboard.current_goal = "combat"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.6,
                reason="approach counter hold",
            )
            return Status.SUCCESS
    attacker = nearest_attacks_me_force(
        state,
        exclude=excluded_target_ids(blackboard),
        origin=blackboard.world_origin,
    )
    if attacker is not None:
        blackboard.scratch[SCRATCH_APPROACH_SEEN_ITEMS] = _seen_item_ids(state)
        blackboard.scratch[SCRATCH_APPROACH_KILL_ID] = int(attacker.track_id)
        cell = object_world_cell(attacker)
        if cell is not None:
            blackboard.scratch[SCRATCH_APPROACH_KILL_CELL] = [
                int(cell[0]),
                int(cell[1]),
            ]
        return continue_or_start_combat(
            state,
            blackboard,
            allow_new=True,
            chosen=attacker,
            reason="attacks_me engage",
        )
    return _loot_counter_drops(state, blackboard)


def farm_loot_or_combat(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    restrict_to_farm: bool = True,
) -> Status | None:
    """Loot first; sticky kill and attacks_me force-engage beat loot.

    While this bot is the party leader, a monster hitting a mage member
    replaces the current fight. After that fight ends, a monster hitting
    any other member is taken before attacks-me, loot, and other help.
    1. A living sticky target is finished before any new loot click, unless
       a monster that has attacked me should take the lock. The sticky
       yields when it has not attacked me. A living sticky that has
       attacked me stays until that monster is dead or the lock is cleared.
       A lower known level does not take it. When the lock is empty, the
       lower known level is engaged. The previous target is not given up.
    2. Else force-engage a monster/summon whose AttackAction targets me
       this tick. A filtered species is included only while that row is
       live, in the field and in a dungeon. That target is ``finish_kill``
       for an allowed species. A filtered species is dropped when it stops
       attacking. Give-up / abandon still clear sticky. Loot waits while
       the sticky is held.
    3. Else pick up on-screen (or memory-near) ground items — loot is priority
       over nearby non-attacking threats (no 5-tile interrupt). A pile already
       chosen is finished before another pile or a new hunt target. Adena is
       preferred only when choosing the first pile.
    4. A missed loot cursor last tick yields to an attackable monster when
       there is nothing left to loot.
    5. After F4, stay on that pile until it leaves the world or the bag
       count rises. Do not hand the tick to patrol on a short timer.
       A failed press waits until the body is stopped, then retries or
       walks onto the tile again.
    6. Else engage the nearest on-screen monster.
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
    exclude = excluded_target_ids(blackboard)
    # Refresh synthetic attacks_me targets before sticky so list-missing
    # attackers (e.g. uncatalogued slime) stay bound until AttackAction ends.
    try:
        sync_attacks_me_force_targets(state)
    except Exception:
        pass
    sticky = rebind_sticky_target(state, blackboard)
    if prefer_attacked_me_sticky(state, blackboard, exclude=exclude):
        sticky = (
            state.get_object(blackboard.current_target_id)
            if blackboard.current_target_id is not None
            else None
        )
        event(
            "combat",
            "farm branch=attacked_me id=%s dist=%s",
            getattr(sticky, "track_id", None),
            _dist(sticky),
        )

    fight_open = sticky is not None or continue_sticky_combat(state, blackboard)
    if blackboard.scratch.get("party_help_open"):
        from app._06_party.assist import choose_help_target

        helped, help_src = choose_help_target(
            state,
            getattr(state, "last_party", None),
            origin=origin,
            current=sticky,
            fight_open=fight_open,
        )
        if help_src in ("mage_help", "member_under_attack") and helped is not None:
            threat_id = int(helped.track_id)
            if blackboard.current_target_id != threat_id:
                begin_engage(
                    state,
                    blackboard,
                    threat_id,
                    finish_kill=True,
                )
            branch = (
                "mage_help" if help_src == "mage_help" else "member_under_attack"
            )
            reason = (
                "mage member under attack"
                if help_src == "mage_help"
                else "party member under attack"
            )
            event(
                "combat",
                "farm branch=%s id=%s dist=%s",
                branch,
                threat_id,
                _dist(helped),
            )
            return continue_or_start_combat(
                state,
                blackboard,
                allow_new=True,
                chosen=helped,
                reason=reason,
            )

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
        from app._04_decision.clickgap import note_hold

        if rebind_sticky_target(state, blackboard) is not None:
            note_hold(
                f"sticky-silent:{tid}",
                f"sticky id={tid} rebind kept lock, no attack",
            )
            return None
        if continue_sticky_combat(state, blackboard):
            note_hold(
                f"sticky-silent:{tid}",
                f"sticky id={tid} lock kept, no attack",
            )
            return None

    attacker = nearest_attacks_me_force(
        state,
        exclude=exclude,
        origin=origin,
    )
    if attacker is not None:
        event(
            "combat",
            "farm branch=attacks_me id=%s dist=%s",
            attacker.track_id,
            _dist(attacker),
        )
        return continue_or_start_combat(
            state,
            blackboard,
            allow_new=True,
            chosen=attacker,
            reason="attacks_me engage",
        )

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
    if open_loot_pile(state, blackboard) is not None:
        event("loot", "farm branch=loot item_id=%s", blackboard.current_item_id)
        blackboard.current_goal = "loot"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.3,
            reason="loot until pickup",
        )
        return Status.SUCCESS

    if blackboard.scratch.get("party_help_open"):
        from app._06_party.assist import resolve_member_help_target

        helped = resolve_member_help_target(
            state,
            getattr(state, "last_party", None),
            origin=origin,
        )
        if helped is not None:
            event(
                "combat",
                "farm branch=party_help id=%s dist=%s",
                helped.track_id,
                _dist(helped),
            )
            return continue_or_start_combat(
                state,
                blackboard,
                allow_new=True,
                chosen=helped,
                reason="party member help",
            )

    loot_click_missed = bool(blackboard.scratch.pop("loot_click_failed", False))
    if loot_click_missed:
        enemy = nearest_attackable(
            state,
            exclude=exclude,
            origin=origin,
        )
        if enemy is not None:
            event(
                "combat",
                "farm branch=loot_miss_combat id=%s dist=%s",
                enemy.track_id,
                _dist(enemy),
            )
            return continue_or_start_combat(
                state, blackboard, allow_new=True, chosen=enemy
            )

    enemy = nearest_attackable(
        state,
        exclude=exclude,
        origin=origin,
        screen_only=True,
    )
    if enemy is not None:
        event(
            "combat",
            "farm branch=screen_combat id=%s dist=%s",
            enemy.track_id,
            _dist(enemy),
        )
        return continue_or_start_combat(
            state, blackboard, allow_new=True, screen_only=True, chosen=enemy
        )
    # When nothing passes screen/path, log nearest filter drops (1s throttle).
    path_details: list[tuple[str, str]] = []
    try:
        detail = describe_attackable_filter_skips(
            state,
            exclude=exclude,
            origin=origin,
            screen_only=True,
            check_path=True,
            path_details=path_details,
        )
    except Exception:
        detail = ""
        path_details = []
    if detail:
        now = time.time()
        last = float(blackboard.scratch.get("_screen_combat_skip_log_at") or 0.0)
        if now - last >= 1.0:
            blackboard.scratch["_screen_combat_skip_log_at"] = now
            event("combat", "screen_combat skips: %s", detail)
            from app.bot_log import get_logger

            combat_log = get_logger("combat")
            for info, segment in path_details:
                event("combat", "screen_combat skip %s", info)
                combat_log.debug("screen_combat skip %s", segment)
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

    exclude = excluded_target_ids(blackboard)
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
    "maybe_heal_mp_to_hp_at_tree",
    "emit_mp_potion",
    "player_is_poisoned",
    "player_has_curable_paralyze",
    "player_should_drink_antidote",
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

from app._04_decision.decide_spans import traced

apply_hp_actions = traced(apply_hp_actions)
farm_loot_or_combat = traced(farm_loot_or_combat)
continue_or_start_combat = traced(continue_or_start_combat)
continue_or_start_loot = traced(continue_or_start_loot)
