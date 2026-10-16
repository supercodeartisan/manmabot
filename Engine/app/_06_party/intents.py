"""Build ActionIntent values for the member brain (reuses action executor)."""
from __future__ import annotations

import random
from typing import Any, Optional

from .config import PartyMemberConfig
from .follow import choose_approach_tile
from .policy import MemberKind


def idle(reason: str, *, priority: float = 0.0) -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.IDLE,
        priority=priority,
        reason=f"party_member:{reason}",
    )


def potion(reason: str = "self_potion") -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.USE_HP_POTION,
        priority=0.9,
        reason=f"party_member:{reason}",
    )


def attack(track_id: int, reason: str) -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.ATTACK,
        target_id=int(track_id),
        priority=0.85,
        reason=f"party_member:{reason}",
    )


def plan_follow_intent(
    game_state: Any,
    origin: Any,
    leader_tile: tuple[int, int],
    config: PartyMemberConfig,
    *,
    previous_goal: Optional[tuple[int, int]],
    rng: random.Random,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """TRAVELING hop toward a walkable cell near the leader."""
    from app._02_state.objects import ObjectType
    from app._04_decision.combat_query import object_absolute_tile
    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.pathfinding import plan_travel_click

    from .types import ActionIntent, ActionType

    terrain = get_terrain_map()
    if terrain is None:
        return idle("no_terrain"), None, "no_terrain"
    occupied: list[tuple[int, int]] = []
    for kind in (ObjectType.PLAYER, ObjectType.MONSTER, ObjectType.NPC):
        for obj in game_state.objects(kind):
            try:
                occupied.append(object_absolute_tile(obj, origin))
            except Exception:
                continue
    prev = previous_goal
    if prev == (int(origin.x), int(origin.y)):
        prev = None
    goal = choose_approach_tile(
        terrain.is_walkable,
        leader_tile,
        config.approach_tiles,
        occupied,
        rng,
        prev,
    )
    if goal is None:
        return idle("no_approach_tile"), None, "no_approach_tile"
    dest, _path, waypoint = plan_travel_click(terrain, origin, goal)
    if dest is None:
        goal = choose_approach_tile(
            terrain.is_walkable,
            leader_tile,
            config.approach_tiles,
            occupied,
            rng,
            None,
            exclude=(goal,),
        )
        if goal is None:
            return idle("no_path"), None, "no_path"
        dest, _path, waypoint = plan_travel_click(terrain, origin, goal)
        if dest is None:
            return idle("no_path"), None, "no_path"
    hop = waypoint if waypoint is not None else goal
    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=dest,
        priority=0.55,
        reason=f"party_member:follow {goal[0]},{goal[1]}",
    )
    detail = f"hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail


def intent_for_kind(
    kind: MemberKind,
    *,
    reason: str,
    game_state: Any = None,
    origin: Any = None,
    leader_tile: Optional[tuple[int, int]] = None,
    config: Optional[PartyMemberConfig] = None,
    previous_goal: Optional[tuple[int, int]] = None,
    rng: Optional[random.Random] = None,
    defend_id: Optional[int] = None,
    assist_id: Optional[int] = None,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    if kind is MemberKind.STOP:
        return idle(reason), previous_goal, reason
    if kind is MemberKind.WAIT:
        return idle(reason), previous_goal, reason
    if kind is MemberKind.HOLD:
        return idle(reason), None, reason
    if kind is MemberKind.POTION:
        return potion(reason), previous_goal, reason
    if kind is MemberKind.DEFEND and defend_id is not None:
        return attack(defend_id, reason), previous_goal, reason
    if kind is MemberKind.ASSIST and assist_id is not None:
        return attack(assist_id, reason), previous_goal, reason
    if kind is MemberKind.FOLLOW:
        if (
            game_state is None
            or origin is None
            or leader_tile is None
            or config is None
        ):
            return idle("follow_incomplete"), previous_goal, "follow_incomplete"
        return plan_follow_intent(
            game_state,
            origin,
            leader_tile,
            config,
            previous_goal=previous_goal,
            rng=rng or random.Random(),
        )
    return idle(reason), previous_goal, reason


__all__ = [
    "attack",
    "idle",
    "intent_for_kind",
    "plan_follow_intent",
    "potion",
]
