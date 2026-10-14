"""Historical logging for replay and dataset generation."""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Iterable

from app._02_state.observation import ObjectObservation
from app._02_state.objects import WorldObject


class Memory:
    """Stores historical information about objects and events.

    Purely a logger: identity resolution and classification live elsewhere.
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self.capacity = capacity
        self._observations: dict[int, deque[ObjectObservation]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)

    def record(
        self,
        frame_id: int,
        objects: Iterable[WorldObject],
        timestamp: float | None = None,
    ) -> None:
        stamp = time.time() if timestamp is None else timestamp
        for obj in objects:
            obs = ObjectObservation(
                track_id=obj.track_id,
                frame_id=frame_id,
                timestamp=stamp,
                object_type=obj.object_type.value
                if hasattr(obj.object_type, "value")
                else str(obj.object_type),
                position=obj.position,
                velocity=obj.velocity,
                identity=obj.identity.name if obj.identity else None,
                identity_confidence=(
                    obj.identity.confidence if obj.identity else 0.0
                ),
                status=obj.status.value if hasattr(obj.status, "value") else str(obj.status),
            )
            bucket = self._observations.setdefault(
                obj.track_id, deque(maxlen=self.capacity)
            )
            bucket.append(obs)

    def record_event(self, event: dict[str, Any]) -> None:
        self._events.append(dict(event))

    def history(self, track_id: int) -> list[ObjectObservation]:
        return list(self._observations.get(track_id, ()))

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)


__all__ = ["Memory", "ObjectObservation"]
