"""Pure member decision order (no I/O)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .config import PartyMemberConfig
from .follow import follow_kind


class MemberKind(str, Enum):
    STOP = "stop"
    WAIT = "wait"
    HEAL = "heal"
    BUFF = "buff"
    POTION = "potion"
    DEFEND = "defend"
    JOIN_MAP = "join_map"
    FOLLOW = "follow"
    CLOSE_IN = "close_in"  # short step toward assist target (out of range)
    ASSIST = "assist"
    HOLD = "hold"


@dataclass(frozen=True)
class PolicyInput:
    paused: bool
    dead: bool
    origin_ok: bool
    leader_present: bool
    leader_dist: Optional[int]
    chasing: bool
    need_potion: bool
    self_threat: bool
    assist_ready: bool
    config: PartyMemberConfig
    # Entity sweep / current UI sees the leader (not only PartySubsystem pose).
    leader_in_ui: bool = True
    # Leader PartySubsystem mapId differs from local MapSubsystem mapId.
    leader_other_map: bool = False
    # Contested / AttackAction — leader is fighting.
    leader_farming: bool = False
    # Leader pose unchanged long enough (not farming) → settle to stop_tiles.
    leader_stopped: bool = False
    # Stopped leader: on the locked cardinal stand? None = no stand available.
    at_settle_stand: Optional[bool] = None
    # Walking leader: within Arrive tolerance of formation slot? None = no slot.
    at_travel_spot: Optional[bool] = None
    # Walk steps to the leader (bodies/walls count). Travel + settle bands only.
    leader_walk_dist: Optional[int] = None
    # Assist target exists but outside attack/spell range → step closer.
    need_combat_step: bool = False
    # Solo farm: own target fights inside the assist leash, leader fight or not.
    solo_farm: bool = False
    # Turret yard: member / target currently inside the farm box.
    in_farm_yard: bool = True
    target_in_yard: bool = True
    # Same assist target as last tick (a fight already in progress).
    assist_sticky: bool = False
    # Turret: no live target and not on the radial seat around the leader.
    off_turret_seat: bool = False
    # In-place heal / buff already armed this tick (manager stashed the intent).
    need_heal: bool = False
    need_buff: bool = False


@dataclass(frozen=True)
class PolicyResult:
    kind: MemberKind
    chasing: bool
    reason: str


def decide_policy(inp: PolicyInput) -> PolicyResult:
    """Member brain: heal/buff/potion, then defend, travel, assist, hold."""
    cfg = inp.config
    if inp.paused:
        return PolicyResult(MemberKind.STOP, False, "paused")
    if inp.dead:
        return PolicyResult(MemberKind.STOP, False, "dead")
    # In-place HP before origin/travel: matches the old support early-return.
    if inp.need_heal:
        return PolicyResult(MemberKind.HEAL, False, "self_heal")
    if inp.need_buff:
        return PolicyResult(MemberKind.BUFF, False, "self_buff")
    if inp.need_potion:
        return PolicyResult(MemberKind.POTION, False, "self_potion")
    if not inp.origin_ok:
        return PolicyResult(MemberKind.WAIT, False, "waiting_origin")
    if cfg.defend_self and inp.self_threat:
        return PolicyResult(MemberKind.DEFEND, False, "defend_self")

    if inp.leader_other_map:
        return PolicyResult(MemberKind.JOIN_MAP, False, "leader_other_map")

    if not inp.leader_present or inp.leader_dist is None:
        return PolicyResult(MemberKind.WAIT, False, "leader_missing")

    dist = int(inp.leader_dist)

    # Lost from entity sweep: always walk to PartySubsystem pose (never idle HOLD).
    if not inp.leader_in_ui:
        return PolicyResult(
            MemberKind.FOLLOW,
            True,
            f"follow_off_ui dist={dist}",
        )

    in_leash = dist <= int(cfg.assist_leash_tiles)

    # --- Leader turret mode: back into the yard unless a fight holds us out ---
    # A fight already in progress may finish outside the yard; a new target
    # outside the yard does not pull a member that is already out.
    fighting_out = inp.assist_ready and (inp.assist_sticky or inp.target_in_yard)
    if cfg.turret_farm and in_leash and not inp.in_farm_yard and not fighting_out:
        return PolicyResult(
            MemberKind.FOLLOW,
            True,
            f"turret_rejoin_yard dist={dist}",
        )

    # --- Combat: party = the leader's target, solo = own target ---
    # assist_ready alone is enough (contested / print_state atk/tgt). Do not
    # require leader_farming — that flag can lag one tick behind the resolve.
    if inp.assist_ready and in_leash:
        yard = "turret_" if cfg.turret_farm else ""
        out = "_out_of_yard" if cfg.turret_farm and not inp.target_in_yard else ""
        if not inp.need_combat_step:
            what = "solo_farm" if inp.solo_farm else "assist"
            return PolicyResult(
                MemberKind.ASSIST, False, f"{yard}{what}{out} dist={dist}"
            )
        what = "solo_close_in" if inp.solo_farm else "close_in"
        return PolicyResult(
            MemberKind.CLOSE_IN, False, f"{yard}{what}{out} dist={dist}"
        )

    # --- Turret: idle members take their radial seat around the leader ---
    if cfg.turret_farm and in_leash and inp.off_turret_seat:
        return PolicyResult(
            MemberKind.FOLLOW,
            True,
            f"turret_seat dist={dist}",
        )

    # --- Combat leash: leader fighting but no live assist target yet ---
    if inp.leader_farming:
        if dist > int(cfg.assist_leash_tiles):
            return PolicyResult(
                MemberKind.FOLLOW,
                True,
                f"follow_combat_leash dist={dist}",
            )
        # Farming but no live target yet — keep near stop band.
        if dist > int(cfg.stop_tiles):
            return PolicyResult(
                MemberKind.FOLLOW,
                True,
                f"follow_combat_near dist={dist}",
            )
        return PolicyResult(
            MemberKind.HOLD,
            False,
            f"hold_combat dist={dist}",
        )

    # --- Travel / idle ---
    walk = int(inp.leader_walk_dist) if inp.leader_walk_dist is not None else dist
    band, chasing = follow_kind(
        walk,
        follow_tiles=cfg.follow_tiles,
        stop_tiles=cfg.stop_tiles,
        leader_farming=False,
        leader_stopped=bool(inp.leader_stopped),
        chasing=inp.chasing,
        at_settle_stand=inp.at_settle_stand,
        at_travel_spot=inp.at_travel_spot,
    )
    if band == "follow":
        why = "follow_settle" if inp.leader_stopped else "follow_travel"
        return PolicyResult(
            MemberKind.FOLLOW,
            chasing,
            f"{why} walk={walk} dist={dist}",
        )

    return PolicyResult(
        MemberKind.HOLD,
        False,
        f"hold walk={walk} dist={dist}",
    )


__all__ = ["MemberKind", "PolicyInput", "PolicyResult", "decide_policy"]
