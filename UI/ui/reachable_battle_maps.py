"""Pack ids offered in the battle-map picker.

Map images and packs stay on disk. This set only limits that dropdown.
Talking Island and Mainland stay first; the caller already sorts the rest
in Korean jamo order.
"""

from __future__ import annotations

REACHABLE_BATTLE_MAP_IDS = frozenset(
    {
        "talking_island",
        "mainland",
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
