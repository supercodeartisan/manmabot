"""Debug / replay observation rows (data only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app._02_state.objects import Position, Velocity


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


__all__ = ["ObjectObservation"]
