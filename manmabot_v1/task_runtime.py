"""Safe adapter from a saved schedule task to the existing runtime profile."""
from __future__ import annotations

import copy
from typing import Any

from manmabot_v1.hp_actions import (
    normalize_hp_actions,
    sync_legacy_from_actions,
)
from manmabot_v1.profile import Profile
from manmabot_v1.schedule import ScheduleTask
from manmabot_v1.strings import normalize_game_language


def _ratio(value: Any, fallback: float) -> float:
    try:
        return max(0.0, min(1.0, float(value) / 100.0))
    except (TypeError, ValueError):
        return fallback


JITTER_MS_MIN = 10
JITTER_MS_MAX = 50


def clamp_jitter_ms(value: Any, fallback: int = 35) -> int:
    """Attack / target-select jitter is only allowed in 10–50 ms."""
    return _int_range(value, fallback, JITTER_MS_MIN, JITTER_MS_MAX)


def _int_range(value: Any, fallback: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


def apply_runtime_settings(task: ScheduleTask, profile: Profile) -> list[str]:
    """Apply only settings already backed by ``Profile`` and return changed keys.

    Account selection and all clock/duration/repetition fields are deliberately
    excluded: the current bot has no schedule executor.
    """
    changed: list[str] = []

    def set_value(name: str, value: Any) -> None:
        if getattr(profile, name) != value:
            setattr(profile, name, value)
            changed.append(name)

    move = task.settings.get("move", {})
    hunt = task.settings.get("hunt", {})
    recovery = task.settings.get("recovery", {})
    magic = task.settings.get("magic", {})
    equipment = task.settings.get("equipment", {})
    other = task.settings.get("other", {})

    if task.character in ("royal", "knight", "elf", "mage"):
        set_value("character", task.character)
    map_id = str(move.get("map_id", profile.active_map) or profile.active_map)
    set_value("active_map", map_id)
    style = str(move.get("map_style", getattr(profile, "map_style", "normal")) or "normal")
    style = "dungeon" if style.strip().lower() == "dungeon" else "normal"
    set_value("map_style", style)
    farms = move.get("selected_farms", profile.selected_farms)
    if isinstance(farms, list):
        set_value("selected_farms", [str(item) for item in farms])
    if style == "dungeon":
        set_value("selected_farms", [])
        set_value("farm_stays_s", {})
    else:
        from manmabot_v1.farm_schedule import normalize_farm_stays_s

        raw_stays = move.get("farm_stays_s", getattr(profile, "farm_stays_s", {}))
        set_value("farm_stays_s", normalize_farm_stays_s(raw_stays))
    try:
        set_value("farm_rotate_s", max(5.0, float(move.get("farm_rotate_s", profile.farm_rotate_s))))
    except (TypeError, ValueError):
        pass

    levels = hunt.get("species_levels")
    if isinstance(levels, dict):
        set_value("species_levels", {str(k): int(v) for k, v in levels.items()})
    blacklist = hunt.get("species_blacklist", profile.species_blacklist)
    if isinstance(blacklist, list):
        set_value("species_blacklist", [str(item) for item in blacklist])
    species_mode = str(
        hunt.get("species_filter_mode", getattr(profile, "species_filter_mode", "blacklist"))
    ).strip().lower()
    if species_mode not in ("blacklist", "whitelist"):
        species_mode = "blacklist"
    set_value("species_filter_mode", species_mode)
    whitelist = hunt.get("species_whitelist", getattr(profile, "species_whitelist", []))
    if isinstance(whitelist, list):
        set_value("species_whitelist", [str(item).strip() for item in whitelist if str(item).strip()])
    species_sort = str(hunt.get("species_sort", profile.species_sort))
    if species_sort in ("name", "level"):
        set_value("species_sort", species_sort)
    set_value("attack_jitter", bool(hunt.get("attack_jitter", getattr(profile, "attack_jitter", False))))
    set_value(
        "attack_jitter_ms",
        clamp_jitter_ms(hunt.get("attack_jitter_ms"), getattr(profile, "attack_jitter_ms", 35)),
    )
    set_value("target_delay", bool(hunt.get("target_delay", getattr(profile, "target_delay", False))))
    delay_min = clamp_jitter_ms(
        hunt.get("target_delay_min_ms"), getattr(profile, "target_delay_min_ms", 20),
    )
    delay_max = clamp_jitter_ms(
        hunt.get("target_delay_max_ms"), getattr(profile, "target_delay_max_ms", 50),
    )
    if delay_max < delay_min:
        delay_max = delay_min
    set_value("target_delay_min_ms", delay_min)
    set_value("target_delay_max_ms", delay_max)
    set_value("abandon_same", bool(hunt.get("abandon_same", getattr(profile, "abandon_same", False))))
    set_value(
        "abandon_seconds",
        _int_range(hunt.get("abandon_seconds"), getattr(profile, "abandon_seconds", 30), 1, 600),
    )
    set_value("antidote_auto", bool(hunt.get("antidote_auto", getattr(profile, "antidote_auto", False))))
    set_value("area_empty", bool(hunt.get("area_empty", getattr(profile, "area_empty", False))))
    set_value(
        "area_empty_seconds",
        _int_range(hunt.get("area_empty_seconds"), getattr(profile, "area_empty_seconds", 60), 1, 600),
    )
    set_value("area_low_yield", bool(hunt.get("area_low_yield", getattr(profile, "area_low_yield", False))))
    set_value(
        "area_low_yield_adena",
        _int_range(
            hunt.get("area_low_yield_adena"),
            getattr(profile, "area_low_yield_adena", 1000),
            1,
            10_000_000,
        ),
    )
    set_value(
        "area_low_yield_seconds",
        _int_range(
            hunt.get("area_low_yield_seconds"),
            getattr(profile, "area_low_yield_seconds", 180),
            1,
            600,
        ),
    )
    set_value("area_players", bool(hunt.get("area_players", getattr(profile, "area_players", False))))
    set_value(
        "area_player_count",
        _int_range(hunt.get("area_player_count"), getattr(profile, "area_player_count", 3), 1, 20),
    )

    set_value(
        "hp_potion_ratio",
        _ratio(recovery.get("hp_potion_below"), profile.hp_potion_ratio),
    )
    set_value(
        "hp_recover_enabled",
        bool(recovery.get("hp_recover_enabled", getattr(profile, "hp_recover_enabled", True))),
    )
    set_value(
        "use_hp_potion",
        bool(recovery.get("use_hp_potion", getattr(profile, "use_hp_potion", True))),
    )
    set_value(
        "use_heal",
        bool(recovery.get("use_heal", getattr(profile, "use_heal", True))),
    )
    set_value(
        "mp_recover_enabled",
        bool(recovery.get("mp_recover_enabled", getattr(profile, "mp_recover_enabled", False))),
    )
    set_value(
        "mp_potion_ratio",
        _ratio(recovery.get("mp_potion_below"), getattr(profile, "mp_potion_ratio", 0.30)),
    )
    set_value(
        "use_mp_potion",
        bool(recovery.get("use_mp_potion", getattr(profile, "use_mp_potion", False))),
    )
    set_value(
        "resurrect_if_dead",
        bool(recovery.get("resurrect_if_dead", getattr(profile, "resurrect_if_dead", True))),
    )
    set_value(
        "resume_after_relogin",
        bool(
            recovery.get(
                "resume_after_relogin",
                getattr(profile, "resume_after_relogin", True),
            )
        ),
    )
    try:
        set_value(
            "max_retries",
            max(
                1,
                min(
                    20,
                    int(recovery.get("max_retries", getattr(profile, "max_retries", 3))),
                ),
            ),
        )
    except (TypeError, ValueError):
        pass
    set_value(
        "hp_escape_ratio",
        _ratio(recovery.get("escape_hp_below"), profile.hp_escape_ratio),
    )
    set_value(
        "mp_escape_enabled",
        False,
    )
    set_value(
        "return_hp_enabled",
        bool(hunt.get("return_hp_enabled", getattr(profile, "return_hp_enabled", True))),
    )
    set_value(
        "return_hp_ratio",
        _ratio(hunt.get("return_hp_below"), getattr(profile, "return_hp_ratio", 0.30)),
    )
    set_value(
        "return_mp_enabled",
        bool(hunt.get("return_mp_enabled", getattr(profile, "return_mp_enabled", True))),
    )
    set_value(
        "return_mp_ratio",
        _ratio(hunt.get("return_mp_below"), getattr(profile, "return_mp_ratio", 0.15)),
    )
    set_value(
        "return_idle_enabled",
        bool(
            hunt.get("return_idle_enabled", getattr(profile, "return_idle_enabled", False))
        ),
    )
    try:
        set_value(
            "return_idle_seconds",
            max(
                1.0,
                float(
                    hunt.get(
                        "return_idle_seconds",
                        getattr(profile, "return_idle_seconds", 60.0),
                    )
                ),
            ),
        )
    except (TypeError, ValueError):
        pass
    teleport_master = bool(
        recovery.get(
            "random_teleport_enabled",
            getattr(profile, "random_teleport_enabled", False),
        )
    )
    set_value("random_teleport_enabled", teleport_master)
    set_value(
        "teleport_on_player",
        bool(
            teleport_master
            and recovery.get(
                "teleport_on_player", getattr(profile, "teleport_on_player", False)
            )
        ),
    )
    set_value(
        "teleport_when_surrounded",
        bool(
            teleport_master
            and recovery.get(
                "teleport_when_surrounded",
                getattr(profile, "teleport_when_surrounded", False),
            )
        ),
    )
    set_value(
        "teleport_surround_count",
        _int_range(
            recovery.get("teleport_surround_count"),
            getattr(profile, "teleport_surround_count", 4),
            2,
            20,
        ),
    )
    actions = normalize_hp_actions(
        recovery.get("hp_actions"),
        potion_pct=round(float(profile.hp_potion_ratio) * 100),
        escape_pct=round(float(profile.hp_escape_ratio) * 100),
        use_heal=bool(profile.use_heal),
        use_potion=bool(profile.use_hp_potion),
    )
    set_value("hp_actions", actions)
    legacy = sync_legacy_from_actions(actions)
    set_value("hp_recover_enabled", True)
    set_value("use_heal", bool(legacy["use_heal"]))
    set_value("use_hp_potion", bool(legacy["use_hp_potion"]))
    set_value("hp_potion_ratio", float(legacy["hp_potion_below"]) / 100.0)
    set_value("hp_escape_ratio", float(legacy["escape_hp_below"]) / 100.0)
    set_value("return_hp_enabled", False)

    slots = magic.get("spell_slots")
    if isinstance(slots, dict):
        set_value("spell_slots", copy.deepcopy(slots))
    layout = magic.get("hotbar_layout")
    if isinstance(layout, dict):
        set_value("hotbar_layout", copy.deepcopy(layout))
    set_value(
        "heal_until_hp_ratio",
        _ratio(magic.get("heal_until_hp_pct"), profile.heal_until_hp_ratio),
    )
    set_value(
        "spell_reserve_ratio",
        _ratio(magic.get("spell_reserve_pct"), profile.spell_reserve_ratio),
    )

    try:
        quantity = max(1, min(999, int(equipment.get("arrow_quantity", profile.arrow_buy_qty))))
        set_value("arrow_buy_qty", quantity)
    except (TypeError, ValueError):
        pass
    try:
        silver_qty = max(
            1,
            min(
                999,
                int(
                    equipment.get(
                        "silver_arrow_quantity",
                        getattr(profile, "silver_arrow_buy_qty", 200),
                    )
                ),
            ),
        )
        set_value("silver_arrow_buy_qty", silver_qty)
    except (TypeError, ValueError):
        pass
    try:
        potion_qty = max(
            1,
            min(
                999,
                int(
                    equipment.get(
                        "buy_portion",
                        getattr(profile, "hp_potion_buy_qty", 100),
                    )
                ),
            ),
        )
        set_value("hp_potion_buy_qty", potion_qty)
    except (TypeError, ValueError):
        pass
    try:
        depoison_qty = max(
            1,
            min(
                999,
                int(
                    equipment.get(
                        "depoison_quantity",
                        getattr(profile, "depoison_buy_qty", 1),
                    )
                ),
            ),
        )
        set_value("depoison_buy_qty", depoison_qty)
    except (TypeError, ValueError):
        pass

    master_buy_arrows = bool(equipment.get("buy_arrows", True))
    buy_normal = bool(equipment.get("buy_normal_arrows", profile.buy_normal_arrows))
    buy_silver = bool(equipment.get("buy_silver_arrows", profile.buy_silver_arrows))
    if not master_buy_arrows:
        buy_normal = False
        buy_silver = False
    elif buy_normal and buy_silver:
        buy_silver = False
    elif not buy_normal and not buy_silver:
        buy_normal = True
    set_value("buy_normal_arrows", buy_normal)
    set_value("buy_silver_arrows", buy_silver)
    set_value(
        "restock_potions",
        bool(equipment.get("restock_potions", profile.restock_potions)),
    )
    set_value(
        "buy_depoison",
        bool(equipment.get("buy_depoison", getattr(profile, "buy_depoison", False))),
    )
    npc = str(
        equipment.get("hp_potion_npc")
        or hunt.get("return_potion_npc")
        or getattr(profile, "hp_potion_npc", "")
        or ""
    ).strip()
    set_value("hp_potion_npc", npc)
    set_value(
        "return_potion_enabled",
        bool(hunt.get("return_potion_enabled", getattr(profile, "return_potion_enabled", True))),
    )
    set_value(
        "return_arrow_enabled",
        bool(hunt.get("return_arrow_enabled", getattr(profile, "return_arrow_enabled", True))),
    )
    set_value(
        "return_depoison_enabled",
        bool(
            hunt.get(
                "return_depoison_enabled",
                getattr(profile, "return_depoison_enabled", False),
            )
        ),
    )
    try:
        set_value(
            "return_potion_count",
            max(0, int(hunt.get("return_potion_count", getattr(profile, "return_potion_count", 20)))),
        )
    except (TypeError, ValueError):
        pass
    try:
        set_value(
            "return_arrow_count",
            max(0, int(hunt.get("return_arrow_count", getattr(profile, "return_arrow_count", 300)))),
        )
    except (TypeError, ValueError):
        pass
    try:
        set_value(
            "return_depoison_count",
            max(
                0,
                int(
                    hunt.get(
                        "return_depoison_count",
                        getattr(profile, "return_depoison_count", 1),
                    )
                ),
            ),
        )
    except (TypeError, ValueError):
        pass
    set_value(
        "return_weight_enabled",
        bool(
            hunt.get(
                "return_weight_enabled",
                getattr(profile, "return_weight_enabled", True),
            )
        ),
    )
    try:
        set_value(
            "return_weight_above",
            max(
                0,
                min(
                    100,
                    int(
                        hunt.get(
                            "return_weight_above",
                            getattr(profile, "return_weight_above", 85),
                        )
                    ),
                ),
            ),
        )
    except (TypeError, ValueError):
        pass
    sell_mode = str(
        equipment.get("sell_mode", getattr(profile, "sell_mode", "sell_only_garbage"))
        or "sell_only_garbage"
    ).strip().lower()
    set_value(
        "sell_mode",
        "sell_except_keep"
        if sell_mode in ("sell_except_keep", "except_keep", "keep")
        else "sell_only_garbage",
    )

    loot_mode = str(other.get("loot_mode", profile.loot_mode))
    if loot_mode in ("all_items", "adena_only"):
        set_value("loot_mode", loot_mode)
    set_value(
        "loot_adena_weight_ratio",
        _ratio(other.get("loot_adena_weight_pct"), profile.loot_adena_weight_ratio),
    )
    pickup_mode = str(other.get("item_pickup_mode", profile.item_pickup_mode)).strip().lower()
    if pickup_mode not in ("all", "blacklist", "whitelist"):
        pickup_mode = "all"
    set_value("item_pickup_mode", pickup_mode)
    raw_names = other.get("item_pickup_names", profile.item_pickup_names)
    if isinstance(raw_names, list):
        names: list[str] = []
        seen: set[str] = set()
        for item in raw_names:
            key = str(item).strip()
            if key and key not in seen:
                seen.add(key)
                names.append(key)
        set_value("item_pickup_names", names)
    set_value("humanize", bool(other.get("humanize", profile.humanize)))
    set_value(
        "game_language",
        normalize_game_language(str(other.get("game_language", profile.game_language))),
    )
    shop_locale = "ko"
    try:
        from manmabot_v1.accounts import AccountStore

        account = None
        if task.account_id:
            account = AccountStore().get(task.account_id)
        if account is not None and getattr(account, "locale", None):
            text = str(account.locale).strip().lower()
            shop_locale = "zh" if text.startswith("zh") else "ko"
        else:
            shop_locale = (
                "zh"
                if str(profile.game_language).strip().lower().startswith("zh")
                else "ko"
            )
    except Exception:
        shop_locale = (
            "zh"
            if str(getattr(profile, "game_language", "ko")).strip().lower().startswith("zh")
            else "ko"
        )
    set_value("shop_locale", shop_locale)
    # Decorative preview is intentionally disabled in the classic UI.
    set_value("show_preview", False)
    return changed
