"""Apply ``decision`` / ``farming`` config sections to live module knobs."""
from __future__ import annotations

from typing import Any, Optional


def _pair(value: Any, fallback: tuple) -> tuple:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        a, b = value[0], value[1]
        if isinstance(fallback[0], int) and isinstance(fallback[1], int):
            return int(a), int(b)
        return float(a), float(b)
    return fallback


def configure_decision(config: Optional[dict[str, Any]] = None) -> None:
    """Load HP/MP/farm/combat/death/search knobs from ``config['decision']``."""
    from app._03_world import constants as world_constants
    from app._03_world import world_coords as wcs
    from app._04_decision import farm_area
    from app._04_decision import mode_control
    from app._04_decision import player_mode as pm
    from app._04_decision.behaviors import combat as combat_beh
    from app._04_decision.behaviors import farm_management
    from app._04_decision.behaviors import mode_ticks
    from app._04_decision.behaviors import navigation as nav_beh
    from app._04_decision.behaviors import search as search_beh
    from app._04_decision import target_selector

    root = (config or {}).get("decision") or {}
    hp = root.get("hp") or {}
    mp = root.get("mp") or {}
    farm = root.get("farm") or {}
    shop = root.get("shop") or {}
    travel = root.get("travel") or {}
    combat = root.get("combat") or {}
    death = root.get("death") or {}
    search = root.get("search") or {}
    nav = (config or {}).get("navigation") or {}

    if "critical_ratio" in hp:
        pm.HP_CRITICAL_RATIO = float(hp["critical_ratio"])
    if "low_ratio" in hp:
        pm.HP_LOW_RATIO = float(hp["low_ratio"])
    if "recover_enabled" in hp:
        pm.HP_RECOVER_ENABLED = bool(hp["recover_enabled"])
    if "use_potion" in hp:
        pm.USE_HP_POTION = bool(hp["use_potion"])
    if "use_heal" in hp:
        pm.USE_HEAL = bool(hp["use_heal"])
    if "almost_full_ratio" in hp:
        pm.HP_ALMOST_FULL_RATIO = float(hp["almost_full_ratio"])
    if "full_ratio" in hp:
        pm.HP_FULL_RATIO = float(hp["full_ratio"])
    if "passive_recover_ratio" in hp:
        pm.HP_PASSIVE_RECOVER_RATIO = max(
            0.20, min(0.90, float(hp["passive_recover_ratio"]))
        )
    if "idle_emergency_ratio" in hp:
        pm.HP_IDLE_EMERGENCY_RATIO = float(hp["idle_emergency_ratio"])
    if "spike_window_s" in hp:
        pm.HP_SPIKE_WINDOW_S = max(0.3, float(hp["spike_window_s"]))
    if "spike_drop" in hp:
        pm.HP_SPIKE_DROP = max(0.08, min(0.6, float(hp["spike_drop"])))

    returning = root.get("return") or {}
    if "hp_enabled" in returning:
        pm.RETURN_HP_ENABLED = bool(returning["hp_enabled"])
    if "hp_ratio" in returning:
        pm.RETURN_HP_RATIO = float(returning["hp_ratio"])
    if "mp_enabled" in returning:
        pm.RETURN_MP_ENABLED = bool(returning["mp_enabled"])
    if "mp_ratio" in returning:
        pm.RETURN_MP_RATIO = float(returning["mp_ratio"])
    if "idle_enabled" in returning:
        pm.RETURN_IDLE_ENABLED = bool(returning["idle_enabled"])
    if "idle_seconds" in returning:
        pm.RETURN_IDLE_SECONDS = max(1.0, float(returning["idle_seconds"]))
    if "hunt_map" in returning:
        mid = str(returning["hunt_map"] or "").strip()
        if mid:
            pm.HUNT_MAP_ID = mid

    teleport = root.get("teleport") or {}
    if "enabled" in teleport:
        pm.RANDOM_TELEPORT_ENABLED = bool(teleport["enabled"])
    if "on_player" in teleport:
        pm.TELEPORT_ON_PLAYER = bool(teleport["on_player"])
    if "when_surrounded" in teleport:
        pm.TELEPORT_WHEN_SURROUNDED = bool(teleport["when_surrounded"])
    if "surround_count" in teleport:
        pm.SURROUND_MONSTER_COUNT = max(2, int(teleport["surround_count"]))

    if "escape_enabled" in mp:
        pm.MP_ESCAPE_ENABLED = bool(mp["escape_enabled"])
    if "low_ratio" in mp:
        pm.MP_LOW_RATIO = float(mp["low_ratio"])
    if "potion_ratio" in mp:
        pm.MP_POTION_RATIO = float(mp["potion_ratio"])
    if "recover_enabled" in mp:
        pm.MP_RECOVER_ENABLED = bool(mp["recover_enabled"])
    if "use_potion" in mp:
        pm.USE_MP_POTION = bool(mp["use_potion"])
    if "recovered_ratio" in mp:
        pm.MP_RECOVERED_RATIO = float(mp["recovered_ratio"])
    if "spell_reserve_ratio" in mp:
        from app._04_decision import spells as spell_mod

        spell_mod.SPELL_MANA_RESERVE_RATIO = float(mp["spell_reserve_ratio"])

    spells_cfg = root.get("spells") or {}
    if spells_cfg:
        from app._04_decision import spells as spell_mod

        if "buff_cooldown_s" in spells_cfg:
            spell_mod.BUFF_COOLDOWN_S = float(spells_cfg["buff_cooldown_s"])
        if "buff_reuse_s" in spells_cfg:
            spell_mod.BUFF_COOLDOWN_S = float(spells_cfg["buff_reuse_s"])
        if "buff_start_light_s" in spells_cfg:
            spell_mod.BUFF_START_DELAY_S[spell_mod.BUFF_LIGHT] = float(
                spells_cfg["buff_start_light_s"]
            )
        if "buff_start_power_s" in spells_cfg:
            spell_mod.BUFF_START_DELAY_S[spell_mod.BUFF_POWER] = float(
                spells_cfg["buff_start_power_s"]
            )
        if "magic_cooldown_s" in spells_cfg:
            from app._05_action import spell_box as spell_box_mod

            spell_box_mod.MAGIC_COOLDOWN_S = float(spells_cfg["magic_cooldown_s"])
        if "unstick_teleport_cooldown_s" in spells_cfg:
            spell_mod.UNSTICK_TELEPORT_COOLDOWN_S = float(
                spells_cfg["unstick_teleport_cooldown_s"]
            )
        if "heal_until_hp_ratio" in spells_cfg:
            spell_mod.HEAL_UNTIL_HP_RATIO = float(spells_cfg["heal_until_hp_ratio"])

    elf_cfg = root.get("elf") or {}
    if "mother_tree" in elf_cfg:
        pm.ELF_MOTHER_TREE = bool(elf_cfg["mother_tree"])

    from app._04_decision.hp_actions import normalize_hp_actions

    explicit_actions = hp.get("actions")
    pm.HP_ACTIONS = normalize_hp_actions(explicit_actions)
    if explicit_actions is not None:
        retreat_thresholds = [
            float(row["hp_below"])
            for row in pm.HP_ACTIONS
            if row.get("enabled")
            and row.get("id") in ("mother_tree", "teleport", "safe_zone")
        ]
        if retreat_thresholds:
            pm.HP_CRITICAL_RATIO = min(retreat_thresholds)
        from app._04_decision.hp_actions import is_item_action

        inplace_thresholds = [
            float(row["hp_below"])
            for row in pm.HP_ACTIONS
            if row.get("enabled")
            and (
                row.get("id") == "heal"
                or is_item_action(str(row.get("id") or ""))
            )
        ]
        if inplace_thresholds:
            pm.HP_LOW_RATIO = min(inplace_thresholds)
        potion_on = False
        for row in pm.HP_ACTIONS:
            if row.get("id") == "heal":
                pm.USE_HEAL = bool(row.get("enabled"))
            if is_item_action(str(row.get("id") or "")) and row.get("enabled"):
                potion_on = True
        pm.USE_HP_POTION = potion_on
        elf_from_actions = next(
            (row for row in pm.HP_ACTIONS if row.get("id") == "mother_tree"),
            None,
        )
        if elf_from_actions is not None:
            pm.ELF_MOTHER_TREE = bool(elf_from_actions.get("enabled"))

    if "loot_adena_weight_ratio" in farm:
        pm.LOOT_ADENA_WEIGHT_RATIO = float(farm["loot_adena_weight_ratio"])
    if "loot_max_tiles" in farm:
        pm.LOOT_MAX_TILES = int(farm["loot_max_tiles"])
    if "loot_keep_tiles" in farm:
        pm.LOOT_KEEP_TILES = max(1, int(farm["loot_keep_tiles"]))
    if "loot_pickup_settle_s" in farm:
        pm.LOOT_PICKUP_SETTLE_S = max(0.0, float(farm["loot_pickup_settle_s"]))
    if "loot_await_gone_s" in farm:
        pm.LOOT_AWAIT_GONE_S = max(0.0, float(farm["loot_await_gone_s"]))
    if "loot_hop_arrive_tiles" in farm:
        pm.LOOT_HOP_ARRIVE_TILES = max(0, int(farm["loot_hop_arrive_tiles"]))
    if "loot_cursor_search_tiles" in farm:
        pm.LOOT_CURSOR_SEARCH_TILES = max(
            0.0, float(farm["loot_cursor_search_tiles"])
        )
    if "loot_danger_tiles" in farm:
        pm.LOOT_DANGER_TILES = max(1, int(farm["loot_danger_tiles"]))
    if "near_monster_width_tiles" in farm:
        pm.NEAR_MONSTER_WIDTH_TILES = max(1, int(farm["near_monster_width_tiles"]))
    if "near_monster_height_tiles" in farm:
        pm.NEAR_MONSTER_HEIGHT_TILES = max(1, int(farm["near_monster_height_tiles"]))
    if "arrive_tiles" in farm:
        farm_area.ARRIVE_TILES = int(farm["arrive_tiles"])
    if "search_leg_ticks" in farm:
        search_beh.LEG_TICKS = int(farm["search_leg_ticks"])
    if "duration_limit_s" in farm or "duration_limits_s" in farm:
        from app._04_decision import farm_time

        if "duration_limit_s" in farm:
            dur = float(farm["duration_limit_s"])
            farm_time.FARM_DURATION_LIMIT = dur
            mode_ticks.FARM_DURATION_LIMIT = dur
            farm_management.FARM_DURATION_LIMIT = dur
        limits_raw = farm.get("duration_limits_s")
        if isinstance(limits_raw, (list, tuple)):
            farm_time.FARM_DURATION_LIMITS = [
                max(1.0, float(item)) for item in limits_raw
            ]
        else:
            farm_time.FARM_DURATION_LIMITS = []
    if "area_empty" in farm:
        pm.AREA_EMPTY_ENABLED = bool(farm["area_empty"])
    if "area_empty_seconds" in farm:
        pm.AREA_EMPTY_SECONDS = max(1.0, float(farm["area_empty_seconds"]))
    if "area_low_yield" in farm:
        pm.AREA_LOW_YIELD_ENABLED = bool(farm["area_low_yield"])
    if "area_low_yield_adena" in farm:
        pm.AREA_LOW_YIELD_ADENA = max(1, int(farm["area_low_yield_adena"]))
    if "area_low_yield_seconds" in farm:
        pm.AREA_LOW_YIELD_SECONDS = max(1.0, float(farm["area_low_yield_seconds"]))
    if "area_players" in farm:
        pm.AREA_PLAYERS_ENABLED = bool(farm["area_players"])
    if "area_player_count" in farm:
        pm.AREA_PLAYER_COUNT = max(1, int(farm["area_player_count"]))

    if shop:
        from app._04_decision import shops as shops_mod

        if "arrow_qty" in shop:
            shops_mod.ARROW_BUY_QTY = max(1, min(999, int(shop["arrow_qty"])))
        if "silver_arrow_qty" in shop:
            shops_mod.SILVER_ARROW_BUY_QTY = max(
                1, min(999, int(shop["silver_arrow_qty"]))
            )
        if "hp_potion_qty" in shop:
            shops_mod.HP_POTION_BUY_QTY = max(
                1, min(999, int(shop["hp_potion_qty"]))
            )
        if "depoison_qty" in shop:
            shops_mod.DEPOISON_BUY_QTY = max(
                1, min(999, int(shop["depoison_qty"]))
            )
        if "buy_normal_arrows" in shop:
            shops_mod.BUY_NORMAL_ARROWS = bool(shop["buy_normal_arrows"])
        if "buy_silver_arrows" in shop:
            shops_mod.BUY_SILVER_ARROWS = bool(shop["buy_silver_arrows"])
        # Mutex: prefer silver only when normal is off.
        if shops_mod.BUY_NORMAL_ARROWS and shops_mod.BUY_SILVER_ARROWS:
            shops_mod.BUY_SILVER_ARROWS = False
        if "restock_potions" in shop:
            shops_mod.RESTOCK_POTIONS = bool(shop["restock_potions"])
        if "buy_depoison" in shop:
            shops_mod.BUY_DEPOISON = bool(shop["buy_depoison"])
        if "return_potion_enabled" in shop:
            shops_mod.RETURN_POTION_ENABLED = bool(shop["return_potion_enabled"])
        if "return_potion_count" in shop:
            shops_mod.RETURN_POTION_COUNT = max(0, int(shop["return_potion_count"]))
        if "return_arrow_enabled" in shop:
            shops_mod.RETURN_ARROW_ENABLED = bool(shop["return_arrow_enabled"])
        if "return_arrow_count" in shop:
            shops_mod.RETURN_ARROW_COUNT = max(0, int(shop["return_arrow_count"]))
        if "return_depoison_enabled" in shop:
            shops_mod.RETURN_DEPOISON_ENABLED = bool(shop["return_depoison_enabled"])
        if "return_depoison_count" in shop:
            shops_mod.RETURN_DEPOISON_COUNT = max(0, int(shop["return_depoison_count"]))
        if "return_weight_enabled" in shop:
            shops_mod.RETURN_WEIGHT_ENABLED = bool(shop["return_weight_enabled"])
        if "shop_locale" in shop:
            shops_mod.SHOP_LOCALE = shops_mod.normalize_shop_locale(shop["shop_locale"])
        if "hp_potion_npc" in shop:
            shops_mod.HP_POTION_NPC = shops_mod.normalize_hp_potion_npc(
                shop["hp_potion_npc"]
            )
        if "sell_mode" in shop:
            shops_mod.SELL_MODE = shops_mod.normalize_sell_mode(shop["sell_mode"])
        if "sell_weight_ratio" in shop:
            shops_mod.SELL_WEIGHT_RATIO = max(
                0.0, min(1.0, float(shop["sell_weight_ratio"]))
            )
        if "potion_suppress_s" in shop:
            shops_mod.POTION_SUPPRESS_S = max(0.0, float(shop["potion_suppress_s"]))
        if "arrive_tiles" in shop:
            shops_mod.SHOP_ARRIVE_TILES = max(1, int(shop["arrive_tiles"]))
        if "npc_search_px" in shop:
            shops_mod.SHOP_NPC_SEARCH_PX = max(1, int(shop["npc_search_px"]))
        if "ui_ref_w" in shop:
            shops_mod.SHOP_UI_REF_W = float(shop["ui_ref_w"])
        if "ui_ref_h" in shop:
            shops_mod.SHOP_UI_REF_H = float(shop["ui_ref_h"])
        if "buy_tab_px" in shop:
            shops_mod.SHOP_BUY_TAB_PX = _pair(shop["buy_tab_px"], shops_mod.SHOP_BUY_TAB_PX)
        if "arrow_row_px" in shop:
            shops_mod.SHOP_ARROW_ROW_PX = _pair(
                shop["arrow_row_px"], shops_mod.SHOP_ARROW_ROW_PX
            )
        if "confirm_px" in shop:
            shops_mod.SHOP_CONFIRM_PX = _pair(shop["confirm_px"], shops_mod.SHOP_CONFIRM_PX)

    from app._04_decision.game_language import set_game_language

    set_game_language(root.get("game_language"))

    if "stuck_ticks" in travel:
        pm.TRAVEL_STUCK_TICKS = int(travel["stuck_ticks"])
    if "stuck_seconds" in travel:
        pm.TRAVEL_STUCK_SECONDS = float(travel["stuck_seconds"])
    if "unstick_seconds" in travel:
        pm.TRAVEL_UNSTICK_SECONDS = float(travel["unstick_seconds"])
    if "unstick_burst_count" in travel:
        pm.UNSTICK_BURST_COUNT = max(1, int(travel["unstick_burst_count"]))
    if "unstick_burst_window_s" in travel:
        pm.UNSTICK_BURST_WINDOW_S = max(1.0, float(travel["unstick_burst_window_s"]))
    if "confined_tiles" in travel:
        pm.UNSTICK_CONFINED_TILES = max(1, int(travel["confined_tiles"]))
    if "confined_seconds" in travel:
        pm.UNSTICK_CONFINED_SECONDS = max(1.0, float(travel["confined_seconds"]))
    if "reclick_s" in travel:
        pm.TRAVEL_RECLICK_SECONDS = float(travel["reclick_s"])
    if "unstick_radius" in travel:
        pm.TRAVEL_UNSTICK_RADIUS = int(travel["unstick_radius"])
    if "unstick_inner_radius" in travel:
        pm.TRAVEL_UNSTICK_INNER_RADIUS = int(travel["unstick_inner_radius"])
    if "cursor_fallback_radius" in travel:
        pm.TRAVEL_CURSOR_FALLBACK_RADIUS = int(travel["cursor_fallback_radius"])
    if "max_attackable" in travel:
        pm.TRAVEL_MAX_ATTACKABLE = int(travel["max_attackable"])

    if "max_engage_seconds" in combat:
        combat_beh.MAX_ENGAGE_SECONDS = float(combat["max_engage_seconds"])
    # Legacy tick-based key → seconds (best-effort for old configs).
    elif "max_engage_ticks" in combat:
        combat_beh.MAX_ENGAGE_SECONDS = float(combat["max_engage_ticks"])
    if "give_up_cooldown_ticks" in combat:
        combat_beh.GIVE_UP_COOLDOWN_TICKS = int(combat["give_up_cooldown_ticks"])
    if "max_missed_frames" in combat:
        target_selector.MAX_MISSED_FRAMES = int(combat["max_missed_frames"])
    if "mage_spell_range" in combat:
        world_constants.MAGE_SPELL_RANGE = int(combat["mage_spell_range"])
    if "attack_click_tiles" in combat:
        pm.ATTACK_CLICK_TILES = max(1, int(combat["attack_click_tiles"]))
    if "sticky_loot_hold_tiles" in combat:
        pm.STICKY_LOOT_HOLD_TILES = max(0, int(combat["sticky_loot_hold_tiles"]))
    if "cursor_search_tiles" in combat:
        pm.ATTACK_CURSOR_SEARCH_TILES = max(0.0, float(combat["cursor_search_tiles"]))
    if "blocked_unstick_seconds" in combat:
        pm.COMBAT_BLOCKED_UNSTICK_SECONDS = max(
            0.5, float(combat["blocked_unstick_seconds"])
        )
    if "blocked_unstick_radius" in combat:
        pm.COMBAT_BLOCKED_UNSTICK_RADIUS = max(
            1, int(combat["blocked_unstick_radius"])
        )
    if "attack_jitter" in combat:
        from app._05_action import humanize as hz

        hz.ATTACK_JITTER_ENABLED = bool(combat["attack_jitter"])
    if "attack_jitter_ms" in combat:
        from app._05_action import humanize as hz

        hz.ATTACK_JITTER_MS = max(10, min(50, int(combat["attack_jitter_ms"])))
    if "target_delay" in combat:
        pm.TARGET_DELAY_ENABLED = bool(combat["target_delay"])
    if "target_delay_min_ms" in combat:
        pm.TARGET_DELAY_MIN_MS = max(10, min(50, int(combat["target_delay_min_ms"])))
    if "target_delay_max_ms" in combat:
        pm.TARGET_DELAY_MAX_MS = max(10, min(50, int(combat["target_delay_max_ms"])))
    if pm.TARGET_DELAY_MAX_MS < pm.TARGET_DELAY_MIN_MS:
        pm.TARGET_DELAY_MAX_MS = pm.TARGET_DELAY_MIN_MS
    if "abandon_same" in combat:
        combat_beh.ABANDON_SAME_ENABLED = bool(combat["abandon_same"])
    if "abandon_seconds" in combat:
        combat_beh.ABANDON_SECONDS = max(1.0, float(combat["abandon_seconds"]))
    if "antidote_auto" in combat:
        pm.ANTIDOTE_AUTO = bool(combat["antidote_auto"])

    if "confirm_seconds" in death:
        mode_control.DEATH_CONFIRM_SECONDS = float(death["confirm_seconds"])
    if "resurrect" in death:
        pm.RESURRECT_IF_DEAD = bool(death["resurrect"])
    if "respawn_cooldown_s" in death:
        mode_control.RESPAWN_CLICK_COOLDOWN = float(death["respawn_cooldown_s"])
    if "respawn_ref_w" in death:
        mode_control.RESPAWN_REF_W = float(death["respawn_ref_w"])
    if "respawn_ref_h" in death:
        mode_control.RESPAWN_REF_H = float(death["respawn_ref_h"])
    if "respawn_px_x" in death:
        mode_control.RESPAWN_PX_X = float(death["respawn_px_x"])
    if "respawn_px_y" in death:
        mode_control.RESPAWN_PX_Y = float(death["respawn_px_y"])
    if "respawn_jitter_px" in death:
        mode_control.RESPAWN_PX_JITTER = float(death["respawn_jitter_px"])

    if "tile_dist_min" in search:
        nav_beh.TILE_DIST_MIN = int(search["tile_dist_min"])
    if "tile_dist_max" in search:
        nav_beh.TILE_DIST_MAX = int(search["tile_dist_max"])
    if "bearing_persist_farm_min" in search:
        nav_beh.BEARING_PERSIST_FARM_MIN = int(search["bearing_persist_farm_min"])
    if "bearing_persist_farm_max" in search:
        nav_beh.BEARING_PERSIST_FARM_MAX = int(search["bearing_persist_farm_max"])

    if "click_path_slack" in nav:
        wcs.CLICK_PATH_SLACK = int(nav["click_path_slack"])
    if "click_sum_min" in nav:
        wcs.CLICK_SUM_MIN = int(nav["click_sum_min"])
    if "click_sum_max" in nav:
        wcs.CLICK_SUM_MAX = int(nav["click_sum_max"])
    if "click_diff_min" in nav:
        wcs.CLICK_DIFF_MIN = int(nav["click_diff_min"])
    if "click_diff_max" in nav:
        wcs.CLICK_DIFF_MAX = int(nav["click_diff_max"])


