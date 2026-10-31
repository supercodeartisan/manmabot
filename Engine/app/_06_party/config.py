"""Party-member knobs. Leader publishes the global farm policy; members apply it."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

_LOOT_ROLES = frozenset({"none", "responsible"})
_LOOT_PRIORITIES = frozenset({"follow", "loot"})
# Member's own farm: party = attack the leader's target; solo = own mobs near leader.
FARM_MODES = ("party", "solo")
# Leader's global mode: turret = party holds a yard around the leader;
# moving = leader roams, members follow without a yard.
LEADER_MODES = ("turret", "moving")


@dataclass
class PartyMemberConfig:
    """Settings for one member bot that mirrors a leader."""

    enabled: bool = False
    # Optional sticky identity after memory resolve; empty = use party_listen leader.
    leader_name: str = ""
    leader_ent: str = ""
    leader_guid: str = ""
    leader_track_id: Optional[int] = None
    # Travel leash: chase when farther than this while leader is moving.
    follow_tiles: int = 8
    # Settle distance when leader is stopped / idle (Chebyshev).
    stop_tiles: int = 2
    # Empty tiles around leader to stand on (never the leader cell).
    approach_tiles: int = 2
    # Assist only while this close to the leader (Chebyshev).
    assist_leash_tiles: int = 10
    # Fallback HP potion when no blackboard (tests). Live: solo potion sides + heal.
    potion_hp_ratio: float = 0.45
    use_hp_potion: bool = True
    defend_self: bool = True
    assist_leader_strikes: bool = True
    external_target_id: Optional[int] = None
    external_target_ent: str = ""
    # Loot: random_loot ON → every member may loot (no ownership gate).
    # random_loot OFF → loot_role none | responsible (ownership gate on).
    random_loot: bool = False
    loot_role: str = "none"
    loot_priority: str = "follow"
    farm_mode: str = "party"
    # Set by the leader policy; turret until the leader says otherwise.
    leader_mode: str = "turret"
    # Turret yard half-extents (None = derive from party_size).
    yard_half_w: Optional[int] = None
    yard_half_h: Optional[int] = None
    yard_scale_with_roster: bool = True
    # Roster size hint from the leader (for yard scaling).
    party_size: int = 1
    # Seat from leader roster: member | mage | shopkeeper.
    seat_role: str = "member"
    # Position in the leader roster (turret radial seat); None = unknown.
    seat_index: Optional[int] = None

    @property
    def solo_farm(self) -> bool:
        return self.farm_mode == "solo"

    @property
    def turret_farm(self) -> bool:
        """Leader is in turret mode: stay inside the yard (party or solo)."""
        return self.leader_mode == "turret"

    @property
    def follow_start_tiles(self) -> int:
        return int(self.follow_tiles)

    @property
    def follow_stop_tiles(self) -> int:
        return int(self.stop_tiles)

    def clamped(self) -> "PartyMemberConfig":
        role = str(self.loot_role or "none").strip().lower()
        if role not in _LOOT_ROLES:
            role = "none"
        mode = str(self.farm_mode or "party").strip().lower()
        if mode not in FARM_MODES:
            mode = "party"
        lead_mode = str(self.leader_mode or "turret").strip().lower()
        if lead_mode not in LEADER_MODES:
            lead_mode = "turret"
        priority = str(self.loot_priority or "follow").strip().lower()
        if priority not in _LOOT_PRIORITIES:
            priority = "follow"
        seat = str(self.seat_role or "member").strip().lower()
        if seat not in ("member", "mage", "shopkeeper"):
            seat = "member"
        follow = max(1, min(40, int(self.follow_tiles)))
        stop = max(0, min(follow, int(self.stop_tiles)))
        hw = self.yard_half_w
        hh = self.yard_half_h
        if hw is not None:
            hw = max(1, min(8, int(hw)))
        if hh is not None:
            hh = max(1, min(8, int(hh)))
        return replace(
            self,
            enabled=bool(self.enabled),
            leader_name=str(self.leader_name or "").strip(),
            leader_ent=str(self.leader_ent or "").strip(),
            leader_guid=str(self.leader_guid or "").strip(),
            leader_track_id=self.leader_track_id,
            follow_tiles=follow,
            stop_tiles=stop,
            approach_tiles=max(1, min(8, int(self.approach_tiles))),
            assist_leash_tiles=max(1, min(40, int(self.assist_leash_tiles))),
            potion_hp_ratio=max(0.05, min(0.95, float(self.potion_hp_ratio))),
            use_hp_potion=bool(self.use_hp_potion),
            defend_self=bool(self.defend_self),
            assist_leader_strikes=bool(self.assist_leader_strikes),
            external_target_id=self.external_target_id,
            external_target_ent=str(self.external_target_ent or "").strip(),
            random_loot=bool(self.random_loot),
            loot_role=role,
            loot_priority=priority,
            farm_mode=mode,
            leader_mode=lead_mode,
            yard_half_w=hw,
            yard_half_h=hh,
            yard_scale_with_roster=bool(self.yard_scale_with_roster),
            party_size=max(1, min(20, int(self.party_size or 1))),
            seat_role=seat,
            seat_index=(
                None
                if self.seat_index is None
                else max(0, min(19, int(self.seat_index)))
            ),
        )

    def merge_leader_policy(
        self,
        policy: Any,
        *,
        self_name: str = "",
    ) -> "PartyMemberConfig":
        """Overlay global knobs from a leader ``party_policy`` body."""
        if not isinstance(policy, dict):
            return self.clamped()
        from .comms.orders import (
            loot_role_for_name,
            seat_index_for_name,
            seat_role_for_name,
        )

        roster = policy.get("roster")
        seat = self.seat_role
        seat_i = self.seat_index
        loot = str(policy.get("loot_role", self.loot_role) or self.loot_role)
        if self_name:
            seat = seat_role_for_name(roster, self_name)
            seat_i = seat_index_for_name(roster, self_name)
            if not bool(policy.get("random_loot", self.random_loot)):
                loot = loot_role_for_name(roster, self_name, default=loot)
        raw = {
            "enabled": self.enabled,
            "leader_name": self.leader_name,
            "leader_ent": self.leader_ent,
            "leader_guid": self.leader_guid,
            "leader_track_id": self.leader_track_id,
            # Movement distances stay the member's own (not leader policy).
            "follow_tiles": self.follow_tiles,
            "stop_tiles": self.stop_tiles,
            "approach_tiles": self.approach_tiles,
            "assist_leash_tiles": self.assist_leash_tiles,
            "potion_hp_ratio": self.potion_hp_ratio,
            "use_hp_potion": self.use_hp_potion,
            "defend_self": self.defend_self,
            "assist_leader_strikes": self.assist_leader_strikes,
            "external_target_id": self.external_target_id,
            "external_target_ent": self.external_target_ent,
            "random_loot": policy.get("random_loot", self.random_loot),
            "loot_role": loot,
            "loot_priority": policy.get("loot_priority", self.loot_priority),
            # Party / solo is the member's own choice; the leader sends turret / moving.
            "farm_mode": self.farm_mode,
            "leader_mode": policy.get("leader_mode", self.leader_mode),
            "yard_half_w": policy.get("yard_half_w", self.yard_half_w),
            "yard_half_h": policy.get("yard_half_h", self.yard_half_h),
            "yard_scale_with_roster": policy.get(
                "yard_scale_with_roster", self.yard_scale_with_roster
            ),
            "party_size": policy.get("party_size", self.party_size),
            "seat_role": seat,
            "seat_index": seat_i,
        }
        return self.from_mapping(raw)

    def with_knobs_from(self, other: "PartyMemberConfig") -> "PartyMemberConfig":
        """Keep this config's leader identity; take every policy knob from ``other``."""
        return replace(
            other,
            enabled=self.enabled,
            leader_name=self.leader_name,
            leader_ent=self.leader_ent,
            leader_guid=self.leader_guid,
            leader_track_id=self.leader_track_id,
            external_target_id=self.external_target_id,
            external_target_ent=self.external_target_ent,
        ).clamped()

    @classmethod
    def from_mapping(cls, raw: Any) -> "PartyMemberConfig":
        if raw is None:
            return cls().clamped()
        if isinstance(raw, cls):
            return raw.clamped()
        if not isinstance(raw, dict):
            return cls().clamped()
        tid = raw.get("leader_track_id")
        try:
            tid_i = int(tid) if tid is not None and str(tid).strip() != "" else None
        except (TypeError, ValueError):
            tid_i = None
        ext = raw.get("external_target_id")
        try:
            ext_i = int(ext) if ext is not None and str(ext).strip() != "" else None
        except (TypeError, ValueError):
            ext_i = None
        if "follow_tiles" in raw and raw.get("follow_tiles") is not None:
            follow = int(raw.get("follow_tiles", 8))
        elif "follow_start_tiles" in raw:
            follow = int(raw.get("follow_start_tiles", 8))
        else:
            follow = 8
        if "stop_tiles" in raw and raw.get("stop_tiles") is not None:
            stop = int(raw.get("stop_tiles", 2))
        elif "follow_stop_tiles" in raw:
            stop = int(raw.get("follow_stop_tiles", 2))
        else:
            stop = 2
        hw = raw.get("yard_half_w", None)
        hh = raw.get("yard_half_h", None)
        try:
            hw_i = int(hw) if hw is not None and str(hw).strip() != "" else None
        except (TypeError, ValueError):
            hw_i = None
        try:
            hh_i = int(hh) if hh is not None and str(hh).strip() != "" else None
        except (TypeError, ValueError):
            hh_i = None
        si = raw.get("seat_index", None)
        try:
            si_i = int(si) if si is not None and str(si).strip() != "" else None
        except (TypeError, ValueError):
            si_i = None
        return cls(
            enabled=bool(raw.get("enabled", False)),
            leader_name=str(raw.get("leader_name") or raw.get("leader") or ""),
            leader_ent=str(raw.get("leader_ent") or ""),
            leader_guid=str(raw.get("leader_guid") or ""),
            leader_track_id=tid_i,
            follow_tiles=follow,
            stop_tiles=stop,
            approach_tiles=int(raw.get("approach_tiles", 2)),
            assist_leash_tiles=int(raw.get("assist_leash_tiles", 10)),
            potion_hp_ratio=float(raw.get("potion_hp_ratio", 0.45)),
            use_hp_potion=bool(raw.get("use_hp_potion", True)),
            defend_self=bool(raw.get("defend_self", True)),
            assist_leader_strikes=bool(raw.get("assist_leader_strikes", True)),
            external_target_id=ext_i,
            external_target_ent=str(raw.get("external_target_ent") or ""),
            random_loot=bool(raw.get("random_loot", False)),
            loot_role=str(raw.get("loot_role") or "none"),
            loot_priority=str(raw.get("loot_priority") or "follow"),
            farm_mode=str(raw.get("farm_mode") or "party"),
            leader_mode=str(raw.get("leader_mode") or "turret"),
            yard_half_w=hw_i,
            yard_half_h=hh_i,
            yard_scale_with_roster=bool(raw.get("yard_scale_with_roster", True)),
            party_size=int(raw.get("party_size", 1) or 1),
            seat_role=str(raw.get("seat_role") or "member"),
            seat_index=si_i,
        ).clamped()


__all__ = ["FARM_MODES", "LEADER_MODES", "PartyMemberConfig"]
