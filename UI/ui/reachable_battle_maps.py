"""Pack ids offered in the battle-map picker.

Map images and packs stay on disk. This set only limits that dropdown.
Talking Island and Mainland stay first; blessing-land field packs follow in
fixed order via ``hangul_sort._PINNED_MAP_IDS``. The caller sorts the rest
in Korean jamo order.
"""

from __future__ import annotations

# Season base packs: live mapId / nav owners. Not offered in solo battle
# picker; still hidden from break + party pickers.
BLESSING_LAND_BASE_MAP_IDS: tuple[str, ...] = (
    "polluted_land_of_blessing",
    "corrupted_land_of_blessing_spring",
    "corrupted_land_of_blessing_summer",
    "corrupted_land_of_blessing_autumn",
    "corrupted_land_of_blessing_winter",
)

# Solo battle picker + pin order after mainland (hangul_sort).
# Season × race (fairy / human / orch / spirit).
BLESSING_LAND_FIELD_MAP_IDS: tuple[str, ...] = (
    "polluted_land_of_blessing_fairy",
    "polluted_land_of_blessing_human",
    "polluted_land_of_blessing_orch",
    "polluted_land_of_blessing_spirit",
    "corrupted_land_of_blessing_spring_fairy",
    "corrupted_land_of_blessing_spring_human",
    "corrupted_land_of_blessing_spring_orch",
    "corrupted_land_of_blessing_spring_spirit",
    "corrupted_land_of_blessing_summer_fairy",
    "corrupted_land_of_blessing_summer_human",
    "corrupted_land_of_blessing_summer_orch",
    "corrupted_land_of_blessing_summer_spirit",
    "corrupted_land_of_blessing_autumn_fairy",
    "corrupted_land_of_blessing_autumn_human",
    "corrupted_land_of_blessing_autumn_orch",
    "corrupted_land_of_blessing_autumn_spirit",
    "corrupted_land_of_blessing_winter_fairy",
    "corrupted_land_of_blessing_winter_human",
    "corrupted_land_of_blessing_winter_orch",
    "corrupted_land_of_blessing_winter_spirit",
)

# Everything blessing-land related that must stay out of break / party lists.
BLESSING_LAND_HIDDEN_MAP_IDS: frozenset[str] = frozenset(
    (*BLESSING_LAND_BASE_MAP_IDS, *BLESSING_LAND_FIELD_MAP_IDS)
)

REACHABLE_BATTLE_MAP_IDS = frozenset(
    {
        "talking_island",
        "mainland",
        *BLESSING_LAND_FIELD_MAP_IDS,
        "ant_cave_dungeon_F1",
        "ant_cave_dungeon_F2",
        "ant_cave_dungeon_F3",
        "ant_cave_dungeon_F4",
        "ant_cave_dungeon_F5",
        "ant_cave_dungeon_F6",
        "ant_cave_dungeon_F7",
        "ant_cave_dungeon_F8",
        "ant_cave_dungeon_F9",
        "gludio_dungeon_F1",
        "gludio_dungeon_F2",
        "gludio_dungeon_F3",
        "gludio_dungeon_F4",
        "gludio_dungeon_F5",
        "gludio_dungeon_F6",
        "gludio_dungeon_F7",
        "giran_dungeon_F1",
        "giran_dungeon_F2",
        "giran_dungeon_F3",
        "giran_dungeon_F4",
        "nerupas_cave_dungeon",
        "talking_island_dungeon_F1",
        "talking_island_dungeon_F2",
        "lair_of_valakas_dungeon",
        "oren_ivory_tower_dungeon_F1",
        "oren_ivory_tower_dungeon_F2",
        "oren_ivory_tower_dungeon_F3",
        "oren_ivory_tower_dungeon_F4",
        "oren_ivory_tower_dungeon_F5",
        "oren_ivory_tower_dungeon_F6",
        "oren_ivory_tower_dungeon_F7",
        "oren_ivory_tower_dungeon_F8",
        "training_dungeon_F1",
        "training_dungeon_F2",
        "training_dungeon_F3",
        "training_dungeon_F4",
        "lair_of_antharas_dungeon",
        "ice_crystal_cave_dungeon",
        "ice_queens_castle_dungeon_F2",
        "ice_queens_castle_dungeon_F3",
        "eva_kingdom_dungeon_F1",
        "eva_kingdom_dungeon_F2",
        "eva_kingdom_dungeon_F3",
        "elven_forest_dungeon_F1",
        "elven_forest_dungeon_F2",
        "elven_forest_dungeon_F3",
        "dragon_valley_dungeon_F1",
        "dragon_valley_dungeon_F2",
        "dragon_valley_dungeon_F3",
        "dragon_valley_dungeon_F4",
        "dragon_valley_dungeon_F5",
        "dragon_valley_dungeon_F6",
    }
)


def battle_picker_choices(
    choices: list[tuple[str, str, bool]],
) -> list[tuple[str, str, bool]]:
    """Keep catalog order. Drop packs the battle picker must not offer."""
    return [item for item in choices if str(item[0]) in REACHABLE_BATTLE_MAP_IDS]


def break_picker_choices(
    choices: list[tuple[str, str, bool]],
) -> list[tuple[str, str, bool]]:
    """Non-dungeon rest maps, excluding blessing-land packs.

    Blessing lands are field battle maps; they must not appear in the break
    list just because they are non-dungeon.
    """
    hidden = BLESSING_LAND_HIDDEN_MAP_IDS
    return [
        item
        for item in choices
        if not item[2] and str(item[0]) not in hidden
    ]
