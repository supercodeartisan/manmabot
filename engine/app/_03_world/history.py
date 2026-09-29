"""Historical logging for replay and dataset generation."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .objects import Position, Velocity, WorldObject


@dataclass
class ObjectObservation:
    """A single recorded observation of a world object at one frame."""

    track_id: int
    frame_id: int
    timestamp: float
    object_type: str
    position: Position
    velocity: Velocity
    identity: str | None
    identity_confidence: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Memory:
    """Stores historical information about objects and events.

    Records a per-frame observation of every tracked object plus world
    events, so sessions can be replayed, debugged and benchmarked from
    logged history (data-first principle). Purely a logger: identity
    resolution and classification live in the Perception Module.
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self.capacity = capacity
        self._observations: dict[int, deque[ObjectObservation]] = {}
        self._frame_log: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)

    def record_frame(
        self, frame_id: int, timestamp: float, objects: Iterable[WorldObject]
    ) -> None:
        """Record a frame: the snapshot plus one observation per object.

        Receives plain data (frame id, timestamp, objects) so Memory has no
        dependency on GameState or any other module.
        """
        objects = list(objects)
        self._frame_log.append(
            {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "objects": [obj.to_dict() for obj in objects],
            }
        )
        for obj in objects:
            self.record_object(obj, frame_id, timestamp)

    def record_object(self, obj: WorldObject, frame_id: int, timestamp: float) -> None:
        observation = ObjectObservation(
            track_id=obj.track_id,
            frame_id=frame_id,
            timestamp=timestamp,
            object_type=obj.object_type.value,
            position=obj.position,
            velocity=obj.velocity,
            identity=obj.identity.name,
            identity_confidence=obj.identity.confidence,
            status=obj.status.value,
        )
        self._observations.setdefault(
            obj.track_id, deque(maxlen=self.capacity)
        ).append(observation)

    def add_event(self, event_type: str, **payload: Any) -> None:
        """Record a world event (e.g. ``monster_died``, ``item_picked_up``)."""
        self._events.append({"type": event_type, "time": time.time(), **payload})

    def history(self, track_id: int) -> list[ObjectObservation]:
        """Full recorded history of one object, oldest first."""
        return list(self._observations.get(track_id, ()))

    def last_seen(self, track_id: int) -> ObjectObservation | None:
        history = self._observations.get(track_id)
        return history[-1] if history else None

    def forget(self, track_id: int) -> None:
        """Drop all history for an object."""
        self._observations.pop(track_id, None)

    def recent_frames(self, n: int = 10) -> list[dict[str, Any]]:
        """Last n frame snapshots, oldest first."""
        return list(self._frame_log)[-n:]

    def events(self, event_type: str | None = None) -> list[dict[str, Any]]:
        all_events = list(self._events)
        if event_type is None:
            return all_events
        return [event for event in all_events if event["type"] == event_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": list(self._frame_log),
            "objects": {
                str(track_id): [obs.to_dict() for obs in history]
                for track_id, history in self._observations.items()
            },
            "events": list(self._events),
        }