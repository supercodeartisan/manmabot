"""Push a live profile into the running decision config.

Start and a paused "update schedule" share this path. Account, character
class, the memory monitor, and the perception capture stay on the Start path.
"""
from __future__ import annotations

import copy
from typing import Any

from session.paths import overlay_farms_path, overlay_patrol_path, overlay_safe_path
from session.probes import load_selected_farm_rects


def route_identity(profile: Any) -> tuple:
    """Map, routine rows, and farm list. Stay seconds are not part of this.

    A change restarts the routine cursor and the in-farm timer. A stay-time
    or HP edit keeps the cursor and the elapsed timer.
    """
    from settings.farm_schedule import normalize_routine

    routine = normalize_routine(getattr(profile, "routine", None) or [])
    rows = tuple(
        (
            str(row.get("map_id") or ""),
            str(row.get("kind") or ""),
            tuple(str(name) for name in (row.get("selected_farms") or []) if str(name).strip()),
        )
        for row in routine
        if isinstance(row, dict)
    )
    farms = tuple(
        str(name) for name in (getattr(profile, "selected_farms", None) or []) if str(name).strip()
    )
    return (
        str(getattr(profile, "active_map", "") or ""),
        str(getattr(profile, "map_style", "normal") or "normal"),
        rows,
        farms,
    )


