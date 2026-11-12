"""Pure member decision order (no I/O)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .config import PartyMemberConfig


class MemberKind(str, Enum):
    STOP = "stop"
    WAIT = "wait"
    HEAL = "heal"
    BUFF = "buff"
    POTION = "potion"
    DEFEND = "defend"
    JOIN_MAP = "join_map"
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
    # Entity sweep / current UI sees the leader (not only PartySubsystem pose).
    leader_in_ui: bool = True
    # Leader PartySubsystem mapId differs from local MapSubsystem mapId.
    leader_other_map: bool = False
    # Contested / AttackAction — leader is fighting.
    leader_farming: bool = False
    # Leader pose unchanged long enough (not farming) → settle to stop_tiles.
    leader_stopped: bool = False
    # Kept for callers; follow_kind ignores slot/stand (close on the leader).
    at_settle_stand: Optional[bool] = None
    at_travel_spot: Optional[bool] = None
    # Walk steps to the leader (bodies/walls count). Travel + settle bands only.
    leader_walk_dist: Optional[int] = None
    # Assist target exists but is outside the solo hunt range, so follow.
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
    # Tile is the 15s/45s cache, not a live party or entity pose.
    leader_pose_stale: bool = False
    # Chebyshev steps to this member's formation slot. None keeps the old
    # distance-to-leader band for callers that have no slot yet.
    slot_dist: Optional[int] = None
    # Hold when the member is inside this many tiles of the slot.
    # Stand passes 1 (a 3×3). A walking side slot stays at 0.
    slot_arrive: int = 0
    # Leader tile changed within the still window. Off-slot follow beats a new assist.
    leader_moving: bool = False
    # Already returning to the slot. Stays on until the member is within one tile.
    catch_up: bool = False


# Off the slot by this many tiles: defer a new hunt until back within one tile.
CATCH_UP_ENTER_TILES = 4
CATCH_UP_EXIT_TILES = 1


def formation_returning(slot_dist: Optional[int], *, latched: bool) -> bool:
    """True while this member is still walking back to the seat.

    Enter at ``CATCH_UP_ENTER_TILES``. Stay until the slot is within
    ``CATCH_UP_EXIT_TILES``. No slot keeps the previous latch. Assist and
    loot do not wait on this. A buff still does.
    """
    if slot_dist is None:
        return bool(latched)
    dist = int(slot_dist)
    if latched:
        return dist > CATCH_UP_EXIT_TILES
    return dist >= CATCH_UP_ENTER_TILES


@dataclass(frozen=True)
class PolicyResult:
    kind: MemberKind
    chasing: bool
    reason: str


def decide_policy(inp: PolicyInput) -> PolicyResult:
    """Member brain: heal/buff/potion, defend, assist, then follow/hold."""
    cfg = inp.config
    if inp.paused:
        return PolicyResult(MemberKind.STOP, False, "paused")
    if inp.dead:
        return PolicyResult(MemberKind.STOP, False, "dead")
    returning = formation_returning(inp.slot_dist, latched=bool(inp.catch_up))
    # Potion and self heal stay ahead of the walk back. A buff waits.
    if inp.need_heal:
        return PolicyResult(MemberKind.HEAL, False, "self_heal")
    if inp.need_buff and not returning:
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

    # Assist beats loot and follow. A leader step or a seat catch-up does not
    # defer it. Out of attack range still follows instead of closing in.
    if inp.assist_ready and not inp.need_combat_step:
        yard = "turret_" if cfg.turret_farm else ""
        out = "_out_of_yard" if cfg.turret_farm and not inp.target_in_yard else ""
        what = "solo_farm" if inp.solo_farm else "assist"
        return PolicyResult(
            MemberKind.ASSIST, False, f"{yard}{what}{out} dist={dist}"
        )

    # A cached tile is a clue, not a live follow goal.
    if inp.leader_pose_stale:
        return PolicyResult(
            MemberKind.WAIT,
            False,
            f"leader_pose_stale dist={dist}",
        )

    # On-screen and off-screen fresh poses share the stop/start band below.
    in_leash = dist <= int(cfg.assist_leash_tiles)

    # --- Leader turret mode: back into the yard ---
    if cfg.turret_farm and in_leash and not inp.in_farm_yard:
        return PolicyResult(
            MemberKind.FOLLOW,
            True,
            f"turret_rejoin_yard dist={dist}",
        )

    # Turret ring seat is not a walk goal: it pulled the member around the
    # leader. Idle hold is ``stop_tiles``. Yard rejoin stays above.

    # --- Combat leash: leader fighting but no live assist target yet ---
    if inp.leader_farming:
        if dist > int(cfg.assist_leash_tiles):
            return PolicyResult(
                MemberKind.FOLLOW,
                True,
                f"follow_combat_leash dist={dist}",
            )
        # Inside the stop band, stand. A side slot does not pull the member
        # around the leader. Outside it, follow the leader tile.
        if dist <= int(cfg.stop_tiles):
            return PolicyResult(
                MemberKind.HOLD,
                False,
                f"hold dist={dist}",
            )
        return PolicyResult(
            MemberKind.FOLLOW,
            True,
            f"follow_combat_near dist={dist}",
        )

    # --- Travel / idle ---
    # Chebyshev to the leader. A formation slot is not a walk goal.
    if dist <= int(cfg.stop_tiles):
        return PolicyResult(
            MemberKind.HOLD,
            False,
            f"hold dist={dist}",
        )
    walk = int(inp.leader_walk_dist) if inp.leader_walk_dist is not None else dist
    why = "follow_settle" if inp.leader_stopped else "follow_travel"
    return PolicyResult(
        MemberKind.FOLLOW,
        True,
        f"{why} walk={walk} dist={dist}",
    )


__all__ = [
    "CATCH_UP_ENTER_TILES",
    "CATCH_UP_EXIT_TILES",
    "MemberKind",
    "PolicyInput",
    "PolicyResult",
    "decide_policy",
    "formation_returning",
]
