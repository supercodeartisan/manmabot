"""Target selection rules for the combat and loot behaviors."""
from __future__ import annotations

from typing import Optional

from app._03_world import CharacterType, GameState, ObjectStatus, ObjectType
from app._03_world.objects import Position, WorldObject, distance_squared
from app._03_world.world_coords import (
    content_to_world,
    in_mage_spell_range,
    max_distance,
)
from app._04_decision.species_rules import is_avoided_for_state


# Monsters not seen for more than this many frames are considered unreachable.
MAX_MISSED_FRAMES = 2


def _reachable(game_state: GameState, obj: WorldObject) -> bool:
    """An object is reachable when it is not dead, not occluded and not lost."""
    if obj.status is ObjectStatus.DEAD:
        return False
    if obj.occluded:
        return False
    if game_state.missing_frames(obj.track_id) > MAX_MISSED_FRAMES:
        return False
    return True


def _is_mage(game_state: GameState) -> bool:
    player = game_state.player
    if player is None:
        return False
    return player.character_type is CharacterType.MAGE


def _mage_tile_distance(obj: WorldObject) -> int:
    """Chebyshev distance from player tile (0,0) to the object's WCS tile."""
    from app._03_world.world_coords import distance_tiles_from_memory

    known = distance_tiles_from_memory(obj)
    if known is not None:
        return known
    tile = content_to_world(obj.position.x, obj.position.y)
    return max_distance(tile, Position(0.0, 0.0))


def _candidates(
    game_state: GameState,
    exclude: set[int] | None = None,
) -> list[WorldObject]:
    by_id: dict[int, WorldObject] = {}
    for obj in game_state.monsters():
        if not _reachable(game_state, obj):
            continue
        if is_avoided_for_state(game_state, obj):
            continue
        by_id[obj.track_id] = obj
    candidates = list(by_id.values())
    if exclude:
        candidates = [obj for obj in candidates if obj.track_id not in exclude]
    return candidates


def select_target(
    game_state: GameState,
    exclude: set[int] | None = None,
) -> Optional[WorldObject]:
    """Select the nearest allowed monster to attack.

    Species allow/deny (blacklist/whitelist) is the only attack gate.
    Sleeping golems stay skipped. Targets in ``exclude`` are skipped.

    For mages, candidates must also be within :data:`MAGE_SPELL_RANGE` tiles
    (Chebyshev / max-distance in discrete WCS).
    """
    player = game_state.player
    if player is None:
        return None

    candidates = _candidates(game_state, exclude)

    if _is_mage(game_state):
        candidates = [
            obj for obj in candidates
            if in_mage_spell_range(obj.position.x, obj.position.y)
        ]
        if not candidates:
            return None
        return min(candidates, key=_mage_tile_distance)

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda o: distance_squared(o.position, player.position),
    )


def select_item(game_state: GameState) -> Optional[WorldObject]:
    """Select the nearest item still present in the live memory list."""
    player = game_state.player
    if player is None:
        return None

    candidates = list(game_state.items())
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda o: distance_squared(o.position, player.position),
    )


def is_target_valid(
    game_state: GameState,
    target_id: int,
    expected_type: ObjectType,
) -> bool:
    """Verify a remembered target is still worth pursuing.

    Requires a live detection (not dead / occluded / lost past
    ``MAX_MISSED_FRAMES``).
    """
    obj = game_state.get_object(target_id)
    if obj is None:
        return False
    if obj.object_type is not expected_type:
        return False
    if not _reachable(game_state, obj):
        return False
    if expected_type is ObjectType.MONSTER and is_avoided_for_state(game_state, obj):
        return False
    if _is_mage(game_state) and not in_mage_spell_range(
        obj.position.x, obj.position.y
    ):
        return False
    return True


__all__ = ["select_target", "select_item", "is_target_valid", "MAX_MISSED_FRAMES"]