def install_profile_runtime(profile: Any, config: dict, *, navigation: bool) -> Any:
    """Copy profile fields into ``config`` and push the decision knobs.

    ``navigation=True`` also reloads the goal map's terrain, farms, and patrol
    (Start, or a paused update whose map, routine, or farms changed).
    Returns the navigation world origin when navigation ran, else None.
    """
    from app._03_world.constants import (
        configure_classification_thresholds,
        configure_species_filter,
        configure_species_level_overrides,
    )
    from app._03_world.space.battle_area import configure_battle_area
    from app._04_decision.configure import configure_action, configure_decision
    from app._04_decision.dungeon import set_dungeon_mode_override
    from app._04_decision.ground_loot import configure_ground_loot
    from app._04_decision.nav_config import configure_navigation, get_terrain_map, set_loot_mode
    from app._04_decision.patrol import configure_patrol_waypoints
    from session.probes import map_style_is_dungeon
    from settings.farm_schedule import stay_seconds_for
    from settings.hp_actions import to_engine_actions
    from settings.profile import DEFAULT_RETURN_WEIGHT_ABOVE, snap_return_weight_above

    if navigation:
        nav = dict(config.get("navigation") or {})
        nav["active_map"] = profile.active_map
        dungeon = map_style_is_dungeon(
            profile.active_map, getattr(profile, "map_style", None)
        )
        set_dungeon_mode_override(dungeon)
        if dungeon:
            nav.pop("farm_areas", None)
            nav.pop("farm_areas_file", None)
        else:
            overlay_farms = overlay_farms_path(profile.active_map)
            if overlay_farms.is_file():
                nav["farm_areas_file"] = str(overlay_farms)
            farms = load_selected_farm_rects(
                profile.selected_farms, map_id=profile.active_map
            )
            if farms:
                nav["farm_areas"] = farms
                nav.pop("farm_areas_file", None)
        overlay_safe = overlay_safe_path(profile.active_map)
        if overlay_safe.is_file():
            nav["safe_areas_file"] = str(overlay_safe)
        config["navigation"] = nav
    else:
        nav = dict(config.get("navigation") or {})

    configure_species_level_overrides(profile.species_levels)
    configure_species_filter(
        getattr(profile, "species_filter_mode", "blacklist"),
        profile.species_blacklist,
        getattr(profile, "species_whitelist", []),
    )

    decision_cfg = dict(config.get("decision") or {})
    hp = dict(decision_cfg.get("hp") or {})
    mp = dict(decision_cfg.get("mp") or {})
    farm = dict(decision_cfg.get("farm") or {})
    spells_cfg = dict(decision_cfg.get("spells") or {})
    hp["low_ratio"] = float(profile.hp_potion_ratio)
    hp["critical_ratio"] = float(profile.hp_escape_ratio)
    hp["recover_enabled"] = bool(getattr(profile, "hp_recover_enabled", True))
    hp["use_potion"] = bool(getattr(profile, "use_hp_potion", True))
    hp["use_heal"] = bool(getattr(profile, "use_heal", True))
    hp["actions"] = to_engine_actions(getattr(profile, "hp_actions", None))
    mp["low_ratio"] = float(profile.mp_escape_ratio)
    mp["escape_enabled"] = False
    mp["potion_ratio"] = float(getattr(profile, "mp_potion_ratio", 0.30))
    mp["recover_enabled"] = bool(getattr(profile, "mp_recover_enabled", False))
    mp["use_potion"] = bool(getattr(profile, "use_mp_potion", False))
    mp["spell_reserve_ratio"] = float(profile.spell_reserve_ratio)
    farm["duration_limit_s"] = float(profile.farm_rotate_s)
    stay_map = getattr(profile, "farm_stays_s", None) or {}
    farm["duration_limits_s"] = [
        stay_seconds_for(
            str(area.get("name") or ""),
            stay_map,
            profile.farm_rotate_s,
        )
        for area in (nav.get("farm_areas") or [])
        if isinstance(area, dict)
    ]
    farm["loot_adena_weight_ratio"] = float(profile.loot_adena_weight_ratio)
    farm["ignore_small_adena"] = bool(getattr(profile, "ignore_small_adena", False))
    farm["ignore_small_adena_qty"] = int(getattr(profile, "ignore_small_adena_qty", 10))
    farm["area_empty"] = bool(getattr(profile, "area_empty", False))
    farm["area_empty_seconds"] = int(getattr(profile, "area_empty_seconds", 60))
    farm["area_low_yield"] = bool(getattr(profile, "area_low_yield", False))
    farm["area_low_yield_adena"] = int(getattr(profile, "area_low_yield_adena", 1000))
    farm["area_low_yield_seconds"] = int(getattr(profile, "area_low_yield_seconds", 180))
    farm["area_players"] = bool(getattr(profile, "area_players", False))
    farm["area_player_count"] = int(getattr(profile, "area_player_count", 3))
    farm["approach_no_engage"] = bool(getattr(profile, "approach_no_engage", False))
    returning = dict(decision_cfg.get("return") or {})
    returning["hp_enabled"] = bool(getattr(profile, "return_hp_enabled", True))
    returning["hp_ratio"] = float(getattr(profile, "return_hp_ratio", 0.30))
    returning["mp_enabled"] = bool(getattr(profile, "return_mp_enabled", True))
    returning["mp_ratio"] = float(getattr(profile, "return_mp_ratio", 0.15))
    returning["idle_enabled"] = bool(getattr(profile, "return_idle_enabled", False))
    returning["idle_seconds"] = float(getattr(profile, "return_idle_seconds", 60.0))
    returning["hunt_map"] = str(profile.active_map or "talking_island")
    decision_cfg["return"] = returning
    tree_cfg = dict(decision_cfg.get("mother_tree") or {})
    tree_cfg["hp_to_mp_enabled"] = bool(
        getattr(profile, "mother_tree_hp_to_mp_enabled", True)
    )
    tree_cfg["hp_to_mp_hp_ratio"] = float(
        getattr(profile, "mother_tree_hp_to_mp_hp_ratio", 0.85)
    )
    tree_cfg["hp_to_mp_mp_ratio"] = float(
        getattr(profile, "mother_tree_hp_to_mp_mp_ratio", 0.80)
    )
    tree_cfg["heal_enabled"] = bool(getattr(profile, "mother_tree_heal_enabled", True))
    tree_cfg["heal_hp_ratio"] = float(getattr(profile, "mother_tree_heal_hp_ratio", 0.40))
    tree_cfg["heal_mp_ratio"] = float(getattr(profile, "mother_tree_heal_mp_ratio", 0.80))
    decision_cfg["mother_tree"] = tree_cfg
    teleport_cfg = dict(decision_cfg.get("teleport") or {})
    teleport_cfg["enabled"] = bool(getattr(profile, "random_teleport_enabled", False))
    teleport_cfg["on_player"] = bool(getattr(profile, "teleport_on_player", False))
    teleport_cfg["when_surrounded"] = bool(
        getattr(profile, "teleport_when_surrounded", False)
    )
    teleport_cfg["surround_count"] = max(
        2, int(getattr(profile, "teleport_surround_count", 10) or 10)
    )
    decision_cfg["teleport"] = teleport_cfg
    death_cfg = dict(decision_cfg.get("death") or {})
    death_cfg["resurrect"] = bool(getattr(profile, "resurrect_if_dead", True))
    decision_cfg["death"] = death_cfg
    combat_cfg = dict(decision_cfg.get("combat") or {})
    combat_cfg["attack_jitter"] = bool(getattr(profile, "attack_jitter", False))
    combat_cfg["attack_jitter_ms"] = max(
        10, min(50, int(getattr(profile, "attack_jitter_ms", 35)))
    )
    combat_cfg["target_delay"] = bool(getattr(profile, "target_delay", False))
    combat_cfg["target_delay_min_ms"] = max(
        10, min(50, int(getattr(profile, "target_delay_min_ms", 20)))
    )
    combat_cfg["target_delay_max_ms"] = max(
        10, min(50, int(getattr(profile, "target_delay_max_ms", 50)))
    )
    combat_cfg["abandon_same"] = False
    combat_cfg["use_antidote_potion"] = bool(
        getattr(profile, "use_antidote_potion", False)
    )
    combat_cfg["antidote_auto"] = combat_cfg["use_antidote_potion"]
    decision_cfg["combat"] = combat_cfg
    shop = dict(decision_cfg.get("shop") or {})
    shop["arrow_qty"] = int(profile.arrow_buy_qty)
    shop["silver_arrow_qty"] = int(getattr(profile, "silver_arrow_buy_qty", 200))
    shop["hp_potion_qty"] = int(getattr(profile, "hp_potion_buy_qty", 10))
    shop["depoison_qty"] = int(getattr(profile, "depoison_buy_qty", 1))
    shop["buy_normal_arrows"] = bool(getattr(profile, "buy_normal_arrows", False))
    shop["buy_silver_arrows"] = bool(getattr(profile, "buy_silver_arrows", True))
    if shop["buy_normal_arrows"] and shop["buy_silver_arrows"]:
        shop["buy_silver_arrows"] = False
    shop["restock_potions"] = bool(getattr(profile, "restock_potions", True))
    shop["store_after_sell"] = bool(getattr(profile, "store_after_sell", True))
    shop["buy_depoison"] = bool(getattr(profile, "buy_depoison", False))
    shop_locale = ""
    try:
        from settings.accounts import AccountStore

        account = AccountStore().get(profile.selected_account_id or "")
        if account is not None and getattr(account, "locale", None):
            shop_locale = str(account.locale).strip().lower()
    except Exception:
        shop_locale = ""
    if not shop_locale:
        shop_locale = str(getattr(profile, "shop_locale", "") or "").strip().lower()
    if not shop_locale:
        shop_locale = str(profile.game_language or "ko")
    shop["shop_locale"] = "zh" if shop_locale.startswith("zh") else "ko"
    shop["hp_potion_npc"] = str(getattr(profile, "hp_potion_npc", "") or "")
    shop["return_potion_enabled"] = bool(
        getattr(profile, "return_potion_enabled", True)
    )
    shop["return_potion_count"] = int(getattr(profile, "return_potion_count", 0))
    shop["return_arrow_enabled"] = bool(
        getattr(profile, "return_arrow_enabled", True)
    )
    shop["return_arrow_count"] = int(getattr(profile, "return_arrow_count", 300))
    shop["return_depoison_enabled"] = bool(
        getattr(profile, "return_depoison_enabled", False)
    )
    shop["return_depoison_count"] = int(getattr(profile, "return_depoison_count", 1))
    shop["return_weight_enabled"] = bool(
        getattr(profile, "return_weight_enabled", True)
    )
    weight_pct = snap_return_weight_above(
        getattr(profile, "return_weight_above", DEFAULT_RETURN_WEIGHT_ABOVE),
        DEFAULT_RETURN_WEIGHT_ABOVE,
    )
    shop["sell_weight_ratio"] = float(weight_pct) / 100.0
    sell_mode = str(
        getattr(profile, "sell_mode", "sell_except_keep") or "sell_except_keep"
    ).strip().lower()
    shop["sell_mode"] = (
        "sell_only_garbage"
        if sell_mode in ("sell_only_garbage", "only_garbage", "garbage")
        else "sell_except_keep"
    )
    shop["potion_suppress_s"] = 600.0
    spells_cfg["heal_until_hp_ratio"] = float(profile.heal_until_hp_ratio)
    spells_cfg["use_haste_potion"] = bool(getattr(profile, "use_haste_potion", False))
    spells_cfg["haste_potion_item"] = str(
        getattr(profile, "haste_potion_item", "") or ""
    ).strip()
    spells_cfg["antidote_potion_item"] = str(
        getattr(profile, "antidote_potion_item", "") or ""
    ).strip()
    spells_cfg["auto_buffs"] = [
        row.as_dict() if hasattr(row, "as_dict") else row
        for row in (getattr(profile, "auto_buff_plan", ()) or ())
    ]
    spells_cfg["solo_mage_attacks"] = [
        row.as_dict() if hasattr(row, "as_dict") else row
        for row in (getattr(profile, "solo_mage_attack_plan", ()) or ())
    ]
    decision_cfg["hp"] = hp
    decision_cfg["mp"] = mp
    decision_cfg["farm"] = farm
    decision_cfg["shop"] = shop
    decision_cfg["spells"] = spells_cfg
    decision_cfg["game_language"] = profile.game_language
    config["decision"] = decision_cfg

    configure_battle_area(config)
    configure_classification_thresholds(config)
    configure_decision(config)
    configure_action(config)
    set_loot_mode(profile.loot_mode)
    configure_ground_loot(profile.item_pickup_mode, profile.item_pickup_names)

    if not navigation:
        return None

    world_origin = configure_navigation(config)
    overlay_patrol = overlay_patrol_path(profile.active_map)
    if overlay_patrol.is_file():
        configure_patrol_waypoints(path=overlay_patrol, terrain=get_terrain_map())
    return world_origin