def configure_action(config: Optional[dict[str, Any]] = None) -> None:
    """Load humanize timings and Esc-dismiss flag from ``config['action']``."""
    from app._05_action import humanize as hz

    section = (config or {}).get("action") or {}

    def _set_range(name: str, attr: str) -> None:
        if name not in section:
            return
        setattr(hz, attr, _pair(section[name], getattr(hz, attr)))

    _set_range("aim_jitter_px", "AIM_JITTER_PX")
    _set_range("move_steps", "MOVE_STEPS")
    _set_range("move_step_sleep", "MOVE_STEP_SLEEP")
    _set_range("move_curve_fraction", "MOVE_CURVE_FRACTION")
    _set_range("key_hold", "KEY_HOLD")
    _set_range("mage_key_hold", "MAGE_KEY_HOLD")
    _set_range("mage_pre_click_gap", "MAGE_PRE_CLICK_GAP")
    _set_range("heal_double_gap", "HEAL_DOUBLE_GAP")
    _set_range("mage_cast_interval", "MAGE_CAST_INTERVAL")
    _set_range("elf_attack_interval", "ELF_ATTACK_INTERVAL")
    if "stop_before_attack" in section:
        hz.ATTACK_STOP_ENABLED = bool(section["stop_before_attack"])
    if "stop_before_attack_wait_s" in section:
        hz.ATTACK_STOP_WAIT_S = max(0.0, float(section["stop_before_attack_wait_s"]))
    _set_range("loot_click_interval", "LOOT_CLICK_INTERVAL")
    _set_range("box_switch_wait", "BOX_SWITCH_WAIT")
    _set_range("escape_wait", "ESCAPE_WAIT")
    _set_range("dismiss_ui_interval", "DISMISS_UI_INTERVAL")
    _set_range("stuck_ticks", "STUCK_TICKS")
    _set_range("click_delay", "CLICK_DELAY")

    # Stored for ActionExecutor construction / late apply.
    global _dismiss_ui_enabled
    if "dismiss_ui_enabled" in section:
        _dismiss_ui_enabled = bool(section["dismiss_ui_enabled"])

    # Cursor verifier (templates under cursors/).
    from app._05_action import cursor_verify as cv

    cur = section.get("cursor_verify") or {}
    if "enabled" in cur:
        cv.CURSOR_VERIFY_ENABLED = bool(cur["enabled"])
    if "settle_s" in cur:
        cv.CURSOR_SETTLE_S = float(cur["settle_s"])
    if "capture_size" in cur:
        cv.CURSOR_CAPTURE_SIZE = int(cur["capture_size"])
    templates = cur.get("templates_dir")
    min_score = cur.get("min_score")
    from pathlib import Path
    from app._05_action.cursor_match import configure_cursor_matcher

    root = Path(__file__).resolve().parents[2]
    tdir = root / str(templates) if templates else None
    configure_cursor_matcher(
        templates_dir=tdir,
        min_score=float(min_score) if min_score is not None else None,
    )


_dismiss_ui_enabled: bool = False


def get_dismiss_ui_enabled() -> bool:
    return _dismiss_ui_enabled


def apply_action_executor_options(executor: Any) -> None:
    """Push action-config flags onto an existing ActionExecutor."""
    if hasattr(executor, "_dismiss_ui_enabled"):
        executor._dismiss_ui_enabled = _dismiss_ui_enabled


__all__ = [
    "configure_decision",
    "configure_action",
    "get_dismiss_ui_enabled",
    "apply_action_executor_options",
]
