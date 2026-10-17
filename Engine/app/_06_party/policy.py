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


@dataclass(frozen=True)
class PolicyResult:
    kind: MemberKind
    chasing: bool
    reason: str


def decide_policy(inp: PolicyInput) -> PolicyResult:
    """Member brain: travel leash / stop settle / combat assist+step / hold."""
    cfg = inp.config
    if inp.paused:
        return PolicyResult(MemberKind.STOP, False, "paused")
    if inp.dead:
        return PolicyResult(MemberKind.STOP, False, "dead")
    if not inp.origin_ok:
        return PolicyResult(MemberKind.WAIT, False, "waiting_origin")
    if inp.need_potion:
        return PolicyResult(MemberKind.POTION, False, "self_potion")
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

    # --- Solo farm: hunt own target while the leader is within the leash ---
    if inp.solo_farm and inp.assist_ready and dist <= int(cfg.assist_leash_tiles):
        if inp.need_combat_step:
            return PolicyResult(
                MemberKind.CLOSE_IN,
                False,
                f"solo_close_in dist={dist}",
            )
        return PolicyResult(
            MemberKind.ASSIST,
            False,
            f"solo_farm dist={dist}",
        )

    # --- Party farm: attack the leader's target when resolved ---
    # assist_ready alone is enough (contested / print_state atk/tgt). Do not
    # require leader_farming — that flag can lag one tick behind the resolve.
    if (
        not inp.solo_farm
        and inp.assist_ready
        and dist <= int(cfg.assist_leash_tiles)
    ):
        if inp.need_combat_step:
            return PolicyResult(
                MemberKind.CLOSE_IN,
                False,
                f"close_in dist={dist}",
            )
        return PolicyResult(
            MemberKind.ASSIST,
            False,
            f"assist dist={dist}",
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
