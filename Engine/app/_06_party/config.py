"""Party-member knobs. Leader publishes the global farm policy; members apply it."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

_LOOT_ROLES = frozenset({"none", "responsible"})
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
    # Loot comes from the leader policy. The near radius is
    # ``farm.loot_max_tiles``: the leader walks that far, and every other
    # member loots their own piles inside it. Hunt and assist stay first.
    # Random ON: closest eligible member takes party drops.
    # Random OFF: ``responsible`` uses the wider engage radius and takes
    # every party pile, including a colleague's.
    # Members do not loot while the leader is moving.
    random_loot: bool = False
    loot_role: str = "none"
    farm_mode: str = "party"
    # From the leader policy. Turret only while the leader stands on a point.
    leader_mode: str = "moving"
    # Leader is standing only to wait for a seat. Keep the walking side line.
    formation_hold: bool = False
    # One leader tick: drop the sticky slot and pick a free seat again.
    formation_reform: bool = False
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
    # Leader supply. Counts below the mins start a buy or a ground drop.
    member_arrow_min: int = 300
    shopkeeper_arrow_min: int = 300
    # Fixed drop to a short member, and arrows bought on one shopkeeper trip.
    member_arrow_give: int = 100
    shopkeeper_arrow_buy: int = 200
    member_hp_min: int = 10
    shopkeeper_hp_min: int = 20
    member_hp_give: int = 10
    shopkeeper_hp_buy: int = 20
    member_depoison_min: int = 1
    shopkeeper_depoison_min: int = 2
    member_depoison_give: int = 1
    shopkeeper_depoison_buy: int = 5
    member_mp_min: int = 5
    shopkeeper_mp_min: int = 10
    member_mp_give: int = 5
    shopkeeper_mp_buy: int = 10
    # all = items until the weight line, then adena. adena = adena only.
    loot_pickup: str = "all"
    loot_weight_pct: int = 30
    # Party recovery. Used as soon as this character is in a party, including
    # before a leader policy. A policy replaces these. Solo settings are not read.
    member_heal_pct: int = 70
    member_potion_pct: int = 50
    mage_heal_pct: int = 80
    retreat_pct: int = 30
    mother_tree: bool = True
    talking_scroll: bool = True
    safe_zone: bool = True
    tree_hp_to_mp: bool = True
    tree_hp_to_mp_hp: int = 85
    tree_hp_to_mp_mp: int = 80
    tree_heal: bool = True
    tree_heal_hp: int = 40
    tree_heal_mp: int = 80

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
        lead_mode = str(self.leader_mode or "moving").strip().lower()
        if lead_mode not in LEADER_MODES:
            lead_mode = "moving"
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
            farm_mode=mode,
            leader_mode=lead_mode,
            formation_hold=bool(self.formation_hold),
            formation_reform=bool(self.formation_reform),
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
            member_arrow_min=max(0, min(9999, int(self.member_arrow_min))),
            shopkeeper_arrow_min=max(0, min(9999, int(self.shopkeeper_arrow_min))),
            member_arrow_give=max(1, min(9999, int(self.member_arrow_give))),
            shopkeeper_arrow_buy=max(1, min(999, int(self.shopkeeper_arrow_buy))),
            member_hp_min=max(0, min(9999, int(self.member_hp_min))),
            shopkeeper_hp_min=max(0, min(9999, int(self.shopkeeper_hp_min))),
            member_hp_give=max(1, min(9999, int(self.member_hp_give))),
            shopkeeper_hp_buy=max(1, min(999, int(self.shopkeeper_hp_buy))),
            member_depoison_min=max(0, min(9999, int(self.member_depoison_min))),
            shopkeeper_depoison_min=max(0, min(9999, int(self.shopkeeper_depoison_min))),
            member_depoison_give=max(1, min(9999, int(self.member_depoison_give))),
            shopkeeper_depoison_buy=max(1, min(999, int(self.shopkeeper_depoison_buy))),
            member_mp_min=max(0, min(9999, int(self.member_mp_min))),
            shopkeeper_mp_min=max(0, min(9999, int(self.shopkeeper_mp_min))),
            member_mp_give=max(1, min(9999, int(self.member_mp_give))),
            shopkeeper_mp_buy=max(1, min(999, int(self.shopkeeper_mp_buy))),
            loot_pickup=(
                "adena"
                if str(self.loot_pickup or "").strip().lower() == "adena"
                else "all"
            ),
            loot_weight_pct=max(1, min(100, int(self.loot_weight_pct))),
            member_heal_pct=_cfg_pct(self.member_heal_pct, 70),
            member_potion_pct=_cfg_pct(self.member_potion_pct, 50),
            mage_heal_pct=_cfg_pct(self.mage_heal_pct, 80),
            retreat_pct=_cfg_pct(self.retreat_pct, 30),
            mother_tree=_cfg_flag(self.mother_tree, True),
            talking_scroll=_cfg_flag(self.talking_scroll, True),
            safe_zone=_cfg_flag(self.safe_zone, True),
            tree_hp_to_mp=_cfg_flag(self.tree_hp_to_mp, True),
            tree_hp_to_mp_hp=_cfg_pct(self.tree_hp_to_mp_hp, 85),
            tree_hp_to_mp_mp=_cfg_pct(self.tree_hp_to_mp_mp, 80),
            tree_heal=_cfg_flag(self.tree_heal, True),
            tree_heal_hp=_cfg_pct(self.tree_heal_hp, 40),
            tree_heal_mp=_cfg_pct(self.tree_heal_mp, 80),
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
            # Party / solo farm stays this member's own setting.
            "farm_mode": self.farm_mode,
            "leader_mode": policy.get("leader_mode", self.leader_mode),
            "formation_hold": bool(policy.get("formation_hold", self.formation_hold)),
            "formation_reform": bool(policy.get("formation_reform", self.formation_reform)),
            "yard_half_w": policy.get("yard_half_w", self.yard_half_w),
            "yard_half_h": policy.get("yard_half_h", self.yard_half_h),
            "yard_scale_with_roster": policy.get(
                "yard_scale_with_roster", self.yard_scale_with_roster
            ),
            "party_size": policy.get("party_size", self.party_size),
            "seat_role": seat,
            "seat_index": seat_i,
            "member_arrow_min": policy.get("member_arrow_min", self.member_arrow_min),
            "shopkeeper_arrow_min": policy.get(
                "shopkeeper_arrow_min", self.shopkeeper_arrow_min
            ),
            "member_arrow_give": policy.get("member_arrow_give", self.member_arrow_give),
            "shopkeeper_arrow_buy": policy.get(
                "shopkeeper_arrow_buy", self.shopkeeper_arrow_buy
            ),
            "member_hp_min": policy.get("member_hp_min", self.member_hp_min),
            "shopkeeper_hp_min": policy.get("shopkeeper_hp_min", self.shopkeeper_hp_min),
            "member_hp_give": policy.get("member_hp_give", self.member_hp_give),
            "shopkeeper_hp_buy": policy.get("shopkeeper_hp_buy", self.shopkeeper_hp_buy),
            "member_depoison_min": policy.get(
                "member_depoison_min", self.member_depoison_min
            ),
            "shopkeeper_depoison_min": policy.get(
                "shopkeeper_depoison_min", self.shopkeeper_depoison_min
            ),
            "member_depoison_give": policy.get(
                "member_depoison_give", self.member_depoison_give
            ),
            "shopkeeper_depoison_buy": policy.get(
                "shopkeeper_depoison_buy", self.shopkeeper_depoison_buy
            ),
            "member_mp_min": policy.get("member_mp_min", self.member_mp_min),
            "shopkeeper_mp_min": policy.get("shopkeeper_mp_min", self.shopkeeper_mp_min),
            "member_mp_give": policy.get("member_mp_give", self.member_mp_give),
            "shopkeeper_mp_buy": policy.get("shopkeeper_mp_buy", self.shopkeeper_mp_buy),
            "loot_pickup": policy.get("loot_pickup", self.loot_pickup),
            "loot_weight_pct": policy.get("loot_weight_pct", self.loot_weight_pct),
            "member_heal_pct": policy.get("member_heal_pct", self.member_heal_pct),
            "member_potion_pct": policy.get(
                "member_potion_pct", self.member_potion_pct
            ),
            "mage_heal_pct": policy.get("mage_heal_pct", self.mage_heal_pct),
            "retreat_pct": policy.get("retreat_pct", self.retreat_pct),
            "mother_tree": policy.get("mother_tree", self.mother_tree),
            "talking_scroll": policy.get("talking_scroll", self.talking_scroll),
            "safe_zone": policy.get("safe_zone", self.safe_zone),
            "tree_hp_to_mp": policy.get("tree_hp_to_mp", self.tree_hp_to_mp),
            "tree_hp_to_mp_hp": policy.get(
                "tree_hp_to_mp_hp", self.tree_hp_to_mp_hp
            ),
            "tree_hp_to_mp_mp": policy.get(
                "tree_hp_to_mp_mp", self.tree_hp_to_mp_mp
            ),
            "tree_heal": policy.get("tree_heal", self.tree_heal),
            "tree_heal_hp": policy.get("tree_heal_hp", self.tree_heal_hp),
            "tree_heal_mp": policy.get("tree_heal_mp", self.tree_heal_mp),
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
            farm_mode=str(raw.get("farm_mode") or "party"),
            leader_mode=str(raw.get("leader_mode") or "moving"),
            formation_hold=bool(raw.get("formation_hold", False)),
            formation_reform=bool(raw.get("formation_reform", False)),
            yard_half_w=hw_i,
            yard_half_h=hh_i,
            yard_scale_with_roster=bool(raw.get("yard_scale_with_roster", True)),
            party_size=int(raw.get("party_size", 1) or 1),
            seat_role=str(raw.get("seat_role") or "member"),
            seat_index=si_i,
            member_arrow_min=_cfg_int(raw.get("member_arrow_min"), 300),
            shopkeeper_arrow_min=_cfg_int(raw.get("shopkeeper_arrow_min"), 300),
            member_arrow_give=_cfg_int(raw.get("member_arrow_give"), 100),
            shopkeeper_arrow_buy=_cfg_int(raw.get("shopkeeper_arrow_buy"), 200),
            member_hp_min=_cfg_int(raw.get("member_hp_min"), 10),
            shopkeeper_hp_min=_cfg_int(raw.get("shopkeeper_hp_min"), 20),
            member_hp_give=_cfg_int(raw.get("member_hp_give"), 10),
            shopkeeper_hp_buy=_cfg_int(raw.get("shopkeeper_hp_buy"), 20),
            member_depoison_min=_cfg_int(raw.get("member_depoison_min"), 1),
            shopkeeper_depoison_min=_cfg_int(raw.get("shopkeeper_depoison_min"), 2),
            member_depoison_give=_cfg_int(raw.get("member_depoison_give"), 1),
            shopkeeper_depoison_buy=_cfg_int(raw.get("shopkeeper_depoison_buy"), 5),
            member_mp_min=_cfg_int(raw.get("member_mp_min"), 5),
            shopkeeper_mp_min=_cfg_int(raw.get("shopkeeper_mp_min"), 10),
            member_mp_give=_cfg_int(raw.get("member_mp_give"), 5),
            shopkeeper_mp_buy=_cfg_int(raw.get("shopkeeper_mp_buy"), 10),
            loot_pickup=str(raw.get("loot_pickup") or "all"),
            loot_weight_pct=_cfg_int(raw.get("loot_weight_pct"), 30),
            member_heal_pct=_cfg_pct(raw.get("member_heal_pct"), 70),
            member_potion_pct=_cfg_pct(raw.get("member_potion_pct"), 50),
            mage_heal_pct=_cfg_pct(raw.get("mage_heal_pct"), 80),
            retreat_pct=_cfg_pct(raw.get("retreat_pct"), 30),
            mother_tree=_cfg_flag(raw.get("mother_tree", True), True),
            talking_scroll=_cfg_flag(raw.get("talking_scroll", True), True),
            safe_zone=_cfg_flag(raw.get("safe_zone", True), True),
            tree_hp_to_mp=_cfg_flag(raw.get("tree_hp_to_mp", True), True),
            tree_hp_to_mp_hp=_cfg_pct(raw.get("tree_hp_to_mp_hp"), 85),
            tree_hp_to_mp_mp=_cfg_pct(raw.get("tree_hp_to_mp_mp"), 80),
            tree_heal=_cfg_flag(raw.get("tree_heal", True), True),
            tree_heal_hp=_cfg_pct(raw.get("tree_heal_hp"), 40),
            tree_heal_mp=_cfg_pct(raw.get("tree_heal_mp"), 80),
        ).clamped()


def _cfg_pct(value: Any, default: int) -> int:
    """1–100. A missing value keeps the party default."""
    if value is None or str(value).strip() == "":
        return default
    try:
        return max(1, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _cfg_flag(value: Any, default: bool) -> bool:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _cfg_int(value: Any, default: int) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = ["FARM_MODES", "LEADER_MODES", "PartyMemberConfig"]
