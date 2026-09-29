"""Defines the core object structures for the World Data Module.

World Data answers "what exists in the game world right now?". It consumes
:class:`PerceptionObject` results produced by the Perception Module and
builds :class:`WorldObject` entities for the decision layer. No
classification, tracking, voting or image processing happens here.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Position:
    """A 2D position in the game world (units follow perception output)."""

    x: float
    y: float

    @classmethod
    def zero(cls) -> "Position":
        return cls(0.0, 0.0)


@dataclass(frozen=True)
class Velocity:
    """A 2D velocity, i.e. per-frame displacement (units follow perception)."""

    x: float
    y: float

    @classmethod
    def zero(cls) -> "Velocity":
        return cls(0.0, 0.0)


@dataclass(frozen=True)
class Size:
    """Bounding box size (units follow perception output)."""

    width: float
    height: float

    @classmethod
    def zero(cls) -> "Size":
        return cls(0.0, 0.0)


@dataclass(frozen=True)
class Identity:
    """Class/name identity of an object, resolved by the Perception Module."""

    name: str | None
    confidence: float

    @classmethod
    def unknown(cls) -> "Identity":
        return cls(None, 0.0)


class ObjectType(Enum):
    """Coarse 5-way object category."""

    PLAYER = "player"
    MONSTER = "monster"
    NPC = "npc"
    ITEM = "item"
    OTHER = "other"


class ObjectStatus(Enum):
    """Lifecycle / behavior status of a world object."""

    UNKNOWN = "unknown"
    ALIVE = "alive"
    MOVING = "moving"
    ATTACKING = "attacking"
    DEAD = "dead"


class Relationship(Enum):
    """Object relationship to the player."""

    SELF = "self"
    ALLY = "ally"
    NEUTRAL = "neutral"
    ENEMY = "enemy"


def _coerce_type(value: ObjectType | str) -> ObjectType:
    if isinstance(value, ObjectType):
        return value
    return ObjectType(value)


def _label_hold_key(
    object_type: ObjectType,
    detail: str | None,
    species_name: str | None = None,
) -> str:
    """Stable key for consecutive-frame label voting (prefer species)."""
    identity = (species_name or detail or "").strip().lower()
    return f"{object_type.value}:{identity}"


def _opt_cell(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PerceptionObject:
    """The completed perception result consumed by the World Data Module.

    Produced by the Perception Module (YOLO + tracker + classifier +
    temporal identity stabilization). The World Data Module mirrors its
    fields verbatim; it never re-classifies, re-tracks or re-scores.
    """

    track_id: int
    object_type: ObjectType | str
    position: Position
    velocity: Velocity = field(default_factory=Velocity.zero)
    identity: Identity | None = None
    size: Size | None = None
    label: str | None = None
    class_id: int | None = None
    yolo_conf: float = 0.0
    detail_classification: str | None = None
    detail_classification_confidence: float = 0.0
    species_name: str | None = None
    species_confidence: float = 0.0
    occluded: bool = False
    frames_lost: int = 0
    world_cx: int | None = None
    world_cy: int | None = None
    world_rx: int | None = None
    world_ry: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerceptionObject":
        """Load a perception result from a logged dict (replay support)."""
        pos = data["position"]
        vel = data.get("velocity") or {}
        ident = data.get("identity")
        size = data.get("size")
        return cls(
            track_id=int(data["track_id"]),
            object_type=data["object_type"],
            position=Position(x=float(pos["x"]), y=float(pos["y"])),
            velocity=Velocity(
                x=float(vel.get("x", 0.0)), y=float(vel.get("y", 0.0))
            ),
            identity=(
                Identity(
                    name=ident.get("name"),
                    confidence=float(ident.get("confidence", 0.0)),
                )
                if ident
                else None
            ),
            size=(
                Size(
                    width=float(size["width"]), height=float(size["height"])
                )
                if size
                else None
            ),
            label=data.get("label"),
            class_id=data.get("class_id"),
            yolo_conf=float(data.get("yolo_conf", 0.0)),
            detail_classification=data.get("detail_classification"),
            detail_classification_confidence=float(
                data.get("detail_classification_confidence", 0.0)
            ),
            species_name=data.get("species_name"),
            species_confidence=float(data.get("species_confidence", 0.0) or 0.0),
            occluded=bool(data.get("occluded", False)),
            frames_lost=int(data.get("frames_lost", 0)),
            world_cx=_opt_cell(data.get("world_cx")),
            world_cy=_opt_cell(data.get("world_cy")),
            world_rx=_opt_cell(data.get("world_rx")),
            world_ry=_opt_cell(data.get("world_ry")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict matching the perception result schema."""
        return _json_ready(asdict(self))


