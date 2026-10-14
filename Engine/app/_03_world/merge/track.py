"""Apply perception entity handoffs into ``GameState`` (conversion only)."""
from __future__ import annotations

import time
from typing import Any, Iterable

from app._02_state.enums import CharacterType
from app._02_state.gamestate import GameState
from app._02_state.objects import ObjectType, PerceptionObject, Position, WorldObject
from app._02_state.player import PlayerState
from app._03_world.constants import (
    DEFAULT_PLAYER_LEVEL,
    LOCAL_PLAYER_TRACK_ID,
    monster_level_for_object,
)
from app._03_world.merge.converter import handoff_to_perception
from app._03_world.space.battle_area import player_screen_position


def default_player(
    character_type: CharacterType = CharacterType.MAGE,
) -> PlayerState:
    pos = player_screen_position()
    return PlayerState(
        track_id=LOCAL_PLAYER_TRACK_ID,
        position=Position(x=pos.x, y=pos.y),
        character_type=character_type,
    )


def create_game_state(
    character_type: CharacterType = CharacterType.MAGE,
    *,
    max_age_frames: int = 30,
) -> GameState:
    """Build an empty live state with the battle-area player anchor."""
    return GameState(
        player=default_player(character_type),
        max_age_frames=max_age_frames,
        character_type=character_type,
    )


def apply_entity_handoff(
    state: GameState,
    handoff_rows: list[dict[str, Any]] | None,
) -> None:
    """Convert handoff dicts → ``WorldObject`` map on ``state``."""
    apply_perception_objects(state, handoff_to_perception(list(handoff_rows or [])))


def apply_perception_objects(
    state: GameState,
    perception_objects: Iterable[PerceptionObject],
) -> None:
    state.frame_id += 1
    state.timestamp = time.time()
    seen: set[int] = set()
    for perception in perception_objects:
        _apply_one(state, perception)
        seen.add(perception.track_id)
    for track_id in list(state._objects):
        if track_id in seen:
            state._missed_frames[track_id] = 0
        else:
            state._missed_frames[track_id] = state._missed_frames.get(track_id, 0) + 1
            if state._missed_frames[track_id] > state.max_age_frames:
                state._objects.pop(track_id, None)
                state._missed_frames.pop(track_id, None)
    refresh_monster_bands(state)


def _apply_one(state: GameState, perception: PerceptionObject) -> None:
    track_id = perception.track_id
    existing = state._objects.get(track_id)
    if existing is not None:
        existing.apply_perception(perception)
    else:
        obj = WorldObject.from_perception(perception)
        state._objects[track_id] = obj
        if obj.object_type is ObjectType.ITEM:
            try:
                from app._03_world.merge.item_sight import note_item_first_seen

                note_item_first_seen(obj)
            except Exception:
                pass


def upsert_object(state: GameState, obj: WorldObject) -> None:
    state.upsert_object(obj)


def touch_object(state: GameState, track_id: int) -> None:
    state.touch_object(track_id)


def note_attacked_me_map(state: GameState, map_id: int) -> None:
    """Drop attacked-me latches when MapSubsystem mapId changes.

    The first observed id only records the map. MapId 0 is a real map.
    """
    mid = int(map_id)
    prev = state.attacked_me_map_id
    state.attacked_me_map_id = mid
    if prev is None or int(prev) == mid:
        return
    for obj in state.monsters():
        obj.attacked_me = False


def refresh_monster_bands(state: GameState) -> None:
    """Classify monsters into weak/strong for ``state`` (debug + decision)."""
    weak: list[WorldObject] = []
    strong: list[WorldObject] = []
    player_level = state.player.level or DEFAULT_PLAYER_LEVEL
    for monster in state._objects.values():
        if monster.object_type is not ObjectType.MONSTER:
            continue
        monster_level = monster_level_for_object(
            monster.species_name,
            monster.detail_classification,
        )
        if monster_level is None:
            strong.append(monster)
        elif monster_level <= player_level:
            weak.append(monster)
        else:
            strong.append(monster)
    state.set_monster_bands(weak, strong)


__all__ = [
    "note_attacked_me_map",
    "apply_entity_handoff",
    "apply_perception_objects",
    "create_game_state",
    "default_player",
    "refresh_monster_bands",
    "touch_object",
    "upsert_object",
]
