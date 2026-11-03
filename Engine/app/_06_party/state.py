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
    leader_ent: str = ""
    leader_guid: str = ""
    leader_track_id: Optional[int] = None
    leader_farming: bool = False
    leader_entity_visible: bool = False
    leader_same_map: bool = True
    leader_target_name: str = ""
    leader_target_guid: str = ""
    leader_target_ent: str = ""
    assist_track_id: Optional[int] = None
    # Mob this member started while the turret leader was idle. Kept until it
    # dies even if the leader begins an attack.
    own_hunt_id: Optional[int] = None
    assist_src: str = ""
    assist_name: str = ""
    tick: int = 0
    # Optional mapId from caller (MapSubsystem); None = unknown / skip check.
    local_map_id: Optional[int] = None
    # Last good PartySubsystem pose (brief glitch / 0,0 read → keep following).
    sticky_leader_tile: Optional[tuple[int, int]] = None
    sticky_leader_map_id: Optional[int] = None
    sticky_leader_pose_at: float = 0.0
    # Random cardinal stand beside the stopped leader (cleared when it walks).
    settle_stand: Optional[tuple[int, int]] = None
    settle_leader_tile: Optional[tuple[int, int]] = None
    settle_blocked: set[tuple[int, int]] = field(default_factory=set)
    # Walk steps to the leader from the follow field (None = no field).
    leader_walk_dist: Optional[int] = None
    # Reynolds formation offset (behind + flank) from the walking leader.
    travel_offset: Optional[tuple[int, int]] = None
    # Last travel click tile on the walk path (in-transit check).
    follow_hop: Optional[tuple[int, int]] = None
    # Turret radial seat around the leader; last seat that had no path.
    turret_seat: Optional[tuple[int, int]] = None
    turret_seat_bad: Optional[tuple[int, int]] = None
    # Moving-mode area reading, e.g. "narrow:trail_seat0" / "open:open_field".
    formation: str = ""
    # Extra bag for debug / UI.
    scratch: dict[str, Any] = field(default_factory=dict)

    def status_dict(self) -> dict[str, Any]:
        return {
            "chasing": self.chasing,
            "approach_goal": self.approach_goal,
            "settle_stand": self.settle_stand,
            "turret_seat": self.turret_seat,
            "formation": self.formation,
            "paused": self.paused,
            "last_reason": self.last_reason,
            "last_kind": self.last_kind,
            "leader_dist": self.leader_dist,
            "leader_walk_dist": self.leader_walk_dist,
            "leader_name_seen": self.leader_name_seen,
            "leader_source": self.leader_source,
            "leader_hp": self.leader_hp,
            "leader_mp": self.leader_mp,
            "leader_map_id": self.leader_map_id,
            "leader_ent": self.leader_ent,
            "leader_guid": self.leader_guid,
            "leader_track_id": self.leader_track_id,
            "leader_farming": self.leader_farming,
            "leader_entity_visible": self.leader_entity_visible,
            "leader_same_map": self.leader_same_map,
            "leader_in_ui": self.leader_entity_visible,
            "leader_target_name": self.leader_target_name,
            "leader_target_guid": self.leader_target_guid,
            "leader_target_ent": self.leader_target_ent,
            "assist_track_id": self.assist_track_id,
            "assist_src": self.assist_src,
            "assist_name": self.assist_name,
            "tick": self.tick,
            "local_map_id": self.local_map_id,
        }


__all__ = ["MemberRuntime"]
