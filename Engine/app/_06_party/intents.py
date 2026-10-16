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


def _occupied_tiles(game_state: Any, origin: Any) -> list[tuple[int, int]]:
    from app._02_state.objects import ObjectType
    from app._04_decision.combat_query import object_absolute_tile

    occupied: list[tuple[int, int]] = []
    for kind in (ObjectType.PLAYER, ObjectType.MONSTER, ObjectType.NPC):
        for obj in game_state.objects(kind):
            try:
                occupied.append(object_absolute_tile(obj, origin))
            except Exception:
                continue
    return occupied


def _plan_approach_hop(
    game_state: Any,
    origin: Any,
    target_tile: tuple[int, int],
    *,
    radius: int,
    previous_goal: Optional[tuple[int, int]],
    rng: random.Random,
    reason_prefix: str,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """Shared TRAVELING hop toward a stand tile near ``target_tile``."""
    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.pathfinding import plan_travel_click

    from .types import ActionIntent, ActionType

    terrain = get_terrain_map()
    if terrain is None:
        return idle("no_terrain"), None, "no_terrain"
    ox, oy = int(origin.x), int(origin.y)
    occupied = _occupied_tiles(game_state, origin)
    prev = previous_goal
    if prev == (ox, oy):
        prev = None
    goal = choose_approach_tile(
        terrain.is_walkable,
        target_tile,
        radius,
        occupied,
        rng,
        prev,
        prefer_near=(ox, oy),
    )
    if goal is None:
        return idle("no_approach_tile"), None, "no_approach_tile"
    if goal == (ox, oy):
        return idle("at_approach"), goal, "at_approach"
    if previous_goal == goal:
        try:
            from app._05_action.body_pose import body_is_moving

            if body_is_moving():
                return idle("follow_in_transit"), goal, "follow_in_transit"
        except Exception:
            pass
    dest, _path, waypoint = plan_travel_click(terrain, origin, goal)
    if dest is None:
        goal = choose_approach_tile(
            terrain.is_walkable,
            target_tile,
            radius,
            occupied,
            rng,
            None,
            exclude=(goal,),
            prefer_near=(ox, oy),
        )
        if goal is None:
            return idle("no_path"), None, "no_path"
        if goal == (ox, oy):
            return idle("at_approach"), goal, "at_approach"
        dest, _path, waypoint = plan_travel_click(terrain, origin, goal)
        if dest is None:
            return idle("no_path"), None, "no_path"
    hop = waypoint if waypoint is not None else goal
    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=dest,
        priority=0.55,
        reason=f"party_member:{reason_prefix} {goal[0]},{goal[1]}",
    )
    detail = f"hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail


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
    return _plan_approach_hop(
        game_state,
        origin,
        leader_tile,
        radius=int(config.approach_tiles),
        previous_goal=previous_goal,
        rng=rng,
        reason_prefix="follow",
    )


def plan_close_in_intent(
    game_state: Any,
    origin: Any,
    monster_tile: tuple[int, int],
    *,
    previous_goal: Optional[tuple[int, int]],
    rng: random.Random,
    radius: int = 1,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """Short hop toward the assist monster when out of attack range."""
    return _plan_approach_hop(
        game_state,
        origin,
        monster_tile,
        radius=max(1, int(radius)),
        previous_goal=previous_goal,
        rng=rng,
        reason_prefix="close_in",
    )


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
    close_in_tile: Optional[tuple[int, int]] = None,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    if kind is MemberKind.STOP:
        return idle(reason), previous_goal, reason
    if kind is MemberKind.WAIT:
        return idle(reason), previous_goal, reason
    if kind is MemberKind.JOIN_MAP:
        # Manager ticks PartyJoinNav directly; this is a safe fallback.
        return idle(reason or "join_map"), None, reason or "join_map"
    if kind is MemberKind.HOLD:
        return idle(reason), None, reason
    if kind is MemberKind.HEAL:
        # Manager returns blackboard HEAL intent directly; idle is a safe fallback.
        return idle(reason or "heal"), previous_goal, reason or "heal"
    if kind is MemberKind.BUFF:
        return idle(reason or "buff"), previous_goal, reason or "buff"
    if kind is MemberKind.POTION:
        return potion(reason), previous_goal, reason
    if kind is MemberKind.DEFEND and defend_id is not None:
        return attack(defend_id, reason), previous_goal, reason
    if kind is MemberKind.ASSIST and assist_id is not None:
        return attack(assist_id, reason), previous_goal, reason
    if kind is MemberKind.CLOSE_IN:
        if game_state is None or origin is None or close_in_tile is None:
            return idle("close_in_incomplete"), previous_goal, "close_in_incomplete"
        return plan_close_in_intent(
            game_state,
            origin,
            close_in_tile,
            previous_goal=previous_goal,
            rng=rng or random.Random(),
        )
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
    "plan_close_in_intent",
    "plan_follow_intent",
    "potion",
]
