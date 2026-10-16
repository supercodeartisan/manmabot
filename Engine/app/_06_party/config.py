"""Party-member knobs (leader mirror). Independent of solo schedule YAML."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

_LOOT_ROLES = frozenset({"none", "responsible"})


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
    # Never mother-tree / retreat / escape — party stays with the leader.
    potion_hp_ratio: float = 0.45
    use_hp_potion: bool = True
    # Hit monsters whose AttackAction targets me (survive without solo retreat).
    defend_self: bool = True
    # Prefer monsters striking the leader; never fall back to random nearest mob.
    assist_leader_strikes: bool = True
    # Optional external target (WS / operator); track_id or memory_ent.
    external_target_id: Optional[int] = None
    external_target_ent: str = ""
    # Loot: random_loot ON → every member may loot (no ownership gate).
    # random_loot OFF → loot_role none | responsible (ownership gate on).
    random_loot: bool = False
    loot_role: str = "none"

    # Legacy aliases for older callers / status dumps.
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
        follow = max(1, min(40, int(self.follow_tiles)))
        stop = max(0, min(follow, int(self.stop_tiles)))
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
        )

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
        ).clamped()


__all__ = ["PartyMemberConfig"]
