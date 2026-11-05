"""Build ActionIntent values for the member brain (reuses action executor)."""
from __future__ import annotations

import random
from typing import Any, Iterable, Optional

from .config import PartyMemberConfig
from .follow import choose_approach_tile, choose_settle_stand
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


def attack(track_id: int, reason: str, *, mid_act: bool = False) -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.ATTACK,
        target_id=int(track_id),
        priority=0.85,
        reason=f"party_member:{reason}",
        mid_act=bool(mid_act),
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
    return _plan_hop_to_goal(
        terrain,
        origin,
        goal,
        previous_goal=previous_goal,
        reason_prefix=reason_prefix,
        retry=lambda bad: choose_approach_tile(
            terrain.is_walkable,
            target_tile,
            radius,
            occupied,
            rng,
            None,
            exclude=(bad,),
            prefer_near=(ox, oy),
        ),
    )


def _plan_hop_to_goal(
    terrain: Any,
    origin: Any,
    goal: tuple[int, int],
    *,
    previous_goal: Optional[tuple[int, int]],
    reason_prefix: str,
    retry: Optional[Any] = None,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """TRAVELING click toward ``goal``; ``retry(bad_goal)`` picks another on no path."""
    from app._04_decision.pathfinding import plan_travel_click

    from .types import ActionIntent, ActionType

    ox, oy = int(origin.x), int(origin.y)
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
        if retry is None:
            return idle("no_path"), None, "no_path"
        goal = retry(goal)
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
    settle_stand: Optional[tuple[int, int]] = None,
    stand_reason: str = "follow_settle",
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """TRAVELING hop toward the leader; exact ``settle_stand`` tile when set."""
    if settle_stand is not None:
        from app._04_decision.nav_config import get_terrain_map

        terrain = get_terrain_map()
        if terrain is None:
            return idle("no_terrain"), None, "no_terrain"
        return _plan_hop_to_goal(
            terrain,
            origin,
            (int(settle_stand[0]), int(settle_stand[1])),
            previous_goal=previous_goal,
            reason_prefix=stand_reason,
        )
    return _plan_approach_hop(
        game_state,
        origin,
        leader_tile,
        radius=int(config.approach_tiles),
        previous_goal=previous_goal,
        rng=rng,
        reason_prefix="follow",
    )


def _travel_max_hop() -> int:
    from app._04_decision import player_mode as pm
    from app._04_decision.dungeon import dungeon_max_hop_tiles, is_dungeon_map

    if is_dungeon_map():
        return int(dungeon_max_hop_tiles())
    return int(pm.TRAVEL_MAX_HOP_TILES)


def plan_field_follow(
    field: Any,
    origin: Any,
    *,
    stop_steps: int,
    previous_goal: Optional[tuple[int, int]],
    previous_hop: Optional[tuple[int, int]],
) -> Optional[tuple[Any, Optional[tuple[int, int]], str, Optional[tuple[int, int]]]]:
    """TRAVELING click down the leader walk field (no A*).

    Returns ``(intent, goal, detail, hop)`` or ``None`` when the member is
    outside the field and the caller should fall back to A*.
    """
    from app._04_decision.pathfinding import select_click_waypoint, waypoint_to_content

    from .types import ActionIntent, ActionType

    ox, oy = int(origin.x), int(origin.y)
    path = field.descent((ox, oy), stop_steps=stop_steps)
    if not path:
        return None
    goal = path[-1]
    if goal == (ox, oy):
        return idle("at_approach"), goal, "at_approach", None
    # Keep walking the last click unless it is nearly reached or the goal moved.
    if (
        previous_goal == goal
        and previous_hop is not None
        and max(abs(previous_hop[0] - ox), abs(previous_hop[1] - oy)) > 1
    ):
        try:
            from app._05_action.body_pose import body_is_moving

            if body_is_moving():
                return (
                    idle("follow_in_transit"),
                    goal,
                    "follow_in_transit",
                    previous_hop,
                )
        except Exception:
            pass
    hop = select_click_waypoint(
        path, origin, terrain=field.terrain, max_hop=_travel_max_hop()
    )
    if hop is None:
        return None
    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=waypoint_to_content(hop, origin),
        priority=0.55,
        reason=f"party_member:follow_walk {goal[0]},{goal[1]}",
    )
    detail = f"walk {len(path) - 1} hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail, hop


def pick_settle_stand(
    game_state: Any,
    origin: Any,
    leader_tile: tuple[int, int],
    config: PartyMemberConfig,
    *,
    previous: Optional[tuple[int, int]],
    rng: random.Random,
    exclude: Iterable[tuple[int, int]] = (),
    field: Any = None,
) -> Optional[tuple[int, int]]:
    """Locked random up/down/left/right tile ``stop_tiles`` from a stopped leader.

    With ``field``, a stand also needs at most ``stop_tiles`` walk steps to
    the leader (a cardinal tile behind a wall is skipped).
    """
    from app._04_decision.nav_config import get_terrain_map

    from .follow import cardinal_tiles

    terrain = get_terrain_map()
    if terrain is None or game_state is None or origin is None:
        return None
    ox, oy = int(origin.x), int(origin.y)
    radius = max(1, int(config.stop_tiles))
    # Standing on the stand must not count as "occupied" by myself.
    occupied = [t for t in _occupied_tiles(game_state, origin) if t != (ox, oy)]
    skip = {(int(x), int(y)) for x, y in exclude}
    if field is not None:
        for tile in cardinal_tiles(leader_tile[0], leader_tile[1], radius):
            steps = field.steps(tile)
            if steps is None or steps > radius:
                skip.add(tile)
    return choose_settle_stand(
        terrain.is_walkable,
        leader_tile,
        radius,
        occupied,
        rng,
        previous,
        exclude=skip,
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
    settle_stand: Optional[tuple[int, int]] = None,
    stand_reason: str = "follow_settle",
    mid_act: bool = False,
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
        return attack(defend_id, reason, mid_act=mid_act), previous_goal, reason
    if kind is MemberKind.ASSIST and assist_id is not None:
        return attack(assist_id, reason, mid_act=mid_act), previous_goal, reason
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
            settle_stand=settle_stand,
            stand_reason=stand_reason,
        )
    return idle(reason), previous_goal, reason


__all__ = [
    "attack",
    "idle",
    "intent_for_kind",
    "pick_settle_stand",
    "plan_close_in_intent",
    "plan_field_follow",
    "plan_follow_intent",
    "potion",
]
