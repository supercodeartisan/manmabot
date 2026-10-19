"""Safe adapter from a saved schedule task to the existing runtime profile."""
from __future__ import annotations

import copy
from typing import Any

from settings.hp_actions import (
    normalize_hp_actions,
    sync_legacy_from_actions,
)
from settings.profile import Profile, normalize_party_roster
from settings.schedule import ScheduleTask
from i18n.strings import normalize_game_language


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
        # Only Profile-backed knobs (see docstring). Skip keys from newer bags
        # that this Profile build does not define yet.
        if not hasattr(profile, name):
            return
        if getattr(profile, name) != value:
            setattr(profile, name, value)
            changed.append(name)

    move = task.settings.get("move", {})
    hunt = task.settings.get("hunt", {})
    party = task.settings.get("party", {})
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
        from settings.farm_schedule import normalize_farm_stays_s

        raw_stays = move.get("farm_stays_s", getattr(profile, "farm_stays_s", {}))
        set_value("farm_stays_s", normalize_farm_stays_s(raw_stays))
    try:
        set_value("farm_rotate_s", max(5.0, float(move.get("farm_rotate_s", profile.farm_rotate_s))))
    except (TypeError, ValueError):
        pass

    from settings.farm_schedule import normalize_routine

    routine = normalize_routine(move.get("routine"))
    if not routine and str(move.get("map_id") or "").strip():
        # Legacy single-map → one battle row so world-nav still has a goal.
        routine = normalize_routine(
            [
                {
                    "map_id": str(move.get("map_id") or profile.active_map),
                    "kind": "battle",
                    "duration_minutes": max(
                        1, int(round(float(getattr(profile, "farm_rotate_s", 600)) / 60.0))
                    ),
                    "selected_farms": list(getattr(profile, "selected_farms", []) or []),
                    "farm_stays_s": dict(getattr(profile, "farm_stays_s", {}) or {}),
                }
            ]
        )
    set_value("routine", routine)

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
    attack_mode = str(
        hunt.get("attack_mode", getattr(profile, "attack_mode", "magic")) or "magic"
    ).strip().lower()
    if attack_mode not in ("ranged", "magic", "melee"):
        attack_mode = "magic"
    set_value("attack_mode", attack_mode)
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
    use_haste = bool(
        hunt.get("use_haste_potion", getattr(profile, "use_haste_potion", False))
    )
    haste_item = str(
        hunt.get("haste_potion_item", getattr(profile, "haste_potion_item", "")) or ""
    ).strip()
    try:
        haste_box = int(
            hunt.get("haste_potion_box", getattr(profile, "haste_potion_box", 0)) or 0
        )
    except (TypeError, ValueError):
        haste_box = 0
    haste_key = str(
        hunt.get("haste_potion_key", getattr(profile, "haste_potion_key", "")) or ""
    ).strip()
    set_value("use_haste_potion", use_haste)
    set_value("haste_potion_item", haste_item)
    set_value("haste_potion_box", haste_box)
    set_value("haste_potion_key", haste_key)

    # Party member (UI → profile). Leader comes from party_listen after join.
    party_role = str(
        party.get("role", getattr(profile, "party_role", "member")) or "member"
    ).strip().lower()
    if party_role not in ("member", "leader"):
        party_role = "member"
    set_value("party_role", party_role)
    set_value(
        "party_ws_port",
        _int_range(
            party.get("ws_port", getattr(profile, "party_ws_port", 8765)),
            8765,
            1,
            65535,
        ),
    )
    set_value(
        "party_leader_host",
        str(
            party.get("leader_host", getattr(profile, "party_leader_host", "")) or ""
        ).strip(),
    )
    # Master Party-tab switch (UI checkbox). Legacy profiles only had member_enabled.
    party_master = party.get("enabled")
    if party_master is None:
        party_master = party.get(
            "member_enabled",
            getattr(
                profile,
                "party_enabled",
                getattr(profile, "party_member_enabled", False),
            ),
        )
    party_master = bool(party_master)
    set_value("party_enabled", party_master)
    # Member follow only when the master switch is on and this PC is a member.
    # Leaders host the socket and farm solo — they never run the member brain.
    party_on = bool(party_master and party_role != "leader")
    set_value("party_member_enabled", party_on)
    set_value("party_leader_name", "")
    follow_raw = party.get("follow_tiles")
    if follow_raw is None:
        follow_raw = party.get(
            "follow_start_tiles",
            getattr(
                profile,
                "party_follow_tiles",
                getattr(profile, "party_follow_start_tiles", 8),
            ),
        )
    follow_tiles = _int_range(follow_raw, 8, 1, 40)
    stop_raw = party.get("stop_tiles")
    if stop_raw is None:
        stop_raw = party.get(
            "follow_stop_tiles",
            getattr(
                profile,
                "party_stop_tiles",
                getattr(profile, "party_follow_stop_tiles", 2),
            ),
        )
    stop_tiles = _int_range(stop_raw, 2, 0, 40)
    if stop_tiles > follow_tiles:
        stop_tiles = follow_tiles
    set_value("party_follow_tiles", follow_tiles)
    set_value("party_stop_tiles", stop_tiles)
    # Keep legacy fields mirrored so older readers stay consistent.
    set_value("party_follow_start_tiles", follow_tiles)
    set_value("party_follow_stop_tiles", stop_tiles)
    set_value(
        "party_assist_leash_tiles",
        _int_range(
            party.get(
                "assist_leash_tiles",
                getattr(profile, "party_assist_leash_tiles", 10),
            ),
            10,
            1,
            40,
        ),
    )
    set_value(
        "party_approach_tiles",
        _int_range(
            party.get(
                "approach_tiles",
                getattr(profile, "party_approach_tiles", 2),
            ),
            2,
            1,
            8,
        ),
    )
    try:
        potion_ratio = float(
            party.get(
                "potion_hp_ratio",
                getattr(profile, "party_potion_hp_ratio", 0.45),
            )
        )
    except (TypeError, ValueError):
        potion_ratio = 0.45
    # UI may store percent (45) or ratio (0.45).
    if potion_ratio > 1.0:
        potion_ratio = potion_ratio / 100.0
    set_value("party_potion_hp_ratio", max(0.05, min(0.95, potion_ratio)))
    set_value(
        "party_random_loot",
        bool(party.get("random_loot", getattr(profile, "party_random_loot", False))),
    )
    loot_role = str(
        party.get("loot_role", getattr(profile, "party_loot_role", "none")) or "none"
    ).strip().lower()
    if loot_role not in ("none", "responsible"):
        loot_role = "none"
    set_value("party_loot_role", loot_role)
    loot_priority = str(
        party.get(
            "loot_priority",
            getattr(profile, "party_loot_priority", "follow"),
        )
        or "follow"
    ).strip().lower()
    if loot_priority not in ("follow", "loot"):
        loot_priority = "follow"
    set_value("party_loot_priority", loot_priority)
    farm_mode = str(
        party.get("farm_mode", getattr(profile, "party_farm_mode", "party")) or "party"
    ).strip().lower()
    if farm_mode not in ("party", "solo"):
        farm_mode = "party"
    set_value("party_farm_mode", farm_mode)
    set_value(
        "party_roster",
        normalize_party_roster(
            party.get("roster", getattr(profile, "party_roster", None))
        ),
    )
    use_antidote = bool(
        hunt.get("use_antidote_potion", getattr(profile, "use_antidote_potion", False))
    )
    antidote_item = str(
        hunt.get("antidote_potion_item", getattr(profile, "antidote_potion_item", ""))
        or ""
    ).strip()
    try:
        antidote_box = int(
            hunt.get(
                "antidote_potion_box", getattr(profile, "antidote_potion_box", 0)
            )
            or 0
        )
    except (TypeError, ValueError):
        antidote_box = 0
    antidote_key = str(
        hunt.get(
            "antidote_potion_key", getattr(profile, "antidote_potion_key", "")
        )
        or ""
    ).strip()
    set_value("use_antidote_potion", use_antidote)
    set_value("antidote_potion_item", antidote_item)
    set_value("antidote_potion_box", antidote_box)
    set_value("antidote_potion_key", antidote_key)
    set_value("abandon_same", False)
    # Legacy hunt.antidote_auto stays off unless the new toggle is on.
    set_value("antidote_auto", use_antidote)
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
        "mother_tree_hp_to_mp_enabled",
        bool(recovery.get("mother_tree_hp_to_mp_enabled", True)),
    )
    set_value(
        "mother_tree_hp_to_mp_hp_ratio",
        _ratio(recovery.get("mother_tree_hp_to_mp_hp"), 0.85),
    )
    set_value(
        "mother_tree_hp_to_mp_mp_ratio",
        _ratio(recovery.get("mother_tree_hp_to_mp_mp"), 0.80),
    )
    set_value(
        "mother_tree_heal_enabled",
        bool(recovery.get("mother_tree_heal_enabled", True)),
    )
    set_value(
        "mother_tree_heal_hp_ratio",
        _ratio(recovery.get("mother_tree_heal_hp"), 0.40),
    )
    set_value(
        "mother_tree_heal_mp_ratio",
        _ratio(recovery.get("mother_tree_heal_mp"), 0.80),
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
            getattr(profile, "teleport_surround_count", 10),
            2,
            20,
        ),
    )
    actions = normalize_hp_actions(
        recovery.get("hp_actions"),
        potion_pct=round(float(profile.hp_potion_ratio) * 100),
        heal_pct=round(float(getattr(profile, "hp_heal_ratio", 0.70)) * 100),
        escape_pct=round(float(profile.hp_escape_ratio) * 100),
    )
    set_value("hp_actions", actions)
    legacy = sync_legacy_from_actions(actions)
    set_value("hp_recover_enabled", True)
    set_value("use_heal", bool(legacy["use_heal"]))
    set_value("use_hp_potion", bool(legacy["use_hp_potion"]))
    set_value("hp_potion_ratio", float(legacy["hp_potion_below"]) / 100.0)
    set_value("hp_heal_ratio", float(legacy["hp_heal_below"]) / 100.0)
    set_value("hp_escape_ratio", float(legacy["escape_hp_below"]) / 100.0)
    set_value("return_hp_enabled", False)

    slots = magic.get("spell_slots")
    layout = magic.get("hotbar_layout")
    if isinstance(layout, dict):
        set_value("hotbar_layout", copy.deepcopy(layout))
    from settings.antidote_potion import apply_antidote_potion_to_spell_slots
    from settings.haste_potion import apply_haste_potion_to_spell_slots

    synced_slots = apply_haste_potion_to_spell_slots(
        slots if isinstance(slots, dict) else getattr(profile, "spell_slots", None),
        use=use_haste,
        item_key=haste_item,
        box=haste_box,
        key=haste_key,
        layout=layout if isinstance(layout, dict) else getattr(profile, "hotbar_layout", None),
    )
    synced_slots = apply_antidote_potion_to_spell_slots(
        synced_slots,
        use=use_antidote,
        item_key=antidote_item,
        box=antidote_box,
        key=antidote_key,
        layout=layout if isinstance(layout, dict) else getattr(profile, "hotbar_layout", None),
    )
    set_value("spell_slots", copy.deepcopy(synced_slots))
    if isinstance(magic, dict):
        magic["spell_slots"] = copy.deepcopy(synced_slots)
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
                        getattr(profile, "hp_potion_buy_qty", 10),
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
        "store_after_sell",
        bool(equipment.get("store_after_sell", getattr(profile, "store_after_sell", True))),
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
            max(0, int(hunt.get("return_potion_count", getattr(profile, "return_potion_count", 0)))),
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
    from settings.profile import (
        DEFAULT_RETURN_WEIGHT_ABOVE,
        snap_return_weight_above,
    )

    set_value(
        "return_weight_above",
        snap_return_weight_above(
            hunt.get(
                "return_weight_above",
                getattr(profile, "return_weight_above", DEFAULT_RETURN_WEIGHT_ABOVE),
            ),
            DEFAULT_RETURN_WEIGHT_ABOVE,
        ),
    )
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
    set_value(
        "ignore_small_adena",
        bool(other.get("ignore_small_adena", getattr(profile, "ignore_small_adena", False))),
    )
    try:
        qty = int(other.get(
            "ignore_small_adena_qty",
            getattr(profile, "ignore_small_adena_qty", 10),
        ))
    except (TypeError, ValueError):
        qty = 10
    set_value("ignore_small_adena_qty", max(1, min(99999, qty)))
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
        "humanize_move",
        bool(other.get("humanize_move", getattr(profile, "humanize_move", True))),
    )
    set_value(
        "game_language",
        normalize_game_language(str(other.get("game_language", profile.game_language))),
    )
    shop_locale = "ko"
    try:
        from settings.accounts import AccountStore

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
    from settings.auto_buffs import auto_buffs_for_magic

    profile.auto_buff_plan = auto_buffs_for_magic(
        magic if isinstance(magic, dict) else {},
        str(getattr(profile, "character", "") or ""),
    )
    return changed