def restart_paused_routine(profile: Any, config: dict, blackboard: Any) -> None:
    """Drop the in-flight route and arm the profile routine. Keeps the pose."""
    from app._04_decision.farm_time import reset_farm_timer
    from app._04_decision.world_nav.hooks import (
        begin_world_nav,
        clear_world_nav_run,
        init_routine_on_blackboard,
    )
    from session.world_nav_inject import install_world_nav_overlays
    from settings.farm_schedule import normalize_routine

    clear_world_nav_run(blackboard)
    routine_rows = normalize_routine(getattr(profile, "routine", None) or [])
    fallback_map = str(profile.active_map or "talking_island")
    install_world_nav_overlays(
        blackboard,
        routine_rows=routine_rows,
        fallback_map=fallback_map,
    )
    init_routine_on_blackboard(
        blackboard,
        routine=routine_rows,
        fallback_map=fallback_map,
        selected_farms=list(profile.selected_farms or []),
        farm_stays_s=dict(getattr(profile, "farm_stays_s", {}) or {}),
        entries_normalized=True,
    )
    blackboard.scratch["runtime_config"] = config
    begin_world_nav(blackboard, "paused_settings")
    reset_farm_timer(blackboard)


def publish_paused_task(controller: Any, profile: Any, task: Any) -> str:
    """Copy ``task`` onto ``profile`` while the worker is paused.

    Returns ``applied``, ``applied_keep_identity``, or ``not_paused``.
    Character class and the selected account are left as they were at Start.
    """
    from session.bot_controller import RunState
    from settings.profile import save_profile
    from settings.task_runtime import apply_runtime_settings

    kept_character = str(getattr(profile, "character", "") or "")
    kept_account = getattr(profile, "selected_account_id", None)
    task_character = str(getattr(task, "character", "") or "")
    task_account = getattr(task, "account_id", None) or None
    identity_held = False
    if task_character in ("royal", "knight", "elf", "mage") and task_character != kept_character:
        identity_held = True
    if task_account and str(task_account) != str(kept_account or ""):
        identity_held = True

    with controller._lock:
        thread = getattr(controller, "_thread", None)
        if controller.state != RunState.PAUSED:
            return "not_paused"
        if thread is None or not thread.is_alive():
            return "not_paused"
        apply_runtime_settings(task, profile)
        profile.character = kept_character
        profile.selected_account_id = kept_account
        controller._settings_epoch += 1
    try:
        save_profile(profile)
    except Exception:
        pass
    return "applied_keep_identity" if identity_held else "applied"


def snapshot_profile(profile: Any) -> Any:
    """Frozen profile the worker can read while the UI edits the live one."""
    return copy.deepcopy(profile)
