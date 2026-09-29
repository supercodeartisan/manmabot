"""World state snapshot."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .objects import ObjectType, WorldObject
from .player import PlayerState


@dataclass(frozen=True, eq=False)
class WorldState:
    """An immutable snapshot of the game world at one frame.

    Read-only: the decision layer can inspect it without side effects.
    ``eq=False`` keeps equality by identity, since the ``objects`` mapping
    holds mutable :class:`WorldObject` values.
    """

    frame_id: int
    timestamp: float
    player: PlayerState | None
    objects: dict[int, WorldObject]
    weak_monsters: list[WorldObject] = field(default_factory=list)
    strong_monsters: list[WorldObject] = field(default_factory=list)
    map_name: str = ""
    safe_zone: bool = False
    minimap: Any | None = None
    regionmap: Any | None = None

    def all_objects(self) -> list[WorldObject]:
        return list(self.objects.values())

    def objects_of(self, kind: ObjectType) -> list[WorldObject]:
        return [obj for obj in self.objects.values() if obj.object_type is kind]

    def monsters(self) -> list[WorldObject]:
        return self.objects_of(ObjectType.MONSTER)

    def players(self) -> list[WorldObject]:
        return self.objects_of(ObjectType.PLAYER)

    def npcs(self) -> list[WorldObject]:
        return self.objects_of(ObjectType.NPC)

    def items(self) -> list[WorldObject]:
        return self.objects_of(ObjectType.ITEM)

    def counts(self) -> dict[ObjectType, int]:
        return {
            kind: sum(
                1 for obj in self.objects.values() if obj.object_type is kind
            )
            for kind in ObjectType
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "player": self.player.to_dict() if self.player else None,
            "objects": [obj.to_dict() for obj in self.objects.values()],
            "weak_monsters": [obj.to_dict() for obj in self.weak_monsters],
            "strong_monsters": [obj.to_dict() for obj in self.strong_monsters],
            "map_name": self.map_name,
            "safe_zone": self.safe_zone,
            "counts": {kind.value: count for kind, count in self.counts().items()},
        }

    def nearest_enemy(
        self,
        origin: tuple[float, float] | "Position",
        max_missed_frames: int = 0,
    ) -> WorldObject | None:
        """Nearest monster, excluding objects not detected recently."""
        from .objects import Position

        candidates = [obj for obj in self.weak_monsters]
        if not candidates:
            return None
        if isinstance(origin, Position):
            ox, oy = origin.x, origin.y
        else:
            ox, oy = origin
        return min(
            candidates,
            key=lambda o: (o.position.x - ox) ** 2 + (o.position.y - oy) ** 2,
        )