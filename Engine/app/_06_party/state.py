"""Runtime member state (not the solo Blackboard)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemberRuntime:
    """Sticky chase / approach goal for one member session."""

    chasing: bool = False
    approach_goal: Optional[tuple[int, int]] = None
    paused: bool = False
    last_reason: str = ""
    last_kind: str = "stop"
    leader_dist: Optional[int] = None
    leader_name_seen: str = ""
    leader_source: str = ""
    leader_hp: Optional[int] = None
    leader_mp: Optional[int] = None
    leader_map_id: Optional[int] = None
    assist_track_id: Optional[int] = None
    tick: int = 0
    # Optional mapId from caller (MapSubsystem); None = unknown / skip check.
    local_map_id: Optional[int] = None
    # Extra bag for debug / UI.
    scratch: dict[str, Any] = field(default_factory=dict)

    def status_dict(self) -> dict[str, Any]:
        return {
            "chasing": self.chasing,
            "approach_goal": self.approach_goal,
            "paused": self.paused,
            "last_reason": self.last_reason,
            "last_kind": self.last_kind,
            "leader_dist": self.leader_dist,
            "leader_name_seen": self.leader_name_seen,
            "leader_source": self.leader_source,
            "leader_hp": self.leader_hp,
            "leader_mp": self.leader_mp,
            "leader_map_id": self.leader_map_id,
            "assist_track_id": self.assist_track_id,
            "tick": self.tick,
            "local_map_id": self.local_map_id,
        }


__all__ = ["MemberRuntime"]
