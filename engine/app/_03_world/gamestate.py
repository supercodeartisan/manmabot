"""Main game state manager."""
from __future__ import annotations

import time
from typing import Any, Iterable

from .constants import (
    DEFAULT_PLAYER_LEVEL,
    LOCAL_PLAYER_TRACK_ID,
    monster_level_for_object,
)
from .enums import CharacterType
from .objects import ObjectType, PerceptionObject, Position, WorldObject
from .player import PlayerState
from .world import WorldState
from .converter import vision_to_perception
from .battle_area import player_screen_position


def _to_position(origin: Position | tuple[float, float]) -> Position:
    if isinstance(origin, Position):
        return origin
    x, y = origin
    return Position(x=x, y=y)


def _default_local_player(
    character_type: CharacterType = CharacterType.MAGE,
) -> PlayerState:
    """Local character at the battle-area player anchor (not from vision)."""
    pos = player_screen_position()
    return PlayerState(
        track_id=LOCAL_PLAYER_TRACK_ID,
        position=Position(x=pos.x, y=pos.y),
        character_type=character_type,
    )


class GameState:
    """Maintains the current state of the game world.

    A stateful live model: each :meth:`update` merges the latest
    :class:`PerceptionObject` results into the tracked world and exposes
    decision-facing queries. The decision layer never sees perception data.

    :attr:`player` is the local character status (battle-area player anchor;
    HP/MP/level from memory monitor when available). Bag fill comes from HUD
    template matching. It is never derived from detected PLAYER boxes.
    """

    def __init__(
        self,
        max_age_frames: int = 30,
        character_type: CharacterType = CharacterType.MAGE,
    ) -> None:
        self.max_age_frames = max_age_frames
        self.character_type = character_type
        self.frame_id = 0
        self.timestamp = time.time()
        self._objects: dict[int, WorldObject] = {}
        self._missed_frames: dict[int, int] = {}
        self._player: PlayerState = _default_local_player(character_type)
        # Last monitor JSON applied by ``apply_snapshot`` (None = never synced).
        self.last_memory_snapshot: dict[str, Any] | None = None
        # Latest print_state sweep (driver read in this process, not a file).
        # Vision still owns click targets. None when the sweep is off or LC.exe is gone.
        self.last_print_state: dict[str, Any] | None = None
        self.last_print_entities: list[dict[str, Any]] = []
        # Latest inventory_listen bag snapshot (DLL / inv.json). None until first scan.
        self.last_inventory: dict[str, Any] | None = None
        # Latest hotbar_listen 24-slot snapshot. None until first scan.
        self.last_hotbar: dict[str, Any] | None = None

    def update(self, perception_objects: Iterable[PerceptionObject]) -> None:
        """Merge the latest perception results into the world state."""
        self.frame_id += 1
        self.timestamp = time.time()

        seen: set[int] = set()
        for perception in perception_objects:
            self._apply(perception)
            seen.add(perception.track_id)

        for track_id in list(self._objects):
            if track_id in seen:
                self._missed_frames[track_id] = 0
            else:
                self._missed_frames[track_id] = self._missed_frames.get(track_id, 0) + 1
                if self._missed_frames[track_id] > self.max_age_frames:
                    self._forget(track_id)

    def update_from_vision(self, vision_output: list[dict[str, Any]]) -> None:
        """Convenience method: accept VisionSystem output directly."""
        perception_objects = vision_to_perception(vision_output)
        self.update(perception_objects)

    def _apply(self, perception: PerceptionObject) -> None:
        track_id = perception.track_id
        existing = self._objects.get(track_id)
        if existing is not None:
            existing.apply_perception(perception)
        else:
            existing = WorldObject.from_perception(perception)
            self._objects[track_id] = existing
        # Detected PLAYER boxes are world objects only; they never set _player.

    def _forget(self, track_id: int) -> None:
        self._objects.pop(track_id, None)
        self._missed_frames.pop(track_id, None)

    @property
    def player(self) -> PlayerState:
        return self._player

    def set_player(self, player: PlayerState) -> None:
        """Replace local player status (memory sync / tests)."""
        self._player = player

    @property
    def world_state(self) -> WorldState:
        """Immutable snapshot of the current frame with weak/strong monster classification."""
        all_monsters = [
            obj for obj in self._objects.values() if obj.object_type is ObjectType.MONSTER
        ]
        weak_monsters = []
        strong_monsters = []
        player_level = self._player.level or DEFAULT_PLAYER_LEVEL
        for monster in all_monsters:
            monster_level = monster_level_for_object(
                monster.species_name,
                monster.detail_classification,
            )
            # Unclassified monsters are never farmed (treated as strong).
            if monster_level is None:
                strong_monsters.append(monster)
            elif monster_level <= player_level:
                weak_monsters.append(monster)
            else:
                strong_monsters.append(monster)

        return WorldState(
            frame_id=self.frame_id,
            timestamp=self.timestamp,
            player=self._player,
            objects=dict(self._objects),
            weak_monsters=weak_monsters,
            strong_monsters=strong_monsters,
        )

    def missing_frames(self, track_id: int) -> int:
        """Number of consecutive frames the object was not detected."""
        return self._missed_frames.get(track_id, 0)

    def objects(self, kind: ObjectType) -> list[WorldObject]:
        return self.world_state.objects_of(kind)

    def players(self) -> list[WorldObject]:
        return self.objects(ObjectType.PLAYER)

    def monsters(self) -> list[WorldObject]:
        return self.objects(ObjectType.MONSTER)

    def npcs(self) -> list[WorldObject]:
        return self.objects(ObjectType.NPC)

    def items(self) -> list[WorldObject]:
        return self.objects(ObjectType.ITEM)

    def weak_monsters(self) -> list[WorldObject]:
        """Return monsters classified as weak (level <= player level)."""
        return self.world_state.weak_monsters

    def strong_monsters(self) -> list[WorldObject]:
        """Return monsters classified as strong (level > player level)."""
        return self.world_state.strong_monsters

    def all_objects(self) -> list[WorldObject]:
        return self.world_state.all_objects()

    def get_object(self, track_id: int) -> WorldObject | None:
        """Return the tracked object by id, or ``None`` if unknown/expired."""
        return self._objects.get(track_id)

    def nearest(self, kind: ObjectType, origin: Position | tuple[float, float]) -> WorldObject | None:
        candidates = self.objects(kind)
        if not candidates:
            return None
        origin = _to_position(origin)
        return min(
            candidates,
            key=lambda o: (o.position.x - origin.x) ** 2
            + (o.position.y - origin.y) ** 2,
        )

    def nearest_enemy(
        self,
        origin: Position | tuple[float, float],
        max_missed_frames: int = 0,
    ) -> WorldObject | None:
        """Nearest monster, excluding objects not detected recently.

        Ghosts (objects pending expiry) are skipped so the decision layer
        never targets an object that may already be gone.
        """
        candidates = [
            obj
            for obj in self.monsters()
            if self.missing_frames(obj.track_id) <= max_missed_frames
        ]
        if not candidates:
            return None
        origin = _to_position(origin)
        return min(
            candidates,
            key=lambda o: (o.position.x - origin.x) ** 2
            + (o.position.y - origin.y) ** 2,
        )

    def counts(self) -> dict[ObjectType, int]:
        return self.world_state.counts()

    def to_dict(self) -> dict[str, Any]:
        return self.world_state.to_dict()