@dataclass
class WorldObject:
    """A structured entity in the game world, derived from perception.

    Identity, position, velocity and size mirror the latest
    :class:`PerceptionObject`. Decision-facing fields (status, threat level
    and relationship) are filled in by later stages, never by perception.
    """

    track_id: int
    object_type: ObjectType
    identity: Identity = field(default_factory=Identity.unknown)
    position: Position = field(default_factory=Position.zero)
    velocity: Velocity = field(default_factory=Velocity.zero)
    size: Size = field(default_factory=Size.zero)
    status: ObjectStatus = ObjectStatus.UNKNOWN
    relationship: Relationship = Relationship.NEUTRAL
    threat_level: float = 0.0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    label: str | None = None
    class_id: int | None = None
    yolo_conf: float = 0.0
    detail_classification: str | None = None
    detail_classification_confidence: float = 0.0
    species_name: str | None = None
    species_confidence: float = 0.0
    occluded: bool = False
    frames_lost: int = 0
    world_cx: int | None = None
    world_cy: int | None = None
    world_rx: int | None = None
    world_ry: int | None = None
    # Consecutive frames the (object_type, species/detail) label has been unchanged.
    label_hold_key: str | None = None
    label_hold_frames: int = 0

    @classmethod
    def from_perception(cls, perception: PerceptionObject) -> "WorldObject":
        """Build a world object by mirroring a completed perception result.

        No classification, voting or type mapping happens here: the
        Perception Module already resolved object type and identity.
        """
        now = time.time()
        obj_type = _coerce_type(perception.object_type)
        detail = perception.detail_classification
        species = perception.species_name
        key = _label_hold_key(obj_type, detail, species)
        return cls(
            track_id=perception.track_id,
            object_type=obj_type,
            identity=perception.identity or Identity.unknown(),
            position=perception.position,
            velocity=perception.velocity,
            size=perception.size or Size.zero(),
            label=perception.label,
            class_id=perception.class_id,
            yolo_conf=perception.yolo_conf,
            detail_classification=detail,
            detail_classification_confidence=perception.detail_classification_confidence,
            species_name=species,
            species_confidence=perception.species_confidence,
            occluded=perception.occluded,
            frames_lost=perception.frames_lost,
            world_cx=perception.world_cx,
            world_cy=perception.world_cy,
            world_rx=perception.world_rx,
            world_ry=perception.world_ry,
            first_seen=now,
            last_seen=now,
            label_hold_key=key,
            label_hold_frames=1,
        )

    def apply_perception(self, perception: PerceptionObject) -> None:
        """Refresh type/spatial/identity fields from a new perception result."""
        self.object_type = _coerce_type(perception.object_type)
        self.position = perception.position
        self.velocity = perception.velocity
        if perception.identity is not None:
            self.identity = perception.identity
        if perception.size is not None:
            self.size = perception.size
        if perception.label is not None:
            self.label = perception.label
        if perception.class_id is not None:
            self.class_id = perception.class_id
        self.yolo_conf = perception.yolo_conf
        if perception.detail_classification is not None:
            self.detail_classification = perception.detail_classification
        self.detail_classification_confidence = (
            perception.detail_classification_confidence
        )
        if perception.species_name is not None:
            self.species_name = perception.species_name
        self.species_confidence = perception.species_confidence
        self.occluded = perception.occluded
        self.frames_lost = perception.frames_lost
        self.world_cx = perception.world_cx
        self.world_cy = perception.world_cy
        self.world_rx = perception.world_rx
        self.world_ry = perception.world_ry
        self.last_seen = time.time()
        key = _label_hold_key(
            self.object_type, self.detail_classification, self.species_name
        )
        if key == self.label_hold_key:
            self.label_hold_frames += 1
        else:
            self.label_hold_key = key
            self.label_hold_frames = 1

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict (enums converted to strings) for logging."""
        return _json_ready(asdict(self))

    def distance_to(self, other: Position | WorldObject) -> float:
        """Distance to another position or WorldObject."""
        if isinstance(other, WorldObject):
            return distance(self.position, other.position)
        return distance(self.position, other)

    def distance_to_squared(self, other: Position | WorldObject) -> float:
        """Squared distance to another position or WorldObject."""
        if isinstance(other, WorldObject):
            return distance_squared(self.position, other.position)
        return distance_squared(self.position, other)


def _json_ready(value: Any) -> Any:
    """Recursively convert enums to strings so output is JSON-friendly."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value


# ==================================================
# GEOMETRY HELPERS (from Lineage_bot utils/geometry.py)
# ==================================================

def distance(pos1: Position, pos2: Position) -> float:
    """Euclidean distance between two positions."""
    dx = pos1.x - pos2.x
    dy = pos1.y - pos2.y
    return math.sqrt(dx * dx + dy * dy)


def distance_squared(pos1: Position, pos2: Position) -> float:
    """Squared Euclidean distance (avoids sqrt for comparisons)."""
    dx = pos1.x - pos2.x
    dy = pos1.y - pos2.y
    return dx * dx + dy * dy


def random_point(base: Position, radius: float = 0.1) -> Position:
    """Generate a random point near base within radius."""
    import random
    angle = random.uniform(0, 2 * math.pi)
    r = random.uniform(0, radius)
    return Position(
        x=base.x + r * math.cos(angle),
        y=base.y + r * math.sin(angle),
    )


def valid_random_point(
    minimap: Any,  # MiniMap placeholder
    last_direction: Position,
    radius: float = 0.1
) -> Position:
    """Generate a valid random point on minimap (placeholder)."""
    # In full implementation, check minimap occupancy grid
    # For now, return center-ish point
    return Position(x=0.5, y=0.5)


__all__ = [
    "Identity",
    "ObjectStatus",
    "ObjectType",
    "PerceptionObject",
    "Position",
    "Relationship",
    "Size",
    "Velocity",
    "WorldObject",
    "distance",
    "distance_squared",
    "random_point",
    "valid_random_point",
]
