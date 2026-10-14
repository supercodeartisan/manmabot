"""Live game state container — fields and read helpers only.

Perception → state conversion lives in ``app._03_world.merge``.
"""
from __future__ import annotations

import time
from typing import Any

from app._02_state.enums import CharacterType
from app._02_state.objects import ObjectType, Position, WorldObject
from app._02_state.player import PlayerState
from app._02_state.world import WorldState


def _to_position(origin: Position | tuple[float, float]) -> Position:
    if isinstance(origin, Position):
        return origin
    x, y = origin
    return Position(x=x, y=y)


class GameState:
    """Structured live snapshot for decision and debug.

    Writers: ``app._03_world.merge`` only.
    Readers: decision, UI debug, preview.
    """

    def __init__(
        self,
        *,
        player: PlayerState,
        max_age_frames: int = 30,
        character_type: CharacterType | None = None,
    ) -> None:
        self.max_age_frames = max_age_frames
        self.character_type = character_type or player.character_type
        self.frame_id = 0
        self.timestamp = time.time()
        self._objects: dict[int, WorldObject] = {}
        self._missed_frames: dict[int, int] = {}
        self._player: PlayerState = player
        self._weak_monsters: list[WorldObject] = []
        self._strong_monsters: list[WorldObject] = []
        self.last_memory_snapshot: dict[str, Any] | None = None
        self.last_print_state: dict[str, Any] | None = None
        self.last_print_entities: list[dict[str, Any]] = []
        self.last_attacks_me: dict[str, Any] | None = None
        self.last_contested_mobs: dict[str, Any] | None = None
        self.last_inventory: dict[str, Any] | None = None
        self.last_hotbar: dict[str, Any] | None = None
        self.last_buff: dict[str, Any] | None = None
        self.last_uidialog: dict[str, Any] | None = None
        self.last_perception_buffer: Any | None = None
        # MapSubsystem mapId for which ``attacked_me`` latches were armed.
        self.attacked_me_map_id: int | None = None

    @property
    def player(self) -> PlayerState:
        return self._player

    def set_player(self, player: PlayerState) -> None:
        self._player = player

    def set_monster_bands(
        self,
        weak: list[WorldObject],
        strong: list[WorldObject],
    ) -> None:
        """Replace weak/strong lists (called by world merge after entity apply)."""
        self._weak_monsters = list(weak)
        self._strong_monsters = list(strong)

    def upsert_object(self, obj: WorldObject) -> None:
        """Insert or replace a tracked object and mark it seen this frame."""
        self._objects[int(obj.track_id)] = obj
        self._missed_frames[int(obj.track_id)] = 0
        obj.last_seen = time.time()

    def touch_object(self, track_id: int) -> None:
        """Reset miss counter so aging does not drop the object."""
        tid = int(track_id)
        if tid in self._objects:
            self._missed_frames[tid] = 0
            self._objects[tid].last_seen = time.time()

    @property
    def world_state(self) -> WorldState:
        return WorldState(
            frame_id=self.frame_id,
            timestamp=self.timestamp,
            player=self._player,
            objects=dict(self._objects),
            weak_monsters=list(self._weak_monsters),
            strong_monsters=list(self._strong_monsters),
        )

    def missing_frames(self, track_id: int) -> int:
        return self._missed_frames.get(track_id, 0)

    def objects(self, kind: ObjectType) -> list[WorldObject]:
        return [obj for obj in self._objects.values() if obj.object_type is kind]

    def players(self) -> list[WorldObject]:
        return self.objects(ObjectType.PLAYER)

    def monsters(self) -> list[WorldObject]:
        return self.objects(ObjectType.MONSTER)

    def npcs(self) -> list[WorldObject]:
        return self.objects(ObjectType.NPC)

    def items(self) -> list[WorldObject]:
        return self.objects(ObjectType.ITEM)

    def weak_monsters(self) -> list[WorldObject]:
        return list(self._weak_monsters)

    def strong_monsters(self) -> list[WorldObject]:
        return list(self._strong_monsters)

    def all_objects(self) -> list[WorldObject]:
        return list(self._objects.values())

    def get_object(self, track_id: int) -> WorldObject | None:
        return self._objects.get(track_id)

    def nearest(
        self, kind: ObjectType, origin: Position | tuple[float, float]
    ) -> WorldObject | None:
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


__all__ = ["GameState"]
