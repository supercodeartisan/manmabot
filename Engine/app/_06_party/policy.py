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
    POTION = "potion"
    DEFEND = "defend"
    FOLLOW = "follow"
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


@dataclass(frozen=True)
class PolicyResult:
    kind: MemberKind
    chasing: bool
    reason: str


def decide_policy(inp: PolicyInput) -> PolicyResult:
    """Member brain ladder — mirrors PARTY_MEMBER_MVP decision order."""
    cfg = inp.config
    if inp.paused:
        return PolicyResult(MemberKind.STOP, False, "paused")
    if inp.dead:
        return PolicyResult(MemberKind.STOP, False, "dead")
    if not inp.origin_ok:
        return PolicyResult(MemberKind.WAIT, False, "waiting_origin")
    if not inp.leader_present or inp.leader_dist is None:
        return PolicyResult(MemberKind.WAIT, False, "leader_missing")
    if inp.need_potion:
        return PolicyResult(MemberKind.POTION, inp.chasing, "self_potion")
    if cfg.defend_self and inp.self_threat:
        return PolicyResult(MemberKind.DEFEND, inp.chasing, "defend_self")

    band, chasing = follow_kind(
        int(inp.leader_dist),
        follow_start=cfg.follow_start_tiles,
        follow_stop=cfg.follow_stop_tiles,
        chasing=inp.chasing,
    )
    if band == "follow":
        return PolicyResult(
            MemberKind.FOLLOW,
            chasing,
            f"follow dist={inp.leader_dist}",
        )

    # Near leader: assist only inside leash with a validated target.
    if inp.assist_ready and int(inp.leader_dist) <= int(cfg.assist_leash_tiles):
        return PolicyResult(
            MemberKind.ASSIST,
            chasing,
            f"assist dist={inp.leader_dist}",
        )
    return PolicyResult(
        MemberKind.HOLD,
        chasing,
        f"hold dist={inp.leader_dist}",
    )


__all__ = ["MemberKind", "PolicyInput", "PolicyResult", "decide_policy"]
